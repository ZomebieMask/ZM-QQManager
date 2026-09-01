"""等待管理员后续消息（补发图片、是/否确认）的会话状态。

``/group pp``、``/broadcast``、``/bye image`` 都是两步指令：先记下意图，再
等下一条消息把图片或答复补上。状态只放内存，插件重载即失效，这是刻意的
——重载后再让机器人干等一张图片没有意义。
"""
from __future__ import annotations

import secrets
import time
from typing import Any, Dict, Optional

# 同时挂起的会话上限，防止字典被反复触发指令撑大
MAX_PENDING = 200


def session_key(event) -> str:
    """同一个人在不同群 / 私聊里的待办互不干扰。"""
    return f"{event.get_group_id() or 'private'}:{event.get_sender_id()}"


class PendingRegistry:
    """按会话保存一份待续状态，超时自动失效。"""

    def __init__(self, ttl: int = 60):
        self.ttl = max(5, int(ttl))
        self._items: Dict[str, Dict[str, Any]] = {}

    def put(self, key: str, **payload: Any) -> str:
        """登记一条待办，返回用于超时校验的 token。

        token 的作用：超时任务只应作废"自己那一次"登记。管理员在 60 秒内
        重新执行了指令的话，旧任务醒来时不能把新登记一起清掉。
        """
        self.prune()
        if len(self._items) >= MAX_PENDING and key not in self._items:
            oldest = min(self._items, key=lambda k: self._items[k]["created"])
            self._items.pop(oldest, None)

        token = secrets.token_hex(8)
        item = dict(payload)
        item["created"] = time.time()
        item["token"] = token
        self._items[key] = item
        return token

    def peek(self, key: str) -> Optional[Dict[str, Any]]:
        item = self._items.get(key)
        if item is None:
            return None
        if time.time() - item["created"] > self.ttl:
            self._items.pop(key, None)
            return None
        return item

    def take(self, key: str) -> Optional[Dict[str, Any]]:
        item = self.peek(key)
        if item is not None:
            self._items.pop(key, None)
        return item

    def drop(self, key: str) -> None:
        self._items.pop(key, None)

    def drop_if(self, key: str, token: str) -> bool:
        """仅当 token 对得上时删除，返回是否真的删掉了。"""
        item = self._items.get(key)
        if item is None or item.get("token") != token:
            return False
        self._items.pop(key, None)
        return True

    def prune(self) -> None:
        now = time.time()
        for key in [k for k, v in self._items.items() if now - v["created"] > self.ttl]:
            self._items.pop(key, None)

    def clear(self) -> None:
        self._items.clear()
