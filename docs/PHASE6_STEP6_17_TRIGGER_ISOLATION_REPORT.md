PHASE6-STEP6.17-TRIGGER-ISOLATION: WAITING HUMAN RETEST

# Phase 6 Step 6.17 — Trigger Isolation Evidence

日期：2026-09-21（Asia/Shanghai）

## 1. 结论与边界

Human 已在 WorkBuddy 5.5.6 同一 conversation 完成 Case A，并报告 `PASS`；Case B 发送精确短语后，代理错误调用普通 `grokbuddy-hub.create_task`，Hub 返回 `PERMISSION_FAILURE: Dedicated WorkBuddy ingress principal required`。B-before 与失败后的 B-after 为零 mutation，证明 6.1 fail closed 未被破坏，但 B 没有创建活动 Task，因此不能判为 PASS。仓内现已补齐独立 ingress、Credential wrapper、WorkBuddy 配置/skill 和本地测试；仍须由 Human 重跑 B→C，当前结论为 `WAITING HUMAN RETEST`。

6.17 只验证 D1–D3 的 Trigger Isolation：无精确触发词不创建、不 sticky；有合格触发词只创建一个带可信 `trigger_evidence` 的活动 GrokBuddy Task；B 的 Task 终态后，普通消息仍不触发。本步不是流程审核或完整任务闭环。

`6.17 PASS ≠ 6.19 ≠ 6.20`。本轮未开始 6.19/6.20，未修改 Trigger 合同、状态机或 Plan≤2 / Final≤3，未恢复 Quick Tunnel，未发 WorkBuddy 消息，未启动真实 Hub，未写目标 `var/workbuddy-mcp/hub.db`，未 dispatch RR；测试只写 pytest 隔离目录。

## 2. 前置证据

- [Phase 6 Pack E 收尾报告](PHASE6_PACK_E_WRAP_REPORT.md) 已记录：`PHASE6-STEP6.8-NAMED-TUNNEL-PUBLICBASE: PASS`、`PHASE6-STEP6.9-AUTOSTART-OBSERVABILITY: PASS`、`PHASE6-PACK-E: PASS`，且明确 `Pack E PASS ≠ 6.17 ≠ 6.19 ≠ 6.20`。
- 本次 6.17 准备阶段只做了只读复核，不用历史结果冒充当前可用性。2026-09-21 21:46（Asia/Shanghai）本地 `/health`、`/ready`、`/` 实测为 200/200/404；同轮完整运行探针对固定 PublicBase 报 `curl: (7) Failed to connect`，因此该次公网状态只记为 `CURRENT PUBLIC ROUTE NOT VERIFIED`，不改写 Pack E 的历史 Human PASS，也不在本步尝试修复。

| 前置项 | 当次命令 / 证据 | 结果 |
| --- | --- | --- |
| Pack E | `docs/PHASE6_PACK_E_WRAP_REPORT.md` | PASS（既有 Human 重启验收） |
| Hub local health/ready/root | `curl.exe -4 --connect-timeout 2 --max-time 5 http://127.0.0.1:8788/{health,ready,/}`（逐项执行） | 200 `{"status":"ok"}` / 200 `database=ok` / 404 `not_found`；PASS（21:46） |
| 固定 PublicBase 当前探测 | `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\Test-GrokBuddyRuntime.ps1` | exit 1；`curl: (7) Failed to connect to grokbuddy.amirhasan.top:443`；CURRENT PUBLIC ROUTE NOT VERIFIED |
| Hub DB query-only smoke | `snapshot --label harness-smoke-not-a-case`，默认 `var/github-manual/hub.db` | PASS；`query_only=true`；Task=3，活动 Task=0，活动 GrokBuddy Task=0；探针前后 `hub.db` mtime 未变 |

## 3. 现场 Case A/B 与根因

| Case | 现场事实 | 判定 |
| --- | --- | --- |
| A | Human 在同一 WorkBuddy conversation 发送无触发词消息；6.17 compare 为 PASS。 | PASS（Human 报告；不由本地夹具替代） |
| B | Human 发送 `启用grokbuddy流程，帮我列一个三步的今日待办提纲。`；WorkBuddy 代理选择 `grokbuddy-hub.create_task`；Hub 返回 `PERMISSION_FAILURE: Dedicated WorkBuddy ingress principal required`；B-before vs B-after-failed-ingress 零 mutation。 | BLOCKED（根因为缺少专用 ingress connector + evidence issuer） |
| C | B 尚未成功创建/终结 Task。 | NOT RUN |

现有两个连接器的职责不能填补该缺口：`grokbuddy-hub` 固定为普通 `builder`，不得通过参数冒充 ingress；`grokbuddy-worker` 只负责领取、上传、进度和完成 Worker 子生命周期，首次信任它也不会自动获得建单权。正确修复必须增加第三个受限入口，而不是放宽 `TaskService.create_task`。

## 4. 只读探针

探针：`scripts/windows/Test-GrokBuddyTriggerIsolation.py`

它有两个命令：

- `snapshot`：在独立子进程中以 SQLite `mode=ro`、`query_only=ON` 读取 Hub；默认硬超时 10 秒。保存所有 Hub 业务表的行数、行哈希及必要的安全 Task 元数据，不保存消息正文、触发签名或 Secret。
- `compare`：只读取两个 JSON 快照。A/C/B′ 要求所有 Hub 表的 ID/内容哈希完全不变；B 要求恰好新增一个 Task、没有删除或改写既有 Task、新 Task 非终态且 `grokbuddy_enabled=true`、`trigger_evidence` 关键字段齐全、同 conversation 前 0 后 1 个活动 GrokBuddy Task。B 的其他支持记录增量仅如实列出，不作为 6.20 证据。

建议先创建本地证据目录；该目录位于已忽略的 `var/` 下，不应提交：

```powershell
$EvidenceDir = '.\var\evidence\phase6-step6.17'
New-Item -ItemType Directory -Force -Path $EvidenceDir | Out-Null
$Probe = '.\.venv\Scripts\python.exe'
$Harness = '.\scripts\windows\Test-GrokBuddyTriggerIsolation.py'
```

每个输出文件默认不可覆盖；若文件已存在，请换一个带时间戳的新文件名，保留原始证据。

## 5. Human + WorkBuddy 真机执行清单

Owner：**Human + WorkBuddy**。Codex 不代发消息。A、B、C 必须在同一 WorkBuddy conversation 中按顺序执行；每条消息前先完成 before snapshot，WorkBuddy 回复后立即完成 after snapshot。

重跑 B 前先由 Human 完成：

1. WorkBuddy MCP 管理中对 `grokbuddy-worker` 点“信任”（若尚未）。
2. 按 [WorkBuddy 集成说明](WORKBUDDY_INTEGRATION.md) 在 Windows Credential Manager 配置与 Hub 一致、至少 32 UTF-8 bytes 的 `GROKBUDDY_TRIGGER_SOURCE_KEY`；不得把值贴进聊天、JSON、Git 或日志。
3. 合并无 Secret 的 [grokbuddy-ingress 配置样例](examples/workbuddy-ingress-mcp.example.json)，安装 [trigger skill](workbuddy-skills/grokbuddy-trigger-ingress/SKILL.md)，刷新/重启 WorkBuddy，并对新 ingress 完成首次信任。
4. 确认 `grokbuddy-ingress` 只暴露 `create_triggered_task`。精确命中时必须调用它；禁止调用普通 `grokbuddy-hub.create_task` 作为替代或 fallback。

Case A 的既有 PASS 不需要为了安装连接器而改写；正式收口仍需把其非 Secret 原始摘要与本轮 B/C 证据一起归档。

### Case A — 无触发词，0 mutation

```powershell
& $Probe $Harness snapshot --label A-before --output "$EvidenceDir\A-before.json"
# Human 在 WorkBuddy 发送：帮我写一句问候语，不要启用任何特殊流程。
& $Probe $Harness snapshot --label A-after --output "$EvidenceDir\A-after.json"
& $Probe $Harness compare --case A --before "$EvidenceDir\A-before.json" --after "$EvidenceDir\A-after.json" --output "$EvidenceDir\A-result.json"
```

期望：compare 退出码 0，`CASE A: PASS`，`changed_tables=(none)`。

### Case B — 精确触发，新建 1 个活动 Task

```powershell
& $Probe $Harness snapshot --label B-before --output "$EvidenceDir\B-before.json"
# Human 在同一 WorkBuddy conversation 发送：启用grokbuddy流程，帮我列一个三步的今日待办提纲。
& $Probe $Harness snapshot --label B-after --output "$EvidenceDir\B-after.json"
& $Probe $Harness compare --case B --before "$EvidenceDir\B-before.json" --after "$EvidenceDir\B-after.json" --output "$EvidenceDir\B-result.json"
```

期望：compare 退出码 0，`CASE B: PASS`。从输出或 `B-result.json` 记录 `new_task_id` 与 `conversation_id`。若 Task 在 after snapshot 前已经终态，则不满足本用例“活动 Task”证据，不能人工改判 PASS。

### Case C — B 已终态后普通消息仍不 sticky

前置：由 Human Abort/`close_task` 或小任务自然结束，使 B 的 Task 进入 `DONE`、`CANCELLED` 或 `FAILED`。只读确认已终态后，把下方 `<B_TASK_ID>` 替换为 B 的真实 ID；探针本身不会关闭 Task。

```powershell
& $Probe $Harness snapshot --label C-before --output "$EvidenceDir\C-before.json"
# Human 在同一 WorkBuddy conversation 发送：再写一句谢谢，普通回复即可。
& $Probe $Harness snapshot --label C-after --output "$EvidenceDir\C-after.json"
& $Probe $Harness compare --case C --task-id '<B_TASK_ID>' --before "$EvidenceDir\C-before.json" --after "$EvidenceDir\C-after.json" --output "$EvidenceDir\C-result.json"
```

期望：compare 退出码 0，`CASE C: PASS`，所有 Hub 表 0 mutation；B Task 在前后都保持终态；该 conversation 前后均无活动 GrokBuddy Task。

### 可选 Case B′ — 短语仅在代码围栏或 Markdown 引用

只选一种消息形态执行，且不得再在解释正文中写出未隔离的触发词。示例使用代码围栏：

````powershell
& $Probe $Harness snapshot --label BPRIME-before --output "$EvidenceDir\BPRIME-before.json"
# Human 在同一 WorkBuddy conversation 发送以下整段：
# ```text
# 启用grokbuddy流程
# ```
& $Probe $Harness snapshot --label BPRIME-after --output "$EvidenceDir\BPRIME-after.json"
& $Probe $Harness compare --case BPRIME --before "$EvidenceDir\BPRIME-before.json" --after "$EvidenceDir\BPRIME-after.json" --output "$EvidenceDir\BPRIME-result.json"
````

期望：与 A 相同，所有 Hub 表 0 mutation。

## 6. A/B/C 证据表（Human 重跑后再改结论）

| Case | Human 消息 | before snapshot | after snapshot | compare / Task 证据 | 判定 |
| --- | --- | --- | --- | --- | --- |
| A | `帮我写一句问候语，不要启用任何特殊流程。` | `[Human 已运行；待粘贴非 Secret 摘要]` | `[Human 已运行；待粘贴非 Secret 摘要]` | `CASE A: PASS`（Human 报告） | PASS |
| B（首次） | `启用grokbuddy流程，帮我列一个三步的今日待办提纲。` | `[Human 已运行；待粘贴非 Secret 摘要]` | `[失败后已运行；零 mutation]` | `PERMISSION_FAILURE: Dedicated WorkBuddy ingress principal required`；无 Task | BLOCKED（历史现场） |
| B（ingress 修复后重跑） | 同上 | `[未运行]` | `[未运行]` | `task_id=[未运行]`；`conversation_id=[未运行]`；trigger evidence `[未运行]` | NOT RUN |
| C | `再写一句谢谢，普通回复即可。` | `[未运行]` | `[未运行]` | B Task 终态 `[未运行]`；0 mutation `[未运行]`；active context 0 `[未运行]` | NOT RUN |
| B′（可选） | 触发短语仅在 fenced code 或 Markdown quote | `[未运行]` | `[未运行]` | `[未运行]` | NOT RUN |

证据粘贴位：

```text
[粘贴 Test-GrokBuddyRuntime.ps1 的非 Secret 摘要]
[粘贴 A-result 控制台摘要]
[粘贴 B-result 控制台摘要，含 task_id / conversation_id]
[粘贴 B Task 终态的只读查询摘要]
[粘贴 C-result 控制台摘要]
```

仅当报告收录 Human 真机 A+B+C 原始摘要，且三项均符合期望，才可把首行改为：

`PHASE6-STEP6.17-TRIGGER-ISOLATION: PASS`

同时保留实际 Asia/Shanghai 日期和 `6.17 PASS ≠ 6.19 ≠ 6.20` 声明。

## 7. Ingress 修复、本地验证与已知限制

- 新增 `src/grokbuddy/interfaces/ingress_mcp.py` 与 `scripts/grokbuddy_ingress_mcp.py`：固定 `workbuddy-ingress`，只暴露 `create_triggered_task`；工具不接受 actor/signature/raw evidence。
- 新增 `scripts/windows/Start-GrokBuddyIngressMcp.ps1`：从 Windows Credential Manager Target `GrokBuddy/GROKBUDDY_TRIGGER_SOURCE_KEY` 读取 Key，只注入子进程；`Start-GrokBuddyHub.ps1` 从同一 Target 注入 Hub。Key 少于 32 UTF-8 bytes 时 fail closed。
- 新增 [无 Secret MCP 样例](examples/workbuddy-ingress-mcp.example.json)和 [WorkBuddy trigger skill](workbuddy-skills/grokbuddy-trigger-ingress/SKILL.md)。普通 Hub/Worker、Remote MCP 五个只读工具和 6.1 双检没有放宽。
- 新增 `tests/test_phase6_workbuddy_ingress.py`：覆盖单工具 surface、合格点火、幂等重放、普通/code fence/quote/pasted 排除、缺 Key 和未展开 session placeholder 零 mutation，以及真实 stdio 子进程 handshake/call。

- `tests/test_trigger_isolation_harness.py` 只验证快照 diff 的 A/B/B′/C 判定和行内容变更检测；它不生成 WorkBuddy 签名、不调用真实 ingress，不是 6.17 PASS 证据。其既有单项结果为 `5 passed`，真实 Hub query-only smoke 与同一份 snapshot 自比只验证 CLI/序列化路径。
- 新 ingress 聚焦测试与 6.1 trigger gate 合跑为 `23 passed`，包括同一幂等键被用于变化消息时 `CONFLICT`、未展开 session placeholder 拒绝且均零 mutation；Hub/Worker/Remote MCP 接口回归为 `46 passed`；最终 `python -m pytest -q` 为 `787 passed in 154.55s`。`compileall`、三个 PowerShell 文件 parser check、example JSON parse、`git diff --check` 均 PASS；合同检查 `validate_phase0.py --allow-core` 为 `219/219 passed`。
- 本轮 ingress 新增文件为 `src/grokbuddy/interfaces/ingress_mcp.py`、`scripts/grokbuddy_ingress_mcp.py`、`scripts/windows/Start-GrokBuddyIngressMcp.ps1`、`tests/test_phase6_workbuddy_ingress.py`、gap report、无 Secret MCP example 与 WorkBuddy skill；最小修改 trigger issuer、Credential/Hub launcher、WorkBuddy/operations/6.17 文档。既有 smoke JSON 仍位于 Git ignored 的 `var/evidence/phase6-step6.17/`，未纳入提交。
- WorkBuddy 官方 Skills 支持运行时 `${CODEBUDDY_SESSION_ID}`；当前 skill 将其作为 Hub conversation ID，未展开占位符 fail closed，adapter 再由 session ID + idempotency key 派生稳定 message/turn ID。自定义 MCP schema 仍没有已验证的 native user-message ID/provenance 注入字段；真 WorkBuddy 是否实际展开当前 session、是否按 skill 传入真实 provenance，仍为 `ENVIRONMENT_VALIDATION_REQUIRED`，只能由上述 Human B→C 真机步骤闭合。
- 固定 PublicBase 在 6.17 准备时的有界探测未连通；原因未在本步诊断或修复。新 WorkBuddy ingress 是本机 stdio，不以 Quick Tunnel 或 PublicBase 代替；PublicBase 继续固定为 `https://grokbuddy.amirhasan.top`，需要公网运行态证据时按既有 Pack E 运维 runbook 另行复核，不能改 hostname。
- SQLite 前后快照不能自动把并发的无关 Hub 变化归因给某条 WorkBuddy 消息。A/C 若出现任何变化必须保留 diff、查清来源并在安静窗口重跑，不能删除差异后手工判 PASS。
- B 只验证 Trigger 创建与 conversation 活动唯一性；即使支持表出现后续自动变化，也不能据此声称 6.19 或 6.20 已通过。

## 8. 当前 STOP

Case A 已 PASS；Case B 的失败根因已定位并完成仓内接线，Case B 修复后重跑与 Case C 尚未执行。当前结论保持 `WAITING HUMAN RETEST`，到此 STOP，不开始 6.19/6.20，也不自行宣称 6.17 PASS。
