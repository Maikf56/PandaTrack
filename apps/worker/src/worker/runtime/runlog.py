"""运行日志落库（A 库 run_log；管理端"系统运行日志"页面的数据源）。

WorkerDaemon 每轮 cycle 结束后调用 record_cycle：把领取/成功/重试/死信/
事实落库计数写入 A 库 run_log（有活动或异常才记，避免空转刷表）。
失败向上抛由 daemon 捕获（non-fatal，不影响调度主循环）。
"""
from __future__ import annotations

import json
from typing import Any, Callable


def record_cycle(connect: Callable[[], Any], worker_id: str, *, cycle: int,
                 tick: dict | None, enqueue_summary: dict | None = None,
                 sync_summary: dict | None = None,
                 error: str | None = None) -> int:
    """一轮 cycle 报告 → run_log 一行；返回 run_log_id。"""
    tick = tick or {}
    has_activity = any(tick.get(k) for k in
                       ("reclaimed", "claimed", "succeeded", "retried",
                        "dead_lettered"))
    if error:
        level, kind = "error", "tick_error"
    elif tick.get("canary_halt"):
        level, kind = "warn", "canary_halt"
    elif tick.get("error_class"):
        level, kind = "warn", "cycle"
    elif has_activity:
        level, kind = "info", "cycle"
    else:
        return 0  # 空转轮次不记，避免每 20s 刷一行零计数

    summary: dict[str, Any] = {}
    if enqueue_summary:
        summary["enqueue"] = enqueue_summary
    if sync_summary:
        summary["sync"] = sync_summary
    if tick.get("canary_mismatches"):
        summary["canary_mismatches"] = tick["canary_mismatches"]
    if error:
        summary["error"] = error

    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO run_log
                   (worker_id, cycle, level, kind,
                    reclaimed, claimed, succeeded, retried, dead_lettered,
                    facts_written, events_written, outbox_written,
                    error_class, summary)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                   RETURNING run_log_id""",
                (worker_id, cycle, level, kind,
                 tick.get("reclaimed", 0), tick.get("claimed", 0),
                 tick.get("succeeded", 0), tick.get("retried", 0),
                 tick.get("dead_lettered", 0),
                 (tick.get("facts") or {}).get("facts_written", 0),
                 (tick.get("facts") or {}).get("events_written", 0),
                 (tick.get("facts") or {}).get("outbox_written", 0),
                 tick.get("error_class"),
                 json.dumps(summary, ensure_ascii=False, default=str)
                 if summary else None))
            run_log_id = cur.fetchone()[0]
        conn.commit()
        return run_log_id
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
