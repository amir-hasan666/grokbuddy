# GrokBuddy V1 Product Path and Scope Reset

Human 冻结日期：2026-09-23（Asia/Shanghai）。状态：**V1 产品范围已冻结；文档控制面已重定义；实现与验收尚未完成。**

本文件是 GrokBuddy V1 产品需求、范围分类及 6.21/6.22 新目标的正式入口。它不声明代码已符合新规则，不授权创建 Task、测试、部署或重启，也不改写任何带日期的 Phase 报告。Hub 仍是 Task、Review、Artifact 和 Audit 的唯一业务事实源。现行实现或旧 Phase 合同与本文件冲突时，应记录 drift，并在后续单独授权的实现工作中对齐；不能以旧 Gate 或当前代码降低 Human 冻结的产品要求。

## Human 冻结的 11 条 V1 产品需求

1. Human 向 WorkBuddy 提需求。
2. WorkBuddy 先出方案，不写代码。
3. WorkBuddy 通过 webhook 把方案同步给 GrokBot。
4. GrokBot 第一轮分析方案，返回结论和修改建议。
5. WorkBuddy 按建议修改方案，再通过 webhook 提交 GrokBot。
6. GrokBot 第二轮只输出 PASS/BLOCKED；只有方向性、核心需求、安全或数据等实质问题才能 BLOCKED，小问题不得 BLOCKED。
7. 第二轮方案 PASS 后 WorkBuddy 才编码；BLOCKED 则 WorkBuddy 停止，前端展示方案 V1、Grok R1、方案 V2、Grok R2 BLOCKED 理由，由 Human 决策。
8. WorkBuddy 完成代码 V1 后提交 GrokBot 审核和测试；R1 PASS 则交付；BLOCKED 则给修改意见，WorkBuddy 修改一次再提交。
9. 第二轮代码审核只允许 PASS/BLOCKED；若 BLOCKED，前端仍展示操作方法、生成文件及 Grok 第二轮阻断理由；不得自动进入第三轮。
10. 必须有网站 / Control Center，可查看 WorkBuddy 与 GrokBot 的文案、时间、方案、代码、测试结果、生成文件和完整时间线。
11. WorkBuddy 代码是否上传 GitHub 不属于自动主链，由 Human / ChatGPT 决策。

方案与终审各最多两轮。第一轮可给修改建议；第二轮只接受产品层的 PASS/BLOCKED。这里的 `BLOCKED` 是产品展示与决策语义；现有协议的 `BLOCK`、`NEEDS_CHANGES` 和 Hub Gate 状态如何对应，属于待对齐的实现/合同 drift，不能把当前枚举直接当作 V1 已实现。方案未 PASS 不得编码。终审 PASS 应展示操作方法与文件；终审 R2 BLOCKED 仍须展示产物和理由，并明确未验收通过。Human 对阻断作出的独立决定不得伪装成 GrokBot PASS。

## V1 范围判定

唯一的 V1 blocker 判据：**不解决它，是否会直接导致上述 11 条中的某一条无法正常工作？** 正常 webhook 主链上的身份、异步审核、Hub 权威状态及成功路径 Manual Glue = 0 继续受既有安全规则约束；这不要求所有极端异常路径都达到同一生产演练覆盖率。

### 当前 5 个 V1 BLOCKER

| # | 工作项与需求 | 已有实现 / 验证 | 尚缺与阻塞原因 |
| --- | --- | --- | --- |
| 1 | 产品合同和双轮语义对齐；需求 2–9 | 本文件冻结产品规则；旧 Phase 6 合同与代码已有方案 2 轮、终审默认 3 轮及 v2 Review 枚举。 | 后续须对齐正式合同、协议映射和实现；目前不能声称双轮产品规则已落地。直接影响方案/终审闸。 |
| 2 | WorkBuddy 连续执行产品流程；需求 1、2、5、7–9 | ingress、Hub、Worker MCP 已实现；6.20 证明一次正式 Plan→Worker→Final 链。仓内 WorkBuddy skill 目前只负责点火。 | 尚未证明一次普通需求下 WorkBuddy 能按 R1 意见修订、等 R2 PASS 再编码、按终审意见至多修改一次并交付。 |
| 3 | 方案 R1/R2 决策与阻断展示；需求 3–7 | webhook 唤醒、认证取件/回传已有 Human 实弹复测；Plan 修订与 Human Gate 有实现。 | 尚未证明 R1 建议→方案 V2→R2 仅 PASS/BLOCKED、小问题不 BLOCKED、R2 BLOCKED 停写并展示四份材料。 |
| 4 | 代码 R1/R2 决策与交付；需求 8–9 | 6.20 证明 Final R1 PASS 可推动 Hub 到 DONE；TEST_RESULT、DIFF、Final Package 可持久化。 | 现行终审默认 3 轮，且现行 `BLOCK` 会直接入 Human Gate；需对齐 R1 修改一次、R2 仅 PASS/BLOCKED、R2 BLOCKED 仍展示方法/文件/理由。 |
| 5 | 网站 / Control Center；需求 7、9、10 | Hub 已保存部分所需数据并提供部分只读查询；仓内尚无完整网站。 | 需要网站及所需读取面，展示双方文案、时间、方案、代码、测试、文件、阻断理由和完整时间线。 |

上述 5 项均阻塞 V1；已有局部实现或历史 PASS 不能代替对应产品行为验收。

### 当前 6 个 V1.1 RELIABILITY BACKLOG

| # | 工作项与关联需求 | 已有实现 / 验证 | 尚缺与 V1 判定 |
| --- | --- | --- | --- |
| 1 | Automatic Same-RR Re-Wake，含 HTTP `status_code` 可观测性、durable retry、bounded backoff/deadline 和 Supervisor recovery；需求 3、5、8 | **IMPLEMENTED + LOCAL REGRESSION PASS / NOT PRODUCTION VALIDATED**。 | 生产验证未做。正常 webhook 唤醒已有独立实弹 PASS；无证据证明 re-wake 是正常主链前提，故不阻塞 V1。 |
| 2 | consumer pause/resume 与 missed wake 恢复；需求 3、5、8 | 有 Supervisor、持久收据及局部恢复实现/测试。 | 组合生产故障场景未闭合；不阻塞正常 webhook 主链。 |
| 3 | active-RR restart 负例及 webhook 故障恢复组合；需求 3、5、8 | 旧 6.21 的 B2 已取得 poller 唤醒下同 RR 跨真实重启并 APPLY 的证据。 | 额外 webhook 故障组合不作为 V1 Exit Gate。 |
| 4 | poller fallback 时序；需求 3、5、8 | poller 可用；webhook 已在 poller 暂停时独立完成 Plan/Final。 | 兜底切换时序未专项验收；不阻塞正常 webhook 主链。 |
| 5 | 极端重复投递、并发与跨 Task race；需求 1、3、8 | 本地幂等/隔离测试和旧 6.21 的 B/C、部分 G 证据已存在。 | 完整故障注入组合未闭合；不作为 V1 阻塞。 |
| 6 | 所有异常路径 Manual Glue = 0；需求 1–10 | 6.20 与 webhook 的正式成功路径已核定 Manual Glue = 0。 | 全异常矩阵未闭合；V1 产品验收仍须保持所验正式路径 Manual Glue = 0，但不强制覆盖每种极端故障。 |

### V1 NICE-TO-HAVE / REMOVE

- **V1 NICE-TO-HAVE，需求 11：** Human 决定上传后的 GitHub 展示/上传辅助。现有 GitHub 集成有实现，6.20 的无 PR binding projection 如实为 `UNKNOWN`；没有这一步也能完成 Hub 主链，因此不阻塞 V1。
- **REMOVE / NO LONGER REQUIRED 作为 V1 Gate：** 旧 6.21 A–I 整体 PASS、为旧 F/G/I 强制新建双 Task/暂停 consumer/重启 Hub/演练 Case G、第三轮自动终审或额外 Human review budget 作为 V1 成功路径、GitHub PR binding/Comment projection PASS。相关代码与历史报告本次不删除；其中仍有价值的故障恢复工作进入 V1.1 backlog。

## 阶段终点重新定义

### 6.21 — V1 产品流程验收

6.21 验收 11 条需求直接要求的产品行为，而非旧负面故障矩阵：

1. Human 提需求后，WorkBuddy 先出方案且方案 PASS 前不编码；方案通过 webhook 触发真实 GrokBot R1，返回建议，WorkBuddy 修订后再次通过 webhook 提交。
2. 方案 R2 只给 PASS/BLOCKED；小问题不作为 BLOCKED。PASS 才编码；BLOCKED 停止并向 Human 展示四份指定材料。
3. 代码与测试交 GrokBot；Final R1 PASS 交付，或 R1 给修改意见后 WorkBuddy 仅修改一次；Final R2 仅 PASS/BLOCKED。R2 BLOCKED 仍展示操作方法、生成文件、理由及未验收状态，不自动进入 R3。
4. Control Center 显示需求 10 的全部字段与完整时间线；Hub 记录与展示一致。GitHub 上传保持独立 Human/ChatGPT 决策。

正常正式路径的身份、异步事件、Hub SoT 与 Manual Glue = 0 仍必须成立。旧 6.21 A–I 中与上述行为直接相关的已有证据可引用，但 **A–I 全矩阵不再是 V1 Exit Gate**。旧 [6.21 报告](PHASE6_STEP6_21_NEGATIVE_E2E_REPORT.md) 的 `IN PROGRESS / PARTIAL / BLOCKED` 是历史结论，不改写为 PASS。**新定义 6.21 当前未验收。**

### 6.22 — V1 实际可用性验收

在 5 个 blocker 对齐且 6.21 产品流程验收成立后，Human 从 WorkBuddy 的普通需求入口实际使用一次产品，检查审核、交付或阻断展示、网站时间线与所需文件是否可理解且可用；随后进行 Human 验收与运维交接。它不增加新的 reliability gate，也不自动授权部署、Hub restart、GitHub 上传或生产变更。**6.22 当前未开始、未 PASS。**

## 最短收尾路径与 Human 操作点

1. Human 审阅本产品范围；后续单独授权对齐合同、WorkBuddy 流程、双轮决策和网站。
2. 完成 5 个 blocker 后，只围绕上述产品场景进行必要验证，不重跑旧 A–I 故障矩阵。
3. 经另行授权执行实际使用验收及所需发布；Human 核对网站、交付物与阻断展示。GitHub 上传由 Human / ChatGPT 单独决定。

预计 Human 必要操作点：范围与合同确认、产品/网站验收、后续生产发布或重启授权；GitHub 上传决策仅在需要时发生。

## 证据边界

- [Current Production Baseline](CURRENT_PRODUCTION_BASELINE.md) 维护当前阶段与正式运行事实；本文件维护 V1 产品范围与 Exit Gate。两者都不能把文档变更当作产品 PASS。
- [6.20 Real Final E2E](PHASE6_STEP6_20_REAL_FINAL_E2E_REPORT.md) 只证明当时的 Hub 核心业务链；其中 Plan round 3 是历史事实，不能充当 V1 双轮验收。
- [Reviewer Webhook Wake Report](PHASE6_REVIEWER_WEBHOOK_WAKE_REPORT.md) 只证明当时正常 webhook wake Human 复测范围。
- [旧 6.21 Negative E2E Report](PHASE6_STEP6_21_NEGATIVE_E2E_REPORT.md) 与 [Case G runbook](PHASE6_STEP6_21_CASE_G_REWAKE_RUNBOOK.md) 保留原文和原状态，供可靠性工作引用；不再决定 V1 出口。
