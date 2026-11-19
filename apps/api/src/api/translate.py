"""轨迹描述翻译（04 §6 增值项；竞品 17TRACK 收配额，我们首版免费）。

实现：Google Cloud Translation v2 + B 库 translation_cache 按
(lang, sha256) 复用——物流描述术语高度固定，缓存命中率决定成本。
- 未配置 PT_TRANSLATE_API_KEY / GOOGLE_TRANSLATE_API_KEY：优雅降级，
  返回原文（translated=false），不报错——翻译是增值，不阻塞查询主链路。
- Google 调用失败/超时：同样降级返回原文，记日志。
- 状态标签（label_zh/status_key）走静态字典，不过机翻。
"""
from __future__ import annotations

import hashlib
import logging
import os

import httpx

logger = logging.getLogger(__name__)

GOOGLE_ENDPOINT = "https://translation.googleapis.com/language/translate/v2"
SUPPORTED_LANGS = frozenset({
    "en", "es", "fr", "de", "pt", "ru", "ja", "ko", "ar", "th", "vi", "id",
})
# 源文本已可读的语言不再机翻（中文标签场景）
PASSTHROUGH_LANGS = frozenset({"zh", ""})
_TIMEOUT_S = 6.0
_MAX_BATCH = 64  # Google v2 单请求 q 数上限（文档 128，保守取 64）


def _api_key() -> str:
    return (os.environ.get("PT_TRANSLATE_API_KEY")
            or os.environ.get("GOOGLE_TRANSLATE_API_KEY") or "").strip()


def source_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def translate_texts(repo, lang: str, texts: list[str]) -> dict[str, str]:
    """批量翻译：缓存优先 → 缺失项一次 Google 批量调用 → 回写缓存。

    返回 原文 → 译文 映射；未覆盖的原文（无 key/失败）不在映射中，
    调用方按原文兜底。repo 需提供 translation_cache_get/put。
    """
    lang = lang.strip().lower()
    if lang in PASSTHROUGH_LANGS or lang not in SUPPORTED_LANGS:
        return {}
    uniq = [t for t in dict.fromkeys(t for t in texts if t and t.strip())]
    if not uniq:
        return {}

    digests = {source_digest(t): t for t in uniq}
    cached = repo.translation_cache_get(lang, list(digests))
    # 统一返回 原文 → 译文（缓存行以 digest 存储，需映射回原文）
    out = {digests[d]: t for d, t in cached.items() if d in digests}
    missing_texts = [t for d, t in digests.items() if d not in cached]
    if not missing_texts:
        return out

    key = _api_key()
    if not key:
        logger.info("translate: no API key configured, skip %d texts",
                    len(missing_texts))
        return out

    translated: dict[str, str] = {}
    for i in range(0, len(missing_texts), _MAX_BATCH):
        chunk = missing_texts[i:i + _MAX_BATCH]
        try:
            resp = httpx.post(
                GOOGLE_ENDPOINT,
                params={"key": key},
                json={"q": chunk, "target": lang, "format": "text"},
                timeout=_TIMEOUT_S,
            )
            resp.raise_for_status()
            items = resp.json().get("data", {}).get("translations", [])
            for src, item in zip(chunk, items):
                text = str(item.get("translatedText", "")).strip()
                if text:
                    translated[src] = text
        except Exception:  # noqa: BLE001 降级不抛：翻译失败返回原文
            logger.warning("translate: google call failed for %d texts",
                           len(chunk), exc_info=True)

    if translated:
        entries = [(source_digest(t), t, v) for t, v in translated.items()]
        try:
            repo.translation_cache_put(lang, entries)
        except Exception:  # noqa: BLE001 缓存写失败不影响本次结果
            logger.warning("translate: cache write failed", exc_info=True)
    return {**out, **translated}
