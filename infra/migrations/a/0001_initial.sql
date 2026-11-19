-- PandaTrack A 库初始迁移（采集事实权威，模块 05 §5.3 + A 库 ER 图）
-- 约定：
--   * 方案 05 字面 TIMESTAMP 统一以 TIMESTAMPTZ 落地（UTC 存储），工程细节具体化，不改变业务语义；
--   * tracking 含 C1 补齐字段（next_sync_at/version/last_success_at）与 public_id；
--   * fetch_job 含 retry_at，single-flight 索引覆盖全部活跃态（C2 修正，见 11 号文档）；
--   * 合成结果 simulated=true 仅限隔离测试写入，生产守卫在应用层（02 §4.3）。

BEGIN;

CREATE TABLE IF NOT EXISTS tracking (
    tracking_id       BIGSERIAL PRIMARY KEY,
    public_id         UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    normalized_number VARCHAR(50) NOT NULL,
    carrier           VARCHAR(20) NOT NULL DEFAULT 'usps',
    next_sync_at      TIMESTAMPTZ,
    version           INT NOT NULL DEFAULT 0,
    last_success_at   TIMESTAMPTZ,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_tracking_number UNIQUE (normalized_number, carrier)
);
CREATE INDEX IF NOT EXISTS idx_tracking_updated_at ON tracking (updated_at);
CREATE INDEX IF NOT EXISTS idx_tracking_next_sync ON tracking (next_sync_at);

CREATE TABLE IF NOT EXISTS tracking_fact (
    fact_id       BIGSERIAL PRIMARY KEY,
    tracking_id   BIGINT NOT NULL REFERENCES tracking(tracking_id),
    source        VARCHAR(20) NOT NULL DEFAULT 'usps_web',
    simulated     BOOLEAN NOT NULL DEFAULT false,
    raw_status    TEXT,
    status        VARCHAR(30),
    quality_gates JSONB,
    collected_at  TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_tracking_fact_tracking_id ON tracking_fact (tracking_id);
CREATE INDEX IF NOT EXISTS idx_tracking_fact_collected_at ON tracking_fact (collected_at DESC);

CREATE TABLE IF NOT EXISTS tracking_event (
    event_id          BIGSERIAL PRIMARY KEY,
    tracking_id       BIGINT NOT NULL REFERENCES tracking(tracking_id),
    event_fingerprint VARCHAR(64) NOT NULL,
    occurred_at       TIMESTAMPTZ,
    status            VARCHAR(30),
    description_raw   TEXT,
    description_zh    TEXT,
    location          VARCHAR(100),
    event_code        VARCHAR(20),
    time_confidence   VARCHAR(10),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_tracking_event_fingerprint UNIQUE (tracking_id, event_fingerprint),
    CONSTRAINT ck_event_time_confidence CHECK (time_confidence IN ('exact', 'low'))
);
CREATE INDEX IF NOT EXISTS idx_tracking_event_occurred_at ON tracking_event (occurred_at DESC);

CREATE TABLE IF NOT EXISTS fetch_job (
    job_id       BIGSERIAL PRIMARY KEY,
    tracking_id  BIGINT NOT NULL REFERENCES tracking(tracking_id),
    state        VARCHAR(30) NOT NULL DEFAULT 'pending',
    attempt      INT NOT NULL DEFAULT 0,
    max_attempts INT NOT NULL DEFAULT 3,
    error_class  VARCHAR(30),
    queue        VARCHAR(20) NOT NULL DEFAULT 'Q_SCHEDULED',
    worker_id    VARCHAR(50),
    lease_until  TIMESTAMPTZ,
    retry_at     TIMESTAMPTZ,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at  TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_fetch_job_state ON fetch_job (state);
CREATE INDEX IF NOT EXISTS idx_fetch_job_lease_until ON fetch_job (lease_until);
CREATE INDEX IF NOT EXISTS idx_fetch_job_retry_at ON fetch_job (retry_at);
-- single-flight（C2 修正）：同一 tracking 同时只允许一个活跃 job；终态不占唯一约束。
-- 活跃态枚举须与 02 §3.1 / 07 §3.1 状态机一致。
CREATE UNIQUE INDEX IF NOT EXISTS uq_fetch_job_single_flight
    ON fetch_job (tracking_id)
    WHERE state IN ('pending', 'claimed', 'running',
                    'waiting_for_session', 'retry_scheduled', 'collecting_response');

CREATE TABLE IF NOT EXISTS provider_attempt (
    attempt_id    BIGSERIAL PRIMARY KEY,
    job_id        BIGINT NOT NULL REFERENCES fetch_job(job_id),
    provider_code VARCHAR(20) NOT NULL,
    error_class   VARCHAR(30),
    quality_gates JSONB,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_provider_attempt_job_id ON provider_attempt (job_id);
CREATE INDEX IF NOT EXISTS idx_provider_attempt_created_at ON provider_attempt (created_at DESC);

CREATE TABLE IF NOT EXISTS parser_evidence_ref (
    evidence_id   BIGSERIAL PRIMARY KEY,
    attempt_id    BIGINT NOT NULL REFERENCES provider_attempt(attempt_id),
    evidence_type VARCHAR(30) NOT NULL,
    content       TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_parser_evidence_attempt ON parser_evidence_ref (attempt_id);

CREATE TABLE IF NOT EXISTS a_outbox (
    event_id          BIGSERIAL PRIMARY KEY,
    aggregate_id      BIGINT NOT NULL,
    aggregate_type    VARCHAR(30) NOT NULL,
    aggregate_version INT NOT NULL,
    payload           JSONB NOT NULL,
    payload_digest    VARCHAR(64) NOT NULL,
    processed         BOOLEAN NOT NULL DEFAULT false,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_a_outbox_aggregate UNIQUE (aggregate_id, aggregate_type, aggregate_version)
);
CREATE INDEX IF NOT EXISTS idx_a_outbox_processed ON a_outbox (processed);

COMMIT;
