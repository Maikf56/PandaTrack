"""轨迹翻译模块单测：缓存优先/批量去重/降级（不碰真库，fake repo + 不出网）。"""
import sys
from pathlib import Path

import pytest

sys.path[:0] = [str(Path(__file__).resolve().parents[2] / "apps" / "api" / "src"),
                str(Path(__file__).resolve().parents[2] / "packages" / "common" / "src")]

from api import translate  # noqa: E402
from api.translate import source_digest, translate_texts  # noqa: E402


class FakeRepo:
    def __init__(self, cached=None):
        self._cached = cached or {}
        self.put_calls: list[list[tuple[str, str, str]]] = []

    def translation_cache_get(self, lang, digests):
        return {d: t for d, t in self._cached.items() if d in digests}

    def translation_cache_put(self, lang, entries):
        self.put_calls.append(list(entries))
        for d, _s, t in entries:
            self._cached[d] = t


@pytest.fixture(autouse=True)
def _isolate_provider_env(monkeypatch):
    """所有用例默认无 provider，避免开发机环境变量泄漏进单测出网。"""
    monkeypatch.delenv("PT_TRANSLATE_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_TRANSLATE_API_KEY", raising=False)
    monkeypatch.delenv("PT_LIBRETRANSLATE_URL", raising=False)
    monkeypatch.delenv("PT_LIBRETRANSLATE_API_KEY", raising=False)


def test_passthrough_langs_no_call():
    repo = FakeRepo()
    assert translate_texts(repo, "", ["你好"]) == {}
    assert translate_texts(repo, "xx", ["你好"]) == {}  # 不支持的语言


def test_no_provider_degrades_to_original():
    repo = FakeRepo()
    assert translate_texts(repo, "en", ["包裹已到达"]) == {}
    # zh 现在是受支持目标，但英文文本无 provider 时仍降级返回原文
    assert translate_texts(repo, "zh", ["Parcel has arrived"]) == {}


def test_zh_target_skips_already_chinese_text(monkeypatch):
    """已是中文的文本在 zh 目标下跳过机翻，不进 provider。"""
    def _boom(*a, **k):
        raise AssertionError("should not call provider")
    monkeypatch.setattr(translate.httpx, "post", _boom)
    monkeypatch.setenv("PT_LIBRETRANSLATE_URL", "http://127.0.0.1:5001")
    assert translate_texts(FakeRepo(), "zh", ["已抵达分拣中心"]) == {}


def test_cache_hit_no_provider_call(monkeypatch):
    text = "包裹已到达"
    repo = FakeRepo(cached={source_digest(text): "Parcel has arrived"})

    def _boom(*a, **k):  # 出网即失败，验证没有调用
        raise AssertionError("should not call provider")
    monkeypatch.setattr(translate.httpx, "post", _boom)
    monkeypatch.setenv("PT_TRANSLATE_API_KEY", "fake-key")

    out = translate_texts(repo, "en", [text, text])  # 重复文本去重
    assert out == {text: "Parcel has arrived"}       # 返回 原文→译文
    assert repo.put_calls == []


def test_google_call_then_cache_write(monkeypatch):
    repo = FakeRepo()
    text = "已抵达分拣中心"

    class FakeResp:
        def raise_for_status(self): ...
        def json(self):
            return {"data": {"translations": [{"translatedText": " Arrived at sorting center "}]}}
    monkeypatch.setattr(translate.httpx, "post", lambda *a, **k: FakeResp())
    monkeypatch.setenv("PT_TRANSLATE_API_KEY", "fake-key")

    out = translate_texts(repo, "en", [text])
    assert out[text] == "Arrived at sorting center"  # strip 过
    assert len(repo.put_calls) == 1
    # 二次调用直接命中缓存
    out2 = translate_texts(repo, "en", [text])
    assert out2[text] == "Arrived at sorting center"
    assert len(repo.put_calls) == 1


def test_google_failure_degrades(monkeypatch):
    repo = FakeRepo()
    monkeypatch.setattr(translate.httpx, "post",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("net down")))
    monkeypatch.setenv("PT_TRANSLATE_API_KEY", "fake-key")
    out = translate_texts(repo, "en", ["网络中断测试"])
    assert out == {}  # 降级返回空映射


def test_libre_call_then_cache_write(monkeypatch):
    """LibreTranslate provider：en→zh 与缓存回写。"""
    repo = FakeRepo()
    text = "Arrived at USPS Facility"

    class FakeResp:
        def raise_for_status(self): ...
        def json(self):
            return {"translatedText": " 已抵达 USPS 处理中心 ", "detectedLanguage": {"language": "en"}}
    captured: list[dict] = []

    def fake_post(url, json=None, timeout=None):
        captured.append({"url": url, "json": json, "timeout": timeout})
        return FakeResp()
    monkeypatch.setattr(translate.httpx, "post", fake_post)
    monkeypatch.setenv("PT_LIBRETRANSLATE_URL", "http://127.0.0.1:5001/")

    out = translate_texts(repo, "zh", [text])
    assert out[text] == "已抵达 USPS 处理中心"
    assert len(captured) == 1
    assert captured[0]["url"] == "http://127.0.0.1:5001/translate"  # 尾斜杠已去除
    assert captured[0]["json"]["target"] == "zh"
    assert "api_key" not in captured[0]["json"]  # 未配 key 不带该字段
    assert len(repo.put_calls) == 1
    # 二次调用命中缓存，不再出网
    out2 = translate_texts(repo, "zh", [text])
    assert out2[text] == "已抵达 USPS 处理中心"
    assert len(captured) == 1


def test_libre_single_failure_continues(monkeypatch):
    """Libre 单条失败不拖垮整批：其余条目仍返回。"""
    repo = FakeRepo()
    texts = ["Arrived at USPS Facility", "Departed USPS Facility"]

    class FakeResp:
        def raise_for_status(self): ...
        def json(self):
            return {"translatedText": "OK"}
    state = {"n": 0}

    def fake_post(url, json=None, timeout=None):
        state["n"] += 1
        if state["n"] == 1:
            raise RuntimeError("boom")
        return FakeResp()
    monkeypatch.setattr(translate.httpx, "post", fake_post)
    monkeypatch.setenv("PT_LIBRETRANSLATE_URL", "http://127.0.0.1:5001")

    out = translate_texts(repo, "zh", texts)
    assert out == {"Departed USPS Facility": "OK"}


def test_libre_failure_degrades(monkeypatch):
    repo = FakeRepo()
    monkeypatch.setattr(translate.httpx, "post",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("net down")))
    monkeypatch.setenv("PT_LIBRETRANSLATE_URL", "http://127.0.0.1:5001")
    assert translate_texts(repo, "zh", ["In Transit to Next Facility"]) == {}
