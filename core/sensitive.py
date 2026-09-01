"""敏感词检测：支持自定义词库、远程词库或两者混合。"""
from __future__ import annotations

import asyncio
import time
from typing import Dict, List, Optional, Set, Tuple

from astrbot.api import logger

from .store import JsonStore, coerce_str_list
from .utils import normalize

# 词库来源: 仅管理员添加 / 仅远程词库 / 混合
MODE_CUSTOM = "custom"
MODE_LIBRARY = "library"
MODE_BOTH = "both"
VALID_MODES = (MODE_CUSTOM, MODE_LIBRARY, MODE_BOTH)

MODE_LABELS = {
    MODE_CUSTOM: "仅自定义词库",
    MODE_LIBRARY: "仅远程词库",
    MODE_BOTH: "混合（自定义 + 远程）",
}

DEFAULT_LIBRARY_URLS = [
    "https://raw.githubusercontent.com/konsheng/Sensitive-lexicon/main/Vocabulary/其他词库.txt",
    "https://raw.githubusercontent.com/konsheng/Sensitive-lexicon/main/Vocabulary/政治类.txt",
    "https://raw.githubusercontent.com/konsheng/Sensitive-lexicon/main/Vocabulary/色情类.txt",
]

CACHE_TTL = 6 * 3600
MIN_WORD_LEN = 2
MAX_LIBRARY_WORDS = 20000


class SensitiveWordEngine:
    """管理自定义词与远程词库，并提供命中检测。"""

    def __init__(self, store: JsonStore, config=None):
        self.store = store
        self.config = config or {}
        self._library: Set[str] = set()
        self._library_normalized: Dict[str, str] = {}
        self._fetched_at = 0.0
        self._fetch_lock = asyncio.Lock()

    # ---------- 自定义词库 ----------

    def custom_words(self, group_id: str) -> List[str]:
        words = self.store.group(str(group_id)).get("words")
        return list(words) if isinstance(words, list) else []

    async def add_word(self, group_id: str, word: str) -> Tuple[bool, str]:
        word = (word or "").strip()
        if not word:
            return False, "敏感词不能为空"
        if len(word) < MIN_WORD_LEN:
            return False, f"敏感词至少需要 {MIN_WORD_LEN} 个字符，避免误伤正常发言"

        bucket = self.store.group(str(group_id))
        words = bucket.get("words")
        if not isinstance(words, list):
            words = []
        if word in words:
            return False, f"敏感词「{word}」已存在"

        words.append(word)
        bucket["words"] = words
        await self.store.save()
        return True, f"已添加敏感词「{word}」，当前自定义词库共 {len(words)} 条"

    async def remove_word(self, group_id: str, word: str) -> Tuple[bool, str]:
        word = (word or "").strip()
        bucket = self.store.group(str(group_id))
        words = bucket.get("words")
        if not isinstance(words, list) or word not in words:
            return False, f"敏感词「{word}」不在自定义词库中"

        words.remove(word)
        bucket["words"] = words
        await self.store.save()
        return True, f"已删除敏感词「{word}」，当前自定义词库共 {len(words)} 条"

    # ---------- 远程词库 ----------

    def _library_urls(self) -> List[str]:
        urls = coerce_str_list(self.config.get("sensitive_library_urls"))
        return urls or DEFAULT_LIBRARY_URLS

    async def _fetch_library(self, force: bool = False) -> Tuple[int, Optional[str]]:
        """拉取远程词库，返回 (词条数, 错误信息)。结果带缓存。"""
        if not force and self._library and time.time() - self._fetched_at < CACHE_TTL:
            return len(self._library), None

        async with self._fetch_lock:
            if not force and self._library and time.time() - self._fetched_at < CACHE_TTL:
                return len(self._library), None

            try:
                import aiohttp
            except ImportError:
                return 0, "缺少 aiohttp 依赖，无法加载远程词库"

            words: Set[str] = set()
            errors: List[str] = []
            timeout = aiohttp.ClientTimeout(total=30)

            try:
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    for url in self._library_urls():
                        try:
                            async with session.get(url) as response:
                                if response.status != 200:
                                    errors.append(f"{url} 返回 HTTP {response.status}")
                                    continue
                                raw = await response.text(errors="ignore")
                        except Exception as exc:
                            errors.append(f"{url} 拉取失败: {exc}")
                            continue

                        for line in raw.splitlines():
                            word = line.strip()
                            if len(word) >= MIN_WORD_LEN and not word.startswith("#"):
                                words.add(word)
                        if len(words) >= MAX_LIBRARY_WORDS:
                            break
            except Exception as exc:
                return 0, f"远程词库加载异常: {exc}"

            if not words:
                return 0, "；".join(errors) or "远程词库为空"

            self._library = set(list(words)[:MAX_LIBRARY_WORDS])
            self._library_normalized = {normalize(w): w for w in self._library}
            self._fetched_at = time.time()
            if errors:
                logger.warning(f"[ZM-QQGroupmgr] 部分词库源不可用: {'；'.join(errors)}")
            return len(self._library), None

    async def reload_library(self) -> Tuple[int, Optional[str]]:
        """强制刷新远程词库。"""
        return await self._fetch_library(force=True)

    @property
    def library_size(self) -> int:
        return len(self._library)

    # ---------- 检测 ----------

    def mode(self, group_id: str) -> str:
        bucket = self.store.group(str(group_id))
        mode = bucket.get("mode")
        return mode if mode in VALID_MODES else MODE_CUSTOM

    async def set_mode(self, group_id: str, mode: str) -> None:
        self.store.group(str(group_id))["mode"] = mode
        await self.store.save()

    def whitelist(self) -> Set[str]:
        return {normalize(w) for w in coerce_str_list(self.config.get("sensitive_whitelist"))}

    async def check(self, group_id: str, text: str, mode: Optional[str] = None) -> Optional[str]:
        """返回命中的敏感词，未命中返回 None。"""
        if not text:
            return None

        mode = mode or self.mode(group_id)
        squeezed = normalize(text)
        if not squeezed:
            return None

        allow = self.whitelist()

        if mode in (MODE_CUSTOM, MODE_BOTH):
            for word in self.custom_words(group_id):
                key = normalize(word)
                if key and key not in allow and key in squeezed:
                    return word

        if mode in (MODE_LIBRARY, MODE_BOTH):
            count, error = await self._fetch_library()
            if error and not count:
                logger.debug(f"[ZM-QQGroupmgr] 远程词库不可用: {error}")
            else:
                for key, word in self._library_normalized.items():
                    if key and key not in allow and key in squeezed:
                        return word

        return None
