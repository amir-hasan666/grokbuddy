# Phase 5 WorkBuddy Worker 上传开工包（2026-09-20）

## 结论与范围

`PHASE5-WORKBUDDY-UPLOAD-READY: PASS`（本机接入就绪）。WorkBuddy 用户配置已追加独立 `grokbuddy-worker`，并由官方 MCP SDK 按该实际配置启动 stdio 子进程，完成 `tools/list`、`list_available_tasks`、`get_task`。领取、上传和进度报告只在隔离测试库调用；真实 Probe 保持未领取。WorkBuddy 桌面 UI 的首次工具调用留给 Worker 本人，本报告不把 SDK 验证说成桌面 UI 验证。

本轮目标仅为 Worker 领取与上传就绪。没有运行 Phase 5 八个 Demo，没有启动 Mock/真实 Reviewer、Grok、Final Review 或 GitHub Comment/PR 写入。

## Readiness / MCP 面

| 项目 | 本次核对 |
|---|---|
| WorkBuddy 用户配置 | `C:\Users\22241\.workbuddy\mcp.json`，追加 server `grokbuddy-worker`；原 `grokbuddy-hub` 条目逐项保持原值 |
| 备份 | `C:\Users\22241\.workbuddy\mcp.json.backup-phase5-20260920-161815` |
| transport | 本机 `stdio`，不使用 Phase 4 公网 `/mcp`（其 5 个工具继续只读） |
| command | `D:\Codex\grokbuddy\.venv-phase0\Scripts\python.exe` |
| args | `D:\Codex\grokbuddy\scripts\grokbuddy_worker_mcp.py --runtime-dir D:\Codex\grokbuddy\var\workbuddy-mcp --contracts-dir D:\Codex\grokbuddy\docs\contracts` |
| cwd | `D:\Codex\grokbuddy`；入口脚本也主动切到该目录，路径均为绝对路径 |
| 环境变量名 | `PYTHONUTF8`；无 token/secret 传给本地 Worker server |
| 身份 | `workbuddy-worker`，本地 BUILDER 类 Worker actor，`worker_type=workbuddy`；与 Reviewer B `workbuddy审核员` 分离 |
| SoT | `D:\Codex\grokbuddy\var\workbuddy-mcp\hub.db` 与同目录 `artifacts`；Artifact 经既有 hash/不可变存储 |

实际 `tools/list` 返回：`list_available_tasks`、`get_task`、`claim_task`、`submit_artifact`、`report_progress`。协议协商 `2025-11-25`。只读发现记录：[phase5-worker-discovery.json](phase5-worker-discovery.json)。本机 SDK 使用的正是上述用户配置；WorkBuddy 随附 CLI 的独立 `mcp list` 不读取该桌面配置，因此其输出没有被当作桌面工具发现证据。

`submit_artifact` 是正式上传入口：接收文件的 UTF-8 文本内容，而非文件路径；通过 `ClientGateway → TaskService.submit_artifact → FileArtifactStore` 保存，并返回 Artifact ID、SHA-256、受控 pointer。Worker actor 领取之前不能上传；`claim_task` 以 Task version 做原子领取，更新 owner 与独立 `worker_status`，留下 Audit。`report_progress` 记录短进度，不改变既有 Task 状态机，也不请求 Review。原 11-tool `grokbuddy-hub` stdio MCP 和 Phase 4 5-tool 远程只读 MCP 未扩展。

## 唯一 Probe Task

- 幂等标识：`phase5-workbuddy-upload-probe`。
- Task ID：`TASK-1c7dc9a4-0d88-46d6-b9a4-c7f7068447a7`。
- 正式路径：`ClientGateway.create_task` → `TaskService.create_task`，随后 `WorkerTaskService.offer_task`；使用固定幂等键。重跑前以只读方式扫描所有本地 Hub runtime 的原始 Task Artifact，没有同名 Probe。
- 当前：`state=NEW`、`worker_status=OFFERED`、`version=1`、`owner_id=builder`、`worker_claimed_by=null`；唯一待领列表中恰有此 Task。期限为 2026-09-27 16:22:14（Asia/Shanghai）。
- 最终只读核对：[phase5-probe-final-state.json](phase5-probe-final-state.json)：全本地 runtime 仅 1 个同名 Probe；此 Task 只有创建时的 `SOURCE_FILE` Artifact，0 个 Review Request，Audit 仅 `ARTIFACT_CREATED`、`TASK_CREATED`、`TASK_OFFERED`；旧 MCP 配置条目逐项未变。
- 原始指令：WorkBuddy 领取后创建 `D:\Codex\grokbuddy\var\workbuddy-mcp\PHASE5_UPLOAD_PROBE.md`，内容恰为一行 `Phase 5 WorkBuddy upload probe.` 加换行；通过 `submit_artifact` 上传为 `EVIDENCE` / `text/markdown`，随后报告简短进度。不要请求 Review 或执行外部动作。
- 未建 Phase 5 branch/PR；`var/phase35-repo` 的现有分支仍为 `phase4-step6-probe`，没有修改 `main`。当前机器没有 `gh` 可执行文件，未取得远端同名 PR 列表；本轮也不需要创建 PR。

## WorkBuddy 开干复制区

把下面内容交给 **WorkBuddy Worker**。使用本机用户配置中的 `grokbuddy-worker` MCP server，勿使用 `workbuddy审核员` 或远程只读 `grokbuddy-hub`。若新 server 尚未出现在 WorkBuddy 的 MCP 列表，刷新 MCP 配置或重启 WorkBuddy 后再继续；确认工具名与下方一致。

1. 调用 `grokbuddy-worker.list_available_tasks`，参数 `{}`；找到 `TASK-1c7dc9a4-0d88-46d6-b9a4-c7f7068447a7`。
2. 调用 `grokbuddy-worker.get_task`，参数 `{"task_id":"TASK-1c7dc9a4-0d88-46d6-b9a4-c7f7068447a7"}`；核对原始指令和最新 `task.version`。目前版本是 `1`，若实际返回不同，以当前返回值为准。
3. **先领取**：调用 `grokbuddy-worker.claim_task`，参数 `{"task_id":"TASK-1c7dc9a4-0d88-46d6-b9a4-c7f7068447a7","expected_version":1,"idempotency_key":"phase5-workbuddy-upload-probe:claim-v1"}`。检查返回 `worker_status=CLAIMED`、`owner_id=workbuddy-worker`；网络不明时用完全相同参数重试。若版本已变化，先 `get_task` 核对是否已经领取；仍为 `OFFERED` 时，以新版本和对应新 key 领取。
4. 创建 `D:\Codex\grokbuddy\var\workbuddy-mcp\PHASE5_UPLOAD_PROBE.md`。UTF-8 内容为 `Phase 5 WorkBuddy upload probe.`，末尾一个换行。读取文件内容后调用 `grokbuddy-worker.submit_artifact`：

   ```json
   {
     "task_id": "TASK-1c7dc9a4-0d88-46d6-b9a4-c7f7068447a7",
     "artifact_type": "EVIDENCE",
     "idempotency_key": "phase5-workbuddy-upload-probe:upload-v1",
     "content_text": "Phase 5 WorkBuddy upload probe.\n",
     "mime_type": "text/markdown"
   }
   ```

   保存返回的 `id`、`sha256`、`storage_pointer`；同一次重试复用同一 idempotency key 和完全相同内容。
5. 可调用 `grokbuddy-worker.report_progress`，参数 `{"task_id":"TASK-1c7dc9a4-0d88-46d6-b9a4-c7f7068447a7","summary":"PHASE5_UPLOAD_PROBE.md 已上传。","idempotency_key":"phase5-workbuddy-upload-probe:progress-v1"}`。把实际 Artifact ID 回报 Human 后停止；不调用 Final Review、Grok 或 GitHub 写工具。

## 源码、测试和证据边界

`SOURCE CHANGES: YES`。新增 `src/grokbuddy/application/worker_tasks.py`、`src/grokbuddy/interfaces/worker_mcp.py`、`scripts/grokbuddy_worker_mcp.py`、`tests/test_phase5_worker_mcp.py`；最小接线调整 `src/grokbuddy/infrastructure/runtime.py`，Worker actor 上传前的守卫调整 `src/grokbuddy/application/tasks.py`；新增本报告、`docs/phase5-worker-discovery.json` 与 `docs/phase5-probe-final-state.json`。用户级 `mcp.json` 仅追加 `grokbuddy-worker`，备份后验证旧条目值未变。

隔离 Worker 测试覆盖：待领过滤、Task 指令读取、领取前上传拒绝、原子领取和幂等重放、不同 key 的重复领取冲突、领取后 Artifact 字节/hash、短进度、无 Review Request，以及 stdio 协商和精确工具列表。`pytest tests/test_phase5_worker_mcp.py tests/test_phase2_interfaces.py tests/test_phase4_remote_mcp.py -q`：21 passed；最终 `pytest -q`：488 passed。实际 Probe 上仅发生创建、发布和只读发现，没有调用领取、上传或进度。

`WorkBuddy claimed: NO | Final RR: NO | Grok: NO | secrets: NO`。没有直接 SQL DML；没有 merge/approve/修改 main。WorkBuddy 桌面首次实际调用仍是下一步 Worker 行为；本机 SDK 的 `tools/list` 和隔离调用证明 server 协议与正式 Application 写路径可用，不证明桌面已经领取或上传。

STOPPED — READY FOR WORKBUDDY TO START FILE UPLOAD
