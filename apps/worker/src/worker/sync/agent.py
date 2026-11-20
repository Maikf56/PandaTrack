"""sync-agent：A 库 outbox → B 库投影（05 §数据链路）。

规格（05 权威口径）：
- sync-agent 用 event_id + aggregate_version 幂等投影；
- A/B 单向摆渡：只读 A（outbox/tracking/tracking_event），只写 B（投影）；
- 崩溃安全：B 侧全量快照 upsert 天然幂等，A 侧 processed 标记在 B 提交
  之后——两段之间崩溃则重放，upsert 结果不变；
- 同一单号可能被多个客户跟踪：投影按 normalized_number 扇出到全部
  customer_tracking（07：跳过抓取 ≠ 跳过客户关系）；
- 无客户关系的事实（无 customer_tracking 行）本轮跳过投影，但事件仍
  标记 processed 不再重放（submit 受理事务自 P14 起同事务建立关系，
  正常链路不应出现缺关系的事实）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from pandatrack_common.status import ALL_STATUSES


@dataclass(slots=True)
class SyncReport:
    fetched: int = 0            # 取到的未处理 outbox 行
    projected: int = 0          # 投影写入的 tracking_projection 行数
    customers_hit: int = 0      # 涉及的 customer_tracking 数
    skipped_no_customer: int = 0  # 无客户关系、留待重放的事实
    marked_processed: int = 0


class SyncAgent:
    """A→B 投影代理；两侧连接工厂注入，便于单测与事务边界控制。"""

    def __init__(self, connect_a: Callable[[], Any],
                 connect_b: Callable[[], Any], *, batch_size: int = 200):
        self._connect_a = connect_a
        self._connect_b = connect_b
        self.batch_size = batch_size

    # ---- A 侧读取 ----
    def _fetch_unprocessed(self, conn) -> list[dict]:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT event_id, aggregate_id, aggregate_version, payload
                   FROM a_outbox
                   WHERE processed = false AND aggregate_type = 'tracking'
                   ORDER BY event_id
                   LIMIT %s""",
                (self.batch_size,))
            rows = cur.fetchall()
        return [{"event_id": r[0], "tracking_id": r[1],
                 "version": r[2], "payload": r[3]} for r in rows]

    def _load_facts(self, conn, tracking_ids: list[int]) -> dict[int, dict]:
        """tracking_id → {normalized_number, events:[投影JSON]}。"""
        if not tracking_ids:
            return {}
        with conn.cursor() as cur:
            cur.execute(
                """SELECT t.tracking_id, t.normalized_number,
                          e.event_fingerprint, e.occurred_at, e.status,
                          e.description_raw, e.description_zh, e.location,
                          e.event_code, e.time_confidence
                   FROM tracking t
                   LEFT JOIN tracking_event e ON e.tracking_id = t.tracking_id
                   WHERE t.tracking_id = ANY(%s)
                   ORDER BY e.occurred_at DESC NULLS LAST, e.event_id DESC""",
                (tracking_ids,))
            rows = cur.fetchall()
        out: dict[int, dict] = {}
        for r in rows:
            tid = r[0]
            entry = out.setdefault(tid, {"normalized_number": r[1],
                                         "events": []})
            if r[2] is None:
                continue  # 无事件（LEFT JOIN 未命中）
            std = ALL_STATUSES.get(r[4])
            entry["events"].append({
                "occurred_at": r[3].isoformat() if r[3] else None,
                "time_confidence": r[9] or "low",
                "status_key": r[4] or "other",
                "label_zh": std.label_zh if std else "其他状态",
                # P17 竞品式双语：description 恒为英文原文（默认直出），
                # description_zh 为 USPS 短语词典中文（前端「翻译」切换用）
                "description": r[5] or "",
                "description_zh": r[6] or None,
                "location": r[7] or None,
                "event_code": r[8] or None,
            })
        return out

    # ---- B 侧投影 ----
    def _project(self, conn, facts: dict[int, dict]) -> tuple[int, int, int]:
        """按 normalized_number 扇出投影。返回 (投影行数, 客户数, 无客户数)。"""
        import json
        projected = customers = skipped = 0
        with conn.cursor() as cur:
            for fact in facts.values():
                number = fact["normalized_number"]
                cur.execute(
                    """SELECT customer_tracking_id FROM customer_tracking
                       WHERE normalized_number = %s""", (number,))
                ct_ids = [r[0] for r in cur.fetchall()]
                if not ct_ids:
                    skipped += 1
                    continue
                events_json = json.dumps(fact["events"], ensure_ascii=False,
                                         default=str)
                for ct_id in ct_ids:
                    cur.execute(
                        """INSERT INTO tracking_projection
                           (customer_tracking_id, normalized_number, status,
                            events, projected_at)
                           VALUES (%s, %s, %s, %s, now())
                           ON CONFLICT (customer_tracking_id)
                           DO UPDATE SET normalized_number = EXCLUDED.normalized_number,
                                         status = EXCLUDED.status,
                                         events = EXCLUDED.events,
                                         projected_at = now()""",
                        (ct_id, number, self._latest_status(fact), events_json))
                    projected += 1
                customers += len(ct_ids)
        return projected, customers, skipped

    @staticmethod
    def _latest_status(fact: dict) -> str:
        """当前状态 = 最新事件的状态键；无事件回退 other。"""
        if fact["events"]:
            return fact["events"][0]["status_key"]
        return "other"

    # ---- A 侧收尾 ----
    def _mark_processed(self, conn, event_ids: list[int]) -> int:
        if not event_ids:
            return 0
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE a_outbox SET processed = true
                   WHERE event_id = ANY(%s) AND processed = false""",
                (event_ids,))
            return cur.rowcount

    def run_once(self) -> SyncReport:
        """投影一轮：A 读 → B 扇出 upsert（单事务）→ A 标 processed。"""
        report = SyncReport()
        with self._connect_a() as ca:
            rows = self._fetch_unprocessed(ca)
            report.fetched = len(rows)
            if not rows:
                return report
            facts = self._load_facts(
                ca, sorted({r["tracking_id"] for r in rows}))

        with self._connect_b() as cb:
            report.projected, report.customers_hit, report.skipped_no_customer = \
                self._project(cb, facts)

        # B 提交成功后才标记 processed；两段间崩溃 → 重放 upsert 幂等。
        with self._connect_a() as ca:
            report.marked_processed = self._mark_processed(
                ca, [r["event_id"] for r in rows])
        return report

    def run_until_drained(self, *, max_rounds: int = 100) -> list[SyncReport]:
        """连续投影直到无积压（worker 常驻/CLI 都可用）。"""
        reports = []
        for _ in range(max_rounds):
            r = self.run_once()
            reports.append(r)
            if r.fetched == 0:
                break
        return reports
