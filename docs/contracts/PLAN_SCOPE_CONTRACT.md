# Plan scope and review materials

本合同澄清既有 v2 Task 的范围语义，不修改 V1 双轮政策，不授权修改历史 Task。`approved_scope` 是方案通过后整个 Task 的变更权限；提交方案时参数虽名为 `approved_scope`，Hub 先保存为 `current_plan_scope`，真实 Reviewer PASS 后才保存为 `approved_scope`。

## 两份清单

| 字段 | 含义 | 时间与要求 |
| --- | --- | --- |
| `approved_scope.files` / `current_plan_scope.files` | 本任务拟新增、修改、删除的文件白名单 | 使用逐字匹配的相对路径；可以包含尚未创建的后续编码、测试、报告和说明文件。不能把目录或通配符当作覆盖子文件的规则。 |
| `supporting_artifact_ids` | 本轮方案审核实际依赖的已有源码、配置、调查或整改证据 | 先上传到同 Task 的 SOURCE_FILE/EVIDENCE，再显式绑定；未引用和跨 Task 材料不可读取。 |

`scope.summary/components` 描述整个 Task 的工作和模块，不只描述正在上传的 Plan 文档。白名单不是“本轮已提交文件清单”，不要求与冻结材料相等。未来文件被列入白名单不等于已实现，方案 PASS 前仍禁止编码。

Reviewer 检查本轮依赖材料是否完整，并核对原需求、Plan 目标及白名单是否一致。Plan 引用的独立调查证据须绑定为 supporting material，或把完整证据内联进 Plan。不能据“缺失一份被引用证据”推导出“未来编码文件不得进入 scope”。如果原需求只交付文档，文档路径白名单合法；不按扩展名或是否只有 PLAN.md 一刀切判错。

终审保持 `changed_files ⊆ approved_scope.files`；新增白名单文件需要合法的方案审批路径，不能由 Builder、Reviewer 建议或准备度查询自动补权。V1 每阶段最多两轮仍成立。

## 冻结 scope 快照，版本 1

部署本实现后，新建 **v2 PLAN_REVIEW** RR 的既有 context Artifact 增加 `plan_scope`：

```json
{
  "plan_scope": {
    "schema_version": 1,
    "scope": {"files": ["app/main.py"], "components": ["app"]},
    "sha256": "<Hub canonical JSON SHA-256 of scope>"
  }
}
```

机器结构见 [common schema](common.schema.json) 的 `$defs/approved_plan_scope` 和 `$defs/plan_scope_snapshot_v1`；正例及真实哈希见 [scope snapshot example](examples/plan-scope-snapshot.json)。`scope` 保留既有非空 summary/files/components 结构兼容性；其中缺少 files 的情况由准备检查提示，不借本次增补改变旧请求守卫。

哈希只覆盖 `scope` 对象：UTF-8 JSON，键排序，`ensure_ascii=false`，逗号/冒号之间无空格，不允许 NaN。数组顺序参与哈希。Hub 在创建 RR 前校验结构及当前 scope/hash 相符；快照随 context 的不可变 Artifact 字节冻结。Reviewer 从 `review_materials.context` 认证取件，先核验 Artifact 哈希，再按上述算法核验 scope 哈希。

这是 context 内的 **版本化增补**，不增加 Review request/result 信封字段；现有 v1/v2 信封及 `grokbuddy-v1-dual-round` 不变。未知快照版本不得擅自套用版本1解释。历史 context 缺少 `plan_scope` 时记录“无冻结 scope 快照”，沿用历史材料，不从当前 Task 重建、回填或修改旧 RR。Final context 与历史 profile/hash 均不迁移。schema bundle 仍含原四份根 schema，新增定义通过 common 的 `$ref` 提供。

## 只读方案准备检查，版本 1

`get_plan_review_readiness(task_id, planned_changed_files=None)` 向已有 Builder 查询增加可选文件清单。WorkBuddy 应从 Plan 的整个任务交付清单独立整理这些路径，而不是照抄 scope；首次提交和 R2 请求前均应核对。只交付文档时就传文档路径。该清单不保存、不增加授权、不消费轮次，也不自动解析 Markdown。

旧的仅 task_id 调用仍可用。新增返回 `scope_readiness.schema_version=1`，含 `scope_semantics=task_change_allowlist`、scope 哈希、是否做覆盖检查、缺项、问题和未检查内容：

| 诊断 | 含义 |
| --- | --- |
| `PLAN_SCOPE_MISSING` | 当前范围或其哈希尚未提交 |
| `PLAN_SCOPE_HASH_MISMATCH` | 当前结构化范围与其存储哈希不符 |
| `PLAN_SCOPE_FILES_MISSING` | 范围没有文件清单，无法声明后续非空终审文件 |
| `PLAN_SCOPE_FILES_NOT_EXACT` | 路径无法满足终审相对路径要求，或被误写为目录/通配符 |
| `PLAN_SCOPE_FILES_INCOMPLETE` | 显式计划文件超出 scope；`missing_planned_files` 列出缺项 |

`file_coverage=COMPLETE/INCOMPLETE` 只描述显式传入清单的集合覆盖。未传清单或非 v2 Task 时是 `NOT_CHECKED`；`not_checked` 始终包含 `plan_body_semantics`。准备提示不是 Reviewer PASS，不能证明 WorkBuddy 提供的清单完整，更不能替代 Reviewer 的实质检查。已知 scope 问题使 `ready_for_review=false`，但 `can_request_review` 继续表示既有请求守卫，合法的 R2 BLOCK 路径不被准备提示另行禁止。
