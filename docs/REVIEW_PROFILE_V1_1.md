# GrokBot 通用审核规则 1.1

Profile 1.1 原实施范围：通用规则、按任务适用的专项规则、Reviewer 指令，以及不可变版本注册。
Hub 仍为唯一业务 SoT；该规则增量没有改变结果 Schema、状态机或默认版本，后续 Reviewer 取件改动属于独立维护。
2026-10-02 当前状态：正式 Hub 已注册 1.1，并已有冻结 1.1 的真实 Plan/Final APPLY 记录；这不证明外部 Reviewer 已加载本指令或审核质量改善。当前证据统一见 [生产基线](CURRENT_PRODUCTION_BASELINE.md) 和 [本次核对记录](MAINTENANCE_DOCS_REGRESSION_20261002.md)。规则不能由 Hub 从机制上保证模型发现所有问题。

## 规则来源与适用范围

[profiles.py](../src/grokbuddy/infrastructure/profiles.py) 是唯一 seed 规则源。
运行时以 Hub `review_profiles` 和 RR 冻结的原始 bytes/Hash 为准，Reviewer 不读取其他版本替换快照。

每个 1.1 快照是完整的字符串数组：通用规则 + 条件式检查 + 该 Profile 的专业补充。
规则编号在快照中以 `REQUIREMENTS:` 等前缀出现，便于说明依据，但不新增协议字段。

| 层次 | 内容 |
| --- | --- |
| 通用 | 适用性、需求、范围、一致性、可行性、证据、验收、副作用、阶段、证据缺口、裁决及复审。 |
| 条件式 | 软件、数据、调查分析、文档、网页视觉、创作及外部操作；依据需求和交付物选择，可组合。 |
| 专业 | Oracle、SQL Server、Python、IIS/Windows、文档的相关深入检查；generic 不强加某个专业领域。 |

创作不因缺少虚构事实引用而阻断，文案不强制代码测试，无数据库的任务不要求 SQL 检查。
方案审核不预先要求成品或生产测试；终审依据实际产物和验证范围作结论。
小建议不制造强制修订；R1 可直接 PASS，V1 R2 保持 PASS/BLOCK 和两轮上限。
细节从冻结 Profile 读取，当前 Reviewer 发布入口是 [1.1 指令](../grok_bot/reviewer_rules_v1_1.md)。

## 版本注册和试用

现有六个 Profile 名称保持不变：`generic`、`oracle_production`、`sql_server_production`、
`python_backend`、`iis_windows`、`document`。每类保留 1.0 并追加 1.1。
注册仍使用现有启动 seed 事务；同名同版本内容改变继续拒绝启动，必须发布新版本。
不执行生产数据库迁移或直接 DML。旧 Task、旧 RR、历史 Review 和 1.0 Hash 保持原样。

所有入口未传版本时仍为 `1.0`。试用操作如下：

1. 在另行授权的发布中加载包含新 seed 的运行版本，并将当前发布指令加载到独立 Reviewer；
   仓库文件更新不证明两个运行端已经更新。保持现有凭证、路由、触发与权限边界。
2. Human 指定新的试用任务；WorkBuddy 经正式 ingress 建单时显式传入 `profile_version="1.1"`，
   并选择现有 Profile 名称。跨领域任务可用 `generic`；不添加新名称，不悄悄降级到 1.0。
3. 核对该新 Task/RR 的版本、Profile Hash 和 Reviewer 实际读取的快照。若运行端没有 1.1，
   报告版本未发布，不用改已有 Task 或重建同一幂等请求绕过错误。
4. 通过正式主链完成指定案例的 Plan/Final 审核，保存 Hub 结果与证据。
   每阶段仍最多两轮；同 RR 重试不消耗新轮次，不靠手工 POST、mock 或临时 driver 证明通过。
5. 评分者独立检查漏报、误阻断、证据引用和阶段边界。全部满足后，另行决定是否改默认值。

暂停试用时停止指定新任务使用 1.1；不撤销已发布的快照、不重解释已有 Task、不改历史裁决。
修正规则须发布后续版本，不能原地修改持久化的 1.1。

## 证据和能力缺口

当前 `GET /reviewer/requests/<RR>/materials` 返回本轮授权材料清单，包含 input、Profile、context、原始需求与触发材料，以及 Final 包引用的 approved Plan、diff、测试和 generated_files。逐件读取仍须经过 RR/Task 绑定及 SHA 检查；同 Task 未列入清单的材料和跨 Task 材料继续拒绝。
这替代了 1.1 原实施时“只允许 input、Profile、context”的取件现状描述，未修改冻结 Profile 内容或历史裁决。运行端接口可用不等于外部 Reviewer 已实际读齐关键证据，新的端到端读取及质量复验仍需证据。

必要材料或视觉能力不可用时，Reviewer 报告技术缺口；不能把缺口当成“产物不存在”，
也不能声称已核验全部需求或实际显示。可读材料中缺少核心设计是实质内容问题。
符合已确认交付范围的阶段性未验证只需准确声明；不得外推为生产验收。

## 验证与交付

- [本地兼容测试](../tests/test_review_profiles_v1_1.py)：旧 Hash、追加版本、同版本变更拒绝、
  默认值、旧 Task/RR 保持、Plan/Final 快照和当前 Schema。
- [案例库](../tests/fixtures/review_profiles_v1_1/README.md)：跨类型正反例、allslowcheck 原版与修正版、
  改名改措辞、建议项、不适用项、技术失败及 R2 边界。期望答案不是实际 Reviewer 结果。
- [验证记录](REVIEW_PROFILE_V1_1_VALIDATION.md)：记录执行命令、实际结果和未完成的外部验证。

| Gate | 所需证据 | 当前状态 |
| --- | --- | --- |
| 本地版本和协议兼容 | 隔离测试及 diff 检查，见验证记录 | 2026-09-26 原结果保留；既有测试缺项与当前回归结果见本次核对记录 |
| 正式 Hub 使用 1.1 | 新 Task/RR 的版本、Hash、正式通道与 APPLY | READ-ONLY VERIFIED：指定历史 Task 的 Plan/Final 为 1.1，冻结 Hash 与注册值一致 |
| 外部 Reviewer 已加载当前指令 | 外部实际加载指令和完整材料读取记录 | NOT VERIFIED；不能由 Hub 版本/Hash 反推 |
| 审核质量改善 | 正式试用的真实结果、期望对照和独立评分 | NOT VERIFIED；历史 PASS 存在材料 403 说明，后续修复后尚缺独立复验 |
| 全面启用 | 质量通过后的单独决定 | NOT RUN；所有入口默认仍为 1.0 |
