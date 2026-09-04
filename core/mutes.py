"""禁言记录：本地记录 + 协议端 shut_up_timestamp 校对。"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from .onebot import OneBotApi
from .store import JsonStore
from .utils import MUTE_CHUNK, RENEW_LEAD


def chunk_duration(duration: int) -> int:
    """把总时长切成一次 set_group_ban 能接受的长度。

    QQ 的 set_group_ban 最长 30 天，直接传 9999 天会被协议端拒掉
    （retcode 1200）。超过 30 天的部分靠到期前续期补上。
    """
    if duration <= 0:
        return 0
    return min(int(duration), MUTE_CHUNK)


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
        duration = int(duration)
        item = {
            "duration": duration,
            "start": now,
            "expire": 0 if duration <= 0 else now + duration,
            "reason": reason,
            "operator": str(operator),
        }
        if duration > MUTE_CHUNK:
            item["renew_at"] = now + MUTE_CHUNK - RENEW_LEAD
        records[str(user_id)] = item
        await self.store.save()

    def due_for_renew(self, now: Optional[int] = None) -> List[Dict[str, Any]]:
        """列出需要续期的长禁言，返回 ``[{group_id, user_id, remaining}]``。

        只有超过 30 天的禁言才会带 ``renew_at``，所以这里扫到的都是分段禁言。
        """
        now = int(now if now is not None else time.time())
        due: List[Dict[str, Any]] = []
        for group_id, bucket in self.store.items():
            if not isinstance(bucket, dict):
                continue
            records = bucket.get("mutes")
            if not isinstance(records, dict):
                continue
            for user_id, item in records.items():
                renew_at = item.get("renew_at") or 0
                expire = item.get("expire") or 0
                if not renew_at or renew_at > now or expire <= now:
                    continue
                due.append(
                    {
                        "group_id": str(group_id),
                        "user_id": str(user_id),
                        "remaining": expire - now,
                    }
                )
        return due

    async def mark_renewed(self, group_id: str, user_id: str) -> None:
        """续期成功后把下一次续期时间推后一个分段。"""
        item = self._records(group_id).get(str(user_id))
        if not item:
            return
        now = int(time.time())
        expire = item.get("expire") or 0
        item.pop("renew_fails", None)
        if expire - now <= MUTE_CHUNK:
            # 剩余时间已能一次性覆盖，不需要再续
            item.pop("renew_at", None)
        else:
            item["renew_at"] = now + MUTE_CHUNK - RENEW_LEAD
        await self.store.save()

    async def mark_renew_failed(
        self, group_id: str, user_id: str, limit: int = 3
    ) -> bool:
        """续期失败：退后 5 分钟重试，连续失败到上限就丢掉这条记录。

        最常见的失败原因是人早就退群了——那种情况下每分钟重试一次纯属刷日志。
        返回是否已放弃。
        """
        records = self._records(group_id)
        item = records.get(str(user_id))
        if not item:
            return True

        fails = int(item.get("renew_fails") or 0) + 1
        if fails >= limit:
            records.pop(str(user_id), None)
            await self.store.save()
            return True

        item["renew_fails"] = fails
        item["renew_at"] = int(time.time()) + 300
        await self.store.save()
        return False

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
