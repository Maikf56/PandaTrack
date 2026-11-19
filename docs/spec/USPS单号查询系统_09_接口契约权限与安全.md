# USPS 单号查询系统 09：接口契约、权限与安全

## 1. 模块目标

统一定义 BFF、客户前端、管理员后端、A/B 摆渡和 SSE 的接口语义、鉴权、租户隔离、错误码、安全响应和审计要求，防止模块各自设计出不兼容接口或越权数据路径。

## 2. 功能范围

- HTTP API 和 SSE 契约、版本策略、错误码和幂等规则。
- 客户/管理员认证、角色、tenant scope、CSRF、会话和速率保护。
- 输入校验、输出投影白名单、日志脱敏、审计和前端产物黑名单。
- BFF 与 A 库隔离、sync-agent 专用身份和 outbox 数据传递约束。

不包含：具体业务页面、Cleaner 算法、数据库完整 schema、Provider 页面解析和限流策略；这些分别归属 02–07。

## 3. 关键设计

### 3.1 客户 API 基线

- `POST /api/v1/submissions`：一次完成清洗、计费、入队和原子受理；返回 202、operation ID、实际扣费和分类汇总，幂等键为客户/端点/client_request_id。
- `POST /api/v1/submissions/estimate`：提交前预估（G2 增补，见 §5.2.1），幂等不入账、不构成报价。
- `GET /api/v1/operations/{id}`：授权 operation 快照、批次进度和摘要。
- `GET /api/v1/events`：当前租户授权的 SSE，支持 Last-Event-ID 和 reset。
- `POST /api/v1/check-updates`：客户主动检查，fresh 命中不创建新 FetchJob。
- `GET /api/v1/trackings/{id}`：按 tenant scope 返回客户允许字段。

端点响应 schema、字段必填性、状态码、错误码、重试语义和兼容策略必须写入仓库 API 契约文件（`packages/contracts/`）并由测试校验。

**ID 口径（已确认裁定，见 11 号文档 §0）**：对外 ID 统一用 UUID（`public_id`），数据库内部保留 bigint 主键，与本节示例一致、防枚举。`GET /api/v1/trackings/{id}` 与 `POST /api/v1/check-updates` 的 `tracking_ids` 一律使用 **B 库 `customer_tracking_id` 的对外 UUID**，不暴露 A 库采集事实 ID（`tracking.public_id`）；拼接与校验只在本站白名单投影内进行。

### 3.2 错误与幂等

错误码按身份/权限、输入、余额、Provider 暂不可用、任务处理和系统故障分类。客户响应不泄露上游状态码、代理、浏览器或内部数据库信息；管理员诊断接口只提供脱敏分类。提交网络重试复用 client_request_id；SSE 重连用事件序号，不触发新业务操作。

### 3.3 权限和隔离

客户 ID、tenant ID 从服务端认证上下文获取，不信任请求体。所有查询和更新在 SQL/数据访问层强制 tenant scope。管理员与客户 API 分离，admin 仅受控内网访问。BFF 不持有 A 库凭据；sync-agent 使用只够完成请求/投影/账务摆渡的身份。

当前是同一 PostgreSQL 实例内 A/B 双库、进程/账号/端口/凭据四层逻辑隔离，**不是物理隔离**；不能防 root、主机入侵、同机高权限代码、快照或备份泄露。前端 JS 天生公开，做不到 100% 防逆向；防逆向主要靠服务端判定、白名单投影、单向摆渡和受控访问，不依赖前端混淆。不把书面授权变成额外发布要求，也不因外部授权不确定性改变本模块的技术限制。

### 3.4 前端与日志安全

生产前端不得包含 USPS 域名、代理地址、profile 名称、A 库表名、内部采集端点、secret、内部错误码或 source map。设置 CSP、CSRF 防护、安全响应头、会话过期和登录速率限制。日志和指标使用脱敏 ID；禁止记录完整单号、客户邮箱、Cookie、认证头和原始代理凭据。

黑名单作用域按已定裁决区分：client-web 全量阻断；admin-web 因仅在内网，可出现队列、Worker、摆渡等内部业务术语，但 USPS 上游域名、代理凭据、浏览器运行时痕迹、secret、内网 IP、source map 和禁用端点仍全量阻断。该划分是有文档依据的作用域差异，不是静默白名单。

## 4. 已吸收的接口基线

以下路径和语义作为当前 API 契约的核心基线，完整字段以仓库内 `packages/contracts/` 为准（原引用的 `开发文档/05_技术文档/API-CONTRACT.md` 目录不存在，D4 裁定见 11 号文档）：

| 类型 | 路径 | 作用 |
|---|---|---|
| 客户认证 | `/api/v1/auth/login`、`/api/v1/auth/me` | 登录、会话和席位快照 |
| 提交 | `/api/v1/submissions`、`/api/v1/submissions/estimate` | 一次完成清洗、计费、入队和受理；提交前预估（不入账） |
| 进度 | `/api/v1/operations/{id}`、`/api/v1/events` | 快照、SSE、断线恢复 |
| 轨迹 | `/api/v1/trackings`、`/api/v1/trackings/{id}`、`/api/v1/check-updates` | 客户投影和主动检查 |
| 账务 | `/api/v1/billing/wallet`、`/api/v1/billing/ledger`、`/api/v1/billing/redemptions` | 余额、流水、兑换码 |
| 管理 | `/api/v1/admin/*` | 仅 admin 角色和受控内网 |

统一错误体使用 `detail.code/message`；`idempotency_conflict`、`invalid_input`、`request_too_large`、`insufficient_points`、`rate_limited` 等错误码必须保持稳定，白话消息不得泄露上游和内部信息。系统不设置 `quote_expired`、`quote_conflict`。

## 5. 请求/响应示例

### 5.1 登录 `POST /api/v1/auth/login`

请求：
```json
{ "email": "user@example.com", "password": "***" }
```
成功 200：
```json
{ "access_token": "eyJhbGciOi...", "token_type": "bearer", "expires_in": 3600 }
```
失败 401：
```json
{ "detail": { "code": "unauthorized", "message": "邮箱或密码不正确" } }
```

### 5.2 提交 `POST /api/v1/submissions`

请求头：`Authorization: Bearer <token>`、`X-Client-Request-Id: <uuid>`

请求：
```json
{
  "raw_text": "9400150206217997979667\n9400150206217997979742\n（最多 1,000,000 行，≤64 MiB）"
}
```
成功 202：
```json
{
  "operation_id": "1e2c87c8-b947-43d9-81a2-eef01d40c29c",
  "state": "accepted",
  "item_count": 2,
  "batch_count": 1,
  "counts": {
    "valid": 2, "garbled": 0, "fresh_hit": 0, "blank_line": 0,
    "normalized": 0, "waived_30d": 0, "checksum_warn": 0,
    "invalid_length": 0, "ambiguous_input": 0, "invalid_charset": 0,
    "carrier_mismatch": 0, "unsupported_shape": 0, "duplicate_in_operation": 0
  },
  "points_charged": 2,
  "points_waived": 0,
  "accepted_at": "2026-11-18T16:05:36.236Z"
}
```

失败 422（输入非法）：
```json
{ "detail": { "code": "invalid_input", "message": "没有可用的单号" } }
```
失败 402（余额不足，整批原子失败）：
```json
{ "detail": { "code": "insufficient_points", "message": "积分余额不足", "required": 1000, "available": 200 } }
```
失败 409（幂等冲突）：
```json
{ "detail": { "code": "idempotency_conflict", "message": "该请求编号已用于另一份提交内容，请重新发起" } }
```

### 5.2.1 提交前预估 `POST /api/v1/submissions/estimate`（G2 增补）

请求头同 §5.2；请求体同 §5.2（`raw_text`）。服务端按 06 §3.1/3.2 做与正式提交完全相同的清洗与计费资格判定，但**不入账、不写 reservation、不产生 operation、不占幂等键业务语义**（同请求内容重复调用返回相同结果）。

成功 200：
```json
{
  "item_count": 2,
  "counts": { "valid": 2, "waived_30d": 0, "duplicate_in_operation": 0,
              "carrier_mismatch": 0, "garbled": 0, "（其余分类同 §5.2 counts）": 0 },
  "points_estimated": 2,
  "cleaner_version": "v1"
}
```

约束：

- 预估结果**不构成报价**、不设报价有效期、不作为任何扣费依据；最终扣费以正式提交的 202 响应为唯一权威。
- 前端以防抖方式调用（输入停顿 ≥300ms），用于实时解析面板与成本预估条展示；禁止前端本地计算计费。
- 预估与提交之间库内事实可能变化（他人提交、后台保鲜），新增数量可能减少——属预期行为，前端预估条须标注"预估，以提交结果为准"。

### 5.3 进度 `GET /api/v1/operations/{id}`

成功 200：
```json
{
  "operation_id": "1e2c87c8-...",
  "state": "processing",
  "total": 1000,
  "done": 357,
  "batches": [
    { "batch_seq": 1, "state": "succeeded", "item_count": 500 },
    { "batch_seq": 2, "state": "processing", "item_count": 500, "done": 357 }
  ],
  "points_charged": 1000
}
```

### 5.4 SSE `GET /api/v1/events?operation_id={id}`

响应头：`Content-Type: text/event-stream`、`Cache-Control: no-cache`

事件流：
```
id: 1
event: batch_progress
data: {"batch_seq":2,"done":100,"total":500}

id: 2
event: operation_done
data: {"operation_id":"1e2c87c8-...","state":"done","succeeded":980,"failed":20}
```

断线重连：携带 `Last-Event-ID: 1`，服务端从该序号续推。

### 5.5 轨迹 `GET /api/v1/trackings/{id}`

成功 200：
```json
{
  "tracking_id": "8b1f2c3d-4e5a-4b6c-8d9e-0f1a2b3c4d5e",
  "normalized_number": "9400150206217997979667",
  "status": "in_transit",
  "status_zh": "运输中",
  "events": [
    {
      "occurred_at": "2026-11-18T10:00:00Z",
      "status": "arrived",
      "description_zh": "已到达 USPS 设施",
      "location": "JERSEY CITY NJ DISTRIBUTION CENTER",
      "event_code": "ARR"
    }
  ],
  "updated_at": "2026-11-18T10:05:00Z"
}
```
未查到 200：
```json
{ "tracking_id": "c2d3e4f5-6a7b-4c8d-9e0f-1a2b3c4d5e6f", "status": "not_found", "status_zh": "无记录", "events": [] }
```

### 5.6 主动检查 `POST /api/v1/check-updates`

请求（`tracking_ids` 为 B 库 `customer_tracking_id` 对外 UUID）：
```json
{ "tracking_ids": ["8b1f2c3d-4e5a-4b6c-8d9e-0f1a2b3c4d5e", "c2d3e4f5-6a7b-4c8d-9e0f-1a2b3c4d5e6f"] }
```
成功 200：
```json
{
  "results": [
    { "tracking_id": "8b1f2c3d-4e5a-4b6c-8d9e-0f1a2b3c4d5e", "fresh": true, "will_fetch": false },
    { "tracking_id": "c2d3e4f5-6a7b-4c8d-9e0f-1a2b3c4d5e6f", "fresh": false, "will_fetch": true }
  ]
}
```

### 5.7 账务 `GET /api/v1/billing/wallet`、`GET /api/v1/billing/ledger`

钱包 200：
```json
{ "balance": 49000, "frozen": 0, "lifetime_consumed": 1000 }
```
流水 200：
```json
{
  "items": [
    { "ledger_id": 1, "ledger_type": "charge", "points_change": -1000, "reference_type": "operation", "reference_id": 42, "description": "提交 1000 条", "created_at": "..." }
  ],
  "next_cursor": "..."
}
```

### 5.8 兑换码 `POST /api/v1/billing/redemptions`

请求：
```json
{ "code": "XXXX-XXXX-XXXX" }
```
成功 200：
```json
{ "points_added": 500, "balance": 49500 }
```
失败 422：
```json
{ "detail": { "code": "redemption_code_invalid", "message": "兑换码无效或已核销" } }
```

## 6. 模块间依赖

00 提供全局权限/权威原则；05 提供实体与投影；06 使用直接提交契约；03/04 按本模块消费管理/客户 API；02/07 的内部调用也必须使用明确服务身份、schema 版本和审计关联 ID。

## 7. 交付内容

- 版本化 OpenAPI/API-CONTRACT 与 SSE schema。
- 错误码和幂等重试规范。
- 客户/管理员/服务账号权限矩阵与 tenant scope 检查。
- CSRF、会话、速率限制、安全响应头和日志脱敏实现。
- 越权、IDOR、注入、前端黑名单和接口兼容性测试报告。
