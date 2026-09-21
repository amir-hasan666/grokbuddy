# Phase 3.5 Real GitHub Integration 报告

日期：2026-09-18。范围仅为真实签名 Webhook、正式 PR binding、`pull_request:synchronize` 到既有 Final Review `PENDING`，以及普通 PR Comment read/create/update 投影。未进入 Phase 4，未连接 Real Grok、ACP 或 WorkBuddy wake-up，未 merge/approve、未修改 `main`、未删除探针分支或改仓库设置。

## Preflight 与边界

- `GITHUB_WEBHOOK_SECRET`、`GITHUB_COMMENT_TOKEN`：仅检查存在性，均为 `PRESENT`；未读取、打印或写入值。
- listener：真实依赖为 `127.0.0.1:8788`，TCP 连接与系统监听表均通过；8787 只是 CLI 默认值，不是本次依赖。
- runtime：真实 ping Delivery 位于 `var/github-manual/hub.db`，因此本轮所有 Task、binding、event、review 与 projection 都继续使用该 runtime。
- 架构与冻结项：Hub DB 仍是唯一事实源；GitHub 只作签名事件入口与 Comment 投影。未改状态机、命令幂等、backup、provider_id、Source of Truth、MCP/HTTP/CLI 或 Webhook 实现。
- trigger：只有 `pull_request:synchronize` 推进 Final Review；`opened` 只记录为 `IGNORED`；`issue_comment` / `pull_request_review_comment` 仍拒绝。

## Gate 1：真实 Webhook → Hub — PASSED

| 证据 | 实际值 |
|---|---|
| repository | `amir-hasan666/grokbuddy`，id=`1372874264` |
| opened Delivery | `929ab5d0-b30f-11f1-99c4-1846cb67d08d` |
| opened 结果 | GitHub HTTP 202；Hub `github_events.status=IGNORED`；未创建 FINAL ReviewRequest |
| synchronize Delivery | `cc895670-b30f-11f1-83f9-d7e56d30cc53` |
| event/action | `pull_request` / `synchronize` |
| head revision | `8f5052118e940c8b0d3d0ead965186dd7f30c285` |
| Hub HTTP 结果 | HTTP 202；响应 `status=APPLIED`、`duplicate=false`、effect `status=PENDING` |
| Hub ingress | `GHE-3641d441-2c24-4b66-b18f-363b0750933a`，`github_events.status=APPLIED` |
| 签名结果 | GitHub Delivery 请求包含 `X-Hub-Signature-256`，应用验签后才返回 202；报告不保存签名摘要或 secret |

GitHub Delivery UI 同时显示 `Completed in 0.68 seconds` 与 `Response 202`。Cloudflare 只暴露 `/webhooks/github` 到 loopback listener；没有暴露 SQLite、MCP 或管理口。

## Gate 2：真实 Repo/PR → PENDING — PASSED

- 探针分支：`phase35-probe`，从 `main` 创建；未 force-push，未修改 `main`。
- 首个无功能提交：`bc7b1bc1fe53afbf75b95dd9133d7287fd76da5e`。
- PR：[#2](https://github.com/amir-hasan666/grokbuddy/pull/2)，保持 `Open`。
- 第二个同步提交：`8f5052118e940c8b0d3d0ead965186dd7f30c285`。
- 新验收 Task：`TASK-7db0acee-8d15-425c-91b6-86177a86e70e`；不是 Phase 2 WorkBuddy task。
- 正式 binding：`GHB-7a2144dbf57ea786b18122c180ed76e10b0f57e0f78f625ce94fdd8f804dccae`，repo id=`1372874264`，PR number=`2`。
- opened 到达后：Task=`SELF_TESTING`、`active_rr_id=null`、FINAL ReviewRequest count=`0`。
- synchronize receipt：`RR-c622e79d-48a4-43ca-98a4-c5e0af317b0a`，预分配 review id=`REV-11c3bf92-dc52-472a-8726-f4737bd19a23`，请求状态严格为 `PENDING`，Task=`FINAL_REVIEW_PENDING`。
- Webhook handler 没有运行 Reviewer/Mock job。随后才通过既有 Mock/Application 异步链路执行 `dispatch=SENT → mock=PASS → event=APPLIED`，请求转 `COMPLETED`，Task 转 `DONE`。

没有伪造 INSERT，也没有直接修改数据库推进业务状态。

## Gate 3：真实 Comment Transport — PASSED

`FileGitHubCommentTransport` 继续作为本地/CI/离线默认；真实投影显式使用 `GitHubHttpCommentTransport` 与环境 Token。

| 证据 | 实际值 |
|---|---|
| review id | `REV-11c3bf92-dc52-472a-8726-f4737bd19a23` |
| marker | `<!-- grokbuddy-final-review:REV-11c3bf92-dc52-472a-8726-f4737bd19a23 -->` |
| Hub pointer | `hub://phase35-real/tasks/TASK-7db0acee-8d15-425c-91b6-86177a86e70e/reviews/REV-11c3bf92-dc52-472a-8726-f4737bd19a23` |
| 第一次 `project-github-once` | `CREATED` |
| comment id | `5724651683` |
| comment URL | `https://github.com/amir-hasan666/grokbuddy/pull/2#issuecomment-5724651683` |
| 重复 `project-github-once` | `operation=null`；冻结的不可变 Review 已 `SENT`，不重复入队/CREATE |
| HTTP Port find→update | `UPDATED`；find/update/find 均返回 comment id `5724651683` |
| PR Comment 数 | 总数 `1`，marker 命中 `1`，没有第二条 GrokBuddy 评论 |

重复 CLI 投影的 no-op 是现有幂等契约，不能为了制造 UPDATE 改写 projection 状态。真实 UPDATE 通过同一个现有 `GitHubHttpCommentTransport` Port 执行 `find_comment → update_comment`，正文仍取 Hub 已冻结的 `desired_body`；未改库、未加后门、未改 CLI/幂等语义。

Comment 更新后，正式读接口仍返回 Task=`DONE`、RR=`COMPLETED`、effective verdict=`PASS`。因此 GitHub Comment 不是事实源，Hub 状态不由 Comment 内容或更新时间驱动。

## Gate 4：错误分类与安全重试 — PASSED（本轮约定为离线分类）

用户明确规定本次续跑不破坏当前 Token 制造真实错误响应；下列分类继续以已有受控离线测试为验收证据：

| HTTP/故障 | 内部分类 | retryable | 结果 |
|---|---|---:|---|
| 401 | `AUTH_FAILED` | false | 第一次即 `FAILED` |
| 403 非限流 | `PERMISSION_DENIED` | false | 第一次即 `FAILED` |
| 403/429 限流 | `RATE_LIMITED` | true | `RETRY`，达到上限后 `FAILED` |
| timeout | `TIMEOUT` | true | `RETRY`，重试前重新 find marker |
| 5xx | `SERVICE_UNAVAILABLE` | true | `RETRY`，达到上限后 `FAILED` |

安全 metadata 只保留白名单 HTTP status、retryability、Retry-After/reset/remaining/resource/request-id；Token、Authorization、Webhook Secret 和响应 body 不写入日志、Audit 或报告。投影失败不回滚已完成的 Hub Review。

## Token 与最小能力

- 类型：Human 注入的 GitHub PAT；GitHub 响应不返回 `X-OAuth-Scopes`，因此无法仅凭 API 响应判定 classic/fine-grained 子类型。
- 真实验证能力：repository metadata read；普通 PR/Issue Comment list/create/update。
- `GITHUB_COMMENT_TOKEN` 对 Git contents push 实测返回 HTTP 403，故探针分支/commit/PR 使用已登录 GitHub UI 完成；没有修改、替换或扩大该 Token。
- 未输出 Token 值。

## 幂等与 Source of Truth

- delivery dedup、semantic dedup：Phase 3 本地 tests 继续通过；本次只补真实 PR 闭环，未使用 GitHub `Redeliver` 或第三个 commit 扩大已授权写操作。
- comment projection dedup：真实第一次 CREATE、重复 CLI no-op、同一 comment id 的真实 UPDATE；marker comment 始终只有一条。
- Hub 权威读结果：Task `DONE`、RR `COMPLETED`、Review `PASS`；Comment update 不改变这些状态。

## 回归与收尾

```powershell
.\.venv-phase0\Scripts\python.exe -m pytest tests\test_phase3_github.py -q --tb=short
.\.venv-phase0\Scripts\python.exe -m pytest -q --tb=short --junitxml=docs\phase35-tests.xml
.\.venv-phase0\Scripts\python.exe scripts\validate_phase0.py --allow-core
.\.venv-phase0\Scripts\python.exe -m pip check
```

- Phase 3 GitHub tests：`25 passed in 18.16s`。
- 全量 pytest：`473 passed in 100.10s`，0 failed，0 skipped；JUnit 已更新。
- contract validator：`171/171 passed`；其静态“external environment gate BLOCKED”提示不读取本次真实外部证据，本报告是 Phase 3.5 外部 Gate 记录。
- `pip check`：`No broken requirements found.`
- listener PID 40464 与 cloudflared PID 38540 经路径/命令行精确核对后已停止；`127.0.0.1:8788` 不再可连接。
- PR #2 与 `phase35-probe` 按要求保留；未 merge、approve 或删除分支。

## 最终 Gate

`PHASE3.5-REAL-GITHUB-EXIT: PASSED`

停止在 Phase 3.5，等待 Human 另行授权 Phase 4。
