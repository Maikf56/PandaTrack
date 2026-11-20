-- PandaTrack A 库迁移 0004：tracking_event.location 放宽到 VARCHAR(500)
-- （生产实测 USPS 事件地点文本可超 100 字符，导致整批事实落库失败 StringDataRightTruncation）

BEGIN;

ALTER TABLE tracking_event ALTER COLUMN location TYPE VARCHAR(500);

COMMIT;
