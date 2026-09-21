# PHASE6-STEP6.0a — Manual Glue / Supervisor Contract

`PHASE6-STEP6.0a-MANUAL-GLUE-SUPERVISOR: PASS`  
日期：2026-09-21（Asia/Shanghai）  
判定范围：**合同、只读代码差距和验收探针设计通过；实现与运行证据 NOT RUN。** 本文承接 [Step 6.0 合同](PHASE6_STEP6_0_CONTRACT_REPORT.md) D1–D12、F1–F10、§7，尤其 D11/D12/F10；[Phase 5 Functional Exit](PHASE5_FUNCTIONAL_EXIT_EVIDENCE_REPORT.md)只作为人工胶水反例。`6.0a PASS ≠ 6.19 PASS ≠ 6.20 PASS`。

## 1. 冻结零人工正式路径

正式业务路径是 `WorkBuddy → Hub 同一 Task 的 Plan → EXECUTING/Worker → Final → Reviewer → Hub event/APPLY → GitHub projection`。Hub DB 是 Task、RR、Review、Finding、Artifact、Audit 和最终状态的唯一事实源。GitHub Comment、PR 和 Reviewer 侧通知只承载请求或投影，不能反向认定 Review PASS/DONE。Codex 与 CLI 不承担正式运行角色。

**6.20 业务证据链的 Manual Glue = 0。** 以下命令可以保留为隔离调试工具；只要其中任何人工动作出现在正式成功路径的运行记录中，该次 Gate 即 **FAIL**，不能用其补齐断点再声称自动 E2E。Human Gate 的授权裁决属于正式治理动作，不是用人工 once/脚本代替 worker；所有裁决仍须认证、绑定范围并留 Audit。

| Manual Glue / Phase 5 反例 | Forbidden in | Replaced by / Owner process | 触发条件 | 幂等键或去重锚 | 失败 → |
| --- | --- | --- | --- | --- | --- |
| 人工 `dispatch-once` | 6.20 正式 RR 投递 | Hub Supervisor / Outbox Dispatcher | 已提交且未过期的 `READY/RETRY` outbox | `RR.id = delivery_key`；lease token + fencing | 有界重试；不确定投递先 reconcile；耗尽进入对应 Human Gate |
| 人工 `event-once` | Reviewer 回传后的 APPLY | Hub Reviewer Ingress + Event Apply Worker | 认证 callback 持久入 inbox，或恢复时发现 `READY` | `(source,deduplication_key)` + normalized hash，RR 唯一 Review | 验证失败隔离；迟到事件不推进；可恢复待处理 inbox |
| 人工 `project-github-once`，包括人工 enqueue | Final Review 投影 | Hub Projection Intent + GitHub Projection Worker | Final Review 原子提交后有待投影 intent | `(review_id,binding_id)`、固定 comment marker/hash | 仅 projection 重试/告警；Hub Review/DONE 不回滚，不双发 Comment |
| 人工 `timeout-once` / 临时 `resume_*.py` | 超时与恢复 | Hub Timeout / Recovery Worker + Human Gate API | task/RR deadline、lease 过期或投递异常 | `task_id/RR.id + deadline/policy version`；Human 命令 key | RR `TIMED_OUT/FAILED` 保留，自动路径冻结或按合同恢复；无伪造 `NEEDS_CHANGES` |
| Reviewer Routine “Test Run” 才接单 | Reviewer intake | Hub 受控待审队列 + 已认证 Reviewer 自动 consumer（push 或 poll） | 已路由、outbox `SENT`、RR 仍 `PENDING/IN_PROGRESS` | `RR.id + frozen input/profile hash` | 不可自动接单即 backlog/告警，6.19 不通过；不把 Comment ACK 当接单 |
| 人工 `bind-pr` / `route-task` | 绑定与未来 RR 路由主路径 | 认证 WorkBuddy/Builder → Hub Binding/Route Policy | 可信 PR 身份出现，且首个外部 RR 投递前；Plan PASS 后复核 | `(repo immutable id, PR number, task_id)`；`task_id + reviewer actor` | 冲突或身份不独立则阻止投递并进入可审计处置，禁止猜测绑定 |
| 人工复制 Grok findings 给 WorkBuddy | Plan/Fix/Final 修复回路 | Hub Review/Finding 查询 API + WorkBuddy 同 task 消费 | Review `APPLIED`，或 Builder 查询当前 actionable finding | `task_id + RR.id + finding_id/version` | 查询失败保持 Hub 状态；不得用聊天粘贴作为正式 finding |
| 人工发起独立 `NEW` Worker Task、另建 Final Task 拼闭环 | 同一业务 Task 生命周期 | WorkBuddy/Hub 同 Task worker offer/claim/complete + Plan/Final Application | Plan `PASS → PLAN_APPROVED → EXECUTING` | `task_id + worker assignment generation`、命令 receipt | claim 竞争/过期可恢复；Worker complete 仅关子生命周期，不直接 DONE |
| 手抄 Quick Tunnel hostname、修改 MCP URL / `--public-host` / `--grok-public-base-url` | 稳定正式入口 | 受监督 Hub 服务 + Named Tunnel/稳定 PublicBase 配置（6.8） | 服务启动、配置校验、凭据轮换 | 配置版本 + 固定 hostname；secret version | 不健康则拒绝新投递并告警；禁止动态域名补救 |

现有 GitHub `pull_request.synchronize` 入口可作为通信事件，但不得替代同一 Task 的 Hub 授权命令或从 PR 状态推断业务状态（D4/F7）。已有 `retry-final` 是显式 Human 恢复旧探针的命令，不是 supervisor 的自动恢复 API。

## 2. Supervisor 通用合同

**进程与边界。** 一个受服务管理器监督、开机自启的 Hub 进程可运行多个独立职责；也可拆进程。每个职责有独立循环、错误计数和重启策略，某一外部适配器故障不得停止 event APPLY、timeout 或 Hub 查询。启动先校验 schema/policy/身份/稳定 PublicBase 和 secret 引用，再恢复已持久化的 `READY/RETRY/LEASED` 工作；进程内存不是队列。进程重启只恢复待办，不重新创建 Task/RR。现有 `LocalRuntime.tick()` 仅为显式本地一次迭代，不是本合同的 supervisor。

**调度。** DB commit 可发本机 wake signal，但每个 worker 必须有可配置的周期扫描兜底；signal 丢失不能丢工作。默认设计上限：dispatch/intake/event/projection 扫描间隔 5 秒，timeout/recovery 5 秒；批量每轮有界，异常后有界退避，扫描滞后和队列最老年龄可观测。间隔不能延长冻结的 RR/task deadline。外部 I/O 不占 Hub 长事务。

**Claim 与 fencing。** 每个持久化工作项以短事务做条件 claim，记录 `lease_token`、递增 `lease_generation`、`lease_until`、attempt 与冻结 task/RR/route/policy 版本；仅持有当前 generation 的 worker 可写完成回执。旧 lease 到期后即使旧 worker 返回，也只能得 `LEASE_LOST`，不得改新状态。lease 到期不等于远端请求未生效：对可能已提交的外部写入必须先按稳定 marker/外部 receipt 对账；无法证明安全时置 `UNKNOWN` 并进人工处置，禁止盲目第二次 POST。对于 GitHub Comment 创建，远端无原子唯一键保证时还须保证同一 marker 不存在并行创建；模糊完成不得仅凭一次暂时“查不到”就重建。

**幂等与事务。** Hub 命令按已认证 actor、operation、key 和参数 hash 存 receipt：同 key/同 hash 返回原 receipt，同 key/异 hash `CONFLICT` 且无业务 mutation。Task/RR/Review/Finding/Audit、待发送 intent 在一个 Hub 事务提交；Artifact 字节按 SHA-256 不可变，DB 元数据/事件重放不得重复创建。`review_round` 只在**新 RR** 创建时 +1；`retry_dispatch` 复用有效 RR 和 delivery key；`revision_round` 只在有效 `NEEDS_CHANGES` 后 Builder 提交新修订时 +1。timeout、重复 callback、transport retry 都不改变二者。遵守 6.0 的 Plan 2 / Final 3 自动上限与 Human Continue 的逐次额外预算。

**Gate。** `PLAN_HUMAN_REVIEW`、`FINAL_HUMAN_REVIEW`、`AWAITING_HUMAN_APPROVAL`、终态和过期 task 均禁止新自动 RR、dispatch、Worker 修复及正常 callback APPLY。Gate 中可保留审计、迟到事件隔离、只读查询与已提交投影的安全重试；Human 决策仅走认证 Governance API，不能由 supervisor 自行恢复。高风险动作审批与 Review PASS/override 分离。Gate 后可重试历史 GitHub 展示，不得改写历史 Review/verdict。

**最小观测面。** 每个 worker 输出 `last_success_at`、`backlog_count`、`oldest_age_seconds`、`last_error_code/at`、运行/重启数；另报 lease 过期、`UNKNOWN`、验证拒绝、RR 超时、投影失败和 GitHub 对账数。`/health` 的进程存活不能代替 readiness；readiness 要检查各循环最近成功与 backlog/deadline 阈值。Audit/日志只存短错误码、关联 ID、hash/计数，不输出 secret、原始 Review JSON 或长内容。6.19 应保存连续运行/重启恢复的指标快照及零人工操作日志。

### 2.1 Outbox Dispatcher

- **输入/输出**：读取 `outbox_events` 与冻结 RR、Task、route/binding；条件 claim `READY/RETRY` 或已过期 `LEASED`；用选定 ReviewerAdapter 查询 `delivery_key` 状态后投递；写 `SENT/RETRY/FAILED/UNKNOWN/CANCELLED`、安全错误码和 Audit。`SENT` 只证明载体接受，不等于 Reviewer 已执行。
- **调度/隔离**：commit wake + ≤5 秒扫描；按 reviewer/transport 分开限流，单条错误不阻塞其他 RR。task/RR 已过期或进入 Human Gate 时不得 claim；检查必须在 claim 事务与完成事务各做一次。
- **幂等/恢复**：`delivery_key=RR.id`，冻结 request/input/profile hash；lease generation fencing；网络断开、POST 回执丢失或状态不可判定时 `UNKNOWN → reconcile`，仅证实未投递才允许同 RR 再试。`retry_dispatch` 不创建 RR、不加 `revision_round`。有限 retry 耗尽标 RR 真实失败并送对应 Gate；当前 `Dispatcher` 的 `UNKNOWN/FAILED → ESCALATED` 是 legacy 行为，须按 v2 Gate 迁移。

### 2.2 Reviewer Intake

- **输入/输出**：Hub 提供按已认证 Reviewer actor 过滤的待审 RR 索引，只暴露 `outbox=SENT`、有效路由、未过期且 task 未冻结的 RR；返回 RR ID、冻结 hash、deadline、当前 expected state/version。Reviewer 自动 consumer 读取现有 `/reviewer/requests/{RR}` 和受控 Artifact，随后以正式事件回传。Reviewer 不取得 Hub outbox lease；intake receipt 与 transport ACK 均不推进 RR verdict。
- **调度/去重**：优先已验证的自动 push/wake；无可靠 wake 时使用受控定时 poll，间隔 ≤5 秒且小于剩余 deadline，cursor/ack 持久化。使用 `RR.id + input/profile hash + reviewer actor` 作为 intake 工作键；同 RR 重见只复用 receipt，不重复执行评估。Hub 不假定 GitHub Comment 能唤醒 Grok。当前账号能否长期自动 poll/push 为 **ENVIRONMENT_VALIDATION_REQUIRED**；只在手动 “Test Run” 可接单则 6.19/6.20 失败。
- **失败态**：认证失败/路由冲突拒绝并告警；consumer 不可用时 backlog 持续增长，timeout worker 按真实 deadline 入相应 Gate，不虚构 ReviewFailed/PASS。

### 2.3 Reviewer Event Ingress / Apply

- **输入/输出**：`POST /reviewer/events` 使用独立 Reviewer 身份验票、大小与 envelope 校验，先持久化 inbox 并回 `202`；后台 APPLY 读取 `READY`，在短事务内核对 RR/task/review/correlation、actor、frozen input/profile/content revision、expected state/version 与当前 Gate，再写不可变 Review/result、Finding events、RR/Task/Audit 和 projection intent。
- **调度/幂等**：HTTP 到达可唤醒 Apply；≤5 秒扫描兜底。入口**先查** `(source,deduplication_key)` 和 payload hash 的 receipt，再决定是否存 Artifact；同 key/同 hash 返回原 ingress/APPLY receipt，无第二个 Artifact/Review/Finding；同 key/异 hash 拒绝并告警。不同 transport 的同一 RR 由 `(RR.id,review_id)` 唯一约束与 normalized hash 去重。APPLY 用 task expected version/CAS 与 RR active guard；重复事件须先查既有 receipt 再校验版本，以免合法重放因版本变化误拒。
- **失败态**：结构/语义无效记 `VALIDATION_FAILURE`，不推进；终态、Gate 或超时后的事件为 `LATE_EVENT`/拒绝并留 Audit，不复活；worker 崩溃时 `READY` inbox 留待扫描。当前 `EventService.ingest()` 会先为每次收到的事件创建 Artifact，随后 `handle_one()` 才去重；因此入口去重与 Artifact side effect 零重复仍待实现。

### 2.4 GitHub Projection Worker

- **输入/输出**：Final Review APPLIED 的同一 Hub 事务产生稳定 projection intent；worker 将不可变 Review/绑定转换为受控短 Comment 与 Artifact pointer，持久化 `READY/LEASED/RETRY/SENT/FAILED/UNKNOWN`、comment ID/hash/Audit。仅 Hub Review 是依据；GitHub 失败不回滚 `COMPLETED`、`DONE` 或 `HUMAN_OVERRIDE`。
- **调度/幂等**：commit wake + ≤5 秒扫描；`(review_id,binding_id)` 唯一、固定 `<!-- grokbuddy-final-review:{review_id} -->` marker；claim fencing；先 find，已有则同内容 no-op、异内容 update，安全无记录才 create。创建回执不明时保持 `UNKNOWN` 并对账，禁止并发 create 和直接再 POST；同一 Review 最多一条 Comment。重试有界、失败告警，projection 独立于 reviewer/event worker。
- **现状差距**：现有 `enqueue_final_review()` 和 `project_one()` 提供唯一 projection ID、marker、find/update/create、lease/retry；但 `enqueue` 由 CLI 显式调用，且 `project_one` 对远端创建回执不明会走普通 retry。目标态须增加自动 intent 和模糊提交安全门。

### 2.5 Timeout / Recovery Worker

- **输入/输出**：扫描 task/RR deadline、过期 lease、`UNKNOWN/FAILED` delivery、待处理 inbox、projection backlog 和 Gate；按冻结 policy 原子结束 RR、取消未发送 outbox、写 Audit 与对应 `PLAN_HUMAN_REVIEW`/`FINAL_HUMAN_REVIEW`，或在 RR 仍有效且远端已确认可重投时安排同 RR `retry_dispatch`。
- **调度/幂等**：≤5 秒扫描；按 `task_id + RR.id + deadline/policy version` 做条件迁移，多个 supervisor 并发只一人成功。重启后用持久化 deadline，不延长；timeout 与 Completed 竞争只准一个终局。`TIMED_OUT` 保留真实 RR 状态；`NEEDS_CHANGES` 只能来自已验证的 Reviewer 结果。单次 transport retry 不烧 review_round；Human Continue 经 Governance 新建 RR 才占一轮。
- **隔离**：GitHub projection 失败仅进 projection backlog，不触发 task review 回滚；Reviewer 投递不可恢复、deadline 耗尽或上限耗尽进入对应 Human Gate，不由临时 resume 脚本自动开新轮。legacy `TimeoutService.sweep()` 当前直接 `ESCALATED`，其迁移属于后续实现。

### 2.6 Binding / Route 与同一 Task Worker 合同

- **Binding/route**：认证 WorkBuddy/Builder 从已批准的代码交付流程提供 immutable repo ID、PR number、task_id、Builder 与 Reviewer actor；Hub 核对身份分离、Task owner、PR 唯一绑定，`ensure_binding`/`ensure_route` 返回稳定 receipt。若 Plan RR 也经 GitHub Comment 载体，在**首个 Plan dispatch 前**完成；Plan PASS 后、进入 EXECUTING 前再次核对已冻结 binding/未来 route，不能等待人工 `bind-pr/route-task`。未绑定不得发外部请求。GitHub webhook 不能创建或修改 Hub 的权威 Plan/Task verdict。
- **同 Task**：唯一业务 `task_id` 贯穿 Plan、Worker execution、Final，Worker assignment 是该 Task 的子对象，包含 worker principal、assignment generation、lease/claim、approved Plan hash、scope 和 completion Artifact/hash。Plan PASS 后的 `EXECUTING` 才 offer；Worker 只能在冻结 scope 内 claim/上传/完成，完成仅置子状态 `COMPLETED` 并留 Audit；Builder 再提交自检/Final Package，合法 Final PASS 或 Human Final Accept 才能 `DONE`。Worker 不能通过改 `Task.owner_id` 抢走 Builder 对 Plan/Final 的权限。Final Fix 同 task 重新进入 EXECUTING；超 approved Plan scope 回 Plan Change/新 Plan RR。
- **Human Gate**：Gate 打开时不得新 offer/claim/自动修复；已领取的 assignment 要冻结并以 generation/version fencing 拒绝迟到完成。Worker 侧不可使用聊天复制的 findings；只从 Hub 的 actionable findings 查询并逐 ID 关联修复证据。

## 3. Recovery / Idempotency 验收探针（设计，未执行）

通用夹具：隔离 SQLite DB + content-addressed Artifact Store、受控时钟、可暂停/丢回执的 Reviewer/GitHub transport、两个并发 supervisor 实例；每个 probe 比对 `tasks/review_requests/reviews/review_findings/artifacts/command_receipts/inbox_events/processed_events/outbox_events/github_comment_projections`、Audit 和模拟远端 Comment。断言同一业务输入只有 1 Task、按合同数量的 RR/Finding/Artifact 业务副作用及 1 个投影 Comment；状态与版本不倒退。模拟器结果只证明本地合同，不是 Grok/GitHub/6.19 证据。

| Probe 名称 | 故障注入 / 操作 | 可断言结果 |
| --- | --- | --- |
| `P01_duplicate_claim_stale_lease` | 两 dispatcher/Worker 同时 claim；A lease 过期、B 接管，A 迟到提交 | 一个有效 generation；A `LEASE_LOST`；无重复 Task/RR/assignment/Artifact，B 的状态不被 A 覆盖 |
| `P02_duplicate_completion` | Worker 同 key/同 hash complete 两次，再同 key/异 hash | 同 hash 原 receipt、一次 `WORKER_COMPLETED`；异 hash `CONFLICT`；主 Task 仍 `EXECUTING`，不直接 `DONE` |
| `P03_duplicate_callback_event` | 同一 callback 两次、跨入口重复、同 key 改 payload | 同 hash 原 ingress/APPLY receipt；恰一 Review、结果 Artifact 元数据和 Finding 集；异 hash reject/Audit；RR/Task 不倒退 |
| `P04_hub_restart_after_commit` | RR+outbox 事务提交后杀 Hub，重启；再在 APPLY 提交前/后杀进程 | 恢复 PENDING/outbox/inbox；同 RR 不新建轮次；APPLY 至多一次，已提交结果不丢 |
| `P05_worker_restart_lease` | 投递/投影外呼前后中断、lease 到期重领 | stale worker 不能提交；按远端 marker/receipt 对账；无第二次不确定 POST、无双 Comment |
| `P06_reviewer_timeout_network` | Reviewer 沉默、网络断开、ACK 丢失，推进受控时钟到 deadline | 有效 RR 内有限重试/对账；`TIMED_OUT` 或真实 `FAILED` + 对应 Human Gate；`revision_round` 不增、无假 `NEEDS_CHANGES`，迟到 callback 不复活 |
| `P07_projection_failure` | Final APPLY/DONE 后 GitHub 429/5xx/断线，随后恢复；模拟 POST 已成功但回执丢失 | Hub Review/DONE 不回滚；projection 单独 RETRY/UNKNOWN→SENT；按 marker 对账后 Comment 总数 1、同一 ID 更新/复用 |
| `P08_same_key_same_hash` | create/ensure binding/route/worker complete/event 命令重放相同 key/hash | 原 receipt 与对象 ID 返回；Task/RR/Finding/Artifact/Comment 数不增 |
| `P09_same_key_different_hash` | 相同 actor+operation+key 但内容/hash 改变 | `CONFLICT`/验证拒绝；业务状态、Artifact/Comment 数不变，安全 Audit 可解释 |
| `P10_gate_freeze_late_event` | Plan/Final Gate 后待投递 RR、已 claim Worker、迟到 callback 同时到达 | 无新 dispatch/claim/RR、无正常 APPLY；迟到事件隔离；Human 命令需认证与 Audit；历史 verdict 不改 |
| `P11_same_task_path` | 从 Plan PASS→EXECUTING→Worker complete→Final PASS 运行夹具 | 全链同一个 `task_id`；Worker complete 后非 DONE；Final 合法结果才 DONE；无独立 NEW Worker/Final Task |
| `P12_token_rotation` | 新旧 token 交接、旧 token 撤销后重放 callback（仅模拟） | 窗口内按配置验票；撤销后 401/403、无 mutation；已提交 RR/Review/receipt 不丢，日志/Artifact/Audit 无 secret |
| `P13_zero_manual_gate` | 用业务链路 trace + 操作日志核对 6.20 样本 | 人工 once、Test Run、临时 resume、复制 findings/hostname、手工 bind/route 计数全为 0；任一非零则 Gate FAIL |

## 4. 当前代码只读核对与可执行 backlog

以下“已有”指源码存在，不表示已在常驻进程或真实账号验证。源码入口均在本仓库根；本轮未读写真实 Hub DB。

| 优先级 / 后续 Step | 已有源码证据 | 缺口与完成条件 / 前置依赖 |
| --- | --- | --- |
| P0 / **6.1** Trigger | `TaskService.create_task`、`ClientGateway._create_task` 目前只接 description/profile/key。 | 增可信当前轮 trigger evidence、conversation 活动 Task 唯一约束与认证 WorkBuddy 创建路径；未完成前不可对生产自动建 Task。6.0a 仅定 glue 合同，不写 trigger。 |
| P0 / **6.2** schema/持久化 | `schema.sql` 有唯一 active RR、outbox/inbox/processed/command receipt、binding/route/projection 表；`SQLiteRepository` 短事务和唯一约束。 | 加 v2 Gate、`revision_round`、conversation、worker assignment generation/lease、intake receipt、projection intent/UNKNOWN、lease generation、可恢复指标及必要索引/迁移；历史 v1 不重写。6.6 的 worker 依赖这些字段。 |
| P0 / **6.3–6.4** Review/Finding 与同 Task loop | `ReviewService.request_review` 原子创建 RR/outbox；`EventService` 有 ingest/handle_one、processed dedup 和 Final finding；`TaskService` 有 Plan/Final 流程。 | 统一 v2 Plan/Final actionable finding、入口去重先于 Artifact、expected task version/CAS、APPLY 原子 projection intent；补 `list_actionable_findings`。`WorkerTaskService` 目前只认 `NEW`，claim 改 `owner_id`，要改为 `EXECUTING` 下独立 assignment 并让 Builder 持续拥有同 Task。需要 6.2 schema。 |
| P0 / **6.5** Human Gate | `GovernanceService.resume/override_review/cancel`、高风险审批已有；`TimeoutService.sweep` 可显式扫描。 | 专用 Plan/Final Gate、Accept/Modify/Continue/Abort、自动冻结和可信用户取消。现有超时/投递错误到 `ESCALATED`，不得直接当 v2 正常 Gate；需历史兼容迁移与 Audit。6.6 自动调度必须以此为守卫。 |
| P1 / **6.6** Supervisor | `Dispatcher.dispatch_one` 有 lease/retry/delivery key；`EventService.handle_one` 有短事务；`GitHubProjectionService` 有 enqueue/claim/project；`LocalRuntime.tick` 有一次性本地迭代。 | 新增服务管理的持续循环、启动恢复、独立错误域、配置/限流、fencing 和健康状态；自动 enqueue Final 投影；UNKNOWN 外部写入安全对账；自动 bind/route policy；Reviewer 受控待审队列 + 自动 consumer。现有 `grokbuddy_grok.py` 与 `grokbuddy_github.py` 的 once 仅保留 debug。依赖 6.2–6.5。 |
| P1 / **6.7** Recovery/身份测试 | `tests/test_workers.py`、`tests/test_governance.py`、`tests/test_phase5_worker_mcp.py` 等覆盖既有局部行为。 | 实现 P01–P12、两 supervisor 并发、restart、失回执、Gate/late event、token rotation 夹具；持续验证唯一业务副作用。依赖 6.6。 |
| P1 / **6.8** 稳定入口 | `grokbuddy_composite.py` 以 `--public-host`、`--grok-public-base-url` 手工配置；`CompositeApplication` 有 `/health`、`/mcp`、`/reviewer/*`，Remote MCP 仅五个只读工具。 | Named Tunnel、稳定 DNS/PublicBase、Worker/Reviewer 自动配置与 secret rotation runbook；禁 Quick Tunnel。稳定公网及自动接单须实际账号验证；本 Step 不实施。 |
| P1 / **6.9** 可观测与自启 | `/health` 目前仅返回 `{status: ok}`；入口脚本用 `uvicorn.run`。 | 服务自动启动/重启、各 worker backlog/last_success/last_error、readiness、持续运行与零人工 trace 采集；staging E2E 后交 6.19。 |

额外静态差距：`GrokReviewerApplication` 只提供已知 RR 的 GET/Artifact 和 POST event；`Remote MCP.list_pending_review_requests` 是 Builder 侧只读全局列表，不能当 Reviewer 专属自动 intake。`GrokBotReviewerAdapter` 的 GitHub Comment `ACCEPTED` 是载体回执，不证明 Grok wake/执行。`GitHubProjectionService` 的 find/update/create 已有本地幂等锚，但远端不确定提交与并发创建仍需 P05/P07 证明。当前 `FileArtifactStore` 使用 SHA-256 内容地址复用字节；`persist_event` 每次 ingress 仍新建 DB Artifact 元数据，故 P03 不能视作已通过。

## 5. Gate 与本轮边界

- **可下一步实现**：依 6.0 顺序先做 6.1 trigger/conversation guard，再 6.2 schema、6.3–6.5 业务守卫，6.6 supervisor，6.7 探针；本报告已把替代胶水设计冻结在 trigger 实现之前。没有 6.2 schema 与 6.5 Human Gate 时，不启动会自动 dispatch 的正式 worker。
- **6.19 前置 Gate**：6.8 Named Tunnel/稳定入口、Reviewer 自动接单、service auto-start、token/secret runbook、恢复/观测和 P01–P12 的隔离测试与当前账号验证齐备；不得以 Phase 5 的 Quick Tunnel/人工 once 证据代替。
- **6.20 Real Final E2E Gate**：6.19 PASS 后才运行真实业务样本，留同一 Task 全链 Hub 记录、自动 worker 运行/恢复记录与 P13 零人工操作证据；出现任何 CLI `*_once`、Test Run、临时脚本、人工复制或手工 binding/route 即 FAIL。投影故障单独报告，不改 Hub verdict。`6.0a PASS` 仅表示下一位工程师可按合同开工。
- **本轮操作**：只读查看 6.0/Phase 5 报告、相关 Application/Adapter/Interface/脚本与 schema；只新增本 UTF-8 文档。项目根 `D:\Codex\grokbuddy` 无 `.git`；嵌套 checkout `var/phase35-repo` 只读 `git status` 为 `phase4-step6-probe`、无工作树修改，未触及 `main`。未改状态机代码、真实业务 Task 或 Hub DB；未跑正式 E2E、未进 6.1 Trigger 实现、未实施 Named Tunnel、未调用 Grok/GitHub 写入。所有 worker 合同与探针均 **NOT IMPLEMENTED / NOT RUN**，外部自动 intake 与稳定入口均 **ENVIRONMENT_VALIDATION_REQUIRED**。

### 静态自检记录

只读命令包括 `rg -n "dispatch-once|event-once|timeout-once" scripts/grokbuddy_grok.py`、`rg -n "project-github-once|bind-pr" scripts/grokbuddy_github.py`、`rg -n "dispatch_one|handle_one|project_one|enqueue_final_review|list_pending_review_requests" src/grokbuddy scripts -g '*.py'`，并逐文件 `Get-Content` 上述源码、`schema.sql` 和两份前置报告。`git -c safe.directory=D:/Codex/grokbuddy/var/phase35-repo -C var/phase35-repo status --porcelain=v1` 输出为空，`branch --show-current` 输出 `phase4-step6-probe`。对本文件执行严格 UTF-8 解码、必需 marker 与本地 Markdown 链接检查：解码通过、无 BOM、缺失 marker 0、失效本地链接 0、P01–P13 探针 13 条。未运行 pytest 或任何业务/外部服务探针；这些静态检查不能证明 supervisor、Grok 自动接单或零人工 E2E 已运行。
