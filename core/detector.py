"""刷屏检测与广告评分。"""
from __future__ import annotations

import re
import time
from collections import defaultdict, deque
from typing import Deque, Dict, Optional, Tuple

from .utils import normalize

# 广告检测关键词与权重
AD_PHRASES = [
    "加微信", "加QQ", "加群", "进群", "私聊", "联系方式",
    "代理", "招代理", "诚招", "兼职", "赚钱", "日入",
    "月入", "收益", "盈利", "稳赚", "零投资", "高回报",
    "包教包会", "一对一", "免费领", "限时优惠", "打折",
    "低价", "便宜", "清仓", "促销", "秒杀",
]

AD_CONTACT_PATTERNS = [
    r"[vVwW][xX][:：]?\s*[a-zA-Z0-9_-]{5,}",
    r"[qQ]{1,2}[:：]?\s*[0-9]{5,}",
    r"微信[:：]?\s*[a-zA-Z0-9_-]{5,}",
]

AD_PHONE_PATTERN = r"1[3-9]\d{9}"
AD_URL_PATTERN = r"https?://[^\s]+"
AD_PROMO_WORDS = ["优惠", "折扣", "特价", "限时", "抢购", "包邮"]

_CONTACT_RE = [re.compile(p) for p in AD_CONTACT_PATTERNS]
_PHONE_RE = re.compile(AD_PHONE_PATTERN)
_URL_RE = re.compile(AD_URL_PATTERN)


def ad_score(text: str) -> int:
    """按多种广告特征累加评分。"""
    if not text:
        return 0

    score = 0
    for phrase in AD_PHRASES:
        if phrase in text:
            score += 3
    for pattern in _CONTACT_RE:
        if pattern.search(text):
            score += 4
    if _PHONE_RE.search(text):
        score += 3
    if _URL_RE.search(text):
        score += 2
    for word in AD_PROMO_WORDS:
        if word in text:
            score += 2
    return score


class FloodDetector:
    """滑动窗口刷屏检测：短时间内消息过多，或连续重复同一内容。"""

    def __init__(self, threshold: int = 5, window: int = 10, repeat_limit: int = 3):
        self.threshold = max(2, threshold)
        self.window = max(1, window)
        self.repeat_limit = max(2, repeat_limit)
        self._timestamps: Dict[Tuple[str, str], Deque[float]] = defaultdict(deque)
        self._recent: Dict[Tuple[str, str], Deque[str]] = defaultdict(deque)

    def configure(self, threshold: int, window: int, repeat_limit: int) -> None:
        self.threshold = max(2, threshold)
        self.window = max(1, window)
        self.repeat_limit = max(2, repeat_limit)

    def record(self, group_id: str, user_id: str, text: str) -> Optional[str]:
        """记录一条消息，触发刷屏时返回原因，否则返回 None。"""
        key = (str(group_id), str(user_id))
        now = time.time()

        stamps = self._timestamps[key]
        stamps.append(now)
        while stamps and now - stamps[0] > self.window:
            stamps.popleft()

        history = self._recent[key]
        squeezed = normalize(text)
        if squeezed:
            history.append(squeezed)
            while len(history) > self.repeat_limit:
                history.popleft()

        if len(stamps) >= self.threshold:
            count = len(stamps)
            stamps.clear()
            history.clear()
            return f"{self.window} 秒内发送 {count} 条消息"

        if (
            squeezed
            and len(history) >= self.repeat_limit
            and len(set(history)) == 1
        ):
            history.clear()
            return f"连续重复发送同一内容 {self.repeat_limit} 次"

        return None

    def reset(self, group_id: str, user_id: Optional[str] = None) -> None:
        """清理计数，用于关闭功能或成员退群。"""
        group_id = str(group_id)
        if user_id is None:
            for key in [k for k in self._timestamps if k[0] == group_id]:
                self._timestamps.pop(key, None)
                self._recent.pop(key, None)
            return
        key = (group_id, str(user_id))
        self._timestamps.pop(key, None)
        self._recent.pop(key, None)


class CardCache:
    """记录已检查过的群名片，避免每条消息都重复判定。"""

    def __init__(self, max_size: int = 5000):
        self.max_size = max_size
        self._seen: Dict[Tuple[str, str], str] = {}

    def should_check(self, group_id: str, user_id: str, card: str) -> bool:
        key = (str(group_id), str(user_id))
        if self._seen.get(key) == card:
            return False
        if len(self._seen) >= self.max_size:
            self._seen.clear()
        self._seen[key] = card
        return True

    def forget(self, group_id: str, user_id: str) -> None:
        self._seen.pop((str(group_id), str(user_id)), None)
