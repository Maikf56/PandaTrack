"""直接提交受理事务（方案 06 §3.4）：B 库单事务完成幂等+计费+落库。

原子性：余额不足 / 幂等冲突 / 请求超限 → 整批失败不扣费；所有写操作同事务提交。
集合化判定：候选批量入临时表，JOIN billing_charge_window 一次性算出 billable_count，
禁止逐单号 N+1，禁止在单事务锁百万明细。
"""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass

from pandatrack_common.hashutil import payload_digest

from .rules import WATERSHED_HOURS

ENDPOINT = "/api/v1/submissions"


class IdempotencyConflict(Exception):
    """同幂等键但请求内容不同（06 §3.4：409 idempotency_conflict）。"""


class InsufficientBalance(Exception):
    """余额不足，整批原子失败（06 §3.4）。"""


@dataclass(frozen=True, slots=True)
class SubmitOutcome:
    operation_public_id: str
    total_count: int
    billable_count: int
    waived_count: int
    balance: int
    replayed: bool = False


def request_fingerprint(payload: dict) -> str:
    """服务端按规范化输入生成内部请求指纹（仅幂等核对/审计，非客户端报价凭证）。"""
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _replay_snapshot(row: tuple) -> SubmitOutcome:
    """从幂等记录重放 202 响应（不重复扣费/建 operation）。"""
    snapshot = row[0]
    return SubmitOutcome(
        operation_public_id=snapshot["operation_id"],
        total_count=snapshot["total_count"],
        billable_count=snapshot["points_charged"],
        waived_count=snapshot.get("free_count", 0),
        balance=snapshot.get("balance", 0),
        replayed=True,
    )


def submit(
    conn,
    *,
    customer_id: int,
    client_request_id: str,
    fingerprint: str,
    normalized_numbers: list[str],
) -> SubmitOutcome:
    """在传入的 DB 连接上执行单事务受理。调用方负责 conn.commit()/rollback()。

    成功写入后返回 202 结果数据；失败抛异常，调用方回滚。
    """
    with conn.cursor() as cur:
        # 1) 锁幂等记录（唯一键 customer_id+endpoint+client_request_id）
        cur.execute(
            "SELECT response_snapshot, request_fingerprint FROM idempotency_record "
            "WHERE customer_id=%s AND endpoint=%s AND client_request_id=%s FOR UPDATE",
            (customer_id, ENDPOINT, client_request_id),
        )
        row = cur.fetchone()
        if row is not None:
            if row[1] != fingerprint:
                raise IdempotencyConflict("同幂等键请求内容不同")
            return _replay_snapshot(row)

        # 2) 候选批量入临时表（会话级，随连接结束清理；显式 DROP 以便复用连接）
        cur.execute("DROP TABLE IF EXISTS _submit_candidates")
        cur.execute(
            "CREATE TEMP TABLE _submit_candidates ("
            " seq INT PRIMARY KEY, normalized_number VARCHAR(50) NOT NULL) ON COMMIT DROP"
        )
        if normalized_numbers:
            with cur.copy(
                "COPY _submit_candidates (seq, normalized_number) FROM STDIN"
            ) as copy:
                for i, num in enumerate(normalized_numbers):
                    copy.write_row((i, num))

        # 3) 集合化免扣判定：同客户同单号 30×24h 窗口内 active 记录免扣
        cur.execute(
            "SELECT COUNT(*) FROM _submit_candidates c "
            "WHERE NOT EXISTS ("
            "  SELECT 1 FROM billing_charge_window w "
            "  WHERE w.customer_id=%s AND w.normalized_number=c.normalized_number "
            "    AND w.active=true AND w.expires_at>now())",
            (customer_id,),
        )
        billable_count = cur.fetchone()[0]
        total_count = len(normalized_numbers)
        waived_count = total_count - billable_count

        # 4) 锁钱包 + 余额检查（FOR UPDATE 串行化同一客户并发提交，防双扣）
        cur.execute(
            "SELECT wallet_id, balance FROM wallet WHERE customer_id=%s FOR UPDATE",
            (customer_id,),
        )
        wrow = cur.fetchone()
        if wrow is None:
            raise InsufficientBalance("钱包不存在")
        wallet_id, balance = wrow
        if balance < billable_count:
            raise InsufficientBalance(f"余额 {balance} < 需扣 {billable_count}")
        new_balance = balance - billable_count

        # 5) 写 operation 头（对外 UUID）
        op_public_id = str(uuid.uuid4())
        cur.execute(
            "INSERT INTO submission_operation "
            " (public_id, customer_id, state, total_count, valid_count, invalid_count, points_charged) "
            "VALUES (%s,%s,'accepted',%s,%s,0,%s) RETURNING operation_id",
            (op_public_id, customer_id, total_count, total_count - waived_count,
             billable_count),
        )
        operation_id = cur.fetchone()[0]

        # 6) 扣费：一条积分流水（CHARGE 负向）
        if billable_count > 0:
            cur.execute(
                "UPDATE wallet SET balance=%s, lifetime_consumed=lifetime_consumed+%s, "
                " version=version+1, updated_at=now() WHERE wallet_id=%s",
                (new_balance, billable_count, wallet_id),
            )
            cur.execute(
                "INSERT INTO points_ledger "
                " (customer_id, ledger_type, points_change, reference_type, reference_id, description) "
                "VALUES (%s,'charge',%s,'submission_operation',%s,'提交扣费')",
                (customer_id, -billable_count, operation_id),
            )

        # 7) reservation（总预留）
        cur.execute(
            "INSERT INTO charge_reservation (operation_id, points_reserved, status) "
            "VALUES (%s,%s,'reserved')",
            (operation_id, billable_count),
        )

        # 8) 写入 30 天免扣窗口（集合化 INSERT ... ON CONFLICT DO NOTHING）
        if billable_count > 0:
            cur.execute(
                "INSERT INTO billing_charge_window "
                " (customer_id, normalized_number, charged_at, expires_at, active) "
                "SELECT %s, c.normalized_number, now(), now() + INTERVAL '%s hours', true "
                "FROM _submit_candidates c "
                "WHERE NOT EXISTS ("
                "  SELECT 1 FROM billing_charge_window w "
                "  WHERE w.customer_id=%s AND w.normalized_number=c.normalized_number AND w.active=true) "
                "ON CONFLICT DO NOTHING",
                (customer_id, WATERSHED_HOURS, customer_id),
            )

        # 9) outbox（供 07 排队消费；aggregate_id 用 operation_id）。
        # digest 统一走 hashutil.payload_digest（canonical_json），消费者
        # （billing/consumer.py）校验同源；存量行已按同算法重算（P7）。
        payload = {
            "operation_id": operation_id,
            "customer_id": customer_id,
            "candidates": normalized_numbers,
        }
        pf = payload_digest(payload)
        cur.execute(
            "INSERT INTO billing_outbox "
            " (aggregate_id, aggregate_type, aggregate_version, payload, payload_digest) "
            "VALUES (%s,'submission_operation',1,%s::jsonb,%s)",
            (operation_id, json.dumps(payload, ensure_ascii=False), pf),
        )

        # 10) 幂等记录（存响应快照供重放）
        snapshot = {
            "operation_id": op_public_id,
            "total_count": total_count,
            "points_charged": billable_count,
            "free_count": waived_count,
            "balance": new_balance,
        }
        cur.execute(
            "INSERT INTO idempotency_record "
            " (customer_id, endpoint, client_request_id, request_fingerprint, response_snapshot) "
            "VALUES (%s,%s,%s,%s,%s::jsonb)",
            (customer_id, ENDPOINT, client_request_id, fingerprint,
             json.dumps(snapshot, ensure_ascii=False)),
        )

    return SubmitOutcome(
        operation_public_id=op_public_id,
        total_count=total_count,
        billable_count=billable_count,
        waived_count=waived_count,
        balance=new_balance,
    )
