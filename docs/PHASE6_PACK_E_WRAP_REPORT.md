`PHASE6-STEP6.8-NAMED-TUNNEL-PUBLICBASE: PASS`
`PHASE6-STEP6.9-AUTOSTART-OBSERVABILITY: PASS`
`PHASE6-PACK-E: PASS`

# Phase 6 Pack E — 6.9 Autostart / Cleanup / Observability Wrap

日期：2026-09-21（Asia/Shanghai）

`REBOOT ACCEPTANCE: PASS`（2026-09-21 约 21:17，Asia/Shanghai）

事故恢复说明：上一轮 Codex Shell 等待状态卡死后，本轮从现有脏工作区继续；未 reset/checkout/clean，已落盘代码、Windows Service 与 `var/service/hub-secrets.clixml` 均保留。

## 1. 6.8 PublicBase 证据边界

沿用 Human 已验证事实：Named Tunnel 名为 `grokbuddy`，固定 PublicBase 为 `https://grokbuddy.amirhasan.top`，published route 指向 `http://localhost:8788`；人工 curl/手机路径已支持 6.8 PASS。根路径返回 HTTP 404 与 `{"error":"not_found"}` 是应用层预期，不是网络失败。

本轮 2026-09-21 20:27（Asia/Shanghai）在任务托管 Hub 已启动后，`Test-GrokBuddyRuntime.ps1` 对固定 PublicBase 的 `/health`、`/ready`、`/` 分别得到 200、200、404，body 与本地口径一致。该运行态证据补充但不替代已冻结的 6.8 Human 证据，也不构成重启验收。

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
- `scripts/windows/Get-GrokBuddyCredential.ps1`
- `scripts/windows/Test-GrokBuddyCredentialStore.ps1`
- `scripts/windows/Install-GrokBuddyHubTask.ps1`
- `scripts/windows/Restart-GrokBuddyHubTask.ps1`
- `scripts/windows/Uninstall-GrokBuddyHubTask.ps1`
- `scripts/windows/Test-GrokBuddyRuntime.ps1`

正式 Secret Source 已切换为当前用户 Windows Credential Manager `CRED_TYPE_GENERIC`。`CredReadW`/`CredFree` 读取三个固定 Target，任一 missing、empty 或 unreadable 均 fail closed；值只注入 launcher/Hub Process 环境。任务 Action 不含 Secret 名称、值或路径。现场发现的三个 User 级同名环境变量已按正式决策精确清除，复核 User/Machine 持久值均不存在。

旧 `var/service/hub-secrets.clixml` 保留、Git ignored、安装时 metadata 复核未改变；Start/Install/Uninstall 已不引用、覆盖或删除它。

计划任务 `GrokBuddy Hub` 保持当前用户 AtLogOn、Interactive、Limited、restart count 10。2026-09-21 20:26 本地切换验证中，重启脚本只停止本仓库旧 Hub PID 11660；清除 User 持久环境值后再次从 Credential Manager 启动，最终 PID 21160 监听 `127.0.0.1:8788`。任务当前 `State=Running`、`LastTaskResult=267009 (0x41301 / SCHED_S_TASK_RUNNING)`。这是长期 launcher 正持有 Hub 子进程的正常状态，不应机械要求 `LastTaskResult=0`。

## 5. 当前 health / readiness

本机有界探测：

| Endpoint | HTTP | Body | 结果 |
| --- | ---: | --- | --- |
| `http://127.0.0.1:8788/health` | 200 | `{"status":"ok"}` | RUN / PASS（liveness） |
| `http://127.0.0.1:8788/ready` | 200 | `{"checks":{"database":"ok"},"status":"ready"}` | RUN / PASS（SQLite readiness） |
| `http://127.0.0.1:8788/` | 404 | `{"error":"not_found"}` | RUN / EXPECTED |
| `https://grokbuddy.amirhasan.top/health` | 200 | `{"status":"ok"}` | RUN / PASS（当前运行态） |
| `https://grokbuddy.amirhasan.top/ready` | 200 | `{"checks":{"database":"ok"},"status":"ready"}` | RUN / PASS（当前运行态） |
| `https://grokbuddy.amirhasan.top/` | 404 | `{"error":"not_found"}` | RUN / EXPECTED（当前运行态） |

`/health` 只证明进程存活；新增 `/ready` 以只读 `SELECT 1` 检查 Hub SQLite。`Test-GrokBuddyRuntime.ps1` 对每个 curl 固定 `--connect-timeout 2 --max-time 5`，不会以前台方式启动常驻进程。

## 6. 重启验收

`REBOOT ACCEPTANCE: PASS`。

2026-09-21 约 21:17（Asia/Shanghai），Human 已重启 Windows、登录配置任务的用户，且未手工启动 Hub。以下表格只记录 Human 提供的当次命令输出摘要，不补写未提供的字段，也不读取或记录 Secret 值/hash：

| 时间 | 命令 / 探针 | 当次关键字段 | 判定 |
| --- | --- | --- | --- |
| 2026-09-21 约 21:17（Asia/Shanghai） | `Test-GrokBuddyCredentialStore.ps1` | `GrokBuddy/GITHUB_WEBHOOK_SECRET: PRESENT`；`GrokBuddy/GROKBUDDY_MCP_TOKEN: PRESENT`；`GrokBuddy/GROKBUDDY_GROK_REVIEWER_TOKEN: PRESENT` | PASS；Secret Source 仍为当前任务用户的 Windows Credential Manager |
| 同次重启验收 | `Test-GrokBuddyRuntime.ps1` | cloudflared `Running / Automatic` | PASS |
| 同次重启验收 | `Test-GrokBuddyRuntime.ps1` | Hub task `Running`；`LastTaskResult=267009`（`SCHED_S_TASK_RUNNING`）；`HoldsHubProcess=true` | PASS；长期 launcher 正持有 Hub 子进程，`267009` 是预期状态，不要求为 `0` |
| 同次重启验收 | `Test-GrokBuddyRuntime.ps1` | 8788 `LISTENING`；Human 摘要中的示例 PID 为 5440，实际 PID 属易变字段，以保存的当次输出为准 | PASS |
| 同次重启验收 | `Test-GrokBuddyRuntime.ps1` | 本地 `/health`、`/ready`、`/` 为 `200 / 200 / 404`，body 符合约定 | PASS |
| 同次重启验收 | `Test-GrokBuddyRuntime.ps1` | 公网 `https://grokbuddy.amirhasan.top` 的 `/health`、`/ready`、`/` 为 `200 / 200 / 404`，body 符合约定 | PASS |

重启验收命令、预期码、卸载与恢复步骤继续以 [Phase 6 Operations Runbook](PHASE6_OPERATIONS_RUNBOOK.md) 为准。上述证据闭合了“实际重启并登录 → AtLogOn 自动拉起 → 8788 自动监听 → 本地/固定 PublicBase 有界探测通过”的 6.9 Gate；因此 `PHASE6-STEP6.9-AUTOSTART-OBSERVABILITY: PASS`。

## 7. Observability / recovery

- `/health`：HTTP 进程 liveness。
- `/ready`：SQLite 只读 readiness；失败返回 503 与 `database=unavailable`，不泄露异常内容。
- cloudflared：`Get-Service`、`sc.exe queryex/qc/qfailure cloudflared`。
- Credential Store：`Test-GrokBuddyCredentialStore.ps1` 只输出 Target 与 `PRESENT`；credential 日志已验证只含允许的 `PRESENT`/`credential target missing: GrokBuddy/...` 状态语法。
- Hub：`Get-ScheduledTask`、`Get-ScheduledTaskInfo`、`Get-NetTCPConnection -LocalPort 8788`、`var/service/logs/hub.*.log`。任务 `Running + 267009` 是长期 launcher 正常语义。
- 恢复顺序：Quick Tunnel 清零 → cloudflared Running/Automatic → Credential Store 三项 PRESENT → 读取首个 Hub bootstrap 错误 → 本地 health/ready/root → 公网固定 PublicBase。未知结果不循环重发、不改 hostname、不降级为持久环境变量。

## 8. 外站操作边界与运营参考

本次文档收口没有登录或修改 GitHub/Grok 控制台，没有新增 Webhook/Connector/Reviewer 试跑证据。下表保留为后续运营核对路径，不表示本次执行了这些动作；指导老师已于 2026-09-21 口头确认可按现有 6.8 冻结证据与本次 Human 重启验收收口 Pack E。

| 系统 | 点击/配置路径 | 旧值检查 | 目标值 | 验收 |
| --- | --- | --- | --- | --- |
| GitHub Webhook | GitHub 仓库 `amir-hasan666/grokbuddy` → **Settings** → **Webhooks** → 打开当前 Hub webhook → **Edit** | 若 Payload URL 为任意 `https://*.trycloudflare.com/webhooks/github`，记录旧值后替换；Secret 不变 | `https://grokbuddy.amirhasan.top/webhooks/github` | Save 后查看 Recent Deliveries；只确认合法 GitHub delivery 响应，不改 event/secret/权限 |
| Grok / Remote MCP Connector | Grok/Cursor/实际使用客户端的 MCP Server 设置 → 选择现有 `grokbuddy-hub` → Edit server URL | 任意 `https://*.trycloudflare.com/mcp` | `https://grokbuddy.amirhasan.top/mcp` | 保留原 Bearer secret；只执行只读 initialize/tools/list/query，不运行 6.20 |
| Grok Reviewer | Grok Bot 桌面端 → `workbuddy审核员` 聊天标题 → 信息页 → `Routines`；同时核对该 Reviewer 的 Hub base/callback 配置 | 任意 trycloudflare request base/callback | request base `https://grokbuddy.amirhasan.top`；callback `https://grokbuddy.amirhasan.top/reviewer/events` | 保持 Routine disabled；不 Test Run，不创建 RR，不假定 Comment 可唤醒 |
| 旧本机密文副本 | `var/service/hub-secrets.clixml` | 已退出 Start/Install/Uninstall 正式链路；内容未读取 | 保留，不删除、不覆盖 | Git ignored；本轮已核对安装前后 metadata 未改变 |

## 9. 验证命令与结果

| 检查 | 结果 |
| --- | --- |
| Windows Credential Store | 3 个固定 Target 均 `PRESENT`；未输出 Secret/hash |
| PowerShell parser：`scripts/windows/*.ps1` | 9 scripts，0 parse errors |
| `python -m pytest -q tests/test_phase4_remote_mcp.py` | 9 passed |
| `python -m pytest -q` | 773 passed in 164.00s |
| `python -m pip check` | No broken requirements found |
| `python scripts/validate_phase0.py --allow-core` | 219/219 contract checks passed；通用 external environment gate 仍为 BLOCKED，不替代本报告的本机证据 |
| `scripts/windows/Test-GrokBuddyRuntime.ps1` | Task `Running` / `267009`；最终 PID 21160 监听；本地与公网均为 200/200/404，body 全部符合 |
| Human 重启后再次运行 `Test-GrokBuddyCredentialStore.ps1` / `Test-GrokBuddyRuntime.ps1` | `REBOOT ACCEPTANCE: PASS`；三项 Credential Target 均 `PRESENT`；cloudflared `Running / Automatic`；Hub task `Running / 267009` 且 `HoldsHubProcess=true`；8788 `LISTENING`；本地与公网均为 200/200/404，body 符合约定 |
| `git diff --check` | PASS |
| Secret Git 边界 | `git check-ignore` 命中 `.gitignore:14:var/`；未 stage/commit Secret |

全量测试使用本地隔离 fixture；它本身不等于 Windows 重启、公网当前路径或外站 Connector 验收。重启与公网当前路径的 PASS 由上表单列的 Human 重启后运行输出支持；本次仍没有新增外站 Connector 试跑。

## 10. 边界与结论

本轮未修改 Domain 状态机、Phase 6.0–6.7 合同数字、业务 Task/RR、Hub DB 业务记录或外站配置；未运行 Grok/WorkBuddy 真审核，未开始 6.20，未 push/merge/approve。

6.8 保持 PASS。Human 真机重启并登录任务用户后，没有手工启动 Hub；三项 Credential Target、cloudflared、Hub 长期 launcher、8788 监听以及本地/固定 PublicBase 探测均满足验收口径，因此 6.9 为 PASS。指导老师已口头确认可收口，`PHASE6-PACK-E: PASS`。

`Pack E PASS ≠ 6.17 ≠ 6.19 ≠ 6.20`。本次没有开始或放行 6.17、6.19、6.20；后续仍按 6.17 → 6.19 → 6.20 的独立授权与 Gate 继续，其中 6.19 未 PASS 时不得启动 6.20。到此 STOP。

## 11. 后续步骤（不在本次授权内）

- 6.17：仍待独立授权与对应 Gate，不因 Pack E PASS 自动开始。
- 6.19：仍待独立 Production Preconditions 验收。
- 6.20：仍未开始；仅可在 6.19 PASS 后按独立授权执行 Real Final E2E。
