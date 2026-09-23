LOCAL PASS / WAITING HUMAN RESTART+CONTINUE

# PHASE6 Reviewer Delivery Gap Report

日期：2026-09-22（Asia/Shanghai）  
范围：只诊断并修复无 GitHub PR / 尚未 binding 的正式 v2 Plan/Final Review 到 `grok-reviewer-b` 的投递缺口。未 push、未调用真实 Grok/WorkBuddy E2E、未修改生产 Hub 数据、未把 6.20 标为 PASS。

## 1. 结论

已选择并实现 **A + C 的最小合同级方案**：

- 正式 v2 Task 指定已注册 Grok Reviewer，且 `github_bindings` 与 `grok_reviewer_routes` **同时不存在**时，创建 RR 前冻结 `delivery_channel=REVIEWER_HTTP`。该 RR 不再等待不存在的 PR metadata。
- Dispatcher 只有先把同一 RR/hash 持久发布到 B 专属的 HTTP intake queue 后，才把 outbox 从 `READY/LEASED` 写为 `SENT`。发布成功但 Dispatcher 回写前崩溃时，下一轮按稳定 intake key 对账并复用，不能重复发布。
- `GET /reviewer/requests` 是 PublicBase 上由 B 专用 Bearer token 保护的待审索引；只返回当前 actor、当前 active RR、未冻结且未过期的 `READY/ACKED` 条目。B 再读单 RR/Artifact 并通过既有 `/reviewer/events` 回传。`SENT`、列表可见和 `ACKED` 都不是 Review verdict。
- 若 binding/route 只存在一半、多条或互不匹配，`request_plan_review` / `request_final_review` 在 RR、outbox、profile/context Artifact 创建前以 `REVIEW_DELIVERY_UNAVAILABLE` 显式失败。不会再创建必然无法 claim 的 `PENDING` 请求。
- binding+route 唯一且匹配时继续使用原 GitHub Comment carrier；历史 v1 routed RR 保持兼容。Local Mock 仍只用于隔离测试，不是生产默认或本修复的 fallback。

本地实现和回归为 **LOCAL PASS**。真实 B 是否已配置为持续轮询 PublicBase、Human 是否已重启正式 Hub、TASK-702 的 Continue、新 RR 的真实 `SENT→ACKED→APPLIED` 均未执行，因此状态是 **WAITING HUMAN RESTART+CONTINUE**，不是 6.20 PASS。

## 2. 只读现场与根因

2026-09-22 以 SQLite `mode=ro` 读取 `var/github-manual/hub.db`，现场与问题描述一致：

- Task `TASK-702a9f15-b1a7-4a2c-a5ef-0c1a12d2a5bd`：`PLAN_HUMAN_REVIEW`、version `4`、`active_rr_id=null`、`automation_frozen=true`、`gate_reason/escalation_reason=REVIEW_TIMEOUT`、协议 `v2`、owner 仍为 `workbuddy-ingress`。
- RR `RR-bebe1782-4a1d-4885-9b1c-9443b1f87a60`：Plan round 1、expected reviewer `grok-reviewer-b`、`TIMED_OUT`、`failure_code=REVIEW_TIMEOUT`。
- Outbox `OUT-fc803015-6ea3-4df8-ad51-4a15351ebe86`：`CANCELLED`、attempts `0`。
- 该 Task 的 `github_bindings=0`、`grok_reviewer_routes=0`。本轮没有对这些记录执行 DML。

生产构造链的只读结论：

1. `scripts/grokbuddy_composite.py` 从 service config 选择 B，构造 `GitHubHttpCommentTransport`、production dispatcher、HTTP intake 和常驻 Supervisor；`_binding_policy_without_fabrication()` 固定返回 `None`，不会猜 PR。
2. 修复前 `LocalRuntime.grok_dispatcher()` 的 eligibility 只接受唯一 binding + 唯一路由 + 二者匹配 B。`Dispatcher._claim()` 在 eligibility 失败时直接跳过，不增加 attempts、不写明确错误。
3. `ReviewService.request_review()` 已先原子创建 `PENDING` RR 与 `READY` outbox；所以无 binding/route 的请求永远没有 claim 机会，直到 `TimeoutService` 把 RR 写为 `TIMED_OUT`、Task 写入 Human Gate，并取消 outbox。
4. 因此本现场不能归因为“Grok 已收到但无响应”；实际是 **Hub 从未投递**。attempts `0` 是关键证据。

## 3. 修复合同与边界

### 3.1 创建 RR 前选择一次通道

通道选择只读取 Hub SoT，不读取 GitHub 标签、评论或自然语言：

| Reviewer / metadata | 冻结通道 | 结果 |
| --- | --- | --- |
| 非 Grok Reviewer（隔离测试） | `LOCAL_ADAPTER` | 保持既有 adapter 路径 |
| 正式 v2 + B + binding=0 + route=0 | `REVIEWER_HTTP` | 允许 PublicBase HTTP intake |
| 唯一 binding + 唯一路由且匹配 B | `GITHUB_COMMENT` | 保持既有 carrier |
| partial / duplicate / mismatch | 无 | `REVIEW_DELIVERY_UNAVAILABLE`，不创建 RR/outbox |

`delivery_channel` 写入 ReviewRequest、outbox 和 `REVIEW_REQUEST_CREATED` Audit；Reviewer 请求 envelope/schema 未被悄悄扩字段。新逻辑不修改 trigger guard、Task owner、round 规则、Human Gate、Reviewer identity 或 event semantic validation。

通道一旦随 RR 冻结，之后新增的 binding 或 `FUTURE_REQUESTS_ONLY` route 只影响后续 RR，不能改写或使当前 `REVIEWER_HTTP` RR 失效。

### 3.2 HTTP 投递与恢复

`REVIEWER_HTTP` 的完成条件不是“内存中可见”，而是 B-scoped `intake_receipts` 已持久化为 `READY/ACKED`。顺序为：

1. Dispatcher claim 同一 outbox 并提交 `LEASED`；
2. adapter 按 `RR.id + input hash + profile hash + reviewer actor` 查询已有 intake；
3. 无记录时持久写入唯一 intake，有记录时复用；
4. adapter 返回 transport `ACCEPTED` 后 Dispatcher 才以 lease token/generation fencing 写 `SENT`；
5. B 的认证 GET 把 intake 写为 `ACKED`，但 RR 仍为 `PENDING/IN_PROGRESS`；只有合法 event APPLY 能产生 Review/verdict。

若第 3 步已提交、第 4 步前进程退出，outbox lease 过期后下一 Dispatcher 先查到原 intake，再把同一 outbox 写为 `SENT`，不会新建 RR、intake 或 review round。

### 3.3 安全边界

- HTTP 索引、RR、Artifact 和 event 继续只用独立 B token；Builder/MCP token 不能替代。
- 列表按 frozen expected reviewer 与当前 delivery contract 再校验；Gate、终态、过期、非 active RR 不返回。
- `ACKED` 条目在 RR 仍 active 时继续出现在索引，避免 Reviewer 读到后崩溃造成不可重见；重复 GET 是幂等读取，不产生第二次评审事实。
- 无 PR 路径不会创建 GitHub Comment，也不会把 GitHub projection 当 Hub verdict。Final Review 完成后若仍无 binding，GitHub 展示投影可独立保持待处理/未投影，不回滚 Hub Review。
- 本修复没有声称当前 Grok 账号已经自动轮询该索引；该项仍是 `ENVIRONMENT_VALIDATION_REQUIRED`。

## 4. 变更清单

- `src/grokbuddy/domain/model.py`：新增稳定错误码 `REVIEW_DELIVERY_UNAVAILABLE`。
- `src/grokbuddy/application/grok_routing.py`：集中通道选择与 frozen delivery contract 复核；HTTP RR 的认证读/回传不再要求虚构 PR route。
- `src/grokbuddy/application/reviews.py`：在任何 RR/outbox/上下文 Artifact 创建前选择通道，持久化并审计。
- `src/grokbuddy/application/workers.py`：HTTP intake 的 durable publish/reconcile、B-scoped 待审索引、ACK 后重见。
- `src/grokbuddy/adapters/grok_bot.py`：按 frozen channel 选择 GitHub Comment 或 HTTP intake；两者复用既有 Grok event normalizer。
- `src/grokbuddy/infrastructure/runtime.py`、`scripts/grokbuddy_composite.py`：production dispatcher 与 HTTP intake 使用同一 B 配置组装；eligibility 接受合法 frozen HTTP channel。
- `src/grokbuddy/interfaces/grok_reviewer.py`：新增 token-authenticated `GET /reviewer/requests`，保留原单 RR/Artifact/event 路径。
- `tests/test_phase6_supervisor_production_wiring.py`：增加无 binding v2 Plan、HTTP list/read/ACK、partial route fail-fast 与生产不回落 mock 的回归。

未修改 schema 表结构、trigger ingress、Task owner、状态机边、mock production 默认、GitHub binding 创建规则或 Human Gate 语义。

## 5. 本地验证

| 命令 | 结果 | 能证明 / 不能证明 |
| --- | --- | --- |
| `python -m pytest tests/test_phase6_supervisor_production_wiring.py -q` | 11 passed | production wiring、无 PR HTTP path、publish 后崩溃对账、frozen channel、partial route fail-fast；不证明公网/B 执行 |
| `python -m pytest tests/test_phase4_grok_adapter.py tests/test_workers.py tests/test_phase6_ingress_builder_drive.py tests/test_phase6_supervisor_recovery.py tests/test_workflow.py -q` | 46 passed | GitHub routed、mock、ingress owner、recovery/timeout 兼容；不证明真实外部系统 |
| `python -m compileall -q src/grokbuddy tests/test_phase6_supervisor_production_wiring.py` | PASS | Python 静态编译 |
| `python -m pytest -q` | 804 passed | 当前仓库全量本地回归；不等于外部 E2E |
| `python scripts/validate_phase0.py` | 218/219；仅 `phase0-no-core-source` FAIL | Phase 0 历史检查要求“无核心实现”，与当前 Phase 6 仓库天然不适用；没有 schema fixture 失败，未伪报全绿 |

核心断言：

- 无 binding/route 的正式 Plan RR 为 `REVIEWER_HTTP`；Supervisor tick 后 outbox=`SENT`、intake=`READY`、RR=`PENDING`、GitHub Comment=0、mock job=0。
- B-token 索引只返回该 RR；读取后 intake=`ACKED`，再次索引仍可见，RR 仍未获得 verdict。
- intake 已持久但 outbox 尚未写 `SENT` 的模拟崩溃可由 lease 到期后对账恢复；仍只有 1 个 RR、1 个 outbox 和 1 个 intake receipt。
- 只有 binding、没有 route 的请求抛 `REVIEW_DELIVERY_UNAVAILABLE`；`review_requests/outbox_events/artifacts` 计数均不变。
- 已有完整 binding+route 的原 GitHub Comment delivery 测试继续通过。

## 6. TASK-702 Human 续跑

旧 RR 与旧 outbox 是不可变故障证据，**不得原位改写或复活**。续跑必须创建新 RR：

1. Human 部署当前仓内改动并受控重启正式 Hub；运行既有 runtime probe，确认 local/public `/health`、`/ready` 正常且 `checks.supervisor=ok`。不得由本报告代替重启证据。
2. 通过 Human 绑定的正式 MCP 重新读取 Task；只在仍为 `PLAN_HUMAN_REVIEW` 且 frozen Plan `ART-ddc48514-1a79-4857-8cd8-946715ba7da0` 未变时继续。只读快照时 version 为 `4`，实际调用必须使用当时重新读取的 version。
3. Human 调用 `human_gate_decide`：`decision=CONTINUE`，给出说明 delivery gap 已修复的真实 reason、新的唯一 idempotency key、`extra_review_budget=1`，以及明确的未来 `new_deadline_at`。这会审计新预算并回到 `PLANNING`；不会复活 `RR-bebe1782...`。
4. Builder 对同一 Task 调用 `request_plan_review`，使用 Continue 返回的新 version 与新的唯一 key。预期新 RR 为 Plan round 2、expected reviewer B、`delivery_channel=REVIEWER_HTTP`，且 Task owner 仍为 `workbuddy-ingress`。
5. 等待常驻 Supervisor 自动处理；查询应看到新 outbox=`SENT`、B intake=`READY/ACKED`，且该 Task 仍无 binding/route、无 mock job。不得运行 `dispatch-once`、Test Run、临时 resume 脚本或人工复制 Review 结果。
6. 只有 B 经 PublicBase 读取冻结 RR/Artifact、提交结构化 event，Hub APPLY 后，才按 Review/Task/Audit 判断结果。Human Gate Accept 不得作为 6.20 证据。

如重启后新 RR 未在一个正常 supervisor 扫描周期内进入 HTTP intake，应停止续跑并保留 RR/outbox/worker metrics；不得等到 deadline 再把它描述为“Grok 无响应”。如 B 当前不能自动轮询 PublicBase，则本地修复仍成立，但真实 6.20 继续 BLOCKED，选项是配置并验证 B 的受控定时 poll/push，或另行批准一个真实、可审计的外部 wake transport；不得回落到 mock。

## 7. Gate

| Gate | 状态 |
| --- | --- |
| 源码根因与 live record 只读核对 | PASS |
| 无 binding 不再永久停留于不可 claim 的 READY | LOCAL PASS |
| partial/mismatch 在 request 时显式失败 | LOCAL PASS |
| 原 GitHub routed path / mock isolation / recovery 回归 | LOCAL PASS |
| Human restart + TASK-702 Continue + 新 RR | NOT RUN |
| 当前账号 B 自动 poll/push PublicBase | ENVIRONMENT_VALIDATION_REQUIRED |
| 真实 Grok result APPLY / WorkBuddy E2E | NOT RUN |
| Phase 6.20 | **NOT PASS** |

STOP：已完成仓内方案、实现、隔离测试与诚实报告；不 push，不代跑 WorkBuddy/Grok E2E。
