# USPS 单号查询系统 10：目录结构与工程约定

> 状态：定稿方案组成部分（施工级约定），补齐 00–09 未规定、但开发前必须明确的「代码放在哪、谁依赖谁、怎么命名、怎么配置」。
> 依据：00 §3 架构图、§6 模块分工、§10 技术基线；各模块交付物见 00 §9。
> 效力：本文件与 00–09 冲突时，业务规则以 00–09 为准（裁定见 11 号文档）；00–09 未规定的工程细节，以本文件为准。

---

## 1. 为什么需要这份文档

00–09 定义了「做什么」，但在工程组织层面存在空白，直接开工会导致每个模块各写一套、契约无法共享、A/B 库摆渡边界模糊：

- 只写了「单一 monorepo」「`packages/contracts`」「A/B migration 分目录」（00 §10 / §198），没有给出完整目录树。
- 既有一份代码库的文件名（`services/runtime.py`、`usps_dispatcher.py`、`usps_claw.py`，见 00 §202、02 §3.3、07 §3）散落在模块文档里，没有统一归位。
- A/B 双库、sync-agent、SSE、前端黑名单等约束需要落到明确的目录边界才能被测试守住。

本文件把上述内容固化，**不含任何业务规则的新增或改动**。

---

## 2. monorepo 顶层结构

```text
pandatrack/
├── apps/                          # 可独立部署的运行单元
│   ├── bff/                       # FastAPI：客户/管理 API + SSE（模块 03/06/09 的 HTTP 层）
│   ├── worker/                    # 采集 Worker：调度消费 + Provider + 解析（模块 02/07）
│   ├── sync-agent/                # A→B 单向摆渡、投影、SSE 事件写入（模块 05）
│   ├── client-web/                # 客户前端 Vue3（模块 04）
│   └── admin-web/                 # 管理前端 Vue3（模块 03）
├── packages/                      # 内部共享库，不独立部署
│   ├── contracts/                 # HTTP/SSE/错误码/幂等 Pydantic 契约（权威源，模块 09）
│   └── common/                    # 错误码字典、状态字典、哈希、时间窗等纯函数
├── infra/                         # 部署与数据库基础设施
│   ├── migrations/
│   │   ├── a/                     # A 库迁移（采集事实权威）
│   │   └── b/                     # B 库迁移（客户/账务权威）
│   ├── docker/                    # 各服务 Dockerfile
│   ├── nginx/                     # 客户域 / 管理域 server block
│   ├── systemd/                   # 进程单元文件
│   └── docker-compose.yml         # 本地/验收编排（00 §202 已固化）
├── tests/
│   ├── unit/                      # 纯逻辑，不依赖 PG/Redis/网络
│   ├── integration/               # 依赖 PG/Redis，需 Linux 验收区
│   └── e2e/                       # 全链路，需真实 Provider 就绪（N1/N2）
├── scripts/                       # 迁移、备份、恢复、制品校验、黑名单扫描
├── docs/                          # 方案补全、契约说明、故障处置附录
├── pyproject.toml                 # Python 依赖与 workspace 根
├── pnpm-workspace.yaml            # 前端 workspace（apps/*-web）
├── .env.example                   # 配置项清单（仅键名与示例，无真实值）
└── README.md                      # 启动与验证入口
```

**关键约束**：
- 只有 `apps/*` 产出可部署制品；`packages/*` 只被依赖，不单独部署。
- `infra/migrations/a` 与 `b` 物理分目录，禁止互相引用；A/B 无跨库 JOIN（00 §4）。
- 真实密钥只经环境变量/秘密注入，仓库内只有 `.env.example`（00 §10 / 02 §4.3）。

---

## 3. apps 内部结构与分层

### 3.1 apps/bff（后端 API）

```text
apps/bff/src/bff/
├── main.py                        # FastAPI app、 lifespans、全局异常处理
├── config.py                      # 环境变量解析（只在此处读 os.environ）
├── api/
│   ├── deps.py                    # 鉴权、租户 scope、幂等键等依赖注入
│   ├── v1/
│   │   ├── auth.py                # /auth/login /auth/me
│   │   ├── submissions.py         # /submissions（06 直接提交事务）
│   │   ├── operations.py          # /operations/{id}
│   │   ├── events.py              # /events（SSE）
│   │   ├── trackings.py           # /trackings /trackings/{id} /check-updates
│   │   ├── billing.py             # /billing/* /redemptions
│   │   └── status_dict.py         # /status-dict（04 §426）
│   └── admin/                     # /admin/*，仅 admin 角色 + 受控内网（09 §5.8）
├── domain/                        # 纯业务，不依赖 infra
│   ├── cleaner.py                 # Cleaner v1（06）
│   ├── billing.py                 # 计费窗口、reservation、ledger、冲正（06）
│   ├── tenant.py                  # 客户/租户/席位/权限（03）
│   └── audit.py                   # 审计（03/09）
├── application/                   # 用例编排，组合 domain + infra
│   └── submission_service.py      # 一次请求内完成清洗→计费→入队→落库
└── infrastructure/
    ├── db_b.py                    # B 库连接、事务、UoW
    ├── redis_client.py            # 队列 broker / 短期缓存
    ├── outbox.py                  # B 库 outbox 写入与重放
    └── security.py                # 会话、Cookie、租户隔离、脱敏
```

### 3.2 apps/worker（采集与调度）

```text
apps/worker/src/worker/
├── main.py                        # Worker 进程入口
├── runtime.py                     # 【既有文件名，00 §202】领取带 lease 的 FetchJob → enabled_provider()
├── scheduler/
│   ├── usps_dispatcher.py         # 【既有文件名，02 §3.3/07 §3】BatchDispatcher
│   │                              #   consolidate / recent_checker / chunk(35) /
│   │                              #   assign_slots / human_interval_ms / max_rounds
│   ├── queue.py                   # Redis 队列（可由 PG pending/claimed/lease 重建）
│   ├── lease.py                   # 租约、single-flight、强杀回收
│   ├── circuit.py                 # 熔断：冷却半开探路
│   └── capacity.py                # auto_max_environments() 内存推算
├── pool/
│   ├── environment.py             # 一套指纹 + 一个轮换出口 = 一个环境
│   ├── tab.py                     # 环境内标签页，每约 10 代换指纹出口
│   └── exit_check.py              # 出口三层准入：TCP→延迟→USPS 首页
├── provider/
│   ├── base.py                    # Provider 接口 + enabled_provider()（fail-closed）
│   └── usps_web.py                # 【对应既有 usps_claw.py，02】ClawBrowser/CDP 适配
├── parser/
│   ├── page_type.py               # 页面类型识别
│   ├── status_map.py              # 12 态映射
│   ├── events.py                  # 物流事件解析
│   └── quality_gate.py            # 八道质量闸门
├── evidence/                      # 页面证据留存 + 脱敏
└── errors.py                      # 失败矩阵分类（RETRYABLE/TERMINAL，权威见 02 §5.1）
```

> **既有文件名映射**：`services/runtime.py` → `worker/runtime.py`；`usps_dispatcher.py` → `worker/scheduler/usps_dispatcher.py`；`usps_claw.py` → `worker/provider/usps_web.py`。保留原有术语，仅归位到统一结构。

### 3.3 apps/sync-agent（A→B 摆渡）

```text
apps/sync_agent/src/sync_agent/
├── main.py
├── outbox_reader.py               # 读 A 库 outbox，按事件 ID / payload digest 幂等
├── projector.py                   # 写 B 库白名单投影 + operation_snapshot
└── sse_publisher.py                # 写 projection_event 供 BFF /events 读取（09 §5.4）
```

### 3.4 前端

```text
apps/client-web/src/
├── api/                           # 仅 /api/v1/* 白名单客户端（04 §513）
├── views/                         # 公共 8 路由 + 工作台页面
├── components/
├── stores/                        # 状态机：提交→202→SSE/轮询→轨迹
├── router/
└── utils/                         # 白话错误映射、防 XSS 转义
apps/admin-web/src/                # 同构；admin 独立域名/会话（00 §10）
```

**前端黑名单**（04 §513、00 §8）：`api/` 与构建产物中禁止出现 USPS 域名、代理、profile、A 库表名、secret、内部错误码、采集端点；由 `scripts/scan_blacklist.sh` 在 CI 守门（08）。

---

## 4. packages 共享库

```text
packages/contracts/src/contracts/  # 权威契约源（替代失效的 05_技术文档/API-CONTRACT.md）
├── common.py                      # 统一错误响应 detail.code/message、状态码
├── submission.py                  # /submissions 请求/响应
├── progress.py                    # /operations/{id} 快照
├── events.py                      # SSE schema、Last-Event-ID
├── tracking.py                    # 轨迹投影（白名单字段）
├── auth.py                        # 登录/会话
└── billing.py                     # 钱包/流水/兑换码

packages/common/src/pandatrack_common/
├── codes.py                       # 错误码字典
├── status.py                      # 12 态映射（服务端权威）
└── hashutil.py                    # payload digest 等
```

依赖方向：`apps/*` 与 `packages/*` 可依赖 `contracts`、`common`；**`contracts`/`common` 不得依赖任何 `apps/*`**（避免循环）。前端的 TS 类型须由 `contracts` 的 OpenAPI/schema 生成或与之对齐，禁止手抄一份。

---

## 5. 分层依赖规则（防循环、守边界）

```text
client-web / admin-web ──HTTP /api/v1/*──▶ bff ──▶ (domain → application → infrastructure)
                                            │
bff ──写 B 库 / 读 projection──▶ B 库        │
bff ──入队──▶ Redis ◀──消费── worker ──写──▶ A 库
                                  │
A 库 ──outbox──▶ sync-agent ──投影──▶ B 库 ──▶ SSE ──▶ 前端
```

- 单向数据流：`BFF → Redis → Worker → A库 → sync-agent → B库 → SSE → 前端`。禁止反向直连（worker 不读 B 库业务表、bff 不读 A 库采集表，00 §4）。
- `infra/migrations/a` 归属采集事实，`b` 归属客户账务；`sync-agent` 是唯一跨库写入者。
- 领域层（`domain/`）为纯函数，不导入 `infrastructure/`；保证单测可在无 PG/Redis 环境运行。

---

## 6. 命名与版本约定

| 对象 | 规则 | 示例 |
|---|---|---|
| API 路径 | `/api/v1/<资源>`，版本固定 v1（09 §4） | `/api/v1/submissions` |
| 对外 ID | 内部 bigint 主键 + 对外 `public_id` UUID（见补全文档裁定） | `operation.public_id` |
| 客户侧轨迹 ID | 一律用 B 库 `customer_tracking_id`，不暴露 A 库事实 ID | `/trackings/{customer_tracking_id}` |
| 错误响应 | `{"detail":{"code":"...","message":"..."}}`（09） | `code=DUPLICATE_CLIENT_REQUEST` |
| 迁移文件 | `<库>/<4位序号>_<语义>.sql`，升序，含 `BEGIN/COMMIT` | `b/0001_initial.sql` |
| 配置项 | 大写下划线；秘密经注入，示例仅键名 | `USPS_MAX_ENVIRONMENTS` |
| 事件 ID | 全局唯一，摆渡幂等键 | event_id |
| 幂等键 | `客户 / 端点 / client_request_id` 三元组（06/09） | — |

---

## 7. 环境分层与交付链路（回应「本地开发 vs 服务器」）

```text
Windows 本地工作区  ──仅编辑源码/文档、纯逻辑单测──▶  提交代码仓库
        │
        ▼
Linux CI runner  ──构建固定制品 + 跑 unit/integration──▶  SHA-256 制品
        │
        ▼
Linux 验收区  ──真实 Provider / 容量标定 / E2E / 恢复演练──▶  验收记录
        │
        ▼
Linux 生产区  ──只部署已验收固定制品，不编译/改码/装依赖──▶  运行观测
```

- Windows **不运行项目服务、不承担验收**；本地 `pytest` 只算临时自检，正式测试在 Linux CI（00 §1.2、§8）。
- 真实 Provider、1/2/5/10 环境标定、百万级受理、备份恢复须在目标 Linux 完成，受 N1/N2 阻塞（00 §12）。
- 开发/验收/生产各自独立的数据库、Redis、域名 Cookie、凭据、profile、代理会话、数据目录（00 §8）。

---

## 8. 待落地清单（本文件已定义、开发时逐步填充）

- [ ] 各 `apps/*` / `packages/*` 的 `__init__.py` 与包安装配置（workspace）
- [ ] `.env.example` 全量键名（对齐 01 秘密注入）
- [ ] `infra/docker/` 各服务 Dockerfile 与 `docker-compose.yml` 对齐
- [ ] `scripts/scan_blacklist.sh` CI 守门脚本（08）
- [ ] 前端 TS 类型由 `contracts` schema 生成的构建步骤

> 本文件只定义结构与约定，不代表上述代码已实现。实现进度见开发任务清单。
