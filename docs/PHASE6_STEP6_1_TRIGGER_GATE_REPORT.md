PHASE6-STEP6.1-TRIGGER-GATE: PASS（2026-09-21，Asia/Shanghai）

# Phase 6 Step 6.1 — Explicit Trigger Gate + Conversation Guard

## 结论与范围

本 Step 的 **本地工程合同及隔离 SQLite 夹具 PASS**：正式创建入口默认 fail closed；只有专用 WorkBuddy ingress principal 提交已签发、当前轮、可核对的用户消息，且其自然语言正文逐字包含 `启用grokbuddy流程`，Hub 才创建 Task。拒绝时 Task、Artifact、命令回执和 Audit 均无新增。Task 保存 conversation ID、消息 provenance、UTF-8 hash、匹配字节 span、签名和受控原文 Artifact 指针；同 conversation 非终态 Task 由事务内检查和 SQLite 唯一索引双重约束。终态后 Hub 查询出的 context 自动失效，新普通消息仍须重新过 trigger gate。

此 PASS 仅指 6.1 代码与本地测试。没有连接真实 WorkBuddy 消息来源、真实 Grok、GitHub 或生产 Hub DB；不代表 6.6、6.19、6.20 PASS。

## Goal → Preflight

按 [6.0 合同](PHASE6_STEP6_0_CONTRACT_REPORT.md) D1–D3、D12 与 [6.0a 合同](PHASE6_STEP6_0A_MANUAL_GLUE_SUPERVISOR_CONTRACT.md) §4 的 6.1 backlog 实施。预检确认：原 `TaskService.create_task` 和 `ClientGateway._create_task` 只接 description/profile/idempotency；`tasks` 原无 conversation/trigger 字段或活动 Task 唯一索引。现有状态机正式终态为 `DONE/CANCELLED/FAILED`。本 Step 不改 D7/D8 轮次与 Human Gate 合同。

拟增且已落地的输入为 `trigger_evidence`：已签发消息包含 `conversation_id`、不可变 `message_id`、`turn_id`、`message_role=user`、`principal_id`、`issued_at` 和带 `source/text` 的分段；证据另带原文 UTF-8 SHA-256、精确短语、UTF-8 byte start/end 和消息包 HMAC-SHA256。`description` 必须与签发消息的完整分段原文一致。时间允许过去 300 秒、未来 30 秒；缺少密钥或可信分段即拒绝。签名密钥由 `GROKBUDDY_TRIGGER_SOURCE_KEY` 或显式运行时参数提供，至少 32 字节，不写入源码、Task、Audit 或报告。

## 最小实现与关键路径

| 位置 | 行为 |
| --- | --- |
| `src/grokbuddy/application/trigger.py` | 验签、核对当前用户角色/专用 principal、时间、原文 hash/description、精确 UTF-8 span；仅 `user_body` 顶层自然语言可匹配，排除 fenced/indented/inline code、Markdown 引用及 `code_block/quote/pasted_document/attachment/tool_output` 分段。 |
| `src/grokbuddy/application/tasks.py` | `create_task(..., trigger_evidence=None)` 在 Hub 内二次校验；事务中检测同 conversation 活动 Task 和旧消息重放；冻结证据及不可变消息 Artifact；`get_conversation_context` 只从 Hub 当前 Task state 推导。 |
| `src/grokbuddy/adapters/schema.sql` | SQLite JSON 表达式部分唯一索引：一个 conversation 至多一个非 `DONE/CANCELLED/FAILED` Task；`(conversation_id, trigger_message_id)` 永久唯一。现有 v3 JSON 表无需 6.2 大迁移。 |
| `src/grokbuddy/infrastructure/runtime.py` | 增 `workbuddy-ingress` 专用 Builder principal、可配置签名密钥；正式默认禁止无 evidence 创建。旧本地 fixture 仅在显式 `legacy_create_test_mode=True` 下可创建无 trigger 的模拟 Task。 |
| `src/grokbuddy/interfaces/gateway.py`、`mcp.py` | 接收并传递 `trigger_evidence`；HTTP/CLI 仍走同一 Gateway/Hub 守卫。远程只读 MCP 未开放写入口。 |
| `src/grokbuddy/domain/model.py`、`application/common.py` | 稳定拒绝码 `TRIGGER_EVIDENCE_REQUIRED`、`TRIGGER_EVIDENCE_INVALID`、`TRIGGER_NOT_FOUND`、`TRIGGER_SOURCE_UNAVAILABLE`、`ACTIVE_CONVERSATION_TASK`；创建拒绝不写 rejection Audit。 |

签名只能由具备可信来源密钥的 ingress 签发。工具调用方传入 `enabled=true`、旧片段、伪签名、错 span、过期消息或非专用 principal 均不能替代该证据。幂等回放同一成功请求返回原 Task；换 key 重放同一 message ID 被拒绝。SQLite `BEGIN IMMEDIATE` 将应用层检查与插入串行化，唯一索引再兜底。

## 用例与证据

| 用例 | 隔离夹具与断言 | 结果 |
| --- | --- | --- |
| A 无触发词 | 缺 evidence 返回 `TRIGGER_EVIDENCE_REQUIRED`；已签发普通消息返回 `TRIGGER_NOT_FOUND`；Task/Artifact/回执/Audit 计数不变。 | PASS |
| B 精确触发词 + 合格 evidence | 签发用户正文可建一个 `NEW` Task；byte span、消息 ID、source hash/Artifact 持久化；同 key 回放无第二 Task，重启可查。 | PASS |
| C 终态后普通消息 | 分别将隔离 Task 置 `DONE/CANCELLED/FAILED`；Hub context 为 disabled/无 task_id；同 conversation 普通消息不建；旧消息不能重放；新一轮显式触发可建新 Task。 | PASS |
| D 同 conversation 活动 Task | 第二个有效触发在应用层返回 `ACTIVE_CONVERSATION_TASK` 且无 mutation；直接 repository 插入被 SQLite 唯一索引拒绝；两线程并发仅一个创建成功。 | PASS |
| E 排除文本 | 代码围栏、Markdown 引用、inline code、`pasted_document` 与 `tool_output` 中单独出现短语均返回 `TRIGGER_NOT_FOUND` 且无 mutation。 | PASS |
| 附加边界 | 伪签名、错 offset、旧时间、错误 principal、未配密钥均 fail closed；相邻 `user_body` 分段内的完整短语可匹配。 | PASS |

## 命令、结果与文件

- `python -m compileall -q src/grokbuddy`：PASS。
- `.\.venv\Scripts\python.exe -m pytest -q tests/test_phase6_trigger_gate.py`：14 passed。
- `.\.venv\Scripts\python.exe -m pytest -q tests/test_phase6_trigger_gate.py tests/test_phase2_interfaces.py`：24 passed。
- `.\.venv\Scripts\python.exe -m pytest -q`：503 passed in 97.37s。首次全量运行有 1 个 stdio 子进程测试未传入隔离签名密钥而 fail closed；补上显式环境传递后单项与全量均通过。
- `git -c safe.directory=D:/Codex/grokbuddy/var/phase35-repo -C var/phase35-repo status --porcelain=v1`：空输出。项目根不是 Git checkout；嵌套探针 checkout 未修改。

改动清单：`src/grokbuddy/{application/{trigger,tasks,common}.py,adapters/schema.sql,domain/model.py,infrastructure/runtime.py,interfaces/{gateway,mcp}.py}`；新增 `tests/test_phase6_trigger_gate.py`；旧本地夹具与入口回归仅在 `tests/{conftest,test_additional_boundaries,test_persistence_artifacts,test_workers,test_phase2_interfaces}.py` 显式启用测试模式或提供隔离签名消息。测试依赖装在被 `.gitignore` 忽略的本地 `.venv`。

## 已知限制与后续对齐

- 本地夹具验证的是签名消息包与 Hub 守卫；真实 WorkBuddy 是否提供不可变消息 ID、当前轮 ID、可信正文/粘贴文档分段，以及由独立受控 ingress 安全签发，**ENVIRONMENT_VALIDATION_REQUIRED**。若不能提供可信分段，创建保持 fail closed。纯文本粘贴与用户自写普通正文的区分依赖该可信 provenance；本 Step 不从自然语言猜测来源。
- `workbuddy-ingress` 在当前本地运行时是固定模拟 principal，HMAC 密钥验证是创建授权条件。真实账号/密钥分发、轮换和当前 WorkBuddy 配置尚未验收；本地 CLI/stdio 测试不代表生产认证链路已通过。
- 旧 Phase 2/5 fixture 的 `legacy_create_test_mode=True` 仅供显式本地模拟，正式默认关闭。6.2 的 v2 Gate/revision/worker schema 与历史迁移、6.6 supervisor、Named Tunnel、自动 Reviewer intake、真实 6.20 E2E 均未实施。
- 本轮没有更改真实生产业务 Task 数据、`main`、探针分支、D7/D8 状态机或轮次逻辑；没有运行 Grok/GitHub 外部调用、Named Tunnel 或 6.20 真 E2E。到 6.1 报告与测试结束即 STOP，等待 Human/指导审阅。
