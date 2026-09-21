# 安全设计与人类控制权

当前实际边界：Phase 2 提供 stdio MCP 与 loopback HTTP；Phase 3 提供 loopback GitHub Webhook 和文件型 Comment mock；Phase 3.5 新增显式 opt-in 的 GitHub HTTPS Comment transport。Webhook secret 与 Comment Token 仅从进程环境注入；正确签名也不授予 Reviewer 身份。真实仓库/tunnel 只读与入口预检已做，但未配置 Webhook、未注入 Token、未写真实 Comment，也未连接 Grok/ACP。principal 仍由本地受信配置映射。当前验证与剩余风险见 [Phase 3.5 报告](docs/PHASE35_REPORT.md)。

## 威胁模型与三层控制

不可信输入包括需求文档、源码注释、SQL、GitHub 评论、Reviewer 输出和 Artifact。其文字不能改变系统权限、选择新下载地址或跳过批准。Prompt/Skill 规定行为；Hub RBAC + 状态机强制；真实账号/网络/数据库权限形成最终边界。

| Principal | 可做 | 禁止 |
|---|---|---|
| Builder | 提交计划/产物、请求审核、接受/修复/证据拒绝 Finding | 写 Review verdict、VERIFIED、waive、自批高风险动作 |
| Reviewer | 读取授权快照、提交 review、复审 verification、评论 | 修改被审内容、生产写入、扩大权限、人工 override/approve |
| Human | 指定范围批准/拒绝、waive、override、恢复预算 | 用匿名 GitHub 评论代替 Hub 认证决策 |
| System | worker、事件处理、timeout、投影 | 冒充 Human 或 Reviewer 业务判断 |

Grok 默认只有 READ/REVIEW/COMMENT，无 Oracle/SQL Server 生产写权限、SYSDBA、服务器管理员、DDL/DML/部署/删除/重启权限。只读证据来源亦需授权；AWR/ASH/Diagnostics Pack 相关检查先确认许可，证据不足不擅自采集。

## 高风险审批

生产 DDL/DML、DROP/TRUNCATE/DELETE/UPDATE、ALTER SYSTEM、SHUTDOWN/RESTART、DEPLOY、删资源、覆盖配置、改防火墙或账号权限一律先进入 AWAITING_HUMAN_APPROVAL。动作分类以实际效果/环境为准，禁止仅靠 SQL 关键字绕过；EXECUTE 包裹写操作仍高风险。

请求须提供：task_id、action 类型、精确参数/脚本 sha256、目标环境与对象、影响范围、前置检查和备份 artifact、回滚方案、验证方案、批准有效期。Hub 规范化后生成 action_digest。独立 HUMAN_APPROVER_IDS 中的人类认证账号批准；Builder/Reviewer 的 API token 没有该权限。

审批用例：创建冻结请求 → Task AWAITING_HUMAN_APPROVAL → 人类检查内容 → approve/reject → 同事务更新 approval + audit + Task。批准后只允许对应 EXECUTING 动作；执行前再次核验 digest/revision/expiry/参数/目标权限并原子消费一次性许可。参数、代码、对象或环境变化即失效，需新审批。拒绝可取消或返 PLANNING；过期升级人工。

V1 不提供通用生产执行器或任意 shell/SQL 执行 Tool；审批机制用于阻止未授权调度，实际高风险执行在后续明确范围内设计。若外部 Executor 将来启用，必须同样验证许可，不能只依赖 Builder 口头承诺。

REVIEW_OVERRIDE、FINDING_WAIVER、HIGH_RISK_ACTION、RESUME 四类审批不可互换。PASS 只代表交付审核，不能暗含 deployment；最终任务交付可以是待人工执行的脚本，但不得把尚未批准的实际生产变更标记为已执行。

## 认证、网络和消息

本地 Hub 默认只监听 127.0.0.1。HTTP/CLI/MCP 绑定真实 principal，不信客户端提交的 actor_type。HTTP/MCP 明确 token scopes；HTTP 校验 Origin/Host、防 DNS rebinding；stdio 使用独立本机运行账号权限，stdout 仅 MCP 协议。不是把共享本地 token 当成人类身份。

GitHub Webhook：原始 bytes 上计算 HMAC-SHA256、常数时间比较 X-Hub-Signature-256；无签名/错签名拒绝。正确签名证明 GitHub 传输，**不证明评论作者有 Reviewer 权限**；还要核对仓库 immutable ID、comment user ID、安装身份和 request.expected_reviewer_actor_id。[GitHub 验签规范](https://docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries)

无效请求不得改变 Task；safe Audit 记录 received hash、错误类别与已验证身份，限制大小/速率。签名日志不记录 secret、Authorization、完整请求体。Webhook 只在持久化后 ACK，Pull 用经认证 API 读取作者与内容，不模拟不存在的 webhook signature。

重放防护：delivery ID 去重 + 跨模式 canonical resource/revision key + RR 单次完成 + 当前 deadline/revision 守卫。GitHub 没有可在所有事件上依赖的统一签名时间戳头，不编造它；payload 的资源时间和 Hub 接收时间是辅助证据，不能替代持久化去重。Header 可被重新包装，因此只按 delivery ID 去重不够。

## Artifact 与 Secret

绝不把 C:\ 本机路径当作云 Reviewer 可读路径。下载端只接受注册 artifact_id，映射 allowlist 存储后读取，禁止外部随意 URL、UNC、`..`、junction/symlink 逃逸、SSRF 或自动执行 HTML/脚本。内容长度和 hash 验证后再交给 Reviewer；日志/SQL 先脱敏。访问能力短期、按 task/artifact/actor 绑定，签名 URL 属 secret，不进公共 Comment。

.env 不提交；真实凭据通过运行用户的安全存储或受保护环境变量注入，不从历史会话、浏览器 cookie 或已有 Connector 中提取凭据。Comment transport 推荐 fine-grained token 且仅限目标仓库：Metadata read + Pull requests write 或 Issues write。HTTP 错误不得把响应 body、Token、Authorization 或 webhook secret写入日志/Audit；只保存白名单 rate-limit/request-id metadata。独立 A/B 身份、密钥轮换和撤销仍须单独验收。

## 审计与剩余风险

Audit append-only，权限失败也保留记录；payload_summary 只含白名单 metadata/hash，错误堆栈脱敏。原始 Review/Artifact 大对象分开存储。安全日志和通信记录最少留存周期须在人类上线审核时确定；设计默认 Artifact 180 天且被引用/hold 不清理，Audit 不自动删除。

SQLite trigger 和文件 ACL 不能抵御本机管理员；要防篡改须离机签名备份/不可变存储。共享 Grok 云电脑可能共享登录态，Prompt 无法保证 actor 独立，必须验证真实 GitHub identity。所有生产写权限与实际账号隔离目前 UNVERIFIED，详见 [能力登记](docs/CAPABILITY_VERIFICATION.md)。
