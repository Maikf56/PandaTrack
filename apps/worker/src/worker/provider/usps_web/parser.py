"""USPS 结果页解析器（模块 02，页面类型识别 + 多单号结果解析 + 12 态映射）。

实测页面结构（2026-11 真实批量结果页源码，22 单号样本）：
- 每个单号一个 <div class="product_summary"> 块；
  内含 <span class="tracking-number">单号</span>。
- 汇总状态: <p class="banner-content statusSummaryText">白话描述</p>，
  外层 banner-wrapper 带 banner-N 数字类别码。
- 事件列表: <div class="tb-step [current-step]">
    <p class="tb-status">汇总状态</p>            (仅 current-step 有)
    <p class="tb-status-detail">事件原文</p>
    <p class="tb-location">地点</p>
    <p class="tb-date"> November 10, 2026 11:06 AM </p>
  </div>

02 §225: 批量页每个结果容器独立绑定对应单号，绑定失败按 parse_failed
处理，不得按页面顺序猜测。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

from pandatrack_common.status import ALL_STATUSES, OTHER

from .status_data import MAPPING


@dataclass
class ParsedEvent:
    """单条轨迹事件（采集侧原始事实，写库前还需过质量闸门）。"""

    detail: str                 # 事件状态原文（tb-status-detail）
    location: str               # 地点原文（tb-location）
    date_raw: str               # 日期原文（tb-date）
    date: datetime | None       # 解析后的本地时间（页面未标注时区）
    is_current: bool            # 是否 current-step（页面标注的当前状态）
    status_key: str             # 12 态映射结果；未登记文本为 "other"
    label_zh: str               # 中文白话标签


@dataclass
class ParsedTracking:
    """单个单号的解析结果。"""

    tracking_number: str
    summary_text: str           # statusSummaryText 白话描述
    banner_code: str | None     # banner-N 类别码
    current_status_key: str     # 当前 12 态
    events: list[ParsedEvent] = field(default_factory=list)


class PageClassificationError(Exception):
    """页面类型无法识别（02 §5.1: page_type_unknown，TERMINAL fail-closed）。"""


def classify_page(html: str) -> str:
    """页面类型识别。

    返回: results / not_found / challenge / blocked / unknown
    """
    if "tb-step" in html and "product_summary" in html:
        return "results"
    low = html.lower()
    if "akamai" in low or "reference&#32;#" in low or "access denied" in low:
        return "blocked"
    if "we could not find" in low or "no records found" in low \
            or "tracking information is not available" in low:
        return "not_found"
    if "challenge" in low or "captcha" in low or "press & hold" in low:
        return "challenge"
    return "unknown"


# 时间部分可选：部分事件（如 "Reminder to Schedule Redelivery"）页面只给日期。
_DATE_RE = re.compile(
    r"([A-Z][a-z]+)\s+(\d{1,2}),\s+(\d{4})"
    r"(?:\s+(\d{1,2}):(\d{2})\s*(AM|PM)?)?",
    re.IGNORECASE,
)
_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
}
_TN_RE = re.compile(r"^\d{10,34}$")


def parse_date(text: str) -> datetime | None:
    """解析 tb-date 文本（页面为目的地当地时间，未含时区标注）。"""
    m = _DATE_RE.search(text)
    if not m:
        return None
    mon = _MONTHS.get(m.group(1).lower())
    if not mon:
        return None
    # 只有日期无时刻时按当日 00:00 记（日期是页面事实，时刻缺失不猜具体值）。
    hour = int(m.group(4)) if m.group(4) is not None else 0
    minute = int(m.group(5)) if m.group(5) is not None else 0
    ampm = (m.group(6) or "").upper()
    if ampm == "PM" and hour < 12:
        hour += 12
    elif ampm == "AM" and hour == 12:
        hour = 0
    try:
        return datetime(int(m.group(3)), mon, int(m.group(2)), hour, minute)
    except ValueError:
        return None


def map_status(detail: str) -> tuple[str, str]:
    """事件原文 → (12 态 key, 服务端白话标签)。未登记文本归 other。

    MAPPING 的中文为辅助资料逐条直译（保留在 raw 层供追溯）；对外前端白话
    标签一律取服务端权威字典 ALL_STATUSES（04 §426），避免同一状态多种文案。
    """
    hit = MAPPING.get(detail.strip())
    if not hit:
        return (OTHER.key, OTHER.label_zh)
    std = ALL_STATUSES.get(hit[0])
    return (hit[0], std.label_zh if std else OTHER.label_zh)


def _split_product_summaries(html: str) -> list[tuple[str, str]]:
    """按 product_summary 块切分，返回 [(tracking_number, block_html)]。

    绑定依据块内显式的 tracking-number 文本；缺失即绑定失败（调用方按
    parse_failed 计）。
    """
    blocks: list[tuple[str, str]] = []
    parts = html.split('<div class="product_summary"')
    for part in parts[1:]:
        m = re.search(
            r'class="tracking-number"[^>]*>\s*([0-9A-Za-z ]{10,40})\s*<', part)
        if not m:
            continue
        tno = re.sub(r"\s+", "", m.group(1))
        if not _TN_RE.match(tno):
            continue
        blocks.append((tno, part))
    return blocks


def _parse_events(block: str) -> list[ParsedEvent]:
    """从单号块内提取 tb-step 事件列表。"""
    events: list[ParsedEvent] = []
    for chunk in block.split('class="tb-step')[1:]:
        current = chunk.startswith(" current-step")
        dm = re.search(r'class="tb-status-detail">\s*(.*?)\s*</p>', chunk, re.S)
        lm = re.search(r'class="tb-location">\s*(.*?)\s*</p>', chunk, re.S)
        dtm = re.search(r'class="tb-date">\s*(.*?)\s*</p>', chunk, re.S)
        if not dm:
            continue
        detail = re.sub(r"\s+", " ", dm.group(1)).strip()
        location = re.sub(r"\s+", " ", lm.group(1)).strip() if lm else ""
        date_raw = re.sub(r"\s+", " ", dtm.group(1)).strip() if dtm else ""
        key, zh = map_status(detail)
        events.append(ParsedEvent(
            detail=detail, location=location, date_raw=date_raw,
            date=parse_date(date_raw), is_current=current,
            status_key=key, label_zh=zh,
        ))
    return events


def parse_html(html: str) -> list[ParsedTracking]:
    """解析批量结果页，返回按块内显式单号绑定的结果列表。"""
    results: list[ParsedTracking] = []
    for tno, block in _split_product_summaries(html):
        sm = re.search(
            r'class="banner-content statusSummaryText">\s*(.*?)\s*</p>',
            block, re.S)
        if sm is None:
            # 无轨迹明细页（如 counterfeit postage）：捕获 banner-header +
            # banner-content 说明，忠实记录页面事实，不写空 summary。
            hm = re.search(r'class="banner-header">\s*(.*?)\s*</h3>', block, re.S)
            cm = re.search(r'class="banner-content">\s*(.*?)\s*</p>', block, re.S)
            parts = [re.sub(r"\s+", " ", x.group(1)).strip()
                     for x in (hm, cm) if x]
            summary = " - ".join(parts) if parts else ""
        else:
            summary = re.sub(r"\s+", " ", sm.group(1)).strip()
        bm = re.search(r'update-banner-wrapper banner-(\d+)', block)
        events = _parse_events(block)
        current = next((e for e in events if e.is_current), None)
        if current is None and events:
            current = events[0]
        results.append(ParsedTracking(
            tracking_number=tno,
            summary_text=summary,
            banner_code=bm.group(1) if bm else None,
            current_status_key=current.status_key if current else "other",
            events=events,
        ))
    return results
