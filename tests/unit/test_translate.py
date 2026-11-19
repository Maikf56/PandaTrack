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


def test_passthrough_langs_no_call():
    repo = FakeRepo()
    assert translate_texts(repo, "zh", ["你好"]) == {}
    assert translate_texts(repo, "", ["你好"]) == {}
    assert translate_texts(repo, "xx", ["你好"]) == {}  # 不支持的语言


def test_no_api_key_degrades_to_original(monkeypatch):
    monkeypatch.setenv("PT_TRANSLATE_API_KEY", "")
    monkeypatch.delenv("GOOGLE_TRANSLATE_API_KEY", raising=False)
    repo = FakeRepo()
    out = translate_texts(repo, "en", ["包裹已到达"])
    assert out == {}  # 降级：调用方按原文兜底，不报错


def test_cache_hit_no_google_call(monkeypatch):
    text = "包裹已到达"
    repo = FakeRepo(cached={source_digest(text): "Parcel has arrived"})

    def _boom(*a, **k):  # 出网即失败，验证没有调用
        raise AssertionError("should not call google")
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
