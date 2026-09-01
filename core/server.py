"""提供临时下载链接的轻量 HTTP 服务。"""
from __future__ import annotations

from typing import Optional

from astrbot.api import logger

from .files import FileRepository


class DownloadServer:
    """只暴露 ``/download/<token>`` 一个入口，凭令牌下载文件。

    令牌一次签发、限时有效，除此之外不开放任何目录浏览或列表接口。
    """

    def __init__(self, repo: FileRepository, host: str = "0.0.0.0", port: int = 9977):
        self.repo = repo
        self.host = host
        self.port = int(port)
        self._runner = None
        self._site = None

    async def start(self) -> Optional[str]:
        """启动服务，成功返回 None，失败返回错误信息。"""
        if self._runner is not None:
            return None

        try:
            from aiohttp import web
        except ImportError:
            return "缺少 aiohttp 依赖，文件下载服务未启动"

        async def handle_download(request):
            token = request.match_info.get("token", "")
            path, download_name, error = self.repo.resolve_token(token)
            if error:
                return web.Response(status=404, text=_error_page(error), content_type="text/html")

            return web.FileResponse(
                path=str(path),
                headers={
                    "Content-Disposition": (
                        f'attachment; filename="{_ascii_fallback(download_name)}"; '
                        f"filename*=UTF-8''{_quote(download_name)}"
                    )
                },
            )

        async def handle_root(_request):
            return web.Response(text="ZM-QQGroupmgr file service", content_type="text/plain")

        app = web.Application()
        app.router.add_get("/", handle_root)
        app.router.add_get("/download/{token}", handle_download)

        try:
            self._runner = web.AppRunner(app, access_log=None)
            await self._runner.setup()
            self._site = web.TCPSite(self._runner, self.host, self.port)
            await self._site.start()
        except Exception as exc:
            logger.error(f"[ZM-QQGroupmgr] 文件下载服务启动失败: {exc}")
            await self.stop()
            return f"文件下载服务启动失败: {exc}"

        logger.info(f"[ZM-QQGroupmgr] 文件下载服务已启动于 {self.host}:{self.port}")
        return None

    async def stop(self) -> None:
        if self._site is not None:
            try:
                await self._site.stop()
            except Exception:
                pass
            self._site = None
        if self._runner is not None:
            try:
                await self._runner.cleanup()
            except Exception:
                pass
            self._runner = None


def _error_page(message: str) -> str:
    """把提示语渲染成一个极简页面，避免浏览器显示成裸文本。"""
    from html import escape

    return (
        "<!doctype html><html lang=\"zh-CN\"><meta charset=\"utf-8\">"
        "<title>ZM-QQGroupmgr</title>"
        "<body style=\"margin:0;display:flex;align-items:center;justify-content:center;"
        "height:100vh;font-family:system-ui,sans-serif;color:#333\">"
        f"<div style=\"font-size:20px\">{escape(message)}</div></body></html>"
    )


def _quote(text: str) -> str:
    from urllib.parse import quote

    return quote(text or "download", safe="")


def _ascii_fallback(text: str) -> str:
    """给不支持 filename* 的客户端准备一个纯 ASCII 名字。

    同时剔除控制字符（含 CR/LF）与引号，避免文件名污染响应头。
    """
    fallback = (text or "download").encode("ascii", "ignore").decode("ascii")
    fallback = "".join(ch for ch in fallback if 0x20 <= ord(ch) < 0x7F)
    return fallback.replace('"', "").replace("\\", "").strip() or "download"
