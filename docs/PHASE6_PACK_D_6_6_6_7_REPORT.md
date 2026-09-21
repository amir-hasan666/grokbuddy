# Phase 6 Pack D — Step 6.6 Supervisor + Step 6.7 Recovery / Idempotency

`PHASE6-STEP6.6-SUPERVISOR: PASS`

`PHASE6-STEP6.7-RECOVERY-IDEMPOTENCY: PASS`

日期：2026-09-21（Asia/Shanghai）

判定范围：本报告证明 Hub 内建 supervisor 的逻辑、可测驱动和 P01–P12 隔离探针通过；所有测试均使用 disposable SQLite、content-addressed Artifact Store、受控时钟和 mock transport。没有启动 Named Tunnel、Windows 服务或真实 Grok/WorkBuddy/GitHub E2E，没有修改真实 Hub DB。`Pack D PASS ≠ 6.8/6.9/6.19/6.20 PASS`。

## 1. Goal / 授权边界

本 Pack 将 6.2–6.5 已有持久化锚、CAS、v2 Review APPLY、同 Task assignment 和 Human Gate 组合成自动调度循环，并用恢复/幂等探针验证重启、重复、lease、网络不确定性、投影失败和 Gate freeze。Hub DB 继续是 Task、RR、Review、Finding、Artifact、Audit 和 verdict 的唯一事实源；GitHub 仅是 projection。

没有实施 6.8 Named Tunnel、6.9 Windows 自启/生产 readiness、6.19 staging soak、6.20 Real Final E2E；没有调用真实 provider、push remote、merge/approve、改 `main`、直接业务 DML 或恢复正式 `owner_id` claim。

## 2. Preflight 差距与落点

| 能力 | Preflight 已有 | Pack D 前缺口 | 本次落点 |
| --- | --- | --- | --- |
| Outbox | `READY/RETRY`、lease generation、delivery key、外呼后二次守卫 | `UNKNOWN` 不再对账；v2 失败仍走 legacy `ESCALATED/FAILED` | `UNKNOWN` 可恢复 claim；稳定 delivery key 先查询；不确定/重试耗尽保留真实 RR failure 并进入对应 Human Gate |
| Reviewer intake | Reviewer 单 RR read、`intake_receipts` 表 | 无自动 consumer/receipt 生命周期 | `ReviewerIntakeWorker` 自动发现 `SENT + active RR`，按 actor/hash 持久 receipt、claim、ACK/UNKNOWN/FAILED；mock 由 supervisor 自动消费 |
| Event APPLY | 入口去重、持久 inbox、统一 APPLY、Late Event | 仅显式 `handle_one` 驱动；跨入口会重复 Artifact metadata | 纳入 supervisor；同 key 同 hash no-op，同 key异 hash conflict；跨入口保留 receipt 但复用 payload Artifact |
| Projection | Final APPLY 原子 `UNKNOWN` intent、marker upsert、lease fencing | 无自动 intent reconcile；模糊 create 走普通 retry | 自动把有 binding 的 intent 升为 READY；create 回执不明保持 UNKNOWN；marker 对账后复用同 Comment；不盲目二次 create |
| Timeout/recovery | deadline sweep、持久 lease | v2 timeout/dispatch failure 仍到 legacy escalation；assignment lease 不回收 | v2 Plan/Final 专用 Human Gate；RR 保留 `TIMED_OUT/FAILED`；过期 assignment 冻结并创建下一 generation |
| Binding/route | 幂等 PR binding、future Reviewer route | 正式链依赖手工 `bind-pr/route-task` | `BindingRouteWorker` 接受服务配置 policy，在 dispatch/projection 前自动、幂等 ensure binding/route；Gate/frozen task 不推进 |
| 调度 | `LocalRuntime.tick()` 一次迭代 | 无统一职责、无 bounded until-idle、错误域不隔离 | `Supervisor.tick/run_until_idle/run_forever`；六职责独立执行和错误记录；默认长期循环间隔上限 5 秒 |
| 恢复探针 | 既有局部 worker/Gate 测试 | P01–P12 未成套 | 新增 12 个命名隔离探针，覆盖竞争、重启、失回执、Gate、same-task 与 token rotation |

## 3. Step 6.6 Worker 职责

| 顺序 / Worker | 持久输入 | 行为与 fencing | 失败/冻结语义 |
| --- | --- | --- | --- |
| Binding / Route | Task + service policy + binding/route 表 | 自动 ensure immutable repo/PR binding；Grok Reviewer route 用稳定 command key | identity/route 冲突留错误；Gate、BLOCKED、终态和 `automation_frozen` 不处理 |
| Timeout / Recovery | Task/RR deadline、assignment lease | 短事务 timeout；CLAIMED lease 过期后旧 generation→FROZEN，再 OFFER 下一 generation | v2 到 `PLAN_HUMAN_REVIEW` / `FINAL_HUMAN_REVIEW`；不伪造 `NEEDS_CHANGES` |
| Outbox Dispatcher | `READY/RETRY/UNKNOWN/expired LEASED` | lease token + generation；外呼前/后守卫；UNKNOWN 先 reconcile；retry 复用 RR/delivery key | v2 耗尽 RR=`FAILED/TIMED_OUT` + Human Gate；legacy v1 行为兼容；`revision_round` 不变 |
| Reviewer Intake | `SENT` outbox + active RR + route + `intake_receipts` | `(source,deduplication_key)` 唯一；key 冻结 RR/input/profile/actor；consumer 不持 outbox lease | Gate/过期 receipt→FAILED；consumer unavailable→UNKNOWN/有界尝试，deadline 由 recovery worker裁决 |
| Event Apply | `READY` inbox | 统一现有 v2 structure/identity/hash/version/CAS 验证；同一 tick 自动 APPLY | Gate/终态/超时→LATE_EVENT；validation failure 不推进；跨入口不重复 Review/Finding/Artifact |
| GitHub Projection | Final intent `UNKNOWN/READY/RETRY/expired LEASED` | 自动补全 binding/body；固定 marker；find→update/create；lease generation | 模糊 create/过期 lease只 reconcile；失败不回滚 Review/DONE；有界失败单独留 projection/Audit |

`LocalRuntime.supervisor(...)` 是本 Pack 的隔离 composition root；`Supervisor.run_forever` 提供长期循环逻辑，`run_until_idle` 提供无 sleep 的确定性测试驱动。原 `LocalRuntime.tick()` 和 CLI `*_once` 未删除，只保留旧回归/debug；它们没有出现在本报告 P01–P12 / same-task 成功证据链中。

## 4. 关键语义

- v2 timeout、Reviewer failure 和 dispatch exhaustion 统一走 `review_failure_gate`：先终结真实 RR、取消未发送 outbox，再冻结对应 Plan/Final Human Gate。v1 历史行为保留。
- assignment claim 使用短 lease，不再占满整个 Task deadline；progress 续租；complete 必须持有未过期当前 lease。Recovery 冻结旧 generation，旧 worker 迟到写入被 CAS/fencing 拒绝。
- outbox `UNKNOWN` 和 expired lease 都先 `get_delivery_status(delivery_key)`；未知持续到有界次数后失败入 Gate，已确认 ACCEPTED 直接 SENT，不重复 submit。
- projection create 回执不明后状态为 `UNKNOWN`；后续只按 marker 对账。找到则复用同一 Comment；暂时查不到不会立即第二次 POST，耗尽后 projection 独立 FAILED。
- callback 首先检查 `(source,deduplication_key)+normalized hash`。同 key 同 hash 返回原 ingress；同 key 异 hash拒绝。跨 source 的相同 normalized event 保留第二 ingress receipt，但复用第一 payload Artifact metadata，APPLY 仍只产生一个 Review/Finding 集。
- intake ACK 只表示 Reviewer consumer 已取得工作，不改变 RR verdict；只有合法 event APPLY 才推进 Hub 状态。
- projection 可在 Review/DONE 已提交后安全追赶；其失败不改 Hub 真相。

## 5. Step 6.7 P01–P12 结果

测试文件：`tests/test_phase6_supervisor_recovery.py`。12 个 probe 全部使用隔离目录；autouse fixture 禁止外部网络。

| Probe | 注入/动作 | 关键断言 | 结果 |
| --- | --- | --- | --- |
| P01 duplicate claim / stale lease | 两线程同 assignment claim；lease 过期；旧 generation 迟到 CAS | 恰一 claim；旧 assignment FROZEN、新 generation OFFERED；旧写 `CONFLICT`；Task/RR 不重复 | PASS |
| P02 duplicate completion | 同 command key/hash complete 两次；同 key 改 Artifact | 原 receipt replay；一次 completion Audit；异 hash CONFLICT；Task 仍 EXECUTING | PASS |
| P03 duplicate callback/event | 同 key同 hash、跨 source同结果、同 key改 payload | 一份 payload Artifact、一 Review、一 Finding；跨入口第二 receipt=DUPLICATE；异 hash拒绝 | PASS |
| P04 Hub restart | RR+outbox commit 后重启；inbox commit 后重启；APPLY 后再重启 | 同 RR/round 恢复；inbox不丢；Review exactly once；已提交状态不倒退 | PASS |
| P05 Worker restart lease | claim/progress 后模拟进程停机与 lease expiry | restart recovery 产生下一 generation；旧 worker不能 complete；主 Task 保持 EXECUTING | PASS |
| P06 reviewer timeout/network | Reviewer 沉默；delivery status持续 UNKNOWN；UNKNOWN 后确认 ACCEPTED | RR真实 TIMED_OUT/FAILED + Plan Gate；无假 Finding/NEEDS_CHANGES；retry 不加 revision；确认 ACK 不二次 submit | PASS |
| P07 projection failure | Final DONE 后 remote create 成功但 receipt timeout；随后 marker 可见 | Hub DONE/Review COMPLETED 不回滚；UNKNOWN→SENT；create=1、Comment=1、同 ID复用 | PASS |
| P08 same key/same hash | create replay；自动 binding/route policy重复扫描 | 原 Task receipt；binding/route 各一；Artifact/Task数不增 | PASS |
| P09 same key/different hash | Artifact command key复用但 bytes 改变 | CONFLICT；Task/Artifact业务数量不变；安全 rejection Audit | PASS |
| P10 Gate freeze/late event | timeout Gate 后强置待投递 outbox并送迟到 Started | outbox CANCELLED；event=LATE_EVENT；无新 RR/dispatch；Task快照不变 | PASS |
| P11 same Task path | Plan PASS→assignment→Worker complete→Final PASS | 全链同 task_id；Worker complete 后非 DONE；Final PASS 才 DONE；Task总数=1 | PASS |
| P12 token rotation | 双 token overlap；撤销旧 token后重放 | overlap期新旧均认证；撤销后旧 token 401、新 token有效；Hub零 mutation；Audit无 secret | PASS |

## 6. Manual Glue 禁清单对照

| 禁止项 | Pack D 正式隔离证据链 |
| --- | --- |
| 人工 `dispatch-once` | 未使用；Supervisor 调用 Dispatcher |
| 人工 `event-once` | 未使用；Supervisor 调用 Event Apply |
| 人工 `project-github-once` / enqueue | 未使用；Final APPLY intent + ProjectionWorker 自动 reconcile/enqueue |
| 人工 `timeout-once` / 临时 resume 脚本 | 未使用；Recovery worker 扫描持久 deadline/lease |
| Reviewer “Test Run” | 未使用；ReviewerIntakeWorker 自动 poll mock queue并写 intake receipt |
| 人工 `bind-pr` / `route-task` | P07/P08 使用自动 policy worker；未调用 CLI |
| 人工复制 findings | 未使用；Finding 始终来自 Hub APPLY/查询 |
| 独立 NEW Worker / Final Task | 未使用；P11 全链 Task总数=1 |
| 手抄 hostname / Quick Tunnel | 未使用；无公网调用 |

Human Gate 的显式认证决策仍属于治理动作，不计作 glue；本 Pack 未自动替 Human 作 Gate 决策。

## 7. 修改文件

- Supervisor / recovery：`src/grokbuddy/application/workers.py`
- v2 Gate 共用失败路径：`src/grokbuddy/application/common.py`、`src/grokbuddy/domain/rules.py`
- Event ingress/APPLY：`src/grokbuddy/application/events.py`
- Assignment lease：`src/grokbuddy/application/worker_tasks.py`
- Projection UNKNOWN reconcile：`src/grokbuddy/application/github.py`
- Mock intake 定向消费/恢复：`src/grokbuddy/adapters/mock.py`、`src/grokbuddy/adapters/mock_queue.py`
- Runtime composition：`src/grokbuddy/infrastructure/runtime.py`
- Token overlap/revoke 契约：`src/grokbuddy/interfaces/grok_reviewer.py`
- 测试：`tests/test_phase6_supervisor_recovery.py`、`tests/test_phase3_github.py`
- 合同检查证据刷新：`docs/phase1-contract-checks.json`
- 报告：本文件

没有新增 schema 或第二事实源；复用 v4 `outbox_events`、`inbox_events`、`intake_receipts`、`github_comment_projections`、`worker_assignments`、command receipt 和 Audit。

## 8. 验证命令与结果

| 命令 | 结果 |
| --- | --- |
| `.\.venv\Scripts\python.exe -m compileall -q src\grokbuddy tests\test_phase6_supervisor_recovery.py` | PASS |
| `.\.venv\Scripts\python.exe -m pytest -q tests\test_phase6_supervisor_recovery.py` | 12 passed |
| 受影响组合（workers / 6.5 / Pack B / Grok adapter / GitHub / schema / Pack D） | 83 passed |
| 重复事件、Governance、projection 与 Pack D 收敛复核 | 46 passed |
| `.\.venv-phase0\Scripts\python.exe scripts\validate_phase0.py --allow-core` | 219/219 passed；external environment gate 仍 BLOCKED |
| `.\.venv\Scripts\python.exe -m pytest -q` | 772 passed（最终全量，以本报告提交前最后一次运行记录为准） |
| `git diff --check` | PASS；仅 Git 的 LF→CRLF 工作树提示，无 whitespace error |

补充：历史 Phase 0 专用模式不带 `--allow-core` 时为 218/219，仅 `phase0-no-core-source` 失败；当前仓库已处于实现阶段，该断言按设计不适用。正确的实现阶段 contract regression 是上述 `--allow-core` 219/219。

## 9. Architecture / Gate 判定

| Gate | 证据 | 判定 |
| --- | --- | --- |
| Hub 唯一事实源 | 所有 worker 只读/写既有 Hub 表；GitHub failure 不改 Review/DONE | PASS |
| D7 retry/round | P06；同 RR/delivery key 重试，revision_round=0 | PASS |
| D8 Human Gate freeze | v2 failure helper + P06/P10 | PASS |
| D9 completion | P11；Worker complete 仍 EXECUTING，Final PASS 才 DONE | PASS |
| D10 same-task/scope | assignment复用 approved Plan/scope；P11 单 Task | PASS |
| Manual Glue=0（隔离自动路径） | §6 操作链；Supervisor trace | PASS |
| P01–P12 | §5 12 probes | PASS |
| 当前账号真实 Reviewer 自动 intake | 本 Pack只验证 generic worker + mock consumer | ENVIRONMENT_VALIDATION_REQUIRED |
| Named Tunnel / service auto-start / real E2E | 未授权、未运行 | NOT RUN |

## 10. NOT WIRED / 停止点

- **6.8 NOT WIRED**：没有 Named Tunnel、稳定 PublicBase/DNS、真实 Reviewer consumer配置、secret manager 或 rotation runbook。P12 只证明 overlap/revoke 验票语义。
- **6.9 NOT WIRED**：没有 Windows 服务自启、进程管理器、生产 readiness、持久 metrics/告警或连续运行 soak。`run_forever` 只是可嵌入的进程内循环逻辑。
- 真 Grok/WorkBuddy/GitHub 自动接单、回传与投影未运行；当前账号能力仍为 `ENVIRONMENT_VALIDATION_REQUIRED`。
- 没有 6.19 staging Gate 或 6.20 Real Final E2E；没有将 mock/local 结果表述为 provider/production PASS。
- CLI `*_once` 与 `LocalRuntime.tick()` 仍仅 debug/旧回归；若出现在未来 6.20 正式成功 trace，Gate 必须 FAIL。

至此只完成 Pack D 6.6 + 6.7，并在该授权边界停止；不进入 Pack E。
