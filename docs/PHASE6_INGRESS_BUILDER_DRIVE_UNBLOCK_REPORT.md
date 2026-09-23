PHASE6-INGRESS-BUILDER-DRIVE: LOCAL PASS / WAITING HUMAN RETEST

# Phase 6 — Unblock NEW→PLANNING after WorkBuddy ingress

日期：2026-09-22（Asia/Shanghai）
范围：只解除 6.20 真机中 ingress-owned Task 的 Hub Builder 驱动阻断；不代跑 WorkBuddy，不改变 owner，不放宽点火，不恢复 legacy Worker owner-transfer，不使用 Manual Glue。

## 1. 结论

现场失败与当前代码一致：`TaskService.create_task` 把专用点火 principal `workbuddy-ingress` 写入 `Task.owner_id`；而 `application/common.py::task_for()` 对任何 Builder command 都要求 `task.owner_id == actor.id`。因此固定为普通 `builder` 的 `grokbuddy-hub` 无法把同一 Task 从 `NEW` 推到 `PLANNING`。Worker 对无 v2 assignment 的 `NEW` Task 返回 `Legacy owner-transfer Worker path is test-only` 也是预期守卫，不应作为替代路径打开。

本轮在 Application 权限边界增加“ingress 创建者 / Hub 驱动者”分离：默认 allowlist 中的普通 `builder` 可驱动满足完整 trigger/v2 anchors 的 ingress Task；`owner_id` 全程仍为 `workbuddy-ingress`。没有 schema 迁移、Task owner CAS/DML、第二 assignment 表或额外事实源。

仓内隔离正反例和相关 Pack B/Supervisor 回归已通过。真实 `TASK-ef7d3c8e-df7d-47d9-b9d4-cfe8ce3a4c84`、正式 SoT、WorkBuddy、Grok、GitHub 与公网均未由 Codex 调用；所以本报告停止在 `LOCAL PASS / WAITING HUMAN RETEST`，不宣称 6.20 PASS。

## 2. 差距与设计决策

| 面 | 修改前差距 | 本轮设计 | 保持不变的边界 |
| --- | --- | --- | --- |
| Task ownership | ingress 是合法创建者，但 owner equality 阻止 Hub Builder 后续命令 | owner 继续表示创建者；另以进程组合配置 `ingress_driver_actor_ids` 判定驱动主体 | 不修改、不转移 `Task.owner_id` |
| 驱动授权 | 只看 `owner_id == actor.id` | 默认仅 `builder`，且必须是无 Worker/trigger 标记的普通 Builder；Task 必须是 owner=`workbuddy-ingress`、grokbuddy enabled、v2、conversation/message/evidence/source anchors 一致 | 非 ingress Task 仍走原 owner equality；无关 Builder、Reviewer、未 claim Worker 均拒绝 |
| 点火 | 已由 dedicated ingress + signed evidence 创建 | 未改 `create_task`；驱动授权只在查找既有 Task 时生效 | 非 ingress create 继续 fail closed；不删除 trigger 双检 |
| Worker | `NEW` Task 没有 assignment，legacy claim 正确拒绝 | Plan PASS 后由 Hub Builder 执行正式 `execute`，同事务创建 v2 assignment；Worker 再按 assignment claim | legacy `NEW + owner transfer` 仍只在显式 test mode 可用 |
| Supervisor/outbox | dispatch/intake/event 不依赖 owner，但此前到不了 Plan RR | 本地全链验证 builder 可建 Plan RR，Supervisor APPLY Plan PASS；后续同 Task Final PASS→DONE | 不增加 `*_once`、人工 resume、同步 review 或伪造 verdict |
| SoT/runtime | 正式 SoT 已是 `var/github-manual` | 只修改仓内 Application/runtime composition；不读写正式 DB | PublicBase、RuntimeDir、Secret 均不变 |

`_can_drive_ingress_task()` 使用 Task 内已经持久化的签名入口锚点，不使用 conversation 的历史“已启用”记忆，因此不会形成 sticky reuse。实际状态、Review、assignment、Audit、receipt 仍只写 Collaboration Hub。

## 3. 本地验证路径

新增隔离用例使用临时 SQLite/Artifact Store，完整覆盖：

1. `workbuddy-ingress` 以真实本地签名 evidence 创建 v2 Task，初始 `NEW`、owner 保持 ingress。
2. 无 v2 assignment 时，`workbuddy-worker.claim_task` 继续返回 `Legacy owner-transfer Worker path is test-only`。
3. 默认驱动 `builder` 通过原 `ClientGateway` 上传 Plan、执行 `submit_plan` 和 `request_plan_review`；Supervisor dispatch/intake/APPLY 后 Task 为 `PLAN_APPROVED`。
4. 同一 `builder` 执行正式 `execute`；同事务产生 generation 1 `worker_assignments`。Worker 通过 assignment claim、上传 evidence、progress、complete；Task 仍为 `EXECUTING`，owner 未变。
5. `builder` 上传测试与 diff，提交 Final package/request；Supervisor APPLY Final PASS 后同一 Task 为 `DONE`，`completion_basis=FINAL_REVIEW_PASS`，owner 仍为 ingress。
6. 另测无关 Builder、Reviewer、未 claim Worker 均拒绝；普通 legacy/v1 Task 的 owner Builder 成功、其他 Builder 仍拒绝。

测试没有使用真实 WorkBuddy、真实 Reviewer、GitHub、PublicBase、正式 DB、手工 once worker 或人工 resume。

## 4. 修改文件

- `src/grokbuddy/application/common.py`：新增严格 ingress Task driving predicate，并在既有 `task_for()` owner guard 中使用。
- `src/grokbuddy/infrastructure/runtime.py`：增加进程组合级 `ingress_driver_actor_ids`；默认仅 `builder`，并固定 ingress owner principal 为 `workbuddy-ingress`。
- `tests/test_phase6_ingress_builder_drive.py`：新增正向同 Task 全链、主体拒绝、普通 Task owner 回归和 legacy/v2 Worker 边界。
- `docs/WORKBUDDY_INTEGRATION.md`：记录 6.20 首次阻断、修复后的身份语义和 Human evidence boundary。
- 本报告。

本轮没有修改 schema、Domain 状态机、Review 合同、ingress MCP、worker MCP、PublicBase/RuntimeDir 配置或任何 Secret。

## 5. 验证结果

| 命令 | 结果 |
| --- | --- |
| `.\.venv\Scripts\python.exe -m pytest -q tests\test_phase6_ingress_builder_drive.py tests\test_phase6_pack_b.py tests\test_phase6_supervisor_recovery.py` | `27 passed in 29.48s` |
| `.\.venv\Scripts\python.exe -m pytest -q` | `791 passed in 164.23s`（最终代码态复跑） |
| `.\.venv\Scripts\python.exe -m compileall -q src\grokbuddy tests\test_phase6_ingress_builder_drive.py` | PASS |
| 严格 UTF-8 / no BOM / no trailing whitespace（本轮 5 文件） | PASS |
| `git diff --check` | PASS；仅输出工作区既有 LF→CRLF 提示，无 whitespace error |

这里的 PASS 仅证明本地 Application、Mock Supervisor 和 SQLite 隔离路径；不证明 WorkBuddy 会在真实对话选择正确工具，不证明真实 Grok/GitHub 回传，也不证明 6.20 完成。

## 6. Human 6.20 重测

1. 若 `TASK-ef7d3c8e-df7d-47d9-b9d4-cfe8ce3a4c84` 仍为 `NEW` 且未 Abort，在原 WorkBuddy conversation 发送短句继续；若选择 Abort，则重新发送包含精确 `启用grokbuddy流程` 的新用户消息建单，再用短句推进。
2. 期望普通 `grokbuddy-hub` 的 `builder` 调用 `submit_plan` 时不再出现 `Task belongs to another Builder`；Task owner 始终为 `workbuddy-ingress`。
3. 期望同 Task 依次出现 Plan Artifact/`PLAN_REVIEW` RR；Plan PASS 后出现 v2 `worker_assignments`，Worker 使用 assignment claim；随后出现 Final package/`FINAL_REVIEW` RR，合法 Final PASS 才能 `DONE`。
4. 以正式 SoT `var/github-manual/hub.db` 的 Task、ReviewRequest、worker assignment、Artifact 与 Audit 为证。不要以聊天文本、PR 状态或工具返回摘要替代 Hub 证据。
5. 如任一步仍失败，保留非 Secret 的 error code、Task state/version/owner/active RR、相关 Audit 与 assignment 摘要；不要通过修改 owner、开启 legacy worker、`*_once` 或人工 resume 绕过。

Human 重测前：**6.20 NOT PASS**。本轮到 `LOCAL PASS / WAITING HUMAN RETEST` 即 STOP。
