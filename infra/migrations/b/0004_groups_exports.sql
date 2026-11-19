-- B4: 次要页面（组与批次/导入/导出/设置）所需扩列（04 §5.8-5.12）。
BEGIN;

-- 组：归档与更新时间。
ALTER TABLE target_group
    ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS updated_at  TIMESTAMPTZ NOT NULL DEFAULT now();

-- 单号归属组（默认组由提交流程写入；删除组只清组织关系，不动事实/账务）。
ALTER TABLE customer_tracking
    ADD COLUMN IF NOT EXISTS group_id BIGINT REFERENCES target_group(group_id);
CREATE INDEX IF NOT EXISTS idx_customer_tracking_group
    ON customer_tracking (group_id);

-- 操作（批次）归属组：每次提交自动归入默认组（04 §5.8）。
ALTER TABLE submission_operation
    ADD COLUMN IF NOT EXISTS group_id BIGINT REFERENCES target_group(group_id);
CREATE INDEX IF NOT EXISTS idx_submission_operation_group
    ON submission_operation (group_id);

-- 导入任务：方案口径展示列（文件名/清洗-入队-完成进度/成功失败跳过重复/
-- 失败明细/关联操作）。
ALTER TABLE import_job
    ADD COLUMN IF NOT EXISTS file_name        VARCHAR(200),
    ADD COLUMN IF NOT EXISTS enqueued         INT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS success_count    INT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS failed_count     INT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS skipped_count    INT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS duplicate_count  INT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS failed_detail    JSONB,
    ADD COLUMN IF NOT EXISTS operation_id     BIGINT
        REFERENCES submission_operation(operation_id);

-- 导出任务：范围/格式/文件名/行数/短期链接过期/失败原因。
ALTER TABLE export_job
    ADD COLUMN IF NOT EXISTS scope        VARCHAR(20) NOT NULL DEFAULT 'all',
    ADD COLUMN IF NOT EXISTS scope_ref    VARCHAR(100),
    ADD COLUMN IF NOT EXISTS format       VARCHAR(10) NOT NULL DEFAULT 'csv',
    ADD COLUMN IF NOT EXISTS file_name    VARCHAR(200),
    ADD COLUMN IF NOT EXISTS row_count    INT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS expires_at   TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS error_detail TEXT,
    ADD COLUMN IF NOT EXISTS token_hash   VARCHAR(64);

-- 设置页：客户显示偏好（时区/默认排序，04 §5.12）。
ALTER TABLE customer
    ADD COLUMN IF NOT EXISTS preferences JSONB NOT NULL DEFAULT '{}';

COMMIT;
