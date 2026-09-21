# Phase 4 Remote MCP（只读验证）证据报告

日期：2026-09-20（Asia/Shanghai）。本报告只对应 Human 本轮明确授权的 Remote MCP 验证；与既有 [Phase 4 Grok Protocol 报告](PHASE4_REPORT.md) 分开。未进入 Phase 5/6，未创建 Grok Connector、运行 Routine、恢复 poller、连接 Real Grok/ACP/WorkBuddy wake-up，未更改 GitHub PR/分支或 Cloudflare 长期配置。

## 范围与起点

目标是在测试时由一个 `127.0.0.1:8788` ASGI listener 共存 `/webhooks/github`、`/mcp`、`/health`，保留原 Webhook application 与既有 11-tool stdio MCP 行为；Remote MCP 只提供 5 个只读查询。Hub DB 仍是唯一事实源。涉及文件仅为新增只读 Application query、固定 Remote MCP surface、HTTP composition/入口、测试与本报告；不改 Domain 状态机、命令幂等、backup、`provider_id`、原 Webhook application/验签/事件规则、GitHub adapter 或 stdio MCP 实现。

2026-09-18 首次检查时，8788 为原 `grokbuddy_github.py --runtime-dir var\github-manual serve --secret-env GITHUB_WEBHOOK_SECRET --host 127.0.0.1 --port 8788`；cloudflared 为 `tunnel --url http://127.0.0.1:8788`，即 Quick Tunnel。指标当时报告的 hostname 为 `resolve-holly-promoting-warming.trycloudflare.com`，**只是当时观察值，不是当前可用地址**。2026-09-20 恢复工作时，8788 和 cloudflared 均未运行，`GROKBUDDY_MCP_TOKEN` 在当前进程环境不存在；Webhook Secret 与 Comment Token 只核对了存在性，未输出值。用户要求使用“现有” tunnel，因此没有新建/重启 Quick Tunnel，也没有配置 Named Tunnel/hostname/DNS/ingress/service。

## 实现与架构 Gate

| Gate | 证据 | 结果 |
|---|---|---|
| 原 Webhook application 不变 | `src/grokbuddy/interfaces/github.py`、`scripts/grokbuddy_github.py` 未改；`composite.py` 只作 ASGI→原 WSGI application 适配；Phase 3 与 composite 签名/事件测试 | PASS |
| 官方 MCP Streamable HTTP | 已安装官方 Python `mcp==2.2.0`；`MCPServer.streamable_http_app(streamable_http_path="/mcp", stateless_http=True, json_response=True)`；真实 SDK client 协商 `2025-11-25` | PASS（本机） |
| Remote 只读面 | 独立 `remote_mcp.py` 精确注册 `get_task`、`get_task_status`、`get_plan_review`、`get_final_review`、`list_pending_review_requests`；其余 7 个写工具不在 `tools/list` 且直接调用失败 | PASS |
| Application/Hub 单一事实源 | Remote 工具经 `ClientGateway.invoke_query` 到原 Hub query；新增查询只读 `review_requests`，用既有 `ACTIVE_REQUEST` 定义非终态，按 `created_at,id` 稳定排序，只返回 schema 中的 `id/task_id/review_type/status` | PASS |
| Bearer 鉴权 | `/mcp` 的全部 HTTP 方法先经 `BearerTokenBoundary`；缺失/错误 token 为 401，正确 token 才进入 SDK；`secrets.compare_digest`；空 token 拒绝启动；GET/DELETE 等不需要方法经认证后 405 | PASS（测试 pre-shared token，不是 OAuth） |
| 最小 `/health` | 只返回 `{"status":"ok"}`；无 token、路径或业务数据 | PASS |
| SDK Host/Origin 防护 | 保留 DNS-rebinding 保护；仅本机及显式提供的现有 public hostname 可通过，未列出的 host 为 421 | PASS（本地模拟 hostname） |
| 8788 单 listener | 真实 smoke 期间 netstat 仅有一个 8788 listener，三个路径由同一 composite 进程提供；结束后原 webhook listener 已恢复 | PASS（本机） |

没有实现 legacy SSE transport、自写 MCP JSON-RPC、GET SSE stream、server-initiated notification 或 transport session state。Remote MCP 的 `/mcp` 仅接受 POST；真实 SDK client 所有 15 次 MCP 请求均为 POST，返回 `application/json`。`/mcp` access log 关闭，测试与报告不包含 Bearer token。当前没有持久 MCP token；live smoke 在子进程环境中生成临时 token，不打印、不传命令行，测试结束后 composite 已停止。

## 测试与真实本机 smoke

最终回归命令与结果：

```powershell
.\.venv-phase0\Scripts\python.exe -m pytest tests\test_phase4_remote_mcp.py -q --tb=short
.\.venv-phase0\Scripts\python.exe -m pytest tests\test_phase3_github.py -q --tb=short
.\.venv-phase0\Scripts\python.exe -m pytest -q --tb=short
.\.venv-phase0\Scripts\python.exe scripts\validate_phase0.py --allow-core
.\.venv-phase0\Scripts\python.exe -m pip check
```

- Phase 4 新测试：`8 passed`。覆盖非空 pending fixture、composite 正确/错误签名、真实业务 `pull_request:synchronize → FINAL_REVIEW_PENDING`、与原 app 相同的超大 body 413、鉴权、5-tool allowlist、7 个禁止工具直接调用、Host/Origin 安全、stdio 查询一致与全表快照不变。
- Phase 3 GitHub：`25 passed`。
- 全量：`481 passed in 85.94s`，0 failed。
- Phase 0 契约：`171/171 passed; 0 failed`。validator 的通用 `External environment gate: BLOCKED (no live integrations executed)` 是其既有输出，不替代本报告的真实本机 MCP smoke，也不证明 Grok/外部环境通过。
- `pip check`：`No broken requirements found.`

显式本机 live 命令：

```powershell
.\.venv-phase0\Scripts\python.exe scripts\verify_phase4_live.py
```

该脚本使用原 `var\github-manual\hub.db` 中真实存在的同一 Task、已完成 Plan Review、已完成 Final Review：`/health=200`，`GET /webhooks/github=405`（原 app 可达），`/mcp` 无/错 token 均 401，正确 token 完成 initialize、`tools/list` 和 5 个查询；7 个禁止工具直接调用全部拒绝。真实 stdio MCP 仍列出 11 工具，其 4 个原有查询与 Remote MCP 的业务数据逐项一致。新 `list_pending_review_requests` 不加到冻结 stdio surface，因此与 Application query/Remote MCP 比较；live DB 当时为 0 条，新增测试 fixture 验证了非空结果。

MCP 查询前后对 Hub 所有业务表的 `id,data` 有序快照一致：SHA-256 均为 `3a9beff7b62ab2afc4220a8d9c2b93e0e7618137be386a55ae715a4dbe50af8e`。Task=1、Review Request=2、GitHub Comment projection=1、Mock Job=2，均无增量。没有在 smoke 中调用 worker 或 GitHub Comment adapter。数据库快照与代码路径能证实本次 Remote MCP 没有推进 Hub 或发起 Comment；未对远端 GitHub 评论列表做独立前后读取，因此不把它表述为独立的 GitHub 账户审计。

live 脚本运行中出现两个**检测器假失败**：第一次端口刚可连接时 netstat 尚未显示 PID；第二次 Windows venv 启动器 PID 与真正监听子进程 PID 不同，脚本误报原 listener 恢复失败，故该次脚本进程退出码为 1。两处检测器已修正。第二次的 MCP 验证自身输出 `LOCAL PASS`；随后只读核对实际监听子进程 PID 6044、父启动器 PID 15464 的命令行均为原 `grokbuddy_github.py` 参数，`127.0.0.1:8788` 唯一监听、原 `/webhooks/github=405`、`/mcp=404`，证明原 listener 恢复且测试 MCP 未持续公开。修正后的恢复分支未再次停服重跑，避免重复已经完成的 live 验证；不把自动恢复脚本的退出码冒充成功。

## 公网 Gate 与剩余边界

2026-09-20 前次验证结束时 cloudflared 进程数为 0；9 月 18 日的 Quick Tunnel hostname 不能视为仍有效。该次按“只使用当前已有 tunnel、不得创建或改变 Cloudflare 配置”的限制，未做公网 `/health`/`/mcp` 调用。

### 2026-09-20 09:19 公网补测现场（Asia/Shanghai）

Human 恢复的现有 cloudflared PID 15288 命令为 `tunnel --url http://127.0.0.1:8788`，是 Quick Tunnel；其本机 metrics 显示 1 个活动 HA connection，**本轮实际 hostname** 为 `bell-applies-entrance-exterior.trycloudflare.com`。未使用 9 月 18 日旧 hostname，未启动第二个 tunnel 或修改 Cloudflare。

切换前检查发现两项与前提不符的阻断条件：

- `GROKBUDDY_MCP_TOKEN` 在当前进程、User、Machine 环境均不存在。只检查了存在性，未读取、打印或记录 token；因此不能启动受控的 Remote MCP endpoint。
- `netstat -ano` 显示 **两个** `127.0.0.1:8788` listener（PID 6044 和 5188），均由现有 `grokbuddy_github.py ... var\github-manual ... --port 8788` 进程占用，不能称为“原 webhook 唯一监听”。本机现状仍为 `GET /webhooks/github=405`、`GET /health=404`、`GET /mcp=404`。

按 Human 指定的“先确认 token，再停止原 listener”顺序，本次在切换前停止：**没有停止任何进程，没有启动 composite，没有发送公网 `/health` 或 `/mcp` 验证请求**。因此也没有发生需要恢复的切换；原 webhook 进程和现有 tunnel 保持在检查时的状态，但双监听风险仍在。后续须由 Human 在本任务可读取的环境范围内安全设置 `GROKBUDDY_MCP_TOKEN`（不要粘贴到聊天或日志），并在重试时重新确认 hostname、精确识别及停止两个原 listener，确保 composite 独占 8788；本轮不自行绕过缺失 token。

`PHASE4-REMOTE-MCP-LOCAL: PASS`（含真实本机 MCP 与原 webhook 集成测试）。

上述 `REMOTE BLOCKED` 是 09:19 当时的历史判定，不是最终公网 Gate。

### 2026-09-20 11:53 公网续跑结果（Asia/Shanghai）

新进程中只确认 `GROKBUDDY_MCP_TOKEN` 与 `GITHUB_WEBHOOK_SECRET` 均存在，未输出其值。切换前 `127.0.0.1:8788` 只有一个原 `grokbuddy_github.py ... var\github-manual ... --port 8788` listener（PID 26908）。现有 cloudflared PID 15968 的命令仍为 `tunnel --url http://127.0.0.1:8788`；启动前重新读取其 metrics，实际 hostname 已变为 **`mental-reader-publicity-nil.trycloudflare.com`**，没有使用前次 `bell-...` 或 9 月 18 日旧地址。

受控流程停止 PID 26908、确认 8788 释放后，在同一端口启动 `scripts/grokbuddy_composite.py --runtime-dir var\github-manual --webhook-secret-env GITHUB_WEBHOOK_SECRET --mcp-token-env GROKBUDDY_MCP_TOKEN --host 127.0.0.1 --port 8788 --public-host mental-reader-publicity-nil.trycloudflare.com`；复核唯一 composite listener PID 31284。未启动第二个 tunnel，未修改 Cloudflare 配置、Webhook application 或 MCP 实现。

| 验证项 | 本机 `127.0.0.1:8788` | 现有 Quick Tunnel 公网 hostname |
|---|---:|---:|
| `GET /health` | 200 | 200 |
| `GET /webhooks/github` | 405（原 app 可达） | 本轮未要求重复公网 Webhook |
| `/mcp` 无 token / 错 token | 401 / 401 | 401 / 401 |
| 正确 Bearer：官方 SDK initialize、`tools/list`、`list_pending_review_requests` | PASS | PASS |
| 协商 MCP protocol version | `2025-11-25` | `2025-11-25` |
| Remote `tools/list` | 精确 5 个既定只读工具 | 精确 5 个既定只读工具 |
| MCP transport | 4 次 POST，均为 `application/json` 响应 | 4 次 POST，均为 `application/json` 响应 |

两端只读查询均成功，当前 pending 列表为 0 条；这不是新增 Review 或 worker 执行证据。Bearer token 只在进程环境/HTTP 认证中使用，未进入命令行、输出或报告。公网测试证明本次 Quick Tunnel 上的 JSON-response Streamable HTTP 可用，不依赖 SSE GET stream；仍不等于 OAuth、Grok Connector 或生产部署验证。

测试流程的 `finally` 随即停止 composite 并按原参数恢复 webhook。独立收尾核对：8788 **唯一** listener 为原 `grokbuddy_github.py` PID 30632，`GET /webhooks/github=405`、`GET /health=404`、`GET /mcp=404`；无 composite 进程，原 cloudflared PID 15968 仍运行。没有改动代码或重跑已成立的 LOCAL Gate。

`PHASE4-REMOTE-MCP-LOCAL: PASS`（保持既有结论）。

`PHASE4-REMOTE-MCP-PUBLIC: REMOTE PASS`（仅本轮现有 Quick Tunnel、上述 hostname 与只读探测范围）。至此停止，不进入 Phase 5/6，不创建 Connector 或运行 Routine/poller。

## 文件清单与停止条件

- 修改：`src/grokbuddy/application/tasks.py`（只读 query）、`src/grokbuddy/interfaces/gateway.py`（固定 query allowlist）、`AGENTS.md`、`IMPLEMENTATION_PLAN.md`、`README.md`。
- 新增：`src/grokbuddy/interfaces/remote_mcp.py`、`src/grokbuddy/interfaces/composite.py`、`scripts/grokbuddy_composite.py`、`scripts/verify_phase4_live.py`、`tests/test_phase4_remote_mcp.py`、本报告。
- 未修改：原 Webhook application/入口、原 stdio MCP implementation、Domain/状态机、schema/backup、GitHub adapter、协议 v1 contracts。工作区没有可用 `.git` 元数据，`git status` 返回 not a git repository；文件清单与测试是本轮证据，不伪称 git diff。

至此停止。未启动 Phase 5/6，未运行 Routine/poller，未创建 Grok Connector、Named Tunnel/hostname/DNS/ingress/Windows service，未向 GitHub 发出 Comment/merge/approve 等写操作。下一阶段内容或公网重验需要 Human 新授权及实际 tunnel/账号能力证据。
