"""BillingOutboxConsumer 离线单测：fake 连接注入，不碰真库。"""
import json
import sys
from pathlib import Path

import pytest

sys.path[:0] = [str(Path(__file__).resolve().parents[2] / "apps" / "worker" / "src"),
                str(Path(__file__).resolve().parents[2] / "packages" / "common" / "src")]

from pandatrack_common.hashutil import payload_digest  # noqa: E402

from worker.billing.consumer import (  # noqa: E402
    BillingOutboxConsumer, EnqueueStats, extract_candidates,
    DIGEST_MISMATCH, PAYLOAD_MALFORMED, MAX_ATTEMPTS)


# ------------------------------------------------------------ fake 连接 ----
class FakeCursor:
    def __init__(self, conn):
        self.conn = conn

    def execute(self, sql, params=None):
        self.conn.queries.append((" ".join(sql.split()), params))
        self._result = self.conn.handler(" ".join(sql.split()), params)

    def fetchone(self):
        return self._result

    @property
    def rowcount(self):
        return self.conn.rowcount

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeConn:
    """最小连接桩：handler(sql, params) → fetchone 结果。"""

    def __init__(self, handler, rowcount=1):
        self.handler = handler
        self.rowcount = rowcount
        self.queries = []
        self.committed = 0

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.committed += 1

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _payload(numbers=("9400110200812345001",), op=101, cid=7):
    return {"operation_id": op, "customer_id": cid,
            "candidates": list(numbers)}


class Harness:
    """A/B 两库桩 + 计数。"""

    def __init__(self, *, job_state=None, b_fail=False, a_fail=False,
                 max_attempts=MAX_ATTEMPTS):
        self.a = FakeConn(self._a_handler)
        self.b = FakeConn(self._b_handler)
        self.job_state = job_state          # fetch_job 最近状态（None=无）
        self.b_fail = b_fail                # B 库标记时抛错
        self.a_fail = a_fail                # A 库入队时抛错
        self.max_attempts = max_attempts
        self.tracking_seq = 500
        self.inserted_jobs = 0
        self.failed_ops = 0

    def _a_handler(self, sql, params):
        if self.a_fail:
            raise RuntimeError("a down")
        if "INSERT INTO tracking" in sql:
            self.tracking_seq += 1
            return (self.tracking_seq,)
        if "SELECT state FROM fetch_job" in sql:
            return None if self.job_state is None else (self.job_state,)
        if "INSERT INTO fetch_job" in sql:
            self.inserted_jobs += 1
        return None

    def _b_handler(self, sql, params):
        if "SET processed = true" in sql and "attempts" not in sql:
            if self.b_fail:
                raise RuntimeError("b down")
            return (1,)
        if "SET attempts = attempts + 1" in sql:
            self.failed_ops += 1
            exhausted = self.failed_ops >= self.max_attempts
            return (exhausted, exhausted)  # (processed, attempts>=max)
        return None

    def consumer(self, **kw):
        return BillingOutboxConsumer(lambda: self.a, lambda: self.b, **kw)

    def seed_event(self, event_id=1, payload=None, digest=None):
        p = payload if payload is not None else _payload()
        self._pending = {"event_id": event_id, "operation_id": p["operation_id"],
                         "payload": p,
                         "digest": digest if digest is not None
                         else payload_digest(p),
                         "attempts": 0}

    def stub_fetch_batch(self, **kw):
        self.max_attempts = kw.get("max_attempts", self.max_attempts)
        c = self.consumer(**kw)
        c._fetch_batch = lambda: [self._pending]
        return c


# ------------------------------------------------------------ 纯函数 ----
def test_extract_candidates_dedup_preserves_order():
    assert extract_candidates(_payload(["B", "A", "B", "A"])) == ["B", "A"]


def test_extract_candidates_rejects_malformed():
    with pytest.raises(ValueError, match=PAYLOAD_MALFORMED):
        extract_candidates(["ok", 123])
    with pytest.raises(ValueError, match=PAYLOAD_MALFORMED):
        extract_candidates([])
    with pytest.raises(ValueError, match=PAYLOAD_MALFORMED):
        extract_candidates("not-a-dict")


# ------------------------------------------------------------ 正常链路 ----
def test_run_once_enqueues_and_marks_processed():
    h = Harness()
    h.seed_event(payload=_payload(("N1", "N2")))
    stats = h.stub_fetch_batch().run_once()
    assert (stats.scanned, stats.enqueued, stats.processed) == (1, 2, 1)
    assert stats.abandoned == 0 and stats.retried == 0
    # A 库：两次 tracking upsert + 两次 fetch_job 插入
    assert h.inserted_jobs == 2
    assert h.a.committed == 1 and h.b.committed == 1


def test_run_once_dedups_candidates_in_payload():
    h = Harness()
    h.seed_event(payload=_payload(("N1", "N1", "N2")))
    stats = h.stub_fetch_batch().run_once()
    assert stats.enqueued == 2  # N1 去重


def test_single_flight_active_job_skipped():
    h = Harness(job_state="pending")
    h.seed_event(payload=_payload(("N1",)))
    stats = h.stub_fetch_batch().run_once()
    assert stats.enqueued == 0 and stats.skipped_active == 1
    assert h.inserted_jobs == 0
    assert stats.processed == 1  # 跳过也算完成


def test_terminal_job_rebuilds_pending():
    h = Harness(job_state="succeeded")
    h.seed_event(payload=_payload(("N1",)))
    stats = h.stub_fetch_batch().run_once()
    assert stats.enqueued == 1 and stats.skipped_terminal == 1


# ------------------------------------------------------------ 失败路径 ----
def test_digest_mismatch_abandons_immediately():
    """digest 不匹配视为载荷被篡改：max_attempts=1 下首次失败即放弃。"""
    h = Harness()
    h.seed_event(digest="0" * 64)  # 与 payload 不匹配
    stats = h.stub_fetch_batch(max_attempts=1).run_once()
    assert stats.scanned == 1 and stats.abandoned == 1
    assert stats.enqueued == 0 and stats.processed == 0
    assert any(DIGEST_MISMATCH in e for e in stats.errors)


def test_digest_mismatch_retries_before_max():
    """未达上限时 digest 失败只重试，不放弃。"""
    h = Harness()
    h.seed_event(digest="0" * 64)
    stats = h.stub_fetch_batch().run_once()  # 默认 max_attempts=5
    assert stats.retried == 1 and stats.abandoned == 0
    assert any(DIGEST_MISMATCH in e for e in stats.errors)


def test_enqueue_fail_retries_event():
    h = Harness(a_fail=True)
    h.seed_event(payload=_payload(("N1",)))
    stats = h.stub_fetch_batch().run_once()
    assert stats.retried == 1 and stats.processed == 0
    assert stats.enqueued == 0


def test_b_fail_retries_event():
    h = Harness(b_fail=True)
    h.seed_event(payload=_payload(("N1",)))
    stats = h.stub_fetch_batch().run_once()
    assert stats.enqueued == 1   # A 库已入队（重放安全）
    assert stats.retried == 1 and stats.processed == 0
    assert h.a.committed == 1


def test_attempts_exhausted_abandons():
    """A 库入队反复失败，第 max_attempts 次失败后放弃。"""
    h = Harness(a_fail=True)
    h.seed_event(payload=_payload(("N1",)))
    c = h.stub_fetch_batch()

    def b_handler(sql, params):
        if "SET attempts = attempts + 1" in sql:
            h.failed_ops += 1
            return (True, True)  # processed=true 且达上限
        if "SET processed = true" in sql and "attempts" not in sql:
            return (1,)
        return None
    h.b.handler = b_handler
    stats = c.run_once()
    assert stats.abandoned == 1 and stats.retried == 0


def test_event_isolation_in_batch():
    """一个事件失败不阻塞同批其它事件。"""
    h = Harness(max_attempts=1)
    h.seed_event(event_id=1, payload=_payload(("N1",)))
    h.seed_event(event_id=2, payload=_payload(("N2",)))
    h.seed_event(event_id=3, digest="f" * 64)  # 坏事件
    batch = [dict(event_id=1, operation_id=101, payload=_payload(("N1",)),
                  digest=payload_digest(_payload(("N1",))), attempts=0),
             dict(event_id=2, operation_id=102, payload=_payload(("N2",)),
                  digest=payload_digest(_payload(("N2",))), attempts=0),
             dict(event_id=3, operation_id=103, payload=_payload(("N3",)),
                  digest="f" * 64, attempts=0)]
    c = h.consumer(max_attempts=1)
    c._fetch_batch = lambda: batch
    stats = c.run_once()
    assert stats.scanned == 3
    assert stats.processed == 2 and stats.abandoned == 1


# ------------------------------------------------------------ 统计 ----
def test_stats_to_dict_omits_zero_fields():
    s = EnqueueStats()
    assert s.to_dict() == {}
    s.enqueued = 3
    assert s.to_dict() == {"enqueued": 3}


# ------------------------------------------------- 环境黑名单（测试隔离）----
def test_skip_numbers_blocks_only_listed_candidates():
    """黑名单命中不入队（防常驻 worker 为测试单号真实采集）；事件仍 processed。"""
    h = Harness()
    h.seed_event(payload=_payload(numbers=("9400110200812345001",
                                           "9302010623396181820639")))
    c = h.stub_fetch_batch(skip_numbers=frozenset({"9302010623396181820639"}))
    stats = c.run_once()
    assert stats.skipped_env == 1
    assert stats.processed == 1
    assert stats.enqueued == 1          # 仅黑名单外的单号入队


def test_skip_numbers_all_blocked_still_processed():
    """全部命中黑名单：不入队但事件必须标记 processed（否则无限重试）。"""
    h = Harness()
    h.seed_event(payload=_payload(numbers=("9302010623396181820639",)))
    c = h.stub_fetch_batch(skip_numbers=frozenset({"9302010623396181820639"}))
    stats = c.run_once()
    assert stats.skipped_env == 1
    assert stats.processed == 1
    assert stats.enqueued == 0
