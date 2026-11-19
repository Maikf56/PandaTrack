"""P2-c 验证：ClawExecutor 暖场前置/出口轮换/抓取(02 §3.1/§66/§5.8)。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "worker" / "src"))

from worker.provider.errors import ProviderError  # noqa: E402
from worker.provider.usps_claw import (  # noqa: E402
    ClawExecutor, ExecutorConfig, NoopRelayControl, CollectedPage,
)

NUMBERS = ["9400150206217997979667"]


class FakeRunner:
    """可编排的 clawctl 模拟：按脚本序列返回输出，并记录调用。"""

    def __init__(self, script: list[tuple[str, str]]):
        self.script = script
        self.calls: list[list[str]] = []

    def run(self, argv: list[str], *, timeout: int = 60) -> str:
        self.calls.append(argv)
        if not self.script:
            return ""
        keyword, out = self.script.pop(0)
        assert keyword in " ".join(argv), f"期望 {keyword!r} 实际 {argv}"
        return out


def cfg(**kw):
    base = dict(warmup_wait_s=0, page_wait_s=0, switch_wait_s=0)
    base.update(kw)
    return ExecutorConfig(**base)


def ok_script(html="<html><title>x</title><div class='tb-step'>ok</div></html>"):
    """暖场成功→跟踪页有1事件→抓取HTML 的标准成功序列。"""
    return [
        ("open", ""),                                              # 暖场 open 首页
        ("eval", json.dumps({"len": 7100})),                      # 暖场 len>1000
        ("open", ""),                                              # 跟踪页 open
        ("eval", json.dumps({"len": 4800, "tb": 1, "ps": 1,        # 页面状态
                             "title": "USPS", "abckNeg": False})),
        ("eval", json.dumps(html)),                                # 抓取 outerHTML
    ]


class TestWarmupPrerequisite:
    def test_success_path_warms_up_before_tracking(self):
        runner = FakeRunner(ok_script())
        ex = ClawExecutor(runner, NoopRelayControl(), config=cfg(rotate_states=False))
        page = ex.collect_page(NUMBERS)
        assert isinstance(page, CollectedPage) and page.warmed_up
        assert page.html.startswith("<html>") and page.exit_attempt == 1
        # 前两条命令：open 首页 → eval 暖场检查（证明暖场在跟踪页 open 之前）。
        cmds = [" ".join(c) for c in runner.calls]
        assert "https://www.usps.com/" in cmds[0]
        assert "innerText.length" in cmds[1]
        assert "tLabels=" in cmds[2]

    def test_warmup_failure_switches_exit(self):
        # 第1出口暖场失败(len=0)，第2出口暖场成功 → 走第2出口。
        script = [
            ("open", ""), ("eval", json.dumps({"len": 0})),        # 出口1 暖场失败
            ("open", ""), ("eval", json.dumps({"len": 7100})),     # 出口2 暖场成功
            ("open", ""), ("eval", json.dumps({"len": 4800, "tb": 1})),
            ("eval", json.dumps("<html>ok</html>")),
        ]
        relay = NoopRelayControl()
        runner = FakeRunner(script)
        ex = ClawExecutor(runner, relay, config=cfg(rotate_states=False))
        page = ex.collect_page(NUMBERS)
        assert page.exit_attempt == 2
        assert len(relay.regions) == 2  # 换了两次出口

    def test_challenge_switches_exit_not_wait(self):
        # 暖场成功但跟踪页空正文(abckNeg) → challenge，换出口；不重复 eval 等待。
        script = [
            ("open", ""), ("eval", json.dumps({"len": 7100})),
            ("open", ""), ("eval", json.dumps({"len": 0, "tb": 0, "abckNeg": True})),
            ("open", ""), ("eval", json.dumps({"len": 7100})),     # 出口2 重新暖场
            ("open", ""), ("eval", json.dumps({"len": 4800, "tb": 1})),
            ("eval", json.dumps("<html>ok</html>")),
        ]
        relay = NoopRelayControl()
        ex = ClawExecutor(FakeRunner(script), relay, config=cfg(rotate_states=False))
        page = ex.collect_page(NUMBERS)
        assert page.exit_attempt == 2
        assert relay.regions[0] != relay.regions[1]

    def test_bad_exit_geo_skips_browser(self):
        class BadGeo(NoopRelayControl):
            def exit_geo(self):
                return {"countryCode": "US", "hosting": True}  # 机房IP不合格
        runner = FakeRunner([])  # 不合格出口不应启动浏览器
        ex = ClawExecutor(runner, BadGeo(), config=cfg(rotate_states=False, max_exits=2))
        try:
            ex.collect_page(NUMBERS)
            assert False, "应抛 ProviderError"
        except ProviderError as e:
            assert e.error_class == "probe_bad_status"
        assert runner.calls == []  # 从未启动浏览器

    def test_all_exits_fail_is_challenge(self):
        script = []
        for _ in range(2):
            script += [("open", ""), ("eval", json.dumps({"len": 7100})),
                       ("open", ""), ("eval", json.dumps({"len": 0, "tb": 0}))]
        ex = ClawExecutor(FakeRunner(script), NoopRelayControl(),
                          config=cfg(rotate_states=False, max_exits=2))
        try:
            ex.collect_page(NUMBERS)
            assert False
        except ProviderError as e:
            assert e.error_class == "challenge"


class TestExecutorGuards:
    def test_reject_batch_over_35(self):
        ex = ClawExecutor(FakeRunner([]), NoopRelayControl(), config=cfg())
        try:
            ex.collect_page([str(i) for i in range(36)])
            assert False
        except ProviderError as e:
            assert e.error_class == "not_accepted"

    def test_reject_empty_batch(self):
        ex = ClawExecutor(FakeRunner([]), NoopRelayControl(), config=cfg())
        try:
            ex.collect_page([])
            assert False
        except ProviderError as e:
            assert e.error_class == "not_accepted"

    def test_rotate_states_randomizes_order(self):
        # 注入固定随机源，验证州级池顺序被打乱（批间换池）。
        class R:
            def shuffle(self, x):
                x.reverse()
        runner = FakeRunner([])
        relay = NoopRelayControl()
        ex = ClawExecutor(runner, relay, config=cfg(rotate_states=True, max_exits=6),
                          randomizer=R())
        try:
            ex.collect_page(NUMBERS)
        except ProviderError:
            pass
        assert relay.regions[0] == "us"  # 反转后首个是兜底泛美

    def test_collected_page_exit_ref_masked(self):
        ex = ClawExecutor(FakeRunner(ok_script()), NoopRelayControl(),
                          config=cfg(rotate_states=False))
        page = ex.collect_page(NUMBERS)
        assert page.exit_ref.startswith("12.3") and len(page.exit_ref) <= 12

    def test_cleanup_removes_profile(self):
        runner = FakeRunner([("profiles", "")])
        ex = ClawExecutor(runner, NoopRelayControl(), config=cfg())
        ex.cleanup()
        assert "profiles" in " ".join(runner.calls[-1]) and "rm" in runner.calls[-1]
