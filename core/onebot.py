"""OneBot v11 (aiocqhttp) 协议端调用封装。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

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

    async def recall_detail(self, message_id: Any) -> Tuple[bool, str]:
        """撤回单条消息，返回 (是否成功, 失败原因)。"""
        try:
            await self.call("delete_msg", message_id=message_id)
            return True, ""
        except RuntimeError as exc:
            return False, str(exc)

    async def group_msg_history(self, group_id: int, count: int = 20) -> List[Dict[str, Any]]:
        """取群最近的聊天记录（旧 → 新），协议端不支持时返回空列表。

        各协议端对参数的要求不一致，逐个尝试：NapCat / Lagrange 接受
        count；go-cqhttp 需要 message_seq；个别实现只认 group_id。
        """
        attempts = (
            {"group_id": int(group_id), "count": int(count)},
            {"group_id": int(group_id), "message_seq": 0, "count": int(count)},
            {"group_id": int(group_id)},
        )
        for payload in attempts:
            result = await self.try_call("get_group_msg_history", **payload)
            messages: Any = None
            if isinstance(result, dict):
                messages = result.get("messages")
            elif isinstance(result, list):
                messages = result
            if isinstance(messages, list) and messages:
                return messages
        return []

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

    async def send_forward(
        self,
        group_id: int,
        nodes: List[Dict[str, Any]],
        source: Optional[str] = None,
        summary: Optional[str] = None,
        prompt: Optional[str] = None,
        news: Optional[List[Dict[str, str]]] = None,
    ) -> Optional[Any]:
        """发送合并转发消息。

        source/summary/prompt/news 用于自定义卡片外观（NapCat、Lagrange 等支持）：
        - source: 卡片标题，默认「群聊的聊天记录」
        - news:   卡片中间的摘要行
        - summary: 卡片底部「查看 N 条转发消息」
        - prompt: 会话列表里的外显文本，默认「[聊天记录]」
        协议端若不支持这些字段，会自动退回不带自定义样式的发送。
        """
        extra: Dict[str, Any] = {}
        if source:
            extra["source"] = source
        if news:
            extra["news"] = news
        if summary:
            extra["summary"] = summary
        if prompt:
            extra["prompt"] = prompt

        if extra:
            result = await self.try_call(
                "send_group_forward_msg",
                group_id=int(group_id),
                messages=nodes,
                **extra,
            )
            if result is not None:
                return result

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
