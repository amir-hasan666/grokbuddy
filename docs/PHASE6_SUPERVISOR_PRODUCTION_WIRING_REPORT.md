PHASE6-SUPERVISOR-PRODUCTION-WIRING: LOCAL PASS / WAITING HUMAN RESTART

# Phase 6 — Supervisor Production Hub Wiring Report

日期：2026-09-22（Asia/Shanghai）

## 1. 判定与边界

本步把 Pack D 已有的 `Supervisor.run_forever()` 接入 Windows 正式 Hub 启动链路，并以隔离 runtime、mock HTTP host 和文件型 GitHub Comment transport 验证进程生命周期、真实 Reviewer B 路由选择、intake receipt、event APPLY worker、projection worker、timeout/recovery 与 readiness。结论只覆盖仓内代码与本地测试：**LOCAL PASS / WAITING HUMAN RESTART**。

本步没有重启正在运行的 Hub/WorkBuddy，没有运行真实 WorkBuddy 对话、真实 Grok Reviewer、GitHub Comment/Projection 或 Named Tunnel E2E，没有写业务 Hub DB，没有运行 `run_until_idle()`/`*_once` 作为生产证据，也没有修改 `Task.owner_id`、ingress allowlist 或 Worker legacy owner-transfer。

因此本报告明确：**不是 `6.20 PASS`，不得写成或解释为 `6.20 PASS`。**

## 2. 接线前只读调用图

| 范围 | 只读盘点结果 |
| --- | --- |
| `src/` | `LocalRuntime.supervisor()` 只负责构造；`Supervisor.run_forever()` 已实现但无生产调用点；`LocalRuntime.tick()` 是旧 debug/兼容入口。 |
| `scripts/` | `grokbuddy_composite.py` 只构造 `LocalRuntime`、HTTP/MCP/webhook/Reviewer ASGI app 并阻塞运行 uvicorn；没有 Supervisor。CLI 中的 `*_once` 仍是显式调试命令。 |
| `tests/` | Pack D 与 builder-drive 使用 `run_until_idle()`/`tick()` 驱动隔离 fixture；这些调用不能证明正式 Hub 常驻调度。 |
| Windows 正式入口 | `scripts/windows/Start-GrokBuddyHub.ps1 → scripts/grokbuddy_composite.py → uvicorn.run()`；端口 8788、Runtime SoT=`var/github-manual`、PublicBase=`https://grokbuddy.amirhasan.top`。 |
| ASGI 组合 | `src/grokbuddy/interfaces/composite.py` 提供 `/health`、`/ready`、`/mcp`、`/reviewer/*`、`/webhooks/github`；原 `/ready` 只检查 SQLite。 |

接线前事实与 Human 现场一致：Pack D 的 Supervisor 合同/实现可以存在，但正式 Windows Hub 进程没有调用 `run_forever()`；纯 MCP 请求可能停在 `*_REVIEW_PENDING`，测试里的 `run_until_idle()` 不属于生产路径。

## 3. 正式启动与生命周期接线

正式链路现在为：

`Start-GrokBuddyHub.ps1 → grokbuddy_composite.py → SupervisorService thread → Supervisor.run_forever()`

同一 Python 进程随后运行 uvicorn。`SupervisorService` 使用进程内 stop event：

1. uvicorn 前启动名为 `grokbuddy-supervisor` 的线程；首轮立即扫描，之后按配置周期扫描。
2. 每轮调用 Pack D 的 bounded `Supervisor.tick()`，各 worker 继续保有独立失败域。
3. uvicorn 返回、启动失败或进程退出路径进入 `finally`，设置 stop event 并 join；没有额外后台脚本或第二事实源。
4. 没有在生产代码中调用 `run_until_idle()`；该方法继续仅用于确定性测试。

正式 Supervisor 的 worker 名称为：

- `binding_route`
- `recovery`
- `dispatch`
- `intake`
- `event_apply`
- `projection`

`binding_route` 被持续调度，但当前没有可信 PR metadata policy 时返回 no-op；它不会猜测 repository/PR，也不会强行创建 binding。已持久化的合法 binding/route 仍由 dispatcher/intake 使用。

## 4. Reviewer、intake 与 mock 隔离

正式 composite 读取 `config/grokbuddy.service.json::reviewerActor`，当前为 `grok-reviewer-b`。正式 dispatcher 使用 `GitHubHttpCommentTransport`、固定 PublicBase 和现有 `GrokBotReviewerAdapter`；只有 expected reviewer 为 B 且存在唯一、相互匹配的 binding/route 时才 claim outbox。缺 binding/route 的 RR 保留待处理，不会被 mock worker 领取，也不会因缺 metadata 被错误投递。

正式 stdio `grokbuddy-hub` 在 `--runtime-dir` 指向 service config 的 `var/github-manual` 时，也从同一配置选择 `grok-reviewer-b` 作为省略 `reviewer_id` 时的默认 Reviewer；隔离 runtime 仍默认 `mock-reviewer`。显式 `reviewer_id` 协议保持兼容。

真实 Reviewer intake 使用既有认证 HTTP 面，而不是本地 mock consumer：

1. Supervisor 发现已 `SENT`、仍 active 且合法路由到 B 的 RR，写入 durable `READY` intake receipt。
2. B 使用专用 Bearer token 成功读取 `/reviewer/requests/<RR>` 后，receipt 才幂等转为 `ACKED`。
3. Comment `SENT` 本身不等于 Reviewer 接单；`ACKED` 也不等于 verdict。
4. 只有认证 `POST /reviewer/events` 持久化 inbox，随后 Supervisor 的 `event_apply` 通过既有校验/APPLY 路径，才可推进 RR/Task。

本地测试直接断言 production dispatcher 的 reviewer 是 `grok-reviewer-b`、没有 `mock_jobs`，并验证 GET 前 `READY`、GET 后 `ACKED`、RR 仍为 `PENDING`。

## 5. 配置与 Secret 边界

`config/grokbuddy.service.json` 新增/冻结：

| 键 | 正式值 / 语义 |
| --- | --- |
| `supervisorEnabled` | `true`；缺省也按开启处理 |
| `supervisorIntervalSeconds` | `5`；合法范围 `(0, 5]` |
| `githubCommentTokenEnv` | `GITHUB_COMMENT_TOKEN` |
| `reviewerActor` | `grok-reviewer-b` |
| `runtimeDir` | `var/github-manual` |
| `publicBase` | `https://grokbuddy.amirhasan.top` |

只有隔离测试/调试才允许显式 `supervisorEnabled=false`，launcher 将其翻译为 `--disable-supervisor`。正式默认不能靠省略参数关闭 Supervisor。

真实 request carrier 与 Final GitHub projection 需要 `GITHUB_COMMENT_TOKEN`。Windows launcher 现在只从 Credential Manager Target `GrokBuddy/GITHUB_COMMENT_TOKEN` 注入该 Process 环境变量；它与 webhook secret、MCP token、Reviewer callback token、trigger source key 分离。仓内只保存 Target/环境变量名称，没有读取、打印、记录或提交 Secret 值/hash。

Human 重启前必须运行 `Test-GrokBuddyCredentialStore.ps1`，确认五个 Target 均为 `PRESENT`。本步没有替 Human 创建或读取该 Secret；若 Target 缺失，正式 launcher 按设计 fail closed。

## 6. readiness、日志与失败语义

`/health` 保持进程 liveness：HTTP 200 `{"status":"ok"}`。

生产 `/ready` 现在同时要求：

- SQLite `SELECT 1` 成功；
- Supervisor 线程仍存活；
- 已至少完成一轮扫描；
- 最近一轮没有未隔离的 worker exception；
- 没有线程级 fatal error。

任一 Supervisor 条件失败时 `/ready` 返回 503、`supervisor=unavailable`；`/health` 可继续为 200，以区分进程活着与调度可用。正常 production body 包含 `database=ok` 与 `supervisor=ok`。既有不挂 Supervisor 的隔离 composite 测试仍保持原 readiness body，避免把测试 composition 误当生产。

`var/service/logs/hub.stderr.log` 的无 Secret 关键字：

- `GROKBUDDY_SUPERVISOR_STARTED`
- `GROKBUDDY_SUPERVISOR_WORKER_ERROR`
- `GROKBUDDY_SUPERVISOR_FAILED`
- `GROKBUDDY_SUPERVISOR_STOPPED`

线程 fatal exit 与 stop timeout 都会留下 `FAILED`，不会由 HTTP liveness 掩盖。具体检查命令见 [Phase 6 Operations Runbook](PHASE6_OPERATIONS_RUNBOOK.md)。

2026-09-22 Human 首次 Restart 暴露 launcher 回归：五项 Credential 均 `PRESENT`，但脚本级 `trap` 与 `$ErrorActionPreference='Stop'` 把 Supervisor 的 `GROKBUDDY_SUPERVISOR_STARTED` INFO stderr 当成 terminating error，导致 uvicorn bind 前退出；现场表现为 Restart 15 秒超时、计划任务 `LastTaskResult=1`、8788 无监听、`hub.bootstrap.log` 记录该 INFO 行而 `hub.stderr.log` 为 0 字节。仓内热修移除了覆盖常驻生命周期的 trap，把启动前校验放进独立 bootstrap `try/catch`，并以 `Start-Process` 直接重定向 stdout/stderr、前台 `Wait`、读取子进程 `ExitCode`。因此 Supervisor STARTED 等行现在由 OS 文件重定向进入 `hub.stderr.log`，不再经过 PowerShell error pipeline；实际任务重启与日志落盘仍等待 Human 验收。

Restart readiness 等待也由固定 15 秒改为默认 30 秒、可通过 `-ReadyTimeoutSeconds` 配置为 1–300 秒，并要求 `/ready` 同时满足 `status=ready` 与 `checks.supervisor=ok`。`Test-GrokBuddyRuntime.ps1` 同步收紧为 local/public `/ready` 都必须含 `supervisor=ok`。

## 7. binding / projection 的诚实边界

Final Review APPLY 仍原子写 projection intent。Supervisor 会运行 ProjectionWorker 并自动尝试补全/对账；但没有唯一 binding 时 `enqueue_final_review()` 不能安全生成 Comment body，intent 继续保持 `UNKNOWN`。本步没有为现场 Task 伪造 GitHub binding，也没有从 PR 状态推断 Hub 业务状态。

因此：

- `UNKNOWN` 是无 binding 时的诚实状态，不是 projection PASS。
- GitHub transport 恢复/marker 对账的本地 fixture 仍只证明代码合同。
- 真实 GitHub Comment CREATE/UPDATE、真实 B intake/event 与最终 projection 均为 Human 重启后另行观察项。

## 8. 文件清单

| 文件 | 本步变更 |
| --- | --- |
| `src/grokbuddy/application/workers.py` | dispatcher 增 route/binding eligibility；新增真实 HTTP intake receipt worker；`run_forever` 提供每轮状态 callback。 |
| `src/grokbuddy/infrastructure/runtime.py` | 可配置默认 Reviewer；可注入 production dispatcher/intake；构造 B intake 与只领取合法冻结 route 的 B dispatcher。 |
| `src/grokbuddy/infrastructure/supervisor_service.py` | 新增进程生命周期线程 host、stop/join、无 Secret 日志与 readiness 状态。 |
| `src/grokbuddy/interfaces/composite.py` | production `/ready` 合并 DB 与 Supervisor readiness。 |
| `src/grokbuddy/interfaces/gateway.py` | 省略 `reviewer_id` 时使用 runtime 的配置默认值；测试默认仍是 mock。 |
| `src/grokbuddy/interfaces/grok_reviewer.py` | 认证读取成功后幂等 ACK intake receipt。 |
| `src/grokbuddy/interfaces/mcp.py`、`scripts/grokbuddy_mcp.py` | 正式 SoT runtime 自动使用 service config 的 Reviewer B；支持显式默认 Reviewer 参数。 |
| `scripts/grokbuddy_composite.py` | 正式构造 HTTP transport、B dispatcher/intake、六 worker Supervisor 与生命周期 host；显式 debug disable flag。 |
| `scripts/windows/Start-GrokBuddyHub.ps1` | 默认开启 Supervisor、校验 interval、从 Credential Manager 注入 Comment token、传递正式参数。 |
| `scripts/windows/Restart-GrokBuddyHubTask.ps1` | readiness 默认等待 30 秒且可配置，并要求首轮 Supervisor 扫描完成、`supervisor=ok`。 |
| `scripts/windows/Test-GrokBuddyRuntime.ps1` | local/public `/ready` 验收均要求 `supervisor=ok`。 |
| `scripts/windows/Test-GrokBuddyCredentialStore.ps1` | 只读检查新增 Comment token Target 是否 `PRESENT`。 |
| `scripts/verify_phase4_live.py` | 历史 Phase 4 隔离 verifier 显式关闭 production Supervisor，避免将旧验证器当生产路径。 |
| `config/grokbuddy.service.json` | 新增 Supervisor 与 Comment token 非敏感配置。 |
| `docs/examples/workbuddy-mcp-smoke.json` | 显式记录正式默认 Reviewer B。 |
| `tests/test_phase6_supervisor_production_wiring.py` | 新增 production config/default reviewer、六 worker、真实 intake ACK、startup/stop/readiness/fatal thread及 Windows launcher stderr/ExitCode 防回归检查。 |
| `docs/PHASE6_OPERATIONS_RUNBOOK.md`、本报告 | Human 重启/复测、日志、ready、Secret 与证据边界。 |

工作区在本步开始前已有 builder-drive/6.17 相关未提交修改；本步保留并在其上做最小叠加，没有 reset/checkout/clean。为避免把既有未提交工作混入一个不可审计提交，本步没有创建可选 commit，也没有 push。

## 9. 本地验证

| 命令 / 检查 | 结果 | 证据边界 |
| --- | --- | --- |
| `python -m compileall -q src/grokbuddy scripts/grokbuddy_composite.py scripts/grokbuddy_mcp.py ...` | PASS | 仅语法/bytecode 编译 |
| production wiring + Remote MCP + Grok Adapter + Pack D + builder-drive 受影响回归 | `34 passed in 25.25s` | 全部为本地隔离 fixture |
| `pytest -q tests/test_phase6_supervisor_production_wiring.py` | `7 passed in 7.35s` | 含 Windows launcher stderr/ExitCode 解析级防回归；启动函数用 mock uvicorn；无外网 |
| `pytest -q` | `798 passed in 294.46s` | 热修后的最终全量本地回归；无真实 WorkBuddy/Grok/GitHub E2E |
| `validate_phase0.py --allow-core` | `219/219 passed`；external environment gate 仍 `BLOCKED` | 合同检查不证明外部能力 |
| PowerShell parser | `10 scripts`，0 parse error | 不等于任务计划实际重启 |
| `Start-Process` INFO stderr redirection smoke | `ExitCode=0`、`StderrBytes=147`、`MarkerReceived=true` | 本机临时文件验证 direct stderr redirection；未启动正式 Hub |

本步没有运行 `Restart-GrokBuddyHubTask.ps1`、`Test-GrokBuddyRuntime.ps1`、Credential Store 现场检查、真实端口监听探针或真实 Reviewer callback。这些均保留给 Human。

热修后的仓内检查会覆盖 PowerShell parser、launcher 解析级合同（无脚本级 trap、无 native `& $python`、具备 stdout/stderr 直接重定向、Wait 与 ExitCode 判定）以及本机临时文件 redirection smoke。后两者可证明 INFO stderr 不会再进入 PowerShell terminating-error 路径并能写入目标文件，但仍不替代 Human 的计划任务 Restart、真实 `hub.stderr.log` 与 8788 验收。

## 10. Human 重启与复测步骤

1. 在 Human 会话运行 `Test-GrokBuddyCredentialStore.ps1`，确认包含 `GrokBuddy/GITHUB_COMMENT_TOKEN` 在内五项均为 `PRESENT`；随后运行 `Restart-GrokBuddyHubTask.ps1`（默认等待 30 秒；如现场确需可传 `-ReadyTimeoutSeconds 60`）和 `Test-GrokBuddyRuntime.ps1`，确认 local/public 为 `200 / 200 / 404`，且 `/ready` 含 `supervisor=ok`。再检查 `hub.stderr.log` 中最新一次 `GROKBUDDY_SUPERVISOR_STARTED`，不得紧跟意外 `FAILED/STOPPED`。
2. 完全退出并重开 WorkBuddy，刷新 `grokbuddy-ingress`、`grokbuddy-hub`、`grokbuddy-worker` 三个 MCP，使 builder-drive 与正式 Reviewer 默认值进入新进程。
3. 使用新会话，或先 Abort 旧活动 Task，再发送 `启用grokbuddy流程…`；随后发送短句 `按流水线走完。`
4. 确认 Plan/Final RR 在没有本地 `run_until_idle()`、`dispatch-once`、`event-once`、`project-github-once` 或临时 resume glue 的情况下被 Supervisor 扫描。只有 binding/route 已存在且真实 Grok 可达时才期待 request Comment、Reviewer GET intake、event ingress/APPLY；无 binding 时保留待办/`UNKNOWN` 并记录缺口。

Human 复测后仍须单独核对 Reviewer B 的真实 execution identity、Grok 当前账号自动接单能力、Hub event/APPLY、同一 Task、零 Manual Glue 与 GitHub projection。没有这些证据时不得把本报告升级为 6.20。

## 11. Gate 表与停止点

| Gate | 状态 | 证据 / 缺口 |
| --- | --- | --- |
| 正式启动路径调用 `run_forever` | LOCAL PASS | `SupervisorService` startup/stop 测试与 production composition |
| 六 worker 挂载 | LOCAL PASS | 新测试断言完整 worker set；B dispatcher 非 mock |
| clean shutdown | LOCAL PASS | mock uvicorn 返回后 thread `running=false`；STOPPED 日志 |
| production default Reviewer B | LOCAL PASS | service config + stdio runtime selection + request envelope 测试 |
| ingress/builder owner 守卫 | LOCAL PASS / regression | 既有 builder-drive 测试通过；未改 owner/allowlist |
| supervisor thread failure readiness | LOCAL PASS | fatal thread 测试为 not ready；production `/ready` 合并检查 |
| Windows launcher INFO stderr 回归 | LOCAL PASS / WAITING HUMAN RESTART | 解析级合同与本机 redirection smoke；真实计划任务与 `hub.stderr.log` 待 Human |
| 无 binding 的 projection | HONEST UNKNOWN | 未伪造 binding；未声称 GitHub projection PASS |
| Windows Hub 实际重启 | WAITING HUMAN | Codex 未代跑 |
| WorkBuddy 三 MCP 热加载 | WAITING HUMAN | 需完全退出并重开客户端 |
| 真实 Grok 自动 intake/APPLY | NOT RUN / ENVIRONMENT_VALIDATION_REQUIRED | 本地 intake fixture 不能证明当前账号能力 |
| 真实 GitHub request/projection | NOT RUN | Comment token/binding/route/外部 API 未执行 |
| 6.20 Real Final E2E | **NOT PASS / NOT RUN** | 本步禁止宣称 PASS |

到此达到 Stop Condition：仓内接线完成，本地回归与报告完成，状态保持 **LOCAL PASS / WAITING HUMAN RESTART**。不进入真实 WorkBuddy/Grok E2E，不 push，不写 `6.20 PASS`。
