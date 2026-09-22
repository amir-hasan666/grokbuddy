PHASE6-STEP6.19: PASS

# Phase 6 Step 6.19 — RuntimeDir Source of Truth Alignment

日期：2026-09-22（Asia/Shanghai）

## 1. 结论与停止边界

仓内正式 Hub、WorkBuddy Hub MCP、Worker MCP 与 ingress MCP 的 RuntimeDir 指引现统一锚定 [config/grokbuddy.service.json](../config/grokbuddy.service.json) 的 `runtimeDir`，当前为 `var/github-manual`，绝对路径是 `D:\Codex\grokbuddy\var\github-manual`。PublicBase 保持 `https://grokbuddy.amirhasan.top`；普通 `create_task`、Builder、Worker 和 Remote MCP 权限均未放宽。

仓内对齐后，Human 已完成本机 `C:\Users\22241\.workbuddy\mcp.json`、WorkBuddy 工具面与重启后探活复核，6.19 的 Human REVERIFY 已闭合。`var/workbuddy-mcp/hub.db` 未迁移、未删除，继续作为 6.17 历史证据库。

`6.19 PASS ≠ 6.20`。本次不启动 6.20。

## 2. Human 提供的重启后与对齐后现场

Human 已闭合以下本机复核证据，本报告按现场事实记录，不用仓内静态检查替代：

- Credential 4 `PRESENT`；`cloudflared` `Running/Automatic`；Hub `AtLogOn` `LastRunTime=2026-09-22 09:01:00`，`LastTaskResult=267009`。
- 重启后本地+公网 `https://grokbuddy.amirhasan.top`：`/health` `/ready` `/` = `200/200/404`。
- 改 mcp 后再次 `Test-GrokBuddyRuntime.ps1`（`CheckedAt=2026-09-22T09:48:39+08:00`）同上全绿。
- 本机 `C:\Users\22241\.workbuddy\mcp.json`：hub/worker/ingress 的 RuntimeDir 均为 `D:\Codex\grokbuddy\var\github-manual`。
- WorkBuddy 确认 `grokbuddy-ingress` 仅 1 工具：`create_triggered_task`（完整名 `mcp__grokbuddy_ingress__create_triggered_task`）。
- `var/workbuddy-mcp/hub.db` 未删，仍为 6.17 历史证据库；正式 SoT=`var/github-manual`。
- `6.19 PASS ≠ 6.20`；未跑真实点火/E2E。

## 3. 只读差距盘点

修改前对 Git tracked 的 PowerShell、Python、JSON 与 Markdown 执行 `git grep -n -I workbuddy-mcp`。结果如下：

| 分类 | 文件 | 处置 |
| --- | --- | --- |
| 活动 MCP 示例 | `docs/examples/workbuddy-ingress-mcp.example.json`、`docs/examples/workbuddy-mcp-smoke.json` | RuntimeDir 改为 `D:\Codex\grokbuddy\var\github-manual`。 |
| 活动启动说明 | `README.md`、`docs/WORKBUDDY_INTEGRATION.md` | 正式命令改为 `github-manual`；增加 Human 本机三 server 对齐步骤与 WAITING 边界。 |
| 启动器 | `scripts/windows/Start-GrokBuddyHub.ps1`、`scripts/windows/Start-GrokBuddyIngressMcp.ps1` | Hub 原已读取 service config；Ingress 原无硬编码默认、但强制传参，现允许省略并从同一 service config 读取。仓内没有 `Start-GrokBuddyWorker*.ps1`。 |
| 测试 | `tests/` 修改前没有 `var/workbuddy-mcp` 硬编码 | 新增静态回归，校验 service config、PublicBase 和两个 MCP 示例一致，并校验 ingress launcher 使用 service config 默认值。 |
| 6.17 历史证据 | `docs/PHASE6_STEP6_17_TRIGGER_ISOLATION_REPORT.md`、`docs/PHASE6_WORKBUDDY_INGRESS_GAP_REPORT.md` | 保留 6.17 PASS 和当次 B4/C 路径；前者增加正式 SoT 交叉说明。 |
| 更早历史证据 | `docs/PHASE2_REPORT.md`、`docs/PHASE3_REPORT.md`、`docs/PHASE5_FUNCTIONAL_EXIT_EVIDENCE_REPORT.md`、`docs/PHASE5_STEP10_12_REPORT.md`、`docs/PHASE5_STEP11_12_RESULT.md`、`docs/PHASE5_WORKBUDDY_UPLOAD_READY_REPORT.md`、`docs/phase5-probe-final-state.json` | 不改历史路径或结果；这些记录描述当次隔离库/证据，不是当前正式 SoT。 |

`var/workbuddy-mcp/hub.db` 不删除、不复制、不自动迁移，只读定位为 6.17 及更早阶段的历史证据库。6.17 历史 B4 使用了 `--database var/workbuddy-mcp/hub.db`；此后正式验收使用探针默认的 `var/github-manual/hub.db`。

## 4. 本次仓内对齐

- 两个 MCP JSON 示例的 RuntimeDir 均改为 `D:\Codex\grokbuddy\var\github-manual`，未加入 Key/Token。
- `Start-GrokBuddyIngressMcp.ps1` 在未传 `-RuntimeDir` 时读取 `config/grokbuddy.service.json`；显式参数仍用于兼容现有 WorkBuddy 配置。
- `Start-GrokBuddyHub.ps1` 继续读取同一 service config，无需改动。
- 仓内没有 Worker PowerShell launcher；Worker 的正式 RuntimeDir 由 Human 在 WorkBuddy `mcp.json` 中对齐。
- `docs/WORKBUDDY_INTEGRATION.md` 明确仓内示例更新不会改写本机配置，并给出三 server 的路径检查表。
- 6.17 报告只增加历史库与现行 SoT 的交叉说明，不改 6.17 PASS。

## 5. Human 本机操作与 Reverify（已完成）

Owner：**Human + WorkBuddy**。不要把 Key/Token 粘贴到 JSON、聊天、Git、报告或命令历史。

1. 打开 `C:\Users\22241\.workbuddy\mcp.json`；保留 server、tool、env 与权限配置，只改 RuntimeDir 参数。
2. 将 `grokbuddy-hub` 的 `--runtime-dir`、`grokbuddy-worker` 的 `--runtime-dir`、`grokbuddy-ingress` 的 `-RuntimeDir` 后一项全部改为 `D:\Codex\grokbuddy\var\github-manual`。Ingress 也可以删除 `-RuntimeDir` 及其值，让 launcher 读取 service config。
3. 保存并刷新/重启 WorkBuddy 三个 MCP server；确认 ingress 仍只暴露 `create_triggered_task`，不要放宽普通 Hub/Worker 权限。
4. 运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\Test-GrokBuddyRuntime.ps1
```

5. 保留非 Secret 探活摘要与本机三 server RuntimeDir 已一致的确认。

Human 已完成上述复核：三个 RuntimeDir 均对齐正式 SoT，WorkBuddy ingress 仍只暴露单工具，且对齐后探活于 `2026-09-22T09:48:39+08:00` 全绿。未记录任何 Secret。

## 6. 仓内回归

仓内测试只能证明配置/语法一致性，不能证明本机 `mcp.json` 已修改或真实 WorkBuddy 已重连。

- `.\.venv\Scripts\python.exe -m pytest -q tests\test_phase6_workbuddy_ingress.py tests\test_phase6_trigger_gate.py tests\test_phase2_interfaces.py tests\test_phase5_worker_mcp.py tests\test_phase4_remote_mcp.py` → **47 passed in 32.03s**。
- `.\.venv\Scripts\python.exe -m compileall -q src\grokbuddy scripts` → exit 0。
- PowerShell AST parser 检查 `Start-GrokBuddyIngressMcp.ps1` → PASS。
- `config/grokbuddy.service.json` 与两个 MCP example 执行 `ConvertFrom-Json` → PASS。
- 本次 9 个变更/新增文件执行 strict UTF-8 decode 且检查无 BOM → PASS。
- `git diff --check` → PASS（仅出现 Git 的 LF→CRLF working-copy 提示，无 whitespace error）。

## 7. 证据结论与 STOP

- Human 本机 `mcp.json` 三 server 对齐：**PASS / HUMAN REVERIFY CLOSED**。
- 对齐后的 WorkBuddy MCP 重载与探活：**PASS / HUMAN REVERIFY CLOSED**。
- WorkBuddy `grokbuddy-ingress` 单工具面确认：**PASS / HUMAN REVERIFY CLOSED**。
- 真实 WorkBuddy 点火、Reviewer/Grok/GitHub E2E：**NOT RUN**；属于后续 6.20，不属于本次 6.19。
- Phase 6.20：**NOT STARTED**。

因此 `PHASE6-STEP6.19: PASS`，Human REVERIFY 已闭合。下一步是 Phase 6.20，必须另开且不在本轮启动。
