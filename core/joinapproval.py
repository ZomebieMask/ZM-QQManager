"""进群审批：验证码生成与 GitHub commit sha 查询。"""
from __future__ import annotations

import re
import secrets
import string
import time
from typing import Dict, Optional, Tuple

from astrbot.api import logger

# /join_approval set verification_code <类型>
CODE_NUMBER = "number"
CODE_LETTER = "letter"
CODE_MIX = "mix"
CODE_SHA = "sha"
CODE_TYPES = (CODE_NUMBER, CODE_LETTER, CODE_MIX, CODE_SHA)

CODE_TYPE_LABELS = {
    CODE_NUMBER: "纯数字",
    CODE_LETTER: "6 位英文字母",
    CODE_MIX: "数字 + 6 位英文字母",
    CODE_SHA: "GitHub 仓库最新 commit 的 sha",
}

# letter 固定 6 位，number / mix 的位数由插件配置决定
LETTER_COUNT = 6
VALID_DIGITS = (4, 6)

# 校验 sha 时允许只发前缀（GitHub 页面上默认只显示前 7 位）
MIN_SHA_PREFIX = 7

# 等待验证的最长分钟数与 sha 轮询的最大间隔，跟插件配置的上限一致
MAX_VERIFY_MINUTES = 30
MAX_POLL_MINUTES = 9999

_REPO_URL_RE = re.compile(
    r"^(?:https?://)?(?:www\.)?github\.com[/:]([\w.-]+)/([\w.-]+?)(?:\.git)?/?$",
    re.IGNORECASE,
)
_REPO_SLUG_RE = re.compile(r"^([\w.-]+)/([\w.-]+?)(?:\.git)?$")


def make_code(code_type: str, digits: int = 6) -> str:
    """生成一个验证码。

    用 ``secrets`` 而不是 ``random``：验证码是踢人与否的唯一依据，
    可预测的伪随机数等于没有验证。
    """
    digits = digits if digits in VALID_DIGITS else 6
    if code_type == CODE_NUMBER:
        return "".join(secrets.choice(string.digits) for _ in range(digits))
    if code_type == CODE_LETTER:
        return "".join(secrets.choice(string.ascii_uppercase) for _ in range(LETTER_COUNT))
    if code_type == CODE_MIX:
        pool = [secrets.choice(string.digits) for _ in range(digits)]
        pool += [secrets.choice(string.ascii_uppercase) for _ in range(LETTER_COUNT)]
        # 打乱顺序，否则 "1234ABCDEF" 的前后两段一眼就能猜出规律
        for i in range(len(pool) - 1, 0, -1):
            j = secrets.randbelow(i + 1)
            pool[i], pool[j] = pool[j], pool[i]
        return "".join(pool)
    raise ValueError(f"未知的验证码类型: {code_type}")


def code_matches(expected: str, answer: str, is_sha: bool = False) -> bool:
    """比对成员发来的内容与期望的验证码，忽略大小写与两侧空白。

    sha 允许只发前缀：GitHub 网页上默认只显示前 7 位，要求成员翻出完整
    40 位反而是刁难。
    """
    expected = (expected or "").strip().lower()
    answer = (answer or "").strip().lower()
    if not expected or not answer:
        return False
    # compare_digest 对含非 ASCII 字符的 str 会直接抛 TypeError，而 answer 是
    # 群里任何人随便发的一句话，先挡掉再比
    if not expected.isascii() or not answer.isascii():
        return False
    if not is_sha:
        if len(expected) != len(answer):
            return False
        return secrets.compare_digest(expected, answer)
    if len(answer) < MIN_SHA_PREFIX or len(answer) > len(expected):
        return False
    return secrets.compare_digest(expected[: len(answer)], answer)


def is_sha_text(text: str) -> bool:
    """判断一句话是不是「看起来像 commit sha」。

    只有像 sha 的消息才值得为它去问一次 GitHub，否则待验证成员随便聊两句
    就能把 API 配额刷光。
    """
    text = (text or "").strip()
    return bool(re.fullmatch(r"[0-9a-fA-F]{%d,40}" % MIN_SHA_PREFIX, text))


def parse_repo(text: str) -> Optional[str]:
    """把 GitHub 仓库链接或 ``owner/name`` 解析成 ``owner/name``。"""
    text = (text or "").strip().strip("<>")
    if not text:
        return None
    for pattern in (_REPO_URL_RE, _REPO_SLUG_RE):
        match = pattern.match(text)
        if match:
            return f"{match.group(1)}/{match.group(2)}"
    return None


class ShaCache:
    """按仓库缓存最新 commit sha，缓存时长即“每隔多少分钟查一次”。"""

    def __init__(self):
        self._items: Dict[str, Tuple[float, str]] = {}

    async def latest(
        self, repo: str, ttl: int = 300, force: bool = False
    ) -> Tuple[str, str]:
        """返回 ``(sha, 错误说明)``，成功时错误为空串。"""
        cached = self._items.get(repo)
        if cached and not force and time.time() - cached[0] < max(1, ttl):
            return cached[1], ""

        sha, error = await _fetch_latest_sha(repo)
        if not sha:
            # 拉取失败时宁可用旧值：GitHub 偶发 5xx 不该让整群卡住
            if cached:
                logger.warning(f"[ZM-QQGroupmgr] {repo} sha 刷新失败（{error}），沿用缓存")
                return cached[1], ""
            return "", error
        self._items[repo] = (time.time(), sha)
        return sha, ""


async def _fetch_latest_sha(repo: str) -> Tuple[str, str]:
    try:
        import aiohttp
    except ImportError:
        return "", "缺少 aiohttp 依赖，无法查询 GitHub"

    url = f"https://api.github.com/repos/{repo}/commits?per_page=1"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "ZM-QQGroupmgr",
    }
    try:
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=headers) as response:
                if response.status == 404:
                    return "", f"仓库 {repo} 不存在或不是公开仓库"
                if response.status == 403:
                    return "", "GitHub API 限流（未认证请求每小时 60 次），请稍后再试"
                if response.status != 200:
                    return "", f"GitHub 返回 HTTP {response.status}"
                payload = await response.json(content_type=None)
    except Exception as exc:
        return "", f"查询 GitHub 失败: {exc}"

    if not isinstance(payload, list) or not payload:
        return "", f"仓库 {repo} 还没有 commit"
    sha = str((payload[0] or {}).get("sha") or "")
    if not sha:
        return "", "GitHub 返回的数据里没有 sha"
    return sha, ""


async def latest_release_tag(repo: str) -> Tuple[str, str]:
    """取仓库最新 release 的 tag（去掉前缀 v），返回 ``(版本号, 错误)``。"""
    try:
        import aiohttp
    except ImportError:
        return "", "缺少 aiohttp 依赖"

    url = f"https://api.github.com/repos/{repo}/releases/latest"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "ZM-QQGroupmgr",
    }
    try:
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=headers) as response:
                if response.status != 200:
                    return "", f"GitHub 返回 HTTP {response.status}"
                payload = await response.json(content_type=None)
    except Exception as exc:
        return "", f"查询最新版本失败: {exc}"

    tag = str((payload or {}).get("tag_name") or "").strip()
    if not tag:
        return "", "最新 release 没有 tag"
    return tag.lstrip("vV"), ""


def version_tuple(text: str) -> tuple:
    """把 ``1.0.6`` 解析成可比较的元组，非数字段按 0 处理。"""
    parts = re.split(r"[.\-+]", str(text or "").strip().lstrip("vV"))
    numbers = []
    for part in parts:
        match = re.match(r"^(\d+)", part)
        numbers.append(int(match.group(1)) if match else 0)
    return tuple(numbers) or (0,)
