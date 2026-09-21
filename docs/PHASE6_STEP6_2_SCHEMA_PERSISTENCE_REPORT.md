PHASE6-STEP6.2-SCHEMA-PERSISTENCE: PASS（2026-09-21，Asia/Shanghai）

# Phase 6 Step 6.2 — v2 Schema / Persistence Foundation

## 结论与边界

本 Step 已把 Phase 6 后续步骤需要的 v2 持久化底座落入现有 Hub SQLite/JSON repository：schema version 升为 v4；Task 可持久化两个专用 Human Review Gate；新 Task 写入独立 `revision_round`；新增 Worker assignment 与 Reviewer intake receipt；现有 outbox、inbox、command receipt、GitHub projection intent 补齐恢复锚、lease generation、fencing 与索引；repository 增加通用条件写入 `compare_and_swap`。隔离迁移测试证明旧 v3 Task JSON 字节及未知 v1 字段不被重写、旧行仍可读、新字段可写、重复初始化安全、外键保持完整。

此 PASS 仅指 schema、迁移、repository 最小读写和本地隔离测试。没有实现 6.3 Review Result APPLY / actionable findings、6.4 完整同 Task loop、6.5 Human Gate API、6.6 supervisor，也没有运行 Named Tunnel、真 Grok/WorkBuddy/GitHub E2E 或修改真实业务 Hub DB。`6.2 PASS ≠ 6.3/6.5/6.6/6.19/6.20 PASS`。

## Goal → Preflight 差距表

预检依据：[6.0 合同](PHASE6_STEP6_0_CONTRACT_REPORT.md) D4/D7/D8/D9、状态矩阵与缺口节，[6.0a supervisor 合同](PHASE6_STEP6_0A_MANUAL_GLUE_SUPERVISOR_CONTRACT.md) §2–§4 的 6.2 行，以及 [6.1 Trigger Gate 报告](PHASE6_STEP6_1_TRIGGER_GATE_REPORT.md)。

| 对象 | 预检时已有 | 6.2 缺口 | 本步结果 |
| --- | --- | --- | --- |
| Task | v3 JSON、17 个状态、owner/version；6.1 conversation/trigger 字段及两个唯一索引 | 两个 v2 Gate、`revision_round`、completion/gate/freeze 锚 | v4 CHECK 接受 19 个状态；新 Task 写 `revision_round=0`、`completion_basis`、`gate_reason`、`automation_frozen`；6.1 索引原样保留 |
| Worker | `worker_status` 嵌入 Task，claim 会改 `owner_id` | assignment generation、lease fencing、approved Plan/scope、completion 关联；正式路径禁止 owner 转移 | 新增 `worker_assignments`；旧 owner 转移入口默认拒绝，仅显式 `legacy_worker_test_mode=True` 可供历史隔离测试 |
| Reviewer intake | 只有已知 RR 的读取/回调入口 | 可恢复、可去重的 intake receipt | 新增 `intake_receipts` 及 source/key 唯一约束、冻结 input/profile hash、reviewer actor、lease 字段 |
| Outbox / inbox | JSON 行、部分状态/lease 字段；outbox 按 RR 唯一 | generation/frozen anchors/恢复扫描索引 | 新 outbox 写 request/input/profile hash、frozen task version、lease generation；新 inbox 写 lease/attempt 字段；补恢复索引和状态/lease 约束 |
| Projection | `github_comment_projections` 已是 intent，按 review 唯一，有 marker/hash/lease/retry | `UNKNOWN` 合法表达、lease generation、review+binding 锚、恢复索引 | 状态约束含 `UNKNOWN`；创建写 intent/frozen hashes/version；claim 递增 generation，完成按 token+generation fencing；补 `(review_id,binding_id)` 唯一索引 |
| Command receipt | 主键为 actor/operation/key 的稳定 digest，保存 input digest/response | 恢复查询字段与时间 | 新写 `created_at`；补 actor/operation 索引；旧 receipt 继续读取 |
| Repository / migration | `add/get/find/save(expected_version)`，支持 v0–v3 | 通用 CAS；空库和 v3 安全升级 | 新增多字段 `compare_and_swap`；支持 v4；Task 表仅为扩展状态 CHECK 重建，opaque JSON 原样复制 |

## Schema、字段与约束清单

### Task 与状态

- `TaskState` 和 `tasks.state` CHECK 新增 `PLAN_HUMAN_REVIEW`、`FINAL_HUMAN_REVIEW`。合同矩阵其余状态已存在。
- 新 Task 写入非负整数 `revision_round=0`，与 `review_requests.review_round` / `(task_id, review_type, review_round)` 唯一约束分离。旧 Task 缺该字段时仍合法可读。
- `completion_basis` 仅允许空、`FINAL_REVIEW_PASS`、`HUMAN_OVERRIDE`；并预留 `gate_reason` 与 `automation_frozen`。这些字段的业务转移见下方 NOT WIRED。
- 6.1 的 `one_active_conversation_task` 和 `one_trigger_message_per_conversation` 均在迁移后重建；活动定义仍只排除 `DONE/CANCELLED/FAILED`，因此两个 Human Gate 仍占用该 conversation 的活动 Task 名额。

### `worker_assignments`

- 主键 `id`；`UNIQUE(task_id,generation)`；同 Task 最多一个 `OFFERED/CLAIMED` assignment。
- 必需锚：`task_id`、正整数 `generation`、状态、非负 `lease_generation/lease_until`、可空 `lease_token`、`approved_plan_artifact_id/hash`、对象型 `approved_scope` 及其 hash。
- completion 以 `completion_artifact_id + completion_hash` 成对表达；approved Plan 与 completion Artifact 均由触发器约束为同一 Task 的 Artifact。
- 恢复索引为 `(status, lease_until)`。repository CAS 可同时比较 version/status/lease_generation，旧 lease 不能覆盖新 generation。

### Intake、outbox、inbox、receipt、projection

- `intake_receipts`：`UNIQUE(source,deduplication_key)`；绑定 RR、Reviewer actor、input/profile hash；状态支持 `READY/LEASED/ACKED/UNKNOWN/FAILED`；保存 lease token/until/generation。
- `outbox_events`：原 `review_request_id` 唯一约束保持；新建行冻结 request/input/profile hash 和 Task version，初始 `lease_generation=0`；合法恢复状态包括 `UNKNOWN`。Dispatcher claim 递增 generation，写回同时比较 token 与 generation。
- `inbox_events`：新建行保存 attempt 与 lease 三元组；保留现有可观察的 legacy duplicate ingress 行。为后续 v2 入口预留带 `receipt_key` 的 `(source,deduplication_key)` 唯一索引，不改变当前 v1 重复事件行为。
- `command_receipts`：现有稳定主键和 input hash 冲突规则不变；新增创建时间与 actor/operation 查询索引。
- `github_comment_projections`：沿用现有 intent 表，状态约束显式包含 `UNKNOWN`，补 `(review_id,binding_id)` 唯一锚和恢复索引；新 intent 冻结 review result hash 与 Task version；claim/complete 使用 lease generation fencing。

## 迁移与兼容策略

`SQLiteDatabase.initialize()` 接受 schema version 0–4。空库直接执行 v4 `schema.sql`。检测到旧 `tasks` DDL 不含 `PLAN_HUMAN_REVIEW` 时，迁移在本地短事务内：

1. 暂停外键强制，建立带扩展 CHECK 的 `tasks_v4`；
2. 以 `INSERT ... SELECT id,data` 复制原始 JSON 文本，不解析、不补值、不改变历史状态或 owner；
3. 替换 Task 表并重建 6.1 两个唯一索引；
4. 执行 `foreign_key_check`，失败即回滚；随后执行幂等 `CREATE ... IF NOT EXISTS` 并设置 `user_version=4`。

兼容策略为 **读旧、写新**：历史 v1/v3 行保持缺省字段并按既有路径读取；新 Task/outbox/inbox/projection/command receipt 写 v2 foundation 字段。没有批量回填、业务状态改写或真实 DB DML。新增表和索引重复初始化不产生第二份对象。旧 Phase 5 Worker owner 转移模型不再是正式默认路径；它只在测试 fixture 显式开启 `legacy_worker_test_mode`，用于证明既有套件未被无故破坏。

## Repository 最小可靠读写与测试

`SQLiteRepository` 保留 `add/get/find/save(expected_version)`，新增 `compare_and_swap(table, record, expected)`。CAS 只接受白名单 JSON 字段名并要求至少一个 predicate；零行更新返回 `CONFLICT`。隔离测试覆盖：

- v4 Gate、非负 `revision_round`、completion basis 与新 Task 默认值；
- v3 旧 JSON byte-for-byte 保留、未知历史字段保留、旧关联 Artifact 可读、外键检查、重复初始化；
- 6.1 conversation 唯一约束在迁移后仍生效；
- assignment generation、单活动 assignment、approved scope、跨 Task Artifact 拒绝、lease CAS 旧 generation 拒绝、Task owner 始终为 Builder；
- intake source/key 去重、outbox frozen anchors、projection `UNKNOWN`、非法状态拒绝；
- 正式默认 runtime 对 legacy owner-transfer Worker path fail closed。

## 验证结果

| 命令 | 结果 |
| --- | --- |
| `.\.venv\Scripts\python.exe -m compileall -q src\grokbuddy` | PASS |
| `.\.venv\Scripts\python.exe -m pytest -q tests\test_phase6_schema_persistence.py tests\test_phase6_trigger_gate.py` | 19 passed |
| `.\.venv\Scripts\python.exe -m pytest -q tests\test_phase6_schema_persistence.py tests\test_rules.py tests\test_workers.py tests\test_phase3_github.py` | 442 passed |
| `.\.venv\Scripts\python.exe -m pytest -q` | 550 passed in 172.75s |
| 修改文件严格 UTF-8 解码 | PASS；报告另行复核无 BOM |

第一次全量运行结果为 549 passed、1 failed：`test_enum_and_settings_boundaries` 仍断言旧状态数 17。该断言按合同改为 19，并增加两个新 Gate 的精确值断言；随后组合回归和最终全量均通过。测试全程使用隔离 `tmp_path` SQLite/Artifact Store，网络由 autouse fixture 禁止。

## 已知 NOT WIRED 与后续依赖

- **NOT WIRED / 6.3–6.4**：两个 Gate 目前可持久化但没有新增正式 transition；`revision_round` 尚未在有效 v2 `NEEDS_CHANGES` 后由 Builder 修订命令递增；v2 Review Result、统一 actionable finding、APPLY 原子 projection intent、同 Task Plan/Worker/Final loop 均未实现。
- **NOT WIRED / 6.4**：`worker_assignments` 已有可靠存储和 CAS，但正式 offer/claim/upload/complete Application/MCP 尚未接线。legacy `Task.owner_id=worker` 路径默认关闭，不能作为 Phase 6 正式 claim。
- **NOT WIRED / 6.5**：Human Accept/Modify/Continue/Abort、extra budget、`completion_basis` 写入和 gate freeze/unfreeze 业务未实现；旧 Timeout/Dispatcher 的 `ESCALATED` 行为没有在本 Step 偷改成 v2 Gate。
- **NOT WIRED / 6.6**：intake receipt、inbox lease 字段和 projection/outbox fencing 尚未由常驻 supervisor 全部消费；无启动恢复循环、自动 Reviewer intake、自动 Final projection enqueue 或 UNKNOWN reconcile worker。
- **后续 6.3–6.6 依赖**：应直接复用 v4 表、唯一锚、CAS 和 generation fencing；不得另建平行事实源，不得从 GitHub 状态推导 Hub verdict，也不得恢复正式 owner-transfer claim。

## 文件清单与停止点

修改：`src/grokbuddy/adapters/{schema.sql,sqlite.py}`、`domain/model.py`、`application/{tasks,common,reviews,events,workers,github,worker_tasks}.py`、`infrastructure/runtime.py`、`tests/{conftest.py,test_rules.py}`。新增：`tests/test_phase6_schema_persistence.py` 与本报告。

项目根 `D:\Codex\grokbuddy` 不是 Git checkout；本 Step 不修改嵌套探针 checkout、`main`、任何真实业务 Task/Hub DB，也未发起外部请求。达到 schema + migration + repository + tests + report Exit，现按 Stop Condition 停止，等待 Human/指导审阅。
