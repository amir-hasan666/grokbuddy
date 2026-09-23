PHASE6-STEP6.20-REAL-FINAL-E2E: PASS

# Phase 6 Step 6.20 — Real Final E2E Report

日期：2026-09-22（Asia/Shanghai）
范围：将 Human 已核定现场与正式 Hub 库/受控 Artifact 的只读核验写入 6.20 历史证据；不重跑 E2E，不修改业务代码、状态机、MCP、Credential、`mcp.json` 或 Hub DB。

## 1. 结论与证据边界

Phase 6.20 的**核心业务 E2E PASS**。同一个 Task 经过正式 WorkBuddy ingress、Plan Review、Worker assignment、self-test、Final Review 与 Hub APPLY，最终由合法 Final PASS 进入 `DONE`：

- Task：`TASK-702a9f15-b1a7-4a2c-a5ef-0c1a12d2a5bd`
- 终态：`state=DONE`、`version=15`、`content_revision=2`
- 完成依据：`completion_basis=FINAL_REVIEW_PASS`，不是 Human Accept/override
- 业务事实源：`var/github-manual/hub.db`；稳定 PublicBase：`https://grokbuddy.amirhasan.top`
- 最终 GitHub projection 是 `UNKNOWN`、`binding_id=null`。这是必须保留的非阻塞诚实项，不是 projection PASS，也不否定 Hub 已成立的 `DONE / FINAL_REVIEW_PASS`。

选择报告首行 A，因为冻结的 [Manual Glue / Supervisor Contract](PHASE6_STEP6_0A_MANUAL_GLUE_SUPERVISOR_CONTRACT.md) 明确规定：Hub Review 是业务依据，GitHub projection 是独立展示面；projection 失败或待对账不回滚 `COMPLETED` / `DONE`。

## 2. 正式路径与零人工胶水

本次核定的正式生产路径为：

`WorkBuddy ingress MCP → Hub/Plan → Reviewer B → Hub APPLY → Worker MCP → self-test/Final → Reviewer B → Hub APPLY/DONE`

- WorkBuddy 仅使用 `grokbuddy-ingress`、`grokbuddy-hub`、`grokbuddy-worker` 三个正式 MCP 面，共用 `var/github-manual` 运行时。
- Hub 为正式 Windows 启动链下的常驻 Supervisor；RR dispatch、event APPLY、projection intent 与 timeout/recovery 不由临时驱动脚本代替。
- 本次运行的 `Manual Glue=0`。未使用 direct Gateway/`LocalRuntime`、临时 `.py` 驱动、mock-reviewer、`run_until_idle`、`*_once`、人工改库、人工复制 finding/result、临时 resume 脚本或 Human Accept 冒充 Final PASS。
- Reviewer B 端的 poller/手动取件完成 intake 与 ACK，后续通过已认证 event 进入 Hub APPLY。该步骤没有被用来伪造 verdict，也没有用 Hub 调试胶水替代正式 worker；权威现场已将该样本的 Manual Glue 计数核定为 `0`。

`config/grokbuddy.service.json` 的现行字段与该现场一致：`runtimeDir=var/github-manual`、`publicBase=https://grokbuddy.amirhasan.top`、`reviewerActor=grok-reviewer-b`、`supervisorEnabled=true`、`supervisorIntervalSeconds=5`。

## 3. Task、Artifact 与 owner 证据

2026-09-22 以 SQLite URI `mode=ro` 读取 `var/github-manual/hub.db`，得到：

| 证据项 | 只读结果 |
| --- | --- |
| Task | `DONE`，version `15`，content revision `2` |
| Completion | `FINAL_REVIEW_PASS` |
| Owner | `workbuddy-ingress` |
| Owner 历史 | Task 由 `workbuddy-ingress` 创建；该 Task 的 Audit 中 owner/transfer 动作记录为 `0`，未发生 `owner_id` transfer |
| Approved Plan | `ART-ddc48514-1a79-4857-8cd8-946715ba7da0` (`PLAN`) |
| Self-test | `self_test_passed=true`，`ART-515c1490-01a0-4a43-900d-644e136e3c19` (`TEST_RESULT`) |
| Current Final | `ART-543fa6fe-aff0-4ab4-9fdb-805b87d81386` (`FINAL_PACKAGE`) |

受控 Artifact Store 的只读核对进一步确认：

- 冻结 Plan 的 approved scope 仅允许 `eye-care-reminder-plan.md`。
- DIFF Artifact `ART-44467caa-0920-4503-9170-8a19d4c2aa78` 仅新增该文件。
- Final Package 的 `changed_files=["eye-care-reminder-plan.md"]`，因此 `changed_files ⊆ approved scope`。
- TEST_RESULT 对 Plan A1–A4 为 `4/4 PASS`，并保留「未做真人体感实测」等未验证边界；本报告不将其扩大为医疗效果证明。

## 4. Review 时间线与不可变历史

| Review Request | 类型/轮次 | 通道 | 结果 | 历史意义 |
| --- | --- | --- | --- | --- |
| `RR-bebe1782-4a1d-4885-9b1c-9443b1f87a60` | PLAN / round 1 | 修复前未冻结通道 | `TIMED_OUT / REVIEW_TIMEOUT` | 当时无 binding 且未投递；保留，不改写、不复活 |
| `RR-32116386-3daa-4ced-a9e3-da87876cd3eb` | PLAN / round 2 | `REVIEWER_HTTP` | `TIMED_OUT / REVIEW_TIMEOUT` | Hub 已持久投递，B 在 deadline 前未取件/未 ACK；保留故障事实 |
| `RR-cfb06e90-0966-4631-97f7-f81bf5ebe37d` | PLAN / round 3 | `REVIEWER_HTTP` | `COMPLETED`，reported/effective verdict 均为 `PASS` | expected/actual reviewer 为 `grok-reviewer-b`；intake ACK、event APPLY 后 Task 进入 `PLAN_APPROVED` |
| `RR-7ec054b2-679f-4948-8882-ca1a0cedd016` | FINAL / round 1 | `REVIEWER_HTTP` | `COMPLETED`，reported/effective verdict 均为 `PASS` | `grok-reviewer-b` 的合法 Final PASS 经 APPLY 将 Task 推进为 `DONE` |

Task Event 链对应的关键迁移为：

`PLAN_REVIEW_PENDING → PLAN_APPROVED (v10) → EXECUTING (v11) → SELF_TESTING (v12) → FINAL_REVIEW_PENDING (v14) → DONE (v15)`

早期 `TIMED_OUT` 和最终 PASS 不矛盾：新 RR 在 Human 正式 Continue/预算治理后另行创建，旧 RR 始终保留原终态。当前 Task 中保留的 `escalation_reason=REVIEW_TIMEOUT` 是历史故障痕迹，不覆盖 `state=DONE` 与 `completion_basis=FINAL_REVIEW_PASS`。

## 5. Worker 与 Final 守卫

1. 首次 `request_final_review(begin_execution=true)` 按合同先将 Plan-approved Task 推进到 `EXECUTING`，随即因 `Latest Worker assignment must complete before self-test` 被预期守卫拒绝；这是正确的中间结果，不是绕过 Worker 的 Final 失败。
2. Worker assignment `WA-909b7a87-eef1-406a-a9e9-fff5533faa54`（generation 1）依次完成 claim、上传 `EVIDENCE` `ART-d0a601f0-6048-489b-a08a-395578d0c6b3`、`report_progress`、complete。
3. Audit 动作顺序为 `WORKER_ASSIGNMENT_CLAIMED → ARTIFACT_CREATED → WORKER_ASSIGNMENT_PROGRESS → WORKER_ASSIGNMENT_COMPLETED`；完成后 assignment `status=COMPLETED`、`version=3`。complete 不能越过 progress，本次没有越过。
4. Builder 再用 `begin_execution=false` 请求 Final Review，绑定 TEST_RESULT、DIFF 和 Final Package；Final 输入 revision `2`、expected task version `14` 与冻结 hash 均通过 Reviewer 核对。

## 6. GitHub projection：非阻塞诚实项

Final APPLY 原子创建了 projection intent，只读现场为：

- projection：`GHP-50d8c21ef46f3137283daf95ce8714a7c9c3dbaa471b7674b03b4292ba9df716`
- `status=UNKNOWN`
- `binding_id=null`，`comment_id=null`，`attempts=0`
- `recovery_reason=BINDING_OR_PROJECTION_WORKER_REQUIRED`

该 Task 没有 PR binding，因此不得写成 GitHub projection PASS，也不得伪造 binding 或人工补投影。但根据 Hub Source of Truth 与冻结 projection 隔离合同，该 `UNKNOWN` 仅表示展示面未完成，不回滚 Review `COMPLETED` 或 Task `DONE`。

## 7. 核验方法、证据分级与未运行项

| 来源 | 本次用途 | 边界 |
| --- | --- | --- |
| Human 已核定现场 | 正式路径、Manual Glue=0、调用先后与禁止路径未使用 | 作为本报告的授权现场，不由旧测试推翻 |
| `hub.db` SQLite `mode=ro` | Task/RR/Review/Worker/Artifact/Audit/projection 字段 | 只读；无 DML，无人工修状态 |
| 受控 Artifact Store | Plan、DIFF、TEST_RESULT、Worker Evidence、Final Package、Review Result | 只读内容/hash 对应；未修改 Artifact |
| `config/grokbuddy.service.json` | runtimeDir、PublicBase、Reviewer、Supervisor 字段 | 配置核对，未修改 |
| 既有历史报告 | delivery gap、MCP scope hotfix、Supervisor wiring 的时点事实 | 只引用，不改写其当时的 WAITING/LOCAL PASS |

本次实际运行的核验是文档和只读检查：

- `Get-Content -Raw -Encoding UTF8 config/grokbuddy.service.json`
- `sqlite3.connect("file:<absolute hub.db>?mode=ro", uri=True)` 后查询 `tasks`、`review_requests`、`reviews`、`worker_assignments`、`artifacts`、`task_events`、`audit_logs`、`github_comment_projections`
- `Get-Content -Raw -Encoding UTF8` 读取上述内容寻址 Artifact
- 对两份交付文档执行 UTF-8/no-BOM、本地 Markdown 链接、必需 marker 和 `git diff --check` 检查

本轮没有重跑 pytest、Runtime、Hub/WorkBuddy Restart 或新 E2E；6.20 PASS 来自已完成的正式业务运行证据，不来自本次 DOCS 检查。

## 8. Gate、后续可选项与 STOP

| Gate | 结果 |
| --- | --- |
| 同一 Task 的正式 Plan → Worker → Final 链 | PASS |
| 合法 Final Reviewer PASS → Hub APPLY → `DONE` | PASS |
| `completion_basis=FINAL_REVIEW_PASS` | PASS |
| Owner 全程不 transfer | PASS |
| Worker progress/version/scope 守卫 | PASS |
| Manual Glue = 0 / 禁止路径未使用 | PASS |
| GitHub projection | `UNKNOWN` / 非阻塞，未写成 PASS |
| 整个 Phase 6 退出 | **未声明**；6.21/6.22 如未单独完成仍保持 open |

可选后续仅作为独立改进项，不回滚本次核心 E2E PASS：

- 为 Reviewer intake 增强经验证的 webhook 自动 wake，保留受控 poll 与持久化 ACK 去重语义。
- 补充 lease/fencing/失回执对账的运维文档，不改动冻结合同。
- 无 PR binding 的 projection 继续保持诚实 `UNKNOWN`，除非未来经正式流程产生真实 binding；不为本 Task 手工补绑定或补评论。

控制面短同步：[Phase 6 Control Plane Detemporalize Report](PHASE6_CONTROL_PLANE_DETEMPORALIZE_REPORT.md) 仍是 `PHASE6-CONTROL-PLANE-DETEMPORALIZE: LOCAL PASS / DOCS ONLY`。它说明可变基线与历史报告的分层，不是本次 E2E PASS 的替代证据。

本次只新增本报告并刷新 `CURRENT_PRODUCTION_BASELINE.md`。未 commit，未 push，未 Restart Hub/WorkBuddy，未启动新 E2E。到此停止。
