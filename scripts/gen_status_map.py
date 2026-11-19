"""从 USPS运输状态纯文本清单.md 生成静态状态映射数据 status_data.py。

分组 → 12 态映射（pandatrack_common.status 的 key）：
  未揽收               → label_created
  运输中               → in_transit
  派送中               → out_for_delivery
  派送异常(取消/退回)   → returned（组内含 delivery_attempted 精确覆盖）
  未付邮资             → postage_due
  已签收               → delivered

产物为纯数据模块（生产运行不依赖辅助资料目录）。
"""
from __future__ import annotations

import re
from pathlib import Path

GROUP_TO_STATUS = {
    "未揽收": "label_created",
    "运输中": "in_transit",
    "派送中": "out_for_delivery",
    "派送异常(取消/退回)": "returned",
    "未付邮资": "postage_due",
    "已签收": "delivered",
}

# 组内精确覆盖：某些文本按语义映射到更准确的 12 态
EXACT_OVERRIDES = {
    # 派送异常组中属投递尝试失败的文本
    "Undeliverable as Addressed": "delivery_attempted",
    "Delivery Attempted": "delivery_attempted",
    "Notice Left": "delivery_attempted",
    "Receptacle Blocked": "delivery_attempted",
    "No Access to Delivery Location": "delivery_attempted",
    "No Secure Location Available": "delivery_attempted",
    "Final notice e-mail sent": "delivery_attempted",
    "Second Notice for Customer": "delivery_attempted",
    "Held at Post Office? At Customer Request": "available_for_pickup",
    "Available for Pickup": "available_for_pickup",
    "Held at Post Office": "available_for_pickup",
    "Out for Delivery": "out_for_delivery",
    "Delivered Front Desk/Reception": "delivered",
    "Delivered to Mailbox": "delivered",
    "Delivered": "delivered",
    # 运输中组中的已揽收语义
    "USPS Pickup": "accepted",
    "Picked Up by Shipping Partner": "accepted",
    "Accepted at USPS Origin Facility": "accepted",
    "Accepted at USPS Destination Facility": "accepted",
}


def gen(src: Path, dst: Path) -> int:
    lines = src.read_text(encoding="utf-8").splitlines()
    mapping: dict[str, tuple[str, str]] = {}  # english -> (status_key, label_zh)
    conflicts: list[str] = []
    current_group = ""
    for raw in lines:
        s = raw.strip()
        if not s:
            continue
        if "|" not in s:
            current_group = s.rstrip("：:")
            continue
        eng, zh = s.split("|", 1)
        eng, zh = eng.strip(), zh.strip()
        if not eng:
            continue
        status = EXACT_OVERRIDES.get(eng) or GROUP_TO_STATUS.get(current_group)
        if status is None:
            conflicts.append(f"未识别分组 {current_group!r}: {eng}")
            continue
        if eng in mapping and mapping[eng] != (status, zh):
            # 同英文不同组/译文：保留首次，记录冲突供人工核查
            conflicts.append(f"重复 {eng!r}: {mapping[eng]} vs {(status, zh)}")
            continue
        mapping[eng] = (status, zh)

    out = ['"""自动生成：USPS 英文状态文本 → 12 态映射（源: USPS运输状态纯文本清单.md）。"""', "",
           f"MAPPING: dict[str, tuple[str, str]] = {{"]
    for eng in sorted(mapping):
        st, zh = mapping[eng]
        out.append(f"    {eng!r}: ({st!r}, {zh!r}),")
    out.append("}")
    dst.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"生成 {len(mapping)} 条映射 → {dst}")
    if conflicts:
        print(f"冲突 {len(conflicts)} 条：")
        for c in conflicts[:10]:
            print("  -", c)
    return len(mapping)


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    src = root / "开发文档" / "02_辅助资料" / "USPS运输状态纯文本清单.md"
    dst = root / "apps" / "worker" / "src" / "worker" / "provider" / "usps_web" / "status_data.py"
    dst.parent.mkdir(parents=True, exist_ok=True)
    gen(src, dst)
