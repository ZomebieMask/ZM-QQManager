"""文件仓库：上传、临时下载链接、更新日志。"""
from __future__ import annotations

import asyncio
import re
import secrets
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from astrbot.api import logger

from .store import JsonStore, get_data_dir
from .utils import safe_name

MAX_CHANGELOG_ENTRIES = 200
DEFAULT_EXPIRED_TIP = "链接已失效"
DEFAULT_TTL = 600
DEFAULT_COOLDOWN = 300

# 只接受"点 + 字母数字"的扩展名，其余一律回退 .zip
_SUFFIX_RE = re.compile(r"^\.[A-Za-z0-9]{1,10}$")


def safe_suffix(original_name: str, source: Path) -> str:
    """从上传文件名里取出可信的扩展名。

    ``original_name`` 完全由上传方控制，``Path(...).suffix`` 可能带上
    ``\\``、``/``、``..`` 等分隔符（Windows 上会造成目录穿越），
    也可能长得离谱，所以这里只放行普通扩展名。
    """
    for candidate in (Path(original_name or "").suffix, source.suffix):
        if candidate and _SUFFIX_RE.match(candidate):
            return candidate
    return ".zip"


def safe_download_name(name: str) -> str:
    """清掉下载文件名里的控制字符与引号，避免污染响应头。"""
    cleaned = "".join(ch for ch in (name or "") if ch.isprintable())
    cleaned = cleaned.replace('"', "").replace("\\", "").strip()
    return cleaned or "download"


def files_dir() -> Path:
    path = get_data_dir() / "files"
    path.mkdir(parents=True, exist_ok=True)
    return path


class FileRepository:
    """管理上传的文件、下载令牌与 changelog。"""

    def __init__(self, store: JsonStore, config=None):
        self.store = store
        self.config = config or {}
        self.dir = files_dir()

    # ---------- 基础读写 ----------

    def _entries(self) -> Dict[str, Any]:
        entries = self.store.get("files")
        if not isinstance(entries, dict):
            entries = {}
            self.store.set("files", entries)
        return entries

    def _tokens(self) -> Dict[str, Any]:
        tokens = self.store.get("tokens")
        if not isinstance(tokens, dict):
            tokens = {}
            self.store.set("tokens", tokens)
        return tokens

    def _cooldowns(self) -> Dict[str, Any]:
        """{QQ号: 上次成功获取下载链接的时间戳}"""
        bucket = self.store.get("cooldowns")
        if not isinstance(bucket, dict):
            bucket = {}
            self.store.set("cooldowns", bucket)
        return bucket

    def get(self, name: str) -> Optional[Dict[str, Any]]:
        return self._entries().get(name)

    def names(self) -> List[str]:
        return sorted(self._entries().keys())

    # ---------- 上传 ----------

    async def save_upload(
        self,
        name: str,
        source_path: str,
        original_name: str,
        uploader: str,
        ttl: int,
    ) -> Tuple[bool, str]:
        """把协议端下载到的文件复制进插件仓库。"""
        clean = safe_name(name)
        if not clean:
            return False, "文件名不合法，仅允许中英文、数字、-、_、."

        source = Path(source_path)
        if not source.exists():
            return False, f"未找到待上传的文件: {source_path}"

        original_name = safe_download_name(original_name)
        suffix = safe_suffix(original_name, source)
        target = self.dir / f"{clean}{suffix}"
        # 双保险：落点必须仍在仓库目录内
        try:
            target.resolve().relative_to(self.dir.resolve())
        except ValueError:
            return False, "文件名不合法，已拒绝保存"

        try:
            await asyncio.to_thread(shutil.copy2, str(source), str(target))
        except Exception as exc:
            logger.error(f"[ZM-QQManager] 保存上传文件失败: {exc}")
            return False, f"保存文件失败: {exc}"

        entries = self._entries()
        existed = clean in entries
        entry = entries.get(clean) if existed else {}
        if not isinstance(entry, dict):
            entry = {}

        size = target.stat().st_size
        entry.update(
            {
                "name": clean,
                "path": str(target),
                "original_name": original_name,
                "size": size,
                "ttl": int(ttl),
                "uploader": str(uploader),
                "updated_at": int(time.time()),
                "version": entry.get("version", ""),
                "downloads": entry.get("downloads", 0),
            }
        )
        entry.setdefault("changelog", [])
        entries[clean] = entry
        await self.store.save()

        action = "更新" if existed else "上传"
        return True, f"{action}成功：{clean}（{format_size(size)}）"

    async def delete(self, name: str) -> Tuple[bool, str]:
        entries = self._entries()
        entry = entries.get(name)
        if not entry:
            return False, f"文件「{name}」不存在"

        path = Path(entry.get("path", ""))
        if path.exists():
            try:
                await asyncio.to_thread(path.unlink)
            except Exception as exc:
                logger.warning(f"[ZM-QQManager] 删除文件失败: {exc}")

        entries.pop(name, None)
        tokens = self._tokens()
        for token in [t for t, item in tokens.items() if item.get("name") == name]:
            tokens.pop(token, None)
        await self.store.save()
        return True, f"已删除文件「{name}」"

    # ---------- 下载令牌 ----------

    async def issue_token(self, name: str, requester: str) -> Tuple[Optional[str], str]:
        """为文件签发一次性临时令牌，返回 (下载链接, 提示)。"""
        entry = self.get(name)
        if not entry:
            return None, f"文件「{name}」不存在，可用 /file list 查看已上传文件"

        path = Path(entry.get("path", ""))
        if not path.exists():
            return None, f"文件「{name}」的本体已丢失，请管理员重新上传"

        ttl = int(entry.get("ttl") or DEFAULT_TTL)
        token = secrets.token_urlsafe(16)
        tokens = self._tokens()
        tokens[token] = {
            "name": name,
            "expire": int(time.time()) + ttl,
            "requester": str(requester),
        }

        entry["downloads"] = int(entry.get("downloads", 0)) + 1
        await self.prune_tokens()
        await self.store.save()

        return f"{self.base_url()}/download/{token}", ""

    def base_url(self) -> str:
        raw = str(self.config.get("file_base_url") or "").strip()
        if not raw:
            host = str(self.config.get("file_host") or "127.0.0.1").strip()
            port = self.config.get("file_port") or 9977
            raw = f"http://{host}:{port}"
        return raw.rstrip("/")

    def expired_tip(self) -> str:
        """链接失效时返回给浏览器的提示语，可在插件配置中自定义。"""
        return str(self.config.get("file_link_expired_tip") or DEFAULT_EXPIRED_TIP)

    def resolve_token(self, token: str) -> Tuple[Optional[Path], Optional[str], str]:
        """校验令牌，返回 (文件路径, 下载名, 错误信息)。"""
        tip = self.expired_tip()
        item = self._tokens().get(token)
        if not item:
            return None, None, tip
        if item.get("expire", 0) <= int(time.time()):
            return None, None, tip

        entry = self.get(item.get("name", ""))
        if not entry:
            return None, None, tip

        path = Path(entry.get("path", ""))
        if not path.exists():
            return None, None, tip

        # 旧数据里可能存着未清洗的文件名，出站前再过一遍
        download_name = safe_download_name(entry.get("original_name") or path.name)
        return path, download_name, ""

    # ---------- 下载冷却 ----------

    def cooldown_seconds(self) -> int:
        """下载冷却时长（秒），可在插件配置中自定义，0 表示不限制。"""
        try:
            value = int(self.config.get("file_download_cooldown", DEFAULT_COOLDOWN))
        except (TypeError, ValueError):
            return DEFAULT_COOLDOWN
        return max(0, value)

    def cooldown_remaining(self, user_id: str) -> int:
        """该成员距离下次可下载还剩多少秒，0 表示当前可以下载。"""
        cooldown = self.cooldown_seconds()
        if cooldown <= 0:
            return 0
        try:
            last = int(self._cooldowns().get(str(user_id), 0))
        except (TypeError, ValueError):
            return 0
        return max(0, last + cooldown - int(time.time()))

    async def mark_cooldown(self, user_id: str) -> None:
        """记录一次成功下载，开始计时。"""
        self._cooldowns()[str(user_id)] = int(time.time())
        await self.store.save()

    async def reset_cooldown(self, user_id: str) -> bool:
        """重置某成员的下载冷却，返回其原本是否处于冷却中。"""
        was_cooling = self.cooldown_remaining(user_id) > 0
        self._cooldowns().pop(str(user_id), None)
        await self.store.save()
        return was_cooling

    async def prune_tokens(self) -> None:
        tokens = self._tokens()
        now = int(time.time())
        expired = [t for t, item in tokens.items() if item.get("expire", 0) <= now]
        for token in expired:
            tokens.pop(token, None)

    # ---------- 更新日志 ----------

    async def add_changelog(
        self, name: str, version: str, contents: str, author: str
    ) -> Tuple[bool, str]:
        entry = self.get(name)
        if not entry:
            return False, f"文件「{name}」不存在，请先使用 /file upload 上传"

        changelog = entry.get("changelog")
        if not isinstance(changelog, list):
            changelog = []

        changelog.append(
            {
                "version": version,
                "contents": contents,
                "author": str(author),
                "time": int(time.time()),
            }
        )
        del changelog[:-MAX_CHANGELOG_ENTRIES]

        entry["changelog"] = changelog
        entry["version"] = version
        await self.store.save()
        return True, f"已记录「{name}」的更新日志，当前版本: {version}"

    def changelog(self, name: str, count: int) -> List[Dict[str, Any]]:
        """取最近 ``count`` 条更新日志，不足则全部返回（新的在前）。"""
        entry = self.get(name)
        if not entry:
            return []
        changelog = entry.get("changelog")
        if not isinstance(changelog, list) or not changelog:
            return []
        return list(reversed(changelog[-count:]))


def format_size(size: int) -> str:
    """把字节数格式化成可读大小。"""
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f}{unit}" if unit == "B" else f"{value:.2f}{unit}"
        value /= 1024
    return f"{value:.2f}GB"
