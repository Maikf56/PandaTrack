"""金丝雀单号监控（吸收《爬虫方案分析》§5.3，08 运维增强）。

SPA 改版不通知人（管线半衰期 3-6 个月）。维护一组**已知状态的测试单号**，
每轮调度前用同一采集管线验证解析结果与预期一致；不一致即告警
（error_class=parse_monitor 语义，由调用方决定回炉/停轮），防止把改版
后的脏页当成功解析入库污染事实源。

纯逻辑：evaluate 只消费「单号 → 12 态 key」映射，采集来源由调用方注入。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass


@dataclass(slots=True)
class CanarySpec:
    """一条金丝雀：单号 + 预期 12 态 key。"""
    number: str
    expected_status_key: str


@dataclass(slots=True)
class CanaryMismatch:
    number: str
    reason: str          # missing | status_mismatch
    expected: str
    actual: str          # missing 时为 ""


def evaluate(
    results: dict[str, str],
    specs: list[CanarySpec],
) -> list[CanaryMismatch]:
    """对照采集结果与金丝雀预期，返回不一致清单（空 = 全部通过）。

    - 单号不在结果里（绑定失败/漏块）→ missing；
    - 状态 key 与预期不符 → status_mismatch。
    """
    mismatches: list[CanaryMismatch] = []
    for spec in specs:
        actual = results.get(spec.number)
        if actual is None:
            mismatches.append(CanaryMismatch(
                number=spec.number, reason="missing",
                expected=spec.expected_status_key, actual=""))
        elif actual != spec.expected_status_key:
            mismatches.append(CanaryMismatch(
                number=spec.number, reason="status_mismatch",
                expected=spec.expected_status_key, actual=actual))
    return mismatches


def load_specs(raw: str | None = None) -> list[CanarySpec]:
    """从环境变量 PT_CANARY_SPEC 加载金丝雀清单（JSON 数组）。

    格式: [{"number": "...", "expected": "delivered"}, ...]
    未配置或格式损坏 → 空清单（金丝雀未启用，不阻塞主流程）。
    """
    text = raw if raw is not None else os.environ.get("PT_CANARY_SPEC", "")
    if not text.strip():
        return []
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return []
    if not isinstance(data, list):
        return []
    specs: list[CanarySpec] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        number = str(item.get("number", "")).strip()
        expected = str(item.get("expected", "")).strip()
        if number and expected:
            specs.append(CanarySpec(number=number, expected_status_key=expected))
    return specs
