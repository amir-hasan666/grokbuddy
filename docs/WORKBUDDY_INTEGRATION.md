# WorkBuddy 接入验证与设计

## 当前结论（2026-09-17）

WorkBuddy 5.5.6 的自定义 MCP transport 已确认，选择 **stdio**，不是猜测：

- `D:\WorkBuddy\WorkBuddy.exe` 的 FileVersion 为 5.5.6，`last-launch.json` 也为 5.5.6。
- 内置 CLI `mcp add --help` 明确支持 `stdio`、`sse`、`http`，默认 `stdio`；`--mcp-config` 可加载 JSON 文件。
- 实际 `C:\Users\22241\.workbuddy\mcp.json` 顶层为 `mcpServers`；腾讯 [WorkBuddy Enterprise MCP 文档](https://cloud.tencent.com/document/product/1831/137039) 给出相同的 `type`、`command`、`args`、`env` 字段。
- 本机内置 Node MCP SDK 为 1.29.0；Hub 使用官方 Python MCP SDK 2.2.0，并以 legacy `2025-11-25` 模式验证旧客户端握手。

因此本地单机 Hub 不启 HTTP listener，不引入端口或认证配置，使用 WorkBuddy 默认且最小的 stdio 子进程模式。脱敏探测记录见 [phase2-workbuddy-transport-probe.json](phase2-workbuddy-transport-probe.json)。

初次 Codex 执行路由中的 `MCP_FAIL` 只表示该路由没有名为 `workbuddy` 的 MCP server；它与 WorkBuddy 桌面/内置 CLI 的客户端能力是两条不同证据链。历史探测仍保存在 [phase2-mcp-probe.json](phase2-mcp-probe.json)。

## 当前验证分级

| 类别 | 结论 | 证据边界 |
|---|---|---|
| CONFIRMED transport | WorkBuddy 5.5.6 支持 stdio/sse/http，stdio 为 CLI 默认 | 本机 `--help` + 官方文档 + 实际 JSON shape |
| LOCAL PASS | Hub Server 可列出精确 11 tools；legacy handshake、stdio 子进程 `create_task`、PENDING/query 分离、跨进程幂等重放通过 | 官方 Python client；不是 WorkBuddy 客户端实调 |
| PARTIAL WorkBuddy load | `--mcp-config` 启动时创建了 Hub runtime/schema/本地主体，证明命令与配置至少进入了 Server 启动路径 | tasks/audit 均为 0；不能证明 tools/list 或 tools/call 完成 |
| USER-REPORTED + LOCAL DB CONFIRMED | WorkBuddy 真实 `create_task` | 用户提供 `TASK-12d16e55-d3ee-4d84-8dc2-d6594c965d56`；本地 Hub DB 有单一 Task 与一次 TASK_CREATED Audit。WorkBuddy UI/网络 trace 未独立抓取 |
| OUT OF SCOPE | Grok、ACP、真实 GitHub 部署 | Phase 3 仅本地 Webhook/Comment mock；未连接外部服务 |

## MCP / HTTP / CLI 共同入口

MCP/HTTP/CLI → `ClientGateway` → Application Service → Domain。MCP 不拥有业务状态，不修改 Review/Finding 协议，也不在 request handler 内运行 worker。

| Tool | 最小输入 | 输出 |
|---|---|---|
| create_task | description、profile、idempotency_key | task snapshot、NEW、version |
| get_task | task_id | 权威快照 |
| submit_plan | task_id、plan artifact、expected_version、idempotency_key | task snapshot |
| request_plan_review | task_id、expected_version、idempotency_key | RR ID、PENDING |
| get_plan_review | RR ID | RR status、result/null |
| respond_to_review | task_id、review_id、finding_id、action、证据、version、key | Finding 收据；不自动重审 |
| submit_artifact | task_id、type、text/base64、key | immutable artifact metadata |
| request_final_review | task、测试/差异 Artifact、final package 摘要、version、key | RR ID、PENDING |
| get_final_review | RR ID | RR status、result/findings |
| get_task_status | task_id | state/version/active RR/escalation |
| close_task | task_id、reason、version、key | Human audit + CANCELLED |

`request_plan_review` / `request_final_review` 只提交 durable request 并返回 `PENDING`；完成结果只能通过 `get_*` 查询。相同 command idempotency key 在 stdio 进程重启后返回同一 Task/ReviewRequest，不创建新轮次。

MCP 进程固定普通工具为本地 `builder` principal，`close_task` 固定为本地 `human` principal；payload 不接受 actor。`close_task` 仍调用原 Human cancel guard，不等同 Review PASS/HUMAN_OVERRIDE。该映射只适用于受信本机 Mock 环境，不是生产认证。

## 配置与启动

Server 入口：

```powershell
.\.venv-phase0\Scripts\python.exe scripts\grokbuddy_mcp.py `
  --runtime-dir var\workbuddy-mcp `
  --contracts-dir docs\contracts `
  --actor builder `
  --human-actor human
```

仓库内临时配置是 [workbuddy-mcp-smoke.json](examples/workbuddy-mcp-smoke.json)。目标用户级配置内容仍由 WorkBuddy 管理；本仓库未在 Phase 3 修改该用户级文件。用户报告已完成真实调用，本地 Hub DB/Audit 与给定 task id 一致。

HTTP/CLI fallback 未删除，仍调用同一个 `ClientGateway`。MockReviewer 仍由独立 `worker-once`/worker 边界推进；MCP tool call 不同步等待 verdict。

## Phase 2 关闭证据边界

用户明确确认 Phase 0–2 已关闭，并提供 WorkBuddy 创建的 task id。本地只读复核确认：Task 状态 `NEW`、owner=`builder`、version=0，且业务 Audit 各一次。这里没有独立保存 WorkBuddy UI/网络 trace，因此最准确的表述是“用户报告真实调用 + Hub 结果已本地确认”，而不是从数据库单独反推全部客户端链路。Phase 3 不再修改 MCP/HTTP/CLI 行为。
