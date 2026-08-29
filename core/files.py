"""文件仓库：上传、临时下载链接、更新日志。"""
from __future__ import annotations

import asyncio
import secrets
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from astrbot.api import logger

from .store import JsonStore, get_data_dir
from .utils import safe_name

MAX_CHANGELOG_ENTRIES = 200


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

        suffix = Path(original_name).suffix or source.suffix or ".zip"
        target = self.dir / f"{clean}{suffix}"

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

        ttl = int(entry.get("ttl") or 3600)
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

    def resolve_token(self, token: str) -> Tuple[Optional[Path], Optional[str], str]:
        """校验令牌，返回 (文件路径, 下载名, 错误信息)。"""
        item = self._tokens().get(token)
        if not item:
            return None, None, "链接无效"
        if item.get("expire", 0) <= int(time.time()):
            return None, None, "链接已过期"

        entry = self.get(item.get("name", ""))
        if not entry:
            return None, None, "文件已被删除"

        path = Path(entry.get("path", ""))
        if not path.exists():
            return None, None, "文件已被删除"

        download_name = entry.get("original_name") or path.name
        return path, download_name, ""

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
