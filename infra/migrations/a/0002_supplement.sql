-- PandaTrack A 库补全迁移（E2：provider_health / fetch_attempt_log，05 §5.5）

BEGIN;

CREATE TABLE IF NOT EXISTS provider_health (
    provider_id          BIGSERIAL PRIMARY KEY,
    provider_code        VARCHAR(20) NOT NULL UNIQUE,
    enabled              BOOLEAN NOT NULL DEFAULT false,
    circuit_open         BOOLEAN NOT NULL DEFAULT false,
    consecutive_failures INT NOT NULL DEFAULT 0,
    cooldown_until       TIMESTAMPTZ,
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS fetch_attempt_log (
    attempt_id    BIGSERIAL PRIMARY KEY,
    job_id        BIGINT NOT NULL REFERENCES fetch_job(job_id),
    provider_code VARCHAR(20) NOT NULL,
    error_class   VARCHAR(30),
    quality_gates JSONB,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_fetch_attempt_log_job_id ON fetch_attempt_log (job_id);
CREATE INDEX IF NOT EXISTS idx_fetch_attempt_log_created_at ON fetch_attempt_log (created_at DESC);

COMMIT;
