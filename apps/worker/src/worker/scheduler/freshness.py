"""四分支判定与刷新预算（模块 07 §3.7）。

客户触发保鲜/「检查更新」时必须先做四分支判定，不能简化成"库里有数据就跳过"：
1. 事实不存在或已失效 → 创建 FetchJob 抓取（need_fetch）
2. 事实存在但已终态 → 沿用事实，不重复抓上游（reuse_terminal）
3. 事实新鲜且未到 next_sync_at → 沿用，0 上游请求（reuse_fresh）
4. 上游暂停/熔断/额度受限 → 保留任务与客户关系，延后（defer）

关键不变量：
- 跳过抓取 ≠ 跳过客户关系：不论是否抓上游，customer_tracking/reservation/
  投影都必须建立（这由 06 计费层负责，本模块只输出判定，不遗漏信号）。
- 后台非终态刷新受活跃单号 7 天窗口 + 全局每日刷新上限约束。
- 时间经 now 注入，纯逻辑可离线单测。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from pandatrack_common.status import TERMINAL_STATUSES

ACTIVE_WINDOW_DAYS = 7
DEFAULT_DAILY_REFRESH_CAP = 100000


@dataclass(slots=True)
class Fact:
    """库内既有事实（脱敏判定用，不含事件明细）。"""

    exists: bool = False
    status: str = ""                # 12 态 key
    last_success_at: datetime | None = None
    next_sync_at: datetime | None = None
    version: int = 0


@dataclass(slots=True)
class UpstreamState:
    """上游可用性（来自 CircuitBreaker / Provider 健康）。"""

    paused: bool = False
    circuit_open: bool = False
    quota_exhausted: bool = False


@dataclass(slots=True)
class Budget:
    """每日刷新预算计数器（进程内视图；持久化由调度层落 Redis）。"""

    date_key: str = ""
    used: int = 0
    cap: int = DEFAULT_DAILY_REFRESH_CAP

    def allows(self, date_key: str) -> bool:
        if self.date_key != date_key:
            return True  # 跨天重置（由调用方重建 Budget）
        return self.used < self.cap


class Branch(str):
    NEED_FETCH = "need_fetch"
    REUSE_TERMINAL = "reuse_terminal"
    REUSE_FRESH = "reuse_fresh"
    DEFER = "defer"


@dataclass(slots=True)
class Decision:
    branch: str
    reason: str
    create_job: bool = False
    upstream_requests: int = 0
    keep_customer_relation: bool = True  # 始终 True（§3.7 关键约束）


def decide(
    fact: Fact,
    upstream: UpstreamState,
    *,
    now: datetime | None = None,
    reason_code: str = "initial",  # initial / refresh / manual_recheck
    budget: Budget | None = None,
    budget_date_key: str = "",
) -> Decision:
    """四分支判定（§3.7）。

    优先级：上游受限(4) > 事实不存在/失效(1) > 终态(2) > 新鲜(3) > 需刷新(1)。
    """
    t = now or datetime.now(timezone.utc)

    # 分支4：上游暂停/熔断/额度受限 → 保留任务与客户关系，延后重试。
    if upstream.paused or upstream.circuit_open or upstream.quota_exhausted:
        return Decision(Branch.DEFER, "上游暂停/熔断/额度受限", create_job=False)

    # 分支1：事实不存在 → 创建 FetchJob。
    if not fact.exists:
        return Decision(Branch.NEED_FETCH, "事实不存在", create_job=True,
                        upstream_requests=1)

    # 分支2：事实已终态（已签收/未找到/退回）→ 沿用，不重复抓上游。
    if fact.status in TERMINAL_STATUSES:
        return Decision(Branch.REUSE_TERMINAL, "事实已终态",
                        upstream_requests=0)

    # 分支3：事实新鲜且未到 next_sync_at → 沿用，0 上游请求。
    if fact.next_sync_at is not None and t < fact.next_sync_at:
        return Decision(Branch.REUSE_FRESH, "未到下次同步时间",
                        upstream_requests=0)

    # 主动刷新但预算耗尽 → 延后（分支4 的预算特例）。
    if reason_code == "refresh" and budget is not None \
            and not budget.allows(budget_date_key):
        return Decision(Branch.DEFER, "每日刷新预算耗尽", create_job=False)

    # 分支1（刷新）：事实非终态、已到同步时间 → 创建刷新任务。
    return Decision(Branch.NEED_FETCH, "事实已过期需刷新", create_job=True,
                    upstream_requests=1)


def within_active_window(last_success_at: datetime | None,
                         *, now: datetime | None = None,
                         days: int = ACTIVE_WINDOW_DAYS) -> bool:
    """活跃单号 7 天窗口：非终态后台刷新只在此窗口内进行（§3.7）。

    无成功时间视为不活跃（不后台刷新，只按需抓取）。
    """
    if last_success_at is None:
        return False
    t = now or datetime.now(timezone.utc)
    return t - last_success_at <= timedelta(days=days)
