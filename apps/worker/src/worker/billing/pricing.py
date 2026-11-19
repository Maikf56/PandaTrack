"""6 档积分套餐配置（方案 06 §3.6 定稿）。

套餐服务端配置生成，不硬编码前端；积分只计量系统维护与运行费用，
不是出售 USPS 轨迹。>100,000 积分转人工报价。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Package:
    code: str
    name_zh: str
    points: int
    unit_price_yuan: float
    total_yuan: float


# 06 §3.6 定稿 6 档
PACKAGES: tuple[Package, ...] = (
    Package("starter", "体验/起充", 3_000, 0.0179, 53.7),
    Package("basic", "基础", 5_000, 0.0169, 84.5),
    Package("standard", "标准", 10_000, 0.0150, 150.0),
    Package("advanced", "进阶", 30_000, 0.0130, 390.0),
    Package("pro", "专业", 50_000, 0.0120, 600.0),
    Package("enterprise", "企业", 100_000, 0.0110, 1_100.0),
)

MAX_PACKAGE_POINTS = 100_000           # 超出转人工报价，不在提交页临时支付
TRIAL_BONUS = 500                       # 试用通过赠积分
FIRST_RECHARGE_BONUS_RATE = 0.10        # 首次充值赠 10%


def package_for_points(points: int) -> Package | None:
    """按积分值反查档位（用于兑换码/核销）；超出上限返回 None（人工报价）。"""
    for pkg in PACKAGES:
        if pkg.points == points:
            return pkg
    return None


def redeemed_points(pkg: Package, *, first_recharge: bool) -> int:
    """兑换码实际到账积分：档位积分 + 首充 10%（06 §3.6）。"""
    bonus = int(pkg.points * FIRST_RECHARGE_BONUS_RATE) if first_recharge else 0
    return pkg.points + bonus
