"""P3-c 验证：BatchDispatcher.dispatch 编排(07 §3.3.2/§3.7)。"""
from __future__ import annotations

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "worker" / "src"))

from worker.scheduler.dispatch import (  # noqa: E402
    BatchDispatcher, DispatchConfig, DispatchMetrics,
)


class SyncPool:
    """同步池工厂：submit 立即执行，避免线程不确定性。"""

    def __init__(self):
        self.calls = []

    def __call__(self):
        outer = self

        class P:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def submit(self, fn, *args):
                outer.calls.append(fn)
                return _F(fn(*args))

        return P()


class _F:
    def __init__(self, v):
        self.v = v

    def result(self):
        return self.v


def n(i):
    return f"9400000000000000{i:04d}"


def ok(nodes):
    return [{"number": x, "error_class": None} for x in nodes]


class TestDispatchPipeline:
    def test_consolidate_and_recent_skip(self):
        seen_batches = []

        def exe(batch):
            seen_batches.append(list(batch))
            return ok(batch)

        d = BatchDispatcher(executor=exe, pool_factory=SyncPool())
        results, m = d.dispatch(
            [[n(1), n(2), n(2)], [n(2), n(3)]],
            recently_ok={n(3)},
        )
        assert m.dedup_removed == 2  # 3 duplicates removed from 5 submitted
        assert m.recent_skipped == 1
        assert results[n(3)] == "succeeded"  # 跳过抓取但保留结果
        assert set(results) >= {n(1), n(2), n(3)}

    def test_recent_none_degrades_to_no_dedup(self):
        def exe(batch):
            return ok(batch)

        d = BatchDispatcher(executor=exe, pool_factory=SyncPool())
        results, m = d.dispatch([[n(1)]], recently_ok=None)
        assert m.recent_skipped == 0
        assert results[n(1)] == "succeeded"

    def test_chunk_35_per_page(self):
        batches = []

        def exe(batch):
            batches.append(len(batch))
            return ok(batch)

        d = BatchDispatcher(executor=exe, pool_factory=SyncPool())
        d.dispatch([[n(i) for i in range(70)]])
        assert sorted(batches) == [35, 35]

    def test_generation_rotation(self):
        def exe(batch):
            return ok(batch)

        d = BatchDispatcher(executor=exe, pool_factory=SyncPool())
        _, m = d.dispatch([[n(i) for i in range(400)]])  # 12 batches -> 2 generations
        assert m.generations == 2

    def test_multi_round_retry(self):
        calls = []

        def exe(batch):
            calls.append(1)
            # 第1轮 challenge，第2轮成功。
            if len(calls) == 1:
                return [{"number": x, "error_class": "challenge"} for x in batch]
            return ok(batch)

        d = BatchDispatcher(executor=exe, pool_factory=SyncPool())
        results, m = d.dispatch([[n(1)]])
        assert results[n(1)] == "succeeded"
        assert m.rounds == 2 and m.retry_dispatched == 1

    def test_terminal_stops_no_retry(self):
        calls = []

        def exe(batch):
            calls.append(1)
            return [{"number": x, "error_class": "rejected"} for x in batch]

        d = BatchDispatcher(executor=exe, pool_factory=SyncPool())
        results, m = d.dispatch([[n(1)]])
        assert results[n(1)] == "rejected"
        assert m.rounds == 1 and len(calls) == 1  # 终态不回炉

    def test_max_rounds_no_more_retry(self):
        # dispatch 只报错误类别；超过 max_rounds 不再回炉，终态转换由 JobLease 负责。
        def exe(batch):
            return [{"number": x, "error_class": "browser_crash"} for x in batch]

        d = BatchDispatcher(executor=exe, pool_factory=SyncPool(),
                            config=DispatchConfig(max_rounds=2))
        results, m = d.dispatch([[n(1)]])
        assert results[n(1)] == "browser_crash"  # 错误类别保留供 lease 转终态
        assert m.rounds == 2
        assert m.retry_dispatched == 1  # 仅第1轮回炉一次，第2轮到顶不再回炉

    def test_infra_failure_separated(self):
        def exe(batch):
            raise RuntimeError("db down")  # 基础设施异常

        d = BatchDispatcher(executor=exe, pool_factory=SyncPool(),
                            config=DispatchConfig(max_rounds=1))
        results, m = d.dispatch([[n(1)]])
        # 基础设施失败归 browser_crash 终态（本测试 max_rounds=1），不是业务 rejected。
        assert results[n(1)] == "browser_crash"

    def test_human_interval_inserted(self):
        sleeps = []

        def exe(batch):
            return ok(batch)

        d = BatchDispatcher(executor=exe, pool_factory=SyncPool(), sleeper=sleeps.append,
                            config=DispatchConfig(tab_interval_requests=2,
                                                  tab_interval_ms=1000),
                            randomizer=random.Random(1))
        d.dispatch([[n(i) for i in range(70)]])  # 2 batches -> 1 interval
        assert len(sleeps) == 1
        assert 0.6 <= sleeps[0] / 1.0 <= 1.4  # 0.6~1.4 倍（秒）

    def test_circuit_gate_blocks_batch(self):
        class CB:
            allows_request = False
            failures = []

            def on_request_started(self):
                pass

            def on_failure(self, ec):
                self.failures.append(ec)

            def on_success(self):
                pass

        cb = CB()
        called = []

        def exe(batch):
            called.append(1)
            return ok(batch)

        d = BatchDispatcher(executor=exe, circuit=cb, pool_factory=SyncPool())
        results, m = d.dispatch([[n(1)]])
        assert results[n(1)] == "circuit_open"
        assert called == []  # 熔断时未发起请求

    def test_metrics_masked(self):
        def exe(batch):
            return ok(batch)

        d = BatchDispatcher(executor=exe, pool_factory=SyncPool())
        _, m = d.dispatch([[n(1), n(2)]])
        snap = m.snapshot()
        assert "results" not in snap  # 指标快照不含单号明细
        assert snap["submitted"] == 2
