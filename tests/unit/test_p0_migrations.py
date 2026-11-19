"""P0 迁移静态校验：结构完整性、C1/C2 补齐项、§5.5 补全表、public_id。

真实 PG 执行验证见 scripts/migrate.py（服务器有 PostgreSQL 16）。
"""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]  # tests/unit/xx.py → tests → 项目根
MIG = ROOT / "infra" / "migrations"


def _sql(db: str, name: str) -> str:
    p = MIG / db / name
    return p.read_text(encoding="utf-8")


@pytest.mark.parametrize("db,name", [
    ("a", "0001_initial.sql"), ("a", "0002_supplement.sql"),
    ("b", "0001_initial.sql"), ("b", "0002_supplement.sql"),
])
class TestSqlShape:
    def test_parentheses_balanced(self, db, name):
        s = _sql(db, name)
        assert s.count("(") == s.count(")"), f"{db}/{name} 括号不配平"

    def test_transaction_wrapped(self, db, name):
        s = _sql(db, name)
        assert s.lstrip().startswith("--"), f"{db}/{name} 缺注释头"
        assert "BEGIN;" in s and "COMMIT;" in s

    def test_no_cross_db_reference(self, db, name):
        # 10 §2：A/B 迁移物理分目录，禁止互相引用
        other_tables = ("submission_operation", "wallet", "customer_tracking", "billing_outbox") if db == "a" \
            else ("fetch_job", "parser_evidence_ref", "a_outbox", "tracking_fact")
        s = _sql(db, name)
        for t in other_tables:
            assert t not in s, f"{db} 迁移不得引用另一库表 {t}"


class TestC1C2Fixes:
    def test_a_tracking_has_c1_columns(self):
        s = _sql("a", "0001_initial.sql")
        for col in ("public_id", "next_sync_at", "version", "last_success_at"):
            assert col in s, f"tracking 缺 C1 字段 {col}"

    def test_a_single_flight_covers_all_active_states(self):
        # C2：索引必须覆盖 02 §3.1 / 07 §3.1 全部活跃态
        s = _sql("a", "0001_initial.sql")
        assert "uq_fetch_job_single_flight" in s
        for st in ("pending", "claimed", "running",
                   "waiting_for_session", "retry_scheduled", "collecting_response"):
            assert f"'{st}'" in s, f"single-flight 缺活跃态 {st}"

    def test_b_public_ids_on_external_tables(self):
        s = _sql("b", "0001_initial.sql") + _sql("b", "0002_supplement.sql")
        for table in ("customer", "submission_operation", "customer_tracking", "points_ledger"):
            seg = s.split(f"CREATE TABLE IF NOT EXISTS {table} (")[1].split(");")[0]
            assert "public_id" in seg, f"{table} 缺 public_id"


class TestE2SupplementTables:
    def test_b_supplement_tables_present(self):
        s = _sql("b", "0002_supplement.sql")
        for table in ("tenant", "seat", "admin_user", "target_group", "import_job",
                      "export_job", "audit_log", "session", "refresh_budget",
                      "billing_charge_window"):
            assert f"CREATE TABLE IF NOT EXISTS {table}" in s, f"缺补全表 {table}"

    def test_a_supplement_tables_present(self):
        s = _sql("a", "0002_supplement.sql")
        for table in ("provider_health", "fetch_attempt_log"):
            assert f"CREATE TABLE IF NOT EXISTS {table}" in s

    def test_charge_window_rolling_unique(self):
        s = _sql("b", "0002_supplement.sql")
        assert "uq_charge_window_subject" in s
        assert "WHERE active = true" in s

    def test_ledger_refund_once(self):
        s = _sql("b", "0001_initial.sql")
        assert "uq_ledger_refund_once" in s
        assert "WHERE ledger_type = 'refund'" in s

    def test_idempotency_key(self):
        s = _sql("b", "0001_initial.sql")
        assert "uq_idempotency_key" in s
        assert "(customer_id, endpoint, client_request_id)" in s
