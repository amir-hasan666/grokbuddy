# Phase 3 GitHub Adapter 实现与验证报告

日期：2026-09-17。Human 明确确认 Phase 0–2 已关闭，并授权本轮只做 GitHub 通信投影与 Webhook 事件面。实现已停在本地边界；没有连接真实 GitHub、Grok 或 ACP。

## 开始前核对与冲突处置

开始前只读核对了 `IMPLEMENTATION_PLAN.md`、`PHASE2_REPORT.md`、`WORKBUDDY_INTEGRATION.md`、GitHub/Webhook/Final Review/Adapter 设计与实际实现。

| 冲突 | 处置 |
|---|---|
| `AGENTS.md` / plan / README 仍写 Phase 2、禁止进入 Phase 3 | 以本轮更新且明确的 Human 授权为准，只更新阶段状态，不借 Phase 3 修改核心 |
| 原 `GITHUB_CONNECTIVITY.md` 以 `issue_comment` 为初期候选 | 本轮明确禁止监听 comment events，改为唯一推进事件 `pull_request:synchronize` |
| 原 Phase 3 计划含 Pull 与真实测试仓库 | 本轮授权更窄；Pull、真实 API、公网投递均不实施并标 `ENVIRONMENT_VALIDATION_REQUIRED` |

Phase 0–2 冻结契约保持不变：Task/ReviewRequest/Finding 状态机、Review 协议、command receipt 幂等、backup 方法、actor `provider_id`、11 个 MCP Tool、HTTP/CLI behavior 均未改。

用户提供 WorkBuddy 真实 create_task `TASK-12d16e55-d3ee-4d84-8dc2-d6594c965d56`。只读查询 `var/workbuddy-mcp/hub.db` 确认：Task 唯一存在、状态 `NEW`、version=0，且有一次 `ARTIFACT_CREATED` 与一次 `TASK_CREATED` Audit。该证据确认 Hub 侧业务效果；WorkBuddy UI/网络来源仍以用户报告为证。

## 实现结果

### Event Mapping

| GitHub event | action | Adapter 结果 | Hub 业务效果 |
|---|---|---|---|
| `pull_request` | `synchronize` | 验签、解析、持久化、PR binding 查找、delivery/semantic dedup | 调用既有 Final `request_review`，只返回 `PENDING`；不运行 dispatcher/Mock/Reviewer |
| `pull_request` | 其他 action | `IGNORED` + Audit | 无 |
| `push` | 任意合法 payload | `IGNORED` + Audit | 无 |
| `ping` | ping | `IGNORED` + Audit | 无 |
| `issue_comment` | 任意 | 422 拒绝，不订阅 | 无；防 Comment→Webhook→Review 循环 |
| `pull_request_review_comment` | 任意 | 422 拒绝，不订阅 | 无 |
| 未知 event | 任意 | 422 拒绝 | 无 |

PR 必须通过 `github_bindings` 显式绑定 `repository_id + pull_request_number → task_id + builder/reviewer`。Repository immutable ID 是匹配依据；GitHub 内容不能选择 actor、修改 Task 状态或提供 verdict。

### Webhook 签名与 Delivery 幂等

- endpoint：`POST /webhooks/github`，本地脚本只允许 loopback。
- secret：从指定进程环境变量读取，默认名 `GITHUB_WEBHOOK_SECRET`；不读取 `.env`，不写源码/日志/Audit。
- 使用原始 body bytes 计算 HMAC-SHA256，与 `X-Hub-Signature-256` 常数时间比较。
- 缺失、错误或篡改签名均 401；Task/RR 不变，只记录 body hash、header 安全元数据与错误分类。
- `X-GitHub-Delivery` 在 `github_events` 唯一；同 delivery + 同 hash 返回原效果，同 delivery + 不同 hash 返回 409。
- canonical key 为 repository/resource/action/revision 的稳定组合。不同 delivery header 包装同一 PR synchronize/head SHA 也不重复创建 RR。
- 事件先持久化为 `PREPARED`，再用 canonical key 派生既有 command idempotency key 调用 ReviewService；若在 Hub commit 后、Adapter 回写前崩溃，重试仍返回原 `PENDING` receipt。

### Final Review Comment 投影

完成的 Final Review 由显式 projector 排队；Hub Review/Task 是唯一事实源。Comment 仅含：

- `status`、`verdict`、短 `summary`；
- `task_id`、`review_id`、`review_request_id`；
- `hub_pointer`；
- `<!-- grokbuddy-final-review:REVIEW_ID -->` 稳定 marker。

Projector 在数据库短事务中 claim，事务外调用 transport，再短事务确认。每次先按 marker 查找：存在则 update，缺失才 create；这也可恢复“外部已创建、确认前崩溃”的歧义。投影失败只进入 RETRY/FAILED，不回滚 Hub 已完成 Review。

当前 transport 是 `FileGitHubCommentTransport` 本地 JSON mock。它用于验证 Comment create-or-update 行为，不含 GitHub token、REST client 或生产写入能力。

### 持久化

SQLite `user_version` 从 1 加法迁移到 2，仅新增：

- `github_bindings`：一个 Task 对一个 PR 的不可变显式绑定；
- `github_events`：Webhook delivery、安全 metadata、处理状态与 RR receipt；
- `github_comment_projections`：每个 review 的 desired/applied hash、marker、comment receipt 与 retry 状态。

旧表、外键语义、backup 方法与 Artifact layout 未改。v1 数据库启动时通过 `CREATE TABLE/INDEX IF NOT EXISTS` 升级；未知版本仍拒绝。

## 验证结果

| Gate / 测试 | 结果 | 证据 |
|---|---|---|
| 本地 Webhook 可达 | PASS | 真实 loopback socket → WSGI `/webhooks/github` 返回 202；无公网/tunnel |
| 正确/错误/缺失/篡改签名 | PASS | `tests/test_phase3_github.py` |
| 同 delivery 重试 | PASS | 一个 Final RR；重复返回同 receipt |
| 同语义不同 delivery | PASS | `DUPLICATE_SEMANTIC`；仍只有一个 Final RR |
| Event→Hub→Final request→PENDING | PASS | PR synchronize 路径；`review=None`、Task=`FINAL_REVIEW_PENDING`、无 mock job |
| Hub result→Comment | PASS | Mock 完成 Hub Final Review 后，已有 marker Comment 被 UPDATE，未新增第二条 |
| Loop protection | PASS | 两类 comment event 均拒绝；出站 Comment 不构成入站 trigger |
| MCP / HTTP / CLI / Core 回归 | PASS | **462 passed**，0 fail，0 skip；[JUnit XML](phase3-tests.xml) |
| v1→v2 migration + backup smoke | PASS | 在临时副本升级；指定 WorkBuddy Task 保留，backup 含 1 Task 与 3 个 GitHub 表；临时目录已清理 |
| 协议 fixtures | PASS | 171/171；不把 schema pass 当真实 GitHub/Grok 证明 |
| Python dependencies | PASS | `pip check` 无 broken requirements |
| Real GitHub / public webhook | NOT RUN | 本轮硬边界；`ENVIRONMENT_VALIDATION_REQUIRED` |

可复现命令：

```powershell
Set-Location D:\Codex\grokbuddy
.\.venv-phase0\Scripts\python.exe -m pytest tests\test_phase3_github.py -q --tb=short
.\.venv-phase0\Scripts\python.exe -m pytest -q --tb=short --junitxml=docs\phase3-tests.xml
.\.venv-phase0\Scripts\python.exe scripts\validate_phase0.py --allow-core
.\.venv-phase0\Scripts\python.exe -m pip check
.\.venv-phase0\Scripts\python.exe scripts\grokbuddy_github.py --help
```

## 新增文件

- `src/grokbuddy/adapters/github.py`
- `src/grokbuddy/application/github.py`
- `src/grokbuddy/interfaces/github.py`
- `scripts/grokbuddy_github.py`
- `tests/test_phase3_github.py`
- `docs/PHASE3_REPORT.md`
- `docs/phase3-tests.xml`

## 修改文件

- `AGENTS.md`
- `README.md`
- `IMPLEMENTATION_PLAN.md`
- `ARCHITECTURE.md`
- `DATA_MODEL.md`
- `SECURITY.md`
- `src/grokbuddy/adapters/schema.sql`
- `src/grokbuddy/adapters/sqlite.py`
- `src/grokbuddy/infrastructure/runtime.py`
- `src/grokbuddy/ports/__init__.py`
- `docs/CAPABILITY_VERIFICATION.md`
- `docs/GITHUB_CONNECTIVITY.md`
- `docs/LOCAL_CORE.md`
- `docs/PHASE2_REPORT.md`
- `docs/SOURCE_OF_TRUTH.md`
- `docs/TEST_MATRIX.md`
- `docs/WORKBUDDY_INTEGRATION.md`

## 明确未做与未决项

- 未接真实 Grok；未创建/调用 GrokAdapter；未验证 Grok wake-up channel。
- 未接 ACP；未唤醒 WorkBuddy；未修改 MCP/HTTP/CLI 接口或用户级 WorkBuddy 配置。
- 未部署 Production GitHub；未读取/保存 token；未调用 GitHub REST；未开 tunnel/public HTTPS。
- 未实现 Pull/hybrid、真实 actor/scopes、rate-limit/401/403 实测、真实 Comment 回执。
- 未自动 merge、approve、push、改 branch；未执行任何高风险 GitHub 写操作。
- 本地 Comment mock 不证明真实 PR 评论权限、仓库 owner/repository ID 或独立 Builder/Reviewer actor。

Phase 3 在此停止，等待 Human 授权；不得自动进入 Phase 4。
