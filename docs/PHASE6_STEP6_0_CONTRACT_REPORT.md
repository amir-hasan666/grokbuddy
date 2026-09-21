# PHASE6_STEP6_0_CONTRACT_REPORT

日期：2026-09-21（Asia/Shanghai）  
范围：Phase 6 Step 6.0 — Freeze Production Contract。本文冻结目标合同并审查当前实现；不代表 Phase 6 功能或生产 Gate 已通过。到此停止，不进入 Step 6.0a 的实现或 Step 6.1。

## 0. 阶段边界、证据与结论

目标 runtime 是 **User → WorkBuddy → GrokBuddy Hub → Grok Reviewer / GrokBot → GitHub projection**。Codex 仅建设项目，不是业务 runtime。Hub DB 是唯一事实源。生产业务数据不得经人工聊天复制，也不得靠 CLI/临时脚本串联。

本轮只读审查了 `src/grokbuddy/domain/{model,rules}.py`、`application/{tasks,reviews,events,governance,worker_tasks,workers,github}.py`、`interfaces/{gateway,mcp,remote_mcp,worker_mcp,grok_reviewer}.py`、`adapters/{schema,grok_bot}.py`、协议 schema、Phase 5 报告和两个本机探针库。实际项目根 `D:\Codex\grokbuddy` 不含 `.git`；嵌套 checkout `var/phase35-repo` 当前为 `phase4-step6-probe`，工作树无修改。本轮没有修改该 checkout、`main`、Hub DB 或真实 Task。

本机只读库核对：Worker 探针 Task `TASK-1c7dc9a4-0d88-46d6-b9a4-c7f7068447a7` 仍为主状态 `NEW`、`worker_status=COMPLETED`、version 4；独立 Final 探针 Task `TASK-588a15cb-8075-4c27-9095-744e2a32ff1b` 为 `DONE`、version 19，第 3 轮 Final RR `COMPLETED`，Review `PASS`，ingress `APPLIED`，projection `SENT`。参见 [Phase 5 Functional Exit](PHASE5_FUNCTIONAL_EXIT_EVIDENCE_REPORT.md)。该试跑经人工 `dispatch-once`、`event-once`、`project-github-once` 和 Quick Tunnel，不是生产自动化证据。

**Step 6.0 合同判定：PASS；Phase 6 runtime/readiness：NOT RUN。** 以下 D1–D12 是冻结的实现决策；现有实现差距列于第 2 节，不因旧测试通过而视作已实现。后续若更改这些边，须修订本合同及对应反例测试，不能暗中扩大已批准 Plan。

## 1. 冻结决策

| ID | Production Contract |
| --- | --- |
| D1 Trigger | `grokbuddy_enabled=false` 为每个新请求的默认值。仅当前轮用户主自然语言正文中逐字出现 `启用grokbuddy流程` 才能激活本 task；代码块、引用、附件/粘贴文档、工具输出及旧对话不参与匹配。当前附上的本合同文本不是触发请求。 |
| D2 Evidence | WorkBuddy 以已认证的专用 principal 传入当前用户消息的不可变消息 ID、conversation ID、正文/分段来源、UTF-8 hash、触发词起止 offset、当前轮 ID 和签发时间。Hub 按可信原文/分段重新核对字面匹配与来源，冻结 `trigger_evidence`；只有调用方自述的布尔值、片段或旧消息一律拒绝。无法取得可信当前消息来源时 fail closed。 |
| D3 Context | `grokbuddy_enabled` 与活动 task_id 只在该 WorkBuddy conversation 的 task-scoped context 生效。Hub 在创建事务内强制同一 conversation 至多一个非终态 GrokBuddy Task；Plan/Fix/Re-review 只能继承同一 task_id。`DONE/CANCELLED/FAILED`（本合同中 `CANCELLED` 即正式用户 Abort 终态）时失效；新普通请求重新执行 D1，不继承旧开关。 |
| D4 SoT | Task、Plan、RR、review_result、Finding、Artifact、Verdict、两个 round 计数、Audit/event 只以 Hub 持久化结果为准。Review result 的原文 Artifact/hash 和 Review 行不可变；Finding 当前状态通过 append-only finding events 演进。GitHub 仅展示/审计投影。 |
| D5 Protocol | Phase 6 新建 RR 使用版本化 v2 Review Result；已有 v1 历史保持原样。Plan 与 Final 的 `NEEDS_CHANGES` 都必须带非空、机器可执行的 `findings[]`（新 finding 或引用当前未关闭 finding），每项有稳定 Hub finding_id（新项由 Hub APPLY 时生成）、描述、证据/上下文、整改建议、scope 与状态。无 actionable 项则拒绝 APPLY，RR/Task 不推进；无效事件记 `VALIDATION_FAILURE`。Plan PASS 须把此前 Plan finding 逐项验证关闭或取得 Human waiver，不能默默遗留 OPEN。Plan v1 `risks[]/suggestions[]` 不自动冒充 v2 finding。 |
| D6 Callback | 专用 Reviewer 身份/token 验证在 ingress；APPLY 再以同一事务核对 reviewer actor、RR ID、task ID、review ID、correlation=RR ID、idempotency key、冻结 input/profile hash、content revision、RR 当前状态及 task expected version。Reviewer 从 Hub 受控读取当前 expected state/version；重复事件须先查相同 key/hash 的既有收据，再做版本守卫。无合法 active RR 无法推进 Task。Outbox lease 只属于 Hub dispatcher，Reviewer 不持有 lease。 |
| D7 Rounds | `review_round` 是每个类型的 RR 创建次数，创建新 PLAN/FINAL RR 时各自 `+1` 并永久占位；自动 Plan 上限 2、自动 Final 默认上限 3，来自统一 Settings/policy 快照。`revision_round` 是有效 `NEEDS_CHANGES` 后 Builder 提交新 Plan/Final 修订的次数；timeout、dispatch retry、重复回调不增加它。`retry_dispatch` 只复用同一仍有效 RR/delivery key，绝不创建 RR；deadline/策略耗尽进入对应 Human Gate。Human Continue 超出默认上限须逐次显式授权额外预算，不能改变 Settings 默认值或重置历史编号。 |
| D8 Human Gate | 新增 `PLAN_HUMAN_REVIEW`、`FINAL_HUMAN_REVIEW`。Plan 第 2 轮未 PASS、Final 第 3 轮未 PASS、同阶段不可恢复超时/投递失败、需要人工裁决的 BLOCK，进入对应 Gate，冻结 Worker/Reviewer 自动推进和新 dispatch。高风险动作专用 `AWAITING_HUMAN_APPROVAL` 继续独立存在。旧 `ESCALATED/BLOCKED` 为历史兼容状态，不作为 v2 Review Gate 的正常目标。 |
| D9 Completion | 自动 `DONE` 仅可由有效 Final PASS 且所有 Finding 关闭、自检/冻结包仍匹配、无待审批高风险动作产生，写 `completion_basis=FINAL_REVIEW_PASS`。Human 在 Final 未 PASS 时 Accept 可到 `DONE`，写 `completion_basis=HUMAN_OVERRIDE`、reason、actor、timestamp、related RR；历史 Review/RR 原 verdict 永不改为 PASS。Worker `complete_task` 只关闭 Worker 子生命周期。 |
| D10 Scope | Final Fix 仅针对最新有效 Final Review 所冻结的 actionable finding 集合；修复证据逐项关联 ID。发现超出 approved Plan 的必要改动时冻结 Final 自动循环，走 Plan Change → Plan Review（新 Plan revision/RR），不得以 Final Fix 偷扩范围。 |
| D11 Production | Phase 6 Real Final E2E 禁用 Quick Tunnel。6.20 前必须具备 Named Tunnel、稳定 PublicBase/Hub endpoint、稳定 Worker/Reviewer MCP 配置、自动 Reviewer intake、service/supervisor auto-start、可恢复 outbox/event/projection、token/secret runbook、health/observability；6.19 未 PASS 时不可启动 6.20。 |
| D12 Manual Glue | 正式 E2E 的人工 `dispatch-once`、`event-once`、`project-github-once`、复制 Quick Tunnel hostname/Grok finding、临时 `resume .py`、`bind-pr`/`route-task`、点击 Test Run 促使 Reviewer 接单均须为 **0 次**。CLI 仅供 debug，不能构成成功路径。 |

## 2. 当前能力与合同逐条差距

| 合同 | 当前可核对能力 | 缺口及落点 |
| --- | --- | --- |
| D1–D3 Trigger | `TaskService.create_task` 和 `ClientGateway._create_task` 仅接 description、profile、idempotency；Worker MCP 可以领取 offered task。 | 无 WorkBuddy 当前轮语义解析、可信 message provenance、`trigger_evidence`、conversation 活动 Task 唯一约束及终态清理。落点：WorkBuddy adapter、`create_task` Application 守卫、tasks schema/唯一索引、MCP 请求。既有本地 fixture 可用显式 test mode，生产入口必须 fail closed。 |
| D4 SoT | `reviews`、`review_findings`、Artifact、Audit、RR 与任务事件已持久化；`get_plan_review`/`get_final_review` 可查询。 | 缺少正式 `list_actionable_findings` 查询及 Plan finding 生命周期；`review_result` 虽有不可变结果 Artifact/Review 行，v2 统一快照/状态定义待实现。落点：协议、EventService、FindingService、Gateway/MCP。 |
| D5 Review result | v1 Plan schema 使用 `comments[]/risks[]/suggestions[]`，Final 使用 `findings[]/verifications[]`；Final `NEEDS_CHANGES` 可因 reported verdict 而没有新 findings。 | v2 两类结果统一 actionable finding 语义；APPLY 前检查非空与当前 scope，拒绝空整改。落点：`docs/contracts/review-result.schema.json` 的新版本、`EventService._complete/_validate_findings`、查询。历史 v1 不重写。 |
| D6 Identity | `/reviewer/events` 有独立 Bearer token；Adapter 校验 agent/server/run；EventService 核对 RR、review、correlation、actor、input/profile/content revision，processed_events 去重。 | 回调当前没有明确 `expected_task_version` 字段；token 与 identity 的轮换/撤销及入口级幂等冲突策略需产品化；`EventService.ingest` 先暂存，再 APPLY。落点：v2 event envelope、authenticated ingress、EventService CAS 与 token runbook。 |
| D7 Rounds | `Settings` 默认 2/3；`request_review` 创建 RR/round；dispatcher retry 复用 RR；Task 保存上限快照。 | 没有独立 `revision_round`；当前 timeout 直接 `ESCALATED`，显式 Human resume 才新建 RR。需固定 review_round/revision_round 的展示与 Gate 规则，避免把超时误记为 NEEDS_CHANGES。 |
| D8–D10 Gates/Scope | 现有 `ESCALATED`、`BLOCKED`、Human resume/override/cancel 与高风险审批；Human Final override 能到 DONE；Worker complete 不改主 Task。 | 缺两个专用 Human Gate 状态、Accept/Modify/Continue/Abort 统一命令、`completion_basis` 和 Final Fix scope 守卫；现有 `cancel` 只由 Human actor 调用，尚无用户取消→认证 WorkBuddy→Hub governance 路径。`WorkerTaskService` 只允许在主 Task `NEW` 时 offer/claim/complete，Phase 5 因此使用了独立 Worker/Final Task；Phase 6 需将同一业务 Task 的 Worker 子生命周期接入 `EXECUTING`，保持主 Task 状态守卫。落点：model/rules/schema、GovernanceService、review event、Worker/Application/MCP。 |
| D11 Stable runtime | 本机 composite、Remote MCP、Reviewer ingress、Grok adapter、outbox/inbox/projection 的 bounded `*_one` 方法已存在；Phase 5 真回传/投影探针通过。 | 无已验 Named Tunnel/稳定 PublicBase、自动 intake、开机自启 supervisor、常驻调度、公开恢复指标/secret rotation Gate。Quick Tunnel 与人工 once 不能代替。 |
| D12 Manual Glue | `scripts/grokbuddy_grok.py` 暴露 `dispatch-once/event-once`；`scripts/grokbuddy_github.py` 暴露 `project-github-once`。Phase 5 报告明确使用。 | 需要由受监督的 outbox dispatch、Reviewer intake、event apply、projection、timeout/recovery worker 接管；自动 PR binding/route 必须经认证 Hub API 与 policy，不能从 PR 反向推导事实。 |

### 需要新增或修改的合同对象

- **状态/字段**：`PLAN_HUMAN_REVIEW`、`FINAL_HUMAN_REVIEW`、`conversation_id`、`trigger_evidence` 引用/hash、`completion_basis`、override metadata、`revision_round`、当前 actionable finding scope、gate reason/frozen automation flag；现有 `CANCELLED` 作正式 Abort 终态，终态集合与唯一活动 conversation 索引同步更新。
- **API/MCP**：生产专用 `create_task` 必带可核验 evidence；`list_actionable_findings(task_id, review_request_id)`；`get_plan_review/get_final_review` 返回不可变快照及当前 Finding 投影，区分两者；`submit_plan_change`、逐 finding fix 证据、`human_gate_decide(Accept/Modify/Continue/Abort)`、认证的 `cancel_current_task`；Reviewer 受控 `get_request` 应返回当前 expected state/version，v2 event 需带这些字段与幂等键。现有 HTTP/CLI 兼容面不得意外获得生产写入权限。
- **Worker/policy**：生产 supervisor 启动 dispatch、Reviewer intake、event apply、projection、timeout/recovery；统一 Settings 中的 2/3 上限、retry/backoff/deadline、单 conversation 活动 Task、scope 与 token rotation policy；健康状态至少报队列滞留、最老 lease、超时、失败投影和身份验证拒绝数，不暴露 secret。

## 3. State transition matrix（v2 目标）

所有边要求授权 actor、当前 task version、冻结 input/revision/hash 匹配，在一个 Hub 事务写 Task/RR/Finding/Audit/Outbox；未列边拒绝。`PLAN_*` 与 `FINAL_*` 的前缀仅为阶段，不把 Verdict 当 Task state。

| From | Event / guard | To | RR / 自动调度 |
| --- | --- | --- | --- |
| 无 | 认证 WorkBuddy + D1–D3 trigger evidence + conversation 无 active task | NEW | 创建 task/原始 Artifact/evidence 原子提交 |
| NEW / PLAN_CHANGES_REQUIRED | Builder 开始 Plan/按 finding 修订 | PLANNING | 无 active RR |
| PLANNING | 冻结 Plan、额度可用、创建新 PLAN RR | PLAN_REVIEW_PENDING | RR `PENDING`，review_round +1 |
| PLAN_REVIEW_PENDING | 有效 ReviewStarted | PLAN_REVIEWING | RR `IN_PROGRESS` |
| PLAN_REVIEW_PENDING / PLAN_REVIEWING | 有效 Plan PASS，先前 Plan findings 全已验证关闭/waive | PLAN_APPROVED | RR `COMPLETED`，冻结 approved Plan |
| 同上 | NEEDS_CHANGES + actionable findings + 仍有下一 RR 额度 | PLAN_CHANGES_REQUIRED | RR `COMPLETED`，revision 待 Builder 提交 |
| 同上 | NEEDS_CHANGES 达第 2 轮，或 BLOCK / retry 耗尽 / timeout | PLAN_HUMAN_REVIEW | 旧 RR `COMPLETED`/`FAILED`/`TIMED_OUT`；停止 auto dispatch |
| PLAN_APPROVED | Builder 开始批准范围内施工 | EXECUTING | 不等于生产执行授权 |
| EXECUTING | Worker 完成并提交证据 | EXECUTING | 仅 `worker_status=COMPLETED`，主状态不变 |
| EXECUTING | 合格自检/冻结 Final Package | SELF_TESTING | 不产生 verdict |
| SELF_TESTING | 创建新 FINAL RR，额度可用 | FINAL_REVIEW_PENDING | RR `PENDING`，review_round +1 |
| FINAL_REVIEW_PENDING | 有效 ReviewStarted | FINAL_REVIEWING | RR `IN_PROGRESS` |
| FINAL_REVIEW_PENDING / FINAL_REVIEWING | 有效 Final PASS + 全部 Finding closed + 安全守卫 | DONE | RR `COMPLETED`，`completion_basis=FINAL_REVIEW_PASS` |
| 同上 | NEEDS_CHANGES + actionable findings + 下一 RR 额度 | FINAL_CHANGES_REQUIRED | RR `COMPLETED`，冻结本轮 fix scope |
| 同上 | NEEDS_CHANGES 达第 3 轮，或 BLOCK / retry 耗尽 / timeout | FINAL_HUMAN_REVIEW | 旧 RR 按实态结束；停止 auto loop |
| FINAL_CHANGES_REQUIRED | Builder 仅处理当前 findings | EXECUTING | 每项 fix 关联 finding ID；越界改动转 Plan Change |
| FINAL_CHANGES_REQUIRED / EXECUTING | 修复要求扩大 approved Plan scope | PLANNING | 显式 Plan Change，旧 approved scope 不可沿用；新 Plan RR |
| EXECUTING | 提出危险动作 | AWAITING_HUMAN_APPROVAL | 停止该动作，独立 action approval |
| AWAITING_HUMAN_APPROVAL | Human 授权 / 拒绝并改 Plan / Abort | EXECUTING / PLANNING / CANCELLED | 审批与 review verdict 分离 |
| 任一非终态 | 已认证用户取消经 Hub governance | CANCELLED | active RR 终止、outbox 取消、loop 停止、context 清理 |
| 任一非终态 | 不可恢复内部故障 | FAILED | 停止调度，保留证据 |

RR：`PENDING → IN_PROGRESS → COMPLETED`，或 `PENDING/IN_PROGRESS → FAILED/TIMED_OUT/ESCALATED`；终态不可回退。Human Gate 后迟到 callback 只能 `LATE_EVENT`/reject，无 Task mutation。Legacy `ESCALATED/BLOCKED` 只能经显式、带审计的迁移/人工决策处理，不能由 v2 worker 自动重开。高风险审批中的任务总超时应进入相应人工处置；不能假定已有 Review Gate 与 action approval 相同。

## 4. Plan / Final round 与 Human Gate 规则

| 决策 | Plan Gate | Final Gate |
| --- | --- | --- |
| Accept | 审计 `PLAN_OVERRIDE`，绑定当前 Plan Artifact/hash、未关闭 finding 与风险，终止 active RR，转 `PLAN_APPROVED`；不记 Reviewer PASS。 | 审计 `FINAL_OVERRIDE`，需合格 Final Package/自检和未关闭问题确认，转 `DONE/HUMAN_OVERRIDE`；写 reason、actor、timestamp、related RR，不修改历史 Review。 |
| Modify | 转 `PLANNING`，新 Plan revision；下次 PLAN RR 占下一 review_round。若额度不足，需独立 Human 扩预算。 | 范围内转 `EXECUTING` 修复当前 findings；超范围转 `PLANNING` 并重审 Plan。 |
| Continue | 明确批准新 deadline/review budget/reason 后，转 `PLANNING`，同一冻结 Plan 可再建 RR；旧 RR 不复活。 | 同样批准后转 `SELF_TESTING`，只有 package/self-test 仍有效时可再建 RR；否则转 `EXECUTING` 重做。 |
| Abort | 转 `CANCELLED`，停止自动 loop、释放 conversation context。 | 同左。 |

每次新 RR 都占 review_round，包括 Human Continue 后的新 RR；review_round 不重置。自动上限始终是 Plan 2/Final 3；Human Continue 的额外 RR 以独立的、绑定 task/type/新增总额度/deadline/actor/reason 的一次性预算批准记录放行，不会把默认 policy 全局调高。`retry_dispatch` 仅在 RR 未过期且同一 delivery_key/lease 下有限重试；超时本身不产生 `NEEDS_CHANGES` 或 revision_round。`NEEDS_CHANGES` 结果缺 actionable `findings[]` 时，APPLY 事务拒绝，不更新 Review/Finding/Task；由 deadline 或合法新结果决定后续。Human Gate 内任何自动 RR 创建、投递、Worker 修复、callback APPLY 均拒绝；Human 操作需要独立身份、理由、expected version、幂等键与 Audit。

## 5. Trigger lifecycle 与取消

1. 每条 WorkBuddy 用户消息先按来源分段，只检查当前轮主自然语言正文；默认 disabled。非命中走普通 WorkBuddy 路径，不调用生产 `create_task`。
2. 命中后由 WorkBuddy 附上 D2 evidence 请求 Hub；Hub 在一个事务核对用户来源、原文 hash/offset/字面值、conversation 活动 Task 唯一性与幂等键，创建 task。缺 evidence、旧轮 evidence、引文/附件 evidence、不同 conversation/task 复用均拒绝。
3. Plan/Fix/Re-review 的上下文绑定 task_id；WorkBuddy 必须从 Hub 获取当前状态/finding，不使用聊天粘贴结果。退出或取消后清除该 task-scoped context；Hub 终态是权威，WorkBuddy 本地清理可重试。
4. 用户取消走已认证 WorkBuddy → Hub governance `cancel_current_task`，Task `CANCELLED`、active RR `ESCALATED`（reason `TASK_CANCELLED`）、未发送 outbox `CANCELLED`；已发送外部请求可能返回迟到事件，只记 `LATE_EVENT`，不复活 Task。下一条普通消息仍按 disabled 处理。

## 6. Forbidden Paths 与后续 negative probes

| # | 禁止路径 | 期望 probe 结果 |
| --- | --- | --- |
| F1 | WorkBuddy 直接 POST `/reviewer/events` | 身份/ACL reject；无 inbox APPLY、Review 或 Task mutation |
| F2 | WorkBuddy 绕 Hub 同步调用 Grok，将文本当正式 review | 无有效 RR/event 不可生成 Review；Task 不推进 |
| F3 | Reviewer 无合法 active RR 推进 Task | reject / `VALIDATION_FAILURE`；无状态变化 |
| F4 | callback token/identity、RR ID、correlation、idempotency key、expected state/version 任一错误 | 401/403/422 或 `VALIDATION_FAILURE`；无业务 mutation |
| F5 | Reviewer 提供/要求 Hub outbox lease | schema/权限 reject；Reviewer 不接触 lease |
| F6 | Worker `complete_task` 直接令主 Task DONE | 仅 worker 子状态完成；主 Task 保持原状态 |
| F7 | PR/comment/webhook 改写 Hub 业务状态/verdict | 忽略或拒绝未授权映射；仅正式 Application/event 可推进 |
| F8 | Human override/resume 绕 governance/API 或无 Audit | reject；Review 历史不改，Task 不推进 |
| F9 | 直接 DB DML 修改业务状态 | 生产 DB 凭据/权限拒绝；运营流程不得提供该路径 |
| F10 | Codex CLI、临时 `.py`、PowerShell once 充当正式 runtime | 6.20 Gate 计为失败；正式 E2E 运行记录中次数为 0 |

补充反例：触发词只在代码块/引用/附件、跨 conversation 继承、双 Task 并发创建、空 `NEEDS_CHANGES findings[]`、Gate 中迟到 callback、超范围 Final Fix、重复 comment 与 token 轮换旧 token。每项要断言 reject/`VALIDATION_FAILURE`/no mutation，并核对 Audit 与 side effect 数。

正向合同测试至少覆盖：当前轮正文触发并只建一 Task、同 task Plan/Fix 继承、第二轮 Plan PASS、第二轮 Plan 未 PASS 入 Gate、第三轮 Final 未 PASS 入 Gate、空整改结果拒绝 APPLY、Human Final Accept 产生 `DONE/HUMAN_OVERRIDE` 且旧 verdict 保持、Human Continue 逐次扩预算、用户 Abort 后下一条普通消息不触发、Final Fix 越界回 Plan Review。每个案例比对 Task/RR/review_round/revision_round、不可变快照、Finding 与 Audit 的持久化结果。

## 7. Step 6.0a Manual Glue / Recovery 测试设计

**人工胶水清单**：Phase 5 使用的 `dispatch-once`、`event-once`、`project-github-once`；手动复制 Quick Tunnel hostname；聊天复制 findings；临时 resume 脚本；手动 `bind-pr`/`route-task`；Reviewer Test Run 点击。它们可用于 debug，但 6.20 业务闭环计数必须全部为 0。正式设计的五个常驻职责：outbox dispatcher、自动 Reviewer intake、event ingress/apply、GitHub projection、retry/timeout/recovery；Hub 持久化 lease/幂等/审计，supervisor 自动重启。

| Recovery probe | 目标不变量 |
| --- | --- |
| duplicate claim / stale lease | 一个有效 owner/version；lease 到期可重新领取，旧 owner 不能完成；无重复 Task/Artifact |
| duplicate completion | 同 key 同结果重放原 receipt；冲突 payload reject；主 Task 不直接 DONE |
| duplicate callback / duplicate event | 同 key 同 hash no-op；同 key 异 hash reject；一个 RR 至多一个 Review snapshot，Finding 不重复 |
| Hub restart / worker restart | 持久化状态恢复、过期 lease 重领；不倒退状态，不重复外部请求 |
| reviewer timeout / network interruption | 同 RR 有限 retry；不记虚假 NEEDS_CHANGES；不确定 delivery 先 reconcile，策略耗尽进对应 Human Gate |
| projection failure | Hub 已完成 Review/DONE 不回滚；可重试且按稳定 marker 查询/更新，不产生第二条 comment |
| token rotation | 新旧 token 切换窗口/撤销由 runbook 控制；旧 token 失效后拒绝，已提交 RR/Review 不受影响；secret 不入日志/Artifact |

所有恢复 probe 需断言 Task/RR/Finding/Artifact side effect 数不重复、状态单调、Audit 可解释。普通 retry 不产生新 review_round；Human Continue 新建 RR 则明确占一轮。

## 8. 后续 Step 依赖顺序（计划，不代表授权或完成）

`6.0 合同` → `6.0a 人工胶水替换合同/测量基线` → `6.1 trigger 与 conversation guard` → `6.2 v2 schema/持久化与迁移` → `6.3 Review Result/Finding 查询与 APPLY` → `6.4 Plan/Final loop 和 scope guard` → `6.5 Human Gate/Abort API 与 MCP` → `6.6 自动 Worker、Reviewer intake、dispatcher、event/projection supervisor` → `6.7 恢复/反例/身份测试` → `6.8 Named Tunnel、稳定配置与 secret runbook` → `6.9 health/observability、auto-start、staging E2E` → `6.19 Production Preconditions Gate` → `6.20 Real Final E2E`。

6.19 必须以实际稳定 endpoint、WorkBuddy/Reviewer 当前配置、自动接单、无人工胶水的连续运行和上述恢复/反例证据 PASS；任何一项缺证据均 BLOCK 6.20。6.20 才能运行真实生产式 E2E；仅合同 PASS 不授权部署、真实 Task 推进、GitHub 高风险写入或生产 DB DML。

## 9. 本轮检查与未验证项

本轮运行了 `rg`/`Get-Content` 文件与源码只读搜索、嵌套 checkout `git status --short --branch` 和 `git status --porcelain=v1`（干净）、Python `sqlite3` 的 `mode=ro` 探针查询、报告本地链接/章节/marker 静态检查（缺失链接 0、Forbidden Paths 10 条、最终 marker 1 处）。未执行 pytest、服务、MCP、Grok、GitHub、tunnel、生产写入或真实任务。文档变更仅此文件。未验证：WorkBuddy 当前轮消息 provenance、生产 trigger、防并发 conversation、v2 schema/APPLY、专用 Gate、Named Tunnel、常驻 supervisor、token rotation、真实无胶水 E2E。它们是后续实现与 Gate 项，不改变本轮 **合同** 判定。

`PHASE6-STEP6.0-CONTRACT: PASS`
