# Phase 4 真 Grok 试跑 runbook（下一轮）

状态：**未试跑**。本文件只使用已实现的正式 Application、GitHub Comment 请求载体和独立认证的 `/reviewer/*` HTTP 面。GitHub Comment `ACCEPTED` 仅表示请求指针已投递，不能证明 Bot 被唤醒或执行。不得用 xAI inference API 冒充 Grok Bot。

## 1. Preflight 与 Human Gate

1. 在 Grok Bot 桌面客户端确认 `workbuddy审核员` 的 agentId=`4335c388-584c-434e-b14e-13964b176b6e`、serverId=`3504754`，核对该 Bot 对目标 PR 的实际权限及能否按单个 request 指针工作。确认当前账号的 PR Comment notification 或 Routine trigger；若不支持，使用明确的一次性 Bot 任务，不假定 Comment 自动唤醒。
2. 确认 Reviewer B 的实际账号/凭据与 Builder A 独立。Hub 中的 `grok-bot:3504754:4335c388-584c-434e-b14e-13964b176b6e` 目前是按 Human 给出的 ID 注册的映射，**尚非平台身份实测**。Bot 名称和自报 run ID 不能单独证明身份。
3. 安全配置专用 `GROKBUDDY_GROK_REVIEWER_TOKEN`，只提供给 Reviewer B 与本机 composite 服务；不得粘贴到聊天、PR、命令行或日志。它必须不同于 `GROKBUDDY_MCP_TOKEN` 和 `GITHUB_WEBHOOK_SECRET`。当前该 token 缺失，未启动写回面。
4. 核对 PR #4 仍 Open、head 为 `phase4-step6-probe`，并确认固定 PublicBase 为 `https://grokbuddy.amirhasan.top`、目标端口为 8788。正式路径只使用 Named Tunnel；禁止沿用历史 Quick Tunnel hostname。
5. Human 为恢复后的新审核给出未来 UTC deadline、Final round budget、恢复原因和稳定 idempotency key。旧 `RR-a5b8e603-58f9-46b6-a4f5-f6927fd18ec7` 已经 `TIMED_OUT`，绝不能把其结果改成 Grok 完成。

## 2. 启动独立写回面

在可读取上述 Secret 的受控进程环境中，先安全切换原 8788 webhook listener，再以固定 PublicBase 启动同端口 composite：

```powershell
$env:PUBLIC_BASE = 'https://grokbuddy.amirhasan.top'
.\.venv-phase0\Scripts\python.exe scripts\grokbuddy_composite.py `
  --runtime-dir var\github-manual `
  --host 127.0.0.1 --port 8788 `
  --public-base-url $env:PUBLIC_BASE `
  --grok-reviewer-actor grok-reviewer-b
```

复核 `/health=200`、原 `/webhooks/github` 可达、`/mcp` 仍仅 5 个只读工具；`/reviewer/*` 无/错 B token 为 401。只把 B token 经受控 Secret 注入到 Bot 环境，不写入请求 Comment。当前 Composite 不启用 B token 时 `/reviewer/*` 返回 404。

## 3. 作废后的新 RR

当前本地 Hub：Task `ESCALATED`、version `9`；旧 RR `TIMED_OUT`、旧 outbox `CANCELLED`；未来请求路由已绑定 B。确认这些值未变化后，用 Human 给出的实际 deadline/reason/key 调用一次：

```powershell
.\.venv-phase0\Scripts\python.exe scripts\grokbuddy_grok.py --runtime-dir var\github-manual retry-final `
  --task-id TASK-50157391-c538-4725-aa56-e607d279c4a3 `
  --old-request-id RR-a5b8e603-58f9-46b6-a4f5-f6927fd18ec7 `
  --expected-version 9 --new-limit 3 `
  --new-deadline-utc <FUTURE_UTC_ISO8601> `
  --reason <HUMAN_REASON> --key <STABLE_KEY>
```

`retry-final` 通过现有 `Human resume → Builder self_test → submit_final_package → request_review` Application 命令建立新 round；复用已冻结的测试 Artifact 并为新 content revision 生成新的 Final package。每一步有由同一个 key 派生的 command receipt，可在中断后用**完全相同的参数/key**重跑。只有确认旧测试证据仍适用于未改动的 probe 时才执行。输出必须是新 RR `PENDING`，其 `expected_reviewer_actor_id=grok-reviewer-b`；旧 RR 保持 `TIMED_OUT`。

## 4. 请求投递与真实执行

先确认 Reviewer B 能读取该新 RR 的 `/reviewer/requests/<NEW_RR>`、其 profile/input/context Artifact 和 SHA-256。再显式投递一次：

```powershell
.\.venv-phase0\Scripts\python.exe scripts\grokbuddy_grok.py --runtime-dir var\github-manual dispatch-once `
  --reviewer-actor-id grok-reviewer-b `
  --public-base-url $env:PUBLIC_BASE
```

该命令只领取 B 的 outbox，查询 PR Comment marker 后按需 CREATE 一条短请求指针；不会领取旧 Mock RR。`SENT` 证明 Comment 载体已接受。若为 `UNKNOWN`，先人工查 marker 和 GitHub 回执，**不得盲目重发**。若当前 Grok Bot 账号无法按 PR Comment 唤醒，Human 在 `workbuddy审核员` 中发起一次性真实任务，提供新 RR 指针与禁令；记录 Bot run 证据，不把手工转述当自动 trigger 通过。

Bot B 从受控 HTTPS endpoint 读取冻结材料，核对 SHA-256 和 Profile，执行独立审核。回传到 `POST /reviewer/events` 时使用专用 Bearer token；事件包含 `event_id`、`event_type`、`source=grok_bot`、Task/RR/Review/correlation ID、deduplication key、真实结果 `payload`，以及 `execution={agent_id,server_id,run_id}`。`run_id` 必须取自实际 Bot 运行记录；不能编造 ReviewResult 或手填 PASS。HTTP 202 仅是 durable inbox receipt。随后显式处理：

```powershell
.\.venv-phase0\Scripts\python.exe scripts\grokbuddy_grok.py --runtime-dir var\github-manual event-once
```

检查 inbox `APPLIED`、Review `execution_identity`、RR/Task 状态和 B 的 Audit；若 `REJECTED`、`LATE_EVENT` 或超时，停止，不覆盖旧结果。复送**相同原始事件**并再次 `event-once` 应是 `DUPLICATE`；改 run ID/结果却复用 dedup key 应拒绝。验证时保留原始 JSON 于受控 Artifact，不贴 PR Comment。

## 5. GitHub projection 与退出

仅在新 Final RR `COMPLETED` 后，使用现有正式投影命令：

```powershell
.\.venv-phase0\Scripts\python.exe scripts\grokbuddy_github.py --runtime-dir var\github-manual project-github-once `
  --review-request-id <NEW_RR>
```

只允许普通 PR Conversation Comment 的 marker、短摘要和 Hub pointer。重复执行后应保持同一 projection/comment ID，不得产生第二条 Final Review 评论。核对真实 Grok run、B 的 credential/provenance、Hub correlation、状态迁移、GitHub Comment、replay 和幂等的逐项证据后才能判定 Functional Exit；最后按测试窗口要求恢复原 webhook listener 或记录持续运行的受控服务。禁止 merge/approve/close PR、改 `main`、直接 DB DML 或启动 Mock worker 处理新 RR。
