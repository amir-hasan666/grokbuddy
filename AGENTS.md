# 仓库长期规则

Phase 3.5 Real GitHub Integration 已于 2026-09-18 通过真实外部 Gate；PR #2 与 `phase35-probe` 保持打开。Phase 4 Remote MCP 只读本机与当次 Quick Tunnel 公网 Gate 已通过，详见 [Remote MCP 报告](docs/PHASE4_REMOTE_MCP_REPORT.md)。Human 于 2026-09-20 进一步授权真 Grok Adapter、认证写回和 Reviewer B 路由；本地实现与证据见 [Grok Adapter 报告](docs/PHASE4_GROK_ADAPTER_REPORT.md)。PR #4 的旧 Mock RR 已通过正式 TimeoutService 转 `TIMED_OUT`，Task 转 `ESCALATED`；未来请求路由指向 B。专用 B Secret 当前缺失，未创建新 RR、未触发真实 Grok 或 GitHub 请求 Comment，Functional Exit 尚未通过。只按 [试跑 runbook](docs/PHASE4_GROK_RUNBOOK.md)和当前 Human 授权继续；仍禁止 ACP、Phase 5/6、merge/approve、修改 `main`、删除探针分支、直接 DB DML、伪造 Reviewer 结果及其他高风险 GitHub 写操作，也不得脏改 Phase 0–3 冻结状态机、命令幂等、backup、provider_id、Source of Truth 或既有 stdio MCP/HTTP/CLI 行为。

## Architecture / Async Review

- Collaboration Hub 数据库是唯一事实源。GitHub 是通信、展示和审计投影，不可通过标签、PR 状态、正文或评论顺序决定业务状态。
- Domain 不依赖 MCP、GitHub、Grok。入口经 Application Service 调用 Domain；ReviewerAdapter 必须可替换。
- Reviewer 一律 request → PENDING → event → COMPLETED/FAILED/TIMED_OUT。请求提交只持久化并立即返回，不等待最终 verdict；禁止同步 `review() -> verdict`。
- MockReviewer 必须走同一 ReviewRequest、normalized event、handler、状态迁移及 Audit，不得同步返回 PASS。
- 状态、Audit、Outbox 原子提交；外部请求不占用数据库长事务。拒绝非法跳转，Task State、Review Request Status、Verdict 三者分离。

## GitHub / Identity / Artifact

- 不假定 Issue/PR Comment 能唤醒 Grok；必须验证当前账号的实际 wake-up channel，证据参见 [能力登记](docs/CAPABILITY_VERIFICATION.md)。
- Builder、Reviewer、Human、System 身份可区分。生产同一 GitHub actor 不能既提交又审核；不能用 Builder 凭据代发并声称来自 Reviewer。
- Comment 仅允许版本 marker、metadata、短摘要、artifact pointer。完整 diff、日志、长 SQL、原始 Review JSON 等进入 Artifact Store。
- Artifact 必须不可变、有 hash、受控 pointer 和 Hub 元数据；不得把其内容放进 Audit。

## State / Finding / Audit / Protocol

- `finding_id` 永久稳定，Hub 生成；展示 R001 不是主键。复审保留 ID；新问题另建，替代/拆分保留关联，不覆盖旧 Review/Finding 历史。
- Audit append-only，记录真实 actor 和关联 ID；任何 waiver、override、人工审批均留痕。
- 协议版本化；未知/缺失版本拒绝，校验失败不推进 Task。结构和语义校验都必须通过，不从自然语言猜 verdict。
- 达到审核轮次/超时/任务时长边界转 ESCALATED，停止自动 Reviewer。重投递不等于新一轮，人工恢复必须显式审计。
- Review Profile 规则只有 Hub 一个正式来源；Skill 引用带版本快照，不复制业务规则。

## Safety / Security / External Capabilities

- 危险生产动作须 AWAITING_HUMAN_APPROVAL，审批绑定动作、环境、对象、hash、范围、期限与批准人。Review PASS 或 HUMAN_OVERRIDE 不等于执行授权。
- 禁止无审批自动生产 DDL/DML、部署、重启、删除资源、覆盖配置、改防火墙或权限。Prompt、Hub 状态机与真实权限三层均控制。
- Reviewer 仅 READ/REVIEW/COMMENT，无生产写入、管理、部署、删除、重启权限。Secret 不进源码、日志、Artifact 或审计摘要。
- 不编造 Grok Bot/WorkBuddy API、GitHub event、MCP capability 或第三方能力；未实测标 UNVERIFIED / ENVIRONMENT_VALIDATION_REQUIRED，官方支持不等于当前环境通过。
- 验证应说明范围；静态契约检查不能证明服务运行、真实 MCP、Grok 唤醒、GitHub 回传或生产安全已通过。

## 项目工作流

按任务需要读取 `skills/architecture-gate`、`skills/phase-execution`、`skills/review-protocol-validator`、`skills/async-workflow-test` 下的 SKILL.md。它们提供操作步骤；长期约束以本文件为维护入口，不建立第二份规则源。每阶段开始说明目标/文件/决策/风险/依赖，结束记录变更、命令、结果、未验证项及下一阶段，未经授权不跨阶段。
