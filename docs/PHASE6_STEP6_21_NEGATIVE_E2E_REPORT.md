PHASE6-STEP6.21-NEGATIVE-E2E: IN PROGRESS / PARTIAL / BLOCKED

# Phase 6 Step 6.21 — Negative E2E / Production Guardrail Audit

日期：2026-09-23（Asia/Shanghai）

范围：Phase A 只读覆盖审计与已授权的 Phase B 最小实证。Phase B 已执行到 fail-closed 停止点：B、C、E 得到本轮证据，G 的本地专项闭合且现网隔离得到部分证据；活动 RR 在 Reviewer APPLY 前到达既定 deadline，F 与完整 G/I 未达接受标准。本文不宣布 6.21 PASS，不进入 6.22，不重开 6.20，不切换 Reviewer Bot，不修改生产 Hub DB，也不把 local/mock/debug 路径当作生产证据。

## 1. Phase A 结论

以下是 Phase A 结束时的审计起点；Phase B 实际结果与当前结论见第 10 节。

Phase A 结束时可以确认：

- 6.20 Real Final E2E 的既有 `PASS`、Reviewer Webhook Wake 的既有 `HUMAN RETEST PASS`、Reviewer Registry 的 `LOCAL PASS / WAITING HUMAN SWITCH DRILL` 均保持原结论；本报告不改写它们。
- 当前正式配置仍是 `runtimeDir=var/github-manual`、`publicBase=https://grokbuddy.amirhasan.top`、`reviewerActor=grok-reviewer-b`、Supervisor enabled。Hub 持久状态仍是唯一业务事实源。
- A–I 均能找到既有实现或自动化依据；没有审计出一个可直接判定为“运行时代码完全没有 guard”的 Case。
- 仍有三处未闭合证据：
  1. **B/F/G 组合生产证据缺口**：没有一条当前正式路径证据同时证明同 key replay、活动 RR 跨真实 Hub restart 恢复，以及第二个无关 Task 不被串写。
  2. **G 专项自动化缺口**：已有 claim/event/request 并发测试和跨 Task Artifact 拒绝，但缺少“两 Task 交错 + recovery/supervisor + 各自 side-effect 计数”的单一专项测试。
  3. **E 启动编码回归缺口**：`Start-GrokBuddyHub.ps1` 当前已对 service config 与 Reviewer registry 使用显式 `-Encoding utf8`，Human 已报告真实故障后恢复成功；现有测试尚未以含中文 `displayName` 的 registry 锁住该行为。
- 因此 Phase A 结束时 6.21 是 **AUDIT / IN PROGRESS**。当时证据足以避免重跑 A、D、H 和既有 6.20 成功链；不足以直接宣布 Negative E2E PASS。

本 Phase A 没有运行 pytest、没有启动/重启服务、没有调用 WorkBuddy/Reviewer/GitHub、没有读 Credential 值、没有对 `var/github-manual/hub.db` 执行 DML。证据来自仓库源码、测试断言、冻结合同、既有 Phase 报告，以及 Human 在本会话同步的非 Secret 预检摘要。

## 2. 证据等级与判定原则

| 等级 | 可证明范围 | 不能外推 |
| --- | --- | --- |
| 自动化 / 隔离 SQLite | Application/Domain guard、事务、CAS、幂等、lease、恢复算法 | 真实 WorkBuddy、Windows task、网络、当前 Reviewer、生产 restart |
| 静态配置 / 源码 | 正式入口配置、实现存在、fail-closed 分支存在 | 当前进程已加载、外部能力已工作 |
| 既有生产/E2E 报告 | 报告锁定日期、对象和路径的事实 | 未运行的负向 Case、之后的环境状态 |
| Human 当前预检 | Human 在 2026-09-23 同步的当前非 Secret 现场 | Codex 未独立重跑的原始输出、未覆盖的故障注入 |

正式 6.21 证据继续遵守 [Current Production Baseline](CURRENT_PRODUCTION_BASELINE.md) 与 [Manual Glue / Supervisor Contract](PHASE6_STEP6_0A_MANUAL_GLUE_SUPERVISOR_CONTRACT.md)：`LocalRuntime`、mock、`run_until_idle`、`*_once`、手工 POST wake、直接 UPDATE `hub.db` 只能是隔离测试或调试，不能成为 production-path PASS 证据。

## 3. A–I 覆盖表（Phase A 起点）

| Case | 已有自动化证据（路径 + 断言要点） | 已有生产 / E2E 证据 | 缺口 | 建议证据类型 | 风险 |
| --- | --- | --- | --- | --- | --- |
| **A Trigger Isolation** | `tests/test_phase6_trigger_gate.py:68-207`：无 trigger 0 mutation、精确 trigger 单 Task、终态后不 sticky、同 conversation 单活动 Task、伪造/过期/错 principal fail closed、并发创建恰一成功；`tests/test_phase6_workbuddy_ingress.py:64-175`：ingress 只暴露一个工具、缺 key/非 trigger/复用 key 异输入均无 mutation。 | `docs/PHASE6_STEP6_17_TRIGGER_ISOLATION_REPORT.md:9-13,71-115` 已锁定 Human + WorkBuddy A/B4/C PASS；`docs/PHASE6_STEP6_20_REAL_FINAL_E2E_REPORT.md:35-45` 证明当前正式 SoT 上的 6.20 Task owner 为 `workbuddy-ingress` 且无 transfer。 | 6.17 live DB 是历史 `var/workbuddy-mcp`，不是当前 SoT；但该 Gate 已冻结关闭，6.20 又证明当前 ingress owner 正式链，不能借 6.21 重开 6.17。 | **单测复用 + 引用既有生产证据**；不重跑现网 A/B/C。 | 低；主要风险是误把历史 DB 路径当成当前 SoT。 |
| **B Duplicate Event / Idempotency** | `tests/test_events.py:18-54,121-151`：同/跨 source completion 只 APPLY 一次、冲突 hash 不覆盖、并发 handler 一 Review；`tests/test_phase6_supervisor_recovery.py:92-146,309-343`：Worker complete replay、callback cross-source、command same key/hash replay、异 hash reject；`tests/test_persistence_artifacts.py:29-56`：receipt replay 不加 round、并发请求只建一 RR/outbox；`tests/test_phase3_github.py:204-237`：delivery/semantic dedup 与 delivery-id 冲突。 | 6.20 保留旧 timeout RR 且没有被后续 PASS 改写；wake 实弹的 Plan/Final 各只有一个 RR、一个 wake receipt、一个 HTTP intake 和一个 Review。它们不是故意 duplicate injection。 | 当前正式路径没有一次“同一正式 MCP 命令 + 同 idempotency key 重放”的只读 side-effect 对照；外部 webhook 对 `Idempotency-Key` 的故障重投语义仍未单独验证。 | **现网一条**，并入 B/F/G 合并演练；只能经正式 WorkBuddy/Hub MCP 重放，禁止手 POST。 | 高；重复 RR/Review、重复模型费用或重复外部 side effect。 |
| **C Invalid State Transition** | `tests/test_rules.py:9-15` 枚举所有未声明 Task edge 并拒绝；`tests/test_phase6_pack_b.py:243-265` 错 RR/旧 task version callback 不改 Task/RR/Finding；`tests/test_events.py:57-96` 冻结字段、坏 Reviewer、迟到 Started 均拒绝或 `LATE_EVENT`；`tests/test_phase6_human_gate_abort.py:48-80` stale version、错误 state、非 Human Gate 决策拒绝。 | 6.20 `docs/PHASE6_STEP6_20_REAL_FINAL_E2E_REPORT.md:69-74` 记录 Worker 未完成时 Final 请求被正式守卫拒绝；旧 RR 终态未复活。 | 尚无当前 6.21 专属的“非法命令前后 Task version/RR 数不变”生产快照。该缺口可在合并演练用一个低风险正式 MCP 负例补齐，不需要新框架。 | **单测复用**；Phase B 合并演练顺带做一条正式 invalid-state 调用。 | 高；非法边可能越过 Worker、Review 或 Human Gate。 |
| **D Permission / Actor Boundary** | `tests/test_persistence_artifacts.py:73-90`：provider identity 唯一、Builder 不能自审、跨 Task evidence 拒绝；`tests/test_governance.py:14-42,141-149`：非 Human 不能批准/waive/override；`tests/test_phase6_ingress_builder_drive.py:264-296`：非配置 Builder、Reviewer、未 claim Worker 均不能驱动 ingress Task；`tests/test_phase6_supervisor_recovery.py:387-408`：旧 token 撤销后 401 且 Hub 0 mutation。 | 6.17 首次误调普通 Hub `create_task` 得到 `PERMISSION_FAILURE` 且 0 Task；6.20 owner 始终为 ingress、Reviewer 为 B；wake 实弹两轮实际 actor 均为 `grok-reviewer-b`。 | Registry 报告已明确：当前 phase-one bearer credential 仍是共享 credential，未证明每个 Reviewer 可独立撤销。它是已知身份隔离边界，不等于当前 actor/route guard 缺失。 | **单测复用 + 引用既有生产拒绝/身份证据**；6.21 不做破坏性 token 试验。 | 高；self-review、owner transfer 或 Human 权限旁路。 |
| **E Reviewer Identity / Registry Guard** | `tests/test_phase6_reviewer_registry_routing.py:87-187`：restart 后只影响新 RR、旧 snapshot 不变、错 actor 拒绝、unknown/disabled/missing/malformed/secret-like/drift/composite startup 全 fail closed、正式默认为 B；`src/grokbuddy/infrastructure/reviewer_registry.py:23-145` 严格 UTF-8 loader、字段白名单、执行身份唯一、active enabled、路径与 service drift 校验。 | `docs/PHASE6_REVIEWER_WEBHOOK_WAKE_REPORT.md:96-106` 的真实 Plan/Final actor 均为 B；Human 当前预检同步 `registry validate ok`、`service.reviewerActor == activeReviewer == grok-reviewer-b`、`OPEN_RR_COUNT=0`。Human 还同步了启动时系统默认编码误读中文 `displayName` 导致 Hub 起不来，显式 UTF-8 修复后 restart、Ready 与 200/200/404 恢复；这是 fail-closed + recovery 候选证据，本 Phase A 未独立重跑。 | 不要求真实切 Bot。缺口是启动脚本 UTF-8 行为没有专项回归；另有共享 bearer 的已知隔离限制。 | **需最小代码修复（仅补回归测试）**：锁定两个 `Get-Content ... -Encoding utf8`，并用中文 `displayName` fixture 做 PowerShell JSON parse；不改 Registry 业务逻辑。 | 中高；错误编码会造成可用性故障，错误 active/identity 则可能错投 Reviewer。 |
| **F Crash / Restart Recovery** | `tests/test_phase6_supervisor_recovery.py:149-195`：RR/outbox、inbox、APPLY 三个重启点 exactly once，Worker lease 过期后新 generation、旧 completion 拒绝；`tests/test_events.py:134-151`：事务中途异常全部回滚且 inbox 保持 READY；`tests/test_workers.py:64-86,150-170`：dispatch 接受后崩溃对账、job lease 恢复、task deadline 重启不延长；`tests/test_phase6_supervisor_production_wiring.py:383-466` 覆盖 production lifecycle/readiness fatal fail closed。 | wake Human 复测曾完成正式 Hub restart 后 `supervisor=ok`；Human 当前预检又同步 UTF-8 启动失败后受控 restart 成功。本次 `OPEN_RR_COUNT=0`，因此这些现场只证明冷启动/恢复服务，不证明活动 RR 恢复。 | **关键缺口**：没有真实 `PENDING/READY/SENT` RR 跨 Windows Hub restart 后保持同一 RR/delivery key、无重复 Review/dispatch 的证据。 | **必须 Human / WorkBuddy 现网一条**，并入 B/F/G 合并演练。 | 高；丢任务、重复外呼、lease 穿透、状态倒退。 |
| **G Task Isolation / Concurrency** | `tests/test_phase6_trigger_gate.py:132-147,196-207`：同 conversation 并发只建一 Task；`tests/test_persistence_artifacts.py:38-45,82-90`：并发同命令只一 RR/outbox、跨 Task Artifact 拒绝；`tests/test_events.py:121-151`：并发 event handler 单 Review 且事务回滚；`tests/test_phase6_supervisor_recovery.py:58-90`：双 claim 只有一个成功、旧 generation fenced；`src/grokbuddy/application/grok_routing.py:130-139` 正式 Reviewer ingress 在入库前绑定 RR/task/review/route。 | 6.20 只证明一个 Task 的同 Task Plan→Worker→Final 链；没有两个生产 Task 重叠执行的隔离证据。 | 缺一个明确的两 Task 交错专项测试，也缺当前正式路径“Task A restart/replay 不改变 Task B”的证据。 | **需最小代码修复（仅补专项测试） + 必须 Human 现网一条**；两者都合并进同一 Phase B drill，不建并发框架。 | 高；跨 Task Artifact、Finding、RR、assignment 或 callback 串写。 |
| **H Review Loop Limit / Human Gate** | `tests/test_phase6_pack_b.py:268-317,409-424`：Plan 第 2 轮、Final 第 3 轮非 PASS 进入专用 Gate/freeze，合法验证后 PASS；`tests/test_phase6_human_gate_abort.py:48-195,225-294`：Human-only、CAS/idempotency、显式额外 budget、hard cap、Gate 中 dispatch/Worker/callback/timeout 全不推进；`tests/test_workers.py:129-170`：默认 2/3 末轮与显式 Human resume 不重置历史 round。 | 6.20 的 Plan round 1/2 保留 `TIMED_OUT`，经正式 Human Continue/预算治理创建 round 3，旧 RR 未复活，round 3 才由 B PASS；Final round 1 PASS。 | 未做一条真实 Reviewer 连续两次 `NEEDS_CHANGES` 的现网负例，但现有合同/自动化与 6.20 Human Gate 历史已覆盖关键 guard，不值得为矩阵强制制造不稳定 Reviewer verdict。 | **单测复用 + 引用 6.20 Gate 历史**；不新增现网循环。 | 高；无限自动修正、绕 Human Gate、旧 RR 复活。 |
| **I Forbidden Runtime Paths** | `tests/` 中使用 `LocalRuntime`/mock/`run_until_idle` 只能证明隔离算法，不能证明该 Case PASS；`docs/PHASE6_STEP6_0A_MANUAL_GLUE_SUPERVISOR_CONTRACT.md` 将正式链 forbidden path 定义为证据级硬失败。 | `docs/PHASE6_STEP6_20_REAL_FINAL_E2E_REPORT.md:20-31,87-116` 与 wake 报告 `108-119` 均由 Human 明确核定 Manual Glue=0，且未使用手 POST wake、mock、LocalRuntime、`*_once`、人工改库或临时 resume。 | 应用无法对本机管理员直接改 SQLite 做绝对防篡改；“未使用 debug/manual 路径”也不能由单测证明。每次 6.21 现网演练都必须保存入口/操作清单并把任一 forbidden path 视为整次证据 FAIL。 | **既有生产证据引用 + Human 现网操作清单**；无需新框架。 | 高；错误证据会把调试旁路冒充生产 guardrail。 |

## 4. Phase A 的证据分流：可直接引用、必须现网、最小修复

### 4.1 已足够引用，不建议重跑

- **A**：6.17 已冻结为 Trigger Isolation PASS；6.21 不重开。
- **D**：角色、owner、self-review、Human 权限与实际 B 身份已有自动化和真实路径交叉证据；不做破坏性 token/权限试验。
- **H**：默认 round、Gate freeze、Human Continue 及 6.20 历史 RR 已足够；不强迫真实 Reviewer 产生特定非 PASS verdict。
- **I 的既有 6.20/wake 成功链**：只引用其各自 Manual Glue=0，不把本地测试当生产证明。

**C** 的代码/自动化已足够；为了让 6.21 有一条当前 production negative 记录，可在 B/F/G 合并演练中顺带做一次低风险 invalid-state 调用，无需单独开窗口。

### 4.2 必须 Human / WorkBuddy 当前现网一条

只建议 **一次合并演练**，覆盖 B、C、F、G、I：

- 两个独立 WorkBuddy conversation 创建两个专用 6.21 测试 Task；
- Task A 的一个 Plan RR 在 Reviewer consumer 暂停窗口中保持 active，执行同 key 正式 MCP replay；
- Task B 只做一条不合法状态命令并保持业务快照不变；
- 在 Task A RR active 时执行受控 Windows Hub restart；
- 恢复原 Reviewer consumer 状态后，由当前 `grok-reviewer-b` 完成 Task A 的合法 Plan event；
- 只读核对 Task A 恰一 RR/Review，Task B 无串写，所有 delivery/receipt/actor/task_id 对应；
- 全程只用正式 ingress/hub、受控 restart、Reviewer B 和只读核验，Manual Glue=0。

如果 WorkBuddy 无法保证重复调用使用完全相同的 idempotency key，必须把 B 现网项记录为 **NOT RUN / BLOCKED BY CLIENT CONTROL**；禁止改用手工 HTTP、临时 Python 或直接数据库写入替代。

### 4.3 只需两条最小测试，不做大改

1. **E / UTF-8 launcher regression**：在现有 `tests/test_phase6_supervisor_production_wiring.py` 或 Registry 专项中，断言 service config 与 registry 两处读取均显式 UTF-8，并用中文 `displayName` fixture 通过 PowerShell JSON parse。现有实现修复不改。
2. **G / two-task isolation regression**：在现有 `tests/test_phase6_supervisor_recovery.py` 增一个两 Task 交错用例；Task A 做 duplicate/restart/apply，Task B 保持独立状态，断言两边 Task/RR/Review/Finding/Artifact/assignment/Audit 的 task scope 和数量。继续使用 disposable runtime；明确标注 local-only。

只有新增测试暴露真实缺陷时，才另行提出最小业务修复；Phase A 不预先假定需要改生产代码。

## 5. fail-closed 审计

### 5.1 已存在的运行时 fail-closed guard

- Trigger 缺 key、错 principal、过期/伪造 evidence、非自然语言命中均拒绝且不建 Task。
- 同幂等键异输入、同 event key 异 hash、已完成 Review 冲突结果均拒绝，不覆盖既有事实。
- 未声明状态边、旧 task version、错 RR/review/task/correlation、终态或 Gate 后回调均拒绝或隔离为 `LATE_EVENT`。
- Builder/Reviewer/Human/Worker 角色、provider identity、自审、owner/task scope 均有 Application guard。
- Registry 缺失、malformed、unknown/disabled active、secret-like 字段、service drift、重复 execution identity 均启动 fail closed；正式 default 不 fallback 到 mock。
- Supervisor fatal/陈旧周期/worker error 令 readiness 失败；v2 timeout/dispatch exhaustion 保留 RR 真实终态并进入对应 Human Gate。
- Human Gate 冻结新 RR、dispatch、Worker 及正常 callback APPLY；Human Continue 必须显式 budget/deadline/Audit。

### 5.2 未闭合但尚不能称为“缺 guard”

- UTF-8 是已修复、已 Human 恢复的启动可用性问题；缺的是回归测试，不是当前已知缺失分支。
- 两 Task 综合隔离缺专项证据；底层 task_id、Artifact scope、RR binding、CAS/lease guard 均存在，需用最小测试和现网一条验证组合效果。
- 活动 RR 真实 restart 缺生产证据；local recovery 已有，不能据此宣布 Windows runtime recovery PASS。
- OS 管理员直接改 SQLite 无法由应用层完全阻止。对 6.21 的 fail-closed 处理是：一旦使用直接 DML 或 debug/manual 路径，整次 production evidence 立即判无效，而不是试图“补日志后继续算 PASS”。

## 6. AUDIT 差异 / 文档漂移

以下差异以冻结 Phase 6 合同、现行 `docs/contracts/` 与符合合同的实现为准；Phase A 只记录，不修改这些历史/规范文件：

| 差异 | 当前审计判断 | 6.21 处理 |
| --- | --- | --- |
| `STATE_MACHINE.md` 仍是 Phase 0 表，未列 `PLAN_HUMAN_REVIEW` / `FINAL_HUMAN_REVIEW`，并把末轮未通过写为 `ESCALATED`。 | 与 `docs/PHASE6_STEP6_0_CONTRACT_REPORT.md` D7/D8、Phase 6 v2 实现及测试不一致；属于控制文档漂移，不是用旧表否定已冻结 v2 contract 的理由。 | 报告记录；本轮不改。未来若修文档需单独授权，不改历史 Phase 报告。 |
| `docs/TEST_MATRIX.md:T22/Demo 5` 仍以末轮未通过 `ESCALATED` 表述。 | 对历史 v1 可成立；对现行 v2 正常路径应是专用 Human Gate + freeze。 | 6.21 Case H 使用 Phase 6.0 contract、Pack B、6.5 与当前实现，不使用旧矩阵的 v1 结论冒充 v2。 |
| `docs/PROTOCOL_V1.md` 仍写“参考实现尚未编写”且只描述 v1，而 `review-result.schema.json`、Phase 6.0 D5 和当前实现已支持 v2。 | 文件标题限定 v1，但其中“当前实现不存在”的陈述已过时；这是协议导航/文档漂移。 | v1 历史不改写；6.21 v2 判定以 Phase 6.0 contract + `docs/contracts/review-result.schema.json` + EventService 语义校验为准。 |
| Human 矩阵写“自动修正最多 2 轮”，冻结合同写自动 Plan review 总上限 2、Final review 总上限 3。 | 按合同应理解为：Plan 初审后最多 1 次自动修订复审；Final 初审后最多 2 次自动修正复审。Human Continue 是另行授权，不属于自动突破。若“最多 2 轮”意指 Plan/Final 都只有 2 个 RR，则与冻结合同冲突，Phase A 不擅自改写。 | Phase B 按冻结的 Plan 2 / Final 3 执行；报告明确 `review_round` 与“修正次数”口径。 |
| `Start-GrokBuddyHub.ps1` 曾依赖系统默认编码读取含中文 Registry。 | 当前工作区静态检查已见两处显式 `-Encoding utf8`；Human 同步真实恢复成功。 | 补最小回归后再把该 incident 作为 E/F 6.21 证据，不改 Registry contract。 |

## 7. Phase B 最小执行计划（已授权并执行至 STOP）

### P0 — 授权与只读前置

Human 先明确授权本文第 8 节的有限范围。随后只读确认：

1. Registry validate 成功，`service.reviewerActor == activeReviewer == grok-reviewer-b`；不切 Bot。
2. 记录原 Reviewer poller/webhook routine 的启停状态；测试结束必须恢复原状。
3. `OPEN_RR_COUNT=0`；若非 0，停止，不与真实未决业务混跑。
4. Credential probe 只记录所需 Target 为 `PRESENT`，不读取/打印值。
5. local/public `health/ready/root = 200/200/404` 且 `supervisor=ok`。

### P1 — 两条最小自动化补证

1. 补 UTF-8 launcher regression。
2. 补 two-task interleaved isolation regression。
3. 仅运行新增测试及直接受影响的 Registry/Supervisor/Recovery 子集；通过后再决定是否需要全量回归。若测试暴露实现缺陷，停止 production drill，提交最小修复方案给 Human，不自动扩大代码范围。

### P2 — 一次 B/C/F/G/I 合并现网演练

1. Human 建立两个新的、命名清晰的 6.21 测试 conversation；分别经 `grokbuddy-ingress` 创建 Task A / Task B，记录 Task ID 与初始 version。
2. Human 临时暂停所有会抢先消费 Reviewer work 的既有 consumer（poller 与 webhook routine），仅形成受控短窗口；Hub/Supervisor 保持运行。不得删除配置或 Credential。
3. Task A 经正式 `grokbuddy-hub` 提交 Plan，并以 Human/WorkBuddy 可控的固定 idempotency key 创建 Plan RR；用完全相同输入和 key 重放一次。只读快照必须显示一个 command receipt、一个 RR、一个 review round、一个 outbox，无第二业务效果。
4. Task B 保持 `NEW`，经正式 `grokbuddy-hub` 尝试 `request_plan_review`；预期拒绝。只读快照必须显示 Task B state/version、RR/Review/Finding 数均不变，只允许安全 rejection Audit。
5. 在 Task A RR 仍 active 时，由 Human 执行既有受控 Hub restart；验收 local/public 200/200/404、`supervisor=ok`，并只读确认 Task A 的 RR ID、round、delivery key 和 Task B 快照均未改变，没有新增 RR/Review。
6. 恢复测试前记录的 Reviewer consumer 状态。当前 `grok-reviewer-b` 从正式 intake 获取 Task A RR 并回传合法事件；等待常驻 Supervisor APPLY，不运行 `run_until_idle`、`*_once` 或手工 POST。
7. 只读核对：Task A 恰一 RR/Review，actor/agent/server/run 与冻结 route 匹配；Task B 仍无 RR/Review/Finding/assignment；跨 Task Artifact/Finding 为 0；重复 ingress 如存在只能是 receipt 级 DUPLICATE，不能有第二 Review。
8. 通过认证 Human governance `close_task`/Abort 清理两条测试 Task；禁止 SQL 清理。恢复并复核原 poller/webhook 状态。

### P3 — 证据与停止条件

最小证据包只含非 Secret 摘要：Task/RR/Review/receipt/outbox/inbox ID 与状态、task_id 归属、before/after count/hash、restart 时间、ready 检查、Audit action、命令入口清单、Reviewer actor，以及 forbidden-path 计数为 0。

任一情况立即停止且不宣称 PASS：

- 不能控制同一 idempotency key；
- 有既有未决 RR 或无法隔离测试 Task；
- restart 后 RR/task/version/delivery key 漂移或产生第二 RR/Review；
- Task B 出现任何非预期业务 mutation；
- actor/route/registry 不再是 B，或 readiness 非 `supervisor=ok`；
- 使用了 LocalRuntime/mock/`run_until_idle`/`*_once`/手 POST/直接 DB DML/临时 resume；
- 为完成矩阵需要切换真实 Reviewer Bot。

## 8. Phase B 授权记录

Human 已在 2026-09-23 明确授权按 P0→P3 执行以下有限范围：

1. 只在 `tests/test_phase6_supervisor_production_wiring.py` 与 `tests/test_phase6_supervisor_recovery.py` 新增 E/G 两条专项测试；若暴露业务实现缺陷则先停下报告。
2. 建立并最终经 Governance Abort 清理两个 6.21 专用 Task；记录 Reviewer consumer 原状态并在 active RR 窗口执行一次受控 Hub restart。
3. WorkBuddy 经正式 MCP 做一次同 key replay 与一次 Task B invalid-state 调用；Codex 只读核验 Registry、Credential presence、health/ready、日志和 `hub.db mode=ro`。
4. 继续禁止 Bot switch、直接 DB DML、手 POST wake、debug once/LocalRuntime/mock 生产取证、修改 6.20/wake/baseline 结论、push、进入 6.22、改冻结协议/状态机或发明后续 Phase。

实际执行未超出上述边界；结果见第 10 节。

## 9. Phase A 实际操作、未验证项与停止点

### 9.1 实际只读检查

- 读取 `docs/CURRENT_PRODUCTION_BASELINE.md`、仓库 `AGENTS.md`、Phase execution / architecture / protocol / async workflow skills。
- 对照 `IMPLEMENTATION_PLAN.md`、`ARCHITECTURE.md`、`DATA_MODEL.md`、`STATE_MACHINE.md`、`docs/PROTOCOL_V1.md`、`docs/VERDICT_RULES.md`、`docs/ASYNC_REVIEW_SEQUENCE.md`、`docs/TEST_MATRIX.md` 与 `docs/contracts/review-result.schema.json`。
- 使用 `rg` / `Get-Content` 只读搜索 `tests/`、`src/`、`docs/PHASE6_*`、正式 service config、Registry 和 Windows launcher；检查当前 worktree，确认已有大量未提交现场并全部保留。
- 未运行测试或生产探针。既有测试结果只按对应历史报告的证据边界引用。

### 9.2 本 Phase 唯一写入

- 新增本报告：`docs/PHASE6_STEP6_21_NEGATIVE_E2E_REPORT.md`。

未修改：`docs/CURRENT_PRODUCTION_BASELINE.md`、`docs/PHASE6_STEP6_20_*`、`docs/PHASE6_REVIEWER_WEBHOOK_WAKE_REPORT.md`、任何源码/测试/配置/Skill、Hub DB 或 Artifact。

### 9.3 Phase A 结束时仍为 UNVERIFIED / NOT RUN

- 活动正式 RR 跨真实 Windows Hub restart exactly-once：**NOT RUN**。
- 两个正式 Task 重叠时的生产隔离：**NOT RUN**。
- 当前外部 webhook 对重复 `Idempotency-Key` 的远端去重：**UNVERIFIED**。
- 每 Reviewer 独立可撤销 credential：**UNVERIFIED / 当前实现未声称具备**。
- 真实 Reviewer Bot switch drill：**不在 6.21 范围，NOT RUN**。

Phase A 当时的停止点：报告初稿完成，状态为 `IN PROGRESS / AUDIT`；随后 Human 按第 8 节授权 Phase B。当前停止点见第 10.8 节。

## 10. Phase B 实际证据与结论

### 10.1 P0 只读前置

- Registry validator 返回 `ok`，service `reviewerActor` 与 registry `activeReviewer` 均为 `grok-reviewer-b`；本轮未切换 Reviewer Bot。
- 正式 SoT `var/github-manual/hub.db` 以 SQLite URI `mode=ro` 检查，演练前 `OPEN_RR_COUNT=0`。
- Human 在演练前确认 `grokbuddy-review-poller` 与 `GrokBuddy Reviewer Webhook` 均已暂停；这是本轮需恢复的原状态。
- 所需 Credential target 与 wake target 均只记录为 `PRESENT`，未读取或打印任何值。
- 演练前 local/public `health/ready/root=200/200/404`，readiness 为 `supervisor=ok`。

P0 满足开窗条件。沙箱内首次探针出现的 Credential missing、public `000` 和 Scheduled Task access denied 均由 Human 权限上下文的只读复核排除，不作为运行时故障证据。

### 10.2 P1 两条最小测试

只修改了获准的两个测试文件，未修改业务代码：

1. `test_windows_launcher_reads_service_and_registry_as_utf8` 锁定 launcher 对 service config 与 registry 的两处 `Get-Content -Raw -Encoding utf8 | ConvertFrom-Json`，并用中文 `displayName=workbuddy审核员` fixture 经 PowerShell 解析。
2. `test_p04b_two_task_interleaved_duplicate_restart_apply_isolated` 在同一 disposable runtime 中交错两个 Task；Task A 做同 key replay、dispatch/event、runtime restart 与 APPLY，Task B 的 Task/RR/round/Review/Finding/Artifact/assignment/Audit/event/outbox/inbox 快照保持不变。

首次只跑 UTF-8 新测时，临时 `.ps1` 被本机 ExecutionPolicy 拒绝；仅在测试子进程参数中补 `-ExecutionPolicy Bypass` 后通过。这不是业务实现缺陷，未触发业务代码修复。

| 验证 | 结果 |
| --- | --- |
| 两条新增测试（最终复跑） | `2 passed in 5.90s` |
| Production wiring + Registry routing + Supervisor recovery 直接相关子集（最终复跑） | `33 passed in 36.03s` |
| `git diff --check`（测试文件） | 通过；只有既有 LF→CRLF 提示 |

### 10.3 P2 对象与初始隔离

| 对象 | 标识 | 初始状态 |
| --- | --- | --- |
| Task A | `TASK-bf511286-567d-4c5d-91a8-92b200ebad4b`；conversation `f9fa2fdf-36fc-457f-a61b-14b535782b40` | `NEW / v0 / active_rr_id=null / owner_id=workbuddy-ingress` |
| Task B | `TASK-b1198dda-835c-49fd-ac02-5a4c020aceaa`；conversation `70c3cb74-ef94-4e13-9d14-49f08c55e3aa` | `NEW / v0 / active_rr_id=null / owner_id=workbuddy-ingress` |

Task B 初始 RR/round/Review/Finding/assignment/outbox/inbox 均为 0；初始完整快照 SHA-256 为 `43627374eadd3c1aa7cde0861f26eda17241f286b41f51e5bc8d573e822b134b`。两个 Reviewer consumer 均处于 Human 已确认的 paused 状态，Hub/Supervisor 保持运行。

### 10.4 B：正式同 key replay

Task A 经正式 `grokbuddy-hub` 依次提交 PLAN Artifact `ART-b2c76ad9-43a4-499e-a4bd-5cae55e04113`、`submit_plan(expected_version=0)`，再以固定 key `phase6-21-a-plan-rr-replay-v1` 调用 `request_plan_review(expected_version=2)` 两次。两次均返回同一 `RR-c68e2fcb-0e7c-4d08-815f-3d4b9067c71b / PENDING`。

随后的 `hub.db mode=ro` 核验显示：

- Task A 为 `PLAN_REVIEW_PENDING / v3`，active RR 为上述 RR；
- 恰一 `request_review` command receipt、一个 RR、一个 review round、一个 outbox；没有第二 RR、第二 round 或第二 outbox；
- outbox `OUT-0583cc47-b3e3-4c88-b1ba-e6927bf9e603` 为 `SENT / attempts=1`，delivery key 为同一 RR ID；
- 当时 Review/Finding 均为 0。

因此 B 的“正式 MCP 同 key、同输入重放产生恰一业务效果”已闭合。该结论不外推到外部 webhook 对 `Idempotency-Key` 的网络故障重投语义。

### 10.5 C 与 Task B 无串写

Task B 保持 `NEW / v0` 时，经正式 `grokbuddy-hub` 调用一次 `request_plan_review(expected_version=0)`，返回 `VALIDATION_FAILURE: Task cannot request this review`。只读核验显示拒绝后 Task B 仍为 `NEW / v0 / active_rr_id=null`，RR/round/Review/Finding/assignment/outbox/inbox 均为 0。

安全 rejection Audit 为 `COMMAND_REJECTED`、actor `builder`、operation `request_review`、code `VALIDATION_FAILURE`；该 Audit 的 `task_id=null`，因此只能按调用时间、actor、operation 与 code 归因，不能声称具有 task-bound attribution。后续 `close_task(expected_version=0)` CAS 成功进一步证明非法命令没有推进 Task B version。

Task A 的 replay、outbox 投递、restart 与 timeout 期间，Task B 的 state/version 与上述业务计数均未变化；未观察到跨 Task RR、Review、Finding、assignment 或 outbox 串写。

### 10.6 F/G/I restart 窗口与 STOP

restart 前 Task A 快照为 `PLAN_REVIEW_PENDING / v3`，同一 RR 为 active；RR/round/outbox 各 1，Review/Finding 为 0。RR 创建于 `2026-09-23 13:21:48.602089 +08:00`，既定 deadline 为 `13:36:48.599087 +08:00`。

Human 在 RR active 窗口执行 `Restart-GrokBuddyHubTask.ps1`：旧 PID `29680` 停止，新 PID `32084` 接管；约 `13:34:58` 记录 `GROKBUDDY_SUPERVISOR_STARTED`，`13:35:14` 探针确认 Hub task `Running / 267009`、local/public `200/200/404`、`supervisor=ok`。Registry 复核仍为 active Reviewer B。

但在取得 deadline 前的 post-restart SoT 接受快照之前，RR 于 `13:36:49.657800` 转为 `TIMED_OUT / REVIEW_TIMEOUT`，Task A 转为 `PLAN_HUMAN_REVIEW / v4`，HTTP intake 随后以 `INTAKE_NO_LONGER_CURRENT` 失败。此时仍只有原 RR、round、outbox 与 delivery key，没有第二 RR/Review；Task B 仍未变化。

这命中本报告第 7 节停止条件：post-restart 接受窗口内 Task/RR status 与 Task version 已因既定 deadline 合法推进，无法再证明“active RR 跨 restart 后保持不变并由 Reviewer B APPLY”。时间线表明 timeout 发生在 restart 恢复之后约 95 秒，**不支持把 timeout 归因为 restart 实现缺陷**；但证据已经不可恢复地不足，故未恢复 Reviewer、未补建 RR、未 Human Continue、未运行 APPLY。

本轮已执行步骤的操作清单中，手 POST wake、直接 DB DML、LocalRuntime/mock/`run_until_idle`/`*_once`、临时 resume、Bot switch 均为 0；测试中的 disposable runtime 只作为本地自动化证据。由于正式 Reviewer event/APPLY 未发生，F、完整生产 G 与完整 I 不满足组合验收。

### 10.7 Governance Abort 与最终只读状态

Human 通过正式 `grokbuddy-hub.close_task` 各调用一次完成清理：

| Task | Abort 输入与结果 | 最终业务计数 |
| --- | --- | --- |
| A | `expected_version=4`，`v5 / CANCELLED / gate_reason=TASK_CANCELLED / escalation_reason=REVIEW_TIMEOUT / completion_basis=null / active_rr_id=null` | RR 1、round 1、Review 0、Finding 0、outbox 1、assignment 0 |
| B | `expected_version=0`，`v1 / CANCELLED / gate_reason=TASK_CANCELLED / completion_basis=null / active_rr_id=null` | RR 0、round 0、Review 0、Finding 0、outbox 0、assignment 0 |

最终 `hub.db mode=ro` 复核 `OPEN_RR_COUNT=0`。两个 Task 均为 Human governance Abort，不是 Reviewer PASS；Task A 的 `REVIEW_TIMEOUT` 历史未被覆盖。command receipts 显示两个 Task 各一条 Human `cancel`，A 仍只有一条 Builder `request_review` receipt。

演练前两个 consumer 的原状态就是 paused；Human 明确回报两个会话均未恢复 consumer，因此没有额外状态切换需要回滚。该状态是 Human 现场确认，不冒充 Windows Scheduled Task 证据；这两个 routine 在 `Get-ScheduledTask` 中不存在。

### 10.8 A–I 缺口闭合与最终判定

| Case | Phase B 后状态 | 判定依据 |
| --- | --- | --- |
| A Trigger Isolation | 既有证据继续引用 | 6.17 冻结 PASS 与 6.20 ingress owner 正式链未重开。 |
| B Duplicate / Idempotency | **CLOSED（本轮现网）** | 同 key/同输入返回同 RR；只读确认恰一 receipt/RR/round/outbox。 |
| C Invalid State | **CLOSED（本轮现网）** | `NEW` Task 正式拒绝，state/version 与业务计数不变；rejection Audit 存在但 task_id 归因受限。 |
| D Permission / Actor | 既有证据继续引用 | 未做破坏性 token/权限试验。 |
| E Registry / UTF-8 | **CLOSED（授权范围内）** | Registry/service 均为 B；中文 fixture 与两处 UTF-8 launcher 回归通过。 |
| F Crash / Restart | **BLOCKED / NOT ACCEPTED** | restart 与 readiness 成功，但没有 deadline 前 post-restart SoT 快照，且 RR 在 Reviewer APPLY 前 timeout。 |
| G Task Isolation | **LOCAL CLOSED；PRODUCTION PARTIAL** | 新专项测试通过；现网 B 未串写且 A exactly-once，但缺少 A 的合法 Reviewer APPLY 终点。 |
| H Review Loop / Human Gate | 既有证据继续引用 | 本轮未制造 Reviewer verdict；timeout 后未用 Human Gate 冒充 PASS。 |
| I Forbidden Paths | **本轮已执行部分满足；完整组合 BLOCKED** | Manual Glue=0、禁止路径计数 0；但正式 Reviewer event/APPLY 未完成，不能以操作合规替代 E2E 完成。 |

停止条件命中项是：活动 RR 的既定 deadline 在 post-restart 取证窗口内到期，导致 RR status 与 Task state/version 在验收前推进；F/G/I 组合链无法继续。未观察到第二 RR/Review、Task B 串写、actor/route 漂移、readiness 失败或禁止路径使用。

**最终结论：`IN PROGRESS / PARTIAL / BLOCKED`，不得写 PASS。** 两条新增测试与 B/C/E 证据成立，但“B/C/F/G/I 现网 + 两条测试全部达标”的 PASS 条件未满足。未暴露可归因于业务实现的新缺陷，因此本轮不提出或自动实施业务代码修复。若要重跑未闭合部分，必须取得新的明确授权；本报告不进入 6.22，也不发明后续 Phase。

## 11. Phase 6.21-B2 后续演练记录（活动 RR 跨重启证据无效）

Human 回报 B2 使用测试 Task `TASK-c2d9705a-0243-4ddf-a9dc-8477a832b1c3` 和 Plan RR `RR-e7ca0866-cc45-4b2d-a504-01dd1eecf98c`；真实 Hub restart 的 PID 从 `32084` 变为 `41060`。PID 变化及 restart 先后顺序来自 Human 现场回报。正式 SoT `var/github-manual/hub.db` 经 SQLite URI `mode=ro` 独立确认：

| 证据 | B2 只读结果 |
| --- | --- |
| Task | `PLAN_APPROVED / v4 / active_rr_id=null / owner_id=workbuddy-ingress` |
| RR | `COMPLETED`，Plan round 1，`REVIEWER_HTTP`；完成时间 `2026-09-23 14:54:55.730496 +08:00` |
| Review | `REV-efbbba59-8e86-47ee-94d2-7a47b22a1523`，`reported_verdict=effective_verdict=PASS`，actor `grok-reviewer-b` |
| Delivery / apply | 同一 RR 的 outbox `SENT / attempts=1 / delivery_key=RR ID`；inbox `APPLIED` |
| 开放请求 | 取证时 `OPEN_RR_COUNT=0` |

Human 确认 Review 在真实 Hub restart 前已完成，故本轮标记为 **`INVALID FOR ACTIVE-RR-RESTART TEST / REVIEW COMPLETED BEFORE REAL RESTART`**。这条 Review PASS 是该 Task 的真实历史事实，但不构成 Case F 的活动 RR 跨 restart PASS；6.21 与 6.21-B2 均不得判 PASS。上述历史 RR、Review、Ingress 和 Audit 均保留，禁止通过数据库清理或改写。

B2 清场已完成。Human 回报在受信 WorkBuddy 会话经正式 `grokbuddy-hub.close_task` 仅调用一次，输入 `expected_version=4`、key `phase6-21-b2-abort-completed-before-restart-v1`，原因为 `Phase 6.21-B2 active-RR restart test invalid: review completed before real Hub restart.`。随后 `hub.db mode=ro` 独立复核：

| 清场核验 | 结果 |
| --- | --- |
| Task 终态 | `CANCELLED / v5 / gate_reason=TASK_CANCELLED / active_rr_id=null / completion_basis=null`；`automation_frozen=true`、`grokbuddy_enabled=false`、`context_invalidated_by=human`、`context_invalidation_reason=ABORT` |
| Human 治理留痕 | 该 Task 有一条 `operation=cancel / actor_id=human` 的 command receipt；Audit 保留 `CANCEL` 与 `STATE_CHANGED`，actor 均为 `human` |
| 历史保留 | 原 RR `COMPLETED`、Review `PASS`；该 Task 仍有 RR 1、round 1、Review 1、outbox 1、inbox 1；原 RR 关联 intake 收据 2、Task Audit 25；未删除或覆盖历史 |
| 开放请求 | 清场后 `OPEN_RR_COUNT=0` |

这次 `CANCELLED` 是 Human governance Abort；原 Review 的 PASS 只说明重启前审核已完成，不能将 6.21-B2 判为活动 RR 跨真实重启 PASS。报告状态继续保持 `IN PROGRESS / PARTIAL / BLOCKED`。

## 12. Phase 6.21-B2 第二轮：活动 RR 跨真实重启恢复

本节记录与第 11 节不同的新 Task `TASK-7ed3b5c6-75a5-40a8-a2b1-7d0b60c53c4f`、新 RR `RR-6611730c-bd87-497b-a487-d53a882f4abc`。Human 指定本轮 Reviewer wake consumer 为 **`grokbuddy-review-poller`**；这项消费者选择来自 Human 现场回报。Webhook routine 为制造重启窗口而主动暂停，原 `grok-reviewer-webhook-wake` 收据的 `FAILED` 是该受控窗口现象，**不是本轮 Webhook 执行成功证据，也不据此认定生产 Webhook 故障**。Webhook 正常可用性的既有结论仍只见其独立报告。

### 12.1 重启前、真实重启及即时快照

- Human 重启前记录 Task 为 `PLAN_REVIEW_PENDING / v3 / active_rr_id=RR-6611730c-bd87-497b-a487-d53a882f4abc`；RR 为 `PENDING`、Review 0、APPLIED event 0，delivery key 为同一 RR ID，冻结 `expected_task_version=3`、expected reviewer 为 `grok-reviewer-b`，deadline 为 `2026-09-23 15:39:58.062381 +08:00`。
- Human 执行正式 Hub restart，报告 PID `41060 → 40920`、script ExitCode `0`、`Ready=True`、`Supervisor=ok`。本机只读进程查询显示新 PID `40920` 的启动时间为 `2026-09-23 15:28:48.425007 +08:00`。
- `2026-09-23 15:30:32.913191 +08:00` 的 `hub.db mode=ro` 一致性快照显示同一 Task 仍为 `PLAN_REVIEW_PENDING / v3`、同一 RR 仍为 active 且 `PENDING`；该 Task 仅 1 个 RR，outbox `SENT / attempts=1 / delivery_key=RR ID`，RR 与 envelope 的 `expected_task_version` 均为 3，expected reviewer 仍为 B。Review 0、结果 inbox 0、APPLIED Audit 0，`OPEN_RR_COUNT=1`；距 deadline 约 565 秒。即时判定为 `POST-RESTART ACTIVE-RR SNAPSHOT VALID`。

### 12.2 Poller 唤醒后的正式 Reviewer 结果

随后对同一正式 SoT 的只读复核取得：

| 核对项 | 结果 |
| --- | --- |
| RR 唯一性与终态 | 该 Task 仍只有原 RR 1 条，最终 `COMPLETED`、Plan round 1、`review_id=REV-7b0411be-5a5b-4897-b784-a194b6ec287a`；`REVIEW_TIMED_OUT` Audit 0 |
| Review 唯一性与身份 | Review 恰 1 条，`reported_verdict=effective_verdict=PASS`、`reviewer_actor_id=grok-reviewer-b`、task_id/RR ID 均与原请求一致 |
| 认证结果事件 | 唯一 inbox `IN-6bea1f04-0192-4d93-b887-aed5b18dfa28`：`event_type=ReviewCompleted`、`event_id=EVT-b66cd9fe-17e9-45cc-a46b-87cbe61ff4ab`、source `grok_bot`、actor B、task_id/RR ID/review_id 均匹配，最终 `APPLIED` |
| APPLY 去重 | 对应 Task 的 `REVIEW_COMPLETED` Audit 1、`APPLIED` Audit 1；Review 1、inbox 1；同一 RR 的 Review/outbox/inbox 跨 Task 记录数 0 |
| Task 推进 | `PLAN_REVIEW_PENDING / v3 → PLAN_APPROVED / v4`，`active_rr_id=null`，approved Plan 已记录；这是同一 RR 的正常 Review APPLY 结果 |
| Delivery / intake | 原 outbox 仍为 `SENT / attempts=1 / delivery_key=RR ID`；HTTP intake `ACKED`，受控暂停期间的 webhook wake 收据 `FAILED` |

时间顺序均晚于新 PID `40920` 的启动时间 `15:28:48.425007 +08:00`：`ReviewCompleted` inbox 收到于 `15:37:49.233369`；Review 创建于 `15:37:51.579306`，RR 完成于 `15:37:51.580311`；`REVIEW_COMPLETED` Audit 为 `15:37:51.581552`，`APPLIED` Audit 为 `15:37:51.582795`。RR 既定 deadline 是 `15:39:58.062381`，故完成早于超时。已知其他 6.21 测试 Task 仍保持原 `CANCELLED / v5`、`CANCELLED / v5`、`CANCELLED / v1`；未见本轮 RR 关联记录串写其他 Task。

**B2 判定：`B2 ACTIVE-RR RESTART RECOVERY EVIDENCE COMPLETE`。** 证据覆盖活动 RR 在真实 Hub restart 后保持同一身份、delivery key 与冻结版本，并由真实 Reviewer B 经本轮 poller wake 完成同一 RR、由常驻 Hub APPLY 一次。该判定仅关闭 B2 的活动 RR 重启恢复证据；不把 poller 记为 Webhook wake，不改变第 11 节第一轮无效事实，也**不宣布整个 Phase 6.21 PASS**。报告总状态继续为 `IN PROGRESS / PARTIAL / BLOCKED`。

## 13. Phase 6.21 G/I 本轮 Task B S0 哨兵基线口径更正

Human 确认：执行卡中“Task B 无 Artifact”的断言过严。正式 `grokbuddy-ingress` 建单会生成两条建单期 `SOURCE_FILE`；本次只修正 Case G 对 Task B 的验收断言，不改变系统行为、不重建 Task B，也不改写此前 Phase B/B2 证据或 6.21 总状态。

`2026-09-23 16:14:11.536830 +08:00` 从正式 `hub.db` 以 SQLite `mode=ro`、`query_only` 和单一只读事务取得 S0：Task B `TASK-7fcc085d-f10d-42c2-9df6-25e434782ba6` 为 `NEW / v0 / active_rr_id=null`，deadline 为 `2026-09-24 16:10:18.220274 +08:00`。Artifact 恰有两条，均为 `workbuddy-ingress` 建单期 `SOURCE_FILE`：`ART-9b558a83-bd1c-4954-a574-9ffdab1f2665` 与 `ART-fd241ecb-b70e-4966-acfb-fa4c81696836`。RR、round、Review、Finding、assignment、outbox、inbox 均为 0；B 范围 Audit 恰有 3 条，均属正式建单行为。S0 stable snapshot SHA-256 为 `164336776cfdca4d6b93c253fbedeb63a96ee2a014cb098087625746bb4dd577`。

> B baseline contains exactly two ingress-created SOURCE_FILE artifacts; their ID set must remain unchanged from S0 through S4.

S0–S4 仍须保持 B 为 `NEW / v0 / active_rr_id=null`，上述 Artifact ID 集合不增不减，RR/Review/Finding/assignment/outbox/inbox 持续为 0，且不得出现由 A 的 replay、restart、Reviewer/APPLY 或 A Abort 引起的 B 范围新增业务 Audit/Event。后续 S1–S4 仅与这个 S0 基线比较，不再使用“Artifact 数量为 0”的旧断言。**`S0 VALID UNDER CORRECTED SENTINEL BASELINE`** 只确认 S0 口径，不构成 Case G/I 或整个 6.21 PASS；A 尚未由 Codex 推进，等待 Human。
