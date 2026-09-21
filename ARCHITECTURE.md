# 架构决策（Phase 0）

2026-09-17：本设计已由用户审核，Phase 1 本地实现见 [LOCAL_CORE](docs/LOCAL_CORE.md)，Phase 3 有限 GitHub Adapter 见 [PHASE3_REPORT](docs/PHASE3_REPORT.md)。使用标准库 sqlite3 实现 Repository/UoW；Phase 3 只增加 loopback WSGI Webhook 和文件型 Comment mock，真实 GitHub/Grok 外部集成仍是未来设计。

## 目标与层次

保留 WorkBuddy Builder、Grok Reviewer、Hub 唯一事实源、GitHub 通信投影、Human 最终控制权。本文为设计，不代表任何服务已实现。

| 层 | 责任 | 依赖边界 |
|---|---|---|
| Domain | Task、Review、Finding、Approval 的规则/迁移 | 仅领域值对象，不导入网络/ORM/MCP |
| Application | 用例、权限、幂等、事务协调、聚合 verdict | Domain + Ports |
| Ports | Repository/UoW、ReviewerAdapter、ArtifactStore、GitHubProjection、Clock、ID | 抽象协议 |
| Adapters | MCP/HTTP/CLI、Mock/Grok、GitHub ingress/projection、SQLite、文件系统 | 实现 Ports，调用 Application |
| Infrastructure | 配置、认证、日志、worker、调度 | 组装依赖，不承载业务状态规则 |

未来目录采用需求第 41 节的 `src/domain/{task,review,finding,approval}`、`application/{services,commands,queries}`、`ports/`、`adapters/{reviewer,github,mcp,http,cli,persistence,artifact}`、`infrastructure/{logging,config,security}`。Phase 0 不创建空业务脚手架。

## 技术选择

Python 3.12+；后续 FastAPI/Pydantic/SQLAlchemy/SQLite/pytest/httpx，单机单 Hub writer + 数据库 worker，无 Redis/Kafka 依赖。SQLite 使用本地磁盘、外键、WAL、busy timeout 和短事务；未来 Repository 替换 PostgreSQL。网络盘/多机写入不支持 V1。

MCP 官方 SDK 是客户端边界依赖。当前官方仓库声明 v2 为稳定主线，不能照搬旧 FastMCP 示例；Phase 2 锁定实测的精确版本、传输与协议协商记录，不在当前空项目伪造 SDK 兼容结果。[官方 SDK](https://github.com/modelcontextprotocol/python-sdk)

异常统一分类：RETRYABLE、NON_RETRYABLE、HUMAN_ACTION_REQUIRED、VALIDATION_FAILURE、AUTHENTICATION_FAILURE、PERMISSION_FAILURE、TIMEOUT。内部异常不返回凭据/原始 payload；公共错误含 code、safe_message、correlation_id、retryable。

## 事务与崩溃恢复

| 事务 | 一次提交的内容 | 提交后工作 |
|---|---|---|
| T1 创建审核 | command 幂等记录；锁定 task version；冻结 profile/plan/artifact revision；RR+reserved review_id+round；Task pending；Audit；Outbox | 返回 PENDING；worker 投递 |
| T2 收到事件 | inbox 持久化（签名校验后）；来源与 hash；ingress Audit | ACK 后 normalized handler 处理 |
| T3 应用结果 | processed_events 唯一键；Review 不可变快照；Finding/event；RR completed；Task 状态；Audit；projection Outbox | 投影 GitHub |
| T4 Finding/审批 | 校验 actor/version；更新当前投影；追加生命周期/审批/Audit；必要 Outbox | 不自动执行真实生产动作 |
| T5 超时 | CAS RR 终态；Task ESCALATED；Audit；取消未发 dispatch | 迟到结果隔离，人工查看 |

所有事务均禁止等待外部 IO。T3 的 processed_events 与业务写入在同一事务，失败全部回滚。T2 先入库再 ACK；handler 崩溃后重放 inbox。文件先写受控暂存、流式 hash、原子 rename，随后提交元数据；失败产生可回收孤儿文件，绝不指向半文件。

SQLite 用 version compare-and-swap + 唯一索引解决并发请求/超时竞态；一次只有一个 active RR/Task。提交在截止时间前到达持久化 inbox 不等于通过：结果处理事务按服务器时钟及当前 RR 状态裁决；`now >= deadline` 超时优先。迟到结果不回滚已完成请求，不复活 Task。

## Outbox / Retry

Outbox 含事件 ID、目的、稳定 idempotency key、payload metadata、attempts、next_attempt_at、lease_until、last_safe_error。worker 短事务领取 lease，事务外发送，短事务确认；进程崩溃后 lease 到期可再领。采用 at-least-once，不宣称跨 GitHub exactly-once。

502/网络暂时错误重投递，同一个 RR 同一轮；429 或 rate-limit 403 尊重 retry headers，其他 403 为 PERMISSION_FAILURE；401 禁止无休止重试。设计最多 5 次，指数退避 base=2 秒、cap=60 秒 + full jitter，不能越过 RR deadline。

**有歧义的发送超时**：先按 correlation/RR/projection key 查询是否已发出；外部通道无法查询或保证幂等时，记录 DELIVERY_UNKNOWN 并升级人工，不盲目重新唤醒 Reviewer。确认结果重复由 Hub 去重仍不能抵消重复模型花费，所以 dispatch 的不确定性单独控制。

Reviewer dispatch 耗尽 → RR FAILED、Task ESCALATED；纯 GitHub projection 耗尽 → outbox 人工处理状态，Hub 已成立的业务状态不回滚。即使 Task DONE 也可继续修复展示投影，但不得再启动 Reviewer。

## ReviewerAdapter 契约

`submit_review_request(envelope, delivery_key)` 仅确认投递 accepted/failed/unknown，绝不返回最终 verdict；`get_delivery_status(delivery_key)` 查询传输状态；`normalize_review_event(raw, verified_identity)` 产出候选 normalized event，不能直接更新 Task。

Mock 和 Grok 经同一 handler。Mock 以队列/worker 产生 ReviewStarted/ReviewCompleted/ReviewFailed，并支持 PASS、NEEDS_CHANGES、BLOCK、TIMEOUT、INVALID_PAYLOAD、DUPLICATE_EVENT。Mock 的即时完成也必须先提交 T1，调用者收到固定 PENDING 提交收据；紧接着 poll 可以已 COMPLETED。

GrokAdapter 在能力 Gate 前保持 disabled；候选唤醒与接收路线参见 [Grok 集成](docs/GROK_BOT_INTEGRATION.md)。后续 GPT/Claude/Gemini/Local 实现同一 Port，不改 Domain。

## Profile 与 Audit

Hub 的版本化 Profile 数据是唯一正式规则源，存储模型见 [DATA_MODEL](DATA_MODEL.md)。六个 Profile 为 generic、oracle_production、sql_server_production、python_backend、iis_windows、document；请求冻结 name/version/hash/snapshot artifact。Skill 只讲行为和如何读取快照。

Audit 只保存 metadata、hash、actor_type/id/name、action、old/new state、correlation/request/event ID、UTC timestamp；大 payload 进 Artifact。审计、Review、Finding event 不覆盖历史。备份将 DB 与被引用 Artifact 的 manifest 一起导出并校验恢复；本地管理员能篡改磁盘的剩余风险明确保留，不能声称 SQLite append-only 等于防篡改存储。
