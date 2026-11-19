"""P2-d 验证：Provider 编排(02 §4/§5.4)与批量调度算法(§3.2/§3.3)。"""
from __future__ import annotations

import json
import random
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "worker" / "src"))

from worker.provider.contracts import ProviderInput  # noqa: E402
from worker.provider.dispatcher import (  # noqa: E402
    consolidate, drop_recent, chunk, assign_slots, human_interval_ms,
    auto_max_environments, plan_next_round, consolidate_all,
)
from worker.provider.usps_claw import CollectedPage  # noqa: E402
from worker.provider.usps_web.provider import UspsWebProvider  # noqa: E402

TNO = "9400150206217997979667"


def result_page(*numbers: str) -> str:
    blocks = []
    for n in numbers:
        blocks.append(
            '<div class="product_summary">'
            f'<span class="tracking-number">{n}</span>'
            '<p class="banner-content statusSummaryText">Delivered</p>'
            '<div class="tb-step current-step">'
            '<p class="tb-status-detail">Delivered</p>'
            '<p class="tb-date">November 10, 2026 11:06 AM</p>'
            '</div></div>')
    return "<html><head><title>x</title></head><body>" + "".join(blocks) + "</body></html>"


class ScriptedExecutor:
    """按调用序返回 CollectedPage；记录每次收到的 numbers。"""

    def __init__(self, pages: list[CollectedPage]):
        self.pages = list(pages)
        self.received: list[list[str]] = []

    def collect_page(self, numbers):
        self.received.append(numbers)
        return self.pages.pop(0)


def page(html, status=200, warmed=True):
    return CollectedPage(html=html, http_status=status, warmed_up=warmed,
                         exit_region="us_texas", exit_ref="ref", profile_ref="p",
                         exit_attempt=1)


def provider(executor):
    return UspsWebProvider(enabled=True, executor=executor,
                           parser_version="v1", provider_config_version="cfg1")


def inp(n, job="j1"):
    return ProviderInput(normalized_number=n, job_ref=job)


class TestProviderPipeline:
    def test_single_success_end_to_end(self):
        ex = ScriptedExecutor([page(result_page(TNO))])
        out = provider(ex).fetch([inp(TNO)])
        assert out.ok
        item = out.items[0]
        assert item.status == "delivered" and item.page_valid
        assert len(item.events) == 1
        assert item.events[0].time_confidence == "exact"
        assert item.parser_version == "v1"
        assert item.raw_payload_ref.startswith("ref://sha256:")
        assert out.provider_config_version == "cfg1"

    def test_missing_target_is_item_parse_failed(self):
        other = "9200000000000000000000"
        ex = ScriptedExecutor([page(result_page(other))])
        out = provider(ex).fetch([inp(TNO)])
        assert not out.ok
        assert out.items[0].item_error_class == "parse_failed"

    def test_batch_level_rejected_stops_all(self):
        ex = ScriptedExecutor([page("", status=403)])
        out = provider(ex).fetch([inp(TNO), inp("9200000000000000000000")])
        assert out.batch_error_class == "rejected"
        assert len(out.items) == 2
        assert all(i.error_class == "rejected" for i in out.items)

    def test_challenge_page_batch_retryable(self):
        challenge_html = "<html><head></head><body><script>"+("x"*150000)+"</script></body></html>"
        ex = ScriptedExecutor([page(challenge_html)])
        out = provider(ex).fetch([inp(TNO)])
        assert out.batch_error_class == "challenge"

    def test_chunk_35_per_page(self):
        numbers = [f"9400000000000000000{i:03d}" for i in range(70)]
        # 两页各 35，均返回空页（批次失败），只验证切片调用。
        ex = ScriptedExecutor([page("", status=403), page("", status=403)])
        out = provider(ex).fetch([inp(n) for n in numbers])
        assert [len(b) for b in ex.received] == [35, 35]
        assert len(out.items) == 70

    def test_partial_success_in_batch(self):
        other = "9200000000000000000000"
        ex = ScriptedExecutor([page(result_page(TNO))])  # 只回了 TNO，other 绑不到
        out = provider(ex).fetch([inp(TNO), inp(other)])
        ok = [i for i in out.items if i.status == "delivered"]
        bad = [i for i in out.items if i.item_error_class == "parse_failed"]
        assert len(ok) == 1 and len(bad) == 1  # 单项失败不影响同批成功项

    def test_event_fingerprint_stable(self):
        ex1 = ScriptedExecutor([page(result_page(TNO))])
        ex2 = ScriptedExecutor([page(result_page(TNO))])
        a = provider(ex1).fetch([inp(TNO)]).items[0].events[0].event_fingerprint
        b = provider(ex2).fetch([inp(TNO)]).items[0].events[0].event_fingerprint
        assert a == b


class TestDispatcherAlgorithms:
    def test_consolidate_keeps_order(self):
        assert consolidate(["b", "a", "b", "c", "a"]) == ["b", "a", "c"]

    def test_drop_recent(self):
        assert drop_recent(["a", "b", "c"], {"b"}) == ["a", "c"]

    def test_chunk(self):
        assert chunk([str(i) for i in range(70)]) == [
            [str(i) for i in range(35)], [str(i) for i in range(35, 70)]]

    def test_chunk_rejects_bad_size(self):
        try:
            chunk(["a"], 0)
            assert False
        except ValueError:
            pass

    def test_assign_slots_generations(self):
        batches = chunk([str(i) for i in range(250)])  # 8 页
        a = assign_slots(batches, max_environments=5)
        assert a.generation_count == 1  # 8 标签页 <10，同一代
        assert all(s["environment"] in range(5) for s in a.slots)
        batches2 = chunk([str(i) for i in range(500)])  # 15 页
        a2 = assign_slots(batches2, 5)
        assert a2.generation_count == 2  # 第 10 页进入下一代

    def test_assign_slots_rejects_zero(self):
        try:
            assign_slots([["a"]], 0)
            assert False
        except ValueError:
            pass

    def test_human_interval_range(self):
        rng = random.Random(42)
        for _ in range(50):
            ms = human_interval_ms(2500, rng)
            assert 1500 <= ms <= 3500  # 0.6~1.4 倍

    def test_auto_max_environments(self):
        assert auto_max_environments(4096) == (4096 - 900) // 550  # 公式,无硬上限
        assert auto_max_environments(4096, explicit=3) == 3  # 显式优先
        assert auto_max_environments(100) == 2  # 下限 2
        assert auto_max_environments(100000) == (100000 - 900) // 550  # 无硬编码上限

    def test_plan_next_round(self):
        items = [
            {"number": "a", "error_class": None},          # 成功
            {"number": "b", "error_class": "challenge"},   # 可回炉
            {"number": "c", "error_class": "rejected"},    # 终态
            {"number": "d", "error_class": "never_seen"},  # 未知→终态
        ]
        plan = plan_next_round(items, max_rounds=3, current_round=1)
        assert plan.retry_numbers == ["b"]
        assert set(plan.terminal_numbers) == {"c", "d"}

    def test_plan_next_round_max_reached(self):
        plan = plan_next_round([{"number": "b", "error_class": "challenge"}],
                               max_rounds=3, current_round=3)
        assert plan.retry_numbers == [] and plan.terminal_numbers == ["b"]

    def test_consolidate_all_two_layers(self):
        subs = [["a", "b"], ["b", "c"], ["c", "d", "e"]]
        out = consolidate_all(subs, recently_ok={"c"})
        assert out == ["a", "b", "d", "e"]
