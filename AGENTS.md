# GrokBuddy AGENTS

跨阶段长期规则。Phase / Gate / PASS 进度只看
[docs/CURRENT_PRODUCTION_BASELINE.md](docs/CURRENT_PRODUCTION_BASELINE.md)
与带日期的 Phase 报告；本文件不改写历史结论。

## 硬规则（违反即停）

1. **Hub 是唯一业务 SoT**。GitHub / Reviewer / 前端只是通道或投影，不得反推 Task/Review 终态。
2. **正式证据 Manual Glue = 0**：禁止 `LocalRuntime`、mock、`run_until_idle`、`*_once`、pipeline-drive 正式路径、手 POST wake、直接 DB DML、Human Continue 冒充 Reviewer PASS。
3. **身份分离**：Builder ≠ Reviewer ≠ Human；禁止 Builder 凭证冒充 Reviewer。
4. **Review 异步 + fail-closed**：adapter（含 mock）不得同步伪造 verdict；未知协议版本 / 校验失败则拒绝。
5. **密钥不进**源码、Git、聊天、日志、Artifact 明文、Audit 摘要、公开 Comment。
6. **未授权禁止**：生产 DDL/DML、部署/重启/删资源、改防火墙、GitHub merge/approve/push/force-push、改默认分支。
7. **合同优先**：与 `docs/contracts/` 冲突时报 drift，禁止用「当前代码」迁就改合同。

## 正式链（本仓库默认；用户需求保持短句）

- 默认走 **GrokBuddy 正式链**：真 Reviewer = `grok-reviewer-b`（REVIEWER_HTTP / wake）。
- 用户侧足够：`走 GrokBuddy。帮我做：…` 或 Hub 已有任务时 `按流水线走完。`  
  **禁止**要求用户每次粘贴本文件约束。
- 开干前自检：无 mock-reviewer、无主动降级、个性化规则若与本文冲突 → **停并报告**。
- 产品闸见 [docs/PRODUCT_PATH_V1.md](docs/PRODUCT_PATH_V1.md)：
  - 方案未 PASS **禁止写代码**
  - 方案/终审各最多两轮；R1 可建议，R2 仅 PASS/BLOCKED；无方向性问题不得 BLOCKED
  - 方案 R2 BLOCKED：停写；展示 WB方案1 / Grok意见1 / WB方案2 / Grok理由2，等 Human
  - 终审 PASS：展示操作方法 + 文件；终审 R2 BLOCKED：仍展示产物 + 理由，并标明未验收通过
- `PRODUCT_PATH_V1.md` 缺失 → 停，请 Human/Codex 补齐，不得自制平行流程。

## 工作方式

- 先读 Baseline，再按需打开 skills：`architecture-gate` / `phase-execution` / `review-protocol-validator` / `async-workflow-test`。
- 只做 Human 明确授权的范围；Roadmap/旧报告/测试用例 ≠ 新授权。
- 状态机细节不复制：见 [STATE_MACHINE.md](STATE_MACHINE.md) 与 contracts。
- 本地单测/fixture/mock 只证明其覆盖范围，不得外推为生产全通。

## 常用命令

```bash
# 相关测试子集（按改动选择）
python -m pytest tests/test_phase6_supervisor_production_wiring.py tests/test_phase6_supervisor_recovery.py -q