-- b/0005: billing_outbox 消费者重试列（P7-enqueue）。
-- attempts: 消费尝试计数；last_error: 最近一次失败类别（脱敏，≤60 字符）。
-- 放弃语义：attempts 达到 max 后再次失败 → processed=true + last_error 留痕，
-- 健康巡检按 last_error 非空的已处理行统计死信。
BEGIN;
COMMENT ON TABLE billing_outbox IS '计费受理 outbox：受理事务写入，消费者
（worker/billing/consumer.py）异步生成 A 库 FetchJob 后标记 processed';
ALTER TABLE billing_outbox
    ADD COLUMN IF NOT EXISTS attempts INT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS last_error VARCHAR(60);
CREATE INDEX IF NOT EXISTS idx_billing_outbox_pending
    ON billing_outbox (event_id) WHERE processed = false;
COMMIT;
