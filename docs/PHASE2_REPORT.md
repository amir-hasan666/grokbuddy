# Phase 2 Client Interfaces 实现与验证报告

日期：2026-09-17。Phase 1 已通过 Human Gate。Phase 2 保留 HTTP/CLI fallback，并新增 Hub stdio MCP Server；没有进入 GitHub/ACP/Grok 阶段。

## Transport 探测

结论：**WorkBuddy 5.5.6 支持 stdio、SSE、HTTP；本地 Hub 采用默认 stdio。**

证据：`WorkBuddy.exe` FileVersion=5.5.6；实际 `C:\Users\22241\.workbuddy\mcp.json` 使用 `mcpServers` 顶层；内置 CLI 的 `mcp add --help` 显示 transport 为 `stdio|sse|http` 且默认 stdio；腾讯官方 WorkBuddy Enterprise MCP 文档给出同一 JSON 字段。完整脱敏摘要见 [transport probe](phase2-workbuddy-transport-probe.json)。

早先 Codex 当前路由对 `workbuddy` server 的枚举仍是 `MCP_FAIL`，只说明 Codex 路由不可寻址，不否定 WorkBuddy 客户端能力，历史记录见 [initial probe](phase2-mcp-probe.json)。

## 实现结果

新增 `src/grokbuddy/interfaces/mcp.py` 与 `scripts/grokbuddy_mcp.py`，锁定官方 `mcp==2.2.0`。MCP、HTTP、CLI 三入口共用 `ClientGateway`，再调用已有 Application Service；Domain 不依赖 transport。

精确暴露 11 tools：`create_task`、`get_task`、`submit_plan`、`request_plan_review`、`get_plan_review`、`respond_to_review`、`submit_artifact`、`request_final_review`、`get_final_review`、`get_task_status`、`close_task`。

- request 只持久化并返回 `{review_request_id, status: PENDING}`；不运行 dispatcher、Mock 或 event handler。
- query 与 request 分开；完成后按相同 idempotency key 重放 request 仍返回原 PENDING 收据。
- stdio stdout 由官方 SDK 专用于 MCP wire；日志级别为 WARNING，不在启动前打印内容。
- 普通 tools 固定本地 `builder` principal；`close_task` 固定本地 `human` principal，保留原 RBAC/Audit/cancel 状态边。
- SDK/domain 输入失败映射为有界 `ToolError`；unexpected exception 继续由 SDK 隐藏。
- HTTP/CLI 文件与行为保留，没有修改状态机、幂等 receipt、backup、`provider_id`、Review/Finding schema。

## 验证结果

| 项目 | 结果 / 证据 |
|---|---|
| 全部本地测试 | **448 PASS，0 FAIL，0 SKIP**；[JUnit XML](phase2-tests.xml) |
| MCP legacy compatibility | 官方 Python MCP client 以 `2025-11-25` handshake 成功；精确列出 11 tools |
| MCP async boundary | `request_plan_review` 立即 PENDING；查询仍 PENDING/result=null，未内联推进 worker |
| MCP stdio process | 真正拉起独立 Python 子进程，握手并调用 `create_task` 成功 |
| MCP reconnect/idempotency | 关闭并重启 stdio process 后以相同 key 重放，返回同一 task id |
| MCP Human cancel | `close_task` 返回 CANCELLED，最后 Audit actor_id=`human` |
| HTTP/CLI fallback | 原有 WSGI、CLI、Mock Plan/Final/Finding 闭环全部回归通过 |
| Dependency | MCP SDK 2.2.0；`pip check` 无 broken requirements |

Windows asyncio 创建内部 socketpair 需要 loopback，因此测试禁网 fixture 仅允许 `127.0.0.1`/`::1` 的底层 event-loop primitive，继续拒绝 `socket.create_connection` 与所有外部地址。测试未调用真实 Grok/GitHub；Mock verdict 仍是合成结果。

## WorkBuddy 客户端证据与关闭补记

仓库内临时 `--mcp-config` 被 WorkBuddy CLI 接受并启动 Server 到 runtime 初始化阶段：`var/workbuddy-mcp/hub.db` 已创建，actors=4、review_profiles=6、tasks=0、audit_logs=0。随后模型 endpoint 在沙箱内返回网络拒绝，未发生 tool call。

按规则请求的两次环境外操作均被安全审批拒绝：

- 写入用户级 `C:\Users\22241\.workbuddy\mcp.json` 注册 stdio server；
- WorkBuddy CLI 联网执行一次真实 `create_task`。

后续用户明确确认 Phase 0–2 已关闭，并提供真实 `create_task`：`TASK-12d16e55-d3ee-4d84-8dc2-d6594c965d56`。2026-09-17 只读复核 `var/workbuddy-mcp/hub.db`：该 Task 唯一存在，状态 `NEW`，对应一次 `ARTIFACT_CREATED` 与一次 `TASK_CREATED` Audit。数据库证据确认 Hub 侧 exactly-once 业务效果；真实调用来源仍以用户报告为证，因为本仓库没有保存 WorkBuddy UI/网络 trace。Phase 3 未修改用户级 `mcp.json`。

## 本次 MCP 扩展文件

新增：

- `src/grokbuddy/interfaces/mcp.py`
- `scripts/grokbuddy_mcp.py`
- `docs/examples/workbuddy-mcp-smoke.json`
- `docs/phase2-workbuddy-transport-probe.json`

修改：

- `pyproject.toml`
- `tests/conftest.py`
- `tests/test_phase2_interfaces.py`
- `README.md`
- `IMPLEMENTATION_PLAN.md`
- `docs/WORKBUDDY_INTEGRATION.md`
- `docs/CAPABILITY_VERIFICATION.md`
- `docs/PHASE2_REPORT.md`
- `docs/phase2-tests.xml`

HTTP/CLI fallback 文件未删除或替换。

## 可复现命令

```powershell
Set-Location D:\Codex\grokbuddy
.\.venv-phase0\Scripts\python.exe -m pip install mcp==2.2.0
.\.venv-phase0\Scripts\python.exe -m pytest -q --tb=short --junitxml=docs\phase2-tests.xml
.\.venv-phase0\Scripts\python.exe scripts\grokbuddy_mcp.py --help
.\.venv-phase0\Scripts\python.exe scripts\validate_phase0.py --allow-core
.\.venv-phase0\Scripts\python.exe -m pip check
```

## 未决项与阶段边界

- WorkBuddy 当前 timeout/approval UX、桌面重载行为仍 `ENVIRONMENT_VALIDATION_REQUIRED`；不影响已确认的单次 create_task 结果。
- GitHub Builder/Reviewer 独立 actor、Grok trigger、评论/Artifact 回写仍 UNVERIFIED/BLOCKED。
- HTTP fallback 无认证，只能绑定 loopback；本地 principal 不是生产认证。

Phase 2 已由后续 Human 指令关闭。进入 Phase 3 的授权仅覆盖本地 GitHub Webhook/Comment mock，不放行 ACP、真实 Grok 或 Production GitHub。
