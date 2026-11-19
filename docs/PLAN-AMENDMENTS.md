# PandaTrack 定稿方案缺陷补全与裁定（施工基准）

> 状态：开发前置文档。把 00–09 中相互矛盾、缺失、失效引用和执行歧义逐条列出并裁定，避免开发时各自假设。
> 依据：00–09 原文（逐条标注出处）；已获确认的口径标注「已确认」，其余为「建议裁定」待你拍板。
> 效力：本文件是对 00–09 的**增补与具体化**，不改动业务目标。经确认的裁定与原文冲突时，以本文件为准并同步回写对应模块文档。

---

## 0. 已确认的三项决策（本轮之前敲定）

| 项 | 决策 | 影响 |
|---|---|---|
| 对外 ID 类型 | 对外统一用 **UUID**（内部 bigint 主键 + `public_id uuid`），与 09 示例一致、防枚举 | 09 §5、05 全部业务表需加 `public_id` |
| 客户侧 tracking_id | 客户 API 一律用 **B 库 `customer_tracking_id`**，不暴露 A 库采集事实 ID | 09 §5.5/§5.6、04 轨迹接口 |
| 缺失表补齐节奏 | **P0 一次性全补齐**，后续模块直接建库，避免边写边改 schema | 05 迁移文件一次性建齐 |

---

## 1. 缺陷总览

| 编号 | 类别 | 一句话 | 出处 | 状态 |
|---|---|---|---|---|
| A1 | 基线矛盾 | 方案把「已存在的 monorepo / 427 passed」当续作前提，但工作区实际只有开发文档 | 00 §10、02 §3.3 | 建议裁定 |
| A2 | 环境边界 | 真实 Provider、容量标定、百万压测、备份恢复只能在目标 Linux 完成，本机无法闭环 | 00 §12、08 | 建议裁定 |
| B1 | 顺序冲突 | §7.1 把 03/04 排第 7 位，§7.2 把 03/04 放 M2（早于采集 M3） | 00 §7.1 vs §7.2 | 建议裁定 |
| C1 | schema 缺失 | A 库 tracking 缺 `next_sync_at/version/last_success_at`，但 02/07 依赖这些字段 | 05 §5.3 vs 02 §5.7.1、07 §3.7 | 已确认补齐 |
| C2 | 索引错误 | single-flight 唯一索引只覆盖 `pending/running`，与实际状态机不匹配 | 05 §5.3 vs 07 §3.1 | 已确认修正 |
| D1 | 数值冲突 | 并发公式除数 500（07 §3.3.1）vs 550（00/02/07 配置表），且都算不出 4G→6 | 00 §5.1、02 §3.3、07 | 建议裁定 |
| D2 | 口径冲突 | 并发上限 ≤5（02 表）vs 无上限、8G→12（00/02/07） | 同上 | 建议裁定 |
| D3 | 分类冲突 | `challenge`/`page_type_unknown`/`circuit_open` 在 02/07 的处置归类相反 | 02 §5.1 vs 07 §3.3.2 | 建议裁定 |
| D4 | 引用失效 | `05_技术文档/API-CONTRACT.md`、`03_原始资料/同类竞品.txt` 均不存在 | 09 §4、04 §3.1、00 §10 | 建议裁定 |
| E1 | 结构缺失 | 全文无目录结构/工程约定（你已指出） | 全文 | 已补全 |
| E2 | schema 缺失 | 缺 11 张方案要求的表（见 §4） | 03/04 功能清单 vs 05 | 已确认补齐 |

---

## 2. 逐条裁定

### A1 代码基线（工作区 vs 方案前提）
- **事实**：00 §10 称已「全量后端测试 427 passed / E2E 69/0 / mock 全删 / compose 固化」，但当前工作区 `E:/WorkBuddy/PandaTrack` 只有 `开发文档/`，无 `pyproject.toml`、无 `services/`、无仓库历史。02 §3.3、07 §3 提到的 `runtime.py`/`usps_dispatcher.py` 也无实体。
- **裁定（建议）**：视方案中的「已完成证据」为**历史验收记录/目标基线**，不作为当前代码事实。当前从零建立 monorepo（目录见 `PROJECT-STRUCTURE.md`），既有文件名作为新代码命名对齐依据。
- **影响**：不复用不存在的文件；所有模块按新目录落地。

### A2 本机交付边界
- **事实**：00 §1.2 明确 Linux 云服务器是唯一开发联调/验收/压测环境；Windows 不作运行验收。00 §12 的 N1/N2 未就绪。
- **裁定（建议）**：本机只交付源码、配置模板、纯逻辑单测；真实 Provider 验收、1/2/5/10 环境容量标定、百万级受理压测、备份恢复演练统一标注「待 Linux 环境 + N1/N2」，不写成通过。既有「427 passed」等历史数字只作参考基线，不作本次交付证据。

### B1 交付顺序冲突
- **事实**：§7.1 步骤 7 才做 03/04；§7.2 的 M2 就交付 03 管理端 + 04 前端骨架。
- **裁定（建议）**：以**依赖关系**而非文档编号排序。契约（09）先行 → 数据（05）→ 计费（06）与采集/调度（02/07）为关键路径 → 03/04 依赖已固化契约，可在契约冻结后并行起骨架，但不先于 06/02 的核心逻辑。采用单一顺序：**骨架+01配置层 → 05 → 09 → 06 → 02 → 07 → 03/04 → 08**，并把 §7.2 里程碑里的 M2 前端「骨架」理解为契约冻结后的 UI 原型，非完整功能。

### C1 A 库 tracking 补字段（已确认补齐）
- **冲突**：05 §5.3 的 tracking 仅 `tracking_id/normalized_number/carrier/created_at/updated_at`；但 02 §5.7.1 的刷新需 `next_sync_at`，07 §3.7 的终态保护需 `version`（乐观锁）与 `last_success_at`。
- **裁定**：tracking 增 `next_sync_at TIMESTAMPTZ`、`version INT DEFAULT 0`、`last_success_at TIMESTAMPTZ`，并建 `idx_tracking_next_sync`。

### C2 single-flight 索引（已确认修正）
- **冲突**：05 的唯一索引覆盖 `(normalized_number, state)` 且 state 仅 `pending/running`；07 §3.1 的状态机含 `claimed/waiting_for_session/retry_scheduled/collecting_response` 等活跃态。
- **裁定**：single-flight 唯一索引改为覆盖全部活跃态（用 partial unique index `WHERE state IN (...)` 列举活跃态），终态不占用唯一约束；`fetch_job` 增 `retry_at TIMESTAMPTZ` 供重建视图使用。

### D1/D2 并发公式与上限
- **事实**：
  - 00 §5.1 表：`max(2,(可用内存MB-900)//550)`；00 §5 正文写 2G→2、4G→6、8G→12。
  - 02 §3.3：`max(2,(可用内存MB-900)//550)`；表格却写「并发环境数 ≤5」。
  - 07 §3.3.1 推算公式：`//500`，并写 4G(可用3.2G)→6、8G(可用7.8G)→12；07 §3.7 配置表又写 `//550`。
- **算术核对**：`//550`：2G(可用≈1.5G→按本机可用口径) 不确定；4G 可用 3.2G→`(3200-900)//550=4`；8G 可用 7.8G→`(7800-900)//550=12`。`//500`：4G→`(3200-900)//500=4`；8G→`(7800-900)//500=13`。**两者都算不出「4G→6」**（要得 6 需除数≈380）。
- **裁定（建议）**：统一用 `max(2, (可用内存MB - 900) // 550)`，`USPS_MAX_ENVIRONMENTS` 显式设置优先。按此公式 8G→12 与多数文档一致；**4G→6 判为文档笔误，按 4G→4 落地**。并发**无硬上限**（删除 02 表格「≤5」的旧残留）；§02「首发从最低值起」保留为分阶段启动策略，非上限。

### D3 失败分类（权威口径）
- **冲突**：02 §5.1 失败矩阵：`challenge` 可回炉；07 §3.4「challenge 移出 stop 名单」。但 07 §3.3.2 又把 `challenge` 列入 TERMINAL；`page_type_unknown`、`circuit_open` 在 02/07 归类相反。
- **裁定（建议）**：以 **02 §5.1 失败矩阵为唯一权威**（原文称其为「实现、告警、验收的直接依据」）：
  - `challenge` = RETRYABLE：换州级出口回炉，超 `max_attempts=3` 转 TERMINAL。
  - `page_type_unknown` / `quality_gate_rejected` = TERMINAL：fail-closed，先修分类器。
  - `circuit_open` = 冷却半开探路，**不计入连续失败阈值**，未超限走 `retry_scheduled`。
  - 07 §3.3.2 的清单按此对齐修订。

### D4 失效引用
- **事实**：09 §4 称完整契约以 `开发文档/05_技术文档/API-CONTRACT.md` 为准，该目录不存在；04 §3.1 引用 `03_原始资料/同类竞品.txt`，实际在 `开发文档/02_辅助资料/`；00 §10/§11 引用 `05_技术文档/` 作执行附录。
- **裁定（建议）**：API 契约权威源改为仓库内 `packages/contracts/`（09 负责新建）；竞品引用修正为 `开发文档/02_辅助资料/同类竞品.txt`；技术与故障附录迁到仓库 `docs/`。删除对所有不存在路径的引用。

### E1 目录结构缺失 — 已补全
- 见 `docs/PROJECT-STRUCTURE.md`。含 monorepo 顶层、`apps/*` 内部分层、`packages/*`、`infra/migrations/a|b`、命名约定、依赖方向、环境分层。

### E2 缺失表 — 已确认一次性补齐
- 03/04 功能要求但 05 未定义的表，P0 迁移一次性补齐（详见 `PROJECT-STRUCTURE.md` §2 与 05 增补迁移）：
  - **B 库**：`tenant`、`seat`、`admin_user`、`target_group`、`import_job`、`export_job`、`audit_log`、`session`、`refresh_budget`、`redemption_code` 相关字段补齐。
  - **A 库**：`provider_health`、`fetch_attempt_log`。
- 同时给全部对外业务表加 `public_id uuid`（见 §0）。

---

## 3. 需要你拍板的开放项（不阻塞方案定稿，但影响开发执行）

| # | 问题 | 建议 |
|---|---|---|
| Q1 | 代码仓库：GitHub 连接器可用（§08 提到「仓库无远端、Actions 首次实跑未完成」）。是否现在创建远端仓库并配 CI？ | 建议创建，CI 在 Linux runner 跑测试与构建 |
| Q2 | 服务器接入：辅助资料有 SSH 文件，按凭据规则我只用脚本读取、不外泄正文。何时连服务器做环境核验？ | 建议代码稳定后再连，边写边联调 |
| Q3 | N1/N2 状态（域名/TLS、代理凭据、ClawBrowser 授权、30–50 真实单号样本）是否就绪？ | 未就绪则 Provider 默认 fail-closed，真实验收标阻塞 |

> 这三项是**执行层**决策，不影响本方案完善结论。你确认方案后，我按 §4 顺序开工；Q1–Q3 可在开发推进中再定。

---

## 4. 补全后的施工顺序（修订 00 §7）

```text
P0  骨架 + 01配置层 + 05(A/B全表/索引/字段) + 09(契约/错误码/权限)   ← 当前应从此开始
P1  06 清洗计费（消费 05+09）
P2  02 采集核心（Provider/解析/fail-closed，产出错误分类契约）
P3  07 调度/Worker/环境池/熔断（消费 02 结果契约，按 D1/D2/D3）
P4  03 管理端 + 04 客户前端（并行，消费已冻结契约）
P5  08 CI/测试/部署/备份/监控（真实环境验收待 N1/N2）
```

**打破文档循环依赖**：02↔07（02 依赖 07 的调度、07 依赖 02 的结果契约）通过「02 先产出错误分类/结果契约，07 再实现」解开；06↔09 通过「09 契约先行」解开。

---

## 5. 变更记录

- 2026-11-19：初版，列出 A1–A2/B1/C1–C2/D1–D4/E1–E2 共 11 项缺陷与裁定；固化 3 项已确认决策；新增目录结构约定文档。

---

## 6. 实施期最终裁定（P8–P10，2026-11-19，全部已落地）

| 编号 | 决策 | 理由与影响 |
|---|---|---|
| R1 | **前端目录保持 `apps/web`（客户端）+ `apps/admin`（管理端）**，不迁移到方案 04 增补的 `frontend/client` | apps/web 已部署、已接 CI、nginx root 固化；迁移目录纯属折腾。本裁定覆盖 04 的 frontend/client 增补 |
| R2 | 生产形态 = **同机同域**：客户 `pandatrack.ginzavog.com` / 管理 `pandaadmin.ginzavog.com`，nginx TLS + `/api/` 反代 127.0.0.1:8100，systemd `pandatrack-api` | 00 §3.2 形态 A 落地；配置入库 `infra/nginx/pandatrack.conf` |
| R3 | **一键部署**：`scripts/deploy.sh`（7 步：检查→pull→依赖→幂等迁移→前端构建发布→systemd→nginx→冒烟）+ `docs/DEPLOY.md` 新服务器初始化指南 | 服务器更新一律 `bash scripts/deploy.sh`；Python 依赖走 `requirements.txt`（monorepo flat-layout 不可 editable 安装） |
| R4 | **测试卫生**：真库集成测试不得触发生产采集——consumer 增 `PT_ENQUEUE_SKIP_NUMBERS` 黑名单（命中不入队仍标记 processed）+ `tests/integration/_dbtest_cleanup.py` teardown 级联清 A 库 | worker 常驻后测试事件会被真实消费；端到端验证 skipped_env=1 零污染 |
| R5 | 后端补齐：`POST /submissions/estimate`（只读预估不入账）、`POST /imports`（大批量受理）、`POST /admin/auth/whoami`（会话恢复） | 04 §5.4/§5.9、03 §3.1 缺口；`total_count` 口径 = Cleaner 全量候选数 |
| R6 | 客户端设计系统按 04 §4.4 落地：中性灰阶 + 单强调色青绿 `#0F766E`、数据列等宽、8pt、两级阴影、120–200ms ease-out | SubmitView 提交页、检查更新防呆弹层、双状态图例、SSE 三态指示器、可见性感知轮询 |
| R7 | 管理端五个页面：登录/客户/账务/Provider/审计；高风险操作理由必填+二次确认 | 03 全部路由已对接；权限矩阵见 R9 |
| R8 | ClawBrowser 流量优化：clawctl 无原生禁图/禁视频配置；当前 USPS 跟踪页实测 ~180KB/次无大图风险；如需拦截走 `clawctl --cdp`（裸 CDP）实现 Network.setBlockedURLs | 计流量代理的防护预案，非当前必做 |

| R9 | **RBAC 5 角色权限矩阵落地**（03 §2）：`super_admin` 系统管理员 / `finance` 账务 / `provider_ops` Provider 运维 / `support` 客户支持 / `readonly` 只读运营；权限点 customers:read/write/delete、billing:read/write、providers:read/write、audit:read | 权威矩阵 `apps/api/src/api/authz.py`（fail-closed，未知角色一律拒绝）；路由 `require_permission` 强制校验；admin 前端按角色过滤菜单/按钮（服务端仍为权威）；迁移 b/0006 归一 legacy `admin`→`super_admin` 并加 CHECK 约束；`customers:delete`（注销）仅 super_admin |
| R10 | **登录防爆破**（09 §5.1）：customer/admin 两个登录端点加两级计数（`ip|账号` 单源 + `*|账号` 跨源撞库）；10 分钟窗口失败 ≥5 次锁定，30s 起指数翻倍封顶 1h；状态持久化 B 库 `auth_throttle`，重启不清零；锁定返回 429 + retry_after_seconds，不泄露账号存在性 | 纯算法 `api/throttle.py` + repo 持久化；nginx 前置下信任 X-Forwarded-For 首跳 |
| R11 | **ResultsView 接入 SSE**：结果页 SSE 推送 → 800ms 防抖自动刷新；可见性感知轮询降级为断线兜底（SSE 在线时轮询自动跳过） | 修复 TrackingDetailView 轨迹时间字段不一致 bug（前端 `event_time` → 后端 `occurred_at`，此前时间列恒为空） |
| R12 | **轨迹翻译（差异化增值）**：`GET /trackings?lang=` 与 `GET /trackings/{id}?lang=`；Google Translation v2 + B 库 `translation_cache` 按 (lang, sha256) 复用；状态标签走静态字典不过机翻 | 10 种目标语言；未配 `PT_TRANSLATE_API_KEY` 或调用失败一律优雅降级返回原文，不阻塞查询主链路；竞品对标：17TRACK 翻译收 1 配额、FrogTracking 无翻译功能——首版免费作为增值项，计费后续单独裁定 |

### 变更记录（续）
- 2026-11-19（晚）：P8 前端重构与管理端落地、P9 测试卫生（R4）、P10 一键部署（R1–R3/R8）三项裁定固化；双域名登录冒烟通过，B 库首个客户与管理员账号建立。
- 2026-11-19（夜）：R9–R12 落地（RBAC 权限矩阵、登录防爆破、ResultsView 接 SSE、轨迹翻译接口）；368 项测试全绿。
