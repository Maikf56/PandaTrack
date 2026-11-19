-- B3: projection_event 变更通知（SSE 真推送）。
-- AFTER INSERT 触发 pg_notify，BFF 的 LISTEN 常驻连接收到后即时扇出给
-- 订阅客户（09 §3.1 触发式呈现；轮询仅作降级兜底）。
-- 载荷只含定位信息（event_id/operation_id/customer_id），不含业务内容——
-- 事件正文始终由 BFF 按租户权限从 projection_event 读出（不通过
-- NOTIFY 泄露，NOTIFY 载荷对同库所有会话可见）。
BEGIN;

CREATE OR REPLACE FUNCTION notify_projection_event() RETURNS trigger AS $$
DECLARE payload TEXT;
BEGIN
    SELECT json_build_object(
        'event_id',     NEW.event_id,
        'operation_id', NEW.operation_id,
        'customer_id',  so.customer_id
    )::text
    INTO payload
    FROM submission_operation so
    WHERE so.operation_id = NEW.operation_id;
    PERFORM pg_notify('pandatrack_projection', COALESCE(payload, '{}'));
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_projection_event_notify ON projection_event;

CREATE TRIGGER trg_projection_event_notify
AFTER INSERT ON projection_event
FOR EACH ROW EXECUTE FUNCTION notify_projection_event();

COMMIT;
