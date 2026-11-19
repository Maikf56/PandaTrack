-- PandaTrack B 库初始迁移（客户/账务权威，模块 05 §5.2 ER 图 + §5.4 字段级 Schema）
-- 约定：
--   * TIMESTAMP 统一 TIMESTAMPTZ（UTC 存储），工程细节具体化；
--   * 对外业务表（customer/submission_operation/customer_tracking/points_ledger）加 public_id UUID（11 号文档裁定）；
--   * customer.tenant_id 的 FK 在 0002 建 tenant 后补齐（本文件只留列，避免跨文件依赖）。

BEGIN;

CREATE TABLE IF NOT EXISTS customer (
    customer_id   BIGSERIAL PRIMARY KEY,
    public_id     UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    email         VARCHAR(100) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    status        VARCHAR(20) NOT NULL DEFAULT 'active',
    role          VARCHAR(20) NOT NULL DEFAULT 'member',
    tenant_id     BIGINT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_customer_tenant_id ON customer (tenant_id);

CREATE TABLE IF NOT EXISTS wallet (
    wallet_id         BIGSERIAL PRIMARY KEY,
    customer_id       BIGINT NOT NULL UNIQUE REFERENCES customer(customer_id),
    balance           INT NOT NULL DEFAULT 0,
    frozen            INT NOT NULL DEFAULT 0,
    lifetime_consumed INT NOT NULL DEFAULT 0,
    version           INT NOT NULL DEFAULT 0,
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS points_ledger (
    ledger_id      BIGSERIAL PRIMARY KEY,
    public_id      UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    customer_id    BIGINT NOT NULL REFERENCES customer(customer_id),
    ledger_type    VARCHAR(20) NOT NULL,
    points_change  INT NOT NULL,
    reference_type VARCHAR(20),
    reference_id   BIGINT,
    description    TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_points_ledger_customer_id ON points_ledger (customer_id);
CREATE INDEX IF NOT EXISTS idx_points_ledger_created_at ON points_ledger (created_at DESC);
-- 冲正只记一次（06 双扣防护；05 §5.5 补充唯一键）
CREATE UNIQUE INDEX IF NOT EXISTS uq_ledger_refund_once
    ON points_ledger (reference_type, reference_id, ledger_type)
    WHERE ledger_type = 'refund';

CREATE TABLE IF NOT EXISTS submission_operation (
    operation_id   BIGSERIAL PRIMARY KEY,
    public_id      UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    customer_id    BIGINT NOT NULL REFERENCES customer(customer_id),
    state          VARCHAR(20) NOT NULL DEFAULT 'accepted',
    total_count    INT NOT NULL,
    valid_count    INT NOT NULL,
    invalid_count  INT NOT NULL DEFAULT 0,
    points_charged INT NOT NULL DEFAULT 0,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_submission_operation_customer_id ON submission_operation (customer_id);
CREATE INDEX IF NOT EXISTS idx_submission_operation_created_at ON submission_operation (created_at DESC);

CREATE TABLE IF NOT EXISTS charge_reservation (
    reservation_id  BIGSERIAL PRIMARY KEY,
    operation_id    BIGINT NOT NULL REFERENCES submission_operation(operation_id),
    points_reserved INT NOT NULL,
    status          VARCHAR(20) NOT NULL DEFAULT 'reserved',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    released_at     TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_charge_reservation_operation_id ON charge_reservation (operation_id);
CREATE INDEX IF NOT EXISTS idx_charge_reservation_status ON charge_reservation (status);

CREATE TABLE IF NOT EXISTS submission_batch (
    batch_id     BIGSERIAL PRIMARY KEY,
    operation_id BIGINT NOT NULL REFERENCES submission_operation(operation_id),
    batch_seq    INT NOT NULL,
    item_count   INT NOT NULL,
    state        VARCHAR(20) NOT NULL DEFAULT 'pending',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_submission_batch_seq UNIQUE (operation_id, batch_seq)
);
CREATE INDEX IF NOT EXISTS idx_submission_batch_state ON submission_batch (state);

CREATE TABLE IF NOT EXISTS submission_item (
    item_id           BIGSERIAL PRIMARY KEY,
    batch_id          BIGINT NOT NULL REFERENCES submission_batch(batch_id),
    item_seq          INT NOT NULL,
    raw_number        VARCHAR(100) NOT NULL,
    normalized_number VARCHAR(50),
    is_valid          BOOLEAN NOT NULL DEFAULT true,
    invalid_reason    VARCHAR(50),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_submission_item_seq UNIQUE (batch_id, item_seq)
);
CREATE INDEX IF NOT EXISTS idx_submission_item_normalized_number ON submission_item (normalized_number);

CREATE TABLE IF NOT EXISTS customer_tracking (
    customer_tracking_id BIGSERIAL PRIMARY KEY,
    public_id            UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    customer_id          BIGINT NOT NULL REFERENCES customer(customer_id),
    normalized_number    VARCHAR(50) NOT NULL,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_customer_tracking_number UNIQUE (customer_id, normalized_number)
);
CREATE INDEX IF NOT EXISTS idx_customer_tracking_customer_id ON customer_tracking (customer_id);

CREATE TABLE IF NOT EXISTS tracking_projection (
    projection_id        BIGSERIAL PRIMARY KEY,
    customer_tracking_id BIGINT NOT NULL UNIQUE REFERENCES customer_tracking(customer_tracking_id),
    normalized_number    VARCHAR(50) NOT NULL,
    status               VARCHAR(30),
    events               JSONB,
    projected_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS operation_snapshot (
    snapshot_id  BIGSERIAL PRIMARY KEY,
    operation_id BIGINT NOT NULL REFERENCES submission_operation(operation_id),
    snapshot     JSONB NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS projection_event (
    event_id          BIGSERIAL PRIMARY KEY,
    operation_id      BIGINT NOT NULL REFERENCES submission_operation(operation_id),
    aggregate_version INT NOT NULL,
    payload           JSONB NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_projection_event_version UNIQUE (operation_id, aggregate_version)
);

CREATE TABLE IF NOT EXISTS idempotency_record (
    idem_id             BIGSERIAL PRIMARY KEY,
    customer_id         BIGINT NOT NULL REFERENCES customer(customer_id),
    endpoint            VARCHAR(50) NOT NULL,
    client_request_id   VARCHAR(50) NOT NULL,
    request_fingerprint VARCHAR(64) NOT NULL,
    response_snapshot   JSONB,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_idempotency_key UNIQUE (customer_id, endpoint, client_request_id)
);

CREATE TABLE IF NOT EXISTS billing_outbox (
    event_id          BIGSERIAL PRIMARY KEY,
    aggregate_id      BIGINT NOT NULL,
    aggregate_type    VARCHAR(30) NOT NULL,
    aggregate_version INT NOT NULL,
    payload           JSONB NOT NULL,
    payload_digest    VARCHAR(64) NOT NULL,
    processed         BOOLEAN NOT NULL DEFAULT false,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_billing_outbox_aggregate UNIQUE (aggregate_id, aggregate_type, aggregate_version)
);
CREATE INDEX IF NOT EXISTS idx_billing_outbox_processed ON billing_outbox (processed);

CREATE TABLE IF NOT EXISTS redemption_code (
    code_id     BIGSERIAL PRIMARY KEY,
    code        VARCHAR(20) NOT NULL UNIQUE,
    points      INT NOT NULL,
    status      VARCHAR(20) NOT NULL DEFAULT 'active',
    redeemed_by BIGINT REFERENCES customer(customer_id),
    redeemed_at TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMIT;
