# Profile 1.1 审核质量案例库

这些材料是离线评测 fixtures。`cases.json` 的期望结果、观测点和禁止的误阻断理由
只供评分者使用，**不能交给被评 Reviewer**。pytest 只检查案例和格式完整性，不运行模型，
不把期望 verdict 生成成实际审核结果。`execution_status=NOT_RUN` 不是生产状态。
案例 ID 及含 pass/defect 等提示的本地文件名也只供评分者使用；提交时使用中性标题和正常
Hub Artifact ID，只提供对应材料正文。不能把整个案例库或评分说明当作待审输入。

`inputs/` 是逐案盲测输入。allslowcheck 原版来自本次 Human 提交的方案正文，
保留了当时的矛盾；修正版是评测用修订，并非获批的业务 Plan。其余案例均为虚构离线场景。
技术失败案例说明受控故障条件，不要求 Reviewer 相信待审文字自称“不可读”；
正式评测必须实际具备对应的失败证据，否则记为测试条件未满足。

## 评分方式

1. 先核对实际提交材料、阶段和版本是否与案例一致；不一致则记为无效试用，不能算命中。
2. 评分者查看实际 Reviewer 结果，核对 expected_outcome 与 required_observations。
   观测点按含义与证据位置评分，不要求固定措辞或固定 Finding 数量。
3. 检查 forbidden_objections，识别不适用项、个人偏好、方案阶段提前索要成品等误阻断。
4. 每个事实、行号、渲染或测试执行声明须有实际读取或运行证据。记录遗漏及虚构引用。
5. `TECHNICAL_FAILURE` 只是评测分类，不是新增 Review verdict。应有技术失败说明，
   没有业务 PASS/BLOCK；不能为凑闭环制造业务裁决。

每类同时保留合格与实质缺陷例；`allslowcheck-renamed` 保留关键冲突但更换名称和措辞。
`minor-only`、`not-applicable`、`visual-unreadable` 等专门防止收紧规则造成误阻断。
R2 案例必须在真实冻结的 Finding context 下评价，输入中的示意引用不替代 Hub finding_id。

## 正式试用和证据表

真实 Reviewer 试用经单独授权后，使用指定新 Task、1.1 快照、独立身份及正常 WorkBuddy 主链。
评分答案不进入冻结的 Reviewer 输入。必须保证需要的原始需求、产物、测试等材料实际可读；
如果现有接口不能承载某例，应记为能力缺口，不用本地模型或人工 POST 冒充正式试用。
不得为了评测直接修改已有 Task、重写 Review 或突破同阶段两轮上限。

建议从 `allslowcheck-original` → `allslowcheck-revised` 的两轮修订、一个干净的 R1 PASS、
以及文档、视觉、纯创作的正反例开始；各案例条件须真实建立，不能仅将期望结果贴给模型。
每次试用记录：

| case_id | Task/RR | 实际 input/Profile Hash | 实际裁决或技术状态 | 命中与漏报 | 误阻断 | 引用错误 | 评分者/日期 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 未执行 | — | — | NOT RUN | — | — | — | — |

仅全部选定案例满足观测点、无所列误阻断且引用准确时，将该次试用记为通过。
失败须保留原结果；规则修订发布后续版本并选择新的试用任务，不修改已冻结的 1.1。

`results/` 中的 JSON 使用虚构 ID 和离线材料，只证明当前 Schema 能表达所需输出。
它们不能作为实际运行、Reviewer 判断或 Hub 状态的证明，也不得向生产发送。
