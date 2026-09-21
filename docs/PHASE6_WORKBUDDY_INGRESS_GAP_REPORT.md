PHASE6-WORKBUDDY-INGRESS-WIRING: LOCAL PASS / WAITING HUMAN RETEST

# Phase 6 — WorkBuddy Ingress Wiring Gap Report

日期：2026-09-21（Asia/Shanghai）
范围：仅解除 6.17-B 的 WorkBuddy 点火入口阻塞；不开始 6.20，不运行 Reviewer，不修改 Plan/Final 合同。

## 1. 结论先行

现场根因是入口身份错配，不是 6.1 守卫过严：WorkBuddy 5.5.6 调用了 `grokbuddy-hub.create_task`，该 server 固定为 `builder`，所以 Hub 对带 evidence 的请求正确返回 `PERMISSION_FAILURE: Dedicated WorkBuddy ingress principal required`；失败前后零 mutation 符合 fail-closed 合同。`grokbuddy-worker` 只负责 Worker 子生命周期，不能替代 ingress。

最小修复是在仓内新增第三个独立 stdio MCP：`grokbuddy-ingress`。它只暴露 `create_triggered_task`，进程固定绑定 `workbuddy-ingress`，在受控进程内签发 evidence，再经原 `ClientGateway → TaskService.create_task` 进入 Hub 二次校验。普通 Hub 的 `create_task`、Worker、远程 `/mcp` 均未获得新权限。

本地代码、MCP handshake、正反例和 stdio 子进程已经验证；WorkBuddy 用户配置、首次信任、真实消息 provenance 和 6.17-B/C 尚未由 Human 重跑，所以结论只能保持 `WAITING HUMAN RETEST`。

## 2. Preflight 差距表

| 面 | 当前入口 / 身份 | 可见能力 | 6.17-B 前差距 | 修复后状态 |
| --- | --- | --- | --- | --- |
| Application | `TaskService.create_task(actor_id, ..., trigger_evidence)` | 只有 actor 的 `trigger_source=workbuddy` 且 evidence 双检通过才建单 | 已有守卫，无签发方 | 不改守卫；新增受限签发适配。 |
| `grokbuddy-hub` stdio | 固定 `builder`；Human 工具另绑 `human` | 12 个 Builder/Human 工具，包含通用 `create_task` | actor 不是 ingress；WorkBuddy 调它必然被拒 | 保持拒绝，不作为点火路径。 |
| `grokbuddy-worker` stdio | 固定 `workbuddy-worker` | list/get/claim/upload/progress/complete | 无 create；首次信任与点火无关 | 不改；Human 仍按清单完成信任。 |
| Gateway / local HTTP fallback | 由进程启动参数固定 actor；local HTTP 无生产认证 | 可把 `trigger_evidence` 透传到 Application | 没有正式 WorkBuddy ingress 认证/签发接线 | 不对公网开放，不用于 6.17 真机。 |
| Remote MCP `/mcp` | Bearer `GROKBUDDY_MCP_TOKEN`，内部仍是 read-only Builder query | 5 个只读查询 | 没有 create，且不应扩大 | 保持只读。PublicBase 仍为 `https://grokbuddy.amirhasan.top`。 |
| WorkBuddy 5.5.6 connector | 用户配置现有 Hub + Worker；支持 stdio/sse/http、`command/args/env` | 可启动本地 MCP 并执行工具；首次连接有信任门 | 没有 `grokbuddy-ingress`，没有 Key，模型只能发现普通 `create_task` | 新增无 Secret 配置样例、Credential wrapper、单工具 server。 |
| WorkBuddy current-message metadata | 自定义 MCP schema 未声明 native user-message ID/provenance 注入；官方 Skills 支持运行时 `${CODEBUDDY_SESSION_ID}` | skill 可传当前 session ID 和当前消息文本/分段 | 无可信签发者；普通模型构造 evidence 不可信 | Skill 传 runtime session ID；未展开占位符 fail closed；message/turn ID 由 session + idempotency key 派生，evidence 在受控进程签发。真实 provenance 仍需 Human B 真机确认。 |

WorkBuddy transport/config 能力依据：本机 `WorkBuddy.exe` FileVersion 5.5.6、当前脱敏 `mcp.json` shape、腾讯 [WorkBuddy Enterprise MCP 使用文档](https://cloud.tencent.com/document/product/1831/137039)及 [Skills 变量占位符文档](https://cloud.tencent.com/document/product/1831/137020)。本报告没有读取或记录任何 Secret 值。

## 3. 最小 ingress 接线

| 文件 | 作用 |
| --- | --- |
| `src/grokbuddy/application/trigger.py` | 增加 `issue_trigger_evidence`；签发和既有 `verify_trigger` 共用结构/provenance 校验，Task 创建事务仍再次验签。 |
| `src/grokbuddy/interfaces/ingress_mcp.py` | 固定 principal `workbuddy-ingress`；只注册 `create_triggered_task`；不接受 actor、signature、description 或 raw evidence。 |
| `scripts/grokbuddy_ingress_mcp.py` | stdio Python 入口。 |
| `scripts/windows/Start-GrokBuddyIngressMcp.ps1` | 从 Windows Credential Manager 读取 Trigger Source Key，验证不少于 32 UTF-8 bytes，只注入 ingress 子进程。 |
| `scripts/windows/Start-GrokBuddyHub.ps1` | 从同一个 Credential Target 向 Hub Process 注入同名环境变量；不记录值/hash。 |
| `scripts/windows/Test-GrokBuddyCredentialStore.ps1` | 只输出 Target + `PRESENT`；新增 trigger key 的存在性/最小长度检查。 |

点火序列：

`WorkBuddy current turn → trigger skill 分段 → grokbuddy-ingress.create_triggered_task → connector 签发 HMAC evidence → ClientGateway(workbuddy-ingress) → TaskService 二次校验 → 原子建 Task/Artifact/Audit/receipt`

没有触发词、短语只在 code/quote/pasted source、Key 缺失/过短、错误 principal、签名或 span 不匹配时，Task/Artifact/receipt/Audit 均不新增。普通 `grokbuddy-hub.create_task` 仍不能冒充 ingress。

## 4. WorkBuddy 可执行物与 Secret 清单

- MCP 配置样例：[workbuddy-ingress-mcp.example.json](examples/workbuddy-ingress-mcp.example.json)。样例没有 Token/Key；Human 只合并新 server 条目，不覆盖现有 Hub/Worker。
- WorkBuddy skill：[grokbuddy-trigger-ingress/SKILL.md](workbuddy-skills/grokbuddy-trigger-ingress/SKILL.md)。它只白名单 ingress 点火工具，要求只看当前轮、精确短语、排除 code/quote/paste/attachment/tool output，把运行时 `${CODEBUDDY_SESSION_ID}` 原样送入，并禁止 fallback 到普通 `create_task`。
- Credential Target：`GrokBuddy/GROKBUDDY_TRIGGER_SOURCE_KEY`。
- Process environment：`GROKBUDDY_TRIGGER_SOURCE_KEY`，值不少于 32 UTF-8 bytes，Hub 与 ingress 必须相同。
- PublicBase：固定 `https://grokbuddy.amirhasan.top`；不得改用 Quick Tunnel。此本地 stdio ingress 不经 PublicBase。
- 禁止位置：Git、仓内 JSON、`mcp.json` 明文、命令参数、日志、报告、聊天。

## 5. 本地验证与证据边界

聚焦测试覆盖：

- ingress tools/list 精确只有 `create_triggered_task`；
- 精确短语创建一个 `NEW` Task，owner/evidence principal 均为 `workbuddy-ingress`；相同 idempotency key 重放同一 Task；
- 普通消息、fenced code、quote、pasted document 均返回 `TRIGGER_NOT_FOUND` 且零 mutation；
- 缺 Key 返回 `TRIGGER_SOURCE_UNAVAILABLE` 且零 mutation；
- 真 stdio 子进程 handshake/list/call/落库；
- 既有 6.1 触发、伪造、错误 principal、offset、时效和 conversation 唯一性回归继续通过。

这些都是本地/隔离证据。WorkBuddy 5.5.6 是否在目标 conversation 中实际展开 session placeholder、是否按 skill 传递真实分段、是否成功读取本机 Credential，仍是 `ENVIRONMENT_VALIDATION_REQUIRED`。

实际命令与结果：

- `python -m pytest -q tests/test_phase6_trigger_gate.py tests/test_phase6_workbuddy_ingress.py` → `23 passed`（含幂等键变化输入 `CONFLICT`、未展开 session placeholder 拒绝 / 零 mutation）。
- `python -m pytest -q tests/test_phase6_trigger_gate.py tests/test_phase6_workbuddy_ingress.py tests/test_phase2_interfaces.py tests/test_phase5_worker_mcp.py tests/test_phase4_remote_mcp.py` → `46 passed`。
- `python -m pytest -q` → `787 passed in 154.55s`。
- `python -m compileall -q src/grokbuddy scripts/grokbuddy_ingress_mcp.py`、三个 PowerShell 文件的 parser check、MCP example JSON parse、`git diff --check` → PASS。
- `.venv-phase0/Scripts/python.exe scripts/validate_phase0.py --allow-core` → `219/219 passed`；其 `External environment gate: BLOCKED` 是 checker 明示未运行 live integrations，不是本地合同失败。

未运行：真实 WorkBuddy tools/list/call、Credential Target 读取、Hub 重启、固定 PublicBase 当次探测、6.17-B/C、Grok/Reviewer/GitHub、6.20。

## 6. Human 重测前动作

1. WorkBuddy MCP 管理中对 `grokbuddy-worker` 点“信任”（若尚未）。
2. 在 Credential Manager 配置同一份 Trigger Source Key；运行 credential check；按既有运维 runbook 让 Hub 受控读取新 Target。
3. 合并 `grokbuddy-ingress` 配置、安装 trigger skill，刷新/重启 WorkBuddy，并完成新 server 的首次信任。
4. tools/list 确认 ingress 只有一个点火工具；不要调用普通 Hub `create_task`。
5. 在同一 WorkBuddy conversation 中按 6.17 报告重跑 `B-before → 发送精确触发消息 → B-after → compare B`。
6. B Task 进入正式终态后，再跑 C；保留所有原始非 Secret 摘要。

到 Human B→C 重测完成前，不得把本报告或 6.17 改成 PASS。
