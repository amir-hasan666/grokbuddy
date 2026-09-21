# Phase 4 Grok Adapter 与审计写回证据报告

日期：2026-09-20（Asia/Shanghai）。本轮按 Human 的“真 Grok Adapter + 审计写回”授权实施，但**没有真实 Grok 执行**。上轮 [Functional Exit 报告](PHASE4_FUNCTIONAL_EXIT_EVIDENCE_REPORT.md) 保留为历史检查点；本报告记录新增代码和现有 Hub 的正式状态变更。

## 方案与边界

官方 [Grok Bot Routine 文档](https://docs.x.ai/grok-bot/skills-routines-and-automations)说明 schedule 和在账号支持时的 event trigger，GitHub event integration 与普通 plugin 分离；未给出本项目可直接调用的 Bot submit/status REST API。因此新增 `GrokBotReviewerAdapter` 使用已有普通 GitHub PR Comment 作为短请求指针载体：`submit_review_request` 创建唯一 marker，`get_delivery_status` 读取并逐字核对冻结请求 Comment，`normalize_review_event` 严格检查已认证 B 的事件字段和 agent/server/run identity。这里的 `status` 仅是**请求载体状态**，不是 Grok Bot run/status API；Comment `ACCEPTED` 不是 Bot 执行或 verdict。

结果通过**独立 Bearer 凭据**保护的 `/reviewer/requests/<RR>`、`/reviewer/requests/<RR>/artifacts/<ART>` 和 `POST /reviewer/events`。读取只允许当前 B 的冻结 request/profile/input/context；写回先经 B token、路由和 RR/Review 身份核对，持久化 inbox，再由既有 EventService 独立处理 schema、冻结字段、deadline、Finding、状态及 Audit。原 `/mcp` 保持 5 个只读工具，原 GitHub webhook 行为不变。B token 不存在时 Reviewer 路由不开启。

`workbuddy审核员` 的 agentId `4335c388-584c-434e-b14e-13964b176b6e`、serverId `3504754` 来自 Human 本轮输入；正式注册为 `grok-reviewer-b` / `grok-bot:3504754:4335c388-584c-434e-b14e-13964b176b6e`。这证明 Hub 有明确映射，**尚不证明当前 Grok Bot 账号与 Builder A 在平台层独立**。实际 Bot run ID 只能由下一轮真实运行和专用 token 认证后记录；测试夹具的 `offline-test-run-1` 不是实际执行。

## 实现清单

| 文件 | 变更 |
|---|---|
| `src/grokbuddy/adapters/grok_bot.py` | 非 Mock 的 GitHub Comment 请求载体、状态对账、事件归一化；不产生 ReviewResult |
| `src/grokbuddy/application/grok_routing.py` | B actor 注册、未来请求路由、受限 Artifact 读取、入站路由核对、Human resume 后新 Final RR 编排 |
| `src/grokbuddy/interfaces/grok_reviewer.py` | 专用认证读/写 HTTP 面；限长、401/403、durable inbox receipt |
| `src/grokbuddy/interfaces/composite.py`、`scripts/grokbuddy_composite.py` | 可选 `/reviewer/*` 路由；缺专用 Secret fail closed，原 MCP/Webhook 共存 |
| `src/grokbuddy/application/workers.py`、`src/grokbuddy/infrastructure/runtime.py` | Worker 按冻结 Reviewer actor 过滤；Mock 与 B 不互相领取 |
| `src/grokbuddy/application/github.py` | 新 GitHub synchronize 只对未来 RR 读取不可变 B route；旧 binding/RR 不改 |
| `src/grokbuddy/application/events.py`、`src/grokbuddy/domain/model.py` | token 认证来源的 execution identity 随 inbox、Review、Audit 留存；correlation 和 run 重放冲突校验 |
| `src/grokbuddy/adapters/schema.sql`、`src/grokbuddy/adapters/sqlite.py` | 加法 schema v3，新增不可变 `grok_reviewer_routes`；旧表结构/backup 方法保持 |
| `scripts/grokbuddy_grok.py` | 显式注册、路由、一次性 dispatch/event/timeout、Human retry Final CLI |
| `tests/test_phase4_grok_adapter.py` | 离线恢复、隔离、认证、Artifact scope、回写、冲突、replay、本地 projection |
| `.env.example` | 仅新增空的专用 Reviewer token 名称；不读取 `.env`，不保存 Secret |

## 现有 Hub 断点与未脏写证明

正式操作前以 SQLite backup API 保存 `var/phase4-grok-preflight-20260920T062350Z/hub.db`（SHA-256 `f3a6bb75bad2ab55de94a03e51b5b3c3bf1ca929067dd4cf51f4d5cba425ef`）及 15 个 Artifact 文件。随后仅调用 `register-reviewer`、`route-task`、`timeout-once` 三项正式 CLI；没有直接 DB DML、Mock worker 或 Grok 请求投递。

前后以 `mode=ro` 比较：schema `2→3`；旧 RR envelope 逐字段相等，SHA-256 `94ab7db7537e6ea3831fadb082a469177347959938b0fbdbfc5b5a893ccedd22`。旧 RR 仅 `status PENDING→TIMED_OUT`、`failure_code=REVIEW_TIMEOUT` 和 `completed_at` 新增；旧 outbox `READY→CANCELLED`；Task `FINAL_REVIEW_PENDING→ESCALATED`、version `8→9`、active RR 清空。新增 B actor 1 行、未来路由 1 行、Audit 4 行；旧 `reviews`、`inbox_events`、`mock_jobs` 均无增量。Audit 明确记录 `GROK_REVIEWER_REGISTERED`、`GROK_REVIEWER_ROUTE_CREATED`、`REVIEW_TIMED_OUT` 与状态变化。旧 RR 没有被写成 Grok `COMPLETED`。

现有 Task `TASK-50157391-c538-4725-aa56-e607d279c4a3` 处于 `ESCALATED`、version 9。新 RR **尚未创建**：专用 `GROKBUDDY_GROK_REVIEWER_TOKEN` 在 Process/User/Machine 环境均缺失，Bot 账号实际通知/回传能力亦未实测；现在开新 30 分钟 RR 会再次耗尽期限。下一轮依 [试跑 runbook](PHASE4_GROK_RUNBOOK.md)先完成 Secret 和 Bot preflight，再以 Human 明确的新 deadline/reason 调用 `retry-final`。

GitHub 只读复核 [PR #4](https://github.com/amir-hasan666/grokbuddy/pull/4) 于本轮仍为 `open`、`merged=false`、head=`phase4-step6-probe`、base=`main`，1 个 commit、1 个 changed file；没有重建 Step 6 或写入 PR。

## 验证与 Exit 状态

| Gate | 结果 |
|---|---|
| 既有 worker/GitHub/Remote MCP 回归 | 48 passed（新实现初始接线后） |
| 新 Grok Adapter、B route、旧 RR 保留、认证写回、Replay、本地 Comment projection | 4 passed；全部为离线合成夹具 |
| 全量 pytest | 485 passed in 111.80s；见本轮命令输出 |
| 身份/worker/事件专项复核 | 44 passed；最终 Adapter/Event 复核 23 passed in 18.46s |
| 协议 validator | 171/171 passed；外部 Gate 仍报告 no live integrations |
| `pip check` | No broken requirements found |
| 当前账号真实 Grok run、独立 B provider、专用 token、真实 GitHub Comment wake-up、真实回传与公网安全 | **NOT RUN / UNVERIFIED** |

本轮结论：**PHASE4-GROK-ADAPTER-LOCAL: PASS；PHASE4-FUNCTIONAL-EXIT: NOT PASSED。** 缺少专用 Secret 和当前账号真 Grok 试跑证据；不能把代码接线、本地合成结果或 GitHub Comment transport `SENT` 宣称为真实 Grok execution。
