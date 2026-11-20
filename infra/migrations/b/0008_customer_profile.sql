-- b/0008 客户资料字段（P17）：名字/电话/备注。
-- NOT NULL DEFAULT '' 兼容存量行（自助注册客户本来就没有资料）；
-- 长度对齐 05 §5.4 口径：name/phone 有界，remark 自由文本。
ALTER TABLE customer ADD COLUMN IF NOT EXISTS name   VARCHAR(100) NOT NULL DEFAULT '';
ALTER TABLE customer ADD COLUMN IF NOT EXISTS phone  VARCHAR(30)  NOT NULL DEFAULT '';
ALTER TABLE customer ADD COLUMN IF NOT EXISTS remark TEXT        NOT NULL DEFAULT '';
