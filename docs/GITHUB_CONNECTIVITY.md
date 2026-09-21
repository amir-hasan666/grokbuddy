# Carrier、Webhook 与 Pull

## Carrier 选择

| 候选 | 适用性与代价 | Phase 0 决策 |
|---|---|---|
| Dedicated Review PR | 独立承载方案/非代码交付，固定 commit 文件；创建分支/PR 增加权限与维护 | 按用户 PR 事件方向作为非代码任务的首选设计载体；真实唤醒 UNVERIFIED |
| 普通 PR | 代码交付可复用 diff/commit，上下文直观 | 代码任务优先投影候选，但 PR merge/review state 不驱动 Hub |
| Issue | 文档/SQL/任意任务低耦合展示 | 仅可选人类展示；Issue Comment 唤醒 UNVERIFIED，不作为主唤醒设计 |
| GitHub Notification | 官方 Grok Routine 事件候选；取决于订阅/过滤/账号集成 | 可评估为用户指定 PR 事件的映射传输，不等于具体 PR trigger 已确认 |
| Routine Event | 是执行触发机制，不是完整 artifact/audit 容器 | 仅用正式已确认的触发类别；不猜 event 名 |
| Routine Webhook / 其他 | 未找到当前产品保证的入站 API 合约 | UNVERIFIED，禁用 |

选定的架构决策是 **Carrier 可替换、优先 PR**：业务只持有 repository immutable ID、PR number 与 task 的显式绑定。Phase 3.5 已验证真实公开仓库 `amir-hasan666/grokbuddy`，immutable repository id=`1372874264`；验收 PR #2 已正式绑定到新 Hub Task，并用第二个无功能 commit 触发真实 synchronize。Grok 候选唤醒标签不直接成为任何 GitHub API 枚举，也不参与本轮 Webhook 状态推进。

## Mode A：Webhook

GitHub → public HTTPS/secure tunnel → signature verification → repo/event/action validation → durable github_events inbox → Adapter handler → Hub Application Service。localhost 无法被 GitHub 直接访问。Phase 3.5 使用 cloudflared 2026.9.1 把唯一 `/webhooks/github` 路径转发到 `127.0.0.1:8788`。真实 opened Delivery `929ab5d0-b30f-11f1-99c4-1846cb67d08d` 返回 202 并记录为 `IGNORED`；真实 synchronize Delivery `cc895670-b30f-11f1-83f9-d7e56d30cc53` 在签名通过后返回 202，Hub ingress `GHE-3641d441-2c24-4b66-b18f-363b0750933a` 为 `APPLIED`，receipt 为 `PENDING`。联调结束后 listener 与 tunnel 均已停止。

本轮唯一会推进 Hub 的映射为 `pull_request:synchronize`。它要求 PR 已显式绑定到一个 Hub Task，Task 已有 passing self-test 与冻结 Final Package；Adapter 调用既有 `request_review(... FINAL_REVIEW ...)`，返回 `PENDING` 后停止，不执行 dispatcher/Mock/Reviewer。

`push`、`ping` 以及 `pull_request` 的其他 action 只做验签、结构解析、delivery 持久化和 Audit，状态为 `IGNORED`；未绑定 synchronize 为 `UNMAPPED`。`issue_comment` 与 `pull_request_review_comment` 明确不订阅并拒绝，防止出站 Comment 再触发审核循环。[官方事件目录](https://docs.github.com/en/webhooks/webhook-events-and-payloads)

在原始 bytes 上用进程环境提供的 secret 校验 `X-Hub-Signature-256`，常数时间比较；缺失、错签名、篡改均 401 且只写 safe Audit。验签后持久化，再返回 2xx；DB 或 Hub command 失败不 ACK 成功。`X-GitHub-Delivery` 在 Adapter 表唯一，同 delivery 相同内容返回原效果，不重复创建 RR；相同 delivery 不同 hash 返回冲突。canonical key 还避免不同 delivery header 包装同一 PR/action/head SHA 时重复产生业务效果。

## Mode B：Pull（本轮未实现）

Hub worker 使用 GitHub REST 查询指定仓库评论资源，例如官方 `GET /repos/{owner}/{repo}/issues/comments`，按 since 时间窗口、分页 Link 完整拉取；不把短期 Events feed 当可靠事件队列。评论 API 也覆盖 PR 普通评论。[官方 API](https://docs.github.com/en/rest/issues/comments)

设计 poll_interval=30 秒，watermark 回看窗口=120 秒，持久化每页结果；完整扫描后再推进 watermark，失败不跳页。对延迟可见/长时间断网定期全量扫描已关联 carrier 的评论 ID；token 撤销暂停并提示人工。新旧时间相同不能只用时间戳去重；保留 resource ID/revision/hash。外部删除无法从常规增量查询完整恢复，Hub Audit 保留已接收事件，必要人工比对。

Pull 不验证 webhook signature，它依赖 HTTPS + 经认证 API + 作者/仓库匹配。429/限流 403 退避，401/其他 403 人工修复；轮询只收事件，不自行启动新的 Reviewer 轮次。

## 同一事件管线与切换

Normalized envelope 包含 event_id、event_type、source、task_id、review_request_id、review_id、repository_id/resource_id/resource_revision（GitHub 模式）、actor_id（经边界解析）、artifact_id/hash、correlation_id、received_at、deduplication_key。Mock 来源不假造 GitHub 字段，业务 payload schema 相同。

transport key 用 webhook delivery ID 或 poll ingestion ID；**semantic key** 使用 provider + repo immutable ID + resource kind + resource ID + event kind + source revision + content hash。相同 Comment 经 webhook/pull 会生成相同 semantic key；另以 reserved review_id / RR 唯一约束防止复制 Comment 或换 delivery ID 重放。JSON whitespace 改动可能生成不同 resource key，但无法再完成同一 RR。

模式配置 disabled/pull/webhook/hybrid；切换保留 inbox、cursor 和 processed_events。先启用目标入口，再短期重叠收取，确认水位后停原入口；永不重置去重历史。候选 sender 校验后才下载 Artifact，不跟随任意 Comment URL。

无 Marker ignore；明确协议但缺 version/未知 version/非法字段 reject + Audit；格式正确也必须校验 actor、请求绑定、hash、deadline，不能根据自然语言或 GitHub PR state 推进状态。

Phase 3.5 使用签名 Webhook，不实现 Pull。Phase 3 的本地签名 fixtures、delivery/semantic 去重、PR synchronize→PENDING，以及 Final result→文件型 Comment mock 仍是基线。真实 GitHub Delivery、正式 binding、synchronize→PENDING 与 Comment API read/create/update 已通过；Token 的精确 PAT 子类型仍因响应不提供 `X-OAuth-Scopes` 而保持未判定。

## Comment 投影

完成的 Final Review 由显式 projector 排队，Comment 仅含 `status`、`verdict`、短 `summary`、`task_id`、`review_id`、`review_request_id`、Hub 逻辑指针，以及稳定 marker `<!-- grokbuddy-final-review:REVIEW_ID -->`。投影先按 marker 查找：找到则更新，未找到才创建；外部投影失败只重试/标记失败，不回滚 Hub Review/Task。

`FileGitHubCommentTransport` 继续作为本地/CI 默认。`GitHubHttpCommentTransport` 是显式 opt-in，仅实现普通 PR issue-comment 的分页查找、create、update：分页达到安全上限时拒绝创建，避免漏查后重复。401=`AUTH_FAILED` 非 transient；403 结合 `Retry-After`、`X-RateLimit-Remaining`、reset 和安全 message 区分 `PERMISSION_DENIED`/`RATE_LIMITED`；timeout/5xx 可限次重试。仅保留安全 status/request-id/rate-limit metadata，不保留响应 body、Token 或 Authorization。真实 PR #2 上 comment id=`5724651683` 已完成 CREATE 与同 ID UPDATE；marker 命中数始终为 1，Hub pointer 存在，重复 CLI 投影不创建第二条评论。
