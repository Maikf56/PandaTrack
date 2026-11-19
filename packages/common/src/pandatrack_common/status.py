"""服务端标准状态字典（12 态，服务端权威；04 §7.1 / 02 §5.3）。

- 状态映射只接受已登记的标准状态（02 §5.3 第 5 条）；
- 未知原文状态保留在 raw_status，映射失败按 parse_failed / quality_gate_rejected 处理；
- 前端只显示白话文案，标签字典由 GET /api/v1/status-dict 提供（04 §426）。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StandardStatus:
    """标准状态：英文 key 稳定 + 中文白话标签 + 是否终态。"""

    key: str
    label_zh: str
    terminal: bool


# 12 态：11 个具名标签（04 §7.1）+ 其他状态
DELIVERED = StandardStatus("delivered", "已签收", terminal=True)
IN_TRANSIT = StandardStatus("in_transit", "运输中", terminal=False)
OUT_FOR_DELIVERY = StandardStatus("out_for_delivery", "派送中", terminal=False)
AVAILABLE_FOR_PICKUP = StandardStatus("available_for_pickup", "到达待取", terminal=False)
ACCEPTED = StandardStatus("accepted", "已揽收", terminal=False)
LABEL_CREATED = StandardStatus("label_created", "已下单", terminal=False)
NOT_FOUND = StandardStatus("not_found", "未找到", terminal=True)
EXCEPTION = StandardStatus("exception", "异常", terminal=False)
POSTAGE_DUE = StandardStatus("postage_due", "邮资未付", terminal=False)
DELIVERY_ATTEMPTED = StandardStatus("delivery_attempted", "投递失败", terminal=False)
RETURNED = StandardStatus("returned", "退回", terminal=True)
OTHER = StandardStatus("other", "其他状态", terminal=False)

ALL_STATUSES: dict[str, StandardStatus] = {
    s.key: s
    for s in (
        DELIVERED, IN_TRANSIT, OUT_FOR_DELIVERY, AVAILABLE_FOR_PICKUP,
        ACCEPTED, LABEL_CREATED, NOT_FOUND, EXCEPTION, POSTAGE_DUE,
        DELIVERY_ATTEMPTED, RETURNED, OTHER,
    )
}

TERMINAL_STATUSES = frozenset(k for k, s in ALL_STATUSES.items() if s.terminal)

# 客户批次进度状态（04 §12.2 用例 9：总量/批次/已完成/处理中/暂未获取/服务暂停）
BATCH_ITEM_STATES = ("pending", "processing", "done", "deferred", "suspended")


def is_registered(key: str) -> bool:
    """映射只接受已登记状态；未登记返回 False（调用方按 parse_failed 处理）。"""
    return key in ALL_STATUSES


def label_zh(key: str) -> str:
    s = ALL_STATUSES.get(key)
    return s.label_zh if s else OTHER.label_zh
