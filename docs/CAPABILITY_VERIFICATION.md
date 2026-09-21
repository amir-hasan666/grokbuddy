# Phase 0 外部能力证据登记

2026-09-18 状态补充：Phase 3 本地退出与 Phase 3.5 Real GitHub Integration 均已通过。真实公开仓库 `amir-hasan666/grokbuddy`（repository id `1372874264`）的 PR #2 已正式绑定；签名 `pull_request:synchronize` 经 cloudflared 到 `127.0.0.1:8788` 后返回 202，并在 Hub 产生 Final Review `PENDING`。既有 Mock/Application 路径完成该 Review 后，真实 PR Comment 已 CREATE、同 ID UPDATE，重复投影无第二条评论。listener/tunnel 已停止；不放行 Grok、ACP、Phase 4 或高风险 GitHub 写操作。

检查时间：2026-09-16（Asia/Shanghai）。等级：CONFIRMED 必须注明 PUBLIC_DOC 或 LOCAL_OBSERVATION；ENVIRONMENT_VALIDATION_REQUIRED 表示目标能力有依据、当前环境未验；UNVERIFIED 表示具体能力/权限/返回路线没有足够证据。不存在“查到文档即真实集成通过”。

## 本次实际操作

用户补充证据（USER_REPORTED）：产品为 x.ai/bot / docs.x.ai/grok-bot/overview；Grok Bot 与 WorkBuddy 已登录；GitHub Connector 已连接；测试仓库名 grokbuddy。owner/visibility、实际 A/B actor、权限及触发器未获运行证明。用户要求 PR 事件 pr-comment/review-* 为首选设计，Issue Comment 唤醒 UNVERIFIED；已纳入文档，不把候选名称写成官方 API。

- 项目开始时为空目录；未找到根/上级 AGENTS.md；未创建 Git 仓库、远程或生产自动化。
- 只读查询官方文档、程序目录/renderer 版本文件、default MCP 配置字段结构（不输出 URL、headers、env 值或凭据）。未读取 credentials、账号数据库、聊天记录或 Grok 会话。
- WorkBuddy renderer-version.json 返回 `5.5.6`。default/mcp.json 有 134 条配置，包含 GitHub；不是已启用/已登录的证明。账户专属 Connector 子目录读取被操作系统拒绝，未绕过。
- 找到 WorkBuddy 与 Grok Bot 本地应用数据目录；未看到可确认的运行进程/完整桌面 About 版本，也未进行 UI/账号连接测试。没有使用 Grok 真实调用。
- PATH Python 为 3.14.3；`py -0p` 显示无注册 Python；Codex 随附 Python 为 3.12.14。本地 `mcp/jsonschema/yaml/pytest` 原先均未装。Phase 0 独立 venv 仅安装验证依赖，未安装业务栈或 MCP SDK。
- 默认网络沙箱阻止首次 pip 下载（WinError 10013）；随后经允许的环境外网络执行在项目 venv 成功安装验证依赖。无自动审批拒绝，无残留阻塞。

## 能力矩阵 / 当前所有外部未验证项

| ID | 能力 | 结论与证据 | 影响 / 如何补证 / 备选 |
|---|---|---|---|
| C01 | WorkBuddy 自定义 MCP | CONFIRMED PUBLIC_DOC，S01/S02 | 可采用 MCP 目标设计，不代表本机可用 |
| C02 | WorkBuddy 当前版本 | LOCAL_OBSERVATION：`WorkBuddy.exe` FileVersion=5.5.6、ProductVersion=5.5.6.0，last-launch=5.5.6 | 后续升级需重新探测；不要混用 CodeBuddy CLI 包版本 |
| C03 | 当前 Connector/登录/权限 | 登录/已连接由用户报告；实际主体/权限 UNVERIFIED；账户目录 access denied | 当前 UI/只读身份验证；禁止从 default catalog 或自述推断 scopes |
| C04 | stdio / Streamable HTTP / auth / timeout / Tool Schema | LOCAL_OBSERVATION + PUBLIC_DOC：5.5.6 CLI 支持 stdio/sse/http，默认 stdio；JSON 字段已确认 | 本轮选择 stdio；真实 WorkBuddy timeout/approval 行为仍需实调 |
| C05 | Hub 客户端 roundtrip | 官方 MCP SDK legacy handshake、11 tools、stdio subprocess 与重连幂等 PASS；WorkBuddy real create_task 为 USER_REPORTED + LOCAL DB CONFIRMED | 指定 task 与 Audit exactly-once 已复核；UI/网络 trace 未独立保存 |
| C06 | Grok GitHub notification Routine 类别 | CONFIRMED PUBLIC_DOC S04 | 用户指定 PR 唤醒方向的可选映射；具体 PR filter/trigger 名仍 UNVERIFIED |
| C07 | 当前 Grok 账号/版本/事件集成 | 已登录为 USER_REPORTED；版本/具体事件集成与运行结果 UNVERIFIED | 查看账户 Routine 配置；遵守本轮不连接真实 Grok |
| C08 | 定时 Routine 类别 | CONFIRMED PUBLIC_DOC S04；当前账号调度 UNVERIFIED | fallback candidate；测试等待上限和重复认领 |
| C09 | PR pr-comment/review-*（主候选）、Issue Comment、Routine webhook 唤醒 | 全部 UNVERIFIED；用户候选标签不是官方枚举 | 设计优先 PR，实际映射待当前 UI 确认；Issue 不作为默认唤醒，通道不启用 |
| C10 | Grok GitHub Connector 读写/评论/Artifact 返回 | UNVERIFIED；S05 是 Grok 对话 Connector，不能证明 Bot 集成 | 隔离测试仓库测 read + result artifact + B comment；人工 relay 仅应急 |
| C11 | GitHub carrier 与资源 API | LIVE READ：公开仓库 `amir-hasan666/grokbuddy`，repository id `1372874264`，default branch `main`，PR=0；UI 显示当前账号可进入 Settings | 无 PR，不能正式 bind 或验证 Comment；Token 类型/scopes仍 UNVERIFIED |
| C12 | Webhook 验签/事件传输 | LOCAL PASS：签名四态、delivery/semantic dedup、PR synchronize→PENDING；TUNNEL PREFLIGHT：公网 GET `/webhooks/github` 到应用 405，本机无签名 POST 401；REAL DELIVERY BLOCKED | 未配置 GitHub Webhook，无 Delivery ID/真实 HMAC/github_events 证据；quick tunnel 已停止 |
| C13 | Pull 模式评论读取 | CONFIRMED PUBLIC_DOC S08；本轮未实现，分页、限流、断网追赶均 UNVERIFIED | 后续单独授权；不要用 Events feed 替代可靠查询 |
| C14 | Builder/Reviewer/Human 独立 identity | ENVIRONMENT_VALIDATION_REQUIRED；本项目未验证 A/B/C | 真实 actor ID/scopes 测试；同账号两 token 不算独立 |
| C15 | 文件系统 Artifact | 设计已选择；安全路径/hash/权限/GC 运行测试未做 | Phase 1 文件测试；不能把文档目录写成功当作 ArtifactStore 通过 |
| C16 | 云 Reviewer 读取本机 Artifact / 结果写回 | UNVERIFIED | 受认证下载或不可变 Git Artifact 实测；本地路径不可直接使用 |
| C17 | 官方 MCP SDK 稳定线 | CONFIRMED PUBLIC_DOC；已锁定并安装 Python SDK 2.2.0，本地以 legacy 2025-11-25 握手测试 | WorkBuddy bundled Node SDK 1.29.0 的真实客户端调用仍待 Gate |
| C18 | Profile、审批、幂等、安全策略执行 | LOCAL PASS 覆盖 Phase 1–3 规则、Adapter delivery/semantic 去重及 Phase 3.5 Comment transport 分类/marker-first 重试；真实 Comment projection dedup 已验证 | 生产身份认证/ACL 仍需单独验收 |
| C20 | GitHub Comment REST transport | REAL PASS：PR #2 comment id `5724651683` 完成 list/create/update；marker/Hub pointer 存在，重复 CLI 投影 no-op，同 marker 评论数为 1 | 401/403/rate-limit/timeout/5xx 按本轮约定保留离线分类证据；未破坏有效 Token 制造错误 |
| C21 | Cloudflare quick tunnel | REAL PASS：真实 synchronize Delivery `cc895670-b30f-11f1-83f9-d7e56d30cc53` 含签名 header、Hub Response 202、ingress `APPLIED`/RR `PENDING` | 仅测试用途、无 SLA；联调后 listener/tunnel 已停止 |
| C19 | SQLite 并发恢复/备份与 Windows 文件 ACL | LOCAL PASS 覆盖崩溃/锁/restore/path 边界；管理员防篡改与真实 ACL 矩阵未验 | V2 仍是单机本地磁盘；Phase 3 为加法迁移 |

## 官方来源（本次实际检索）

| ID | 官方来源 | 支持的有限结论 |
|---|---|---|
| S01 | [WorkBuddy 桌面连接器](https://www.workbuddy.cn/docs/workbuddy/From-Beginner-to-Expert-Guide/Function-Description/Connector) | 自定义 MCP 连接器入口 |
| S02 | [WorkBuddy 开放平台连接器](https://open.workbuddy.cn/docs/connector) | MCP/CLI 两种接入，认证配置需按产品流程 |
| S03 | [MCP transport 2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports) | stdio、Streamable HTTP 与本地安全要求；作为兼容基线，不声称最新版本 |
| S04 | [Grok Bot skills/routines](https://docs.x.ai/grok-bot/skills-routines-and-automations) | schedule、GitHub notification 事件类别，事件集成独立于插件 |
| S05 | [Grok Connectors](https://docs.x.ai/grok/connectors) / [Grok Bot computer/apps](https://docs.x.ai/grok-bot/computer-and-apps) | 产品范围区分；不能推出机器返回 API |
| S06 | [GitHub signature validation](https://docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries) | 原始 body + X-Hub-Signature-256 |
| S07 | [GitHub webhook events](https://docs.github.com/en/webhooks/webhook-events-and-payloads) | 实际 GitHub event 目录，不证明 Grok 支持 |
| S08 | [GitHub issue comments REST](https://docs.github.com/en/rest/issues/comments) | 评论 API 与 Pull carrier 依据 |
| S09 | [GitHub webhook best practices](https://docs.github.com/en/webhooks/using-webhooks/best-practices-for-using-webhooks) | 持久化/快速 ACK、重复 delivery 处理 |
| S10 | [官方 MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) | 当前稳定主线声明，未来锁版本依据 |
| S11 | [WorkBuddy Enterprise MCP 使用文档](https://cloud.tencent.com/document/product/1831/137039) | `mcpServers` 配置、stdio/SSE/http transport 与 CLI 字段 |
| S12 | [GitHub REST rate limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api) | 403/429、Retry-After、remaining/reset 与停止重试要求 |
| S13 | [Cloudflare Quick Tunnels](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/) | 临时开发 tunnel 用法与非生产限制 |
| S14 | [GitHub REST API versions](https://docs.github.com/en/rest/about-the-rest-api/api-versions) | `2022-11-28` 仍受支持至 2028-03-10 |

## Gate 结论

LOCAL_DOCUMENT_AND_CONTRACT_VALIDATION 以 [验证报告](VALIDATION_REPORT.md) 为准；Phase 3 本地退出证据见 [PHASE3_REPORT](PHASE3_REPORT.md)，Phase 3.5 见 [PHASE35_REPORT](PHASE35_REPORT.md)。`PHASE3.5-REAL-GITHUB-EXIT: PASSED`：真实签名 Webhook、正式 binding、synchronize→PENDING、Mock/Application 完成、Comment CREATE/UPDATE、重复投影无重复评论和全回归均有证据。未调用 Grok/ACP/WorkBuddy wake-up，未进入 Phase 4。
