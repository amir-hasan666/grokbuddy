# Phase 6 Pack E — 6.9 Autostart / Cleanup / Observability Wrap

日期：2026-09-21（Asia/Shanghai）

- `PHASE6-STEP6.8-NAMED-TUNNEL-PUBLICBASE: PASS`（沿用 Human 已验证并冻结的 6.8 证据）
- `PHASE6-STEP6.9-AUTOSTART-OBSERVABILITY: PARTIAL`
- `PHASE6-PACK-E: NOT PASS`

事故恢复说明：上一轮 Codex Shell 等待状态卡死后，本轮从现有脏工作区继续；未 reset/checkout/clean，已落盘代码、Windows Service 与 `var/service/hub-secrets.clixml` 均保留。

## 1. 6.8 PublicBase 证据边界

沿用 Human 已验证事实：Named Tunnel 名为 `grokbuddy`，固定 PublicBase 为 `https://grokbuddy.amirhasan.top`，published route 指向 `http://localhost:8788`；人工 curl/手机路径已支持 6.8 PASS。根路径返回 HTTP 404 与 `{"error":"not_found"}` 是应用层预期，不是网络失败。

本轮开发机 `Resolve-DnsName` 把域名解析为 `198.18.0.249`；`curl.exe -4 --noproxy '*' --connect-timeout 3 --max-time 10` 对 `/health` 返回 curl exit 7 / HTTP 000。因此本轮不伪造新的公网 PASS，也不推翻已冻结的 6.8 人工证据，不改 PublicBase。

## 2. Quick Tunnel 清理

预检确认旧进程 PID 48936：

```text
D:\Codex\grokbuddy\var\phase35-tools\cloudflared.exe tunnel --url http://127.0.0.1:8788
```

按精确 PID 停止后 `StillExists=false`。随后系统仅剩 cloudflared PID 58840；`sc.exe queryex/qc cloudflared` 证明它是正式 Windows Service：`RUNNING`、`AUTO_START`，命令为 `tunnel run --token-file C:\ProgramData\cloudflared\token`。未停止 Named Tunnel Service，正式路径不再依赖 Quick Tunnel。

仓库新增 `scripts/windows/Stop-GrokBuddyQuickRoute.ps1`，只匹配 `tunnel --url`，并写不含 Secret 的清理计数证据。

## 3. 仓内 PublicBase 清理

正式运行项统一到 `https://grokbuddy.amirhasan.top`：

- `.env.example`
- `config/grokbuddy.service.json`
- `scripts/grokbuddy_composite.py`：新增 `PUBLIC_BASE` / `--public-base-url` 单一入口，并从 origin 派生 MCP host allowlist 与 Reviewer pointer base
- `docs/PHASE4_GROK_RUNBOOK.md`
- `README.md`

Phase 4/5 报告中的 `trycloudflare.com` 是不可改写的当次审计证据，已在对应报告顶部标记 `HISTORICAL`。测试 fixture 已改为固定正式 host/保留非生产拒绝 host，不再用 trycloudflare 作为当前示例。

## 4. cloudflared 与 Hub 自启现状

### cloudflared

- Windows Service：Running
- StartType：Automatic
- 身份：LocalSystem
- 凭据：`--token-file`，未把 token 放到 service command line
- failure actions：5 秒、15 秒、60 秒重启，reset period 86400 秒
- 脚本：`scripts/windows/Install-GrokBuddyCloudflaredService.ps1`

### Hub

新增配置与脚本：

- `config/grokbuddy.service.json`
- `scripts/windows/Start-GrokBuddyHub.ps1`
- `scripts/windows/Install-GrokBuddyHubTask.ps1`
- `scripts/windows/Restart-GrokBuddyHubTask.ps1`
- `scripts/windows/Uninstall-GrokBuddyHubTask.ps1`
- `scripts/windows/Test-GrokBuddyRuntime.ps1`

计划任务 `GrokBuddy Hub` 已注册为当前用户 AtLogOn，restart count 10；动作和参数不含 Secret。但当前 `LastTaskResult=1`：bootstrap 证据为“该项不适于在指定状态下使用”，即现有 DPAPI 文件不能由 Task Scheduler 上下文解密。该文件未损坏、未覆盖；把明文 Secret 自动持久化到 HKCU 环境的方案未执行。须由 Human 明确选择 Windows Credential Manager 或任务主体可读的受保护重新封装方案，之后才能完成自启 Gate。

当前 Hub 已由不含 Secret 参数的隐藏后台进程恢复，`127.0.0.1:8788` 由 PID 11660 监听；这证明当前进程可运行，不等于重启后任务自启通过。

## 5. 当前 health / readiness

本机有界探测：

| Endpoint | HTTP | Body | 结果 |
| --- | ---: | --- | --- |
| `http://127.0.0.1:8788/health` | 200 | `{"status":"ok"}` | RUN / PASS（liveness） |
| `http://127.0.0.1:8788/ready` | 200 | `{"checks":{"database":"ok"},"status":"ready"}` | RUN / PASS（SQLite readiness） |
| `http://127.0.0.1:8788/` | 404 | `{"error":"not_found"}` | RUN / EXPECTED |
| `https://grokbuddy.amirhasan.top/health` | 000 | empty；curl exit 7；DNS=`198.18.0.249` | RUN / ENVIRONMENT LIMITED |
| `https://grokbuddy.amirhasan.top/ready` | 000 | empty；curl exit 7；DNS=`198.18.0.249` | RUN / ENVIRONMENT LIMITED |
| `https://grokbuddy.amirhasan.top/` | 000 | empty；curl exit 7；DNS=`198.18.0.249` | RUN / ENVIRONMENT LIMITED（沿用 6.8 人工根路径证据） |

`/health` 只证明进程存活；新增 `/ready` 以只读 `SELECT 1` 检查 Hub SQLite。`Test-GrokBuddyRuntime.ps1` 对每个 curl 固定 `--connect-timeout 2 --max-time 5`，不会以前台方式启动常驻进程。

## 6. 重启验收

`REBOOT ACCEPTANCE: NOT RUN`。本轮未获授权重启机器，不能把 Automatic/AtLogOn 配置、手工进程恢复或已冻结公网证据冒充重启证据。

重启后验收命令、预期码、卸载与恢复步骤见 [Phase 6 Operations Runbook](PHASE6_OPERATIONS_RUNBOOK.md)。在 Hub 任务 Secret 上下文修复、实际重启并登录、8788 自动监听、本地与公网三路径通过之前，6.9 与 Pack E 都不得判 PASS。

## 7. Observability / recovery

- `/health`：HTTP 进程 liveness。
- `/ready`：SQLite 只读 readiness；失败返回 503 与 `database=unavailable`，不泄露异常内容。
- cloudflared：`Get-Service`、`sc.exe queryex/qc/qfailure cloudflared`。
- Hub：`Get-ScheduledTask`、`Get-ScheduledTaskInfo`、`Get-NetTCPConnection -LocalPort 8788`、`var/service/logs/hub.*.log`。
- 恢复顺序：Quick Tunnel 清零 → cloudflared Running/Automatic → 读取首个 Hub bootstrap 错误 → 修复受保护 Secret 注入 → 本地 health/ready/root → 公网固定 PublicBase。未知结果不循环重发或改 hostname。

## 8. Human Action Required

到此触及外站/凭据 Hard Stop，不自行登录或修改。

| 系统 | 点击/配置路径 | 旧值检查 | 目标值 | 验收 |
| --- | --- | --- | --- | --- |
| GitHub Webhook | GitHub 仓库 `amir-hasan666/grokbuddy` → **Settings** → **Webhooks** → 打开当前 Hub webhook → **Edit** | 若 Payload URL 为任意 `https://*.trycloudflare.com/webhooks/github`，记录旧值后替换；Secret 不变 | `https://grokbuddy.amirhasan.top/webhooks/github` | Save 后查看 Recent Deliveries；只确认合法 GitHub delivery 响应，不改 event/secret/权限 |
| Grok / Remote MCP Connector | Grok/Cursor/实际使用客户端的 MCP Server 设置 → 选择现有 `grokbuddy-hub` → Edit server URL | 任意 `https://*.trycloudflare.com/mcp` | `https://grokbuddy.amirhasan.top/mcp` | 保留原 Bearer secret；只执行只读 initialize/tools/list/query，不运行 6.20 |
| Grok Reviewer | Grok Bot 桌面端 → `workbuddy审核员` 聊天标题 → 信息页 → `Routines`；同时核对该 Reviewer 的 Hub base/callback 配置 | 任意 trycloudflare request base/callback | request base `https://grokbuddy.amirhasan.top`；callback `https://grokbuddy.amirhasan.top/reviewer/events` | 保持 Routine disabled；不 Test Run，不创建 RR，不假定 Comment 可唤醒 |
| Hub 自启 Secret | Windows 本机受保护凭据方案 | 当前 DPAPI 文件对 Task Scheduler 上下文不可解密 | Human 明确批准 Windows Credential Manager，或由任务主体安全重新封装现有三项 Secret | Task `LastTaskResult=0`、实际重启后 8788 自动监听；禁止命令行/明文文件 |
| 旧本机密文副本 | `%LOCALAPPDATA%\GrokBuddy\hub-secrets.clixml` | 当前计划任务已不引用该路径；不读取内容 | 完成新凭据方案并确认无引用后，由 Human 决定是否删除 | 删除前先核对任务 Action；本轮不擅自删除凭据文件 |

## 9. 验证命令与结果

| 检查 | 结果 |
| --- | --- |
| PowerShell parser：`scripts/windows/*.ps1` | 7 scripts，0 parse errors |
| `python -m pytest -q tests/test_phase4_remote_mcp.py` | 9 passed |
| `python -m pytest -q` | 773 passed in 146.18s |
| `python -m pip check` | No broken requirements found |
| `python scripts/validate_phase0.py --allow-core` | 219/219 contract checks passed；通用 external environment gate 仍为 BLOCKED，不替代本报告的本机证据 |
| `scripts/windows/Test-GrokBuddyRuntime.ps1` | 当前 PID 11660 监听；本地 200/200/404 与 body 均符合；公网三项均 curl exit 7 / HTTP 000，脚本按设计整体非零退出 |
| `git diff --check` | PASS |
| Secret Git 边界 | `git check-ignore` 命中 `.gitignore:14:var/`；未 stage/commit Secret |

全量测试使用本地隔离 fixture；不等于 Windows 重启、公网当前路径或外站 Connector 验收。

## 10. 边界与结论

本轮未修改 Domain 状态机、Phase 6.0–6.7 合同数字、业务 Task/RR、Hub DB 业务记录或外站配置；未运行 Grok/WorkBuddy 真审核，未开始 6.20，未 push/merge/approve。

6.8 保持 PASS；6.9 因任务 Secret 上下文、重启证据和当前机公网探测限制为 PARTIAL；Pack E 因上述项及 GitHub/Grok 外站 URL 尚待 Human 核对修改而 NOT PASS。到此 STOP。
