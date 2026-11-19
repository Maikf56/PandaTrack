"""页面校验器与八道质量闸门（模块 02 §5.2 / §5.3.2）。

职责边界：
- verify_page()：判定"这是不是可采信的结果页"，只做分类与识别，不解析事实。
  关键区分（02 §66 实测定案）：
    * 未暖场硬拦（空标题 + 大混淆脚本 + abck~-1~）= 会话/探针失败，
      归类 probe_empty_body / page_type_unknown，不等待、不当 challenge；
    * 已完成暖场仍在查询页遇挑战 = challenge，可换州级出口回炉。
- quality_gates()：写库前八道闸门，成功/失败都返回可落 parse_evidence 的 JSON。

本模块为纯逻辑（输入 HTML 字符串），可离线单测；不依赖浏览器/网络。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from pandatrack_common.status import TERMINAL_STATUSES

from worker.provider.contracts import ProviderItem
from worker.provider.usps_web.parser import classify_page

# 大体积混淆脚本阈值（02 §5.1 分类器样本："空标题 + >100KB 脚本"）。
_OBFUSCATED_SCRIPT_MIN = 100_000
_TITLE_RE = re.compile(r"<title[^>]*>\s*(.*?)\s*</title>", re.I | re.S)


@dataclass(slots=True)
class PageVerdict:
    """页面校验结论。"""

    page_class: str              # results / not_found / challenge / blocked / unknown
    error_class: str | None      # 非结果页的错误分类（02 §5.1）
    http_status: int
    valid: bool
    reason: str = ""
    warmed_up: bool = False

    def to_evidence(self) -> dict:
        return {
            "page_class": self.page_class,
            "error_class": self.error_class,
            "http_status": self.http_status,
            "valid": self.valid,
            "reason": self.reason,
            "warmed_up": self.warmed_up,
        }


def _empty_title(html: str) -> bool:
    m = _TITLE_RE.search(html)
    return not m or not m.group(1).strip()


def _big_script(html: str) -> bool:
    """是否存在大体积混淆脚本（近似：整页超大且脚本占比高）。"""
    if len(html) < _OBFUSCATED_SCRIPT_MIN:
        return False
    script_chars = sum(len(s) for s in re.findall(r"<script[^>]*>(.*?)</script>",
                                                  html, re.I | re.S))
    return script_chars > _OBFUSCATED_SCRIPT_MIN // 2


def verify_page(html: str, *, http_status: int = 200,
                warmed_up: bool = True) -> PageVerdict:
    """响应层 + 挑战识别 + 目标页识别（02 §5.2 前三步）。

    参数 warmed_up 表示本会话是否已按 §66 完成 USPS 首页暖场。
    """
    base = {"http_status": http_status, "warmed_up": warmed_up}

    # 1) 响应层校验（§5.2 第 1 步）。
    if http_status == 403:
        return PageVerdict("blocked", "rejected", http_status, False,
                           "HTTP 403 Access Denied", warmed_up)
    if http_status == 429:
        return PageVerdict("blocked", "quota", http_status, False,
                           "HTTP 429 quota", warmed_up)
    if http_status >= 500:
        return PageVerdict("blocked", "upstream_5xx", http_status, False,
                           f"HTTP {http_status}", warmed_up)
    if http_status != 200 or not html.strip():
        cls = "probe_empty_body" if http_status == 200 else "probe_bad_status"
        return PageVerdict("blocked", cls, http_status, False,
                           "空 body 或非 200", warmed_up)

    low = html.lower()
    # 2) 挑战/拒绝识别（§5.2 第 2 步）。
    if "access denied" in low:
        return PageVerdict("blocked", "rejected", http_status, False,
                           "页面含 Access Denied", warmed_up)
    if any(k in low for k in ("captcha", "press & hold", "verify you are human")):
        return PageVerdict("challenge", "challenge", http_status, False,
                           "验证码/身份校验页", warmed_up)
    # 空标题 + 大混淆脚本：暖场未完成 → 探针失败（不等待）；已完成 → challenge。
    if _empty_title(html) and _big_script(html):
        if not warmed_up:
            return PageVerdict("blocked", "probe_empty_body", http_status, False,
                               "未暖场硬拦（空标题+大脚本）", warmed_up)
        return PageVerdict("challenge", "challenge", http_status, False,
                           "查询页挑战（空标题+大脚本）", warmed_up)

    # 3) 目标页识别（§5.2 第 3 步）交给 parser.classify_page。
    pc = classify_page(html)
    if pc == "results":
        return PageVerdict("results", None, http_status, True,
                           "结果容器存在", warmed_up)
    if pc == "not_found":
        return PageVerdict("not_found", None, http_status, True,
                           "页面明确无记录", warmed_up)
    if pc == "blocked":
        return PageVerdict("blocked", "page_type_unknown", http_status, False,
                           "拒绝/封禁页但无法细分", warmed_up)
    if pc == "challenge":
        return PageVerdict("challenge", "challenge", http_status, False,
                           "挑战页", warmed_up)
    return PageVerdict("unknown", "page_type_unknown", http_status, False,
                       "无法分类，拒绝解析", warmed_up)


@dataclass(slots=True)
class GateResult:
    """八道闸门结论（成功/失败都落 parse_evidence）。"""

    passed: bool
    item_ref: str
    failed_gates: list[str] = field(default_factory=list)
    error_class: str | None = None
    evidence: dict = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(self.evidence, ensure_ascii=False, sort_keys=True)


def quality_gates(
    item: ProviderItem,
    *,
    expected_number: str | None = None,
    http_status: int = 200,
    existing_status: str | None = None,
    existing_has_events: bool = False,
    parser_version: str = "",
    payload_ref: str = "",
    transaction_atomic: bool = True,
) -> GateResult:
    """执行八道闸门（02 §5.3.2）。

    existing_* 为库内既有事实，用于闸门 4/5 的终态保护与事件一致性。
    transaction_atomic 由写库层在同事务提交后回填；纯校验阶段默认 True。
    """
    failed: list[str] = []
    ec: str | None = None

    def fail(gate: str, error_class: str):
        failed.append(gate)
        nonlocal ec
        if ec is None or error_class == "quality_gate_rejected":
            ec = error_class

    # 1 目标匹配：结果单号与任务目标完全一致。
    if expected_number is not None and item.normalized_number != expected_number:
        fail("1_target_match", "quality_gate_rejected")
    # 2 页面有效：page_valid + 无错误 + HTTP 200。
    if not (item.page_valid and item.error_class is None
            and item.item_error_class is None and http_status == 200):
        fail("2_page_valid", item.error_class or item.item_error_class
             or "quality_gate_rejected")
    # 3 字段完整：状态存在；事件存在，或明确 not_found。
    if not item.status or (not item.events and item.status != "not_found"):
        fail("3_fields_complete", "parse_failed")
    # 4 终态保护：既有高置信终态不得被低置信新结果改写。
    if (existing_status in TERMINAL_STATUSES
            and item.status != existing_status and item.confidence < 1.0):
        fail("4_terminal_protect", "quality_gate_rejected")
    # 5 事件一致：event_id 不重复；已有事件时新结果不应为空。
    fps = [e.event_fingerprint for e in item.events]
    if len(fps) != len(set(fps)) or (existing_has_events and not item.events):
        fail("5_events_consistent", "quality_gate_rejected")
    # 6 时间置信：每条只能 exact / low。
    if any(e.time_confidence not in ("exact", "low") for e in item.events):
        fail("6_time_confidence", "quality_gate_rejected")
    # 7 解析证据：parser_version + 结构化 raw_payload 引用。
    if not (item.parser_version or parser_version) or not (item.raw_payload_ref or payload_ref):
        fail("7_parse_evidence", "quality_gate_rejected")
    # 8 事务原子：由写库层保证。
    if not transaction_atomic:
        fail("8_transaction_atomic", "quality_gate_rejected")

    evidence = {
        "item_ref": item.ref,
        "expected_number": expected_number[:4] + "****" if expected_number else None,
        "page_class": item.page_class,
        "http_status": http_status,
        "status": item.status,
        "event_count": len(item.events),
        "parser_version": item.parser_version or parser_version,
        "failed_gates": failed,
        "passed": not failed,
    }
    return GateResult(not failed, item.ref, failed, ec, evidence)
