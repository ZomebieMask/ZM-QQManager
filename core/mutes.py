"""禁言记录：本地记录 + 协议端 shut_up_timestamp 校对。"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from .onebot import OneBotApi
from .store import JsonStore


class MuteTracker:
    """记录本插件发起的禁言，用于 /mutelist 展示原因与剩余时长。"""

    def __init__(self, store: JsonStore):
        self.store = store

    def _records(self, group_id: str) -> Dict[str, Any]:
        bucket = self.store.group(str(group_id))
        records = bucket.get("mutes")
        if not isinstance(records, dict):
            records = {}
            bucket["mutes"] = records
        return records

    async def record(
        self,
        group_id: str,
        user_id: str,
        duration: int,
        reason: str = "",
        operator: str = "",
    ) -> None:
        """写入一条禁言记录，``duration`` 为 0 表示永久。"""
        records = self._records(group_id)
        now = int(time.time())
        records[str(user_id)] = {
            "duration": int(duration),
            "start": now,
            "expire": 0 if duration <= 0 else now + int(duration),
            "reason": reason,
            "operator": str(operator),
        }
        await self.store.save()

    async def clear(self, group_id: str, user_id: str) -> None:
        records = self._records(group_id)
        if str(user_id) in records:
            records.pop(str(user_id), None)
            await self.store.save()

    def get(self, group_id: str, user_id: str) -> Optional[Dict[str, Any]]:
        return self._records(group_id).get(str(user_id))

    async def prune(self, group_id: str) -> None:
        """清掉已经到期的记录。"""
        records = self._records(group_id)
        now = int(time.time())
        expired = [
            uid
            for uid, item in records.items()
            if item.get("expire") and item["expire"] <= now
        ]
        for uid in expired:
            records.pop(uid, None)
        if expired:
            await self.store.save()

    async def list_muted(self, api: OneBotApi, group_id: str) -> List[Dict[str, Any]]:
        """汇总当前被禁言的成员。

        以协议端 ``shut_up_timestamp`` 为准；拿不到成员列表时退回本地记录。
        """
        await self.prune(group_id)
        now = int(time.time())
        records = self._records(group_id)
        members = await api.member_list(int(group_id))
        result: List[Dict[str, Any]] = []

        if members:
            for member in members:
                shut_up = member.get("shut_up_timestamp") or 0
                try:
                    shut_up = int(shut_up)
                except (TypeError, ValueError):
                    shut_up = 0
                if shut_up <= now:
                    continue

                uid = str(member.get("user_id"))
                local = records.get(uid, {})
                result.append(
                    {
                        "user_id": uid,
                        "name": member.get("card") or member.get("nickname") or uid,
                        "remaining": shut_up - now,
                        "reason": local.get("reason", ""),
                        "operator": local.get("operator", ""),
                        "source": "协议端",
                    }
                )
            result.sort(key=lambda item: item["remaining"], reverse=True)
            return result

        for uid, item in records.items():
            expire = item.get("expire") or 0
            if expire and expire <= now:
                continue
            result.append(
                {
                    "user_id": uid,
                    "name": uid,
                    "remaining": 0 if not expire else expire - now,
                    "reason": item.get("reason", ""),
                    "operator": item.get("operator", ""),
                    "source": "本地记录",
                }
            )
        result.sort(key=lambda item: item["remaining"], reverse=True)
        return result
