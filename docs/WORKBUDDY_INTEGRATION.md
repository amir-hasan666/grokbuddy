# WorkBuddy 接入验证与设计

## Phase 6 trigger ingress 接线（2026-09-21）

6.17-B 的现场失败不是 Hub 守卫缺陷：当前用户级 `mcp.json` 只有 `grokbuddy-hub`（固定 `builder`）和 `grokbuddy-worker`（固定 `workbuddy-worker`）。普通 Hub 的 `create_task` 即使收到调用方提供的 `trigger_evidence`，也必须因 actor 不是 `workbuddy-ingress` 而返回 `PERMISSION_FAILURE`；Worker surface 根本不暴露建单工具。

仓内现已增加第三个、独立且最小的 stdio surface：`grokbuddy-ingress`。它只列出 `create_triggered_task`，固定绑定 `workbuddy-ingress`，不接受 actor 或签名作为工具参数。工具接收当前消息的 provenance segments、由 WorkBuddy Skill 运行时注入的 session ID 和稳定 idempotency key；connector 进程签发 HMAC evidence 后，再调用原 `ClientGateway → TaskService.create_task`，Hub 在创建事务里继续执行 6.1 的 principal、签名、正文 hash、exact phrase、offset、时效和活动 conversation 双检。普通 Hub/Worker 的工具和权限没有放宽。

WorkBuddy 5.5.6 当前实际能力与边界：

| 能力 | 当次证据 | 对 ingress 的影响 |
| --- | --- | --- |
| `stdio` / `sse` / `http` 与 `mcpServers` | 本机 5.5.6、用户配置、[官方 MCP 文档](https://cloud.tencent.com/document/product/1831/137039) | 采用与现有 Hub/Worker 一致的 stdio 子进程。 |
| `command` / `args` / `env` / `defer_loading` / tool override | 官方文档和本机配置 shape | 无 Secret 配置样例可直接合并；点火工具保持非延迟，避免模型继续选择普通 Hub 建单。 |
| 当前 session ID | [官方 Skills 文档](https://cloud.tencent.com/document/product/1831/137020)说明 `${CODEBUDDY_SESSION_ID}` 会在 Skill 运行时替换为当前会话 ID | skill 必须把替换后的值原样传给 ingress；未展开的占位符会被拒绝。同一 conversation 即使 stdio 重连也继续使用同一 Hub conversation ID。 |
| 当前消息 immutable ID / provenance 自动注入 custom MCP | 官方自定义 MCP schema 未给出 native user-message ID 或 provenance 注入字段；本机配置也没有 | message/turn ID 由 runtime session ID + 每消息稳定 idempotency key 派生；segments 由 skill 按当前消息传入并由 ingress/Hub 两次解析。Human B4/C 已验证当前真机路径满足 6.17；不外推为 native immutable message ID 能力。 |
| message provenance segmentation | 由 WorkBuddy 技能传入；Hub 仍自行解析 fenced/indented/inline code 和 Markdown quote | skill 必须把粘贴文档、附件、工具输出标成排除 source；不能把它们改标成 `user_body`。 |

### WorkBuddy 配置步骤（Human 已为 6.17 完成；保留作 runbook）

1. 在 Windows Credential Manager 为当前登录用户新增 Generic Credential Target `GrokBuddy/GROKBUDDY_TRIGGER_SOURCE_KEY`，值不少于 32 UTF-8 bytes；它必须与 Hub 使用的同名 Key 完全一致。不要把值贴进聊天、命令历史、`mcp.json`、Git、日志或报告。
2. 运行 `scripts/windows/Test-GrokBuddyCredentialStore.ps1`；输出只能包含四个 Target 的 `PRESENT`。按既有运维 runbook 让 Hub 在下一次受控启动时读取新增 Target；PublicBase 继续固定为 `https://grokbuddy.amirhasan.top`。
3. 把 [workbuddy-ingress-mcp.example.json](examples/workbuddy-ingress-mcp.example.json) 中的单个 `grokbuddy-ingress` 条目合并到 `C:\Users\22241\.workbuddy\mcp.json`。样例通过 `Start-GrokBuddyIngressMcp.ps1` 从 Credential Manager 读取 Key，JSON 中没有 Secret。Phase 6.19 起还必须按下节把现有 Hub/Worker 与 ingress 的 RuntimeDir 一并对齐到正式 SoT。
4. 将 [trigger skill](workbuddy-skills/grokbuddy-trigger-ingress/SKILL.md) 安装到 WorkBuddy 用户 skills 目录并刷新/重启 WorkBuddy。确认 Skill 中的 `${CODEBUDDY_SESSION_ID}` 在执行时被替换；MCP 管理界面中对 `grokbuddy-worker` 点“信任”（若尚未），并对新 `grokbuddy-ingress` 完成首次信任。
5. 确认 `grokbuddy-ingress` 只显示 `create_triggered_task`。无精确短语时不调用；命中时只调用该工具，不调用 `grokbuddy-hub.create_task`。失败时不得回退到普通 create、Quick Tunnel、人工 once 或粘贴 findings。

`grokbuddy-ingress` 是本机 stdio 点火面，不经 PublicBase；固定 PublicBase 仍用于长期 Hub health/read-only Remote MCP/Reviewer 路径。Human 已完成 connector 加载、信任、Credential、skill 与单工具 `tools/list` 前置，并在现为历史证据库的 `var/workbuddy-mcp/hub.db` 取得 B4/C 证据，6.17 已关闭为 PASS；详见 [6.17 Trigger Isolation 报告](PHASE6_STEP6_17_TRIGGER_ISOLATION_REPORT.md)。此 PASS 不等于 6.19/6.20 或完整 E2E。

### Phase 6.19 RuntimeDir 单一 SoT（2026-09-22）

正式 RuntimeDir 的唯一锚点是 [grokbuddy.service.json](../config/grokbuddy.service.json) 的 `runtimeDir`，当前解析为 `D:\Codex\grokbuddy\var\github-manual`。正式 Hub 已由 `Start-GrokBuddyHub.ps1` 读取该值；`Start-GrokBuddyIngressMcp.ps1` 未传 `-RuntimeDir` 时也读取同一值。仓内 JSON 样例显式参数已与它对齐，但**修改样例不等于修改本机 WorkBuddy 配置**。

Human 必须在本机 `C:\Users\22241\.workbuddy\mcp.json` 中只改路径参数，不写入或改动任何 Key/Token：

| server | 要检查的参数 | 必须值 |
| --- | --- | --- |
| `grokbuddy-hub` | `--runtime-dir` 后一项 | `D:\Codex\grokbuddy\var\github-manual` |
| `grokbuddy-worker` | `--runtime-dir` 后一项 | `D:\Codex\grokbuddy\var\github-manual` |
| `grokbuddy-ingress` | `-RuntimeDir` 后一项；也可删除这两个参数以采用 launcher 的 service config 默认值 | `D:\Codex\grokbuddy\var\github-manual` |

保存后刷新/重启 WorkBuddy 的三个 MCP server，再运行 `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\Test-GrokBuddyRuntime.ps1` 并保留非 Secret 摘要。Human 已完成 6.19 本机复核：三个 RuntimeDir 均为 `D:\Codex\grokbuddy\var\github-manual`，对齐后探活 `CheckedAt=2026-09-22T09:48:39+08:00` 全绿，且 `grokbuddy-ingress` 仍仅暴露 `create_triggered_task`；Phase 6.19 已 PASS。不要迁移或删除 `var/workbuddy-mcp/hub.db`；它只保留为 6.17 及更早阶段的历史证据库。`6.19 PASS ≠ 6.20`，真实点火/E2E 未跑。

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
| LOCAL PASS | Hub Server 当前可列出精确 12 tools；legacy handshake、stdio 子进程 `create_task`、PENDING/query 分离、跨进程幂等重放通过 | 官方 Python client；不是 WorkBuddy 客户端实调 |
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
  --runtime-dir var\github-manual `
  --contracts-dir docs\contracts `
  --actor builder `
  --human-actor human
```

仓库内临时配置是 [workbuddy-mcp-smoke.json](examples/workbuddy-mcp-smoke.json)。目标用户级配置内容仍由 WorkBuddy 管理；仓内示例变更不会修改该用户级文件。Phase 2 用户报告的真实调用及其 `var/workbuddy-mcp` Hub DB/Audit 保留为历史证据，不作为 Phase 6.19 正式 SoT。

HTTP/CLI fallback 未删除，仍调用同一个 `ClientGateway`。MockReviewer 仍由独立 `worker-once`/worker 边界推进；MCP tool call 不同步等待 verdict。

## Phase 2 关闭证据边界

用户明确确认 Phase 0–2 已关闭，并提供 WorkBuddy 创建的 task id。本地只读复核确认：Task 状态 `NEW`、owner=`builder`、version=0，且业务 Audit 各一次。这里没有独立保存 WorkBuddy UI/网络 trace，因此最准确的表述是“用户报告真实调用 + Hub 结果已本地确认”，而不是从数据库单独反推全部客户端链路。Phase 3 不再修改 MCP/HTTP/CLI 行为。
