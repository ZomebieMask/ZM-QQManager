"""消息里图片的提取、下载与格式转换。

群头像、群公告、退群提示都要把用户发来的图片交给协议端。图片组件在不同
协议端上的形态差别很大（本地路径、file:// URI、http 链接、base64），这里
统一抽成"拿到 bytes"这一步，再由调用方决定用哪种写法喂给 OneBot API。
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import time
from pathlib import Path
from typing import Any, List, Optional, Tuple

from astrbot.api import logger

from .store import get_data_dir

# 群头像走协议端上传，过大的图片既慢又容易被直接拒掉
MAX_IMAGE_BYTES = 10 * 1024 * 1024

# 常见图片格式魔数，用来挡住"把别的文件当图片发"的情况
_MAGIC = (
    (b"\xff\xd8\xff", "jpg"),
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"GIF87a", "gif"),
    (b"GIF89a", "gif"),
    (b"BM", "bmp"),
)


def guess_image_ext(data: bytes) -> Optional[str]:
    """按魔数判断图片格式，认不出返回 None。"""
    for magic, ext in _MAGIC:
        if data.startswith(magic):
            return ext
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def extract_images(event) -> List[Any]:
    """取出消息里的全部图片组件，保持出现顺序。"""
    found: List[Any] = []
    try:
        segments = event.message_obj.message or []
    except AttributeError:
        return found
    for component in segments:
        if type(component).__name__ == "Image":
            found.append(component)
    return found


def _read_local(path_text: str) -> Optional[bytes]:
    """读取本地图片，路径不存在或过大时返回 None。"""
    try:
        path = Path(path_text)
        if not path.is_file():
            return None
        if path.stat().st_size > MAX_IMAGE_BYTES:
            raise ValueError(f"图片超过 {MAX_IMAGE_BYTES // 1024 // 1024}MB 上限")
        return path.read_bytes()
    except ValueError:
        raise
    except OSError:
        return None


async def _download(url: str) -> Optional[bytes]:
    """下载远程图片，边下边计字节数，避免超大响应把内存打满。"""
    try:
        import aiohttp
    except ImportError:
        logger.warning("[ZM-QQGroupmgr] 缺少 aiohttp 依赖，无法下载图片")
        return None

    timeout = aiohttp.ClientTimeout(total=30)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as response:
                if response.status != 200:
                    logger.warning(f"[ZM-QQGroupmgr] 下载图片失败 HTTP {response.status}: {url}")
                    return None
                chunks = []
                total = 0
                async for chunk in response.content.iter_chunked(64 * 1024):
                    total += len(chunk)
                    if total > MAX_IMAGE_BYTES:
                        raise ValueError(
                            f"图片超过 {MAX_IMAGE_BYTES // 1024 // 1024}MB 上限"
                        )
                    chunks.append(chunk)
                return b"".join(chunks)
    except ValueError:
        raise
    except Exception as exc:
        logger.warning(f"[ZM-QQGroupmgr] 下载图片失败: {exc}")
        return None


def _candidate_sources(component: Any) -> List[str]:
    """收集图片组件上所有可能指向图片内容的字段，按可靠性排序。"""
    sources: List[str] = []
    for attr in ("file", "file_", "url", "path"):
        value = getattr(component, attr, None)
        if isinstance(value, str) and value.strip() and value not in sources:
            sources.append(value.strip())
    return sources


async def image_bytes(component: Any) -> Tuple[Optional[bytes], str]:
    """把图片组件解析成原始字节，返回 ``(数据, 错误说明)``。"""
    sources = _candidate_sources(component)

    for source in sources:
        try:
            if source.startswith("base64://"):
                try:
                    return base64.b64decode(source[9:], validate=True), ""
                except (binascii.Error, ValueError):
                    continue

            if source.startswith(("http://", "https://")):
                data = await _download(source)
                if data:
                    return data, ""
                continue

            if source.startswith("file://"):
                # Windows 上是 file:///E:/x.png，去掉前缀后仍是合法路径
                local = source[7:]
                if local.startswith("/") and len(local) > 2 and local[2] == ":":
                    local = local[1:]
                data = await asyncio.to_thread(_read_local, local)
                if data:
                    return data, ""
                continue

            data = await asyncio.to_thread(_read_local, source)
            if data:
                return data, ""
        except ValueError as exc:
            return None, str(exc)

    # 新版 AstrBot 的 Image 组件自带下载方法，作为最后兜底
    converter = getattr(component, "convert_to_file_path", None)
    if callable(converter):
        try:
            path = await converter()
            data = await asyncio.to_thread(_read_local, str(path))
            if data:
                return data, ""
        except ValueError as exc:
            return None, str(exc)
        except Exception as exc:
            logger.warning(f"[ZM-QQGroupmgr] convert_to_file_path 失败: {exc}")

    return None, "未能读取图片内容，请重新发送图片（建议使用原图或本地文件）"


def to_base64_uri(data: bytes) -> str:
    """转成协议端认得的 ``base64://`` 写法。"""
    return "base64://" + base64.b64encode(data).decode("ascii")


def tmp_dir() -> Path:
    """临时图片目录，用于给只认路径的协议端提供落地文件。"""
    path = get_data_dir() / "tmp"
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_temp_image(data: bytes, ext: str) -> Optional[Path]:
    """把图片落到临时目录，供 ``file://`` 方式调用；失败返回 None。"""
    try:
        directory = tmp_dir()
        # 顺手清掉上次残留的临时图片，避免目录无限增长
        cutoff = time.time() - 3600
        for stale in directory.glob("img_*"):
            try:
                if stale.stat().st_mtime < cutoff:
                    stale.unlink()
            except OSError:
                pass
        path = directory / f"img_{int(time.time() * 1000)}.{ext}"
        path.write_bytes(data)
        # 必须给绝对路径：老版本 AstrBot 取不到数据目录时 get_data_dir()
        # 会退回相对路径 data/，相对路径既转不成 file:// URI，协议端也找不到
        return path.resolve()
    except OSError as exc:
        logger.warning(f"[ZM-QQGroupmgr] 写入临时图片失败: {exc}")
        return None


def file_candidates(data: bytes, ext: str) -> Tuple[List[str], Optional[Path]]:
    """生成喂给协议端的多种 ``file`` 写法，返回 ``(候选列表, 临时文件)``。

    各协议端支持度不一：NapCat / Lagrange 认 base64，部分实现只认本地路径，
    所以逐个试过去，谁能成就用谁。
    """
    candidates = [to_base64_uri(data)]
    temp = write_temp_image(data, ext)
    if temp is not None:
        try:
            candidates.append(temp.as_uri())
        except ValueError:
            # 拿不到合法 file:// URI 就只用裸路径，别让整条指令挂掉
            pass
        candidates.append(str(temp))
    return candidates, temp


def cleanup_temp(path: Optional[Path]) -> None:
    """删掉 :func:`file_candidates` 产生的临时文件，失败无所谓。"""
    if path is None:
        return
    try:
        path.unlink()
    except OSError:
        pass


def save_named_image(data: bytes, directory: Path, stem: str, ext: str) -> Optional[Path]:
    """把图片长期保存下来（退群提示图等），同名旧文件会被替换。"""
    try:
        directory.mkdir(parents=True, exist_ok=True)
        for old in directory.glob(f"{stem}.*"):
            try:
                old.unlink()
            except OSError:
                pass
        path = directory / f"{stem}.{ext}"
        path.write_bytes(data)
        return path
    except OSError as exc:
        logger.error(f"[ZM-QQGroupmgr] 保存图片失败: {exc}")
        return None
