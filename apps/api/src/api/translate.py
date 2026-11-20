"""轨迹描述翻译（04 §6 增值项；竞品 17TRACK 收配额，我们首版免费）。

Provider 选择（按优先级，均失败则优雅降级返回原文）：
1. Google Cloud Translation v2 —— 配置 PT_TRANSLATE_API_KEY /
   GOOGLE_TRANSLATE_API_KEY 时启用（批量接口，缓存命中率决定成本）。
2. 自托管 LibreTranslate —— 配置 PT_LIBRETRANSLATE_URL 时启用
   （零注册零费用，docker 部署见 docs/DEPLOY.md；只需 en↔zh）。
3. 都未配置：返回原文（translated 降级），不报错——翻译是增值，
   不阻塞查询主链路。

语言范围收敛为 en↔zh（R12 修订）：lang=zh 时英文描述机翻为中文；
lang=en 时中文描述机翻为英文；lang='' 返回原文。
- 调用失败/超时：降级返回原文，记日志。
- 状态标签（label_zh/status_key）走静态字典，不过机翻；
  文本已是目标语言（CJK 启发式）时跳过，原样返回。
"""
from __future__ import annotations

import hashlib
import logging
import os
import time

import httpx

logger = logging.getLogger(__name__)

GOOGLE_ENDPOINT = "https://translation.googleapis.com/language/translate/v2"
SUPPORTED_LANGS = frozenset({"en", "zh"})  # R12 修订：整站与轨迹只需中英
PASSTHROUGH_LANGS = frozenset({""})  # 空串 = 原文直出
_TIMEOUT_S = 6.0
_MAX_BATCH = 64  # Google v2 单请求 q 数上限（文档 128，保守取 64）
_LIBRE_TIMEOUT_S = 4.0   # 自托管单条超时（本机回环，正常 <300ms）
_LIBRE_DEADLINE_S = 12.0  # 整页机翻总预算，超时后剩余条目降级为原文


def _google_key() -> str:
    return (os.environ.get("PT_TRANSLATE_API_KEY")
            or os.environ.get("GOOGLE_TRANSLATE_API_KEY") or "").strip()


def _libre_url() -> str:
    return os.environ.get("PT_LIBRETRANSLATE_URL", "").strip().rstrip("/")


def _libre_api_key() -> str:
    return os.environ.get("PT_LIBRETRANSLATE_API_KEY", "").strip()


def source_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _lang_weights(text: str) -> tuple[int, int]:
    """统计 CJK 字符与拉丁字母数，用于判断文本所属语言。"""
    cjk = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    latin = sum(1 for c in text if c.isascii() and c.isalpha())
    return cjk, latin


def _needs_translate(text: str, lang: str) -> bool:
    """文本已是目标语言时跳过机翻（中文标签/英文原文直出场景）。"""
    cjk, latin = _lang_weights(text)
    if lang == "zh":
        return cjk <= latin  # 已是中文（或纯符号）则不翻
    return cjk > 0  # en 目标：含中文才翻


def _translate_google(texts: list[str], lang: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for i in range(0, len(texts), _MAX_BATCH):
        chunk = texts[i:i + _MAX_BATCH]
        try:
            resp = httpx.post(
                GOOGLE_ENDPOINT,
                params={"key": _google_key()},
                json={"q": chunk, "target": lang, "format": "text"},
                timeout=_TIMEOUT_S,
            )
            resp.raise_for_status()
            items = resp.json().get("data", {}).get("translations", [])
            for src, item in zip(chunk, items):
                text = str(item.get("translatedText", "")).strip()
                if text:
                    out[src] = text
        except Exception:  # noqa: BLE001 降级不抛：翻译失败返回原文
            logger.warning("translate: google call failed for %d texts",
                           len(chunk), exc_info=True)
    return out


def _translate_libre(texts: list[str], lang: str) -> dict[str, str]:
    """LibreTranslate 逐条翻译（自托管回环，量小；总预算超时即降级）。"""
    out: dict[str, str] = {}
    deadline = time.monotonic() + _LIBRE_DEADLINE_S
    payload_key = _libre_api_key()
    for text in texts:
        if time.monotonic() > deadline:
            logger.warning("translate: libre deadline exceeded, %d texts skipped",
                           len(texts) - len(out))
            break
        try:
            payload: dict = {"q": text, "source": "auto", "target": lang,
                             "format": "text"}
            if payload_key:
                payload["api_key"] = payload_key
            resp = httpx.post(f"{_libre_url()}/translate",
                              json=payload, timeout=_LIBRE_TIMEOUT_S)
            resp.raise_for_status()
            translated = str(resp.json().get("translatedText", "")).strip()
            if translated:
                out[text] = translated
        except Exception:  # noqa: BLE001 单条失败不影响其余条目
            logger.warning("translate: libre call failed for one text",
                           exc_info=True)
    return out


def translate_texts(repo, lang: str, texts: list[str]) -> dict[str, str]:
    """批量翻译：缓存优先 → 缺失项 provider 批量调用 → 回写缓存。

    返回 原文 → 译文 映射；未覆盖的原文（未配 provider/失败/已是
    目标语言）不在映射中，调用方按原文兜底。repo 需提供
    translation_cache_get/put。
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
    # 已是目标语言的文本不进 provider，直接按原文兜底
    missing_texts = [t for d, t in digests.items()
                     if d not in cached and _needs_translate(t, lang)]
    if not missing_texts:
        return out

    if _google_key():
        translated = _translate_google(missing_texts, lang)
    elif _libre_url():
        translated = _translate_libre(missing_texts, lang)
    else:
        logger.info("translate: no provider configured, skip %d texts",
                    len(missing_texts))
        return out

    if translated:
        entries = [(source_digest(t), t, v) for t, v in translated.items()]
        try:
            repo.translation_cache_put(lang, entries)
        except Exception:  # noqa: BLE001 缓存写失败不影响本次结果
            logger.warning("translate: cache write failed", exc_info=True)
    return {**out, **translated}
