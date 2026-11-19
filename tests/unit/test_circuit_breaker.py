"""P3-a 验证：自适应限流状态机(07 §3.4 含熔断死锁修复5条定案)。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "worker" / "src"))

from worker.scheduler.circuit import (  # noqa: E402
    CircuitBreaker, CircuitPhase, ControlConfig, STOP_ERRORS, CHALLENGE,
)


class Clock:
    def __init__(self, t=0.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, sec):
        self.t += sec


def breaker(clock, **cfg):
    return CircuitBreaker(config=ControlConfig(**cfg), _now=clock)


class TestDeadlockFixes:
    def test_fix1_auto_half_open_after_cooldown(self):
        # 修复1：熔断后冷却期满自动半开，无需人工复位。
        clk = Clock()
        cb = breaker(clk, failure_threshold=2, cooldown_seconds=600)
        cb.on_failure("upstream_5xx")
        cb.on_failure("upstream_5xx")
        assert cb.phase == CircuitPhase.OPEN and not cb.allows_request
        clk.advance(599)
        assert not cb.allows_request  # 冷却未满
        clk.advance(1)
        assert cb.allows_request and cb.phase == CircuitPhase.HALF_OPEN

    def test_fix2_failure_threshold_opens(self):
        clk = Clock()
        cb = breaker(clk, failure_threshold=3)
        cb.on_failure("network_timeout")
        cb.on_failure("network_timeout")
        assert cb.phase == CircuitPhase.GREEN
        cb.on_failure("network_timeout")  # 达阈值
        assert cb.phase == CircuitPhase.OPEN

    def test_fix3_challenge_not_stop_not_counted(self):
        # 修复3：challenge 不进 stop 名单、不开熔断、不计失败（换出口回炉）。
        assert CHALLENGE not in STOP_ERRORS
        clk = Clock()
        cb = breaker(clk, failure_threshold=1)
        for _ in range(10):
            cb.on_failure("challenge")
        assert cb.phase == CircuitPhase.GREEN
        assert cb.consecutive_failures == 0
        assert cb.allows_request

    def test_fix4_circuit_open_not_counted(self):
        # 修复4：circuit_open 自反馈不计入连续失败，防阈值永真死锁。
        clk = Clock()
        cb = breaker(clk, failure_threshold=2)
        cb.on_failure("upstream_5xx")
        for _ in range(100):
            cb.on_failure("circuit_open")
        assert cb.consecutive_failures == 1
        assert cb.phase == CircuitPhase.GREEN

    def test_fix5_half_open_clears_count(self):
        # 修复5：半开放行时清零历史失败计数。
        clk = Clock()
        cb = breaker(clk, failure_threshold=30, cooldown_seconds=100)
        for _ in range(29):
            cb.on_failure("network_timeout")
        cb.on_failure("rejected")  # 红档开熔断
        assert cb.consecutive_failures == 29
        clk.advance(101)
        assert cb.allows_request
        assert cb.consecutive_failures == 0  # 半开清零

    def test_half_open_success_resets(self):
        clk = Clock()
        cb = breaker(clk, failure_threshold=1, cooldown_seconds=60)
        cb.on_failure("rejected")
        clk.advance(61)
        assert cb.allows_request and cb.phase == CircuitPhase.HALF_OPEN
        cb.on_request_started()
        cb.on_success()
        assert cb.phase == CircuitPhase.GREEN and cb.consecutive_failures == 0
        assert cb.allows_request

    def test_half_open_only_one_probe(self):
        # 半开只放行一次探路，禁止并发放行第二个。
        clk = Clock()
        cb = breaker(clk, failure_threshold=1, cooldown_seconds=60)
        cb.on_failure("rejected")
        clk.advance(61)
        assert cb.allows_request  # 触发转半开
        cb.on_request_started()
        assert not cb.allows_request  # 探路占用中

    def test_half_open_failure_reopens_with_new_cooldown(self):
        clk = Clock()
        cb = breaker(clk, failure_threshold=1, cooldown_seconds=60)
        cb.on_failure("rejected")
        clk.advance(61)
        assert cb.allows_request  # 过门禁触发 OPEN→HALF_OPEN 懒转换
        cb.on_request_started()
        cb.on_half_open_failure()
        assert cb.phase == CircuitPhase.OPEN
        clk.advance(59)
        assert not cb.allows_request
        clk.advance(1)
        assert cb.allows_request

    def test_half_open_max_attempts_terminal(self):
        # 探路连续失败达 max_attempts → 保持熔断，终态由调度层处理。
        clk = Clock()
        cb = breaker(clk, failure_threshold=1, cooldown_seconds=10, max_attempts=2)
        cb.on_failure("rejected")
        for _ in range(2):
            clk.advance(11)
            assert cb.allows_request  # 先过门禁转半开
            cb.on_request_started()
            cb.on_half_open_failure()
        assert cb.phase == CircuitPhase.OPEN
        assert cb.attempts_in_half_open == 2
        assert cb.consecutive_failures == cb.config.failure_threshold


class TestRateStates:
    def test_red_error_opens_immediately(self):
        clk = Clock()
        cb = breaker(clk, failure_threshold=1000)  # 阈值很高
        for ec in ("rejected", "quota", "rate_limited", "page_type_unknown"):
            cb2 = breaker(Clock(), failure_threshold=1000)
            cb2.on_failure(ec)
            assert cb2.phase == CircuitPhase.OPEN, ec

    def test_yellow_on_p95_rise(self):
        cb = breaker(Clock())
        cb.state.concurrency = 4
        phase = cb.observe_window(p95_ms=16000, baseline_p95_ms=10000,
                                  success_rate=0.9, baseline_success_rate=0.9)
        assert phase == CircuitPhase.YELLOW
        assert cb.state.concurrency == 3  # ×0.75
        assert cb.state.interval_ms > 2500  # 间隔放大

    def test_yellow_on_success_drop(self):
        cb = breaker(Clock())
        phase = cb.observe_window(p95_ms=10000, baseline_p95_ms=10000,
                                  success_rate=0.84, baseline_success_rate=0.90)
        assert phase == CircuitPhase.YELLOW

    def test_green_slowly_increases(self):
        cb = breaker(Clock())
        cb.state.concurrency = 4
        phase = cb.observe_window(p95_ms=10000, baseline_p95_ms=10000,
                                  success_rate=0.9, baseline_success_rate=0.9)
        assert phase == CircuitPhase.GREEN
        assert cb.state.concurrency == 5  # +1（≤10% 取保守）
        assert cb.state.interval_ms == 2500

    def test_open_phase_skips_window(self):
        clk = Clock()
        cb = breaker(clk, failure_threshold=1)
        cb.on_failure("rejected")
        phase = cb.observe_window(99999, 10000, 0.1, 0.9)
        assert phase == CircuitPhase.OPEN

    def test_snapshot_masked(self):
        cb = breaker(Clock())
        snap = cb.snapshot()
        assert snap["phase"] == "green" and "cooldown_remaining_s" in snap
