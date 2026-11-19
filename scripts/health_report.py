#!/usr/bin/env python3
"""PandaTrack 健康巡检（P5 运维）：A/B 库关键指标 + 阈值告警。

由 systemd pandatrack-health.timer 每小时触发，输出到 journalctl
（journalctl -u pandatrack-health 查看）。也可手工执行：
    .venv/bin/python scripts/health_report.py --json

指标（只读 SQL，不动数据）：
- A 库：dead_letter 累计、活跃积压（pending+到期 retry_scheduled）、
  未处理 a_outbox；
- B 库：未处理 billing_outbox、最旧投影年龄（tracking_projection）。

告警规则（build_report 纯函数，可单测）：
- dead_letter > 0 → problem（任务终态失败需人工排查）；
- 未处理 a_outbox > 100 → problem（sync-agent 未排空/积压）；
- 活跃积压 > 500 → problem（采集吞吐不足或上游故障）；
- 未处理 billing_outbox > 100 → problem；
- 最旧投影 > 48h → problem（投影链路停摆）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

# 阈值（初始观测值，验收区标定后调整）。
THRESHOLDS = {
    "dead_letter": 0,
    "a_outbox_unprocessed": 100,
    "active_backlog": 500,
    "billing_outbox_unprocessed": 100,
    "oldest_projection_hours": 48.0,
}


def build_report(a: dict, b: dict, *,
                 now: datetime | None = None,
                 thresholds: dict | None = None) -> tuple[dict, list[str]]:
    """聚合指标 + 出告警清单；a/b 为 metric 名→值 的扁平字典。"""
    th = thresholds or THRESHOLDS
    metrics = {
        "dead_letter": a.get("dead_letter", 0),
        "active_backlog": a.get("active_backlog", 0),
        "a_outbox_unprocessed": a.get("a_outbox_unprocessed", 0),
        "billing_outbox_unprocessed": b.get("billing_outbox_unprocessed", 0),
        "oldest_projection_hours": b.get("oldest_projection_hours", 0.0),
    }
    problems: list[str] = []
    if metrics["dead_letter"] > th["dead_letter"]:
        problems.append(
            f"dead_letter={metrics['dead_letter']}，任务终态失败需人工排查")
    if metrics["a_outbox_unprocessed"] > th["a_outbox_unprocessed"]:
        problems.append(
            f"a_outbox 未处理 {metrics['a_outbox_unprocessed']} 条，"
            "sync-agent 积压")
    if metrics["active_backlog"] > th["active_backlog"]:
        problems.append(
            f"采集积压 {metrics['active_backlog']} 条（pending+到期重试）")
    if metrics["billing_outbox_unprocessed"] > th["billing_outbox_unprocessed"]:
        problems.append(
            f"billing_outbox 未处理 {metrics['billing_outbox_unprocessed']} 条")
    if metrics["oldest_projection_hours"] > th["oldest_projection_hours"]:
        problems.append(
            f"最旧投影 {metrics['oldest_projection_hours']:.1f}h，投影链路可能停摆")
    report = {"metrics": metrics, "problems": problems,
              "checked_at": (now or datetime.now(timezone.utc)).isoformat(),
              "ok": not problems}
    return report, problems


def fetch_a(url: str) -> dict:
    import psycopg
    with psycopg.connect(url) as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT
                 (SELECT count(*) FROM fetch_job WHERE state='dead_letter'),
                 (SELECT count(*) FROM fetch_job
                    WHERE state='pending'
                       OR (state='retry_scheduled'
                           AND (retry_at IS NULL OR retry_at <= now()))),
                 (SELECT count(*) FROM a_outbox WHERE processed=false)""")
        r = cur.fetchone()
    return {"dead_letter": r[0], "active_backlog": r[1],
            "a_outbox_unprocessed": r[2]}


def fetch_b(url: str) -> dict:
    import psycopg
    with psycopg.connect(url) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM billing_outbox WHERE processed=false")
        billing_outbox = cur.fetchone()[0]
        cur.execute(
            """SELECT coalesce(max(now() - projected_at), interval '0')
                 FROM tracking_projection""")
        oldest = cur.fetchone()[0]
    return {"billing_outbox_unprocessed": billing_outbox,
            "oldest_projection_hours": oldest.total_seconds() / 3600.0}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="PandaTrack 健康巡检")
    ap.add_argument("--url-a", default=os.environ.get("DATABASE_A_URL", ""))
    ap.add_argument("--url-b", default=os.environ.get("DATABASE_B_URL", ""))
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    if not args.url_a or not args.url_b:
        print("缺少 DATABASE_A_URL / DATABASE_B_URL", file=sys.stderr)
        return 2
    a = fetch_a(args.url_a)
    b = fetch_b(args.url_b)
    report, problems = build_report(a, b)
    if args.json:
        print(json.dumps(report, ensure_ascii=False))
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
