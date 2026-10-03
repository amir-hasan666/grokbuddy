# Profile 1.1 实施与验证记录

首次实施：2026-09-24；恢复后完整验证：2026-09-26。范围：仓库实现与隔离本地验证。
本记录不改变历史 Phase 报告或已有 Task/Review 的裁决。
比较基线：`72ef237`。2026-09-26 本地验证时的结论：**Profile 1.1 LOCAL COMPATIBILITY PASS / REAL REVIEWER NOT RUN**。

以下原验证结果与失败复核保留为当时记录。2026-10-02 已重新核对正式 Hub 的 1.1 使用记录，并修正既有入口测试的 V1 交付材料缺项；当前回归结果和外部证据边界见 [本次文档与回归记录](MAINTENANCE_DOCS_REGRESSION_20261002.md)。本地通过、正式协议 APPLY 与实质审核质量分开报告。

## 实施

- 六类 Profile 保留 1.0 原内容并追加 1.1 完整快照；注册仍经现有 seed 事务，拒绝同版本改内容。
- 通用、条件式和专业规则统一组装；Reviewer 指令按冻结版本和政策工作，默认保持 1.0。
- 提供 20 个跨类型审核案例和 3 个现有 v2 Schema 格式样例；期望答案与盲测输入分开。
- 没有增加协议字段、Hub 审核守卫、取件权限、外部调用或生产状态修改。

## 本地验证

| 检查 | 状态 | 说明 |
| --- | --- | --- |
| 新增版本兼容用例 | 15 passed（本次全量执行包含全部用例） | 隔离临时目录；包含真实 MCP 工具调用的默认/显式版本、幂等性，以及升级时已有 Review 的保留测试，未连接实际 WorkBuddy 或 Grok。 |
| 全量 pytest | 886 passed / 1 failed（235.64s） | 2026-09-26 对最终文件完整重跑；失败仍为既有入口测试缺少 operation_method，修改前模块同样失败；详情见下文。 |
| 既有合同检查器 | 272/272 passed | 首次 271/272 的断链在本记录创建后复测关闭；没有修改合同。 |
| Git diff 与范围检查 | PASS | 生产代码仅 Profile 和注册循环；旧规则、默认入口、协议、生产配置及历史报告无改动。新指令和案例库链接也已核对。 |

测试入口：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_review_profiles_v1_1.py -q
.\.venv\Scripts\python.exe -m pytest -q
```

合同检查复用 `scripts/validate_phase0.py` 的 `validate_documents(True)` 和 `validate_contracts()`，
通过 `runpy.run_path` 加载；不调用会写回历史 `phase1-contract-checks.json` 的 `main()`。
这样保留原检查逻辑和全部正负例，不覆盖历史报告。

2026-09-24 首次全量结果为 885 passed / 1 failed（242.57s），当时收集了首版 14 项新增用例；
随后将默认版本用例加强为真实 MCP 默认/显式选择的两项测试，专项重跑 15 passed（15.46s）。
升级兼容用例又补入已有已完成 Review 的保留检查，该单例通过（2.66s）。
2026-09-26 恢复时核对工作区及已有记录，没有回滚或重做实现；本次全量已包含全部 15 项
最终版新增用例，结果为上表 886 passed / 1 failed。生产代码自首次全量执行后未再变化。
本次同时复测既有合同检查器（272/272）及补充文档链接检查，并确认旧 Profile 源码逐字保留、
所有创建入口默认仍为 1.0，协议、应用守卫、取件接口、生产配置与历史报告均未改动。
案例完整性与结果样例测试只证明材料可用和 Schema 兼容，不评价模型实质判断。

### 既有失败复核

失败测试：
`tests/test_phase6_ingress_builder_drive.py::test_ingress_owner_is_preserved_while_configured_builder_drives_plan_to_done`。
其 `request_final_review` 材料没有 V1 要求的操作方法，触发
`HubError: V1 Final package requires operation method`（`application/tasks.py`）。

分别执行当前工作区该单例，以及在隔离进程内用 `git show HEAD:<path>` 读取并加载
修改前 `infrastructure/profiles.py`、`infrastructure/runtime.py` 后执行相同单例，
两者都在同一位置因相同错误失败。测试本身及该校验代码未修改。
这是对两个改动模块的基线对照，不是声称对完整历史仓库进行了全量重跑。
2026-09-26 的完整重跑再次在同一测试和同一校验处失败，没有新增失败项。
本期保留该既有失败，不通过放宽终审条件使测试变绿。

### 1.1 快照 Hash（本地 seed 计算）

以下仅供后续核对发布快照，不证明生产已经注册：

| Profile | SHA-256 |
| --- | --- |
| generic | `56f5d3dafb6cd5868462db0dba71bf289ba4e9621071944bb42caff361c8cd2e` |
| oracle_production | `fc8c468901cb230eadf4845fcc5f997895238b1b6adbdfd609a035d07be98912` |
| sql_server_production | `42e1d4feec67c51c8a3015f51a934e1863ecaa0e275268fe84c868b599d08125` |
| python_backend | `eee875ae31c3e7cdf9371d219b58331f7bd320f878ff1483dfd796a8a4572c12` |
| iis_windows | `70874d74fe82f8850fe9f8a2ae915e811beb486c7d6cffe55ed1708734d613f8` |
| document | `9a79458b7fb12f5b6effe348cb50f298d8e002693b6b8a5fd2ddfd8f32036f1f` |

## 实际审核 Gate

| Gate | 状态 | 缺少的实际证据 |
| --- | --- | --- |
| 生产运行端注册 1.1 | NOT RUN | 经授权发布后的新 Task/RR 版本和 Hash。 |
| 独立 GrokBot 加载新指令 | NOT RUN | 外部 Reviewer 的实际加载及取件记录。 |
| 跨类型审核质量改善 | NOT RUN | 正常主链的真实 verdict、命中/漏报、误阻断和引用评分。 |
| 全面改为默认 1.1 | NOT RUN | 跨类型试用结果及单独决定。 |

已知能力限制：当前取件范围不自动包含原始需求和 Final 包引用的全部文件；
视觉检查能力也不能由规则文案产生。试用中须如实报告实际材料/能力缺口，
不能用 mock、格式样例或本地测试替代真实 Reviewer 证据。
