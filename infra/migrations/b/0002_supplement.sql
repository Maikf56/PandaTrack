-- PandaTrack B 库补全迁移（E2：05 §5.5 补全表，P0 一次性补齐）

BEGIN;

CREATE TABLE IF NOT EXISTS tenant (
    tenant_id  BIGSERIAL PRIMARY KEY,
    public_id  UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    name       VARCHAR(100) NOT NULL,
    status     VARCHAR(20) NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 补齐 customer.tenant_id 外键（0001 预留列）
ALTER TABLE customer
    ADD CONSTRAINT fk_customer_tenant FOREIGN KEY (tenant_id) REFERENCES tenant(tenant_id);

CREATE TABLE IF NOT EXISTS seat (
    seat_id     BIGSERIAL PRIMARY KEY,
    tenant_id   BIGINT NOT NULL REFERENCES tenant(tenant_id),
    customer_id BIGINT REFERENCES customer(customer_id),
    role        VARCHAR(20) NOT NULL DEFAULT 'member',
    status      VARCHAR(20) NOT NULL DEFAULT 'active',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_seat_tenant_id ON seat (tenant_id);

CREATE TABLE IF NOT EXISTS admin_user (
    admin_id      BIGSERIAL PRIMARY KEY,
    public_id     UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    username      VARCHAR(50) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    role          VARCHAR(20) NOT NULL DEFAULT 'admin',
    status        VARCHAR(20) NOT NULL DEFAULT 'active',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS target_group (
    group_id    BIGSERIAL PRIMARY KEY,
    public_id   UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    customer_id BIGINT NOT NULL REFERENCES customer(customer_id),
    name        VARCHAR(50) NOT NULL,
    is_default  BOOLEAN NOT NULL DEFAULT false,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_target_group_customer_id ON target_group (customer_id);

CREATE TABLE IF NOT EXISTS import_job (
    import_job_id BIGSERIAL PRIMARY KEY,
    public_id     UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    customer_id   BIGINT NOT NULL REFERENCES customer(customer_id),
    status        VARCHAR(20) NOT NULL DEFAULT 'pending',
    total         INT NOT NULL DEFAULT 0,
    done          INT NOT NULL DEFAULT 0,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_import_job_customer_id ON import_job (customer_id);

CREATE TABLE IF NOT EXISTS export_job (
    export_job_id BIGSERIAL PRIMARY KEY,
    public_id     UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    customer_id   BIGINT NOT NULL REFERENCES customer(customer_id),
    status        VARCHAR(20) NOT NULL DEFAULT 'pending',
    file_ref      VARCHAR(200),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_export_job_customer_id ON export_job (customer_id);

CREATE TABLE IF NOT EXISTS audit_log (
    audit_id   BIGSERIAL PRIMARY KEY,
    actor_id   BIGINT,
    actor_role VARCHAR(20) NOT NULL,
    action     VARCHAR(50) NOT NULL,
    target     VARCHAR(100),
    detail     JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_audit_log_created_at ON audit_log (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_log_actor ON audit_log (actor_id, actor_role);

CREATE TABLE IF NOT EXISTS session (
    session_id  BIGSERIAL PRIMARY KEY,
    customer_id BIGINT REFERENCES customer(customer_id),
    admin_id    BIGINT REFERENCES admin_user(admin_id),
    token_hash  VARCHAR(64) NOT NULL UNIQUE,
    expires_at  TIMESTAMPTZ NOT NULL,
    revoked     BOOLEAN NOT NULL DEFAULT false,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_session_subject CHECK (customer_id IS NOT NULL OR admin_id IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS idx_session_customer_id ON session (customer_id);

CREATE TABLE IF NOT EXISTS refresh_budget (
    budget_id  BIGSERIAL PRIMARY KEY,
    scope      VARCHAR(20) NOT NULL,
    day        DATE NOT NULL,
    used       INT NOT NULL DEFAULT 0,
    budget_max INT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_refresh_budget_scope_day UNIQUE (scope, day)
);

CREATE TABLE IF NOT EXISTS billing_charge_window (
    window_id         BIGSERIAL PRIMARY KEY,
    customer_id       BIGINT NOT NULL REFERENCES customer(customer_id),
    normalized_number VARCHAR(50) NOT NULL,
    charged_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at        TIMESTAMPTZ NOT NULL,
    active            BOOLEAN NOT NULL DEFAULT true
);
-- 滚动 30×24h 免扣窗口唯一约束（06；active 由过期清理任务置 false，
-- 谓词索引不可用 now()，故以 active 列实现滚动窗口语义）
CREATE UNIQUE INDEX IF NOT EXISTS uq_charge_window_subject
    ON billing_charge_window (customer_id, normalized_number)
    WHERE active = true;
CREATE INDEX IF NOT EXISTS idx_charge_window_expires ON billing_charge_window (expires_at);

COMMIT;
