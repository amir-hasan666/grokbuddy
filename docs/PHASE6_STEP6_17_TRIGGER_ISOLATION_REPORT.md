PHASE6-STEP6.17-TRIGGER-ISOLATION: WAITING HUMAN / WORKBUDDY

# Phase 6 Step 6.17 — Trigger Isolation Evidence

日期：2026-09-21（Asia/Shanghai）

## 1. 结论与边界

本报告已准备只读 Hub 证据探针和 Human 真机执行清单，但 **Human 尚未在同一 WorkBuddy conversation 中完成并回填 A → B → C 证据**，因此当前只能是 `WAITING HUMAN / WORKBUDDY`，不能判为 PASS。

6.17 只验证 D1–D3 的 Trigger Isolation：无精确触发词不创建、不 sticky；有合格触发词只创建一个带可信 `trigger_evidence` 的活动 GrokBuddy Task；B 的 Task 终态后，普通消息仍不触发。本步不是流程审核或完整任务闭环。

`6.17 PASS ≠ 6.19 ≠ 6.20`。本轮未开始 6.19/6.20，未修改 Trigger 合同、状态机或 Plan≤2 / Final≤3，未恢复 Quick Tunnel，未发 WorkBuddy 消息，未启动 Hub，未写 Hub DB，未 dispatch RR。

## 2. 前置证据

- [Phase 6 Pack E 收尾报告](PHASE6_PACK_E_WRAP_REPORT.md) 已记录：`PHASE6-STEP6.8-NAMED-TUNNEL-PUBLICBASE: PASS`、`PHASE6-STEP6.9-AUTOSTART-OBSERVABILITY: PASS`、`PHASE6-PACK-E: PASS`，且明确 `Pack E PASS ≠ 6.17 ≠ 6.19 ≠ 6.20`。
- 本次 6.17 准备阶段只做了只读复核，不用历史结果冒充当前可用性。2026-09-21 21:46（Asia/Shanghai）本地 `/health`、`/ready`、`/` 实测为 200/200/404；同轮完整运行探针对固定 PublicBase 报 `curl: (7) Failed to connect`，因此该次公网状态只记为 `CURRENT PUBLIC ROUTE NOT VERIFIED`，不改写 Pack E 的历史 Human PASS，也不在本步尝试修复。

| 前置项 | 当次命令 / 证据 | 结果 |
| --- | --- | --- |
| Pack E | `docs/PHASE6_PACK_E_WRAP_REPORT.md` | PASS（既有 Human 重启验收） |
| Hub local health/ready/root | `curl.exe -4 --connect-timeout 2 --max-time 5 http://127.0.0.1:8788/{health,ready,/}`（逐项执行） | 200 `{"status":"ok"}` / 200 `database=ok` / 404 `not_found`；PASS（21:46） |
| 固定 PublicBase 当前探测 | `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\Test-GrokBuddyRuntime.ps1` | exit 1；`curl: (7) Failed to connect to grokbuddy.amirhasan.top:443`；CURRENT PUBLIC ROUTE NOT VERIFIED |
| Hub DB query-only smoke | `snapshot --label harness-smoke-not-a-case`，默认 `var/github-manual/hub.db` | PASS；`query_only=true`；Task=3，活动 Task=0，活动 GrokBuddy Task=0；探针前后 `hub.db` mtime 未变 |

## 3. 只读探针

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

## 4. Human + WorkBuddy 真机执行清单

Owner：**Human + WorkBuddy**。Codex 不代发消息。A、B、C 必须在同一 WorkBuddy conversation 中按顺序执行；每条消息前先完成 before snapshot，WorkBuddy 回复后立即完成 after snapshot。

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

## 5. A/B/C 证据表（Human 回填后再改结论）

| Case | Human 消息 | before snapshot | after snapshot | compare / Task 证据 | 判定 |
| --- | --- | --- | --- | --- | --- |
| A | `帮我写一句问候语，不要启用任何特殊流程。` | `[未运行]` | `[未运行]` | `[未运行]` | NOT RUN |
| B | `启用grokbuddy流程，帮我列一个三步的今日待办提纲。` | `[未运行]` | `[未运行]` | `task_id=[未运行]`；`conversation_id=[未运行]`；trigger evidence `[未运行]` | NOT RUN |
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

## 6. 本地夹具验证与已知限制

- `tests/test_trigger_isolation_harness.py` 只验证快照 diff 的 A/B/B′/C 判定和行内容变更检测；它不生成 WorkBuddy 签名、不调用真实 ingress，不是 6.17 PASS 证据。
- 本地命令 `python -m pytest -q tests/test_trigger_isolation_harness.py` 为 `5 passed`。真实 Hub query-only smoke 成功；用**同一份** smoke snapshot 自比得到 `CASE A: PASS / changed_tables=(none)`，这只验证 CLI 与序列化路径，绝不是 Human A 用例证据。
- 最终本地回归：`python -m py_compile scripts/windows/Test-GrokBuddyTriggerIsolation.py tests/test_trigger_isolation_harness.py` PASS；`python -m pytest -q` 为 `778 passed in 134.55s`；`git diff --check` PASS。所有 pytest 均是本地/隔离证据，不替代真机签发。
- 本轮新增文件仅为 `scripts/windows/Test-GrokBuddyTriggerIsolation.py`、`tests/test_trigger_isolation_harness.py`、`docs/PHASE6_STEP6_17_TRIGGER_ISOLATION_REPORT.md`。smoke JSON 位于 Git ignored 的 `var/evidence/phase6-step6.17/`，未纳入提交。
- 真 WorkBuddy 是否将同一 conversation、当前用户消息 provenance 和签发证据正确送达 Hub，仍为 `ENVIRONMENT_VALIDATION_REQUIRED`，只能由上述 Human 真机步骤闭合。
- 固定 PublicBase 在本次准备时的有界探测未连通；原因未在 6.17 范围内诊断或修复。若 Human/WorkBuddy 的实际签发路径依赖该入口，应先按既有 Pack E 运维 runbook 恢复并重新保存当次只读 health/ready 证据，再执行 A/B/C。
- SQLite 前后快照不能自动把并发的无关 Hub 变化归因给某条 WorkBuddy 消息。A/C 若出现任何变化必须保留 diff、查清来源并在安静窗口重跑，不能删除差异后手工判 PASS。
- B 只验证 Trigger 创建与 conversation 活动唯一性；即使支持表出现后续自动变化，也不能据此声称 6.19 或 6.20 已通过。

## 7. 当前 STOP

夹具与报告模板已完成；Human A/B/C 真机证据尚未回填。当前结论保持 `WAITING HUMAN / WORKBUDDY`，到此 STOP，不开始 6.19/6.20。
