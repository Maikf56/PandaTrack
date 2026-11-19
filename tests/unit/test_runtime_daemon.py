"""Worker 常驻入口单测：配置解析、连接复用、适配器、周期调度、CLI。

全部离线纯逻辑（注入 fake loop/sync/clock/sleeper），不碰真实 DB/Claw。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "worker" / "src"))

import worker.runtime.daemon as daemon_mod  # noqa: E402
from worker.runtime.daemon import (  # noqa: E402
    CycleReport, PersistentConnect, WorkerDaemon, WorkerSettings,
    make_canary_fetch, make_fetch, parse_args,
)
from worker.runtime.loop import TickReport, WriteStats  # noqa: E402
from worker.scheduler.canary import CanaryMismatch  # noqa: E402
from worker.sync.agent import SyncReport  # noqa: E402
from worker.provider.contracts import ProviderInput, ProviderItem, ProviderResult  # noqa: E402
from worker.provider.errors import ProviderError  # noqa: E402


# ---------------------------------------------------------------- fakes ----
class FakeConn:
    def __init__(self):
        self.closed = False
        self.rollbacks = 0

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


class FakeClock:
    def __init__(self, start=1000.0):
        self.t = start
        self.steps = 0

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


class FakeLoop:
    """脚本化 tick：按序返回报告或抛异常。"""

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    def tick(self):
        self.calls += 1
        item = self.script.pop(0) if self.script else TickReport()
        if isinstance(item, Exception):
            raise item
        return item


class FakeSync:
    def __init__(self, reports=None):
        self.reports = list(reports or [])
        self.drain_calls = 0

    def run_until_drained(self, *, max_rounds=100):
        self.drain_calls += 1
        return self.reports


def make_tick(**kw):
    fields = dict(reclaimed=0, claimed=1, succeeded=1, retried=0,
                  dead_lettered=0, facts=WriteStats(facts_written=1,
                                                    events_written=2,
                                                    outbox_written=1),
                  canary_halt=False, canary_mismatches=[], error_class=None)
    fields.update(kw)
    return TickReport(**fields)


# ---------------------------------------------------------------- 配置 ----
def test_settings_defaults():
    s = WorkerSettings.from_env(env={})
    assert s.dsn_a == "" and s.dsn_b == ""
    assert s.worker_id == "worker-1"
    assert s.tick_interval_s == 20 and s.sync_interval_s == 30
    assert s.claim_limit == 10 and s.lease_seconds == 300
    assert s.usps_enabled is True
    assert s.claw_profile == "smoke1"


def test_settings_custom_env():
    s = WorkerSettings.from_env(env={
        "PT_DB_A_URL": "postgres://a", "PT_DB_B_URL": "postgres://b",
        "PT_WORKER_ID": "w-9", "PT_TICK_INTERVAL_S": "5",
        "PT_CLAIM_LIMIT": "3", "PT_USPS_ENABLED": "false",
        "PT_CLAW_BIN": "/usr/local/bin/clawctl", "PT_RELAY_SOCKS5": "127.0.0.1:2080",
    })
    assert s.dsn_a == "postgres://a"
    assert s.worker_id == "w-9"
    assert s.tick_interval_s == 5 and s.claim_limit == 3
    assert s.usps_enabled is False
    assert s.claw_bin == "/usr/local/bin/clawctl"
    assert s.relay_socks5 == "127.0.0.1:2080"


def test_settings_invalid_int_falls_back():
    s = WorkerSettings.from_env(env={"PT_TICK_INTERVAL_S": "abc"})
    assert s.tick_interval_s == 20


def test_settings_zero_int_clamped_to_one():
    s = WorkerSettings.from_env(env={"PT_CLAIM_LIMIT": "0"})
    assert s.claim_limit == 1


# ------------------------------------------------------------ 连接工厂 ----
def test_persistent_connect_reuses_connection():
    made = []

    def factory(dsn):
        made.append(dsn)
        return FakeConn()

    pc = PersistentConnect("postgres://x", connect=factory)
    c1 = pc()
    c2 = pc()
    assert c1 is c2
    assert made == ["postgres://x"]


def test_persistent_connect_reconnects_when_closed():
    made = []

    def factory(dsn):
        c = FakeConn()
        made.append(c)
        return c

    pc = PersistentConnect("postgres://x", connect=factory)
    c1 = pc()
    c1.closed = True
    c2 = pc()
    assert c2 is not c1
    assert len(made) == 2


def test_persistent_connect_reset_rolls_back():
    pc = PersistentConnect("postgres://x", connect=lambda dsn: FakeConn())
    conn = pc()
    pc.reset()
    assert conn.rollbacks == 1


def test_persistent_connect_reset_drops_broken_connection():
    class Broken:
        closed = False

        def rollback(self):
            raise RuntimeError("broken pipe")

    made: list = []

    def factory(dsn):
        c = Broken() if not made else FakeConn()
        made.append(c)
        return c

    pc = PersistentConnect("postgres://x", connect=factory)
    pc()
    pc.reset()
    # 丢弃坏连接后下次调用重建。
    fresh = pc()
    assert isinstance(fresh, FakeConn)


def test_persistent_connect_close():
    pc = PersistentConnect("postgres://x", connect=lambda dsn: FakeConn())
    conn = pc()
    pc.close()
    assert conn.closed is True


# ------------------------------------------------------------- 适配器 ----
class FakeProvider:
    def __init__(self, result=None, exc=None):
        self.seen = None
        self.result = result or ProviderResult()
        self.exc = exc

    def fetch(self, inputs):
        self.seen = list(inputs)
        if self.exc:
            raise self.exc
        return self.result


def test_make_fetch_maps_numbers_to_provider_input():
    p = FakeProvider()
    fetch = make_fetch(p)
    fetch(["94001111AAAA", "94002222BBBB"])
    assert [i.normalized_number for i in p.seen] == \
        ["94001111AAAA", "94002222BBBB"]
    assert all(isinstance(i, ProviderInput) for i in p.seen)


def test_make_canary_fetch_returns_ok_statuses():
    ok = ProviderItem.succeed(
        normalized_number="94001111AAAA", source="usps_web", simulated=False,
        status="delivered")
    fail = ProviderItem.fail("94002222BBBB", "parse_failed", source="usps_web")
    p = FakeProvider(result=ProviderResult(items=[ok, fail]))
    statuses = make_canary_fetch(p)(["94001111AAAA", "94002222BBBB"])
    assert statuses == {"94001111AAAA": "delivered"}


def test_make_canary_fetch_fail_closed_on_provider_error():
    p = FakeProvider(exc=ProviderError("challenge", "blocked"))
    statuses = make_canary_fetch(p)(["94001111AAAA"])
    assert statuses == {}


# --------------------------------------------------------------- 调度 ----
def test_cycle_runs_tick_only_when_sync_not_due():
    clock = FakeClock(start=1000.0)
    loop = FakeLoop([make_tick()])
    sync = FakeSync([SyncReport(fetched=1)])
    d = WorkerDaemon(loop=loop, sync=sync, tick_interval_s=20,
                     sync_interval_s=30, clock=clock, sleeper=lambda s: None,
                     reset=lambda: None)
    report = d.run_cycle()
    assert report.error is None
    assert report.tick["claimed"] == 1
    assert report.sync_rounds == 0
    assert sync.drain_calls == 0


def test_cycle_runs_sync_when_due():
    clock = FakeClock(start=1000.0)
    loop = FakeLoop([make_tick()])
    sync = FakeSync([SyncReport(fetched=2, projected=3),
                     SyncReport(fetched=0)])
    d = WorkerDaemon(loop=loop, sync=sync, tick_interval_s=20,
                     sync_interval_s=30, clock=clock, sleeper=lambda s: None,
                     reset=lambda: None)
    d._next_sync_at = 1000.0  # 立即到期
    report = d.run_cycle()
    assert sync.drain_calls == 1
    assert report.sync_rounds == 2
    assert report.sync_summary == {"fetched": 2, "projected": 3,
                                   "skipped_no_customer": 0}
    # 下一次投影被推迟一个 sync_interval。
    assert d._next_sync_at == 1030.0


def test_cycle_tick_error_resets_and_skips_sync():
    clock = FakeClock(start=1000.0)
    reset_calls = []
    loop = FakeLoop([RuntimeError("db gone")])
    sync = FakeSync([SyncReport(fetched=1)])
    d = WorkerDaemon(loop=loop, sync=sync, tick_interval_s=20,
                     sync_interval_s=30, clock=clock, sleeper=lambda s: None,
                     reset=lambda: reset_calls.append(1))
    d._next_sync_at = 1000.0
    report = d.run_cycle()
    assert report.error is not None and "db gone" in report.error
    assert reset_calls == [1]
    assert sync.drain_calls == 0  # 失败轮不投影，防投影到脏数据


def test_cycle_reports_canary_halt():
    loop = FakeLoop([make_tick(canary_halt=True,
                               canary_mismatches=[CanaryMismatch(
                                   number="9400XX", reason="missing",
                                   expected="delivered", actual="")])])
    clock = FakeClock(start=1000.0)
    d = WorkerDaemon(loop=loop, sync=FakeSync(), tick_interval_s=20,
                     sync_interval_s=30, clock=clock, sleeper=lambda s: None,
                     reset=lambda: None)
    report = d.run_cycle()
    assert report.tick["canary_halt"] is True
    assert report.tick["canary_mismatches"] == [{"number": "9400XX",
                                                 "reason": "missing"}]


def test_run_forever_max_cycles():
    clock = FakeClock(start=1000.0)
    sleeps = []

    def sleeper(s):
        sleeps.append(s)
        clock.advance(s)

    loop = FakeLoop([make_tick() for _ in range(3)])
    d = WorkerDaemon(loop=loop, sync=FakeSync(), tick_interval_s=20,
                     sync_interval_s=10**9, clock=clock, sleeper=sleeper,
                     reset=lambda: None)
    done = d.run_forever(max_cycles=3)
    assert done == 3
    assert loop.calls == 3
    assert sleeps == [20, 20]


def test_run_forever_graceful_on_interrupt():
    clock = FakeClock(start=1000.0)

    def sleeper(s):
        raise KeyboardInterrupt

    loop = FakeLoop([make_tick()])
    d = WorkerDaemon(loop=loop, sync=FakeSync(), tick_interval_s=20,
                     sync_interval_s=30, clock=clock, sleeper=sleeper,
                     reset=lambda: None)
    assert d.run_forever() == 1
    assert d.stopped is False  # KeyboardInterrupt 不置 stop 标记，正常退出


def test_run_forever_stops_on_stop_flag():
    clock = FakeClock(start=1000.0)
    loop = FakeLoop([make_tick(), make_tick()])

    def sleeper(s):
        clock.advance(s)
        d.stop()

    d = WorkerDaemon(loop=loop, sync=FakeSync(), tick_interval_s=20,
                     sync_interval_s=30, clock=clock, sleeper=sleeper,
                     reset=lambda: None)
    done = d.run_forever()
    assert done == 1  # 第一轮后 stop 生效，不再进入第二轮
    assert d.stopped is True


# ---------------------------------------------------------------- CLI ----
def test_parse_args_default_run():
    args = parse_args([])
    assert args.mode == "run" and args.verbose is False


def test_parse_args_modes():
    assert parse_args(["once"]).mode == "once"
    assert parse_args(["sync"]).mode == "sync"
    assert parse_args(["run", "--verbose"]).verbose is True


def test_parse_args_rejects_unknown_mode():
    with pytest.raises(SystemExit):
        parse_args(["bogus"])


# ------------------------------------------------------- 生产组装守卫 ----
def test_build_components_requires_dsns(monkeypatch):
    monkeypatch.setattr(daemon_mod, "WorkerSettings", WorkerSettings)
    s = WorkerSettings.from_env(env={})
    with pytest.raises(ValueError, match="PT_DB_A_URL"):
        daemon_mod.build_components(s)
