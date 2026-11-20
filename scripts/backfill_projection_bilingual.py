"""存量投影双语回填：tracking_projection.events 重建为竞品式双语结构。

背景（P17 翻译改造）：此前投影 events 的 description 取 `description_zh
or description_raw`（中文优先），前端无法实现「默认英文原文、点翻译出
中文」。改造后 events 元素为：
    description    = description_raw（英文原文，恒直出）
    description_zh = description_zh（USPS 词典中文，可为 None）
本脚本从 A 库 tracking_event 重建全部客户投影，幂等可重复执行。

用法（服务器仓库根目录）：
    set -a && . ./.env && set +a
    PYTHONPATH=apps/worker/src:apps/api/src .venv/bin/python \\
        scripts/backfill_projection_bilingual.py
"""
from __future__ import annotations

import json
import os
import sys

import psycopg

from pandatrack_common.status import ALL_STATUSES


def main() -> int:
    dsn_b = os.environ.get("DATABASE_B_URL", "").replace(
        "postgresql+psycopg://", "postgresql://")
    dsn_a = os.environ.get("DATABASE_A_URL", "").replace(
        "postgresql+psycopg://", "postgresql://")
    if not dsn_a or not dsn_b:
        print("缺少 DATABASE_A_URL / DATABASE_B_URL", file=sys.stderr)
        return 1

    with psycopg.connect(dsn_a) as ca:
        with ca.cursor() as cur:
            cur.execute(
                """SELECT t.normalized_number,
                          e.occurred_at, e.status, e.description_raw,
                          e.description_zh, e.location, e.event_code,
                          e.time_confidence
                   FROM tracking t
                   JOIN tracking_event e ON e.tracking_id = t.tracking_id
                   ORDER BY t.tracking_id,
                            e.occurred_at DESC NULLS LAST, e.event_id DESC""")
            rows = cur.fetchall()

    facts: dict[str, list[dict]] = {}
    for r in rows:
        number, occurred_at, status, raw, zh, location, code, conf = r
        std = ALL_STATUSES.get(status)
        facts.setdefault(number, []).append({
            "occurred_at": occurred_at.isoformat() if occurred_at else None,
            "time_confidence": conf or "low",
            "status_key": status or "other",
            "label_zh": std.label_zh if std else "其他状态",
            "description": raw or "",
            "description_zh": zh or None,
            "location": location or None,
            "event_code": code or None,
        })

    projected = 0
    with psycopg.connect(dsn_b) as cb:
        with cb.cursor() as cur:
            cur.execute(
                "SELECT customer_tracking_id, normalized_number "
                "FROM customer_tracking")
            ct_rows = cur.fetchall()
            print(f"customer_tracking 行数: {len(ct_rows)}；"
                  f"A 库有事实的单号: {len(facts)}")
            for ct_id, number in ct_rows:
                events = facts.get(number)
                if not events:
                    continue
                latest = events[0]["status_key"]
                cur.execute(
                    """UPDATE tracking_projection
                       SET status=%s, events=%s, projected_at=now()
                       WHERE customer_tracking_id=%s""",
                    (latest, json.dumps(events, ensure_ascii=False), ct_id))
                projected += cur.rowcount
        cb.commit()
    print(f"已重建投影: {projected} 行")
    return 0


if __name__ == "__main__":
    sys.exit(main())
