-- b/0007 邀请好友脚手架（P15）。
-- 奖励结算依赖开放注册；注册开放前表只记录邀请码与好友占位（status=pending）。
CREATE TABLE IF NOT EXISTS invite_code (
    invite_code_id BIGSERIAL PRIMARY KEY,
    customer_id    BIGINT NOT NULL REFERENCES customer(customer_id),
    code           VARCHAR(16) NOT NULL UNIQUE,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_invite_code_customer ON invite_code(customer_id);

CREATE TABLE IF NOT EXISTS invite_friend (
    friend_id            BIGSERIAL PRIMARY KEY,
    inviter_customer_id  BIGINT NOT NULL REFERENCES customer(customer_id),
    friend_customer_id   BIGINT REFERENCES customer(customer_id),
    friend_email         VARCHAR(255) NOT NULL,
    status               VARCHAR(20) NOT NULL DEFAULT 'pending',
    points_awarded       INTEGER NOT NULL DEFAULT 0,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_invite_friend_inviter ON invite_friend(inviter_customer_id);
