"""元数据路由：状态字典（04 §7.1/§426 前端标签权威源）。"""
from __future__ import annotations

from fastapi import APIRouter

from pandatrack_common import status as status_dict

router = APIRouter(prefix="/api/v1", tags=["meta"])


@router.get("/status-dict")
def status_dictionary():
    return {
        "statuses": [
            {"key": s.key, "label_zh": s.label_zh, "terminal": s.terminal}
            for s in status_dict.ALL_STATUSES.values()
        ],
        "item_state_enum": list(status_dict.BATCH_ITEM_STATES),
    }
