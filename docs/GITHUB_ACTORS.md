# GitHub Actors

| Actor | 身份与凭据设计 | 验证 |
|---|---|---|
| A = Builder / Hub | 专用 GitHub App installation A 或最小权限 PAT A | 只在指定测试/协作仓库提交待审指针与 Hub 状态摘要 |
| B = Reviewer / Grok | 独立 bot account/App B 的 Connector 授权 | provider_actor_id 必须与 A 不同，输出作者身份与 request.expected_reviewer_actor_id 一致 |
| C = Human | 独立 Hub 审批主体，GitHub 映射可选 | 人类认证 + approver allowlist，不能从 comment 声称身份推断 |
| S = System | Hub worker 的独立审计身份 | 投影行为记 System；不冒充 Reviewer 判断 |

生产启动必须验证 A != B，不能只是两枚同一 GitHub 用户 PAT。审计同时保存 actor_type、Hub actor_id、actor_name，以及 provider_actor_id 的映射。login 是展示信息，授权以不可变 provider ID 为准。

Reviewer 提交外部结果要用 B 凭据。若 Hub 用 A 投影“Hub 收到某 Reviewer 的结果”，必须明确是 System/Builder 的引用摘要，原始 B 结果链接/来源另存；不能把这种摘要当成 B 的入站结果。Mock 本地模式使用 `mock-reviewer` principal；若投影 GitHub，必须配置单独测试 Reviewer actor，不能伪造 sender。

GitHub 权限现实限制：评论通常需要 issues/pull_requests 的相应写权限，这可能比“仅 comment”更宽。选择独立协作仓库、不授予 contents write/admin/deploy，Hub Tool allowlist 限制具体操作，并记录平台权限粒度的剩余风险。具体 Token/App 权限及 Connector 是否允许指定 B 目前未实测，不声称天然 comment-only。

生产配置步骤：建立 A/B/C → 安装到指定仓库 → 只读确认各身份及仓库 ID → 核对 scopes → 在非生产测试仓库发布一对 A 请求/B 回复 → 验证伪造 actor 与 A 自审均拒绝 → 保存不含 token 的证据。**当前阶段不创建账号、不发消息、不安装 App。**

共享云端浏览器登录态可能使 B 实际使用 A 的 GitHub 用户。真实端到端前须专门验证；失败即阻断独立 Reviewer 上线，不通过修改 display name 掩盖。
