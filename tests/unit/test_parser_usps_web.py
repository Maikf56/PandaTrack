"""L3 解析器验证：在真实 USPS 批量结果页源码上离线验证（22 单号 / 230 事件样本）。

样本: 开发文档/02_辅助资料/USPS查询结果页的源码.txt（真实页面，非合成）。
该样本属辅助资料、不入库；服务器可用 PT_USPS_SAMPLE 环境变量指定其路径
（如 ~/.pandatrack-secrets/usps_sample.html）。缺省路径不存在时相关用例 skip，
不影响纯逻辑用例。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "worker" / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "packages" / "common" / "src"))

from worker.provider.usps_web.parser import (  # noqa: E402
    classify_page, map_status, parse_date, parse_html,
)
from pandatrack_common.status import ALL_STATUSES  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
_DEFAULT = ROOT / "开发文档" / "02_辅助资料" / "USPS查询结果页的源码.txt"
SAMPLE = Path(os.environ["PT_USPS_SAMPLE"]) if os.environ.get("PT_USPS_SAMPLE") else _DEFAULT
needs_sample = pytest.mark.skipif(
    not SAMPLE.exists(), reason=f"真实页样本缺失: {SAMPLE}（设 PT_USPS_SAMPLE）")


class TestPageClassification:
    @needs_sample
    def test_real_page_is_results(self):
        assert classify_page(SAMPLE.read_text(encoding="utf-8")) == "results"

    def test_block_page(self):
        assert classify_page("<html>Access Denied reference#</html>") == "blocked"

    def test_not_found_page(self):
        assert classify_page(
            "<html>Tracking information is not available</html>") == "not_found"

    def test_unknown_page(self):
        assert classify_page("<html>hello</html>") == "unknown"


@needs_sample
class TestRealSampleParse:
    """真实源码端到端解析（L3 核心验收）。"""

    def setup_method(self):
        self.results = parse_html(SAMPLE.read_text(encoding="utf-8"))

    def test_all_22_numbers_bound(self):
        # 页面 URL 显示 22 个单号，每个 product_summary 必须独立绑定
        assert len(self.results) == 22
        nums = {r.tracking_number for r in self.results}
        assert len(nums) == 22, "单号去重后应仍是 22 个（不得重复绑定）"

    def test_all_events_have_detail(self):
        total = sum(len(r.events) for r in self.results)
        assert total >= 200, f"事件总数应≈230，实际 {total}"
        for r in self.results:
            for e in r.events:
                assert e.detail, f"{r.tracking_number} 存在空事件"

    def test_dates_all_parsed(self):
        bad = [e for r in self.results for e in r.events if e.date is None]
        assert not bad, f"{len(bad)} 个事件日期解析失败，如 {bad[:2]}"

    def test_current_step_present(self):
        # 有轨迹明细的单号才应有 current-step；无明细单号（如 counterfeit
        # postage 页面明确不展示）是合法事实，不强制当前步。
        no_current = [r.tracking_number for r in self.results
                      if r.events and not any(e.is_current for e in r.events)]
        assert not no_current, f"有明细却缺 current-step 的单号: {no_current}"

    def test_no_detail_numbers_carry_banner_fact(self):
        # 无轨迹明细的单号必须忠实记录页面 banner 事实（不写空 summary）。
        empty = [r for r in self.results if not r.events]
        assert empty, "样本应含无明细单号"
        known = ("tracking not displayed", "tracking not available")
        for r in empty:
            assert r.summary_text, f"{r.tracking_number} 无明细且未记录 banner 文案"
            assert r.summary_text.lower().startswith(known), \
                f"{r.tracking_number} 未记录合法的 no-detail banner: {r.summary_text!r}"

    def test_status_mapping_coverage(self):
        # 映射覆盖率：other 占比必须低（大量未登记文本说明清单不足）
        total = sum(len(r.events) for r in self.results)
        other = sum(1 for r in self.results for e in r.events
                    if e.status_key == "other")
        rate = 1 - other / total
        assert rate >= 0.9, f"12 态映射覆盖率 {rate:.1%}（other {other}/{total}）"
        # 映射结果必须是已登记状态
        for r in self.results:
            assert r.current_status_key in ALL_STATUSES

    def test_chronological_order(self):
        # 事件应按时间倒序（页面最新在前）
        for r in self.results:
            ds = [e.date for e in r.events if e.date]
            assert ds == sorted(ds, reverse=True), \
                f"{r.tracking_number} 事件顺序异常"


class TestStatusMap:
    def test_known_texts(self):
        # 标签取服务端权威白话字典（04 §426），非辅助资料逐条直译。
        assert map_status("Delivered") == ("delivered", "已签收")
        assert map_status("Shipping Label Created, USPS Awaiting Item")[0] == "label_created"
        # 2026-11-19 真实采集：结果页用无后缀简写，清单缺此短语，已补映射
        assert map_status("Shipping Label Created")[0] == "label_created"
        assert map_status("Out for Delivery")[0] == "out_for_delivery"
        assert map_status("In Transit to Next Facility")[0] == "in_transit"

    def test_unknown_text_maps_other(self):
        assert map_status("Totally Made Up Status") == ("other", "其他状态")

    def test_date_formats(self):
        assert parse_date("November 10, 2026 11:06 AM").year == 2026
        assert parse_date("November 10, 2026 12:00 PM").hour == 12
        assert parse_date("November 10, 2026 12:05 AM").hour == 0
        assert parse_date("November 10, 2026 11:06 PM").hour == 23
        assert parse_date("garbage") is None
