PHASE6-MCP-SUBMIT-PLAN-SCOPE-FIX: LOCAL PASS / WAITING HUMAN MCP RELOAD

# Phase 6 MCP `submit_plan` approved scope hotfix

日期：2026-09-22

## 1. 范围与结论

本步只修复 `grokbuddy-hub` MCP 的 `submit_plan` 输入合同和转发缺口。没有修改 v2 scope 业务校验、ingress allowlist、`owner_id`、状态机、Reviewer 路由或生产默认；没有调用真实 WorkBuddy、Grok、GitHub，也没有运行 `LocalRuntime.run_until_idle` 作为现场证据。

仓内实现和隔离回归为 **LOCAL PASS**。WorkBuddy 尚未完全重开并重载更新后的 Hub MCP schema，现场 Task 也尚未由 Human 重试，因此当前结论只能是 **WAITING HUMAN MCP RELOAD**，明确不等于 6.20 PASS。

## 2. 根因与修复

修复前，`src/grokbuddy/interfaces/mcp.py` 的 `submit_plan` 只声明并转发 `task_id`、`plan_artifact_id`、`expected_version`、`idempotency_key`。Gateway/Hub 对 ingress-owned v2 Task 已要求非空 structured `approved_scope`，因此正式 MCP 无法满足 Application 合同；直接调用 `ClientGateway.invoke` 的测试绕过了该工具 schema 缺口。

修复后：

- MCP `submit_plan` 必填 `approved_scope`，只声明既有 `summary`、`files`、`components` 字段，空对象拒绝。
- MCP 将结构化 scope 转为普通对象并原样转发给 `ClientGateway → Hub.submit_plan`；Hub 的 `_validated_scope` 继续执行最终业务校验，没有放宽。
- `submit_plan` 顶层和 `approved_scope` 内部均拒绝未知字段，避免 MCP SDK 静默丢弃输入。
- 文档明确 Plan Artifact 的 `artifact_type` 使用大写 `PLAN`，并给出包含 `approved_scope` 的 MCP 示例。

## 3. MCP 层回归覆盖

新增/更新的 MCP Client 路径覆盖：

1. `tools/list` 中 `submit_plan` schema 将 `approved_scope` 标为 required，并发布非空 structured object 形态。
2. ingress 创建的 v2 Task 由正式 `grokbuddy-hub` MCP `submit_plan` 成功挂 Plan，`owner_id` 继续保持 `workbuddy-ingress`。
3. 缺省 scope、空 scope、scope 内未知字段、顶层未知字段均拒绝，且拒绝前 Task 保持未变。
4. 复现修复前 Gateway 已把 Task 推入 `PLANNING`、随后因缺 scope 失败的现场形态；更新后的 MCP 用**同一 idempotency key**补入 scope 后成功，精确重放只产生一次 `PLAN_SUBMITTED` Audit。

## 4. 本地验证

| 命令 / 检查 | 结果 | 证据边界 |
| --- | --- | --- |
| `.\.venv-phase0\Scripts\python.exe -m pytest tests/test_phase6_ingress_builder_drive.py tests/test_phase2_interfaces.py -q` | `15 passed in 16.63s` | MCP/Gateway 隔离路径；无真实 WorkBuddy |
| `.\.venv-phase0\Scripts\python.exe -m pytest -q` | `800 passed in 184.21s` | 仓库全量本地回归；无外部 E2E |
| `.\.venv-phase0\Scripts\python.exe -m compileall -q src\grokbuddy tests\test_phase2_interfaces.py tests\test_phase6_ingress_builder_drive.py` | PASS | 语法/bytecode 编译 |
| `.\.venv-phase0\Scripts\python.exe scripts\validate_phase0.py --allow-core` | `219/219 passed`；`External environment gate: BLOCKED` | 实现阶段合同检查；不证明真实 MCP 重载 |
| `git diff --check` | PASS | 仅既有 LF→CRLF 提示；无 whitespace error |

## 5. Human 必须执行的现场步骤

1. **完全退出并重新打开 WorkBuddy**，确保 `grokbuddy-hub` stdio 子进程和缓存的 tool schema 都已重载；仅在原窗口继续对话不足以证明重载。
2. 不新建 Task。目标仍是 `TASK-702a9f15-b1a7-4a2c-a5ef-0c1a12d2a5bd`，使用已有 Plan Artifact `ART-ddc48514-1a79-4857-8cd8-946715ba7da0`。
3. 对原 `submit_plan` 请求保持同一 `task_id`、`plan_artifact_id`、`expected_version` 和**同一 `idempotency_key`**，只补入非空 `approved_scope` 后重试。不要生成新的 key；不要因本次失败新建 Task，除非 Human 另行明确指示。
4. 现场成功与否必须以 WorkBuddy MCP 返回、Hub Task/command receipt/Audit 的真实结果为准。该证据产生前继续保持 `WAITING HUMAN MCP RELOAD + RETRY`，禁止宣称 6.20 PASS。

## 6. 改动文件

- `src/grokbuddy/interfaces/mcp.py`
- `tests/test_phase2_interfaces.py`
- `tests/test_phase6_ingress_builder_drive.py`
- `docs/WORKBUDDY_INTEGRATION.md`
- `docs/PHASE6_MCP_SUBMIT_PLAN_SCOPE_FIX_REPORT.md`

STOP：仓内热修与 LOCAL PASS 报告完成；等待 Human 完全重开 WorkBuddy 并按上述约束重试，不进入后续现场步骤。
