"""USPS Web Provider：fail-closed + 完整采集编排（模块 02 §3.1 / §4）。

关键不变量（02 §1.2 / §3.3 / §4.3）：
- 默认 enabled=false；未通过 Linux 运行验收前调用一律 fail-closed，无 mock 回退。
- 门禁通过后编排：collect_page → 页面校验(§5.2) → L3 解析 → 逐项映射 →
  八道闸门(§5.3.2) → ProviderResult。批次级拒绝整批停止，单项失败独立携带
  item_error_class（§5.4），不猜结果、不伪造轨迹。
- Provider 不写库、不决定计费；simulated/source 缺失按 source_invalid 拒绝。

executor 需提供 collect_page(numbers) -> CollectedPage（ClawExecutor 协议）；
未注入即视为未验收（runtime_missing）。
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone

from worker.provider.contracts import (
    ProviderEvent, ProviderInput, ProviderItem, ProviderResult,
)
from worker.provider.errors import ProviderError
from worker.provider.usps_web.parser import parse_html
from worker.provider.usps_web.validator import quality_gates, verify_page

PAGE_BATCH_LIMIT = 35
_TIME_HAS_CLOCK = re.compile(r"\d{1,2}:\d{2}")


def _event_fingerprint(number: str, detail: str, date_raw: str) -> str:
    raw = f"{number}|{detail}|{date_raw}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _time_confidence(date_raw: str) -> str:
    """页面给精确时分=exact，仅日期/时间段=low（02 §5.3.1 第4条）。"""
    return "exact" if _TIME_HAS_CLOCK.search(date_raw) else "low"


def _evidence_ref(html: str) -> str:
    """脱敏证据引用：只存哈希引用，不落原始 HTML（02 §5.6）。"""
    return "ref://sha256:" + hashlib.sha256(html.encode()).hexdigest()[:16]


class UspsWebProvider:
    """真实 usps_web Provider，默认禁用且 fail-closed。"""

    provider_code = "usps_web"

    def __init__(self, *, enabled: bool = False,
                 emergency_stop: bool = False,
                 circuit_open: bool = False,
                 executor=None,
                 provider_config_version: str = "",
                 parser_version: str = "v1") -> None:
        self.enabled = enabled
        self.emergency_stop = emergency_stop
        self.circuit_open = circuit_open
        self.executor = executor
        self.provider_config_version = provider_config_version
        self.parser_version = parser_version

    def _guard(self) -> None:
        """启用前门禁（02 §3.1 检查 enabled/emergency_stop/circuit_open）。"""
        if not self.enabled:
            raise ProviderError("provider_disabled", "usps_web 未启用")
        if self.emergency_stop:
            raise ProviderError("provider_unavailable", "紧急停止中")
        if self.circuit_open:
            raise ProviderError("circuit_open", "熔断已开，冷却后半开探路")
        if self.executor is None or not hasattr(self.executor, "collect_page"):
            raise ProviderError("runtime_missing", "未注入已验收的 ClawExecutor")

    def fetch(self, inputs: list[ProviderInput]) -> ProviderResult:
        """批量查询（02 §4）；内部按 35 切片，逐页校验/解析/闸门。"""
        self._guard()
        if not inputs:
            return ProviderResult(provider_config_version=self.provider_config_version)
        fetched_at = datetime.now(timezone.utc)
        all_items: list[ProviderItem] = []
        batch_errors: list[str] = []

        for start in range(0, len(inputs), PAGE_BATCH_LIMIT):
            chunk = inputs[start:start + PAGE_BATCH_LIMIT]
            page = self.executor.collect_page([i.normalized_number for i in chunk])
            verdict = verify_page(page.html, http_status=page.http_status,
                                  warmed_up=page.warmed_up)
            if not verdict.valid or verdict.page_class not in ("results", "not_found"):
                # 批次级失败：整批停止，每项都标同一 batch error（§5.4）。
                ec = verdict.error_class or "page_type_unknown"
                batch_errors.append(ec)
                for inp in chunk:
                    all_items.append(ProviderItem.fail(
                        inp.normalized_number, ec, batch_level=True,
                        source="usps_web", page_class=verdict.page_class,
                        http_status=page.http_status, parser_version=self.parser_version,
                        fetched_at=fetched_at))
                continue
            self._map_page(chunk, page.html, verdict.page_class,
                           fetched_at, all_items)

        return ProviderResult(
            items=all_items,
            provider_config_version=self.provider_config_version,
            fetched_at=fetched_at,
            batch_error_class=batch_errors[0] if batch_errors else None,
        )

    def _map_page(self, chunk: list[ProviderInput], html: str, page_class: str,
                  fetched_at: datetime, out: list[ProviderItem]) -> None:
        """把一页解析结果逐项映射到目标单号，过闸门后写入结果列表。"""
        parsed = {p.tracking_number: p for p in parse_html(html)}
        evidence = _evidence_ref(html)
        for inp in chunk:
            p = parsed.get(inp.normalized_number)
            if p is None:
                # 单号绑定失败：按 parse_failed（02 §5.2 第4条），不按页面顺序猜。
                out.append(ProviderItem.fail(
                    inp.normalized_number, "parse_failed",
                    source="usps_web", page_class=page_class, page_valid=True,
                    http_status=200, parser_version=self.parser_version,
                    raw_payload_ref=evidence, fetched_at=fetched_at))
                continue
            events = [ProviderEvent(
                event_fingerprint=_event_fingerprint(inp.normalized_number,
                                                     e.detail, e.date_raw),
                occurred_at=e.date,
                status=e.status_key,
                description_raw=e.detail,
                description_zh=e.label_zh,
                location=e.location,
                event_code=e.status_key,
                time_confidence=_time_confidence(e.date_raw),
            ) for e in p.events]
            item = ProviderItem.succeed(
                normalized_number=inp.normalized_number,
                source="usps_web", simulated=False,
                status=p.current_status_key,
                raw_status=p.summary_text,
                events=events,
                page_class=page_class, page_valid=True, http_status=200,
                confidence=1.0 if p.events else 0.7,
                parser_version=self.parser_version,
                raw_payload_ref=evidence,
                fetched_at=fetched_at,
            )
            gate = quality_gates(item, expected_number=inp.normalized_number,
                                 parser_version=self.parser_version,
                                 payload_ref=evidence)
            if not gate.passed:
                item.item_error_class = gate.error_class
            out.append(item)
