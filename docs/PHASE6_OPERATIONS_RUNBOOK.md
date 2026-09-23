PHASE6-SUPERVISOR-PRODUCTION-WIRING: LOCAL PASS / WAITING HUMAN RESTART

# Phase 6 Windows Operations Runbook

正式 PublicBase 固定为 `https://grokbuddy.amirhasan.top`，本地 origin 固定为 `http://127.0.0.1:8788`。根路径 `GET /` 的预期是 HTTP 404 与 `{"error":"not_found"}`；不得为健康检查增加假首页。本文只覆盖 Windows 运行、恢复与验收，不授权 GitHub/Grok 外站修改或 6.20 E2E。

## 1. 配置与 Secret 边界

- 非敏感运行配置：`config/grokbuddy.service.json`。
- 正式 Secret Source 是当前登录用户的 Windows Credential Manager Generic Credential（`CRED_TYPE_GENERIC`）。`Get-GrokBuddyCredential.ps1` 只通过 `CredReadW` 读取，并始终用 `CredFree` 释放原生缓冲区。
- 五个基础 Target 为 `GrokBuddy/GITHUB_WEBHOOK_SECRET`、`GrokBuddy/GROKBUDDY_MCP_TOKEN`、`GrokBuddy/GROKBUDDY_GROK_REVIEWER_TOKEN`、`GrokBuddy/GROKBUDDY_TRIGGER_SOURCE_KEY`、`GrokBuddy/GITHUB_COMMENT_TOKEN`。最后一项只用于正式 Supervisor 的普通 GitHub Comment 请求载体与 Final projection；Trigger Source Key 还必须不少于 32 UTF-8 bytes。任一基础项 missing、empty、过短或 unreadable 都 fail closed，不启动 Hub。
- Reviewer webhook wake 默认关闭：`reviewerWakeWebhookUrlEnv` 与 `reviewerWakeWebhookKeyEnv` 在 service config 中均为空。启用时必须同时配置两个非敏感环境变量名，并在当前登录用户的 Credential Manager 中增加 `GrokBuddy/REVIEWER_WAKE_WEBHOOK_URL` 与 `GrokBuddy/REVIEWER_WAKE_WEBHOOK_KEY`；任一可选项缺失或不合法都 fail closed。URL 与 key 的值不得进入 service JSON、命令行、日志、报告或 Git。
- `Start-GrokBuddyHub.ps1` 只把值注入 launcher/Hub 的 Process 环境。禁止 `setx`，禁止 User/Machine 环境持久化，禁止把值写入 JSON、任务参数、Git、日志或报告。
- `var/service/hub-secrets.clixml` 被 Git 忽略并保留，但已退出正式启动链路。安装、启动和卸载脚本均不读取、覆盖或删除它。

只读验证（不输出 Secret 或 hash）：

```powershell
.\scripts\windows\Test-GrokBuddyCredentialStore.ps1
```

wake 关闭时成功输出五个基础 Target 的 `PRESENT`；wake 启用时再显示两个可选 Target 的 `PRESENT`。脚本不显示值或 hash。

## 2. 清理 Quick Tunnel

管理员 PowerShell：

```powershell
Set-Location D:\Codex\grokbuddy
.\scripts\windows\Stop-GrokBuddyQuickRoute.ps1 -Verbose
Get-Process cloudflared -ErrorAction SilentlyContinue
sc.exe queryex cloudflared
sc.exe qc cloudflared
```

清理脚本只匹配 `cloudflared tunnel --url`；正式服务必须仍显示 `tunnel run --token-file`。若正式服务异常，管理员运行：

```powershell
.\scripts\windows\Install-GrokBuddyCloudflaredService.ps1
```

有意卸载 Named Tunnel 服务时才运行 `cloudflared.exe service uninstall`；这会中断固定公网入口，不属于普通恢复步骤。

## 3. Hub 任务安装、启动与卸载

在拥有上述四个 Generic Credential 的当前 Windows 用户上下文中安装：

```powershell
.\scripts\windows\Install-GrokBuddyHubTask.ps1
```

任务触发器是当前用户登录，失败自动按 1 分钟间隔重启最多 10 次。它不等于 LocalSystem 开机前服务；验收口径是“机器重启并登录该用户后自动监听”。

`Start-GrokBuddyHub.ps1` 是长期 launcher：它以前台子进程方式持有 Hub。因此健康运行时任务应为 `Running`，`LastTaskResult=267009 (0x41301 / SCHED_S_TASK_RUNNING)` 是“任务仍在运行”，不应机械要求为 `0`。只有 launcher 已退出时，才把最终退出码作为诊断依据。

2026-09-22 回归：旧 launcher 的脚本级 `trap` 与 `$ErrorActionPreference='Stop'` 覆盖了整个常驻周期，Python logging 写入 native stderr 的 `GROKBUDDY_SUPERVISOR_STARTED` INFO 行被 PowerShell 视为 terminating error，导致 uvicorn bind 前退出、计划任务 `LastTaskResult=1`、8788 无监听且 `hub.stderr.log` 为空。修复后启动前配置/Credential 失败由独立 bootstrap `try/catch` fail closed；常驻 Python 改为 `Start-Process -RedirectStandardOutput/-RedirectStandardError -Wait -PassThru`，stderr 直接进入 `hub.stderr.log`，launcher 只在子进程真正退出后读取并返回 `ExitCode`。INFO stderr 不再进入 PowerShell error pipeline。

`config/grokbuddy.service.json` 的 `supervisorEnabled` 默认为且正式值为 `true`，`supervisorIntervalSeconds` 必须在 `(0, 5]`。launcher 将其传给同一个 `grokbuddy_composite.py` 进程；该进程启动 Supervisor 线程，退出时设置 stop event 并 join。仅隔离测试/调试才可显式把配置改为 `false`，对应 CLI flag 是 `--disable-supervisor`；这不是生产降级路径。

正式 stdio `grokbuddy-hub` 只要 `--runtime-dir` 指向本配置的 `var/github-manual`，就从同一 service config 取得默认 Reviewer `grok-reviewer-b`。隔离 runtime 仍默认 `mock-reviewer`。显式传 `reviewer_id` 的既有协议保持不变；此接线没有修改 ingress allowlist、`Task.owner_id` 或 Worker assignment 规则。

WorkBuddy 专用 trigger ingress 不把 Key 写进 `mcp.json`。其 stdio 配置调用 `Start-GrokBuddyIngressMcp.ps1`；该 wrapper 从相同的 `GrokBuddy/GROKBUDDY_TRIGGER_SOURCE_KEY` Target 读取并只注入 ingress 子进程。仓内无 Secret 的配置样例见 [workbuddy-ingress-mcp.example.json](examples/workbuddy-ingress-mcp.example.json)。

停止并卸载任务：

```powershell
.\scripts\windows\Uninstall-GrokBuddyHubTask.ps1
```

卸载脚本只注销任务并停止本仓库 Hub 进程；不会删除 Credential Manager 条目，也不会删除旧 CLIXML 文件。

## 4. 有界健康检查

```powershell
.\scripts\windows\Test-GrokBuddyRuntime.ps1
```

脚本只使用 `curl.exe -4 --connect-timeout 2 --max-time 5`，不会以前台方式启动常驻进程。成功口径：

| Endpoint | HTTP | Body / meaning |
| --- | ---: | --- |
| `/health` | 200 | `{"status":"ok"}`；只表示 HTTP 进程存活 |
| `/ready` | 200 | `status=ready`、`database=ok` 且 `supervisor=ok`；表示 SQLite 可读、Supervisor 线程存活且已完成至少一轮无 worker exception 的扫描 |
| `/` | 404 | `{"error":"not_found"}`；应用层无根路由 |

服务与任务状态：

```powershell
Get-Service cloudflared | Format-List Name,Status,StartType
Get-ScheduledTask -TaskName 'GrokBuddy Hub'
Get-ScheduledTaskInfo -TaskName 'GrokBuddy Hub'
Get-NetTCPConnection -State Listen -LocalPort 8788
```

## 5. 失败恢复

1. 先运行 `Stop-GrokBuddyQuickRoute.ps1`，确保不存在 `tunnel --url`。
2. `cloudflared` 不为 Running/Automatic 时，管理员运行安装脚本恢复并复核 `sc.exe qc/qfailure cloudflared`。
3. 8788 不监听时，先运行 `Test-GrokBuddyCredentialStore.ps1`，再读 `var/service/logs/hub.credential.log`、`hub.bootstrap.log`、`hub.stderr.log` 和计划任务状态。不要循环重启掩盖首个错误。
4. 若凭据测试出现 `credential target missing: GrokBuddy/...`，在 Windows Credential Manager 的当前用户 Generic Credentials 中修复对应 Target；禁止用 User/Machine 环境变量或任务参数绕过 fail-closed。
5. 8788 已监听后，依次验证本地 health/ready/root；再用 `curl.exe -4` 验证固定 PublicBase。本机若解析到 `198.18.0.0/15`，记录为开发机 Fake-IP 限制，沿用独立网络人工证据，不改 PublicBase。

Supervisor 的无 Secret 日志关键字位于 `var/service/logs/hub.stderr.log`：

- `GROKBUDDY_SUPERVISOR_STARTED`：线程已启动，并列出 worker 名称；wake 关闭时正式进程应包含 `binding_route,recovery,dispatch,intake,event_apply,projection`；wake 启用后还应包含 `reviewer_wake`。
- `GROKBUDDY_SUPERVISOR_WORKER_ERROR`：某一轮 worker 抛出异常；该轮 `/ready` 应返回 503 和 `supervisor=unavailable`，但 `/health` 仍可为 200。
- `GROKBUDDY_SUPERVISOR_FAILED`：线程异常退出或 stop 超时；不得把 HTTP liveness 当作 ready。
- `GROKBUDDY_SUPERVISOR_STOPPED`：随 Hub 退出完成停止；正常启动后不应在没有重启/退出的情况下出现新的 STOPPED。

安全查看最近状态（不输出 Secret）：

```powershell
Select-String -LiteralPath .\var\service\logs\hub.stderr.log `
  -Pattern 'GROKBUDDY_SUPERVISOR_(STARTED|WORKER_ERROR|FAILED|STOPPED)' |
  Select-Object -Last 20
```

GitHub binding/route 仍以 Hub 表为准。Supervisor 会扫描 binding/route 职责，但没有可信 PR metadata 时不会虚构 binding；未绑定 Final projection 保持 `UNKNOWN`，不允许据此声称 GitHub projection PASS。

## 6. 重启验收模板

重启只能由 Human 明确执行。重启后登录配置任务的同一用户，不要手工启动 Hub，等待 AtLogOn 任务自行拉起，然后记录：

```powershell
Get-Date -Format o
.\scripts\windows\Test-GrokBuddyCredentialStore.ps1
.\scripts\windows\Restart-GrokBuddyHubTask.ps1
Get-Service cloudflared | Format-List Name,Status,StartType
Get-ScheduledTask -TaskName 'GrokBuddy Hub' | Format-List TaskName,State
Get-ScheduledTaskInfo -TaskName 'GrokBuddy Hub'
Get-NetTCPConnection -State Listen -LocalPort 8788
.\scripts\windows\Test-GrokBuddyRuntime.ps1
```

`Restart-GrokBuddyHubTask.ps1` 默认最多等待 30 秒，并且只有 `/ready` 同时返回 `status=ready` 与 `checks.supervisor=ok` 才成功；这是为了容纳 Supervisor 至少完成首轮扫描。必要时可显式传 `-ReadyTimeoutSeconds 60`（允许范围 1–300 秒），不得通过跳过 supervisor 检查来缩短等待。

`Test-GrokBuddyRuntime.ps1` 内每个 curl 都固定 `--connect-timeout 2 --max-time 5`，并同时校验 local/public `/ready` 中的 `supervisor=ok`。若需人工展开 HTTP 头，也必须保留 `curl.exe -4` 和不超过 15 秒的单请求硬超时。

未实际重启时，报告必须写 `NOT RUN`，不能从服务 StartType、任务手工启动或进程恢复推断通过。

## 7. 本次接线后的 Human 复测

1. 先运行 `Test-GrokBuddyCredentialStore.ps1`，确认包含 `GrokBuddy/GITHUB_COMMENT_TOKEN` 在内的五项均为 `PRESENT`；随后运行 `Restart-GrokBuddyHubTask.ps1` 和 `Test-GrokBuddyRuntime.ps1`，确认本地/公网仍为 `200 / 200 / 404`，并确认 `/ready` 含 `supervisor=ok`。
2. 完全退出并重开 WorkBuddy，使 `grokbuddy-ingress`、`grokbuddy-hub`、`grokbuddy-worker` 三个 stdio MCP 全部重建并加载 builder-drive 与正式 Reviewer 默认值。
3. 使用新会话，或先 Abort 旧活动 Task，再发送 `启用grokbuddy流程…`；随后发送短句 `按流水线走完。`
4. 核对 Plan/Final RR 在没有任何本地 `run_until_idle()`、`*_once` 或临时 glue 的情况下被 Supervisor 扫描；仅当 binding/route 与真实 Grok Reviewer 可达时才期待 intake/APPLY。无 binding 时记录待办/`UNKNOWN`，不得伪造投影或 6.20 成功。

这组 Human 操作只用于重启/复测。本仓接线结论仍是 `LOCAL PASS / WAITING HUMAN RESTART`，不是 `6.20 PASS`。

## 8. Reviewer webhook wake 配置与隔离复测

### 8.1 启用与 Secret 注入

wake 只是“队列已有新 RR”的尽力通知，不携带完整 Review，不提交 verdict，也不替代认证的 `GET /reviewer/requests` 与 `POST /reviewer/events`。POST body 只有固定事件名与 `review_request_id`；sender key 只放在 HTTPS `Authorization: Bearer ...` header，稳定去重值放在 `Idempotency-Key` header。

Human 先在当前计划任务用户的 Windows Credential Manager 中创建两个 Generic Credential：

- `GrokBuddy/REVIEWER_WAKE_WEBHOOK_URL`：已经人工验证的 Grok Bot Reviewer webhook URL；
- `GrokBuddy/REVIEWER_WAKE_WEBHOOK_KEY`：与现有 webhook/MCP/Reviewer/GitHub 凭据相互独立的 sender key。

然后仅把 `config/grokbuddy.service.json` 中两个非敏感字段从空字符串改为下列环境变量名；不得把实际值写入 JSON：

```json
"reviewerWakeWebhookKeyEnv": "GROKBUDDY_REVIEWER_WAKE_WEBHOOK_KEY",
"reviewerWakeWebhookUrlEnv": "GROKBUDDY_REVIEWER_WAKE_WEBHOOK_URL"
```

`reviewerWakeMaxAttempts` 默认是 `3`，允许范围 `1`–`5`；它是连续 transient 失败的快速重试窗口，不是 RR 的总 wake 次数。首次失败后按 5、10 秒等退避，达到该窗口后按最长 60 秒的冷却间隔继续自动检查；每个 RR 总尝试数硬上限为 64，且任何下次尝试时间都不超过原 RR/task deadline。HTTP 2xx 只表示 wake transport 接受；若 Reviewer HTTP intake 仍未 ACK，Supervisor 也会在退避到期后重新唤醒同一 RR。原 RR、review round、outbox `delivery_key`、冻结 envelope 与 wake 去重键均保持不变。Reviewer intake ACK、已 APPLY 的 ReviewStarted/ReviewCompleted、过期、stale/superseded、明确拒绝或总尝试数耗尽会终止重试；待校验的 `READY` Reviewer event 仅临时抑制 wake，拒绝后可继续恢复。wake 收据 JSON 持久化 `next_retry_at`、`consecutive_failures`、`recovery_reason`、`terminal_reason`、`last_result`、`last_attempt_at`、`last_http_status_code`，每次 claim 与结果另有非 Secret Audit；HTTP 状态码本身不含 Secret，响应正文不保存。wake 失败不会回滚已 `SENT` 的 outbox、失败 Task 或代替 Reviewer 结果。

运行只读检查；启用后应比基础配置多看到两个可选 Target 的 `PRESENT`：

```powershell
Set-Location D:\Codex\grokbuddy
.\scripts\windows\Test-GrokBuddyCredentialStore.ps1
```

只有 Human 可以执行 `Restart-GrokBuddyHubTask.ps1`。launcher 通过 `CredReadW` 读取两项值，仅注入 Hub 子进程环境；缺省空配置不读取可选 Target，也不启用 wake。不要使用 `setx`，不要在命令行临时传值。

### 8.2 与 poller 并存及 Human 验证

生产运行时 wake 与既有 `grokbuddy-review-poller` 可以并存：wake 只缩短 Reviewer 被叫醒的时间，poller 仍是兼容和恢复路径；两者都只指向同一个 Hub intake，Hub 的 RR、Finding、verdict 和 Task 状态仍是唯一事实源。不要删除或破坏 poller。

为了单独证明 wake，Human 在验证窗口内应先记录 poller 当前状态，再通过 poller 自身的受控调度界面暂停 `grokbuddy-review-poller`，不得删除任务或修改其凭据。验证顺序：

1. 配置上述 URL/key Target 与两个环境变量名，运行只读 Credential 检查；
2. 由 Human 重启正式 Hub，并确认 `/ready` 为 `database=ok`、`supervisor=ok`，启动 worker 列表包含 `reviewer_wake`；
3. 暂停 `grokbuddy-review-poller`；
4. 创建一个新任务并正常推进到 `REVIEW_PENDING`；从此不手动 POST webhook，也不手动运行任何 poller、`*_once`、`run_until_idle` 或 resume glue；
5. 观察 Reviewer 是否自行执行认证 GET 并使 intake 从 `READY` 变为 `ACKED`，随后通过认证 event 回传 started/completed 与 verdict；
6. 记录 RR/outbox/intake/wake receipt/Audit 的安全状态，不记录 URL、key、Authorization header 或完整 Review；验证结束后恢复 poller 原状态。

2026-09-22 Human 已在 poller 暂停窗口完成零胶水实弹复测：两轮 wake 与 Reviewer HTTP intake 均 `ACKED`，Plan/Final 均由真实 Reviewer PASS，因此 Reviewer webhook wake 已收口为 `HUMAN RETEST PASS`。该结论不等于改写 6.20 或宣告 Phase 6 退出；后续复测仍必须同时得到 Reviewer intake ACK 与认证 verdict，不能只凭 webhook POST 的 transport ACK 宣称 Reviewer 已运行。
