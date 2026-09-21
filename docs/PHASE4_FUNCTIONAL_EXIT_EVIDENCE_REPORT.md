# Phase 4 Functional Exit 证据报告

> **HISTORICAL：** 本文 `trycloudflare.com` PublicBase 只对应当次试跑。Phase 6 正式入口为 `https://grokbuddy.amirhasan.top`。

## 当前结论（2026-09-20，Asia/Shanghai）

**Phase 4 Functional Exit: PASS**

本结论针对 PR #4、Task `TASK-50157391-c538-4725-aa56-e607d279c4a3` 和新 Final Review Request `RR-ba6908f7-f5e2-4508-bf84-5b65aa962e78` 的本次真实 Grok 试跑。依据是本次提供的正式命令与 HTTP 回执，以及对本地 Hub `var/github-manual/hub.db` 的只读核对。此前的 **BLOCKED AT ROUTING** 是 2026-09-20 13:40（Asia/Shanghai）时旧 Mock RR 的历史结论，原检查记录保留在文末；它不再代表当前 Functional Exit 状态。

### 探针、身份和运行时

| 项目 | 本次证据 |
|---|---|
| GitHub 探针 | [PR #4](https://github.com/amir-hasan666/grokbuddy/pull/4)：head=`phase4-step6-probe`，Open，base=`main`；本次按提供的试跑记录列示，未在本次文档更新中重新请求 GitHub。 |
| Hub 关联 | Task `TASK-50157391-c538-4725-aa56-e607d279c4a3`；新 Final RR `RR-ba6908f7-f5e2-4508-bf84-5b65aa962e78` 走真 Grok 路径。旧 Mock RR `RR-a5b8e603-58f9-46b6-a4f5-f6927fd18ec7` 经正式 TimeoutService 转 `TIMED_OUT`，没有改写成 Grok 完成。 |
| 服务与公网入口 | 当次 Tunnel hostname：`mental-reader-publicity-nil.trycloudflare.com`；composite：`127.0.0.1:8788`；本地及公网 `/health` 均为 HTTP 200；`/reviewer/*` 无 token 为 HTTP 401。这是当次运行时证据，不保证临时 Tunnel 此后持续可用。 |
| Reviewer B | Hub actor `grok-reviewer-b`；Grok Bot `workbuddy审核员`；agentId `4335c388-584c-434e-b14e-13964b176b6e`；serverId `3504754`。只读 Hub 核对 actor 与新 RR envelope 均指向该 B。 |
| Secret 配置 | User 环境已配置 `GROKBUDDY_GROK_REVIEWER_TOKEN`（及 webhook/MCP 相关）。本报告不记录任何 token 值。 |

### 闭环时序

以下顺序和回执来自本次正式命令/HTTP 试跑；Hub 中的持久化状态另在下文列明。

1. `retry-final` 创建新 RR，返回 `{"ok": true, "result": {"review_request_id": "RR-ba6908f7-f5e2-4508-bf84-5b65aa962e78", "status": "PENDING"}}`。
2. `dispatch-once` 将新 RR 的请求载体投递为 `SENT`。
3. 真 Grok 回传获得 HTTP **202**：`ingress_id=IN-276c5383-c772-43e4-bb24-bf2ddac3fd97`，`event_id=EVT-9d42d1cb-0503-47cc-a7b3-6e600bcff290`，`execution.run_id=t23u-20260920T071657Z`，结论 **PASS**。HTTP 202 表示入口接收；Hub 应用结果由下一步确认。
4. `event-once` 返回 `{"ok": true, "result": {"event": "APPLIED"}}`。
5. `project-github-once` 返回 `{"ok": true, "result": {"operation": "CREATED", "transport": "github-http"}}`。
6. 幂等再跑：`event-once` 返回 `{"ok": true, "result": {"event": null}}`，未第二次应用；`project-github-once` 返回 `{"ok": true, "result": {"operation": null, "transport": "github-http"}}`，未第二次 `CREATED`。

### Hub 只读交叉核对

本次以 SQLite `mode=ro` 读取本地 Hub，未执行直接 DB DML。新 RR 为 Final round 2、`COMPLETED`，其冻结 envelope 的 `expected_reviewer_actor_id=grok-reviewer-b`；Task 当前为 `DONE`。对应 Review `REV-e15fc6d9-7f77-43ed-a0c2-f70d134ed786` 的 `reported_verdict` 与 `effective_verdict` 均为 `PASS`，`reviewer_actor_id=grok-reviewer-b`，`execution_identity` 中的 agentId、serverId 和 runId 与上表一致。入站 `IN-276c5383-c772-43e4-bb24-bf2ddac3fd97` 的 eventId 与上述回执一致，`source=grok_bot`、actor 为 B、状态 `APPLIED`。新 RR outbox 为 `SENT`；对应 GitHub projection 为 `SENT`，记录 comment ID `5748362023`。旧 Mock RR 仍为 `TIMED_OUT`、`failure_code=REVIEW_TIMEOUT`。

### Exit 对照

| Exit 项 | 判定 | 证据范围 |
|---|---|---|
| 真 Grok execution | **MET** | 当次真 Grok HTTP 回传及 `execution.run_id`；Hub Review 留存 B actor 与同一 execution identity、PASS。 |
| Hub correlation / APPLIED | **MET** | 新 RR、Review、ingress、event ID 关联；`event-once` 为 `APPLIED`，Hub inbox 状态同为 `APPLIED`。 |
| 状态转换 | **MET** | 新 RR `PENDING` → `COMPLETED`，Task 当前 `DONE`；旧 Mock RR 保持 `TIMED_OUT`。 |
| GitHub projection | **MET** | 正式命令返回 `CREATED` / `github-http`；Hub projection `SENT` 并有 comment ID。 |
| replay / 幂等 | **MET** | 再跑 `event-once` 得 `event: null`，再跑 `project-github-once` 得 `operation: null`；这两次重跑未重复应用或创建。 |
| 未 merge/approve/改 `main` | **MET** | 本次试跑按授权保持 PR #4 Open、base=`main`，未执行 merge、approve 或修改 `main`。 |
| 未直接 DB DML 伪造 | **MET** | 使用正式 `retry-final`、dispatch、event、projection 路径；本次文档核对为只读；旧 RR 保留超时历史。 |

### 安全与证据边界

未用 Mock 冒充真 Grok Exit，也未恢复 poller 处理旧 Mock RR。Chat 输出不是 Source of Truth；Hub 持久化记录与正式命令输出才是本报告的依据。HTTP 202、GitHub 请求载体 `SENT` 各自只证明对应步骤，最终 PASS 依赖后续 `APPLIED`、Review/Task 状态和 GitHub projection 的闭环。本次仅更新此报告，不修改状态机或业务代码，也不启动 Phase 5/6。

---

## 历史检查点：旧 Mock RR 路由受阻（2026-09-20 13:40，Asia/Shanghai）

以下保留原报告的检查内容。文中“当前”“本轮”均指当时的旧 RR 检查点；其 **BLOCKED AT ROUTING** 与“未试跑”结论已被文首本次真实试跑的 PASS 取代。

检查时间：2026-09-20 05:40 UTC（Asia/Shanghai 13:40）。从用户给定的 Step 6 PASS checkpoint 继续；未重做 probe。本报告只判定 PR #4 / `TASK-50157391-c538-4725-aa56-e607d279c4a3` / `RR-a5b8e603-58f9-46b6-a4f5-f6927fd18ec7` 能否合法进入真实 Grok Functional Exit。

### 当时结论

**PHASE4-FUNCTIONAL-EXIT: BLOCKED AT ROUTING。** 当前 RR 不能由真实 Grok 合法接管并在 Hub 记录真实 Reviewer execution identity。原因是正式请求和 GitHub binding 都冻结/指定了本地 Mock 主体 `mock-reviewer`，运行时 dispatcher 只连接 `MockReviewerAdapter`，且仓库没有经过认证的 Grok 结果入口或待审请求改派命令。启动现有 `worker-once` 会把请求交给 Mock；让 Grok 声称为 `mock-reviewer` 则会制造虚假的执行身份。两者均不满足本次 Exit。

本轮没有 claim outbox、运行 Poller/Mock/Grok、提交 Reviewer event、投影 GitHub Comment 或修改 Hub 业务数据。RR 保持 `PENDING`；其冻结 review deadline 为 **2026-09-20 05:52:19.813954 UTC**。期限到达后应由既有 TimeoutService 按正式状态机处理，不能把迟到结果用于完成本 RR。

### 当时检查点与证据

| Gate | 现场证据 | 判定 |
|---|---|---|
| Step 6 探针 | 用户给定 Step 6 PASS；[PR #4](https://github.com/amir-hasan666/grokbuddy/pull/4) 只读查询显示 `open`、`merged=false`、head=`phase4-step6-probe`、1 commit、1 changed file；PR Conversation comment 列表为空 | 保留检查点；未重做 |
| Hub Task / RR | 以 SQLite `mode=ro` 查询 `var/github-manual/hub.db`：Task `FINAL_REVIEW_PENDING`、version 8、active RR 为本次 RR；RR `PENDING`、Final round 1、review ID `REV-2e55eaff-ac1d-4e24-b264-1e759ff26a0a` | PASS（只读当前态） |
| 冻结 Reviewer | RR envelope 的 `expected_reviewer_actor_id=mock-reviewer`；actors 记录 `reviewer_type=mock`、`provider_id=local:mock-reviewer`；PR #4 binding 的 `reviewer_actor_id=mock-reviewer` | **真实 Grok 路由 FAIL** |
| Dispatch 前状态 | 本次 outbox `READY`、attempts 0；无本次 mock job、inbox event、Review 或 Comment projection | 未触发；可证明本轮没有把 Mock 结果冒充 Grok |
| 运行时路由 | `LocalRuntime` 只注册 `MockReviewerAdapter`；`Dispatcher` 固定使用该 adapter；`tick()` 依次运行 timeout、dispatch、mock、event | **不能运行 worker** |
| 结果身份校验 | `EventService.handle_one()` 要求入站 actor 等于 RR 冻结 actor，结果 `reviewer.id/type` 又必须等于已认证 actor 的 id/type；Builder 同 provider identity 也拒绝 | 真 Grok 的 `grok_bot` 身份会被拒；伪装 Mock 不合法 |
| 真 Grok 当前账号 | 本机有 Grok Bot 进程，但未取得独立 B 的不可变 provider identity、可验证的 Routine/事件触发和回传证据。官方文档只说明可能的 schedule/event Routine，且 GitHub event integration 与普通 GitHub plugin 分离 | **UNVERIFIED** |
| 回归 | `python -m pytest tests/test_additional_boundaries.py tests/test_workers.py -q --tb=short`：`21 passed in 17.97s` | PASS（本地测试；不能证明真 Grok） |

路由与校验实现位置：[ReviewService](../src/grokbuddy/application/reviews.py)、[Runtime](../src/grokbuddy/infrastructure/runtime.py)、[Dispatcher](../src/grokbuddy/application/workers.py)、[EventService](../src/grokbuddy/application/events.py)、[GitHub binding](../src/grokbuddy/application/github.py)。冻结协议见 [REVIEW_PROTOCOL](../REVIEW_PROTOCOL.md)。官方 Routine 能力仅参考 [Grok Bot 文档](https://docs.x.ai/grok-bot/skills-routines-and-automations)，不能代替当前账号验证。

### 当时正式修复路径评估

1. **当前 RR 原位改派：不存在合法 Application 命令。** `expected_reviewer_actor_id` 是 v1 冻结审核输入的一部分，GitHub binding 亦已指定 Mock。直接改 DB、手改 provider ID、改 envelope 或让 Grok 冒充 Mock 会破坏请求/身份/审计边界。
2. **最小可审查的后续实现：**先验证独立 Reviewer B 的不可变 provider identity 与可用的受认证 Grok Bot trigger、artifact 读取、结果回传；再提供正式的 Reviewer 注册、按请求选择的可替换 adapter、认证 ingress 和 Application 级路由/审计。若要在未 dispatch 的 `PENDING` 阶段改派，须先设计显式 supersession 或重路由命令、幂等和审计，并保持旧请求历史。当前实现没有该状态迁移，不能在本轮即兴修改冻结 RR。
3. **现有状态机的恢复边界：**本 RR 超时后，`TimeoutService` 可将 RR 置 `TIMED_OUT`、Task 置 `ESCALATED`；已有 `GovernanceService.resume` 只能由 Human 用新的期限和轮次预算显式恢复，之后才可创建新 RR。那不是本次 RR 的真实 Grok 完成，也不能拿来冒充本次 Functional Exit。

### 当时 Exit 判定

| 所需证据 | 状态 |
|---|---|
| 真实 Grok execution 与独立 B 身份 | BLOCKED |
| Grok 结果的 Hub ingress、冻结字段/身份 correlation | NOT RUN |
| `PENDING` → 合法事件 → `COMPLETED` 与 Task 状态转换 | NOT RUN |
| GitHub PR #4 marker/pointer Comment projection | NOT RUN |
| 同一入站结果 replay、重复投影及幂等 | NOT RUN |

未创建/关闭/合并/批准 PR，未修改 `main`，未执行直接 DB DML，未伪造 Reviewer 结果。当前只有只读现场与本地回归通过，**不能签发 Phase 4 Functional Exit PASS**。
