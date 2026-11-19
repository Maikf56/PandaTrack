"""真库集成测试共享清理助手。

worker 已 systemd 常驻：任何留在 A 库的 tracking/fetch_job 都会被它
领取并触发真实代理采集。凡走 submit()/imports 链路的集成测试，
teardown 必须按测试单号清空 A 库残留（fetch_job → a_outbox →
tracking_fact/tracking_event → tracking），并把 billing_outbox
事件也清掉（B 库），把「测试触发生产采集」的窗口压到最小。
"""
from __future__ import annotations

import psycopg


def purge_a_numbers(db_a_url: str, *numbers: str) -> None:
    """A 库按归一化单号级联清除 tracking 及全部从属行（幂等）。"""
    if not numbers:
        return
    with psycopg.connect(db_a_url) as conn, conn.cursor() as cur:
        cur.execute(
            """DELETE FROM fetch_job WHERE tracking_id IN
                 (SELECT tracking_id FROM tracking
                   WHERE normalized_number = ANY(%s))""", (list(numbers),))
        cur.execute(
            """DELETE FROM a_outbox WHERE aggregate_id IN
                 (SELECT tracking_id FROM tracking
                   WHERE normalized_number = ANY(%s))""", (list(numbers),))
        cur.execute(
            """DELETE FROM tracking_event WHERE tracking_id IN
                 (SELECT tracking_id FROM tracking
                   WHERE normalized_number = ANY(%s))""", (list(numbers),))
        cur.execute(
            """DELETE FROM tracking_fact WHERE tracking_id IN
                 (SELECT tracking_id FROM tracking
                   WHERE normalized_number = ANY(%s))""", (list(numbers),))
        cur.execute(
            "DELETE FROM tracking WHERE normalized_number = ANY(%s)",
            (list(numbers),))
        conn.commit()


def purge_b_outbox_by_numbers(db_b_url: str, *numbers: str) -> None:
    """B 库删除候选单号命中的 billing_outbox 事件（防 daemon 消费）。"""
    if not numbers:
        return
    with psycopg.connect(db_b_url) as conn, conn.cursor() as cur:
        # candidates 是 JSON 数组：::text 后 LIKE 匹配任一单号即可。
        for n in numbers:
            cur.execute(
                """DELETE FROM billing_outbox
                   WHERE payload::text LIKE %s""", (f"%{n}%",))
        conn.commit()
