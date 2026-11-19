"""USPS 网页采集 Provider 适配层（02：错误分类、fail-closed、ClawBrowser/CDP、解析）。"""

from worker.provider.errors import (  # noqa: F401
    ErrorRule, RULES, RETRYABLE, TERMINAL, COUNTS_FAILURE,
    DEFAULT_MAX_ATTEMPTS, ProviderError, rule_for, is_retryable,
    next_task_state, backoff_seconds,
)
