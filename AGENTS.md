# GrokBuddy AGENTS

跨阶段长期规则。**V1 产品需求、blocker 与 6.21/6.22 Exit Gate** 以
[docs/PRODUCT_PATH_V1.md](docs/PRODUCT_PATH_V1.md) 为准；当前生产部署事实与
历史 PASS / BLOCKED 进度看 [docs/CURRENT_PRODUCTION_BASELINE.md](docs/CURRENT_PRODUCTION_BASELINE.md)
及带日期的 Phase 报告。本文件不改写历史结论。

## 硬规则（违反即停）

1. **Hub 是唯一业务 SoT**。GitHub / Reviewer / 前端只是通道或投影，不得反推 Task/Review 终态。
2. **正式证据 Manual Glue = 0**：禁止 `LocalRuntime`、mock、`run_until_idle`、`*_once`、pipeline-drive 正式路径、手 POST wake、直接 DB DML、Human Continue 冒充 Reviewer PASS。
3. **身份分离**：Builder ≠ Reviewer ≠ Human；禁止 Builder 凭证冒充 Reviewer。
4. **Review 异步 + fail-closed**：adapter（含 mock）不得同步伪造 verdict；未知协议版本 / 校验失败则拒绝。
5. **密钥不进**源码、Git、聊天、日志、Artifact 明文、Audit 摘要、公开 Comment。
6. **未授权禁止**：生产 DDL/DML、部署/重启/删资源、改防火墙、GitHub merge/approve/push/force-push、改默认分支。
7. **产品范围与合同均须对齐**：V1 范围以 `docs/PRODUCT_PATH_V1.md` 为准，现行机器协议以 `docs/contracts/` 为准；两者或代码冲突时报 drift，禁止靠旧 Gate 或「当前代码」降低 V1 需求。

## WorkBuddy Managed Workload（正式业务链）

- 普通 WorkBuddy 对话不进入 GrokBuddy。只有 Human 在 WorkBuddy 当前用户消息中满足下述精确触发规则，才通过专用 WorkBuddy ingress 创建 Hub Task；该触发闸不约束下文的 Codex 仓库维护。
- 已触发的业务 Task 走 **GrokBuddy 正式链**：真 Reviewer = `grok-reviewer-b`（REVIEWER_HTTP / wake）。
- 新 Task 的当前用户自然语言正文须逐字包含唯一触发语 `启用grokbuddy流程`（常量见 `src/grokbuddy/application/trigger.py` 的 `PHRASE`）；Hub 已有任务时可说 `按流水线走完。`
  **禁止**要求用户每次粘贴本文件约束。
- 开干前自检：无 mock-reviewer、无主动降级、个性化规则若与本文冲突 → **停并报告**。
- 此正式链的 Plan / Code 必须绑定当前 Hub Task 的 Grok Review、`PLAN_APPROVED`、`approved_scope` 与 Task lifecycle；Task A 的授权不得用于 Task B。
- 产品闸见 [docs/PRODUCT_PATH_V1.md](docs/PRODUCT_PATH_V1.md)：
  - 方案未 PASS **禁止写代码**
  - 方案/终审各最多两轮；R1 可建议，R2 仅 PASS/BLOCKED；无方向性问题不得 BLOCKED
  - 方案 R2 BLOCKED：停写；展示 WB方案1 / Grok意见1 / WB方案2 / Grok理由2，等 Human
  - 终审 PASS：展示操作方法 + 文件；终审 R2 BLOCKED：仍展示产物 + 理由，并标明未验收通过
- `PRODUCT_PATH_V1.md` 缺失 → 停，请 Human/Codex 补齐，不得自制平行流程。
- 旧 6.21 A–I 负面矩阵不是 V1 Exit Gate；新 6.21 是产品流程验收，新 6.22 是实际可用性验收。same-RR re-wake 默认属于 V1.1 reliability backlog，不能以未做生产验证继续阻塞 V1。历史报告状态保持原样。

## GrokBuddy Control Plane Development（Codex 维护）

- Human 在 Codex 会话中明确要求修改本仓库自身代码、合同、测试、文档或自动化时，该指令即为本次仓库维护的授权；不要求先建 WorkBuddy Hub Task，也不要求提供 `PLAN_APPROVED` Task ID 或 `approved_scope`。Hub、MCP、Control Center、Supervisor、Webhook 与 Reviewer routing 均属此类维护。
- Hub Task 可只读用于复现和验收，但不是 Codex 仓库维护的授权凭证；不得擅自修改业务 Task 数据。
- 不擅自修改 Credential，不擅自执行 destructive production action；生产级高风险操作仍需 Human 明确确认。保留上述密钥、身份、Hub SoT、生产操作及正式证据边界。
- 修改后按影响范围运行测试，并审核 Git diff；本地检查不能代替生产验收。

## 工作方式

- 先读 [V1 Product Path](docs/PRODUCT_PATH_V1.md) 和 [Current Production Baseline](docs/CURRENT_PRODUCTION_BASELINE.md)，再按需打开 skills：`architecture-gate` / `phase-execution` / `review-protocol-validator` / `async-workflow-test`。
- 只做 Human 明确授权的范围；Roadmap/旧报告/测试用例 ≠ 新授权。
- 状态机细节不复制：见 [STATE_MACHINE.md](STATE_MACHINE.md) 与 contracts。
- 本地单测/fixture/mock 只证明其覆盖范围，不得外推为生产全通。

## 常用命令

```bash
# 相关测试子集（按改动选择）
python -m pytest tests/test_phase6_supervisor_production_wiring.py tests/test_phase6_supervisor_recovery.py -q
