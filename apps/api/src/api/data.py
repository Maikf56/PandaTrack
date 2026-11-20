"""B 库数据访问层（09 §3.3：所有查询强制 tenant scope）。

BFF 只持有 B 库凭据，不碰 A 库。对外 ID 一律 UUID（public_id），内部 bigint
不暴露。所有 SQL 参数绑定。
"""
from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator

import psycopg

from pandatrack_common import codes
from pandatrack_common.status import TERMINAL_STATUSES

from api.errors import ApiProblem
from api.throttle import next_lock_seconds


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class BRepository:
    """B 库访问；dsn 由环境变量注入。

    管理端观察类方法（provider/fetch_job）需要 A 库只读访问，
    通过可选 dsn_a 短生命周期打开，客户路由绝不触碰 A 库。
    """

    def __init__(self, dsn: str, dsn_a: str | None = None):
        self.dsn = dsn
        self.dsn_a = dsn_a

    @contextmanager
    def connect(self) -> Iterator[psycopg.Connection]:
        with psycopg.connect(self.dsn) as conn:
            yield conn

    @contextmanager
    def connect_a(self) -> Iterator[psycopg.Connection]:
        """A 库短连接（仅管理端观察/操作使用）。"""
        if not self.dsn_a:
            raise RuntimeError("A 库 DSN 未配置（DATABASE_A_URL）")
        with psycopg.connect(self.dsn_a) as conn:
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
        # 返回 None 而非抛错：调用方（登录路由）需在 401 前记录防爆破失败。
        if row is None or not self._verify_password(password, row[2]):
            return None
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

    def list_operations(self, customer_id: int, *,
                        limit: int = 50, offset: int = 0) -> tuple[list[dict], int]:
        """客户提交记录列表（tenant scope，最新在前；对外仅 public_id）。"""
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT count(*) FROM submission_operation WHERE customer_id=%s",
                    (customer_id,))
                total = cur.fetchone()[0]
                cur.execute(
                    """SELECT public_id, state, total_count, valid_count,
                              invalid_count, points_charged, created_at
                       FROM submission_operation
                       WHERE customer_id=%s
                       ORDER BY created_at DESC LIMIT %s OFFSET %s""",
                    (customer_id, limit, offset))
                rows = cur.fetchall()
        return ([{"public_id": str(r[0]), "state": r[1], "total_count": r[2],
                  "valid_count": r[3], "invalid_count": r[4], "points_charged": r[5],
                  "created_at": r[6].isoformat() if r[6] else ""}
                 for r in rows], total)

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
        """客户单号列表（结果页）：附分组名与最近一次提交批次（P14 分组视图）。

        批次经 submission_item→submission_batch→submission_operation 按单号
        关联（idx_submission_item_normalized_number 已建索引）；同号多次提交
        取最近一次。未分组/从未提交的单号对应字段为 None。
        """
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT ct.public_id, ct.normalized_number, tp.status,
                              tp.events, tp.projected_at, g.name,
                              op.public_id, op.created_at
                       FROM customer_tracking ct
                       LEFT JOIN tracking_projection tp
                         ON tp.customer_tracking_id=ct.customer_tracking_id
                       LEFT JOIN target_group g ON g.group_id=ct.group_id
                       LEFT JOIN LATERAL (
                           SELECT so.public_id, so.created_at
                           FROM submission_item si
                           JOIN submission_batch sb ON sb.batch_id=si.batch_id
                           JOIN submission_operation so
                             ON so.operation_id=sb.operation_id
                           WHERE si.normalized_number=ct.normalized_number
                             AND so.customer_id=ct.customer_id
                           ORDER BY so.created_at DESC LIMIT 1
                       ) op ON true
                       WHERE ct.customer_id=%s ORDER BY ct.created_at DESC LIMIT 1000""",
                    (customer_id,),
                )
                rows = cur.fetchall()
        return [{"customer_tracking_id": str(r[0]), "normalized_number": r[1],
                 "status": r[2], "events": r[3] or [], "projected_at": r[4],
                 "next_sync_at": None, "last_success_at": r[4],
                 "group_name": r[5],
                 "batch_id": str(r[6]) if r[6] else None,
                 "batch_created_at": r[7].isoformat() if r[7] else None}
                for r in rows]

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

    # ========== 管理端（03）：admin 鉴权、客户/账务/Provider/审计 ==========

    def authenticate_admin(self, username: str, password: str) -> dict | None:
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT admin_id, public_id, username, password_hash, role, status
                       FROM admin_user WHERE username=%s""",
                    (username,),
                )
                row = cur.fetchone()
        if row is None or not self._verify_password(password, row[3]):
            return None
        if row[5] != "active":
            return None
        return {"admin_id": row[0], "public_id": str(row[1]),
                "username": row[2], "role": row[4]}

    def create_admin_session(self, subject: dict, token: str, *, ttl_seconds: int = 1800) -> None:
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO session (customer_id, admin_id, token_hash, expires_at)
                       VALUES (NULL, %s, %s, %s)""",
                    (subject["admin_id"], token_hash(token),
                     datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)),
                )
                conn.commit()

    def resolve_admin_session(self, token: str) -> dict | None:
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT s.admin_id, a.public_id, a.username, a.role, a.status
                       FROM session s
                       JOIN admin_user a ON a.admin_id=s.admin_id
                       WHERE s.token_hash=%s AND s.revoked=false
                         AND s.expires_at>now() AND s.customer_id IS NULL""",
                    (token_hash(token),),
                )
                row = cur.fetchone()
        if row is None or row[4] != "active":
            return None
        return {"admin_id": row[0], "public_id": str(row[1]),
                "username": row[2], "role": row[3]}

    # ---- 登录防爆破（09 §5.1；api.throttle 计算锁定时长）----

    def login_throttle_locked_until(self, scope: str, key: str) -> datetime | None:
        """未过期的锁定时刻；未锁或已过期返回 None。"""
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT locked_until FROM auth_throttle
                       WHERE scope=%s AND key=%s
                         AND locked_until IS NOT NULL AND locked_until > now()""",
                    (scope, key),
                )
                row = cur.fetchone()
        return row[0] if row else None

    def login_throttle_record_fail(self, scope: str, key: str, *,
                                   window_seconds: int, max_attempts: int) -> int:
        """记一次失败（窗口外重置计数），返回含本次的失败次数。"""
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO auth_throttle (scope, key, fail_count,
                                                 last_fail_at, updated_at)
                       VALUES (%s, %s, 1, now(), now())
                       ON CONFLICT (scope, key) DO UPDATE SET
                         fail_count = CASE
                           WHEN auth_throttle.last_fail_at
                                < now() - make_interval(secs => %s) THEN 1
                           ELSE auth_throttle.fail_count + 1 END,
                         last_fail_at = now(), updated_at = now()
                       RETURNING fail_count""",
                    (scope, key, window_seconds),
                )
                fail_count: int = cur.fetchone()[0]
                lock_seconds = next_lock_seconds(fail_count,
                                                 max_attempts=max_attempts)
                if lock_seconds > 0:
                    cur.execute(
                        """UPDATE auth_throttle
                           SET locked_until = now() + make_interval(secs => %s)
                           WHERE scope=%s AND key=%s""",
                        (lock_seconds, scope, key),
                    )
                conn.commit()
        return fail_count

    def login_throttle_reset(self, scope: str, key: str) -> None:
        """登录成功清零失败计数与锁定。"""
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE auth_throttle
                       SET fail_count=0, locked_until=NULL, updated_at=now()
                       WHERE scope=%s AND key=%s""",
                    (scope, key),
                )
                conn.commit()

    # ---- 轨迹翻译缓存（api.translate 调用；Google v2 + digest 复用）----

    def translation_cache_get(self, lang: str,
                              digests: list[str]) -> dict[str, str]:
        """批量取缓存：digest → 译文。"""
        if not digests:
            return {}
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT source_digest, translated FROM translation_cache
                       WHERE lang=%s AND source_digest = ANY(%s)""",
                    (lang, digests),
                )
                return {r[0]: r[1] for r in cur.fetchall()}

    def translation_cache_put(self, lang: str,
                              entries: list[tuple[str, str, str]]) -> None:
        """批量写入缓存：[(digest, source_text, translated)]，幂等去重。"""
        if not entries:
            return
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.executemany(
                    """INSERT INTO translation_cache
                         (lang, source_digest, source_text, translated)
                       VALUES (%s, %s, %s, %s)
                       ON CONFLICT (lang, source_digest) DO NOTHING""",
                    [(lang, d, s, t) for d, s, t in entries],
                )
                conn.commit()

    # ---- 客户/租户/席位（只读 + 状态变更）----
    def list_customers(self, *, tenant_id: int | None = None,
                       limit: int = 100, offset: int = 0) -> tuple[list[dict], int]:
        """客户列表（管理端）：带钱包余额（LEFT JOIN，无钱包行视为 0）。"""
        with self.connect() as conn:
            with conn.cursor() as cur:
                if tenant_id is not None:
                    cur.execute(
                        "SELECT count(*) FROM customer WHERE tenant_id=%s", (tenant_id,))
                else:
                    cur.execute("SELECT count(*) FROM customer")
                total = cur.fetchone()[0]
                base_sql = (
                    """SELECT c.customer_id, c.public_id, c.email, c.status, c.role,
                              c.tenant_id, c.created_at,
                              COALESCE(w.balance, 0) AS balance
                       FROM customer c
                       LEFT JOIN wallet w ON w.customer_id = c.customer_id""")
                if tenant_id is not None:
                    cur.execute(
                        base_sql + " WHERE c.tenant_id=%s ORDER BY c.created_at DESC"
                        " LIMIT %s OFFSET %s",
                        (tenant_id, limit, offset))
                else:
                    cur.execute(
                        base_sql + " ORDER BY c.created_at DESC LIMIT %s OFFSET %s",
                        (limit, offset))
                rows = cur.fetchall()
        return ([{"customer_id": r[0], "public_id": str(r[1]), "email": r[2],
                  "status": r[3], "role": r[4], "tenant_id": r[5],
                  "created_at": r[6].isoformat() if r[6] else "",
                  "balance": r[7]}
                 for r in rows], total)

    def update_customer_status(self, customer_id: int, status: str) -> bool:
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE customer SET status=%s, updated_at=now() WHERE customer_id=%s",
                    (status, customer_id))
                return cur.rowcount > 0

    # ---- Provider 健康/任务（只读）----
    def provider_health(self) -> list[dict]:
        with self.connect_a() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT provider_code, enabled, circuit_open, consecutive_failures,
                              cooldown_until, updated_at
                       FROM provider_health ORDER BY updated_at DESC""")
                rows = cur.fetchall()
        return [{"provider_code": r[0], "enabled": r[1], "circuit_open": r[2],
                 "consecutive_failures": r[3], "cooldown_until": r[4].isoformat() if r[4] else None,
                 "updated_at": r[5].isoformat() if r[5] else None} for r in rows]

    def queue_snapshot(self) -> dict:
        with self.connect_a() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT state, count(*) FROM fetch_job GROUP BY state ORDER BY state""")
                rows = cur.fetchall()
                cur.execute("SELECT count(*) FROM fetch_job WHERE state='dead_letter'")
                dead = cur.fetchone()[0]
        return {"by_state": {r[0]: r[1] for r in rows}, "dead_letter": dead}

    # ---- 积分调整（追加 PointsLedger，不直接 patch 钱包绝对值）----
    def admin_adjust_points(self, customer_id: int, delta: int,
                            description: str, *, actor_id: int, actor_role: str) -> dict:
        """admin 积分调整：追加 PointsLedger + 同步 wallet balance（相对值）。"""
        if delta == 0:
            raise ValueError("delta 不能为 0")
        with self.connect() as conn:
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """INSERT INTO points_ledger
                           (customer_id, ledger_type, points_change, description)
                           VALUES (%s, 'admin_adjust', %s, %s)
                           RETURNING ledger_id""",
                        (customer_id, delta, description))
                    ledger_id = cur.fetchone()[0]
                    cur.execute(
                        """UPDATE wallet SET balance=balance+%s, updated_at=now()
                           WHERE customer_id=%s RETURNING balance""",
                        (delta, customer_id))
                    row = cur.fetchone()
                    if row is None:
                        raise ValueError("wallet not found")
                    balance = row[0]
                    cur.execute(
                        """INSERT INTO audit_log (actor_id, actor_role, action, target, detail)
                           VALUES (%s, %s, 'admin_adjust_points', %s, %s)""",
                        (actor_id, actor_role, str(customer_id),
                         json.dumps({"delta": delta, "ledger_id": str(ledger_id),
                                     "new_balance": balance})))
                conn.commit()
                return {"ledger_id": str(ledger_id), "new_balance": balance}
            except Exception:
                conn.rollback()
                raise

    # ---- 审计日志 ----
    def write_audit(self, *, actor_id: int, actor_role: str,
                    action: str, target: str, detail: dict | None = None) -> None:
        """写入审计日志（管理端所有写操作强制调用，03 §3.1/§3.4）。"""
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO audit_log (actor_id, actor_role, action, target, detail)
                       VALUES (%s, %s, %s, %s, %s)""",
                    (actor_id, actor_role, action, target,
                     json.dumps(detail) if detail is not None else None))
            conn.commit()

    def toggle_provider(self, provider_code: str, enabled: bool) -> bool:
        """Provider 启停（A 库 provider_health）；返回是否存在该 Provider。"""
        with self.connect_a() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE provider_health SET enabled=%s, updated_at=now()
                       WHERE provider_code=%s RETURNING provider_code""",
                    (enabled, provider_code))
                ok = cur.fetchone() is not None
            conn.commit()
        return ok

    def audit_log(self, *, limit: int = 100, offset: int = 0,
                  actor_id: int | None = None, action: str | None = None,
                  target: str | None = None) -> tuple[list[dict], int]:
        with self.connect() as conn:
            with conn.cursor() as cur:
                where = "WHERE 1=1"
                params: list = []
                if actor_id is not None:
                    where += " AND actor_id=%s"
                    params.append(actor_id)
                if action is not None:
                    where += " AND action=%s"
                    params.append(action)
                if target is not None:
                    where += " AND target=%s"
                    params.append(target)
                cur.execute(f"SELECT count(*) FROM audit_log {where}", params)
                total = cur.fetchone()[0]
                cur.execute(
                    f"""SELECT audit_id, actor_id, actor_role, action, target, detail, created_at
                        FROM audit_log {where}
                        ORDER BY created_at DESC LIMIT %s OFFSET %s""",
                    (*params, limit, offset),
                )
                rows = cur.fetchall()
        return ([{"audit_id": r[0], "actor_id": r[1], "actor_role": r[2],
                 "action": r[3], "target": r[4], "detail": r[5],
                 "created_at": r[6].isoformat() if r[6] else ""}
                for r in rows], total)

    # ============ 次要页面：组与批次 / 导入 / 导出 / 统计 / 设置 ============
    # （04 §5.8-5.12；b/0004 扩列。全部 tenant scope，对外 public_id。）

    # ---- 组与批次 ----
    def list_groups(self, customer_id: int) -> list[dict]:
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT g.group_id, g.public_id, g.name, g.is_default,
                              g.archived_at, g.created_at,
                              (SELECT count(*) FROM customer_tracking ct
                                WHERE ct.group_id = g.group_id) AS tracking_count,
                              (SELECT count(*) FROM submission_operation so
                                WHERE so.group_id = g.group_id) AS batch_count
                       FROM target_group g
                       WHERE g.customer_id=%s
                       ORDER BY g.is_default DESC, g.created_at""",
                    (customer_id,))
                rows = cur.fetchall()
                # 最近状态分布：组内单号的投影状态计数。
                cur.execute(
                    """SELECT ct.group_id, tp.status, count(*)
                       FROM customer_tracking ct
                       JOIN tracking_projection tp
                         ON tp.customer_tracking_id = ct.customer_tracking_id
                       WHERE ct.customer_id=%s AND ct.group_id IS NOT NULL
                       GROUP BY ct.group_id, tp.status""",
                    (customer_id,))
                dist: dict[int, dict[str, int]] = {}
                for gid, status, n in cur.fetchall():
                    dist.setdefault(gid, {})[status or "other"] = n
        return [{"id": str(r[1]), "name": r[2], "is_default": r[3],
                 "archived": r[4] is not None,
                 "tracking_count": r[6], "batch_count": r[7],
                 "status_distribution": dist.get(r[0], {}),
                 "created_at": r[5].isoformat() if r[5] else ""}
                for r in rows]

    def create_group(self, customer_id: int, name: str) -> dict:
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO target_group (customer_id, name)
                       VALUES (%s, %s) RETURNING group_id, public_id""",
                    (customer_id, name))
                gid, pub = cur.fetchone()
            conn.commit()
        return {"id": str(pub), "name": name, "is_default": False,
                "archived": False, "tracking_count": 0, "batch_count": 0,
                "status_distribution": {}, "created_at": ""}

    def rename_group(self, customer_id: int, group_public_id: str,
                     name: str) -> bool:
        return self._group_update(
            customer_id, group_public_id,
            """UPDATE target_group SET name=%s, updated_at=now()
               WHERE customer_id=%s AND public_id=%s
               RETURNING group_id""",
            (name, customer_id, group_public_id))

    def archive_group(self, customer_id: int, group_public_id: str,
                      archive: bool) -> bool:
        return self._group_update(
            customer_id, group_public_id,
            """UPDATE target_group
               SET archived_at=%s, updated_at=now()
               WHERE customer_id=%s AND public_id=%s RETURNING group_id""",
            (datetime.now(timezone.utc) if archive else None,
             customer_id, group_public_id))

    def delete_group(self, customer_id: int, group_public_id: str) -> bool:
        """删除组只清组织关系（成员/批次 group_id 置空），不动事实与账务。"""
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """DELETE FROM target_group
                       WHERE customer_id=%s AND public_id=%s
                       RETURNING group_id""",
                    (customer_id, group_public_id))
                row = cur.fetchone()
                if row is None:
                    return False
                gid = row[0]
                cur.execute(
                    "UPDATE customer_tracking SET group_id=NULL WHERE group_id=%s",
                    (gid,))
                cur.execute(
                    """UPDATE submission_operation SET group_id=NULL
                       WHERE group_id=%s""", (gid,))
            conn.commit()
        return True

    def _group_update(self, customer_id: int, group_public_id: str,
                      sql: str, params: tuple) -> bool:
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                ok = cur.fetchone() is not None
            conn.commit()
        return ok

    def ensure_default_group(self, customer_id: int) -> int:
        """取（或建）客户默认组，返回内部 group_id（04 §5.8）。"""
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT group_id FROM target_group
                       WHERE customer_id=%s AND is_default=true
                       ORDER BY group_id LIMIT 1""", (customer_id,))
                row = cur.fetchone()
                if row:
                    return row[0]
                cur.execute(
                    """INSERT INTO target_group (customer_id, name, is_default)
                       VALUES (%s, '默认组', true) RETURNING group_id""",
                    (customer_id,))
                gid = cur.fetchone()[0]
            conn.commit()
        return gid

    def assign_operation_group(self, customer_id: int,
                               operation_public_id: str, group_id: int) -> None:
        """批次归组 + 单号补挂组（仅补空缺，不覆盖客户手动分组）。"""
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE submission_operation so SET group_id=%s
                       FROM (SELECT operation_id FROM submission_operation
                             WHERE public_id=%s AND customer_id=%s) op
                       WHERE so.operation_id = op.operation_id
                         AND so.group_id IS NULL""",
                    (group_id, operation_public_id, customer_id))
                cur.execute(
                    """UPDATE customer_tracking ct SET group_id=%s
                       WHERE ct.customer_id=%s AND ct.group_id IS NULL
                         AND ct.normalized_number IN (
                           SELECT si.normalized_number
                           FROM submission_item si
                           JOIN submission_batch sb ON sb.batch_id=si.batch_id
                           JOIN submission_operation so
                             ON so.operation_id=sb.operation_id
                           WHERE so.public_id=%s
                             AND si.normalized_number IS NOT NULL)""",
                    (group_id, customer_id, operation_public_id))
            conn.commit()

    def list_batches(self, customer_id: int, *,
                     group_id: str | None = None,
                     limit: int = 50) -> list[dict]:
        """操作（批次）列表：含终态/无投影计数口径（04 §5.8 批次详情）。"""
        where = "so.customer_id=%s"
        params: list = [customer_id]
        if group_id is not None:
            where += " AND g.public_id=%s"
            params.append(group_id)
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""SELECT so.operation_id, so.public_id, so.state, so.total_count,
                               so.valid_count, so.points_charged,
                               so.created_at, so.updated_at, g.name
                        FROM submission_operation so
                        LEFT JOIN target_group g ON g.group_id=so.group_id
                        WHERE {where}
                        ORDER BY so.created_at DESC LIMIT %s""",
                    (*params, limit))
                rows = cur.fetchall()
                # 各批次物流状态分布（三级页面批次卡片，P15）。
                cur.execute(
                    """SELECT so.operation_id, tp.status, count(*)
                       FROM submission_operation so
                       JOIN submission_batch sb ON sb.operation_id=so.operation_id
                       JOIN submission_item si ON si.batch_id=sb.batch_id
                         AND si.is_valid=true
                       JOIN customer_tracking ct
                         ON ct.customer_id=so.customer_id
                        AND ct.normalized_number=si.normalized_number
                       LEFT JOIN tracking_projection tp
                         ON tp.customer_tracking_id=ct.customer_tracking_id
                       WHERE so.customer_id=%s
                       GROUP BY so.operation_id, tp.status""",
                    (customer_id,))
                dist: dict[int, dict[str, int]] = {}
                for oid, status, n in cur.fetchall():
                    dist.setdefault(oid, {})[status or "other"] = n
        return [{"id": str(r[1]), "state": r[2], "total_count": r[3],
                 "valid_count": r[4], "points_charged": r[5],
                 "group_name": r[8],
                 "status_distribution": dist.get(r[0], {}),
                 "created_at": r[6].isoformat() if r[6] else "",
                 "updated_at": r[7].isoformat() if r[7] else ""}
                for r in rows]

    def batch_detail(self, customer_id: int, operation_public_id: str) -> dict | None:
        """批次详情：总量/已完成/处理中/暂未获取/失败待处理 + 状态分布。"""
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT operation_id, public_id, state, total_count,
                              valid_count, invalid_count, points_charged,
                              created_at, updated_at
                       FROM submission_operation
                       WHERE customer_id=%s AND public_id=%s""",
                    (customer_id, operation_public_id))
                op = cur.fetchone()
                if op is None:
                    return None
                oid = op[0]
                cur.execute(
                    """SELECT count(*) FILTER (WHERE tp.status = ANY(%s)),
                              count(*) FILTER (WHERE tp.status IS NOT NULL
                                               AND tp.status != 'other'),
                              count(*) FILTER (WHERE ct.customer_tracking_id IS NULL)
                       FROM submission_item si
                       LEFT JOIN customer_tracking ct
                         ON ct.customer_id=%s
                        AND ct.normalized_number=si.normalized_number
                       LEFT JOIN tracking_projection tp
                         ON tp.customer_tracking_id=ct.customer_tracking_id
                       JOIN submission_batch sb ON sb.batch_id=si.batch_id
                       WHERE sb.operation_id=%s AND si.is_valid=true""",
                    (list(TERMINAL_STATUSES), customer_id, oid))
                terminal, processing, missing = cur.fetchone()
        return {"id": str(op[1]), "state": op[2], "total_count": op[3],
                "valid_count": op[4], "invalid_count": op[5],
                "points_charged": op[6],
                "completed": terminal, "processing": processing,
                "missing": missing,
                "created_at": op[7].isoformat() if op[7] else "",
                "updated_at": op[8].isoformat() if op[8] else ""}

    # ---- 导入任务 ----
    def list_imports(self, customer_id: int, *,
                     limit: int = 50) -> list[dict]:
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT i.public_id, i.file_name, i.status, i.total,
                              i.done, i.enqueued, i.success_count,
                              i.failed_count, i.skipped_count,
                              i.duplicate_count, i.created_at,
                              so.public_id
                       FROM import_job i
                       LEFT JOIN submission_operation so
                         ON so.operation_id=i.operation_id
                       WHERE i.customer_id=%s
                       ORDER BY i.created_at DESC LIMIT %s""",
                    (customer_id, limit))
                rows = cur.fetchall()
        return [{"id": str(r[0]), "file_name": r[1], "status": r[2],
                 "total": r[3], "done": r[4], "enqueued": r[5],
                 "success_count": r[6], "failed_count": r[7],
                 "skipped_count": r[8], "duplicate_count": r[9],
                 "operation_id": str(r[11]) if r[11] else None,
                 "created_at": r[10].isoformat() if r[10] else ""}
                for r in rows]

    # ---- 导出任务（短期有效下载，04 §5.9）----
    def create_export(self, customer_id: int, *, scope: str,
                      scope_ref: str | None, export_dir: str) -> dict:
        """按范围同步生成 CSV（验收区规模），路径不回显，token 短期有效。"""
        import csv
        import hashlib
        import secrets
        from pathlib import Path
        rows = self._export_rows(customer_id, scope, scope_ref)
        token = secrets.token_urlsafe(32)
        th = hashlib.sha256(token.encode()).hexdigest()
        directory = Path(export_dir).expanduser()
        directory.mkdir(parents=True, exist_ok=True)
        file_name = f"export-{scope}-{datetime.now(timezone.utc):%Y%m%d%H%M%S}.csv"
        path = directory / f"{secrets.token_hex(8)}.csv"
        with path.open("w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(["normalized_number", "status", "projected_at"])
            w.writerows(rows)
        expires = datetime.now(timezone.utc) + timedelta(minutes=15)
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO export_job (customer_id, status, file_ref,
                           scope, scope_ref, file_name, row_count, expires_at,
                           token_hash)
                       VALUES (%s, 'done', %s, %s, %s, %s, %s, %s, %s)
                       RETURNING public_id""",
                    (customer_id, str(path), scope, scope_ref, file_name,
                     len(rows), expires, th))
                pub = cur.fetchone()[0]
            conn.commit()
        return {"id": str(pub), "scope": scope, "scope_ref": scope_ref,
                "format": "csv", "file_name": file_name,
                "row_count": len(rows), "status": "done", "token": token,
                "expires_at": expires.isoformat(), "created_at": ""}

    def _export_rows(self, customer_id: int, scope: str,
                     scope_ref: str | None) -> list[tuple]:
        if scope not in ("all", "group", "batch"):
            raise ValueError("invalid export scope")
        where = "ct.customer_id=%s"
        params: list = [customer_id]
        if scope == "group":
            where += " AND g.public_id=%s"
            params.append(scope_ref)
        elif scope == "batch":
            where = """ct.customer_id=%s AND ct.normalized_number IN (
                         SELECT si.normalized_number FROM submission_item si
                         JOIN submission_batch sb ON sb.batch_id=si.batch_id
                         WHERE sb.operation_id=(SELECT operation_id FROM
                           submission_operation WHERE customer_id=%s
                           AND public_id=%s))"""
            params = [customer_id, customer_id, scope_ref]
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""SELECT ct.normalized_number, tp.status, tp.projected_at
                        FROM customer_tracking ct
                        LEFT JOIN target_group g ON g.group_id=ct.group_id
                        LEFT JOIN tracking_projection tp
                          ON tp.customer_tracking_id=ct.customer_tracking_id
                        WHERE {where} ORDER BY ct.normalized_number""",
                    params)
                rows = [(r[0], r[1] or "",
                         r[2].isoformat() if r[2] else "") for r in cur.fetchall()]
        return rows

    def list_exports(self, customer_id: int, *, limit: int = 50) -> list[dict]:
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT public_id, scope, scope_ref, format, file_name,
                              row_count, status, expires_at, created_at
                       FROM export_job WHERE customer_id=%s
                       ORDER BY created_at DESC LIMIT %s""",
                    (customer_id, limit))
                rows = cur.fetchall()
        now = datetime.now(timezone.utc)
        return [{"id": str(r[0]), "scope": r[1], "scope_ref": r[2],
                 "format": r[3], "file_name": r[4], "row_count": r[5],
                 "status": r[6],
                 "expired": r[7] is not None and r[7] < now,
                 "expires_at": r[7].isoformat() if r[7] else None,
                 "created_at": r[8].isoformat() if r[8] else ""}
                for r in rows]

    def resolve_download(self, customer_id: int, export_public_id: str,
                         token: str) -> tuple[str, str] | None:
        """校验 token/过期/归属 → (文件路径, 文件名)；不符返回 None。"""
        import hashlib
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT file_ref, file_name, token_hash, expires_at, status
                       FROM export_job
                       WHERE customer_id=%s AND public_id=%s""",
                    (customer_id, export_public_id))
                row = cur.fetchone()
        if row is None or row[2] is None:
            return None
        if row[2] != hashlib.sha256(token.encode()).hexdigest():
            return None
        if row[4] != "done" or not row[1]:
            return None
        if row[3] is not None and row[3] < datetime.now(timezone.utc):
            return None
        return row[0], row[1]

    # ---- 查询统计（服务端口径，前端不推算，04 §5.10）----
    def stats_summary(self, customer_id: int, *, days: int = 30) -> dict:
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT count(*), coalesce(sum(total_count),0),
                              coalesce(sum(points_charged),0)
                       FROM submission_operation
                       WHERE customer_id=%s
                         AND created_at > now() - make_interval(days=>%s)""",
                    (customer_id, days))
                submissions, tracking_count, charged = cur.fetchone()
                cur.execute(
                    """SELECT count(*) FROM billing_charge_window
                       WHERE customer_id=%s AND active=true
                         AND charged_at > now() - make_interval(days=>%s)""",
                    (customer_id, days))
                waived = cur.fetchone()[0]
                cur.execute(
                    """SELECT tp.status, count(*)
                       FROM tracking_projection tp
                       JOIN customer_tracking ct
                         ON ct.customer_tracking_id=tp.customer_tracking_id
                       WHERE ct.customer_id=%s GROUP BY tp.status""",
                    (customer_id,))
                distribution = {r[0] or "other": r[1] for r in cur.fetchall()}
                cur.execute(
                    """SELECT date(created_at), count(*)
                       FROM submission_operation
                       WHERE customer_id=%s
                         AND created_at > now() - make_interval(days=>%s)
                       GROUP BY date(created_at) ORDER BY date(created_at)""",
                    (customer_id, days))
                daily = [{"date": str(r[0]), "submissions": r[1]}
                         for r in cur.fetchall()]
        return {"days": days, "submissions": submissions,
                "tracking_count": tracking_count,
                "points_charged": charged, "waived_count": waived,
                "status_distribution": distribution, "daily": daily}

    # ---- 设置页（04 §5.12）----
    def change_password(self, customer_id: int, old_password: str,
                        new_password: str) -> bool:
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT password_hash FROM customer WHERE customer_id=%s",
                    (customer_id,))
                row = cur.fetchone()
                if row is None or not self._verify_password(
                        old_password, row[0]):
                    return False
                cur.execute(
                    """UPDATE customer SET password_hash=%s, updated_at=now()
                       WHERE customer_id=%s""",
                    (self.hash_password(new_password), customer_id))
            conn.commit()
        return True

    def list_sessions(self, customer_id: int,
                      current_token_hash: str) -> list[dict]:
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT session_id, created_at, expires_at, revoked,
                              token_hash
                       FROM session WHERE customer_id=%s
                       ORDER BY created_at DESC LIMIT 50""",
                    (customer_id,))
                rows = cur.fetchall()
        return [{"id": r[0],
                 "created_at": r[1].isoformat() if r[1] else "",
                 "expires_at": r[2].isoformat() if r[2] else "",
                 "revoked": r[3], "current": r[4] == current_token_hash}
                for r in rows]

    def revoke_other_sessions(self, customer_id: int,
                              current_token_hash: str) -> int:
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE session SET revoked=true
                       WHERE customer_id=%s AND token_hash != %s
                         AND revoked=false""",
                    (customer_id, current_token_hash))
                n = cur.rowcount
            conn.commit()
        return n

    def get_preferences(self, customer_id: int) -> dict:
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT preferences FROM customer WHERE customer_id=%s",
                    (customer_id,))
                row = cur.fetchone()
        return row[0] if row and row[0] else {}

    def set_preferences(self, customer_id: int, patch: dict) -> dict:
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE customer
                       SET preferences = coalesce(preferences,'{}') || %s
                       WHERE customer_id=%s RETURNING preferences""",
                    (json.dumps(patch), customer_id))
                row = cur.fetchone()
            conn.commit()
        return row[0] if row else {}

    # ---- 邀请好友（P15 脚手架；奖励结算依赖开放注册）----
    _INVITE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"

    def _new_invite_code(self) -> str:
        import secrets
        return "".join(secrets.choice(self._INVITE_ALPHABET) for _ in range(8))

    def get_or_create_invite(self, customer_id: int) -> dict:
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT code, created_at FROM invite_code "
                    "WHERE customer_id=%s ORDER BY invite_code_id DESC LIMIT 1",
                    (customer_id,))
                row = cur.fetchone()
                if row is None:
                    for _ in range(5):  # code 唯一冲突重试
                        try:
                            cur.execute(
                                "INSERT INTO invite_code (customer_id, code) "
                                "VALUES (%s, %s) RETURNING code",
                                (customer_id, self._new_invite_code()))
                            code = cur.fetchone()[0]
                            break
                        except psycopg.errors.UniqueViolation:
                            continue
                    else:
                        raise ApiProblem(codes.INTERNAL_ERROR)
                    conn.commit()
                else:
                    code = row[0]
        return {"code": code}

    def regenerate_invite(self, customer_id: int) -> dict:
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM invite_code WHERE customer_id=%s", (customer_id,))
                code = None
                for _ in range(5):
                    try:
                        cur.execute(
                            "INSERT INTO invite_code (customer_id, code) "
                            "VALUES (%s, %s) RETURNING code",
                            (customer_id, self._new_invite_code()))
                        code = cur.fetchone()[0]
                        break
                    except psycopg.errors.UniqueViolation:
                        continue
                else:
                    raise ApiProblem(codes.INTERNAL_ERROR)
            conn.commit()
        return {"code": code}

    def invite_summary(self, customer_id: int) -> dict:
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT code FROM invite_code WHERE customer_id=%s "
                    "ORDER BY invite_code_id DESC LIMIT 1", (customer_id,))
                row = cur.fetchone()
                if row is None:
                    conn.commit()
                code = row[0] if row else None
                cur.execute(
                    "SELECT count(*), "
                    "count(*) FILTER (WHERE status='recharged'), "
                    "coalesce(sum(points_awarded), 0) "
                    "FROM invite_friend WHERE inviter_customer_id=%s",
                    (customer_id,))
                invited, recharged, awarded = cur.fetchone()
        if code is None:
            return self.get_or_create_invite(customer_id) | {
                "invited_count": invited, "recharged_count": recharged,
                "awarded_points": awarded}
        return {"code": code, "invited_count": invited,
                "recharged_count": recharged, "awarded_points": awarded}

    def list_invite_friends(self, customer_id: int, *,
                            limit: int = 50) -> list[dict]:
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT friend_email, status, points_awarded, created_at
                       FROM invite_friend WHERE inviter_customer_id=%s
                       ORDER BY created_at DESC LIMIT %s""",
                    (customer_id, limit))
                rows = cur.fetchall()
        return [{"friend_email": r[0], "status": r[1], "points_awarded": r[2],
                 "created_at": r[3].isoformat() if r[3] else ""}
                for r in rows]
