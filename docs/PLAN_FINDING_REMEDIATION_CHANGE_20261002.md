# 方案 Finding 整改与拒绝诊断：2026-10-02 本地交付

## 结论与证据边界

本次完成三项仓库维护：修复方案 Finding 的公开 `fix` 路径；新增 WorkBuddy 方案整改技能和只读准备度查询；为异步 Reviewer 拒绝收据保存具体原因。结果为 **本地实现与回归通过**。正式服务尚未由本会话部署或重启，WorkBuddy 用户技能尚未由本会话安装，真实 WorkBuddy → GrokBot → Hub 新任务验收尚未执行。

没有修改正式 Hub 业务数据，没有向原 RR 重投，没有调用 Human Gate，没有替 Reviewer 提交 PASS。下述测试中的数据库写入、mock 结果和 Human 操作仅发生在可丢弃的本地 fixture 中，不能作为正式证据。

## 原 Task 的只读复核

2026-10-02 19:25:11 上海，直接以 SQLite `mode=ro` 和 `PRAGMA query_only=ON` 在同一读取事务中核对 `config/grokbuddy.service.json` 指向的 `var/github-manual/hub.db`：

| 对象 | Hub 记录 |
| --- | --- |
| Task `TASK-5188ad70-68c2-4197-8e41-fefc7e62f79e` | `PLAN_HUMAN_REVIEW`，version 8，active RR 空，`REVIEW_TIMEOUT`，自动化冻结，Plan 上限 2 |
| R2 `RR-29621b23-87c6-4590-801d-4fae9fead2a1` | `TIMED_OUT`，round 2 / limit 2，截止 2026-10-02 18:36:14.197796 上海 |
| Ingress `IN-bacf5c8d-8336-40e2-9dea-7450e8b7eee4` | `REJECTED / ILLEGAL_TRANSITION`，历史记录没有 field path 或 rejection details |
| `FND-4e933976-7393-4cf0-9017-fcfc906afdfc` | HIGH，OPEN，version 0 |
| `FND-c36bddb5-7771-453b-ad69-7edd4aafab65` | MEDIUM，OPEN，version 0 |
| Finding events / Human approvals | 2 / 0；未走过 Builder accept/fix |
| Plan 请求 | R1 COMPLETED；R2 TIMED_OUT；没有新一轮请求 |

原结果对 OPEN Finding 请求 Reviewer verification。Hub 的 `finding_transition(OPEN, verify, REVIEWER)` 不允许该转换，抛出 `ILLEGAL_TRANSITION`；结果尚未走到 PASS 的未关闭项检查就已回滚。正常修复路线由 Builder accept → fix，使 Finding 达到 FIXED，再由独立 Reviewer verification；修改 Plan 本身不会更改 Finding 状态，FIXED 也不等于 PASS。

原 Task 的两轮已用尽，不能在同 Task 上再开“新 R2”，不能借 Continue/Modify/额外预算产生 R3。旧 RR 保留 TIMED_OUT，旧 ingress 保留 REJECTED；后续业务必须等待 Human 根据现行 Gate 合同决策，本次维护没有代做该决策。历史 ingress 不回填新诊断。

## 三项实现

### 1. 公开方案整改路径

[Gateway](../src/grokbuddy/interfaces/gateway.py) 的 `respond_to_review(action="fix")` 在 Finding 属于 PLAN_REVIEW 时直接调用既有 Finding Application Service，不先做 `execute`。方案修复保持 `PLANNING`，不创建 Worker assignment。

既有角色分离、Task 权限、状态、活动 RR 冻结、Task version CAS、幂等键和证据类型约束保留；Plan 本身仍不能充当 Builder fix 证据。Final 原有执行路径保留。

### 2. WorkBuddy 整改技能和准备度查询

新增 [方案整改技能](workbuddy-skills/grokbuddy-plan-remediation/SKILL.md)，并在原 [触发技能](workbuddy-skills/grokbuddy-trigger-ingress/SKILL.md) 中添加后续技能入口。原精确触发闸仍只负责新任务创建，没有扩展为持续驱动。

新增 `get_plan_review_readiness(task_id)`，经本地 Gateway/MCP 暴露，在 Builder/Task 权限内只读返回 Task version、活动 RR、轮次余额、Plan Finding 状态和下一步建议。未加入公开 Remote MCP 查询面，不写 Task、Finding、Audit、outbox 或轮次。

准备度还提示 FIXED 项的修复证据是否显式绑定到当前 Plan 材料。复用共享工作区已有的 `submit_plan(supporting_artifact_ids=...)`、冻结 RR 材料和 Reviewer 白名单读取能力；本次正向测试使用 EVIDENCE。Builder fix 支持的 DIFF/TEST_RESULT 并不等于当前 Plan supporting materials 支持，因此技能明确使用 EVIDENCE 作为必读修复说明。

`can_request_review` 和 `ready_for_review` 都是读取时的提示，不是授权、预留轮次或 PASS。没有新增“所有项 FIXED 才能请求 R2”的硬守卫，保留实质问题无法解决时合法交给 R2 判断 BLOCK 的路径。活动 R2 的余额为 0 时仍可等待结果；过期、冻结、Human Gate 和无余额则停止自动推进。

### 3. 异步拒绝诊断

[Event Service](../src/grokbuddy/application/events.py) 在业务事务回滚后，仅将已校验、同 Task 的安全元数据保存到拒绝收据。经鉴权的 `GET /reviewer/ingress/<IN>` 返回新增 `reason_code`、`rejection_details`、`rejection_details_source`。`POST /reviewer/events` 仍是异步 `202 READY`，不提前宣称业务成功。

- `FINDING_NOT_READY_FOR_VERIFICATION`：保留 `ILLEGAL_TRANSITION`，列出 Finding ID、当时状态、requested outcome、合法源状态和字段位置，并给出 `blocking_open_findings`。
- `PASS_HAS_UNRESOLVED_FINDINGS`：保留 `VALIDATION_FAILURE`，列出通过投影检查后仍未关闭的项。OPEN 列表为空也可能因 FIXED 等待 verification 而拒绝 PASS。

不复制原始异常、Finding 文本、结果 summary、证据正文或凭证。Audit 仅增加受控 reason code 和 field path。跨 Task、证据或 frozen version 校验先拒绝，不泄露相关 Finding 细节。历史收据无新字段时返回 null，不重跑 APPLY，不用今天的状态猜历史原因。详细接口说明见 [拒绝诊断](REVIEW_INGRESS_DIAGNOSTICS.md)。

共享工作区并行维护引入的纯结果绑定函数移至 [Domain](../src/grokbuddy/domain/review_result.py)，原 adapter import 保留兼容导出，消除 Application → Adapter 的架构依赖；判定行为保持不变。

## 验证

新增 [14 项整改与诊断回归](../tests/test_plan_finding_remediation.py)，覆盖：

- 两条 R1 Finding accept/fix、证据绑定与 Reviewer 白名单取件、R2 verification PASS → PLAN_APPROVED，全程无 Worker；相同参数和幂等键重试不重复推进。
- 活动 RR、stale version、错误证据类型、跨 Task 证据、OPEN 直接 fix、错误 Task 状态、Reviewer 冒充 Builder 均拒绝且不改变业务数据。
- 准备度/MCP 查询无写入、权限范围、未列入 Remote 查询面、证据未绑定提示，以及 R2 超时后不得增加轮次。
- 真正 ASGI HTTP 鉴权边界中的异步收据、两条无效 verification 一次列出、安全诊断、拒绝事务回滚、查询无写入、超时/后续变化后的历史诊断稳定，以及旧收据返回 null。
- FIXED 未验证的 PASS 拒绝与跨 Task verification 不泄露诊断。

| 检查 | 结果 |
| --- | --- |
| 首次相关 7 文件回归 | 78 passed |
| 扩展 Application/Domain/worker/Gate 回归 | 672 passed；1 项架构检查失败，纯函数依赖已移至 Domain |
| 修正架构后相关 8 文件回归 | 662 passed；1 项旧测试工具清单未包含并行新增的 `preflight_final_review` |
| 同步工具清单后的失败项复测 | 1 passed；上述架构检查和 14 项新增回归已在上一轮通过，无剩余已知失败 |
| 文档链接与现行 contracts 离线检查 | 272 / 272；未重写历史 Phase 报告 |
| 新 skill 的 skill-creator 校验 | Skill is valid |
| `git diff --check` | 通过；仅 Git 换行风格提示 |

未宣称全仓全量测试通过。工作区包含其他维护的修改，未撤销、提交或推送它们，也未将全部未提交 diff 视为本次授权的发布包。

## 交接与下一阶段

代码与规范部分无需 WorkBuddy 或 GrokBot 代写。需要 WorkBuddy 完成的是用户端技能加载和实际工具发现；需使用仓内新整改技能，同时更新原触发技能。工具未出现时应报告服务/MCP 版本未就绪，不能绕过 Hub。

正式启用必须单独批准部署范围并按生产基线执行：本次改动同时涉及正式 Hub 的异步 Event Service 和本地 MCP 的 Gateway/工具面。正式部署/重启受 [AGENTS.md](../AGENTS.md) 硬规则 6 约束，尚未执行。

真实验收在授权部署后使用 Human 新近明确触发的独立任务，并由 Supervisor 和真实 `grok-reviewer-b` 完成；观察新 ingress 的最终 APPLIED、Finding verification 与 Hub PLAN_APPROVED。旧超时 RR 不能用于验收。GrokBot 的结果 schema 不因本次诊断增量而改变；该会话没有向 GrokBot 发消息或手动投递。
