# 审核协议总览

新 V1 Task 的轮次/verdict/Finding 决策见 [V1 Review Decision Policy](docs/contracts/V1_REVIEW_DECISION_POLICY.md)；下文 v1 轻量 Plan 与旧 Task 描述保持历史兼容。Review 协议版本与任务冻结的产品决策策略是两个独立字段。

协议版本 v1；GitHub 控制平面 marker 为 `[AI-COLLAB v1]` / `[AI-REVIEW v1]`，Artifact 数据平面是结构化 JSON。规范字段见 [PROTOCOL_V1](docs/PROTOCOL_V1.md)，机器可读草案见 [request schema](docs/contracts/review-request.schema.json) 和 [result schema](docs/contracts/review-result.schema.json)。Phase 0 校验 schema/examples，不把它们当作可调用服务。

## 请求

Hub 创建 RR 时冻结 task/content revision、review_type、round、Profile name/version/hash、input artifact/hash、deadline、expected Reviewer actor；预分配 review_id。request 工具只返回 `{review_request_id,status:PENDING}`，最终结果由 query 获取。包括所有 required metadata 的输入审核 envelope 通过 Outbox 投递。

PLAN payload：原始目标、范围、约束、计划、风险、待验证项。FINAL_PACKAGE：原始任务、批准方案、本次修改范围与文件、commit SHA 或 diff artifact、测试与自检、已知风险/未验证事项、Profile 快照，具体见 [Artifact](docs/ARTIFACT_MODEL.md)。

## 输出与审核重量

PLAN：summary、总 verdict、轻量 comments/risks/suggestions；无强制 Finding Lifecycle。FINAL：summary、verdict、new findings、既有 findings 的 verifications、证据；每一新增问题有 severity/blocking/category/title/finding/evidence/impact/recommendation，Hub 分配 stable finding_id。

Reviewer 不可写 Task State 或 HumanApproval。输出中 actor 声明必须与 transport 鉴权匹配，不以 JSON 自报 identity 建立权限。`timestamp` 仅源端声明时间，Hub received_at 和 deadline 作权威裁决。

请求/输出未知字段拒绝，版本未知不自动猜兼容。校验结构后还需 [状态机](STATE_MACHINE.md) 和 [Verdict](docs/VERDICT_RULES.md) 语义检查。missing artifact、invalid JSON、hash mismatch、wrong task/revision/Profile/round、self-review 均不能应用结果。schema 通过本身不代表业务可接受。

## Profile 规则源

正式规则由 Hub review_profiles.rules_json 管理（Phase 1 建立），发起请求时导出任务级不可变快照 Artifact。请求携带 name、version、hash、snapshot reference；修改规则新版本，不 retroactively 改已创建 RR。以下是设计覆盖要求，后续生成单一 Hub 数据源，Reviewer Skill 不复制。

| Profile | 核心关注 |
|---|---|
| generic | 需求覆盖、反例、边界、测试、证据、权限、回滚 |
| oracle_production | 下述 Oracle 专用覆盖；最高优先级之一 |
| sql_server_production | 正确性、执行计划/索引、锁/事务、并发、权限、回滚及版本兼容 |
| python_backend | API/schema、异常、安全、依赖、并发、持久性、测试 |
| iis_windows | 应用池/身份、连接池、配置、日志、权限、部署/重启审批及回滚 |
| document | 来源、数据口径、完整性、可读性、版本/引用、未验证项 |

Oracle 覆盖：SQL 正确性、字段/表来源、JOIN/WHERE/NULL/隐式转换；索引/函数索引/选择性/执行计划/基数/全表扫描；锁/死锁/事务/COMMIT/ROLLBACK/异常/并发/连接池；AWR/ASH/V$SQL/SQL_ID/Child Cursor/Bind Variable；统计窗口、累计/增量；Oracle 11g；DDL/DML 误更新；UNDO/REDO/TEMP/CPU/IO/Shared Pool/Latch/Mutex；回滚方案、验证 SQL、上线步骤、最小权限、Diagnostics Pack 许可风险。

Reviewer 必须独立判断，不信任 Builder 结论；没有实际计划/运行数据只能标 EVIDENCE_INSUFFICIENT，不能把静态 SQL 审核写成 Oracle 编译/生产验收。每条 Profile rule 将有 rule_id、要求的 evidence、适用条件和 finding category；许可未确认时停止相应采集并报告缺口。
