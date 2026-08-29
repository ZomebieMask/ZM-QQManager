"""OneBot v11 (aiocqhttp) 协议端调用封装。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from astrbot.api import logger


def is_aiocqhttp(event) -> bool:
    """判断事件是否来自 aiocqhttp 协议端。"""
    try:
        return event.get_platform_name() == "aiocqhttp"
    except Exception:
        return False


def get_client(event):
    """取得协议端 client，非 aiocqhttp 返回 None。"""
    if not is_aiocqhttp(event):
        return None
    return getattr(event, "bot", None)


class OneBotApi:
    """把常用群管理动作包装成方法，统一异常与日志。"""

    def __init__(self, event):
        self.event = event
        self.client = get_client(event)

    @property
    def available(self) -> bool:
        return self.client is not None

    async def call(self, action: str, **payload: Any) -> Any:
        """调用协议端 API，失败时抛出 RuntimeError。"""
        if self.client is None:
            raise RuntimeError("当前平台不支持该操作，仅支持 QQ (aiocqhttp)")
        try:
            return await self.client.api.call_action(action, **payload)
        except Exception as exc:
            logger.error(f"[ZM-QQManager] 调用 {action} 失败: {exc}")
            raise RuntimeError(str(exc)) from exc

    async def try_call(self, action: str, **payload: Any) -> Optional[Any]:
        """调用协议端 API，失败返回 None（用于不应中断流程的场景）。"""
        try:
            return await self.call(action, **payload)
        except RuntimeError:
            return None

    async def mute(self, group_id: int, user_id: int, duration: int) -> None:
        """禁言成员，``duration`` 为 0 表示解除禁言。"""
        await self.call(
            "set_group_ban", group_id=int(group_id), user_id=int(user_id), duration=int(duration)
        )

    async def mute_all(self, group_id: int, enable: bool) -> None:
        """开启或关闭全体禁言。"""
        await self.call("set_group_whole_ban", group_id=int(group_id), enable=bool(enable))

    async def kick(self, group_id: int, user_id: int, reject: bool = False) -> None:
        await self.call(
            "set_group_kick",
            group_id=int(group_id),
            user_id=int(user_id),
            reject_add_request=bool(reject),
        )

    async def recall(self, message_id: Any) -> None:
        await self.call("delete_msg", message_id=message_id)

    async def set_admin(self, group_id: int, user_id: int, enable: bool) -> None:
        await self.call(
            "set_group_admin", group_id=int(group_id), user_id=int(user_id), enable=bool(enable)
        )

    async def set_title(self, group_id: int, user_id: int, title: str) -> None:
        await self.call(
            "set_group_special_title",
            group_id=int(group_id),
            user_id=int(user_id),
            special_title=title,
            duration=-1,
        )

    async def set_card(self, group_id: int, user_id: int, card: str) -> None:
        await self.call(
            "set_group_card", group_id=int(group_id), user_id=int(user_id), card=card
        )

    async def member_list(self, group_id: int) -> List[Dict[str, Any]]:
        result = await self.try_call("get_group_member_list", group_id=int(group_id))
        return result if isinstance(result, list) else []

    async def member_info(self, group_id: int, user_id: int) -> Dict[str, Any]:
        result = await self.try_call(
            "get_group_member_info", group_id=int(group_id), user_id=int(user_id), no_cache=True
        )
        return result if isinstance(result, dict) else {}

    async def group_list(self) -> List[Dict[str, Any]]:
        result = await self.try_call("get_group_list")
        return result if isinstance(result, list) else []

    async def send_group_msg(self, group_id: int, message: Any) -> Optional[Any]:
        return await self.try_call("send_group_msg", group_id=int(group_id), message=message)

    async def send_forward(self, group_id: int, nodes: List[Dict[str, Any]]) -> Optional[Any]:
        """发送合并转发消息。"""
        return await self.try_call(
            "send_group_forward_msg", group_id=int(group_id), messages=nodes
        )


def forward_node(user_id: str, nickname: str, content: str) -> Dict[str, Any]:
    """构造一条合并转发节点。"""
    return {
        "type": "node",
        "data": {
            "uin": str(user_id),
            "name": nickname or str(user_id),
            "content": [{"type": "text", "data": {"text": content}}],
        },
    }


async def resolve_member_name(api: OneBotApi, group_id: int, user_id: str) -> str:
    """尽力取得成员昵称，失败时退回 QQ 号。"""
    info = await api.member_info(group_id, int(user_id))
    return info.get("card") or info.get("nickname") or str(user_id)
