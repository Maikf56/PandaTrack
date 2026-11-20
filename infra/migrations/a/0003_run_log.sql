-- PandaTrack A 库迁移 0003：run_log（worker 运行日志，管理端"系统运行日志"数据源）

BEGIN;

CREATE TABLE IF NOT EXISTS run_log (
    run_log_id     BIGSERIAL PRIMARY KEY,
    worker_id      VARCHAR(50) NOT NULL DEFAULT 'worker-1',
    cycle          INT,
    level          VARCHAR(10) NOT NULL DEFAULT 'info',   -- info / warn / error
    kind           VARCHAR(30) NOT NULL DEFAULT 'cycle',  -- cycle / tick_error / canary_halt
    reclaimed      INT NOT NULL DEFAULT 0,
    claimed        INT NOT NULL DEFAULT 0,
    succeeded      INT NOT NULL DEFAULT 0,
    retried        INT NOT NULL DEFAULT 0,
    dead_lettered  INT NOT NULL DEFAULT 0,
    facts_written  INT NOT NULL DEFAULT 0,
    events_written INT NOT NULL DEFAULT 0,
    outbox_written INT NOT NULL DEFAULT 0,
    error_class    VARCHAR(30),
    summary        JSONB,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_run_log_created_at ON run_log (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_run_log_level ON run_log (level);

COMMIT;
