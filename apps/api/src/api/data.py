"""B 库数据访问层（09 §3.3：所有查询强制 tenant scope）。

BFF 只持有 B 库凭据，不碰 A 库。对外 ID 一律 UUID（public_id），内部 bigint
不暴露。所有 SQL 参数绑定。
"""
from __future__ import annotations

import hashlib
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator

import psycopg

from pandatrack_common import codes

from api.errors import ApiProblem


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class BRepository:
    """B 库访问；dsn 由环境变量注入，本类不读 A 库。"""

    def __init__(self, dsn: str):
        self.dsn = dsn

    @contextmanager
    def connect(self) -> Iterator[psycopg.Connection]:
        with psycopg.connect(self.dsn) as conn:
            yield conn

    # ---- 鉴权 ----
    def authenticate(self, email: str, password: str) -> dict:
        """校验邮箱+密码，返回客户主体（含 tenant scope）。密码只做哈希比对。"""
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT customer_id, public_id, password_hash, status, role,
                              tenant_id, email
                       FROM customer WHERE email=%s""",
                    (email,),
                )
                row = cur.fetchone()
        if row is None or not self._verify_password(password, row[2]):
            raise ApiProblem(codes.UNAUTHORIZED)
        if row[3] != "active":
            raise ApiProblem(codes.FORBIDDEN)
        return {"customer_id": row[0], "public_id": str(row[1]),
                "role": row[4], "tenant_id": row[5], "email": row[6]}

    @staticmethod
    def _verify_password(password: str, stored: str) -> bool:
        # 支持 scrypt/pbkdf2 风格 "scheme$salt$hash"；真实验收区用 argon2/bcrypt。
        # 这里提供确定性 scrypt 校验（标准库，无额外依赖）。
        if stored.startswith("scrypt$"):
            _, salt, expected = stored.split("$", 2)
            import hashlib as hl
            got = hl.scrypt(password.encode(), salt=bytes.fromhex(salt),
                            n=2**14, r=8, p=1, dklen=32).hex()
            return got == expected
        # 兼容历史明文/简单 sha256（仅开发种子数据，生产禁用）。
        return hashlib.sha256(password.encode()).hexdigest() == stored

    @staticmethod
    def hash_password(password: str) -> str:
        import secrets
        salt = secrets.token_bytes(16)
        digest = hashlib.scrypt(password.encode(), salt=salt,
                                n=2**14, r=8, p=1, dklen=32).hex()
        return f"scrypt${salt.hex()}${digest}"

    def create_session(self, subject: dict, token: str, *, ttl_seconds: int = 3600) -> None:
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO session (customer_id, admin_id, token_hash, expires_at)
                       VALUES (%s, %s, %s, %s)""",
                    (subject.get("customer_id"), subject.get("admin_id"),
                     token_hash(token),
                     datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)),
                )
                conn.commit()

    def resolve_session(self, token: str) -> dict | None:
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT s.customer_id, s.admin_id, c.public_id, c.email,
                              c.role, c.tenant_id, c.status
                       FROM session s
                       LEFT JOIN customer c ON c.customer_id=s.customer_id
                       WHERE s.token_hash=%s AND s.revoked=false AND s.expires_at>now()""",
                    (token_hash(token),),
                )
                row = cur.fetchone()
        if row is None:
            return None
        if row[6] is not None and row[6] != "active":
            raise ApiProblem(codes.FORBIDDEN)
        return {"customer_id": row[0], "admin_id": row[1],
                "public_id": str(row[2]) if row[2] else None,
                "email": row[3], "role": row[4], "tenant_id": row[5]}

    def wallet_balance(self, customer_id: int) -> int:
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT balance FROM wallet WHERE customer_id=%s",
                            (customer_id,))
                row = cur.fetchone()
        return row[0] if row else 0

    def wallet_detail(self, customer_id: int) -> dict | None:
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT balance, frozen, lifetime_consumed FROM wallet
                       WHERE customer_id=%s""",
                    (customer_id,),
                )
                row = cur.fetchone()
        if not row:
            return None
        return {"balance": row[0], "frozen": row[1], "lifetime_consumed": row[2]}

    def ledger_entries(self, customer_id: int, limit: int = 200) -> list[dict]:
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT public_id, ledger_type, points_change, description, created_at
                       FROM points_ledger WHERE customer_id=%s
                       ORDER BY created_at DESC LIMIT %s""",
                    (customer_id, limit),
                )
                rows = cur.fetchall()
        return [{"ledger_id": str(r[0]), "ledger_type": r[1],
                 "points_change": r[2], "description": r[3],
                 "created_at": r[4].isoformat() if r[4] else ""} for r in rows]

    def redeem(self, customer_id: int, code: str) -> tuple[int, int]:
        """核销兑换码：单事务锁码→标 redeemed→钱包加积分→追加 redeem 流水。

        03 §3.2：不直接 patch 余额，必须追加 PointsLedger。重复核销抛 ValueError。
        """
        with self.connect() as conn:
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """SELECT code_id, points FROM redemption_code
                           WHERE code=%s AND status='active' FOR UPDATE""", (code,)
                    )
                    row = cur.fetchone()
                    if row is None:
                        raise ValueError("invalid or redeemed code")
                    code_id, points = row
                    cur.execute(
                        """UPDATE redemption_code
                           SET status='redeemed', redeemed_by=%s, redeemed_at=now()
                           WHERE code_id=%s""", (code_id, customer_id))
                    cur.execute(
                        """UPDATE wallet SET balance=balance+%s, updated_at=now()
                           WHERE customer_id=%s RETURNING balance""",
                        (points, customer_id))
                    balance = cur.fetchone()[0]
                    cur.execute(
                        """INSERT INTO points_ledger
                           (customer_id, ledger_type, points_change, reference_type,
                            reference_id, description)
                           VALUES (%s,'redeem',%s,'redemption_code',%s,'兑换码充值')""",
                        (customer_id, points, code_id))
                conn.commit()
                return points, balance
            except Exception:
                conn.rollback()
                raise

    # ---- operation（tenant scope）----
    def operation(self, public_id: str, customer_id: int) -> dict | None:
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT operation_id, public_id, state, total_count, valid_count,
                              invalid_count, points_charged
                       FROM submission_operation
                       WHERE public_id=%s::uuid AND customer_id=%s""",
                    (public_id, customer_id),
                )
                row = cur.fetchone()
        if not row:
            return None
        return {"operation_id": row[0], "public_id": str(row[1]),
                "state": row[2], "total_count": row[3], "valid_count": row[4],
                "invalid_count": row[5], "points_charged": row[6]}

    def operation_batches(self, operation_id: int) -> list[dict]:
        """批次进度聚合（done/processing/deferred/suspended 由 item/batch state 汇总）。"""
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT batch_seq, item_count, state FROM submission_batch
                       WHERE operation_id=%s ORDER BY batch_seq""",
                    (operation_id,),
                )
                rows = cur.fetchall()
        return [{
            "batch_seq": r[0], "item_count": r[1],
            "done": r[1] if r[2] in ("done", "succeeded", "completed") else 0,
            "processing": r[1] if r[2] in ("processing", "running") else 0,
            "deferred": r[1] if r[2] in ("pending", "retry_scheduled") else 0,
            "suspended": r[1] if r[2] in ("suspended", "dead_letter") else 0,
        } for r in rows]

    # ---- tracking 投影（tenant scope，对外 UUID）----
    def tracking(self, customer_tracking_uuid: str, customer_id: int) -> dict | None:
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT ct.public_id, ct.normalized_number, tp.status, tp.events,
                              tp.projected_at,
                              NULL::timestamptz AS next_sync_at,
                              tp.projected_at AS last_success_at
                       FROM customer_tracking ct
                       LEFT JOIN tracking_projection tp
                         ON tp.customer_tracking_id=ct.customer_tracking_id
                       WHERE ct.public_id=%s::uuid AND ct.customer_id=%s""",
                    (customer_tracking_uuid, customer_id),
                )
                row = cur.fetchone()
        if not row:
            return None
        return {"customer_tracking_id": str(row[0]), "normalized_number": row[1],
                "status": row[2], "events": row[3] or [], "projected_at": row[4],
                "next_sync_at": row[5], "last_success_at": row[6]}

    def list_trackings(self, customer_id: int) -> list[dict]:
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT ct.public_id, ct.normalized_number, tp.status,
                              tp.events, tp.projected_at
                       FROM customer_tracking ct
                       LEFT JOIN tracking_projection tp
                         ON tp.customer_tracking_id=ct.customer_tracking_id
                       WHERE ct.customer_id=%s ORDER BY ct.created_at DESC LIMIT 1000""",
                    (customer_id,),
                )
                rows = cur.fetchall()
        return [{"customer_tracking_id": str(r[0]), "normalized_number": r[1],
                 "status": r[2], "events": r[3] or [], "projected_at": r[4],
                 "next_sync_at": None, "last_success_at": r[4]} for r in rows]

    def projection_events(self, customer_id: int, *, after: int = 0,
                          limit: int = 50) -> list[dict]:
        """SSE 事件投影：只取本租户授权 operation 的事件，按 event_id 递增重放。"""
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT pe.event_id, pe.payload, pe.created_at
                       FROM projection_event pe
                       JOIN submission_operation so ON so.operation_id=pe.operation_id
                       WHERE so.customer_id=%s AND pe.event_id>%s
                       ORDER BY pe.event_id LIMIT %s""",
                    (customer_id, after, limit),
                )
                rows = cur.fetchall()
        return [{"event_id": r[0], "payload": r[1],
                 "created_at": r[2].isoformat() if r[2] else ""} for r in rows]

    def recent_success_numbers(self, customer_id: int, hours: int) -> set[str]:
        """库内近期成功(24h)单号，供 dispatch recent_checker。"""
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT normalized_number FROM billing_charge_window
                       WHERE customer_id=%s AND active=true
                         AND charged_at > now() - make_interval(hours=>%s)""",
                    (customer_id, hours),
                )
                return {r[0] for r in cur.fetchall()}
