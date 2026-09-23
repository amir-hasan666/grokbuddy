PHASE6-STEP6.17-TRIGGER-ISOLATION: PASS

# Phase 6 Step 6.17 — Trigger Isolation Evidence

日期：2026-09-21（Asia/Shanghai）

## 1. 结论与边界

Human 已在 WorkBuddy 5.5.6 的同一 conversation 完成 A/B/C 真机验证：Case A 无触发词且 0 mutation；Case B4 经专用 ingress `create_triggered_task` 恰好创建一个带完整可信 `trigger_evidence` 的活动 GrokBuddy Task；该 Task 进入 `CANCELLED` 后，Case C 的普通消息保持所有 Hub 表 0 mutation、同 conversation 活动 Task 仍为 0。A、B、C 均为 **PASS**，因此 6.17 关闭。

6.17 只验证 D1–D3 的 Trigger Isolation：无精确触发词不创建、不 sticky；有合格触发词只创建一个带可信 `trigger_evidence` 的活动 GrokBuddy Task；B 的 Task 终态后，普通消息仍不触发。本步不是流程审核或完整任务闭环。

`6.17 PASS ≠ 6.19 ≠ 6.20`。本次仅把已冻结的 Human 真机非 Secret 证据写回报告；未启动 6.19/6.20，未修改 Trigger 合同、状态机或 Plan≤2 / Final≤3，未放宽 ingress/Hub 权限，未 dispatch RR，也未宣称完整 E2E。

## 2. 前置证据

- [Phase 6 Pack E 收尾报告](PHASE6_PACK_E_WRAP_REPORT.md) 已记录：`PHASE6-STEP6.8-NAMED-TUNNEL-PUBLICBASE: PASS`、`PHASE6-STEP6.9-AUTOSTART-OBSERVABILITY: PASS`、`PHASE6-PACK-E: PASS`，且明确 `Pack E PASS ≠ 6.17 ≠ 6.19 ≠ 6.20`。
- 2026-09-21 21:46（Asia/Shanghai）的准备阶段，本地 `/health`、`/ready`、`/` 实测为 200/200/404；同轮固定 PublicBase 探测未连通。该历史公网状态不改写 Pack E 的既有 Human PASS，也不是本机 stdio ingress 的 6.17 判定条件。
- Human 已完成 6.17 真机前置：worker 信任、Trigger Key Credential 配置、trigger skill 安装与 ingress 加载；`tools/list` 确认 ingress 只暴露 `create_triggered_task`。报告不读取、写入或记录 Credential/Secret/HMAC/签名值。

| 前置项 | 当次命令 / 证据 | 结果 |
| --- | --- | --- |
| Pack E | `docs/PHASE6_PACK_E_WRAP_REPORT.md` | PASS（既有 Human 重启验收） |
| Hub local health/ready/root | `curl.exe -4 --connect-timeout 2 --max-time 5 http://127.0.0.1:8788/{health,ready,/}`（逐项执行） | 200 `{"status":"ok"}` / 200 `database=ok` / 404 `not_found`；PASS（21:46） |
| 固定 PublicBase 准备阶段探测 | `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\Test-GrokBuddyRuntime.ps1` | exit 1；`curl: (7) Failed to connect to grokbuddy.amirhasan.top:443`；历史 `CURRENT PUBLIC ROUTE NOT VERIFIED`，不影响本机 stdio 6.17 证据 |
| Ingress + Human 配置 | worker 信任、Trigger Key Credential、trigger skill、ingress `tools/list` | PASS；ingress 仅 `create_triggered_task`，普通 Hub `create_task` 未获得 ingress 权限 |

## 3. Live database 与只读探针

6.17 真机正式证据读取的 live Hub DB 是：

`var/workbuddy-mcp/hub.db`

该路径仅是 6.17 历史 B4 通过 `--database var/workbuddy-mcp/hub.db` 取得的证据库；自 6.19 对齐起，正式 SoT 与后续正式验收均使用探针默认的 `var/github-manual/hub.db`，不改变本报告的 6.17 PASS。

探针 `scripts/windows/Test-GrokBuddyTriggerIsolation.py` 的 `snapshot` 默认库仍是 `var/github-manual/hub.db`，但该库不是本次真机库，只保留作历史/manual 路径。早期 B2 的假 FAIL 正是因未显式指定参数而拍到该错库。正式证据的每次 `snapshot` 都必须显式使用：

```powershell
--database .\var\workbuddy-mcp\hub.db
```

探针有两个命令：

- `snapshot`：在独立子进程中以 SQLite `mode=ro`、`query_only=ON` 读取 Hub；默认硬超时 10 秒。保存所有 Hub 业务表的行数、行哈希及必要的安全 Task 元数据，不保存消息正文、触发签名或 Secret。
- `compare`：只读取两个 JSON 快照。A/C/B′ 要求所有 Hub 表的 ID/内容哈希完全不变；B 要求恰好新增一个 Task、没有删除或改写既有 Task、新 Task 非终态且 `grokbuddy_enabled=true`、`trigger_evidence` 关键字段齐全、同 conversation 前 0 后 1 个活动 GrokBuddy Task。`compare` 不连接数据库，因此没有 `--database` 参数。

证据目录位于已忽略的 `var/` 下，不提交：

```powershell
$EvidenceDir = '.\var\evidence\phase6-step6.17'
$LiveHubDatabase = '.\var\workbuddy-mcp\hub.db'
$Probe = '.\.venv\Scripts\python.exe'
$Harness = '.\scripts\windows\Test-GrokBuddyTriggerIsolation.py'
```

每个输出文件默认不可覆盖；再次执行时应使用新的带时间戳文件名，保留既有原始证据。

## 4. 现场、根因与正式判定

历史现场与根因保留如下，不改变 B4 的正式 PASS 判定：

- 首次点火出现 `PERMISSION_FAILURE`，原因是代理误调普通 `grokbuddy-hub.create_task`。Hub fail closed 正确，普通 Builder 没有冒充 ingress。
- ingress 接线后的首次点火已经创建 `TASK-35bb7bb9…`，B3-live 可见；该 Task 后续为 `CANCELLED`。由于缺少 live DB 的 before 快照，B3 不作为正式 B 判定。
- B2 对默认 `var/github-manual/hub.db` 的 FAIL 是拍错库，不是点火失败。
- 正式 B 以同一 conversation、live DB 上的 B4 before/after/compare 为准。

## 5. Human + WorkBuddy 真机命令路径

Owner：**Human + WorkBuddy**。以下命令明确固定 live DB；A 已有既有 Human PASS，无需为 ingress 安装而重跑。B4/C 已按此路径完成，命令保留作审计与复现说明。

### Case A — 无触发词，0 mutation

```powershell
& $Probe $Harness snapshot --database $LiveHubDatabase --label A-before --output "$EvidenceDir\A-before.json"
# Human 在 WorkBuddy 发送：帮我写一句问候语，不要启用任何特殊流程。
& $Probe $Harness snapshot --database $LiveHubDatabase --label A-after --output "$EvidenceDir\A-after.json"
& $Probe $Harness compare --case A --before "$EvidenceDir\A-before.json" --after "$EvidenceDir\A-after.json" --output "$EvidenceDir\A-result.json"
```

正式判定：既有 Human 真机 `CASE A: PASS`；无触发词，0 mutation。

### Case B — 精确触发，新建 1 个活动 Task

```powershell
& $Probe $Harness snapshot --database $LiveHubDatabase --label B4-before --output "$EvidenceDir\B4-before.json"
# Human 在同一 WorkBuddy conversation 发送：启用grokbuddy流程，帮我列一个三步的今日待办提纲。
& $Probe $Harness snapshot --database $LiveHubDatabase --label B4-after --output "$EvidenceDir\B4-after.json"
& $Probe $Harness compare --case B --before "$EvidenceDir\B4-before.json" --after "$EvidenceDir\B4-after.json" --output "$EvidenceDir\B4-result.json"
```

正式判定：B4 `CASE B: PASS`；新 Task 为 `TASK-b7545afe-d72e-4506-8469-68f56f156d36`，conversation 为 `385323b6-f3a4-48cc-beae-f603da934817`。

### Case C — B 已终态后普通消息仍不 sticky

```powershell
& $Probe $Harness snapshot --database $LiveHubDatabase --label C-before --output "$EvidenceDir\C-before.json"
# Human 在同一 WorkBuddy conversation 发送：再写一句谢谢，普通回复即可。
& $Probe $Harness snapshot --database $LiveHubDatabase --label C-after --output "$EvidenceDir\C-after.json"
& $Probe $Harness compare --case C --task-id 'TASK-b7545afe-d72e-4506-8469-68f56f156d36' --before "$EvidenceDir\C-before.json" --after "$EvidenceDir\C-after.json" --output "$EvidenceDir\C-result.json"
```

正式判定：B4 Task 在 before/after 都为 `CANCELLED`；`CASE C: PASS`，所有 Hub 表 0 mutation，conversation 前后均无活动 GrokBuddy Task。

### 可选 Case B′ — 短语仅在代码围栏或 Markdown 引用

B′ 本次未运行，也不是关闭 6.17 的必需项。若以后执行，所有 `snapshot` 同样必须显式带 `--database $LiveHubDatabase`，不得使用默认库。

## 6. A/B/C 非 Secret 证据表

| Case | Human 消息 | before snapshot | after snapshot | compare / Task 证据 | 判定 |
| --- | --- | --- | --- | --- | --- |
| A | `帮我写一句问候语，不要启用任何特殊流程。` | 既有 Human 真机快照 | 既有 Human 真机快照 | `CASE A: PASS`；无触发词；0 mutation | **PASS** |
| B（首次，历史） | `启用grokbuddy流程，帮我列一个三步的今日待办提纲。` | Human 已运行 | 失败后已运行；0 mutation | 误调 `grokbuddy-hub.create_task`；`PERMISSION_FAILURE`；无 Task | BLOCKED（历史现场，已由 B4 取代） |
| B（B4，正式） | 同上；经 ingress `create_triggered_task` | `var/evidence/phase6-step6.17/B4-before.json`；`2026-09-21T23:48:16+08:00`；task_count=4；latest `TASK-35bb7bb9…`=`CANCELLED`；active_grokbuddy_task_count=1（其他会话残留，本会话活动=0） | `var/evidence/phase6-step6.17/B4-after.json`；`2026-09-21T23:48:58+08:00`；task_count=5；latest `TASK-b7545afe-d72e-4506-8469-68f56f156d36`=`NEW` | `var/evidence/phase6-step6.17/B4-result.json`；`CASE B: PASS`；`exactly_one_new_task=True`；`conversation_id=385323b6-f3a4-48cc-beae-f603da934817`；新 Task 非终态、GrokBuddy enabled、trigger evidence 完整；本会话 active 0→1；changed tables=`artifacts,audit_logs,command_receipts,tasks` | **PASS** |
| C | `再写一句谢谢，普通回复即可。` | `var/evidence/phase6-step6.17/C-before.json`；`2026-09-21T23:50:58+08:00`；B4 Task=`CANCELLED` | `var/evidence/phase6-step6.17/C-after.json`；`2026-09-21T23:51:30+08:00`；同态、task_count 不变 | `var/evidence/phase6-step6.17/C-result.json`；`CASE C: PASS`；`changed_tables=(none)`；所有 Hub 表不变；B Task 前后均终态；本会话 active 0→0 | **PASS** |
| B′（可选） | 触发短语仅在 fenced code 或 Markdown quote | 未运行 | 未运行 | 未运行 | NOT RUN（不影响 6.17） |

证据文件均位于 Git ignored 的 `var/evidence/phase6-step6.17/`；报告只引用路径与非 Secret 控制台字段，不收录 Credential、HMAC、签名或消息原文之外的敏感内容。

Human 控制台摘要：

```text
PHASE6-STEP6.17 CASE A: PASS
0 mutation

PHASE6-STEP6.17 CASE B: PASS
exactly_one_new_task=True
new_task_id=TASK-b7545afe-d72e-4506-8469-68f56f156d36
conversation_id=385323b6-f3a4-48cc-beae-f603da934817
new_task_nonterminal=True
grokbuddy_enabled=True
trigger_evidence_complete=True
conversation_active_before_zero=True
conversation_active_after_one=True
changed_tables=artifacts,audit_logs,command_receipts,tasks

PHASE6-STEP6.17 CASE C: PASS
changed_tables=(none)
all_hub_tables_unchanged=True
b_task_terminal_before=True
b_task_terminal_after=True
conversation_active_before_zero=True
conversation_active_after_zero=True
```

## 7. Ingress 接线、验证边界与已知限制

- `src/grokbuddy/interfaces/ingress_mcp.py` 与 `scripts/grokbuddy_ingress_mcp.py` 固定 `workbuddy-ingress`，只暴露 `create_triggered_task`；工具不接受 actor/signature/raw evidence。
- `scripts/windows/Start-GrokBuddyIngressMcp.ps1` 从 Windows Credential Manager 读取 Trigger Source Key，只注入子进程；`Start-GrokBuddyHub.ps1` 从同一 Target 注入 Hub。Key 少于 32 UTF-8 bytes 时 fail closed。Human 已完成 Credential、worker/ingress 信任、skill 与 tools/list 前置，但本报告不记录值。
- 普通 Hub/Worker、Remote MCP 五个只读工具和 6.1 双检没有放宽。首次 `PERMISSION_FAILURE` 证明普通 Hub create 仍 fail closed；B4 证明专用 ingress 真机路径可完成本步点火。
- `tests/test_trigger_isolation_harness.py` 只验证快照 diff 的 A/B/B′/C 判定和行内容变更检测；其既有 `5 passed` 不是 Human 真机 PASS 的替代。6.17 的最终结论来自上述 A/B4/C live DB 证据。
- ingress 聚焦测试与 6.1 trigger gate 的既有结果为 `23 passed`；Hub/Worker/Remote MCP 接口回归为 `46 passed`；当时完整测试为 `787 passed in 154.55s`。这些本地结果保留为实现证据，不冒充 6.19/6.20 或完整 E2E。
- WorkBuddy 自定义 MCP schema 仍没有已验证的 native immutable user-message ID 自动注入字段；6.17 只证明当前 skill/session/idempotency/provenance 路径在 Human B4/C 真机案例中满足 Trigger Isolation，不外推为平台级完整来源证明。
- 固定 PublicBase 在准备阶段的有界探测未连通；本机 stdio ingress 不经 Quick Tunnel/PublicBase，因此没有为关闭 6.17 修改 hostname 或把公网状态写成 PASS。
- SQLite 前后快照不能自动把并发的无关 Hub 变化归因给某条 WorkBuddy 消息。A/C 若未来复测出现变化，必须保留 diff、查清来源并在安静窗口重跑，不能删除差异后手工判 PASS。
- B 只验证 Trigger 创建与 conversation 活动唯一性；支持表变化不能据此声称 6.19 或 6.20 已通过。

## 8. STOP

Case A、B4、C 均 **PASS**，`PHASE6-STEP6.17-TRIGGER-ISOLATION: PASS`，6.17 到此关闭。**不启动 6.19/6.20，不宣称完整 E2E**；等待 Human/指导审阅。
