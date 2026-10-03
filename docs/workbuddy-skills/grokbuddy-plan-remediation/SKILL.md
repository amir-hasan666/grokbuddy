---
name: grokbuddy-plan-remediation
description: 在已授权的 GrokBuddy Hub Task 中提交方案（含 supporting_artifact_ids 支撑材料绑定）、处理方案 R1 Finding、提交修订和修复证据并准备 R2；不创建 Task，不处理 Final 修复，不恢复超时或 Human Gate。
allowed-tools: mcp__grokbuddy-hub__get_task mcp__grokbuddy-hub__get_plan_review mcp__grokbuddy-hub__get_plan_review_readiness mcp__grokbuddy-hub__get_task_status mcp__grokbuddy-hub__submit_artifact mcp__grokbuddy-hub__submit_plan mcp__grokbuddy-hub__respond_to_review mcp__grokbuddy-hub__request_plan_review
---

# GrokBuddy Plan Finding remediation

仅用于 Human 已授权推进的当前 Hub Task。Task ID、Finding ID、Review ID 和状态全部从 Hub 读取；不从自然语言 PASS、GitHub 或其他 Task 推断授权。方案尚未获 Hub `PLAN_APPROVED` 时只修改方案，不编码。

首次提交方案和后续修订都适用下面的材料绑定规则；R1 Finding 的整改见「完成一次方案整改」。

## 方案材料绑定（首次提交与修订通用）

方案依赖已有源码、配置或调查结论时，**自己读取、自己上传、自己绑定**，不要求 Human 转交材料：

1. 读取本方案实际依赖的源码/配置/调查证据，用 `submit_artifact` 上传为当前 Task 的 `SOURCE_FILE`（源码或配置全文）或 `EVIDENCE`（调查结论与依据）。
2. 调用 `submit_plan` 时把这些制品 ID 放进 `supporting_artifact_ids`，并在计划正文里写明每份材料的用途与位置。
3. 只绑定**本方案实际需要**的材料，不把整个任务历史打包进来。`approved_scope` 是**整个 Task 后续变更白名单**：files 逐项列出拟新增、修改、删除的相对文件路径，可以包括尚未创建的编码、测试、报告和说明文件；summary/components 覆盖实际工作与模块。它不等于本轮材料清单，不能要求“只声明已提交的文件”，也不能仅因当前只上传 PLAN.md 就把范围缩成 PLAN.md。目录和通配符不覆盖子文件。只有原需求确实仅交付文档时，文档白名单才完整。
4. 材料白名单只覆盖**同 Task 且被显式引用**的 `SOURCE_FILE`/`EVIDENCE`：同 Task 未引用的、以及跨 Task 的材料都不开放。更新方案**不会**改写旧 RR 已冻结的清单——要换材料必须重提方案并在新的 `supporting_artifact_ids` 中引用。
5. 材料绑定只是引用检查，不代替 Reviewer 实际取件与质量判断；绑定成功不等于方案会通过。

完整语义见 [Plan scope contract](../../contracts/PLAN_SCOPE_CONTRACT.md)。首次提交和修订后，从 Plan 的整个任务交付清单**独立整理** `planned_changed_files`，调用 `get_plan_review_readiness(task_id, planned_changed_files=...)`。不要照抄 scope 掩盖遗漏。处理 `scope_readiness.issues` 和 `missing_planned_files`；未传清单的 `file_coverage=NOT_CHECKED` 不能报告为“范围完整”。查询不会增补权限或消费轮次；已批准任务不得靠查询结果改 scope。

## 先读取当前状态

调用 `grokbuddy-hub.get_plan_review_readiness(task_id)` 和 `get_task(task_id)`，必要时用 `get_plan_review(review_request_id)` 阅读 R1 的 `result`、整改建议和证据。

- 工具缺失时报告版本未就绪，不用脚本、直接 DB、mock 或手动 worker 替代。
- Task 已终结、过期、进入 `PLAN_HUMAN_REVIEW` 或自动化冻结时停止，展示 Hub 状态、原因和当前材料，等待 Human 决策。R2 超时不是 Reviewer BLOCK；不得重投旧 RR、改轮次、追加第三轮或代 Human 调用 Gate。
- `PLAN_APPROVED` 时本技能结束；后续工作只能绑定本 Task 的 approved Plan 和 scope。
- `active_rr_id` 非空时只查询对应 RR；Finding 回应和内容已冻结，不提交 accept/fix 或新 RR。活动 R2 的 `rounds_remaining=0` 不影响等待这轮合法结果。
- 无活动 RR、尚未批准且 `rounds_remaining=0` 时停止，展示轮次已用尽，等待 Human 决策。

## 完成一次方案整改

在 R1 `NEEDS_CHANGES`/`BLOCK` 后，对 Hub 返回的本阶段 Finding 逐条处理，保持原 `finding_id` 和所属 R1 `review_id`：

1. 对准备修复的 `OPEN` Finding 调用 `respond_to_review(action="accept")`。`ACCEPTED` 不重复 accept；已关闭或 `advisory=true` 的项不再次修复。若有理由不采纳，提交证据后使用 `reject`，保留 `REJECTED_WITH_EVIDENCE` 等 Reviewer 判断，不伪称已关闭。
2. 根据 R1 意见一次修订方案，先上传大写 `PLAN` Artifact，保留返回的 Plan ID。若 Hub 已是 `PLANNING` 且修订已提交，不盲目重复提交。
3. 用 `submit_artifact` 上传本 Task 的 `EVIDENCE`，逐项写明 Finding ID、修改前后、修订 Plan ID、位置和实际检查结果，不编造自检。Builder fix 也支持 `DIFF/TEST_RESULT`，但当前方案 supporting materials 只接受 `SOURCE_FILE/EVIDENCE`；需要 Reviewer 读取的修复说明应使用 `EVIDENCE`。PLAN Artifact 本身不能作为 Builder fix 的证据。
4. 使用 `submit_plan` 提交 Plan ID、非空结构化 `approved_scope` 和 `supporting_artifact_ids` 中的修复 EVIDENCE ID。从 `PLAN_CHANGES_REQUIRED` 进入 `PLANNING`。Hub 将这些明确引用连同哈希冻结进下一轮 RR，Reviewer 可通过材料白名单读取。同 Task 的未列入证据仍不可读取；如果修订已提交而必读材料没有绑定，报告准备缺口，不绕过材料权限或盲目再次提交修订。
5. 对 `ACCEPTED` Finding 调用 `respond_to_review(action="fix", evidence_artifact_id=...)`，引用上述修复证据。方案 fix 应使 Finding 变为 `FIXED`，Task 保持 `PLANNING`，不启动 Worker。`FIXED` 仍等待 Reviewer 验证，不代表 PASS。

每个修改命令前读取 Task 的最新 `version`，传给 `expected_version`；不是 Finding version。每个不同命令使用不同稳定 `idempotency_key`。若响应不确定，复用同一个 key 和完全相同的参数，不改 version 盲重试；先查询实际状态。版本冲突后重新读取并核对已完成的操作，再决定剩余步骤。

## 核对后请求 R2

再次调用 `get_plan_review_readiness`，传入从整个任务交付清单整理的 `planned_changed_files`，核对范围缺项、每条 Finding 状态和 `next_action`。准备修复的项不得遗漏 accept、证据或 fix；`unready_findings` 列出仍为 OPEN/ACCEPTED 的项，`unbound_fix_evidence` 列出 FIXED 但修复证据尚未绑定到当前方案材料的项。材料绑定只是引用检查，不代替 Reviewer 实际取件和核验。`FIXED` 和 `REJECTED_WITH_EVIDENCE` 在下一轮等 Reviewer verification。

`can_request_review` 只表示读取时的基本请求条件；`ready_for_review` 是整改准备提示，均不是授权或 PASS，实际请求继续接受 Hub 全部校验。若 R1 实质问题无法解决，保留问题与证据，不伪造 FIXED；在当前有效授权和剩余轮次内仍可提交 R2 让 Reviewer 判断 BLOCK，准备提示不是禁止这条合法路径的新守卫。

确认当前 Plan、Finding 状态、Task version、Reviewer 身份和剩余轮次后，只调用一次 `request_plan_review`，正式 Reviewer 保持 `grok-reviewer-b`。记录返回的 RR ID。

`PENDING` 只是请求收据，不是结论。之后做**有界查询**，等待 Hub 实际落库结果：

- 用 `get_plan_review(review_request_id)` 读该方案 RR 的结果，用 `get_task_status(task_id)` 读状态、版本、活动 RR 与截止时间。终审材料和等待由独立终审技能负责。
- 匹配到的 RR 才是本次结果；不把别的 Task 的 RR 当成本任务结论。
- 不要求 Human 转述 Grok/Reviewer 的话，不推测 verdict，不新建轮次或 Task 规避错误，不手动 wake。
- 只有 Hub 显示真实 Reviewer 结果才可对外报告；PENDING 未落库或超时时如实说明并停止自动推进。

R2 仅接受 PASS/BLOCK。只有 Hub 已 APPLY PASS 并显示 `PLAN_APPROVED` 才可进入后续编码；R2 BLOCK 或技术失败时显示 R1/R2 方案、意见、理由和当前 Hub Gate，停止自动推进。

## 自行处理与单点提问

材料格式、字段、JSON 编码、制品类型、路径这类在当前身份与权限内可修复的问题，自行修复后重提，不向 Human 转交，也不把 `OPEN`/`ACCEPTED` 当作已修复。

只有**需求歧义、权限不足、Human gate 或生产授权**时，才向用户提**一条**具体问题，包含：Task/RR、失败步骤、可行选项。不只贴日志。

## 禁止

mock、手动 wake、直接改业务数据库、用 Human Continue 制造正式通过证据。密钥沿用安全配置，不写入材料、聊天或日志；`record_workbuddy_message` 正文等受内容过滤约束的字段只写相对路径。
