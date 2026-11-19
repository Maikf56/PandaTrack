-- b/0006: RBAC 角色收敛 + 登录防爆破表 + 轨迹翻译缓存
-- 1) RBAC（03 §2）：legacy 'admin' 归一化为 super_admin，并加 CHECK 约束
UPDATE admin_user SET role = 'super_admin' WHERE role = 'admin';
ALTER TABLE admin_user
    DROP CONSTRAINT IF EXISTS ck_admin_user_role;
ALTER TABLE admin_user
    ADD CONSTRAINT ck_admin_user_role
    CHECK (role IN ('super_admin', 'finance', 'provider_ops', 'support', 'readonly'));

-- 2) 登录防爆破（09 §5.1 速率保护）：持久化失败计数，重启不清零
CREATE TABLE IF NOT EXISTS auth_throttle (
    throttle_id  BIGSERIAL PRIMARY KEY,
    scope        VARCHAR(10)  NOT NULL,            -- customer / admin
    key          VARCHAR(255) NOT NULL,            -- ip|identifier 或 *|identifier
    fail_count   INT NOT NULL DEFAULT 0,
    locked_until TIMESTAMPTZ,
    last_fail_at TIMESTAMPTZ,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (scope, key)
);
CREATE INDEX IF NOT EXISTS idx_auth_throttle_locked
    ON auth_throttle (scope, key) WHERE locked_until IS NOT NULL;

-- 3) 轨迹翻译缓存：物流描述术语高度固定，按 (lang, digest) 复用，压成本
CREATE TABLE IF NOT EXISTS translation_cache (
    cache_id      BIGSERIAL PRIMARY KEY,
    lang          VARCHAR(10) NOT NULL,
    source_digest CHAR(64)    NOT NULL,
    source_text   TEXT        NOT NULL,
    translated    TEXT        NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (lang, source_digest)
);
