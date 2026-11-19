"""哈希与指纹工具（A/B 摆渡幂等依赖：event fingerprint、payload digest）。"""
from __future__ import annotations

import hashlib
import json
from typing import Any


def sha256_hex(data: bytes | str) -> str:
    """SHA-256 十六进制摘要（payload_digest / request_fingerprint）。"""
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def canonical_json(value: Any) -> str:
    """稳定序列化：键排序、紧凑分隔符，保证跨库 digest 一致。"""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def payload_digest(payload: Any) -> str:
    """outbox 载荷摘要（05 a_outbox.payload_digest / billing_outbox）。"""
    return sha256_hex(canonical_json(payload))


def event_fingerprint(*parts: Any) -> str:
    """事件指纹（tracking_event 去重键）：按约定顺序拼接后取 SHA-256。"""
    return sha256_hex("\x1f".join(str(p) for p in parts))


def request_fingerprint(customer_id: int, endpoint: str, payload: Any) -> str:
    """幂等请求指纹（idempotency_record）：客户+端点+规范化载荷。"""
    return payload_digest({"customer_id": customer_id, "endpoint": endpoint, "payload": payload})
