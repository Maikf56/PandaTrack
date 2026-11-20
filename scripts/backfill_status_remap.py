"""P18 存量状态映射回填：A 库事件 status + B 库投影（事件级 + 顶层）。

背景：USPS 采集层 map_status 未登记的描述归 other（Delivered, In/At Mailbox
等 527 条），词典 MAPPING 补齐后需要重刷存量：
1. A 库 tracking_event：description_raw 命中新 MAPPING → 更新 status；
2. B 库 tracking_projection：逐事件按事件描述重算 status_key/label_zh，
   顶层 status = 最新事件 status_key（与 agent._latest_status 同口径）。

幂等：重复执行结果一致（全部按 MAPPING 重算覆盖）。
用法（服务器）：PYTHONPATH=apps/worker/src:.venv/lib/python3.12/site-packages \\
    .venv/bin/python scripts/backfill_status_remap.py [--dry-run]
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..",
                                "apps", "worker", "src"))

import psycopg

from pandatrack_common.status import ALL_STATUSES
from worker.provider.usps_web.status_data import MAPPING

A_URL = os.environ["DATABASE_A_URL"].replace("postgresql+psycopg://",
                                             "postgresql://")
B_URL = os.environ["DATABASE_B_URL"].replace("postgresql+psycopg://",
                                             "postgresql://")

DRY = "--dry-run" in sys.argv


def remap_event(ev: dict) -> dict | None:
    """事件按最新 MAPPING 重算状态；无变化返回 None。"""
    desc = (ev.get("description") or "").strip()
    if not desc:
        return None
    hit = MAPPING.get(desc)
    if hit is None:
        return None
    key, _zh = hit
    std = ALL_STATUSES.get(key)
    label = std.label_zh if std else "其他状态"
    if ev.get("status_key") == key and ev.get("label_zh") == label:
        return None
    ev["status_key"] = key
    ev["label_zh"] = label
    # 词典中文顺带补全（P17 未回填到的事件）
    if not ev.get("description_zh"):
        ev["description_zh"] = _zh
    return ev


def main() -> None:
    # 1) A 库：tracking_event 状态重归类
    with psycopg.connect(A_URL) as ca, ca.cursor() as cur:
        changed = 0
        for raw, (key, _zh) in MAPPING.items():
            cur.execute(
                """UPDATE tracking_event SET status=%s
                   WHERE status='other' AND description_raw=%s""",
                (key, raw))
            changed += cur.rowcount
        print(f"A库 tracking_event 重归类: {changed} 行")
        if not DRY:
            ca.commit()

    # 2) B 库：投影事件级重算 + 顶层状态
    with psycopg.connect(B_URL) as cb, cb.cursor() as cur:
        cur.execute("""SELECT projection_id, status, events
                       FROM tracking_projection
                       WHERE jsonb_array_length(events) > 0""")
        rows = cur.fetchall()
        proj_changed = 0
        for pid, _old_status, events in rows:
            evs = events if isinstance(events, list) else json.loads(events)
            touched = False
            for ev in evs:
                if isinstance(ev, dict) and remap_event(ev) is not None:
                    touched = True
            latest = evs[0].get("status_key", "other") if evs else "other"
            if touched or _old_status != latest:
                cur.execute(
                    """UPDATE tracking_projection
                       SET status=%s, events=%s::jsonb, projected_at=now()
                       WHERE projection_id=%s""",
                    (latest, json.dumps(evs, ensure_ascii=False), pid))
                proj_changed += 1
        print(f"B库 tracking_projection 重算: {proj_changed}/{len(rows)} 行")
        if not DRY:
            cb.commit()

    # 3) 结果分布
    with psycopg.connect(B_URL) as cb, cb.cursor() as cur:
        cur.execute("""SELECT status, count(*) FROM tracking_projection
                       GROUP BY 1 ORDER BY 2 DESC""")
        print("重算后状态分布:", cur.fetchall())


if __name__ == "__main__":
    main()
