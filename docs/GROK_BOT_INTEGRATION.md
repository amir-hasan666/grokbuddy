# Grok Bot：唤醒和返回通道

核查日期 2026-09-16。本次只读公开官方资料和本机安装目录痕迹，遵守当前要求：不连接真实 Grok，不触发 Routine，不创建生产 GitHub 自动化。

用户确认产品为 [Grok Bot](https://x.ai/bot) / [官方 overview](https://docs.x.ai/grok-bot/overview)，自述 Grok Bot 与 WorkBuddy 已登录、GitHub Connector 已连接，测试仓库名 `grokbuddy`。状态记录为 USER_REPORTED；仓库 owner/visibility、Connector 实际主体与 scopes、触发器及返回能力仍 UNVERIFIED。不索要 Token / Secret。

## 已确认与未确认

官方 [Skills and routines](https://docs.x.ai/grok-bot/skills-routines-and-automations) 说明定时 Routine 以及 GitHub notification 事件集成，且事件集成与普通插件分开。**官方类别支持已确认；当前账号具体 trigger/filter、是否有该集成、是否能访问目标仓库和返回结果均未确认。**

[Grok Connectors](https://docs.x.ai/grok/connectors) 列出 GitHub 数据连接，但该页面是 Grok 对话产品，不能直接作为 Grok Bot Routine 的权限证明。[Grok Bot computer/apps](https://docs.x.ai/grok-bot/computer-and-apps) 描述电脑和应用使用方式；它也没有给出本项目所需的机器回调 API。

## 主/回退通道选择

| 角色 | 选定候选 | 当前状态 | 放行条件 |
|---|---|---|---|
| primary wake-up channel | 用户指定 PR 事件候选：pr-comment / review-* → Grok Bot Routine | UNVERIFIED；配置 disabled | 当前 UI 确认真正 trigger 名与匹配规则、严格 PR/repo 过滤、同 RR 唤醒一次、独立 B 身份、结果可返回 |
| fallback wake-up channel | 定时 Routine 检查指定协作仓库待审指针 | DOC_CONFIRMED / ACCOUNT_UNVERIFIED；配置 disabled | 账号支持 schedule、固定权限/范围、认领与去重、最坏等待小于 deadline |
| 人工应急 | 人类手动交付已冻结审核包、登记返回证据 | 不视为自动通道已通过 | 明确 Human Relay provenance，不能伪造 B 回传 |

`pr-comment` / `review-*` 是用户给定的设计标签，不宣称是 GitHub webhook 或 Grok API 的真实事件枚举；通配符绝不直接注册。优先评估是否能通过官方已说明的 GitHub notification 事件集成映射到所需 PR 事件，再按当前 UI 的实际选项配置。Issue Comment、PR Comment、PR opened/review_requested、Routine incoming webhook 的具体 Grok 支持均 UNVERIFIED。GitHub 拥有相应 event 不代表 Grok 支持该 trigger。不得自行发明 Grok API endpoint、event 名或用 xAI 模型 API 偷换 Bot Reviewer。

H8 要求最终选定**经过当前账号验证**的通道；当前仅可选定候选，无法宣布 H8 验收完成。对应实现必须保持禁用。Phase 0 外部 Gate 为 BLOCKED，用户须审核后决定如何补足证据，不能静默跳过。

## Review 返回路径（待验证）

优先设计：B 获取冻结 input/profile/artifacts → 独立审核 → 写 REVIEW_RESULT 到经许可的 Artifact Store → B 在选定 carrier 发表 AI-REVIEW v1 指针 → Hub Pull/Webhook 取回、验身份/hash/schema、统一事件处理。

当前尚未确认 B Connector 能写 Artifact 或发表评论；B 可能只有读权限。若只能返回聊天文本：人工下载 JSON、通过独立人类入口提交，Audit 明记 HUMAN_RELAY 与原始输出证据；该流程不满足自动 Reviewer E2E，只是候选替代。若只能通过 Git 文件输出则需评估 contents write 与 Reviewer 最小权限冲突，优先独立结果仓库或 Hub 受限 artifact upload，而不授予生产仓库写权限。

Cloud Reviewer 无法直接访问 Windows 本地 Artifact。必须验证不可变 Git 文件或受认证下载服务。download URL 不能携带公开 secret；审查输入携带项目自有逻辑 pointer 也必须有能解析它的适配器，不能假定 Grok 原生支持。

## 人工配置与后续实测步骤

1. 核对当前 Bot 产品/版本/账号/套餐；查看 Routine 设置和事件集成连接方式；只记录可选项与状态，不获取凭据。
2. 建独立 Reviewer Bot，赋予生产审核行为；Phase 4 生成 `grok_bot/reviewer_skill.md`、`grok_bot/routine_setup.md`、`MANUAL_GROK_SETUP.md`。Skill 从 Hub 读取 Profile 快照，不复制 Oracle 规则。
3. 在批准的非生产协作仓库连接独立 GitHub B 身份；校验 B != A、实际权限和 artifact 读写策略。
4. primary 测试先查当前 UI 中与 PR comment/review 对应的实际 trigger；若只有 notification，则确认其能否严格过滤目标 PR 事件。限制 repository/resource/RR 匹配，发一条无敏感内容的测试输入，记录 event→run→output provenance。不得把 pr-comment/review-* 当作已有官方枚举。
5. fallback 测定时检查相同 RR 的去重，不自动新建轮次；限制成本、扫描窗口和 deadline。只在 primary 明确失败/人工选择后切换，不能同时重复唤醒。
6. 审核输出必须通过 schema；分别试 invalid JSON、无证据、错误 actor、重复结果和超时，保存 run ID、GitHub resource ID、RR ID、hash 与脱敏证据。
7. 所有真实写操作、Routine Test run 和真实模型调用在后续明确授权范围内执行。本阶段不执行这些步骤。

若账号不支持候选：输出 confirmed/unverified/限制/阻塞/替代方案，保留 Grok 独立 Reviewer 目标，请人类决定；不改成 Builder 自审。
