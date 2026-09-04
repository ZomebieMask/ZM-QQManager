"""时长解析、用户提取等通用工具。"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

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

# 单次禁言允许的最长时间：3650 天。QQ 自己只接受 30 天以内的 set_group_ban，
# 更长的时长由插件分段续期实现（见 MuteTracker.due_for_renew）。
MAX_DURATION = 3650 * 86400

# QQ 侧 set_group_ban 的上限，超过就返回 retcode 1200
MUTE_CHUNK = 30 * 86400

# 提前多久续期：留出余量，避免轮询间隔正好错过导致成员短暂解禁
RENEW_LEAD = 600


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


def escape_cq(text: str) -> str:
    """转义 CQ 码特殊字符。

    昵称、群名片、敏感词等内容会被拼进要发送的消息里，若原样保留 ``[`` ``]``，
    协议端会把 ``[CQ:at,qq=all]`` 之类的内容当成真正的 CQ 码执行。
    """
    return (
        (text or "")
        .replace("&", "&amp;")
        .replace("[", "&#91;")
        .replace("]", "&#93;")
    )


def truncate(text: str, limit: int = 60) -> str:
    """截断过长文本，便于写进提示与日志。"""
    text = (text or "").replace("\n", " ").strip()
    return text if len(text) <= limit else text[:limit] + "..."


# /group 的 [qq群号] 参数：单个群号，或用 - , ， 、 串起来的一批群号
_GROUP_IDS_RE = re.compile(r"\d{4,12}(?:[-,，、]\d{4,12})*")
_GROUP_IDS_SPLIT = re.compile(r"[-,，、]")
_HAS_SEPARATOR = re.compile(r"[-,，、]")

# 被引号包住的整段文字按原样取用，用于群名本身以数字结尾的场景
_QUOTED_RE = re.compile(r'^(["\'「“])(.*?)(["\'」”])(?=\s|$)', re.DOTALL)

# 刻意不收 1 / 0 / on / off：公告正文以数字结尾很常见
# （"报名截止 10:00 30"），把末位数字当成置顶开关会改错语义。
_TRUE_WORDS = {"true", "t", "yes", "y", "是", "置顶"}
_FALSE_WORDS = {"false", "f", "no", "n", "否", "不置顶"}


def parse_group_ids(token: str) -> Optional[List[str]]:
    """把 ``3366-1009-10032`` 解析成群号列表，不是群号串时返回 None。"""
    token = (token or "").strip()
    if not token or not _GROUP_IDS_RE.fullmatch(token):
        return None
    ids: List[str] = []
    for piece in _GROUP_IDS_SPLIT.split(token):
        if piece and piece not in ids:
            ids.append(piece)
    return ids


def split_trailing_group_ids(text: str) -> Tuple[str, Optional[List[str]]]:
    """从末尾切出 ``[qq群号]``，返回 ``(剩余文本, 群号列表)``。

    这里比 :func:`parse_group_ids` 更保守：末尾那一段只有在带分隔符
    （``3366-1009``）或至少 5 位数字时才算群号。否则 ``/g newname 老年活动
    中心 2025`` 里的年份会被误吞成群号。真要用数字结尾的群名就加引号：
    ``/g newname "老年活动中心 2025"``。
    """
    body = (text or "").strip()
    if not body:
        return "", None

    quoted = _QUOTED_RE.match(body)
    if quoted:
        return quoted.group(2).strip(), parse_group_ids(body[quoted.end():].strip())

    parts = body.rsplit(None, 1)
    if len(parts) == 2:
        tail = parts[1]
        if _HAS_SEPARATOR.search(tail) or len(tail) >= 5:
            ids = parse_group_ids(tail)
            if ids:
                return parts[0].strip(), ids
    return body, None


def parse_bool(token: str) -> Optional[bool]:
    """解析 true / false 参数，认不出返回 None。"""
    lowered = (token or "").strip().lower()
    if lowered in _TRUE_WORDS:
        return True
    if lowered in _FALSE_WORDS:
        return False
    return None


def split_trailing_bool(text: str) -> Tuple[str, Optional[bool]]:
    """从末尾切出 true/false，返回 ``(正文, 布尔值)``。

    正文可以是多行的（``rsplit`` 按任意空白切分），因此把 ``true`` 单独写在
    最后一行也能正确识别。末尾不是布尔值时返回 ``(原文, None)``。
    """
    body = (text or "").strip()
    if not body:
        return "", None

    parts = body.rsplit(None, 1)
    value = parse_bool(parts[-1])
    if value is None:
        return body, None
    # 整条消息只有一个 true/false 时，正文为空（图片可能在消息段里）
    return (parts[0].strip() if len(parts) == 2 else ""), value


def render_cq(template: str, values: Dict[str, str]) -> str:
    """把管理员写的提示语模板渲染成待发送的消息文本。

    模板由管理员编写，其中的 CQ 码原样保留（便于插入表情、图片）；但填进去
    的值里如果含成员可控内容（昵称等），调用方必须先自行 :func:`escape_cq`，
    否则一个叫 ``[CQ:at,qq=all]`` 的人就能借机器人之口 @ 全体。
    """
    text = template or ""
    for key, value in values.items():
        text = text.replace("{" + key + "}", str(value))
    return text


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
