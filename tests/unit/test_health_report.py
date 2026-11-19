"""健康巡检单测：build_report 聚合 + 告警规则 + CLI 退出码约定。"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from health_report import build_report  # noqa: E402

NOW = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)


def test_report_ok_when_all_below_thresholds():
    report, problems = build_report(
        {"dead_letter": 0, "active_backlog": 10, "a_outbox_unprocessed": 3},
        {"billing_outbox_unprocessed": 0, "oldest_projection_hours": 1.2},
        now=NOW)
    assert report["ok"] is True and problems == []
    assert report["metrics"]["active_backlog"] == 10
    assert report["checked_at"] == NOW.isoformat()


def test_report_dead_letter_warns_on_any_failure():
    _, problems = build_report(
        {"dead_letter": 2, "active_backlog": 0, "a_outbox_unprocessed": 0},
        {"billing_outbox_unprocessed": 0, "oldest_projection_hours": 0},
        now=NOW)
    assert len(problems) == 1 and "dead_letter=2" in problems[0]


def test_report_outbox_backlog_and_billing_rules():
    _, problems = build_report(
        {"dead_letter": 0, "active_backlog": 501,
         "a_outbox_unprocessed": 101},
        {"billing_outbox_unprocessed": 101, "oldest_projection_hours": 0},
        now=NOW)
    assert len(problems) == 3  # 积压 + a_outbox + billing_outbox


def test_report_stale_projection():
    _, problems = build_report(
        {"dead_letter": 0, "active_backlog": 0, "a_outbox_unprocessed": 0},
        {"billing_outbox_unprocessed": 0, "oldest_projection_hours": 49.5},
        now=NOW)
    assert any("49.5h" in p for p in problems)


def test_report_custom_thresholds():
    _, problems = build_report(
        {"dead_letter": 0, "active_backlog": 0, "a_outbox_unprocessed": 5},
        {"billing_outbox_unprocessed": 0, "oldest_projection_hours": 0},
        now=NOW,
        thresholds={"dead_letter": 0, "a_outbox_unprocessed": 4,
                    "active_backlog": 500,
                    "billing_outbox_unprocessed": 100,
                    "billing_outbox_dead": 0,
                    "oldest_projection_hours": 48.0})
    assert len(problems) == 1 and "5 条" in problems[0]


def test_report_missing_metrics_default_zero():
    report, problems = build_report({}, {}, now=NOW)
    assert report["ok"] is True
    assert report["metrics"]["oldest_projection_hours"] == 0.0
