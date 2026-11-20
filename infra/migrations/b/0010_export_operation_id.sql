-- b/0010 导出任务关联操作列补齐（P18 探针发现：b/0004 的 ALTER 在部分
-- 环境未生效，delete_batch 依赖该列）。幂等补齐。
ALTER TABLE export_job ADD COLUMN IF NOT EXISTS operation_id BIGINT
    REFERENCES submission_operation(operation_id);
