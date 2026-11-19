"""自适应限流状态机（模块 07 §3.4，含 2026-11-18 熔断死锁修复定案）。

关键不变量（§3.4 五条修复，逐条落实）：
1. 熔断后冷却期（默认10min）自动半开，放行一次探路——不允许人工复位死锁；
2. 连续失败 N 次（默认30）自动开熔断；
3. challenge 不进 stop 名单：换出口回炉，受 max_attempts=3 约束，不直接打死
   Provider；
4. circuit_open 拒绝不计入连续失败（自反馈错误排除），防阈值永真；
5. 半开放行时清零失败计数，防历史累积让阈值判定永真。

三态（绿/黄/红）阈值均为初始观测策略，不是 USPS 安全保证。时间经 `now`
注入，纯逻辑可离线单测。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

# 触发开熔断的错误类（§3.4 红档）：HTTP 403/429、拒绝、额度耗尽、页面误判。
# 注意：challenge 不在其中（换出口回炉）；circuit_open 不计入（自反馈）。
STOP_ERRORS = frozenset({
    "rejected", "quota", "rate_limited", "source_invalid",
    "page_type_unknown", "quality_gate_rejected",
    "probe_bad_status", "probe_empty_body", "proxy_gateway_unreachable",
})
# 明确不计入连续失败的自反馈错误。
NON_COUNTING_ERRORS = frozenset({"circuit_open", "not_found"})
# challenge 是可回炉的阻断信号：换出口，不加连续失败计数、不开熔断。
CHALLENGE = "challenge"


class CircuitPhase(str, Enum):
    GREEN = "green"          # 正常
    YELLOW = "yellow"        # 观察/降速
    OPEN = "open"            # 熔断打开（冷却中）
    HALF_OPEN = "half_open"  # 冷却期满，放行一次探路


@dataclass(slots=True)
class ControlConfig:
    """§3.4 初始观测阈值（验收区须重新标定）。"""

    failure_threshold: int = 30          # USPS_CIRCUIT_FAILURE_THRESHOLD
    cooldown_seconds: int = 600          # USPS_CIRCUIT_COOLDOWN_MIN=10
    max_attempts: int = 3                # 半开探路失败上限（同 02 max_attempts）
    yellow_p95_ratio: float = 1.5        # P95 较基线上升 50%
    yellow_success_drop: float = 0.05    # 成功率下降 5 个百分点
    green_concurrency_step: int = 1      # 每观察窗口最多 +1 worker
    green_concurrency_ratio: float = 0.10  # 或约 +10%
    yellow_concurrency_factor: float = 0.75  # ×0.7~0.8
    yellow_interval_factor: float = 1.75    # ×1.5~2

    def __post_init__(self):
        if self.failure_threshold < 1 or self.cooldown_seconds < 0:
            raise ValueError("invalid circuit config")


@dataclass(slots=True)
class RateState:
    """当前速率控制值。"""

    concurrency: int = 1
    interval_ms: int = 2500


@dataclass(slots=True)
class CircuitBreaker:
    """单 Provider 的限流/熔断状态机。

    now() 可注入以精确测试冷却期与半开，无需真实 sleep。
    """

    config: ControlConfig = field(default_factory=ControlConfig)
    state: RateState = field(default_factory=RateState)
    phase: CircuitPhase = CircuitPhase.GREEN
    consecutive_failures: int = 0
    attempts_in_half_open: int = 0
    opened_at: float = 0.0
    _half_open_inflight: bool = False
    _now: object = None  # 注入时钟；None 时用 time.time

    def __post_init__(self):
        if self._now is None:
            import time
            self._now = time.time

    @property
    def now(self) -> float:
        return self._now()

    @property
    def allows_request(self) -> bool:
        """当前是否允许发起新请求（门禁 §3.1）。"""
        if self.phase == CircuitPhase.OPEN:
            # 冷却期满自动转半开（懒转换，避免后台定时器）。
            if self.now - self.opened_at >= self.config.cooldown_seconds:
                self._enter_half_open()
                return True
            return False
        if self.phase == CircuitPhase.HALF_OPEN:
            # 半开只放行一次探路，禁止并发放行第二个。
            return not self._half_open_inflight
        return True

    def _enter_half_open(self) -> None:
        # 修复5：半开放行时清零"连续失败"计数，防历史失败让阈值永真。
        # 注意：attempts_in_half_open 必须跨冷却周期累积，否则探路失败永远
        # 达不到 max_attempts 转终态——那是死锁的另一种形式。
        self.phase = CircuitPhase.HALF_OPEN
        self.consecutive_failures = 0
        self._half_open_inflight = False

    def _open(self, t: float) -> None:
        self.phase = CircuitPhase.OPEN
        self.opened_at = t
        self._half_open_inflight = False
        # 红档降速：并发收缩、间隔拉大（§3.4 红档动作）。
        self.state.concurrency = max(1, int(self.state.concurrency * 0.5))
        self.state.interval_ms = int(self.state.interval_ms * 2)

    def on_request_started(self) -> None:
        """放行请求时调用，标记半开探路已占用。"""
        if self.phase == CircuitPhase.HALF_OPEN:
            self._half_open_inflight = True

    def on_success(self) -> None:
        """真实结果成功：绿档保持/恢复，熔断复位。"""
        was_half_open = self.phase in (CircuitPhase.HALF_OPEN, CircuitPhase.OPEN)
        # 修复5：半开探路成功 → 复位清零，关闭熔断。
        self.consecutive_failures = 0
        self.attempts_in_half_open = 0
        self._half_open_inflight = False
        self.phase = CircuitPhase.GREEN
        if was_half_open:
            # 复位后保守恢复：不低于 1。
            self.state.concurrency = max(1, self.state.concurrency)

    def on_failure(self, error_class: str) -> None:
        """按错误分类更新状态（修复3/4 在此落实）。"""
        ec = error_class
        # 修复4：自反馈/非失败不计入阈值，也不改变状态。
        if ec in NON_COUNTING_ERRORS:
            return
        # 修复3：challenge 换出口回炉，不计连续失败、不开熔断、不进 stop 名单。
        if ec == CHALLENGE:
            return
        if ec in STOP_ERRORS:
            # 红档：立即开熔断（不论当前计数）。
            self._open(self.now)
            return
        # 普通瞬态失败：累加，达阈值开熔断。
        self.consecutive_failures += 1
        if self.consecutive_failures >= self.config.failure_threshold:
            self._open(self.now)

    def on_half_open_failure(self) -> None:
        """半开探路失败：继续熔断，计数达上限转终态由调度层处理。"""
        if self.phase != CircuitPhase.HALF_OPEN:
            return
        self.attempts_in_half_open += 1
        self._half_open_inflight = False
        if self.attempts_in_half_open >= self.config.max_attempts:
            # 探路连续失败达上限 → 保持熔断，重置冷却重新开始计时。
            self.phase = CircuitPhase.OPEN
            self.opened_at = self.now
            self.consecutive_failures = self.config.failure_threshold
        else:
            # 未达上限：仍在冷却，等待下一次半开。
            self.phase = CircuitPhase.OPEN
            self.opened_at = self.now

    def observe_window(self, p95_ms: float, baseline_p95_ms: float,
                       success_rate: float, baseline_success_rate: float) -> CircuitPhase:
        """每个观察窗口评定的绿/黄档速率调整（§3.4）。

        红档由 on_failure 的事件驱动处理，不在此处。
        """
        if self.phase in (CircuitPhase.OPEN, CircuitPhase.HALF_OPEN):
            return self.phase
        yellow = (baseline_p95_ms > 0 and
                  p95_ms >= baseline_p95_ms * self.config.yellow_p95_ratio) or \
                 (baseline_success_rate - success_rate >= self.config.yellow_success_drop)
        if yellow:
            self.phase = CircuitPhase.YELLOW
            self.state.concurrency = max(1, int(
                self.state.concurrency * self.config.yellow_concurrency_factor))
            self.state.interval_ms = int(
                self.state.interval_ms * self.config.yellow_interval_factor)
        else:
            self.phase = CircuitPhase.GREEN
            # 绿档每窗口最多 +1 worker 或约 +10%（两者取更小的保守步长）。
            ratio_step = max(1, int(self.state.concurrency
                                    * self.config.green_concurrency_ratio))
            step = min(self.config.green_concurrency_step, ratio_step)
            self.state.concurrency += step
        return self.phase

    def snapshot(self) -> dict:
        """脱敏可观测快照（§3.5），不含秘密。"""
        return {
            "phase": self.phase.value,
            "concurrency": self.state.concurrency,
            "interval_ms": self.state.interval_ms,
            "consecutive_failures": self.consecutive_failures,
            "attempts_in_half_open": self.attempts_in_half_open,
            "cooldown_remaining_s": max(
                0, int(self.config.cooldown_seconds - (self.now - self.opened_at)))
            if self.phase == CircuitPhase.OPEN else 0,
        }
