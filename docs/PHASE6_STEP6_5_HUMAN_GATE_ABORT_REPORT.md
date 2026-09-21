PHASE6-STEP6.5-HUMAN-GATE-ABORT: PASS（2026-09-21，Asia/Shanghai）

# Phase 6 Step 6.5 — Human Gate / Abort API + MCP

## 1. 结论与边界

本 Step 已为 Pack B 可写入并冻结的 `PLAN_HUMAN_REVIEW` / `FINAL_HUMAN_REVIEW` 补齐正式 Human Gate 离开边：Accept、Modify、Continue、Abort 全部经 Hub Application Governance，在同一事务内执行认证 principal、`task_id + expected_task_version` CAS、幂等 receipt、状态迁移、审批记录和 Audit。Final Accept 写入 `completion_basis=HUMAN_OVERRIDE` 及 actor/time/reason/related RR；历史 RR、Review 和 Reviewer verdict 保持不变。

Abort 会终止活动 RR、取消未完成 outbox 和本地 mock queue job、取消活动 Worker assignment、停止自动 loop，并显式把 task-scoped GrokBuddy conversation context 标记失效后转 `CANCELLED`。Gate 期间的 Dispatcher、Timeout、Reviewer read/callback、Worker list/claim/upload/progress/complete 均不能推进 Task。

本次仅修改本地工程代码并运行隔离 SQLite/Artifact 测试；没有修改真实 Hub DB/业务 Task，没有直接 DB 业务命令，没有调用真 Grok、WorkBuddy、GitHub，没有 Named Tunnel、部署或常驻 supervisor。`6.5 PASS ≠ 6.6/6.19/6.20 PASS`。

## 2. Preflight 差距与结果

预检依据：6.0 合同 D7–D10、状态矩阵和 Human Gate 表；Pack B 报告 §8；6.2 schema/persistence 报告；`application/governance.py`、review/event/worker/dispatcher、Gateway/MCP 和 Pack B fixture。

| 对象 | 预检已有 | Step 6.5 缺口 | 本步结果 |
| --- | --- | --- | --- |
| Gate 写入 | Pack B 第 2 个 Plan / 第 3 个 Final 非 PASS 可进入专用 Gate，写 `gate_reason`、`automation_frozen=true` | 无正式离开边 | 增加八条 event-labelled Human 边，未通过直接 state 赋值绕过 Domain |
| callback | Gate/freeze/终态 callback 已记 `LATE_EVENT` | 需与其他自动入口一起证明 | 专项测试证明 callback 不改 Task/RR/Finding |
| Dispatcher/Timeout | 旧逻辑只显式识别终态/`ESCALATED` | Gate/freeze 仍可能被 claim 或 timeout 改写 | claim 前和外部返回提交前双重 freeze 守卫；Timeout 在 Gate/freeze 下不推进 |
| Worker | assignment claim/upload/progress/complete 已检查 `EXECUTING` 和 freeze | 缺 Gate 负向组合证据 | list/claim/upload/progress/complete 全部隔离验证拒绝 |
| Governance | 旧 `resume`、`override_review`、`cancel` 已有角色、CAS、幂等基础 | 不认识两个新 Gate；无统一命令、额外预算硬上限和完整 completion metadata | 新增 `human_gate_decide`；保留旧兼容 API；`cancel` 复用新的统一 Abort 清理 |
| MCP/Gateway | 普通 MCP 11 工具，已有 Human `close_task`；Remote MCP 固定五只读工具 | 缺 Gate 治理入口 | 普通治理 MCP 最小新增 `human_gate_decide`；Remote MCP 五工具完全不变 |

## 3. API / MCP 清单

### 3.1 Application Governance

`GovernanceService.human_gate_decide(...)`：

- 必填：`actor_id`、`task_id`、`decision`、`reason`、`expected_version`、幂等 `key`。
- 可选且按 decision 严格解释：`acknowledged_findings`、`modification_scope`、`finding_ids`、`extra_review_budget`、`new_deadline_at`。
- 仅启用的 `Role.HUMAN` principal 可调用；Builder/Reviewer/System 拒绝。
- 只接受 `PLAN_HUMAN_REVIEW` / `FINAL_HUMAN_REVIEW`；错误状态和 stale version 均拒绝，事务不留下业务 mutation。
- 同 actor/operation/key/相同参数返回原 response；同 key 异参数沿用既有冲突规则。

`GovernanceService.cancel(...)` 继续作为任意非终态的认证 Human Cancel；内部复用统一 Abort 清理。它仍由既有 `close_task` Gateway/MCP 暴露，不把取消解释为 Review PASS。

### 3.2 Gateway / MCP

| 工具 | principal | 作用 |
| --- | --- | --- |
| `human_gate_decide` | MCP 启动参数固定的 Human principal，不从工具输入选择身份 | Gate Accept / Modify / Continue / Abort；透传 CAS、幂等和显式 scope/budget/deadline |
| `close_task` | 同一固定 Human principal | 任意非终态 Cancel/Abort；用于活动闭环取消 |

`ClientGateway.TOOL_NAMES` 从 11 增至 12，仅新增上述治理工具。HTTP/CLI 若使用默认 Builder principal 调用该工具仍会被 Application 角色守卫拒绝。Phase 4 Remote MCP 的 `REMOTE_QUERY_NAMES` 和公开五工具仍严格为 `get_task`、`get_task_status`、`get_plan_review`、`get_final_review`、`list_pending_review_requests`；没有扩大 Remote MCP 写面。

## 4. 状态离开边

| Gate / 决策 | Guard 与绑定 | To | 解冻 / 后续 |
| --- | --- | --- | --- |
| Plan Accept | 当前 Plan Artifact/hash 与 latest RR；精确确认全部未关闭 Finding；记录 latest Review risks | `PLAN_APPROVED` | `automation_frozen=false`；冻结 `approved_plan_id/scope/hash`；不伪造 Reviewer PASS |
| Plan Modify | Human 指定结构化 scope 和 Finding IDs；若下一 RR 无额度，必须显式附加预算 | `PLANNING` | 新 Plan 必须在 Human scope 内；`pending_revision_kind=PLAN_REVIEW` |
| Plan Continue | 正数额外 budget、未来 deadline、同一冻结 Plan 仍匹配 | `PLANNING` | 允许创建有限的新 Plan RR；旧 RR 不复活、不重置 round |
| Plan Abort | 当前 Gate、Human reason | `CANCELLED` | 停 RR/outbox/job/assignment/loop；context 失效 |
| Final Accept | latest Final Package、self-test、related RR、全部未关闭 Finding 精确认领；无未解决高风险审批 | `DONE` | `completion_basis=HUMAN_OVERRIDE`，写 actor/time/reason Artifact/related RR；旧 verdict 不改 |
| Final Modify（scope 内） | Human scope 是 approved Plan 子集；指定当前 actionable Finding；下一 Final RR budget 可用 | `EXECUTING` | 解冻并创建下一 generation Worker assignment；assignment 仍冻结完整 approved Plan scope，Task 另存本次 fix scope |
| Final Modify（scope 外） | Human 明确指定越界 scope | `PLANNING` | 清除旧 approved Plan/scope，记录 scope-change request，不创建 Worker assignment；下一步重新 Plan Review |
| Final Continue（package/self-test 仍有效） | 正数额外 Final budget、未来 deadline、latest RR input 仍匹配 | `SELF_TESTING` | 可对同一冻结 package 新建有限 Final RR |
| Final Continue（冻结输入失效） | 同上，但 package/self-test 不再可复用 | `EXECUTING` | 创建受 approved Plan 约束的 rework assignment |
| Final Abort | 当前 Gate、Human reason | `CANCELLED` | 与 Plan Abort 相同 |

未列边仍由 `transition()` 拒绝。Accept/Modify/Continue 离开前会取消任何异常残留的未完成 outbox；不会把旧 RR 从终态复活。

## 5. Extra Review Budget 策略

- 自动默认上限保持合同值：Plan `2`、Final `3`；未修改全局默认语义，也不重置 `review_round`。
- Human budget 只通过显式字段 `extra_review_budget > 0` 增加；每次增加写一条独立 `HUMAN_REVIEW_BUDGET` consumed approval 和 Audit。
- Task 分别累计 `plan_extra_budget` / `final_extra_budget`，同时只增加该 Task 的 `plan_limit` / `final_limit`；不修改 Settings 默认值。
- Settings 提供可配置的累计额外硬上限：默认 Plan 额外最多 `2`、Final 额外最多 `3`，因此默认单 Task 总轮数最多分别为 `4` / `6`。超过硬上限整笔事务拒绝。
- Continue 必须同时给未来 `new_deadline_at`。Modify 只有在当前 limit 尚有未使用轮次时可不加 budget；若已到上限，必须显式给预算，并形成独立预算审批记录。
- 新 RR 仍由原 `ReviewService.request_review` 创建，每个 RR 永久占一个递增的 `review_round`；transport retry 不增加轮次。

## 6. Audit / 持久化字段

| 记录 | 关键字段 |
| --- | --- |
| `command_receipts` | actor、operation=`human_gate_decide`/`cancel`、idempotency digest、input digest、冻结 response、created_at |
| `human_approvals` Gate decision | kind（`PLAN_OVERRIDE` / `FINAL_OVERRIDE` / `HUMAN_GATE_MODIFY` / `HUMAN_GATE_CONTINUE` / `HUMAN_GATE_ABORT` / `CANCEL`）、approver、reason Artifact、decision/consumed time、task scope |
| `human_approvals` budget | `review_type`、related RR、`granted_budget`、`total_extra_budget`、default/new limit、hard extra limit |
| Accept scope | related RR/review、input Artifact/hash、content revision、acknowledged Finding、immutable risk snapshot |
| Modify scope | next review type、structured modification scope、Finding IDs、是否在 approved Plan 内、budget approval ID |
| Continue scope | related RR、budget approval ID、extra budget、new round limit、deadline、是否复用冻结输入 |
| Task completion | `completion_basis=HUMAN_OVERRIDE`、actor、timestamp、reason Artifact、related RR |
| Abort context | `grokbuddy_enabled=false`、context invalidated at/by/reason、`automation_frozen=true`、`gate_reason=TASK_CANCELLED` |
| append-only Audit / task_events | 真实 Human actor、decision action、approval ID、old/new state、related RR |

Reason 正文进入不可变 `EVIDENCE` Artifact；Audit 只保存 pointer/metadata，不保存长文本。没有把 Human decision 放到 GitHub 或从 GitHub 状态反推 Hub 事实。

## 7. Freeze 与 Abort 守卫

- `ReviewService.request_review` 仍只允许 `PLANNING` / `SELF_TESTING`，Gate state 不能自动建新 RR。
- `Dispatcher` 在 claim 前及外部调用返回后同时检查 Gate/freeze；命中的未发送 outbox 转 `CANCELLED`，不调用 Reviewer adapter。
- `TimeoutService` 不把已在专用 Human Gate 的 v2 Task 自动倒退到 legacy `ESCALATED`；Human Continue 必须显式给新 deadline。
- Reviewer `grok_request` 显式拒绝 Gate/freeze；callback handler 保留 `LATE_EVENT` 口径。
- Worker list/claim/upload/progress/complete 都要求 `EXECUTING && !automation_frozen`；Gate 中即使存在异常残留 OFFERED/CLAIMED assignment 也不能推进。
- Abort 取消 active RR（RR 保留真实历史，终止用既有合法 `ESCALATED` status + failure code）、未发送 outbox、本地未完成 mock job、OFFERED/CLAIMED assignment；SENT/DONE 历史不重写。
- Task 转 `CANCELLED` 后 conversation 唯一活动索引释放；`get_conversation_context` 返回 disabled，新普通消息仍须重新满足 6.1 当前轮触发证据，不能继承 sticky context。

## 8. 隔离用例

新增 `tests/test_phase6_human_gate_abort.py`，共 10 个本地隔离 case：

| 用例 | 关键断言 |
| --- | --- |
| Plan Accept | `PLAN_APPROVED`、Plan/hash/scope 绑定、Review 不变、CAS stale/非法 state/非 Human 拒绝、幂等 replay |
| Plan Continue | 额外 1 轮、累计/硬上限 Audit、第 3 个 RR 占 round 3；超硬上限拒绝 |
| Plan Modify | 无可用轮次且无显式 budget 拒绝；Human scope 持久化；新 Plan 越界拒绝 |
| Final Accept | `DONE/HUMAN_OVERRIDE`、actor/time/reason/related RR、Reviewer `NEEDS_CHANGES` 不改、context 失效 |
| Final Continue + scope 内 Modify | Final round 4；或 `EXECUTING` + 新 assignment + fix scope |
| Final scope 外 Modify | 回 `PLANNING`、清旧 approved scope、无新 assignment |
| Plan Abort via MCP | 固定 Human principal、`CANCELLED`、conversation disabled、下一条普通消息无 Task side effect |
| Final Abort | 未发送 outbox 取消，dispatcher/timeout 均不推进 |
| Gate freeze negatives | dispatch、Worker list/claim/upload/progress/complete、callback、timeout 全部不推进 |
| Active-loop close_task | 非 Gate `EXECUTING` 的 live assignment 被 Cancel，Task/context 终止 |

所有测试使用 `tmp_path` 隔离数据库/Artifact Store；autouse fixture 禁止网络。没有用 sleep 模拟业务成功，也没有运行真实 provider。

## 9. 与 6.0 D8/D9/D10 对齐

- D8：两个专用 Gate 是本命令唯一正常入口；Gate 冻结 Reviewer/Worker/dispatch；旧 `ESCALATED/BLOCKED` 兼容 API未改成 v2 正常 Gate。
- D7：默认 Plan 2 / Final 3 保持；Human Continue 只增加显式、逐 Task、可审计且有硬上限的额外预算；历史 round 不重置。
- D9：只有 Final Accept 写 `DONE/HUMAN_OVERRIDE`；Plan Accept 仅到 `PLAN_APPROVED`；旧 Review/verdict 永不改成 PASS。
- D10：Final Modify 在 approved scope 内才进入执行；越界明确回 `PLANNING` 并重新走 Plan Review，不以 Final Fix 偷扩范围。
- D3：`DONE/CANCELLED` 显式失效 task-scoped conversation context；普通消息不会继承 GrokBuddy 开关。
- Forbidden Paths：所有 Human 写入均经 Application Governance；没有直接数据库治理入口，没有以 GitHub 参与裁决。

## 10. 修改文件

- Domain / policy：`src/grokbuddy/domain/model.py`、`src/grokbuddy/domain/rules.py`
- Application：`src/grokbuddy/application/governance.py`、`tasks.py`、`workers.py`、`grok_routing.py`
- Gateway / MCP：`src/grokbuddy/interfaces/gateway.py`、`mcp.py`
- 测试：新增 `tests/test_phase6_human_gate_abort.py`；调整 `tests/test_phase2_interfaces.py`、`test_phase4_remote_mcp.py` 的精确工具面断言
- 报告：本文件

未修改 schema：新增 Task budget/completion/context metadata 继续存于现有 JSON record；Human decision/budget 复用现有 `human_approvals`、`approval_events`、Audit 和 command receipt，没有建立第二事实源。

## 11. 验证命令与结果

| 命令 | 结果 |
| --- | --- |
| `.\.venv\Scripts\python.exe -m compileall -q src\grokbuddy tests\test_phase6_human_gate_abort.py` | PASS |
| `.\.venv\Scripts\python.exe -m pytest -q tests\test_phase6_human_gate_abort.py` | 10 passed |
| 6.5 + Pack B + Trigger + Governance + Workers + Phase 2 + Grok Adapter 核心组合 | 79 passed |
| Remote MCP 边界 + 6.5 + Phase 2 工具面复核 | 12 passed |
| `.\.venv\Scripts\python.exe -m pytest -q` | 767 passed in 162.84s |

首次全量回归为 766 passed、1 failed；失败仅是 `test_phase4_remote_mcp.py` 仍断言旧的普通 MCP 11 工具列表。更新为 12 工具并同时把 `human_gate_decide` 加入 Remote MCP 禁止写工具反例后，最终全量 767 passed。Remote 五工具列表本身从未改变。

## 12. NOT WIRED / 停止点

- **6.6 NOT WIRED**：无常驻 supervisor、auto-start、启动恢复循环、自动 Reviewer intake、自动 timeout→专用 Gate 编排、自动 projection reconcile、assignment lease recovery 或健康指标。
- 未做 Named Tunnel、稳定公网配置、真 Grok/WorkBuddy/GitHub E2E、生产 secret/token 验证、部署或真实业务 Hub DB 迁移。
- Codex 仅完成工程与隔离验证，不是正式 runtime。
- `6.5 PASS` 不代表 `6.6`、`6.19`、`6.20` 已通过。

至此达到 Step 6.5 Exit，按 Stop Condition 停止，等待 Human/指导审阅；不进入 6.6。
