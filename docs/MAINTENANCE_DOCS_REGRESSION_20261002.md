# 2026-10-02 当前文档核对与必要回归

结果：**DOCS RECONCILED / LOCAL REGRESSION PASS**。新定义 6.21/6.22 仍未验收；本次不声明生产产品 PASS。

范围：Human 授权的 Codex 仓库维护，更新当前说明、补齐既有测试材料并运行本地回归。未开始新的 WorkBuddy 业务 Task，未修改生产数据、服务配置、凭证、冻结 Profile 或状态机合同，未部署、重启或上传 GitHub。

## 当前事实与证据等级

2026-10-02 18:34（Asia/Shanghai）只读正式 DB 快照使用 SQLite `mode=ro`、`PRAGMA query_only=ON` 和读取事务；不初始化运行时、不执行业务命令。沙箱内打开 live WAL 读取失败后，仅对同一只读查询使用沙箱外执行，不使用 immutable 模式绕过 WAL。

| 核对项 | 实际结果 | 证据边界 |
| --- | --- | --- |
| 正式本机 GET `/ready` | `ready`；database=`ok`、supervisor=`ok` | 只证明核对时就绪，不是产品验收。 |
| Profile 注册 | 六个 Profile 各有 1.0、1.1，共 12 项 | 入口默认仍为 1.0，不自动切换新任务。 |
| 指定历史 1.1 Task | `TASK-673aaac2-7ad9-4728-b663-c2d003de6015` 为 `DONE / FINAL_REVIEW_PASS` | Hub 历史权威状态保持原样，不代表交付质量已独立确认。 |
| 该 Task 的 Plan / Final | `RR-d2d90392-cc95-4fde-bbe4-3a43fcb924c6` / `RR-50b72684-998b-4c2f-9ca4-386e70c2277d` 经 `REVIEWER_HTTP`、`grok-reviewer-b`，均 `COMPLETED / PASS`；冻结 Profile Hash 与 `generic@1.1` 注册值一致 | 不反推外部指令加载或实际材料读取。历史 Final 快照仍含 403，不能因后续权限修复而改写历史结论。 |
| 正式 Reviewer HTTP 记录概览 | 22 个 RR：16 COMPLETED、5 TIMED_OUT、1 PENDING；对应 inbox 为 16 APPLIED、30 VALIDATION_FAILURE 拒绝、6 CONFLICT 拒绝、1 ILLEGAL_TRANSITION 拒绝 | 点时提交记录含重试，不是任务失败率；活动 RR 未被本次维护处理。 |
| Reviewer 材料/回执实现 | `grok_routing.py` 与 `grok_reviewer.py` 已有 RR-scoped materials、artifact、ingress、结果 schema GET | 本次未执行认证 Reviewer GET 或外部 GrokBot 公网拉取；不触发 intake ACK。2026-09-30 既有重启证据保留在本地 rollback 目录。 |
| 新定义 6.21 / 6.22 | 未见完整产品场景与实际可用性验收记录 | 保持未验收，不重跑旧 A–I 矩阵作为 V1 出口条件。 |

## 修改

- 当前事实集中到 `CURRENT_PRODUCTION_BASELINE.md`；产品文档保留冻结需求，将原 blocker 表明确标为 2026-09-23 快照。
- WorkBuddy 集成说明标明 6.20 早期等待重测语句的历史时间，引用后来正式核心链 PASS；不要求重投旧任务。
- 运维手册将历史等待重启标记移入历史说明，并按 service config 更新 wake 环境变量名的配置事实；Grok 集成入口明确标注原观察日期。
- Profile 1.1 说明区分正式 Hub 已使用、外部指令加载未证实与质量未复验；更新 Reviewer 材料/回执说明。保留原 2026-09-26 测试结果及历史 Phase 报告。
- 既有 ingress Builder 完整流程测试补齐操作方法、生成文件及其真实测试 Artifact 引用；不放宽生产校验。

## 本地验证

本地测试在临时目录使用隔离运行时和 mock，只证明覆盖范围，不构成正式业务链证据。全量结果针对本次完成时的工作区，包含本次开始前已有的 Profile 1.1 和材料接口改动；本次未改动这些运行代码。

| 检查 | 实际结果 | 说明 |
| --- | --- | --- |
| 修复前既有失败复现 | 1 failed，5.20s | `test_ingress_owner_is_preserved_while_configured_builder_drives_plan_to_done` 在 V1 Final 的操作方法校验处失败。核对同时发现生成文件引用也缺失。 |
| 修复后相关回归 | 29 passed，13.10s | ingress Builder 流程与 Control Center；操作方法和源文件 Artifact 通过既有 Gateway 补齐 SHA 后提交，不更改生产校验。 |
| 全量 pytest | 888 passed，230.33s | 本次完整重跑，没有失败；不替代真实 WorkBuddy/GrokBot 或生产验收。 |
| 既有文档/合同检查器 | 272/272 passed | 只调用 `validate_documents(True)` 和 `validate_contracts()`，不调用会写回历史报告的 `main()`。 |
| 本次 11 份 Markdown 链接 | PASS，无断链 | 包含 `grok_bot/` 下两个指令文件，补足既有文档扫描范围。 |
| V1 冻结要求对照 | PASS | 与 HEAD 比较“Human 冻结的 11 条 V1 产品需求”章节，内容逐字未改。 |
| Git diff 审核与空白检查 | PASS | 使用仓库正常行尾配置执行 `git diff --check`；未对既有 CRLF 文件做批量格式化。 |

测试命令：

```powershell
.\.venv\Scripts\python.exe -B -m pytest tests/test_phase6_ingress_builder_drive.py::test_ingress_owner_is_preserved_while_configured_builder_drives_plan_to_done -q -p no:cacheprovider
.\.venv\Scripts\python.exe -B -m pytest tests/test_phase6_ingress_builder_drive.py tests/test_control_center.py -q -p no:cacheprovider
.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider
git diff --check
```

文档/合同检查复用 `scripts/validate_phase0.py` 的函数，通过 `runpy.run_path(..., run_name='maintenance_checks')` 加载，检查结果只打印而不覆盖 `phase0-checks.json` 或 `phase1-contract-checks.json`。

## 本次文件范围

- 当前入口与导航：[README](../README.md)、[生产基线](CURRENT_PRODUCTION_BASELINE.md)、[V1 产品文档](PRODUCT_PATH_V1.md)、[WorkBuddy 集成](WORKBUDDY_INTEGRATION.md)、[Grok 集成历史边界](GROK_BOT_INTEGRATION.md)、[运维手册](PHASE6_OPERATIONS_RUNBOOK.md)。
- Profile 与 Reviewer 当前说明：[Profile 1.1](REVIEW_PROFILE_V1_1.md)、[原验证记录的当前指针](REVIEW_PROFILE_V1_1_VALIDATION.md)、[Reviewer 1.1 指令](../grok_bot/reviewer_rules_v1_1.md)、[Reviewer 协议说明](../grok_bot/reviewer_skill.md)。
- 测试修正：[既有 ingress Builder 流程测试](../tests/test_phase6_ingress_builder_drive.py)；新增本验证记录。

所有既有带日期 Phase 报告保留原样。开始维护前已有的未提交改动未被回滚、提交或上传。

## 尚需 Human 或外部证据的事项

当前文档和本地回归可由 Codex 完成。后续新 6.21/6.22 的真实 WorkBuddy 使用、双方修订与阻断展示、Control Center 字段和文件可用性仍需另行授权的实际使用证据。外部 Reviewer 指令更新、默认版本切换、生产发布/重启与 GitHub 上传不在本次范围。
