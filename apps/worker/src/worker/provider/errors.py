"""Provider 错误分类契约（模块 02 §5.1 权威矩阵）。

本模块是 15 类 error_class 的唯一权威源，供 Provider、BatchDispatcher 与
模块 07 调度器共同消费。裁定要点（11 号文档 D4）：
- `challenge` 可换州级出口回炉，最多 max_attempts=3；
- `page_type_unknown` / `quality_gate_rejected` 为终态（不猜、不回炉）；
- `circuit_open` 冷却半开、不计入连续失败阈值。

禁止把本模块的内部 error_class 直接暴露给客户（对外码见 09 codes.py）。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ErrorRule:
    """单类错误的处置规则。

    retryable     是否允许自动重试（换出口/换环境/回炉）。
    task_state    未超限时的任务状态；超限或终态类走 dead_letter。
    action        处置动作（与 02 §5.1 / §5.8 对齐）。
    alert         告警级别（INFO/WARN/ERROR/CRITICAL）。
    backoff_s     退避序列（秒）；空表示不按退避、由调度层换出口立即重试。
    counts_failure 是否计入连续失败/熔断阈值（circuit_open 半开探路不计）。
    """

    error_class: str
    retryable: bool
    task_state: str
    action: str
    alert: str
    backoff_s: tuple[int, ...] = ()
    counts_failure: bool = True


# 02 §5.1 完整矩阵（15 类，含 not_found 有效结果）。
RULES: dict[str, ErrorRule] = {
    # —— 配置/运行时类：fail-closed，不重试 ——
    "provider_disabled": ErrorRule(
        "provider_disabled", False, "dead_letter", "不发起请求", "ERROR"),
    "provider_unavailable": ErrorRule(
        "provider_unavailable", False, "dead_letter", "不发起请求", "ERROR"),
    "provider_config_unavailable": ErrorRule(
        "provider_config_unavailable", False, "dead_letter", "不发起请求", "ERROR"),
    "runtime_missing": ErrorRule(
        "runtime_missing", False, "dead_letter", "保持 fail closed", "ERROR"),
    "not_accepted": ErrorRule(
        "not_accepted", False, "dead_letter", "保持 fail closed", "ERROR"),
    # —— 熔断：冷却半开，不计连续失败 ——
    "circuit_open": ErrorRule(
        "circuit_open", True, "retry_scheduled", "冷却期后半开探路", "WARN",
        counts_failure=False),
    # —— 上游阻断：challenge 可换出口回炉；rejected/quota 整批终态 ——
    "challenge": ErrorRule(
        "challenge", True, "retry_scheduled", "换州级出口回炉（≤3次）", "CRITICAL"),
    "rejected": ErrorRule(
        "rejected", False, "dead_letter", "整批终态失败，积分冲正", "CRITICAL"),
    "quota": ErrorRule(
        "quota", False, "dead_letter", "整批终态失败；有Retry-After按提示等待", "CRITICAL"),
    # —— 临时异常：有限重试 + 退避抖动 ——
    "upstream_5xx": ErrorRule(
        "upstream_5xx", True, "retry_scheduled", "保持已验证速率，不加压", "WARN",
        backoff_s=(5, 15, 45)),
    "network_timeout": ErrorRule(
        "network_timeout", True, "retry_scheduled", "记录profile健康，同profile不并发", "WARN",
        backoff_s=(5, 15, 45)),
    "browser_crash": ErrorRule(
        "browser_crash", True, "retry_scheduled", "暂停该profile，换新环境", "WARN",
        backoff_s=(5, 15, 45)),
    # —— 准入层：查询前换候选出口 ——
    "proxy_gateway_unreachable": ErrorRule(
        "proxy_gateway_unreachable", True, "retry_scheduled", "换候选出口，不启动浏览器", "WARN"),
    "probe_bad_status": ErrorRule(
        "probe_bad_status", True, "retry_scheduled", "换出口，不进入查询页", "WARN"),
    "probe_empty_body": ErrorRule(
        "probe_empty_body", True, "retry_scheduled", "换出口，不进入查询页", "WARN"),
    # —— 会话软限流 ——
    "soft_throttled": ErrorRule(
        "soft_throttled", True, "retry_scheduled", "整批换出口回炉", "WARN"),
    # —— 解析/质量：终态，不猜 ——
    "page_type_unknown": ErrorRule(
        "page_type_unknown", False, "dead_letter", "暂停写库，分类器工单", "ERROR"),
    "parse_failed": ErrorRule(
        "parse_failed", True, "retry_scheduled", "同一配置受控重取一次", "ERROR"),
    "quality_gate_rejected": ErrorRule(
        "quality_gate_rejected", False, "dead_letter", "保留证据，不写事实", "ERROR"),
    # —— 数据库/outbox：由事务回滚与租约回收处理 ——
    "db_or_outbox_error": ErrorRule(
        "db_or_outbox_error", True, "retry_scheduled", "回滚，等待租约回收", "ERROR"),
    # —— 来源无效：模拟/缺失来源字段，fail-closed ——
    "source_invalid": ErrorRule(
        "source_invalid", False, "dead_letter", "拒绝写入模拟或来源不明结果", "ERROR"),
    # —— 有效事实：非失败 ——
    "not_found": ErrorRule(
        "not_found", False, "succeeded", "正常结束，status=not_found", "INFO"),
}

# 快速分组（供调度器做集合判断）。
RETRYABLE = frozenset(k for k, r in RULES.items() if r.retryable)
TERMINAL = frozenset(k for k, r in RULES.items() if not r.retryable)
COUNTS_FAILURE = frozenset(k for k, r in RULES.items() if r.counts_failure)

DEFAULT_MAX_ATTEMPTS = 3


class ProviderError(Exception):
    """Provider 失败异常，携带 02 §5.1 error_class 与脱敏证据。

    detail 只进受控审计日志，不得直接进入客户可见响应（09 §3）。
    """

    def __init__(self, error_class: str, detail: str = "", *,
                 evidence: dict | None = None):
        if error_class not in RULES:
            raise ValueError(f"未登记的 error_class: {error_class}")
        super().__init__(f"{error_class}: {detail}" if detail else error_class)
        self.error_class = error_class
        self.detail = detail
        self.evidence = evidence or {}

    @property
    def rule(self) -> ErrorRule:
        return RULES[self.error_class]


def rule_for(error_class: str) -> ErrorRule:
    """取处置规则；未知类按 page_type_unknown 安全降级（不猜）。"""
    return RULES.get(error_class, RULES["page_type_unknown"])


def is_retryable(error_class: str) -> bool:
    return rule_for(error_class).retryable


def next_task_state(error_class: str, attempt: int,
                    max_attempts: int = DEFAULT_MAX_ATTEMPTS) -> str:
    """按类别与尝试次数给出任务状态。

    - not_found：始终 succeeded（有效事实）。
    - 不可重试类：dead_letter。
    - 可重试类：attempt < max_attempts 时才 retry_scheduled，否则 dead_letter。
    - circuit_open：冷却半开不计入阈值，只要熔断已开就允许一次探路。
    """
    r = rule_for(error_class)
    if error_class == "not_found":
        return "succeeded"
    if error_class == "circuit_open":
        return "retry_scheduled"
    if not r.retryable:
        return "dead_letter"
    return "retry_scheduled" if attempt < max_attempts else "dead_letter"


def backoff_seconds(error_class: str, attempt: int) -> int:
    """退避秒数（attempt 从 1 计）；无退避序列返回 0。"""
    seq = rule_for(error_class).backoff_s
    if not seq or attempt < 1:
        return 0
    return seq[min(attempt - 1, len(seq) - 1)]
