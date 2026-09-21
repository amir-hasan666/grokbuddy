# Phase 6 Windows Operations Runbook

正式 PublicBase 固定为 `https://grokbuddy.amirhasan.top`，本地 origin 固定为 `http://127.0.0.1:8788`。根路径 `GET /` 的预期是 HTTP 404 与 `{"error":"not_found"}`；不得为健康检查增加假首页。本文只覆盖 Windows 运行、恢复与验收，不授权 GitHub/Grok 外站修改或 6.20 E2E。

## 1. 配置与 Secret 边界

- 非敏感运行配置：`config/grokbuddy.service.json`。
- 正式 Secret Source 是当前登录用户的 Windows Credential Manager Generic Credential（`CRED_TYPE_GENERIC`）。`Get-GrokBuddyCredential.ps1` 只通过 `CredReadW` 读取，并始终用 `CredFree` 释放原生缓冲区。
- 四个固定 Target 为 `GrokBuddy/GITHUB_WEBHOOK_SECRET`、`GrokBuddy/GROKBUDDY_MCP_TOKEN`、`GrokBuddy/GROKBUDDY_GROK_REVIEWER_TOKEN`、`GrokBuddy/GROKBUDDY_TRIGGER_SOURCE_KEY`。Trigger Source Key 还必须不少于 32 UTF-8 bytes；任一项 missing、empty、过短或 unreadable 都 fail closed，不启动 Hub。
- `Start-GrokBuddyHub.ps1` 只把值注入 launcher/Hub 的 Process 环境。禁止 `setx`，禁止 User/Machine 环境持久化，禁止把值写入 JSON、任务参数、Git、日志或报告。
- `var/service/hub-secrets.clixml` 被 Git 忽略并保留，但已退出正式启动链路。安装、启动和卸载脚本均不读取、覆盖或删除它。

只读验证（不输出 Secret 或 hash）：

```powershell
.\scripts\windows\Test-GrokBuddyCredentialStore.ps1
```

成功时只显示四个 Target 的 `PRESENT`。

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
| `/ready` | 200 | `status=ready` 且 `database=ok`；表示 SQLite 可读 |
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

## 6. 重启验收模板

重启只能由 Human 明确执行。重启后登录配置任务的同一用户，不要手工启动 Hub，等待 AtLogOn 任务自行拉起，然后记录：

```powershell
Get-Date -Format o
.\scripts\windows\Test-GrokBuddyCredentialStore.ps1
Get-Service cloudflared | Format-List Name,Status,StartType
Get-ScheduledTask -TaskName 'GrokBuddy Hub' | Format-List TaskName,State
Get-ScheduledTaskInfo -TaskName 'GrokBuddy Hub'
Get-NetTCPConnection -State Listen -LocalPort 8788
.\scripts\windows\Test-GrokBuddyRuntime.ps1
```

`Test-GrokBuddyRuntime.ps1` 内每个 curl 都固定 `--connect-timeout 2 --max-time 5`。若需人工展开 HTTP 头，也必须保留 `curl.exe -4` 和不超过 15 秒的硬超时。

未实际重启时，报告必须写 `NOT RUN`，不能从服务 StartType、任务手工启动或进程恢复推断通过。
