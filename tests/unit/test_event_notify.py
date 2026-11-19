"""SSE 推送基础设施单测：Hub 扇出/载荷解析/事件帧/事件流游标语义。

全部离线纯逻辑（无真实 DB/LISTEN）；触发器→LISTEN 全链路由集成测试覆盖。
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "api" / "src"))

import api.routes.events as events_mod  # noqa: E402
from api.notify import (  # noqa: E402
    NotifierHub, PgListener, parse_notification,
)
from api.routes.events import _frame, sse_stream  # noqa: E402


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------- Hub ----
def test_hub_subscribe_dispatch_unsubscribe():
    hub = NotifierHub()
    loop = asyncio.new_event_loop()
    hub.bind_loop(loop)
    q = hub.subscribe(7)
    assert hub.dispatch(7, {"event_id": 1}) == 1
    loop.run_until_complete(asyncio.sleep(0))  # call_soon_threadsafe 落地
    assert q.get_nowait() == {"event_id": 1}
    hub.unsubscribe(7, q)
    assert hub.dispatch(7, {"event_id": 2}) == 0
    loop.close()


def test_hub_multiple_subscribers_same_customer():
    hub = NotifierHub()
    q1, q2 = hub.subscribe(3), hub.subscribe(3)
    assert hub.dispatch(3, {"x": 1}) == 2
    assert q1.get_nowait() == {"x": 1}
    assert q2.get_nowait() == {"x": 1}
    assert hub.subscriber_count == 2
    hub.unsubscribe(3, q1)
    assert hub.subscriber_count == 1


def test_hub_dispatch_unknown_customer_noop():
    hub = NotifierHub()
    assert hub.dispatch(999, {"x": 1}) == 0


def test_hub_dispatch_without_loop_falls_back():
    hub = NotifierHub()  # 未 bind_loop：直接投递（测试/降级路径）
    q = hub.subscribe(5)
    assert hub.dispatch(5, {"x": 1}) == 1
    assert q.get_nowait() == {"x": 1}


def test_hub_unsubscribe_unknown_queue_noop():
    hub = NotifierHub()
    hub.subscribe(2)
    hub.unsubscribe(2, asyncio.Queue())  # 未注册的队列不抛错
    assert hub.subscriber_count == 1


# ------------------------------------------------------------ 载荷解析 ----
def test_parse_notification_ok():
    out = parse_notification(json.dumps(
        {"event_id": 9, "operation_id": 4, "customer_id": 2}))
    assert out == (2, {"event_id": 9, "operation_id": 4, "customer_id": 2})


def test_parse_notification_missing_customer_treated_as_zero():
    out = parse_notification(json.dumps({"event_id": 9}))
    assert out == (0, {"event_id": 9})


def test_parse_notification_garbage_returns_none():
    assert parse_notification("not-json") is None
    assert parse_notification(None) is None
    assert parse_notification(json.dumps(["a", "b"])) is None


def test_listener_handle_notification_dispatches():
    hub = NotifierHub()
    ln = PgListener("postgres://fake", hub)
    q = hub.subscribe(4)
    raw = json.dumps({"event_id": 3, "operation_id": 1, "customer_id": 4})
    assert ln.handle_notification(raw) == 1
    assert q.get_nowait() == {"event_id": 3, "operation_id": 1,
                              "customer_id": 4}


def test_listener_handle_malformed_silent_zero():
    hub = NotifierHub()
    ln = PgListener("postgres://fake", hub)
    assert ln.handle_notification("{{{") == 0
    assert hub.subscriber_count == 0


# ---------------------------------------------------------------- 帧 ----
def _row(event_id=1, kind="tracking.updated", **extra):
    payload = {"kind": kind, **extra}
    return {"event_id": event_id, "payload": payload,
            "created_at": "2026-11-19T09:00:00+00:00"}


def test_frame_whitelisted():
    r = _row(event_id=5, operation_id="op-1", summary="3/5 已送达")
    f = _frame(r)
    assert f.startswith("id: 5\nevent: tracking.updated\n")
    data = json.loads(f.split("data: ", 1)[1])
    assert data["payload"] == {"operation_id": "op-1",
                               "summary": "3/5 已送达"}


def test_frame_non_whitelisted_empty():
    assert _frame(_row(kind="internal.debug")) == ""


def test_frame_drops_unknown_payload_fields():
    r = _row(secret="代理IP", internal_state="A库细节")
    data = json.loads(_frame(r).split("data: ", 1)[1])
    assert "secret" not in data["payload"]
    assert "internal_state" not in data["payload"]


# -------------------------------------------------------------- 事件流 ----
class FakeRepo:
    def __init__(self, batches):
        self.batches = list(batches)   # 每次 projection_events 调用弹出一批
        self.calls = []

    def projection_events(self, customer_id, *, after=0, limit=50):
        self.calls.append((customer_id, after))
        return self.batches.pop(0) if self.batches else []


class FakeHub:
    def __init__(self):
        self.queues = {}

    def subscribe(self, cid):
        q = asyncio.Queue()
        self.queues.setdefault(cid, []).append(q)
        return q

    def unsubscribe(self, cid, q):
        self.queues.get(cid, []).remove(q)


async def _collect(gen, *, wake=None, rounds=3, step_s=0.01):
    """消费事件流：每轮让出一小段时间给生成器推进；可注入唤醒钩子。"""
    out: list[str] = []
    task = asyncio.ensure_future(_drain(gen, out))
    for i in range(rounds):
        await asyncio.sleep(step_s)
        if wake is not None:
            wake(i)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    return out


async def _drain(gen, out):
    try:
        async for chunk in gen:
            out.append(chunk)
    except (asyncio.CancelledError, StopAsyncIteration):
        pass


def test_stream_replays_catchup_after_last_event_id():
    repo = FakeRepo([[_row(event_id=6, operation_id="op-1"),
                      _row(event_id=7, kind="internal.debug")]])
    chunks = run(_collect(sse_stream(repo, 42, None, "5",
                                     _always_false)))
    assert repo.calls == [(42, 5)]  # 从 Last-Event-ID 游标追赶
    assert len(chunks) == 1  # 白名单外的 id=7 不推送但游标已推进
    assert chunks[0].startswith("id: 6\nevent: tracking.updated\n")


async def _always_false():
    return False


def test_stream_first_batch_empty_yields_nothing():
    repo = FakeRepo([[]])
    chunks = run(_collect(sse_stream(repo, 42, None, None, _always_false),
                          rounds=1))
    assert chunks == []


def test_stream_wakes_on_queue_event():
    """推送链路语义：唤醒后回读积压并即时推送。"""
    repo = FakeRepo([[], [_row(event_id=8, operation_id="op-2")]])
    hub = FakeHub()

    def wake(_i):
        hub.queues.get(42, [None])[0] and \
            hub.queues[42][0].put_nowait({"event_id": 8})  # noqa: harmless

    chunks = run(_collect(sse_stream(repo, 42, hub, None, _always_false),
                          wake=wake))
    assert any(c.startswith("id: 8\nevent: tracking.updated\n")
               for c in chunks), chunks
    assert (42, 8) in repo.calls  # 唤醒后从 id>8 之后回读（8 已发）


def test_stream_fallback_polls_when_no_hub(monkeypatch):
    """hub 缺席：降级节流轮询仍回读推送（不丢事件）。"""
    monkeypatch.setattr(events_mod, "_FALLBACK_POLL_S", 0.01)
    repo = FakeRepo([[], [_row(event_id=9, operation_id="op-3")]])
    chunks = run(_collect(sse_stream(repo, 42, None, None, _always_false)))
    assert any("id: 9" in c for c in chunks), chunks


def test_stream_unsubscribes_on_exit():
    hub = FakeHub()
    repo = FakeRepo([[]])
    run(_collect(sse_stream(repo, 42, hub, None, _always_false), rounds=1))
    assert hub.queues.get(42) in (None, [])  # 退出后清理订阅
