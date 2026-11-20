-- b/0009 组备注（P18 对标竞品组卡「备注 ✏️」）：自由文本，竞品式组级备注。
ALTER TABLE target_group ADD COLUMN IF NOT EXISTS remark TEXT NOT NULL DEFAULT '';
