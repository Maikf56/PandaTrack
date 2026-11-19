"""计费规则（方案 06 §3.3/3.4/3.6）。

- 1 个新单号扣 1 积分；
- 同客户同单号 UTC 滚动 30×24h 内免扣（waived_30d），以已提交 reservation 为权威；
- 重复项、不可安全识别项不扣费；checksum_warn 仍计费入队；
- 余额不足整批原子失败；余额按客户账号共享，子账号共用。

计费免扣（本模块，客户+单号）与采集去重（07 recent_checker，全库）是两层，
不得混为一谈。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

WATERSHED_HOURS = 30 * 24               # 30×24 小时滚动窗口（06 §3.6）


def is_waived(last_charged_at: datetime | None, now: datetime) -> bool:
    """该单号在当前时刻是否落在 30×24h 免扣窗口内。

    last_charged_at 为该客户此前成功提交该单号的时间（UTC）；无记录不免扣。
    窗口边界：expires_at = last + 30 天，now < expires_at 才免扣（超窗口按新单号计费）。
    """
    if last_charged_at is None:
        return False
    # 统一到 UTC 感知时间比较
    cur = last_charged_at if last_charged_at.tzinfo else last_charged_at.replace(tzinfo=timezone.utc)
    n = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    return n < cur + timedelta(hours=WATERSHED_HOURS)


@dataclass(frozen=True, slots=True)
class BillingDecision:
    """一次提交的计费判定结果。"""
    billable_count: int                 # 实际扣费积分
    waived_count: int                   # 30 天免扣条数
    duplicate_count: int                # 同批重复条数
    invalid_count: int                  # 不可安全识别条数
    total_count: int                    # 清洗后候选总数
    balance: int                        # 当前余额
    sufficient: bool                    # 余额是否足够

    @property
    def would_be_balance(self) -> int:
        return self.balance - self.billable_count if self.sufficient else self.balance


def compute_charge(
    candidates: list[str | None],
    *,
    recent_charged: dict[str, datetime],
    now: datetime,
    balance: int,
) -> BillingDecision:
    """集合化计费判定（纯逻辑版；DB 层用暂存表 + JOIN 等价实现，见 06 §3.4）。

    candidates: 清洗后的规范化单号列表，None 表示不可安全识别（不计费）。
    recent_charged: 该客户 30 天窗口内已扣费单号 → 扣费时间。
    重复项与窗口内项不重复计费。
    """
    seen: set[str] = set()
    duplicate_count = 0
    waived_count = 0
    invalid_count = 0
    billable = 0

    for num in candidates:
        if not num:
            invalid_count += 1
            continue
        if num in seen:
            duplicate_count += 1
            continue
        seen.add(num)
        if is_waived(recent_charged.get(num), now):
            waived_count += 1
            continue
        billable += 1

    return BillingDecision(
        billable_count=billable,
        waived_count=waived_count,
        duplicate_count=duplicate_count,
        invalid_count=invalid_count,
        total_count=len(candidates),
        balance=balance,
        sufficient=balance >= billable,
    )
