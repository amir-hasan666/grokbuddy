PHASE6-STEP6.3-REVIEW-APPLY: PASS

PHASE6-STEP6.4-LOOP-SAME-TASK-WORKER: PASS

日期：2026-09-21（Asia/Shanghai）  
范围：PHASE6-PACK-B，仅 Step 6.3 + Step 6.4。本报告不代表 6.5、6.6、6.19 或 6.20 PASS。

# Phase 6 Pack B — Review APPLY + Plan/Final Loop + Same-Task Worker

## 1. Goal 与执行边界

本 Pack 在 Step 6.1 Trigger Gate 和 Step 6.2 v4 persistence foundation 上完成两条业务边：

1. v2 Plan/Final Review Result 以不可变原文 Artifact 和不可变 Review snapshot 经 Hub APPLY；统一 actionable Finding 语义、入口级去重、按 Task/RR 查询和 Final projection intent。
2. 同一 `task_id` 串起 Plan → Review → `PLAN_APPROVED` → `EXECUTING` → Worker assignment → self-test/Final package → Final Review → `DONE`，并实现 revision/review round 与 approved scope 守卫。

本轮只使用隔离 `tmp_path` SQLite 与本地 Artifact Store；pytest 自动禁止外网。没有修改真实业务 Hub DB、真实 Task、`main` 或嵌套探针分支；没有调用 Grok、WorkBuddy、GitHub、Named Tunnel 或生产系统。

## 2. Preflight 差距表（动手前）

| 范围 | 已有能力 | Pack B 缺口 | 本轮结果 |
| --- | --- | --- | --- |
| v2 Review/APPLY | v1 Plan/Final 分裂 schema；EventService 可原子写 Review/Finding/Task | 新 RR 未使用 v2；Plan 无 Finding；缺 `expected_task_version`；`NEEDS_CHANGES` 可空 finding | 新 Phase 6 Task 固定 v2；Plan/Final 共用必填 evidence/risks/recommendations/proposed changes/findings/verifications；空 actionable finding fail closed |
| ingress 去重 | APPLY 阶段有 `processed_events` | 先建 Artifact 再判重；重复 ingress 新建元数据 | 使用现有 Inbox receipt key 先判 `source + deduplication_key + normalized hash`；同 key/同 hash no-op，同 key/异 hash reject |
| Finding 查询 | `list_findings(task_id)` | 无正式 actionable 查询及 RR 冻结范围 | `list_actionable_findings(task_id, review_request_id=None)` 返回 Hub 当前未关闭投影；Review snapshot 冻结 actionable IDs |
| Projection | 已有 6.2 `github_comment_projections` 和独立 projector | Final APPLY 未原子确保 intent | v2 Final APPLY 同事务创建每 Review 唯一 `UNKNOWN` intent；现有 enqueue 可在 binding 就绪后升级该行，不创建第二 intent |
| 轮次/Gate | `review_round`、2/3 policy、两个 Gate 状态已可存 | v2 末轮仍走 legacy `ESCALATED`；`revision_round` 未接线 | Plan 第 2 轮、Final 第 3 轮非 PASS 写专用 Gate 并 freeze；Builder 实际提交修订才增加 `revision_round` |
| Same-Task Worker | v4 `worker_assignments`、CAS/generation/lease schema | Application/MCP 仍用 `NEW + owner_id` legacy claim | `PLAN_APPROVED → EXECUTING` 原子 offer assignment；Worker MCP claim/upload/progress/complete 使用 assignment，Task owner 始终为 Builder |
| Scope | Final finding/fix 已有旧流程 | approved scope 未冻结；Final fix 可直接 execute | Plan 冻结结构化 scope/hash；assignment 锚定 approved Plan/scope；Final fix 越界转 `PLANNING`，禁止 silent expansion |

## 3. Step 6.3 — v2 Review Result / Finding APPLY

### 3.1 合同与不可变快照

- `review-request.schema.json` 保留 v1，并接受 v2；v2 必须携带 `expected_task_version`。
- `review-result.schema.json` 保留历史 v1 两分支，新增统一 v2 分支。v2 对 Plan/Final 都要求：verdict、summary、reviewer、timestamp、evidence、risks、recommendations、proposed changes、findings、verifications；Finding 必须含 description/evidence/impact/recommendation/proposed changes/scope/status/actionable。
- `NEEDS_CHANGES` 在 schema 和 Application 两层要求至少一个可 action finding；缺字段、空 findings、关闭 finding 伪装为 actionable、同一结果同时 action/verify 同一 Finding 均拒绝。
- 原始 v2 JSON 以 `REVIEW_RESULT` content-addressed Artifact/hash 保存；immutable `reviews` 行同时保存 Hub-normalized `result_snapshot` 和新 Finding 的稳定 Hub `finding_id`。历史 v1 行不迁移、不重写。
- 新 Phase 6 Trigger Task 写 `review_protocol_version=v2`，后续 RR 不允许降级；legacy isolated-test Task 继续走 v1，保证历史兼容。

### 3.2 callback、去重与 CAS

- ingress 在任何 Artifact/Inbox 新建之前计算 receipt key 与 normalized hash；hash 包括 task/RR/review/correlation、actor、execution identity 和 payload。
- 同 key/同 hash 返回原 ingress ID，不新增 Artifact、Inbox、Review、Finding 或 Audit；同 key/异 hash 入口即 `CONFLICT`。
- APPLY 在同一短事务重验 actor、task/RR/review/correlation、冻结 input/profile/content revision、active RR、终态/Gate/freeze 和 `expected_task_version`。
- 迟到、终态、Human Gate 或冻结后的 callback 记 `LATE_EVENT`；错 RR/错 binding/错 task version 记 validation rejection，Task/RR/Finding 不倒退。
- 认证 Reviewer GET 对 v2 返回当前 Task state/version CAS anchor；持久化 request envelope 仍保持不可变。

### 3.3 actionable 查询与 projection intent

- `TaskService.list_actionable_findings(task_id, review_request_id=None)` 是机读 Hub 查询；按 RR 查询使用 immutable Review 的 `actionable_finding_ids`，不依赖聊天粘贴。
- v2 Final Review 每次成功 APPLY 均在同一 Hub 事务创建唯一 `github_comment_projections` intent；无 binding/supervisor 时状态为 `UNKNOWN`，不会外呼，也不会影响 Hub Review/Task 提交。
- 后续显式 enqueue 复用/升级同一个 intent；实际发送失败只影响 projection 行，不回滚已提交的 Review/DONE。自动 reconcile/常驻投影属于 6.6。

## 4. Step 6.4 — Plan/Final Loop + Same-Task Worker

### 4.1 Plan 与 round 语义

- v2 Plan submission 必须带结构化 scope；Plan PASS 冻结 `approved_plan_id`、scope 和 hash。
- 有效 `NEEDS_CHANGES` 后仅设置待修订标记；Builder 提交新的 Plan 或 Final package 时才增加 `revision_round`。重复 callback、dispatcher retry、timeout 本轮均不伪造 `NEEDS_CHANGES` 或 revision。
- Plan 第 1 轮 `NEEDS_CHANGES` → `PLAN_CHANGES_REQUIRED`；修订再审可 PASS → `PLAN_APPROVED`。第 2 轮仍非 PASS/BLOCK → `PLAN_HUMAN_REVIEW`，写 `gate_reason` 并 `automation_frozen=true`。
- Plan PASS 如果仍有未 VERIFIED/WAIVED 的 Plan Finding 会拒绝 APPLY，不能默默遗留 OPEN/FIXED finding。

### 4.2 assignment Worker，不转移 owner

- v2 `PLAN_APPROVED → EXECUTING` 在同一事务创建 `worker_assignments` generation 1，冻结 approved Plan Artifact/hash、approved scope/hash 和可选 fix Finding IDs。
- Worker MCP 的 list/get/claim/upload/progress/complete 已走 assignment；claim/progress/complete 用 assignment version、lease generation 和 repository CAS。
- Worker upload 仅在同 Task、`EXECUTING`、未冻结且 assignment 已由该 principal claim 时开放。
- complete 写 assignment completion Artifact/hash/actor/time；不修改 `Task.owner_id`，不把主 Task改为 `DONE`。自检要求最新 assignment 已完成；Final fix assignment 还要求所选 Finding 有逐项 FIXED evidence。
- legacy `NEW + owner_id transfer` 只在显式 `legacy_worker_test_mode=True` 的历史测试中保留，正式默认仍 fail closed。

### 4.3 Final、scope 与完成依据

- Final package 的 changed files 必须属于 approved Plan scope。
- `FINAL_CHANGES_REQUIRED` 不能再走通用 `execute`；必须调用 `begin_final_fix` 并提交冻结 Finding IDs 与 proposed scope。
- scope 在 approved Plan 内：同 Task 回 `EXECUTING`，创建下一 assignment generation；scope 越界：写 scope-change request 并转 `PLANNING`，清除旧 approved Plan/scope，不创建新 Worker assignment。
- Final fix → Worker completion → Finding evidence → self-test/package → re-review 可 PASS → `DONE`，写 `completion_basis=FINAL_REVIEW_PASS`。
- Final 第 3 轮仍非 PASS/BLOCK → `FINAL_HUMAN_REVIEW` 并 freeze；本轮只证明 Gate 状态可持久化，不实现 Human 决策业务 API。

## 5. 隔离用例

`tests/test_phase6_pack_b.py` 共 12 个 pytest case（11 个函数，其中 1 个双参数）：

| 用例 | 关键断言 |
| --- | --- |
| v2 Plan APPLY/query | immutable raw/result snapshot、稳定 finding_id、按 RR actionable 查询 |
| 空 findings / 缺字段 | APPLY reject；Task/RR/Finding 无业务副作用 |
| ingress duplicate/hash conflict | 同 key/hash 不新增 Artifact/Inbox；异 hash 入口 reject |
| wrong RR / stale Task version | callback reject；Task/RR/Finding 不变 |
| Plan round/Gate/late event | Plan 2 轮上限、revision 只在修订时增加、Gate 后 late event |
| Plan revision PASS | 前轮 Finding 必须 FIXED 后由 Reviewer VERIFIED，第二轮才 PASS |
| same-task complete≠DONE | owner 不变；assignment complete 后主 Task 仍 EXECUTING；Final PASS 才 DONE |
| Worker MCP assignment | list/claim/upload/progress/complete 全部使用 v2 assignment |
| scope escape | 越出 approved scope 转 PLANNING，不创建下一 assignment |
| Final fix/re-review PASS | 同 Task generation 2、逐 finding evidence、Final round 2 PASS |
| Final round Gate | Final 3 轮上限、generation 1→2→3、`FINAL_HUMAN_REVIEW`、completion basis 仍空 |

旧 `test_events.py` 与 `test_phase4_grok_adapter.py` 的 duplicate 断言同步为入口 no-op；其余 v1/Phase 2–5 行为保持回归覆盖。

## 6. 验证证据

| 命令 | 结果 |
| --- | --- |
| `.\.venv\Scripts\python.exe -m compileall -q src\grokbuddy tests\test_phase6_pack_b.py` | PASS |
| `.\.venv\Scripts\python.exe -m pytest -q tests\test_phase6_pack_b.py` | 12 passed |
| 约定核心回归（Pack B + 6.1/6.2 + event/workflow/worker/GitHub/Grok/Phase 5/interfaces/rules） | 566 passed in 94.39s |
| `.\.venv\Scripts\python.exe -m pytest -q` | 613 passed in 121.69s（最终完成后复跑） |
| `.\.venv-phase0\Scripts\python.exe scripts\validate_phase0.py` | 218/219 contract checks passed；唯一失败为历史 `phase0-no-core-source`（当前仓库已进入实现阶段）；两个新增 v2 positive fixtures、meta-schema 与负向 required/unknown-field 检查均 PASS |

说明：Phase 0 validator 的 `phase0-no-core-source` 明确要求仓库不存在 `src/`，在 Phase 6 实现仓库必然失败，不作为 Pack B Gate。其余 218 项合同检查通过；`docs/phase0-checks.json` 已刷新为本次本地证据。所有 pytest 使用隔离数据库且无网络。

## 7. 改动路径

- 合同与示例：`docs/contracts/review-request.schema.json`、`review-result.schema.json`、`examples/{plan-v2-result,final-v2-result}.json`
- Domain/Application：`src/grokbuddy/domain/rules.py`；`application/{tasks,reviews,events,findings,worker_tasks,github,grok_routing}.py`
- Adapter/Interface：`src/grokbuddy/adapters/mock.py`；`interfaces/gateway.py`
- 测试：新增 `tests/test_phase6_pack_b.py`；调整 `tests/test_events.py`、`tests/test_phase4_grok_adapter.py`
- 证据/报告：`docs/phase0-checks.json`、本报告

Step 6.2 的 `schema.sql`、CAS、generation fencing、`worker_assignments`、Inbox/Projection 唯一锚被直接复用；没有创建第二套表或事实源。

## 8. NOT WIRED / 后续边界

- **6.5 NOT WIRED**：没有实现 Human Gate 的 Accept/Modify/Continue/Abort 完整 Application/MCP、额外 review budget、正式取消/解冻流程。Pack B 只写入并冻结 `PLAN_HUMAN_REVIEW` / `FINAL_HUMAN_REVIEW`。
- **6.6 NOT WIRED**：没有常驻 supervisor、启动恢复循环、自动 Reviewer intake、自动 UNKNOWN projection reconcile、自动 binding/route、assignment lease recovery 或 v2 timeout/recovery worker。现有 bounded `tick`/`*_one` 仍只是本地测试与 debug 能力。
- 没有 Named Tunnel、真 Grok/WorkBuddy/GitHub E2E、部署、自启、生产 secret/token 验证或真实 Hub 数据迁移。
- 新 actionable query 先落在 Application 层；本轮没有扩大 Phase 4 固定 Remote MCP 五工具面。Worker MCP 仅把已有六工具正式接到 assignment 模型。
- timeout/不确定投递没有记作 `NEEDS_CHANGES`，也不增加 `revision_round`；把 v2 timeout/retry exhaustion 自动送入专用 Human Gate 的常驻恢复编排仍归 6.6/6.7。

## 9. 结论与停止点

Step 6.3 与 Step 6.4 的 Exit 条件已由合同 fixture、隔离正/负向用例、核心回归和全量回归覆盖，判定均为 **PASS**。Hub 仍是唯一事实源；GitHub 只有 projection intent；同一业务闭环只使用一个 Task；Worker complete 不等于 DONE。

到此按 Pack B Stop Condition 停止，等待 Human/指导审阅，不进入 6.5 或 6.6。
