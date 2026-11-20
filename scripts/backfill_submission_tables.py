"""存量受理数据回填：customer_tracking + submission_batch + submission_item。

背景（P14 断链修复）：submit() 事务此前未写这三张表，导致已受理的历史
operation 采集成功后投影扇出 skipped_no_customer，客户永远看不到结果。
本脚本从 billing_outbox 的受理事件（payload 含 operation_id/customer_id/
candidates）回填，幂等可重复执行。

用法（服务器仓库根目录）：
    set -a && . ./.env && set +a
    PYTHONPATH=apps/worker/src:apps/api/src .venv/bin/python \\
        scripts/backfill_submission_tables.py
"""
from __future__ import annotations

import json
import os
import sys

import psycopg

BATCH_SIZE = 35  # 与 worker.billing.submission.BATCH_SIZE 同源


def main() -> int:
    dsn_b = os.environ.get("DATABASE_B_URL", "").replace(
        "postgresql+psycopg://", "postgresql://")
    dsn_a = os.environ.get("DATABASE_A_URL", "").replace(
        "postgresql+psycopg://", "postgresql://")
    if not dsn_b:
        print("缺少 DATABASE_B_URL", file=sys.stderr)
        return 1

    with psycopg.connect(dsn_b) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT event_id, aggregate_id, payload
                   FROM billing_outbox
                   WHERE aggregate_type = 'submission_operation'
                   ORDER BY event_id""")
            events = cur.fetchall()
            print(f"受理事件总数: {len(events)}")

            filled_ops = skipped_ops = filled_ct = 0
            for _eid, op_id, payload in events:
                if isinstance(payload, str):
                    payload = json.loads(payload)
                candidates = [c for c in (payload.get("candidates") or [])
                              if isinstance(c, str) and c]
                customer_id = payload.get("customer_id")
                if not candidates or customer_id is None:
                    skipped_ops += 1
                    continue

                # 已有批次的 operation 跳过（幂等）
                cur.execute(
                    "SELECT count(*) FROM submission_batch WHERE operation_id=%s",
                    (op_id,))
                if cur.fetchone()[0] > 0:
                    skipped_ops += 1
                    continue

                cur.execute(
                    """INSERT INTO customer_tracking (customer_id, normalized_number)
                       SELECT %s, c FROM unnest(%s::varchar[]) AS c
                       ON CONFLICT (customer_id, normalized_number) DO NOTHING""",
                    (customer_id, candidates))
                filled_ct += cur.rowcount

                for seq in range(0, len(candidates), BATCH_SIZE):
                    chunk = candidates[seq:seq + BATCH_SIZE]
                    cur.execute(
                        """INSERT INTO submission_batch
                               (operation_id, batch_seq, item_count, state)
                           VALUES (%s, %s, %s, 'accepted') RETURNING batch_id""",
                        (op_id, seq // BATCH_SIZE + 1, len(chunk)))
                    batch_id = cur.fetchone()[0]
                    with cur.copy(
                        "COPY submission_item (batch_id, item_seq, raw_number, "
                        "normalized_number, is_valid) FROM STDIN"
                    ) as copy:
                        for j, num in enumerate(chunk, start=1):
                            copy.write_row((batch_id, j, num, num, True))
                filled_ops += 1
        conn.commit()
    print(f"回填 operation: {filled_ops}；跳过（已有明细/缺载荷）: {skipped_ops}；"
          f"新建 customer_tracking: {filled_ct}")

    # 重置 A 库 tracking outbox：sync-agent 对"无客户关系"的事实也会标记
    # processed（与模块注释相悖），回填建立关系后需重放才能补投影。
    # 重放安全：B 侧 upsert 幂等。
    if dsn_a:
        with psycopg.connect(dsn_a) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE a_outbox SET processed = false
                       WHERE aggregate_type = 'tracking' AND processed = true""")
                reset = cur.rowcount
            conn.commit()
        print(f"A 库 outbox 重置待重放: {reset} 条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
