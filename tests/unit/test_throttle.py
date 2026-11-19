"""登录防爆破算法单测（09 §5.1）：纯函数，不碰库。"""
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[2] / "apps" / "api" / "src"),
                str(Path(__file__).resolve().parents[2] / "packages" / "common" / "src")]

from api.throttle import (  # noqa: E402
    BASE_LOCK_SECONDS, MAX_ATTEMPTS, MAX_LOCK_SECONDS, client_ip,
    next_lock_seconds, throttle_keys,
)


class _FakeRequest:
    def __init__(self, headers=None, host="203.0.113.9"):
        self.headers = headers or {}
        self.client = type("C", (), {"host": host})()


def test_no_lock_below_threshold():
    for n in range(MAX_ATTEMPTS):
        assert next_lock_seconds(n) == 0, n


def test_lock_at_threshold_and_exponential():
    assert next_lock_seconds(MAX_ATTEMPTS) == BASE_LOCK_SECONDS          # 30s
    assert next_lock_seconds(MAX_ATTEMPTS + 1) == BASE_LOCK_SECONDS * 2  # 60s
    assert next_lock_seconds(MAX_ATTEMPTS + 2) == BASE_LOCK_SECONDS * 4  # 120s


def test_lock_capped_at_one_hour():
    assert next_lock_seconds(MAX_ATTEMPTS + 20) == MAX_LOCK_SECONDS
    assert MAX_LOCK_SECONDS == 3600


def test_two_level_keys_single_source_and_cross_source():
    keys = throttle_keys("1.2.3.4", "user@example.com")
    assert keys[0] == "1.2.3.4|user@example.com"  # 单源爆破
    assert keys[1] == "*|user@example.com"        # 跨源撞库


def test_client_ip_prefers_forwarded_for():
    req = _FakeRequest({"x-forwarded-for": "198.51.100.7, 10.0.0.1"})
    assert client_ip(req) == "198.51.100.7"


def test_client_ip_fallback_direct():
    assert client_ip(_FakeRequest({}, host="192.0.2.5")) == "192.0.2.5"
    assert client_ip(_FakeRequest({}, host=None)) == "unknown"
