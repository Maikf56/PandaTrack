"""登录防爆破（09 §5.1 速率保护）：失败计数 + 指数锁定。

设计（03 §1 高风险操作/09 分类 5）：
- 维度 scope（customer/admin）+ key；key 同时记两级：
  `{ip}|{identifier}`（单源爆破）与 `*|{identifier}`（跨源撞库）。
- 窗口 10 分钟内失败 ≥5 次 → 锁定，锁时长 30s 起指数翻倍，上限 1h。
- 登录成功即清零；状态持久化 B 库 auth_throttle，重启不清零。
- 锁定期间返回 RATE_LIMITED（429）并附 retry_after_seconds，不泄露账号存在性。
"""
from __future__ import annotations

from datetime import datetime, timezone

WINDOW_SECONDS = 600
MAX_ATTEMPTS = 5
BASE_LOCK_SECONDS = 30
MAX_LOCK_SECONDS = 3600


def locked_retry_after(locked_until) -> int | None:
    """锁定中返回剩余秒数（≥1）；未锁/已过期/非法值返回 None。

    类型守卫：repo 桩（MagicMock）等非 datetime 返回值按未锁处理，
    避免测试桩/异常数据被误判为已锁定。
    """
    if not isinstance(locked_until, datetime):
        return None
    if locked_until.tzinfo is None:
        locked_until = locked_until.replace(tzinfo=timezone.utc)
    remaining = int((locked_until - datetime.now(timezone.utc)).total_seconds())
    return max(1, remaining) if remaining > 0 else None


def next_lock_seconds(fail_count: int, *,
                      max_attempts: int = MAX_ATTEMPTS,
                      base_lock: int = BASE_LOCK_SECONDS,
                      max_lock: int = MAX_LOCK_SECONDS) -> int:
    """fail_count 已含本次失败；未达阈值返回 0，否则 30s×2^over 封顶 1h。"""
    if fail_count < max_attempts:
        return 0
    over = fail_count - max_attempts
    return min(base_lock * (2 ** over), max_lock)


def throttle_keys(ip: str, identifier: str) -> list[str]:
    """一次登录需要检查/计数的两级 key：单源 + 跨源。"""
    return [f"{ip}|{identifier}", f"*|{identifier}"]


def client_ip(request) -> str:
    """取客户端 IP：nginx 前置下信任 X-Forwarded-For 首跳，兜底直连地址。"""
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        first = xff.split(",")[0].strip()
        if first:
            return first[:64]
    host = getattr(request, "client", None)
    return (host.host if host and getattr(host, "host", None) else "unknown")
