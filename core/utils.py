"""时长解析、用户提取等通用工具。"""
from __future__ import annotations

import re
from typing import List, Optional

# 单位 -> 秒。同时接受英文缩写与中文写法。
_UNIT_SECONDS = {
    "s": 1, "sec": 1, "secs": 1, "second": 1, "seconds": 1, "秒": 1, "秒钟": 1,
    "m": 60, "min": 60, "mins": 60, "minute": 60, "minutes": 60, "分": 60, "分钟": 60,
    "h": 3600, "hr": 3600, "hour": 3600, "hours": 3600, "时": 3600, "小时": 3600,
    "d": 86400, "day": 86400, "days": 86400, "天": 86400, "日": 86400,
    "w": 604800, "week": 604800, "weeks": 604800, "周": 604800, "星期": 604800,
}

# 表示"永久"的写法。
_FOREVER = {"0", "永久", "forever", "perm", "permanent", "无限", "always"}

_SEGMENT_RE = re.compile(r"(\d+)\s*([A-Za-z一-鿿]*)")

MAX_DURATION = 365 * 86400


def parse_duration(text: str, default_unit: str = "m") -> Optional[int]:
    """把 ``10``、``3m``、``1h30m``、``2天`` 解析成秒数。

    不带单位时使用 ``default_unit``。返回 ``0`` 表示永久，``None`` 表示无法解析。
    """
    if not text:
        return None

    raw = text.strip().lower()
    if raw in _FOREVER:
        return 0

    total = 0
    matched = 0
    for match in _SEGMENT_RE.finditer(raw):
        value, unit = int(match.group(1)), match.group(2).strip()
        seconds = _UNIT_SECONDS.get(unit or default_unit)
        if seconds is None:
            return None
        total += value * seconds
        matched += 1

    if not matched:
        return None
    # 整段必须都是"数字+单位"，避免把 "abc12" 之类当成时长。
    if _SEGMENT_RE.sub("", raw).strip():
        return None
    return total


def format_duration(seconds: int) -> str:
    """把秒数格式化成 ``1天2小时3分钟`` 这种可读形式。"""
    if seconds <= 0:
        return "永久"

    units = (("天", 86400), ("小时", 3600), ("分钟", 60), ("秒", 1))
    parts: List[str] = []
    remaining = int(seconds)
    for label, size in units:
        if remaining >= size:
            parts.append(f"{remaining // size}{label}")
            remaining %= size
    return "".join(parts) or "0秒"


def extract_user_ids(event) -> List[str]:
    """取出消息里 @ 到的所有 QQ 号，保持出现顺序且去重。"""
    found: List[str] = []
    try:
        segments = event.message_obj.message or []
    except AttributeError:
        return found

    for segment in segments:
        qq = getattr(segment, "qq", None)
        if qq is None or type(segment).__name__ != "At":
            continue
        qq = str(qq)
        if qq not in found:
            found.append(qq)
    return found


def extract_targets(event, text: str) -> List[str]:
    """综合 @ 与纯 QQ 号，解析命令里的目标成员。"""
    targets = extract_user_ids(event)
    for number in re.findall(r"\b(\d{5,12})\b", text or ""):
        if number not in targets:
            targets.append(number)
    return targets


def normalize(text: str) -> str:
    """归一化文本，削弱插入符号、空格、大小写造成的绕过。"""
    if not text:
        return ""
    lowered = text.lower()
    return re.sub(r"[\s​‌‍\-_.*·、,，。!！?？~—+/\\|]+", "", lowered)


def truncate(text: str, limit: int = 60) -> str:
    """截断过长文本，便于写进提示与日志。"""
    text = (text or "").replace("\n", " ").strip()
    return text if len(text) <= limit else text[:limit] + "..."


def safe_name(name: str) -> Optional[str]:
    """校验文件名，只允许中英文、数字与 ``-_.``，避免路径穿越。"""
    if not name:
        return None
    name = name.strip()
    if name in {".", ".."} or len(name) > 64:
        return None
    if not re.fullmatch(r"[\w一-鿿.\-]+", name):
        return None
    return name
