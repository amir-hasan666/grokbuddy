# Phase 6 Windows Operations Runbook

正式 PublicBase 固定为 `https://grokbuddy.amirhasan.top`，本地 origin 固定为 `http://127.0.0.1:8788`。根路径 `GET /` 的预期是 HTTP 404 与 `{"error":"not_found"}`；不得为健康检查增加假首页。本文只覆盖 Windows 运行、恢复与验收，不授权 GitHub/Grok 外站修改或 6.20 E2E。

## 1. 配置与 Secret 边界

- 非敏感运行配置：`config/grokbuddy.service.json`。
- Secret 只在进程环境或 Human 批准的受保护 Windows 凭据设施中提供；不得进入 JSON、计划任务参数、Git、日志或报告。
- `var/service/hub-secrets.clixml` 被 Git 忽略。它使用创建上下文的 DPAPI；若 Task Scheduler 返回加密上下文错误，停止并由 Human 选择受保护迁移方案。不得自动覆盖或降级为命令行/明文文件。
- `Start-GrokBuddyHub.ps1` 可读取预先配置的 User 环境，再回退到 DPAPI 文件；仓库脚本不会自行持久化明文 Secret。

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

在已安全注入三项进程环境变量的同一 Windows 用户上下文中安装：

```powershell
.\scripts\windows\Install-GrokBuddyHubTask.ps1
```

若 Human 已确认现有 DPAPI 文件可由任务主体解密，可用 `-UseExistingSecrets` 避免覆盖。当前现场的 DPAPI 文件与 Task Scheduler 上下文不兼容，因此在 Human 选择 Windows Credential Manager 或重新封装方案前，不得用此参数宣称自启已通过。

任务触发器是当前用户登录，失败自动按 1 分钟间隔重启最多 10 次。它不等于 LocalSystem 开机前服务；验收口径是“机器重启并登录该用户后自动监听”。

停止并卸载任务：

```powershell
.\scripts\windows\Uninstall-GrokBuddyHubTask.ps1
```

默认保留受保护 Secret 文件；只有明确要撤销本机凭据时才追加 `-RemoveCredentialFile`。

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
3. 8788 不监听时，先读 `var/service/logs/hub.bootstrap.log`、`hub.stderr.log` 和计划任务 `LastTaskResult`。不要循环重启掩盖首个错误。
4. 若 bootstrap 报 DPAPI 状态错误，保留原文件，停止自动重试，等待 Human 批准安全凭据迁移。
5. 8788 已监听后，依次验证本地 health/ready/root；再用 `curl.exe -4` 验证固定 PublicBase。本机若解析到 `198.18.0.0/15`，记录为开发机 Fake-IP 限制，沿用独立网络人工证据，不改 PublicBase。

## 6. 重启验收模板

重启只能由 Human 明确执行。重启并登录后记录：

```powershell
Get-Date -Format o
Get-Service cloudflared | Format-List Name,Status,StartType
Get-ScheduledTaskInfo -TaskName 'GrokBuddy Hub'
Get-NetTCPConnection -State Listen -LocalPort 8788
curl.exe -4 --connect-timeout 2 --max-time 5 -i http://127.0.0.1:8788/health
curl.exe -4 --connect-timeout 2 --max-time 5 -i http://127.0.0.1:8788/ready
curl.exe -4 --connect-timeout 2 --max-time 5 -i http://127.0.0.1:8788/
curl.exe -4 --connect-timeout 3 --max-time 10 -i https://grokbuddy.amirhasan.top/health
curl.exe -4 --connect-timeout 3 --max-time 10 -i https://grokbuddy.amirhasan.top/ready
curl.exe -4 --connect-timeout 3 --max-time 10 -i https://grokbuddy.amirhasan.top/
```

未实际重启时，报告必须写 `NOT RUN`，不能从服务 StartType 或手工重启进程推断通过。
