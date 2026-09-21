# Phase 1 本地核心使用与实现边界（含 Phase 3 加法迁移说明）

已授权范围仅 Local Core。这里的 `Hub` 是可调用 Python 服务对象，不是联网服务器；没有 MCP/HTTP handler、GitHub Adapter、Grok Adapter、外部账号认证或生产命令执行器。

## 运行方式

从仓库根目录执行：

```powershell
.\.venv-phase0\Scripts\python.exe -m pytest -q
.\.venv-phase0\Scripts\python.exe scripts\demo_local_core.py
.\.venv-phase0\Scripts\python.exe scripts\validate_phase0.py --allow-core
```

新环境按 [README](../README.md) 安装 `requirements-dev.txt`。测试通过 pyproject 的 pythonpath 使用源码；演示显式加载仓库 `src`。已验证的是仓库运行方式，未制作/验收 wheel 发布包。

程序入口（在已配置 `src` 为 Python 搜索路径的本机受信宿主中）：

```python
from grokbuddy.infrastructure.runtime import LocalRuntime
from grokbuddy.domain.model import Settings

runtime = LocalRuntime(
    "var/local-core",
    "docs/contracts",
    settings=Settings(max_plan_review_rounds=2, max_final_review_rounds=3),
)
hub = runtime.hub
task = hub.create_task("builder", "本地待审任务", key="create-unique-task-key")
task = hub.move("builder", task["id"], "begin_plan", task["version"], key="begin-unique-key")
plan = hub.submit_artifact("builder", task["id"], "PLAN", b"A concrete local plan", key="plan-artifact-key")
task = hub.submit_plan("builder", task["id"], plan["id"], task["version"], key="submit-plan-key")
receipt = hub.request_review("builder", task["id"], "PLAN_REVIEW", "mock-reviewer", task["version"], key="request-review-key")
assert receipt["status"] == "PENDING"
# Above: no Reviewer called and no evaluation performed.
runtime.dispatcher.dispatch_one()  # Outbox -> durable mock job; delivery receipt only
runtime.mock.run_one()             # job -> ReviewCompleted -> normalized event -> durable inbox
runtime.events.handle_one()        # dedup + validation -> review/findings/state/audit in one UoW
result = hub.get_review(receipt["review_request_id"])
```

`runtime.tick()` 只是一次有界的本地 worker 顺序调度（timeout→dispatch→mock→handler），不会被 request_review 自动调用。真实时钟使用 UTC 微秒；测试的 ManualClock 可精确推进到 deadline，不依赖 sleep。下一次 worker 调度恢复未完成的 outbox/inbox，不需保持原 Python 对象存活。

## 本地接口范围

| 服务 | 已实现用例 |
|---|---|
| TaskService | create_task、get_task、move（仅 Builder 有限动作）、submit_artifact、submit_plan、self_test、submit_final_package、profile_snapshot、get_review、list_findings、audit_log |
| ReviewService | request_review（PLAN/FINAL 共用创建机制；结果处理重量不同） |
| FindingService | accept/reject/fix；verify/reopen 只能进入 Reviewer evaluation 事件 |
| GovernanceService | request_action、decide_action、consume_action、withdraw_action、waive_finding、resume、override_review、cancel |
| EventService | ingest、handle_one；Started/Completed/Failed 同一管线 |
| workers | Dispatcher lease/retry/reconciliation；TimeoutService 处理 request/task/approval deadline |

所有业务修改使用独立 principal、幂等 key；Task 相关修改还要求 expected_version。原命令重放返回原提交收据（即便审核后来已完成，原 request 收据仍 PENDING），当前结果须 query。不得把提交收据当成最终结果。

## Mock 与生产契约的关系

`ReviewerAdapter` 定义 submit_review_request/get_delivery_status/normalize_review_event。submit 仅返回 ACCEPTED/UNKNOWN/NOT_FOUND 类型传输收据，没有 verdict；Mock 在独立 `run_one` 才产生结果。

Mock 构造参数仅包含 ReviewQueue Port、Clock 与时间格式函数，不接收 Hub/Task Repository。SQLiteMockQueue 是基础设施，负责 mock_jobs 持久化、lease、normalized event 入站；同一事务提交 job DONE 与 inbox/Audit。真正应用结果的唯一位置是 EventService。

支持 PASS/NEEDS_CHANGES/BLOCK/TIMEOUT/INVALID_PAYLOAD/DUPLICATE_EVENT/FAILED；测试可配置 findings/verifications/result。Mock 模拟评审结果，不是实际代码/SQL 分析器，不证明 Profile 规则已被真实模型正确执行。

future GitHub/Pull/Webhook/Grok ingress 必须适配同一 normalized event 和 EventService，不能增加第二套 Task 状态推进逻辑。当前跨 source 重复的测试只验证本地 normalized 管线，不等于 Webhook/Pull 已集成。

## 持久层与 Phase 0 逻辑设计的对应

标准库 sqlite3，Repository/UoW Port；每个 UoW 独立连接，BEGIN IMMEDIATE、foreign_keys、WAL、busy timeout。领域/Application 不导入 SQLite 或网络库。Phase 3 将数据库 `user_version` 从 1 加法迁移到 2：只以 `CREATE TABLE/INDEX IF NOT EXISTS` 新增 GitHub Adapter 表，Phase 0–2 表与 backup 实现不变；未知 schema version 仍拒绝打开。

每张物理表以 `id + data JSON` 保存完整实体，生成列暴露 state/version/task_id/request_id 等约束与索引字段。逻辑文档的 task_id/review_request_id/finding_id 在所属表中由通用 id 表示，在关联/协议中保留原字段。这样不会创建另一份可漂移的数据状态。

Phase 0–2 表为 actors/tasks/task_events/review_requests/review_rounds/reviews/review_findings/finding_events/artifacts/review_profiles/human_approvals/approval_events/audit_logs/command_receipts/outbox_events/inbox_events/processed_events/mock_jobs。Phase 3 新增 github_bindings/github_events/github_comment_projections；Pull cursor 未实现。当前所有 Artifact 永久保留，无 GC，所以不需要实现删除授权或引用回收器。

数据库强制：每 Task 仅一个 active RR、每 kind/round 唯一、每 RR 单一 Review、每 review/external key 唯一、provider_id 唯一、关键 FK/状态 CHECK。Audit、Review、Finding/Approval/Task 事件、Artifact 元数据、Profile 和 command receipt 有 UPDATE/DELETE 拒绝触发器。Finding 当前投影可更新；原内容/历次 review artifact/event 历史不改。

Profile 正式运行数据在 Hub `review_profiles`，`infrastructure/profiles.py` 是唯一 seed 规则源。已存在 name/version 的 hash 与 seed 不同会阻止启动，要求新版本；RR 保存 task-scoped Profile 快照。Schema 直接读已审阅的 `docs/contracts/`，没有复制另一套协议文件。

## 事务与恢复

- Request：RR+round+Task+Audit+Outbox+command receipt 原子提交；不会在事务里调用 Reviewer。
- Dispatch：领取 lease 后释放事务；查询 delivery key，必要时发送。重试是同一 RR/round；5 次有界退避，不能越过 deadline。未知交付状态升级人工，不盲目再次评估。
- Mock：队列认领、产生事件、事务写入 inbox；重启后租约到期可重领。
- Handle：dedup+Review+Finding/events+RR+Task+Audit 同事务；失败回滚后安全记录拒绝。系统异常保留 READY 供恢复；业务校验失败隔离 REJECTED。
- 超时：采用 Scheme B，以事件应用时的 `clock.now()` 判定是否迟到，`received_at` 不是判定依据；即使截止前已接收，应用时达到截止时间也视为超时。截止相等视为超时，RR 保留 TIMED_OUT、Task ESCALATED。迟到/重复结果不能复活任务，最后允许轮仍有 PASS 机会。
- Artifact：受控内容地址、原始 bytes SHA-256、长度限制、暂存+原子发布；禁止 arbitrary path/URL/UNC/link 路径。事务失败可能留无引用内容文件，但不会注册半文件，且不会自动删除。
- 备份：`db.backup_to(new_path)` 只生成 SQLite 一致性快照，不备份 Artifact；Artifact 内容需手动另行备份。没有并发冻结机制，因此不保证数据库快照与另行复制的 Artifact 构成同一时点的联合快照。既有恢复测试验证的是测试样本中分别备份的二者恢复后任务、审核和每个 hash 可读。没有提供生产备份调度或自动清理。

## Human Approval 的实际边界

动作绑定 operation/environment/targets/parameters、脚本和 precheck/backup/rollback/verification Artifact hash、task revision、expiry。只有 Human 决策，Builder/Reviewer/System 不能批准。未消费/未批准动作会阻止自检进入最终流程，也会在最终事件和 override 再次校验。

`consume_action` 是一次性授权消费的本地模型，返回 `execution_performed=false`，不运行 SQL、部署、删除、重启或任何生产命令。使用同一个 command key 重放不会再次消费。接入未来真实 Executor 时仍须专门设计执行与回执的可靠性，不能把这里的返回值当作重复可用的执行 token。

拒绝后选择 replan 明确撤回旧动作；过期/被拒绝动作可由 Human 说明理由后 withdraw，再显式 resume。撤回只移除“仍待执行”的假设，绝不授予执行权。Task 总时限先触发时也可补记审批过期后撤回，避免审批永久悬挂。

## 当前限制

本机是受信进程边界，模拟 actor_id 由调用宿主选择。没有客户端认证、端口监听或多租户隔离。真实集成适配器必须从认证上下文映射 principal，不能把任意客户端 actor_id 原样传入。Python/SQLite 管理者能修改文件或数据库，append-only trigger 不等于防管理员篡改。

未做真实进程断电/文件系统故障注入；已做 UoW 回滚、lease 中断、重新实例化恢复、并发 handler/dispatcher/timeout 测试。Windows 中文/空格路径已测；Windows 实际 junction/ACL 权限矩阵未在本阶段实测。Artifact 不扫描全部可能的秘密，输入应先脱敏；本阶段没有索要或读取任何生产凭据。

Phase 2 的 WorkBuddy create_task 已由用户报告并在 Hub DB/Audit 复核。Phase 3 只运行了本地签名 Webhook fixtures 与文件型 Comment mock；GitHub A/B identity/权限、公网投递、真实评论 API、Grok Trigger、Artifact 云端读取仍 UNVERIFIED，External Integration Gate BLOCKED。
