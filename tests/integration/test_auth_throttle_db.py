"""登录防爆破集成测试（B 库真实 PG，09 §5.1）。

需环境变量 PT_DB_B_URL；未配置则 skip。
覆盖：auth_throttle 失败计数窗口重置、指数锁定、成功清零、两级 key。
"""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import pytest

sys.path[:0] = [str(Path(__file__).resolve().parents[2] / "apps" / "api" / "src"),
                str(Path(__file__).resolve().parents[2] / "packages" / "common" / "src")]

DB_URL = os.environ.get("PT_DB_B_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="未设 PT_DB_B_URL，跳过 DB 集成测试")

psycopg = pytest.importorskip("psycopg", reason="未安装 psycopg3，跳过 DB 集成测试")

from api.data import BRepository  # noqa: E402
from api.throttle import (BASE_LOCK_SECONDS, MAX_ATTEMPTS, WINDOW_SECONDS,  # noqa: E402
                          locked_retry_after, next_lock_seconds)

SCOPE = "customer"


def _cleanup() -> None:
    with psycopg.connect(DB_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM auth_throttle WHERE key LIKE %s",
                        (f"{uuid.uuid4().hex[:8]}%",))
            conn.commit()


def test_fail_count_window_reset_and_lock_and_reset():
    _cleanup()
    tag = uuid.uuid4().hex[:8]
    key = f"{tag}|user@example.com"
    repo = BRepository(DB_URL)
    try:
        # 0 失败：未锁
        assert locked_retry_after(repo.login_throttle_locked_until(SCOPE, key)) is None
        # 1..4 次失败：计数递增但不锁
        for n in range(1, MAX_ATTEMPTS):
            fc = repo.login_throttle_record_fail(SCOPE, key,
                                                 window_seconds=WINDOW_SECONDS,
                                                 max_attempts=MAX_ATTEMPTS)
            assert fc == n
            assert locked_retry_after(repo.login_throttle_locked_until(SCOPE, key)) is None
        # 第 5 次：锁定
        fc = repo.login_throttle_record_fail(SCOPE, key,
                                             window_seconds=WINDOW_SECONDS,
                                             max_attempts=MAX_ATTEMPTS)
        assert fc == MAX_ATTEMPTS
        retry = locked_retry_after(repo.login_throttle_locked_until(SCOPE, key))
        assert retry is not None and 1 <= retry <= BASE_LOCK_SECONDS
        # 成功登录：清零
        repo.login_throttle_reset(SCOPE, key)
        assert locked_retry_after(repo.login_throttle_locked_until(SCOPE, key)) is None
        # 清零后失败计数从头开始
        fc = repo.login_throttle_record_fail(SCOPE, key,
                                             window_seconds=WINDOW_SECONDS,
                                             max_attempts=MAX_ATTEMPTS)
        assert fc == 1
    finally:
        with psycopg.connect(DB_URL) as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM auth_throttle WHERE key=%s", (key,))
                conn.commit()


def test_window_expired_resets_counter():
    """把 last_fail_at 拨回窗口外，下一次失败应重置为 1 而不是累加。"""
    tag = uuid.uuid4().hex[:8]
    key = f"{tag}|stale@example.com"
    repo = BRepository(DB_URL)
    try:
        for _ in range(3):
            repo.login_throttle_record_fail(SCOPE, key,
                                            window_seconds=WINDOW_SECONDS,
                                            max_attempts=MAX_ATTEMPTS)
        with psycopg.connect(DB_URL) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE auth_throttle
                       SET last_fail_at = now() - make_interval(secs => %s)
                       WHERE scope=%s AND key=%s""",
                    (WINDOW_SECONDS + 60, SCOPE, key))
                conn.commit()
        fc = repo.login_throttle_record_fail(SCOPE, key,
                                             window_seconds=WINDOW_SECONDS,
                                             max_attempts=MAX_ATTEMPTS)
        assert fc == 1  # 窗口外 → 重置
        assert next_lock_seconds(fc) == 0
    finally:
        with psycopg.connect(DB_URL) as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM auth_throttle WHERE key=%s", (key,))
                conn.commit()
