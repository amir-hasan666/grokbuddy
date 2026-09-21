# Phase 0 交付报告

历史快照（2026-09-16）。用户于 2026-09-17 审核并授权 Phase 1；当前实现与 Gate 请看 [Phase 1 报告](PHASE1_REPORT.md)。以下保留当时的交付与证据边界。

范围：本项目唯一的架构规划与验证阶段；不增加额外规划生命周期。当前交付设计与允许范围内的验证，**没有进入 Phase 1，没有实现 Hub，没有真实 Grok 调用或生产 GitHub 自动化。** 外部环境 Gate 仍 BLOCKED，不声称全部 Phase 0 验收通过。

## 需求要求的首轮 28 项答复

| # | 答复 / 决策 | 详见 |
|---|---|---|
| 1 理解 | 长期系统，Builder/独立 Reviewer/Hub/GitHub/Human 五方职责不变 | [README](../README.md) |
| 2 核心架构 | Domain + Application + Ports + Adapters + Infrastructure；单机 SQLite | [架构](../ARCHITECTURE.md) |
| 3 SoT | Hub 状态/审核/轮次/Finding/审批/元数据/Audit/事件权威；GitHub 投影 | [边界](SOURCE_OF_TRUTH.md) |
| 4 异步模型 | T1 commit 返回 PENDING；后台投递；事件 handler；客户端 poll | [时序](ASYNC_REVIEW_SEQUENCE.md) |
| 5 Task State | 独立 17 状态；非法边拒绝；终态不复活 | [状态机](../STATE_MACHINE.md) |
| 6 Request State | PENDING/IN_PROGRESS/COMPLETED/FAILED/TIMED_OUT/ESCALATED | [状态机](../STATE_MACHINE.md) |
| 7 Finding | Hub 稳定 UUID；接受/修复/验证/证据拒绝/人工豁免 | [生命周期](FINDING_LIFECYCLE.md) |
| 8 Human Approval | 独立人类、action digest/范围/期限/一次性许可，override 不等于执行批准 | [安全](../SECURITY.md) |
| 9 Artifact | 内容不可变、Hub metadata、SHA-256、受控 pointer、引用保留/审批清理 | [产物](ARTIFACT_MODEL.md) |
| 10 Control Plane | Comment 仅 marker、metadata、短摘要、pointer，非状态权威 | [协议](PROTOCOL_V1.md) |
| 11 双模式 | Webhook/Pull 共用 normalized event、semantic dedup、handler、状态机 | [连接](GITHUB_CONNECTIVITY.md) |
| 12 双 Actor | A Builder/Hub、B Reviewer，C Human；真实 provider ID 区分 | [身份](GITHUB_ACTORS.md) |
| 13 WorkBuddy | MCP 目标、HTTP/CLI 降级；官方能力与当前环境分级 | [WorkBuddy](WORKBUDDY_INTEGRATION.md) |
| 14 Grok 唤醒 | 用户指定 PR 事件 pr-comment/review-* primary / scheduled poll fallback 候选；具体 PR trigger 与账号能力 UNVERIFIED，Issue Comment UNVERIFIED，均 disabled | [Grok](GROK_BOT_INTEGRATION.md) |
| 15 ReviewerAdapter | submit delivery/get delivery status/normalize event，无同步 review verdict | [架构](../ARCHITECTURE.md) |
| 16 Profile | Hub 单一规则源、不可变版本快照、六类 Profile；Skill 不复制规则 | [审核](../REVIEW_PROTOCOL.md) |
| 17 Verdict | 未关闭 CRITICAL BLOCK；其他未关闭 NEEDS_CHANGES；全关闭才自动 PASS | [聚合](VERDICT_RULES.md) |
| 18 Protocol v1 | 两个 marker、严格字段/版本、PLAN 轻量/FINAL 生命周期、反例校验 | [协议](PROTOCOL_V1.md) |
| 19 Data Model | 表/主外键/唯一约束/索引、actor、review、finding、approval、event | [数据](../DATA_MODEL.md) |
| 20 Transaction/Outbox | request+audit+outbox 原子；网络在事务外；lease/backoff/reconcile | [架构](../ARCHITECTURE.md) |
| 21 Audit | append-only、actor 三字段、旧新状态/关联 ID、只存 metadata/hash | [数据](../DATA_MODEL.md) |
| 22 Security | Prompt/Hub/真实权限三层，最小权限，验签/防重放/脱敏/受控下载 | [安全](../SECURITY.md) |
| 23 README | 项目/架构/目录/当前阶段/Windows 使用/配置/接入/限制/故障/路线 | [README](../README.md) |
| 24 AGENTS | 长期硬约束统一入口，项目 Skills 只维护工作流 | [AGENTS](../AGENTS.md) |
| 25 Phase 1–6 | 1本地核心→2入口→2.5管理→3GitHub→4协议设置→5Mock E2E→6真实Grok | [计划](../IMPLEMENTATION_PLAN.md) |
| 26 十大风险 | trigger、身份、云产物、MCP、重复投递、事件竞态、错误DONE、SQLite、泄密、权限 | [风险表](../IMPLEMENTATION_PLAN.md) |
| 27 未验证项 | C01–C19逐项记录证据范围/影响/验证路径/备选 | [能力登记](CAPABILITY_VERIFICATION.md) |
| 28 Phase 1 Gate | 文档/契约、人类设计审阅、WorkBuddy环境、Grok当前通道、身份、明确授权 | [Gate](../IMPLEMENTATION_PLAN.md) |

## 规定交付与变更

用户补充已纳入：Grok Bot 官网 x.ai/bot、官方 overview；Grok Bot/WorkBuddy 已登录、GitHub Connector 已连接、测试仓库名 grokbuddy。均按 USER_REPORTED 记录，未索要 Token/Secret。当前以 Hub + MockReviewer 离线闭环为设计基线；PR 事件名称是候选标签，不当作已验证 API/event。

初始目录为空，因此本次全部为新增，无原有业务文件修改。

规定根目录 8 文件：README.md、AGENTS.md、ARCHITECTURE.md、DATA_MODEL.md、STATE_MACHINE.md、SECURITY.md、REVIEW_PROTOCOL.md、IMPLEMENTATION_PLAN.md。

规定 docs 10 文件：SOURCE_OF_TRUTH.md、ASYNC_REVIEW_SEQUENCE.md、ARTIFACT_MODEL.md、FINDING_LIFECYCLE.md、GITHUB_ACTORS.md、GITHUB_CONNECTIVITY.md、VERDICT_RULES.md、PROTOCOL_V1.md、WORKBUDDY_INTEGRATION.md、GROK_BOT_INTEGRATION.md。

四个项目 Skill：architecture-gate、phase-execution、review-protocol-validator、async-workflow-test，全部遵循官方 skill-creator 格式。复用已安装 skill-creator 的规范与验证器，没有复制其通用说明。`skills/` 为用户指定位置；当前不宣称宿主已自动注册这些项目技能，AGENTS 提供发现路径。

辅助交付：能力登记、本报告、验证报告、测试矩阵、requirements-phase0.txt、.env.example、.gitignore、docs/contracts 中的 schema/examples、scripts/validate_phase0.py。仅用于设计和离线契约检查，不是 Phase 1 业务实现。

Grok reviewer_skill/routine_setup/MANUAL_GROK_SETUP 明确安排 Phase 4；本轮不提前创建或安装真实 Bot 行为。

## 验证与剩余问题

实际命令/结果详见 [验证报告](VALIDATION_REPORT.md)。Phase 0 检查文档链接、交付清单、Skill 格式、Schema 与正反例；没有运行数据库、Hub、Webhook、真实 MCP 或业务 Demo。

最终离线结果 171/171 PASS；官方 Skill 校验 4/4 PASS；pip check 通过。首轮发现并修正日期格式验证依赖缺失，过程已写入验证记录。18 份规定文档及 4 个 Skill 已全部交付；这不是对当前账号外部 Gate 的放行。

无法在“不连接真实 Grok”的当前限制下完成当前账号触发与返回 E2E；本次也未取得 WorkBuddy 当前账号兼容性证明。架构没有把这些缺口隐藏在 Mock 结果中：已选候选但关闭通道，保留 Gate BLOCKED，等待用户审核。本阶段不会自行启动补验证 Routine，也不会进入 Phase 1。

## 需求覆盖索引

原总需求 1–2 → 审核/状态机/时序；3–10（H1–H8）→ SoT/时序/Artifact/Finding/连接/身份/安全/能力登记；11–13 → Verdict/审核；14–16 → Profile 与 Phase 4 Skill；17–21 → 协议/连接/WorkBuddy；22–27 → 状态机/Finding/Verdict；28–34 → 数据/架构/安全/协议；35 → Mock 契约和测试矩阵；36–39 → 18 文档+4 Skill+本报告；40–43 → 架构/数据/Windows README；44–46 → 实施计划/测试矩阵；47–51 → 本报告、AGENTS、Gate 与停止边界。
