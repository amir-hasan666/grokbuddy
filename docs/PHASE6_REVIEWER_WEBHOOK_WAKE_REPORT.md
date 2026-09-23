PHASE6-REVIEWER-WEBHOOK-WAKE: HUMAN RETEST PASS

# Phase 6 Reviewer Webhook Wake Report

日期：2026-09-22（Asia/Shanghai）

## 1. 结论与证据边界

本步已在仓内实现可选的 Grok Bot Reviewer webhook wake：正式 Supervisor 只有在 `REVIEWER_HTTP` outbox 已持久化为 `SENT`，并且同一 RR 的认证 HTTP intake 已为 `READY`（可由 B 拉取）时，才执行轻量 HTTPS POST。wake 只负责叫醒 Reviewer routine；B 仍必须通过既有 `GET /reviewer/requests` 读取冻结请求，并通过 `POST /reviewer/events` 回传认证事件。

结论为 **HUMAN RETEST PASS**。仓内实现阶段的本地隔离验证之后，Human 已完成受保护配置、正式 Hub restart、poller 暂停窗口和一条新的零胶水实弹任务；Hub 权威库 `var/github-manual/hub.db` 记录了两轮 webhook wake、Reviewer HTTP intake、认证 Reviewer verdict 与 Task 状态迁移。该结论只关闭 Reviewer webhook wake 的 Human 配置与复测 Gate。因此：

- 不等于 6.20 PASS；
- 不改写会话 A 的 6.20 证据；
- 已证明在本次隔离窗口中，webhook 可在 poller 暂停时单独叫醒真实 Reviewer，并完成 ACK 与 Plan/Final verdict；
- 不等于 Phase 6 退出。

## 2. 配置与 Secret 边界

`config/grokbuddy.service.json` 新增三个非敏感字段：

| 字段 | 仓内默认 | 作用 |
| --- | --- | --- |
| `reviewerWakeWebhookUrlEnv` | 空字符串 | URL 所在 Process 环境变量名；空表示关闭 |
| `reviewerWakeWebhookKeyEnv` | 空字符串 | sender key 所在 Process 环境变量名；必须与 URL 字段同时配置 |
| `reviewerWakeMaxAttempts` | `3` | 每个 RR 的 wake 尝试上限，允许 `1`–`5` |

Windows launcher 只在两个环境变量名同时启用时读取下列当前用户 Generic Credential：

- `GrokBuddy/REVIEWER_WAKE_WEBHOOK_URL`
- `GrokBuddy/REVIEWER_WAKE_WEBHOOK_KEY`

值只注入 Hub 子进程的 Process 环境。仓库、命令行、日志、Audit 与本报告都不保存 URL/key 值或 hash。可选配置不完整、环境变量名与现有 Secret 冲突、URL 非 HTTPS、sender key 为空或与现有凭据复用时均 fail closed。

POST body 仅包含固定事件名和 `review_request_id`；sender key 只进入 HTTPS `Authorization` header，稳定去重键进入 `Idempotency-Key` header。transport 禁止 redirect，防止向重定向目标转发 sender key；响应正文有 4 KiB 上限且不写日志/Audit。

## 3. 实现与事务边界

正式顺序为：

1. 既有 dispatcher 把冻结 RR 发布到 `grok-reviewer-http` intake；
2. dispatcher 在独立短事务中把 Hub outbox 置为 `SENT`；
3. Supervisor 在 `intake` 之后运行可选 `reviewer_wake` worker；
4. wake worker 同时核对 `REVIEWER_HTTP`、正式 Reviewer actor、当前有效 route、`SENT` outbox 与 `READY` intake；
5. worker 在短事务中创建/claim 独立 `source=grok-reviewer-webhook-wake` 的持久收据，随后在数据库事务外 POST；
6. 成功置 wake 收据为 `ACKED`；可重试失败使用同一去重键并受最大尝试数限制；明确拒绝或耗尽置为 `FAILED`。

同一 RR 成功后不会再次 POST。进程在远端接受后、本地写收据前崩溃时，过期 lease 可用同一 `Idempotency-Key` 恢复；这避免无界狂轰，但外部 webhook 是否实际按该 header 去重仍属于 Human 环境验证项。

wake 失败域与 Hub 业务状态分离：worker 不更新 Review Request、Task 或主 outbox，不调用 review failure gate，也不把 transport failure 抛成 Supervisor fatal error。已 `SENT` 的 outbox 保持 `SENT`，Task 继续等待认证 Reviewer event。

## 4. 变更文件

| 文件 | 变更 |
| --- | --- |
| `src/grokbuddy/adapters/reviewer_wake.py` | 新增 HTTPS、禁止重定向、响应有界且错误码无 Secret 的 wake transport |
| `src/grokbuddy/application/workers.py` | 新增持久去重/lease/有限重试的 wake worker，并接入 Supervisor 独立失败域 |
| `src/grokbuddy/infrastructure/runtime.py` | 增加 wake worker 构造与可选 Supervisor 注入 |
| `scripts/grokbuddy_composite.py` | 从命名环境变量解析可选受保护配置，校验独立 Secret，并接入 production Supervisor |
| `scripts/windows/Start-GrokBuddyHub.ps1` | 从两个固定 Credential Target 读取并仅注入 Process 环境；默认关闭 |
| `scripts/windows/Test-GrokBuddyCredentialStore.ps1` | wake 启用时只读检查两个可选 Target 是否 `PRESENT` |
| `config/grokbuddy.service.json` | 新增默认关闭的非敏感 wake 配置 |
| `tests/test_phase6_reviewer_webhook_wake.py` | 覆盖成功顺序、缺配置、fail closed、去重、有限重试、失败隔离、body/header 与 launcher 边界 |
| `docs/PHASE6_OPERATIONS_RUNBOOK.md` | 增加 URL/key 配置、poller 并存及 Human 隔离复测步骤 |
| `docs/PHASE6_REVIEWER_WEBHOOK_WAKE_REPORT.md` | 本报告 |

本步未创建或修改 `docs/CURRENT_PRODUCTION_BASELINE.md`、`docs/PHASE6_STEP6_20_REAL_FINAL_E2E_REPORT.md`，也未改写任何既有 `PHASE6_*` 历史报告正文。

## 5. 本地验证

| 命令 | 结果 | 证据范围 |
| --- | --- | --- |
| `.\.venv-phase0\Scripts\python.exe -m pytest -q tests/test_phase6_reviewer_webhook_wake.py tests/test_phase6_supervisor_production_wiring.py` | `18 passed in 7.53s` | wake 专项与既有 production Supervisor 接线回归；无外网 |
| `.\.venv-phase0\Scripts\python.exe -m pytest -q tests/test_phase6_reviewer_webhook_wake.py tests/test_phase6_supervisor_production_wiring.py tests/test_phase6_supervisor_recovery.py tests/test_rules.py` | `614 passed in 20.37s` | recovery、状态/依赖边界与专项回归；无外网 |
| `.\.venv-phase0\Scripts\python.exe -m pytest -q` | `811 passed in 165.66s` | 最终工作区全量本地回归；无外网 |
| PowerShell AST parse：`Start-GrokBuddyHub.ps1`、`Test-GrokBuddyCredentialStore.ps1` | PASS | 仅脚本语法，不读取 Credential |
| `ConvertFrom-Json` 解析 `config/grokbuddy.service.json` | PASS | JSON 语法 |
| `.\.venv-phase0\Scripts\python.exe -m compileall -q src scripts tests/test_phase6_reviewer_webhook_wake.py` | PASS | Python 语法/导入编译 |
| `git diff --check` | PASS | whitespace 检查；工作区另有并行会话的既有改动，本步未清理或覆盖 |

专项可观察断言包括：POST 执行当下 outbox 已为 `SENT` 且 intake 为 `READY`；第二轮 Supervisor 不重复发送；可重试失败在固定上限停止且复用同一去重键；非重试失败后 RR 仍 `PENDING`、Task 仍 `PLAN_REVIEW_PENDING`、主 outbox 仍 `SENT`；缺配置时没有 wake worker 或 wake 收据。

这些结果本身仍只是本地 SQLite/fake transport 证据；第 6 节记录的后续 Human 实弹复测才证明当前账号 routine、正式 Hub、真实网络与 Reviewer wake 成功路径。外部 webhook 对 `Idempotency-Key` 的重复投递语义仍未通过故障注入单独验证。

## 6. Human Retest Evidence

### 6.1 正式配置与运行窗口

Human 运行态证据记录：

- 当前正式 Hub 计划任务用户的 Windows Credential Manager Target `GrokBuddy/REVIEWER_WAKE_WEBHOOK_URL` 与 `GrokBuddy/REVIEWER_WAKE_WEBHOOK_KEY` 均为 `PRESENT`；本报告不读取、不记录其值。
- `config/grokbuddy.service.json` 的 `reviewerWakeWebhookUrlEnv` / `reviewerWakeWebhookKeyEnv` 配置为环境变量名 `GROKBUDDY_REVIEWER_WAKE_WEBHOOK_URL` / `GROKBUDDY_REVIEWER_WAKE_WEBHOOK_KEY`，不是 Credential Manager 路径或 Secret 值。
- 约在 2026-09-22 19:16（Asia/Shanghai），Human 执行 `Restart-GrokBuddyHubTask.ps1` 与 `Test-GrokBuddyRuntime.ps1`；本机/公网探针为 `200 / 200 / 404`，readiness 中 `supervisor=ok`。
- 验证期间 `grokbuddy-review-poller` 已暂停，webhook routine `GrokBuddy Reviewer Webhook` 已启用。poller 未被删除，仍可作为兼容与恢复兜底；本次复测证明 webhook 在 poller 暂停时可以单独叫醒 Reviewer。

### 6.2 Hub 权威库证据

Human 创建了不同于 6.20 `TASK-702...` 的新任务 `TASK-7d7fb65b-41b3-4d7f-bff6-f33ff1f8fa5d`。`var/github-manual/hub.db` 的只读核对覆盖 2026-09-22 19:18:06–19:29:31（Asia/Shanghai），结果如下：

| 阶段 | Hub 证据 |
| --- | --- |
| Plan | `RR-a3f14dcb-e4d8-41d8-92e3-5694b801c47e` 为 `COMPLETED / PASS`；`REVIEWER_HTTP` outbox `OUT-3f5fcc51-a981-45d8-8af7-5c534cfd693e` 为 `SENT`；wake 收据 `INT-805e7625f6cc76654710cc23525e0f9bb53ef9f7455f83fecd21e8bb7435ab82` 的 `source=grok-reviewer-webhook-wake`、`status=ACKED`；HTTP intake `INT-dfedfb59a7ffc7eac5d56a15298cb3fa1be34fc6410666fe22b0adb340b87eb5` 的 `source=grok-reviewer-http`、`status=ACKED`；Task 随后进入 `PLAN_APPROVED`。 |
| Final | `RR-5a7220c7-f116-4065-8751-c035868591bb` 为 `COMPLETED / PASS`；`REVIEWER_HTTP` outbox `OUT-ea93b40b-d52e-497b-aaed-1be020e4768b` 为 `SENT`；wake 收据 `INT-587d9e7cfc13753d8cda5c6205ac737e63487f9f837a620cd844df0272f70627` 的 `source=grok-reviewer-webhook-wake`、`status=ACKED`；HTTP intake `INT-2d516c74b96956e54da91bf7b2f7ca79cf66e672aeeea98c6e60d7ec482a5067` 的 `source=grok-reviewer-http`、`status=ACKED`；Task 最终为 `DONE / v9 / completion_basis=FINAL_REVIEW_PASS`。 |
| Reviewer | 两轮结果的 `reviewer_actor_id=grok-reviewer-b`，`execution_identity.server_id=3504754`；Human 现场身份为 `workbuddy审核员`。 |

时间点进一步对应：Plan wake 于 19:19:09 ACK、Reviewer intake 于 19:19:32 ACK、Task 于 19:20:20 进入 `PLAN_APPROVED`；Final wake 于 19:25:40 ACK、Reviewer intake 于 19:26:19 ACK、Task 于 19:29:31 进入 `DONE`。这证明的不只是 webhook transport 接受，而是 Reviewer 随后认证拉取、回传并由 Hub APPLY。

### 6.3 零胶水与失败边界

Human 确认本次成功路径没有手动 POST webhook、没有手动运行 poller、没有使用 `run_until_idle`、mock、`LocalRuntime`、`*_once` 或临时 resume glue；Builder 经 `grokbuddy-hub` MCP，Worker 仅在 Task 已进入 `EXECUTING` 且 assignment 已产生后使用。Hub 库中的 Worker assignment `WA-915512bb-2546-4f47-848d-0d5a323cf7dd` 为 `COMPLETED`，对应 Task 先由 `PLAN_APPROVED` 迁移到 `EXECUTING`。

wake 仍是可选能力：两个环境变量名留空即可关闭，默认/未启用路径不读取可选 Credential。wake 失败只影响独立 wake 收据，不得回滚已经 `SENT` 的 Review outbox，不得失败 Task，也不得伪造 Reviewer verdict；poller 可继续作为兜底。本次 PASS 只证明已配置环境中的 webhook 单独叫醒成功路径，不放宽上述失败隔离和 fail-closed 边界。

### 6.4 收口清单

- [x] CONFIG：两个 Credential Target 为 `PRESENT`，service config 仅保存对应环境变量名。
- [x] RESTART / HEALTH：正式 Hub 已重启，本机/公网 `200 / 200 / 404`，`supervisor=ok`。
- [x] RETEST：poller 暂停窗口内，两轮 wake 与 HTTP intake 均 `ACKED`，Plan/Final 均由真实 Reviewer PASS。
- [x] ZERO GLUE：未使用手动 webhook/poller/once/mock/LocalRuntime/resume glue。

## 7. 停止点

Reviewer webhook wake 的仓内实现、本地隔离测试、Human 配置与实弹复测均已完成，状态收口为 `HUMAN RETEST PASS`。本次文档收口不改写 6.20，不启动或扩大到 6.21/6.22，不修改生产代码、service config、Credential Manager 或任何 skill，也不 push。
