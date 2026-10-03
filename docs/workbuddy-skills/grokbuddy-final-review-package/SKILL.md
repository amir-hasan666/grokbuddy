---
name: grokbuddy-final-review-package
description: 在已授权的 GrokBuddy Hub Task 编码与自测完成后，装配终审材料（差异、真实测试结果、交付文件全文、操作方法与 generated_files），用 preflight_final_review 迭代到 ready=true，核对 changed_files_without_source 后调用 request_final_review 并等待 Hub 实际结果；不创建 Task，不处理方案 Finding，不代替 Reviewer 判定。
allowed-tools: mcp__grokbuddy-hub__get_task mcp__grokbuddy-hub__get_task_status mcp__grokbuddy-hub__submit_artifact mcp__grokbuddy-hub__preflight_final_review mcp__grokbuddy-hub__request_final_review mcp__grokbuddy-hub__get_final_review
---

# GrokBuddy 终审材料装配与预检

仅用于本 Task 方案已 `PLAN_APPROVED`、编码与 Worker 自测链已完成的终审阶段。Task ID、版本、RR ID 全部从 Hub 读取；不从自然语言 PASS、GitHub 或其他 Task 推断授权。

## 前置条件

调用 `get_task_status(task_id)`（必要时 `get_task`）确认：`state=EXECUTING`、`approved_plan_id` 非空、无活动 RR。

- 前置不满足 → 不做终审动作，展示 Hub 实际状态并回到相应阶段。
- 工具缺失 → 报告服务/MCP 版本未就绪，不用脚本、直接 DB、mock 或手动 worker 替代。

## 装配终审材料

1. 上传本 Task 的 `DIFF`（真实变更）、`TEST_RESULT`（真实自测输出）与交付文件全文（`SOURCE_FILE`）。内容必须来自实际执行的产出，不编造。
   - 承载 JSON 类文件二选一：把 JSON **序列化后的字符串**放进 `content_text`，或改用 `content_base64`；**不要直接把 JSON 对象传给 `content_text`**（会报 `content_text / Input should be a valid string`）。
2. `generated_files` 每项**只**写 `path` 与 `artifact_id`：`path` 是批准范围内的相对路径，且必须属于 `changed_files`。SHA256 由 Hub 生成，**不要自己传**，也不要伪造。
3. `operation_method` 写明可复现的操作方法（相对路径、命令、验证步骤）。
4. 每个写命令前读取 Task 最新 `version`；每个不同命令使用不同稳定 `idempotency_key`。

## 预检直到 ready=true

调用 `preflight_final_review`，输入**只**是终审材料字段：

`task_id` / `test_artifact_id` / `diff_artifact_id` / `change_scope` / `changed_files` / `self_test_summary` / `known_risks` / `unverified_items` / `operation_method` / `generated_files`

**不传** `expected_version`、`idempotency_key`、`begin_execution`、`reviewer_id`——它们不在该工具的 schema 内，工具为 `additionalProperties=false`，传入会直接失败。带这四个字段的是 `request_final_review`，不是预检。

`ready=false` 时按 `issues[].error_code` 与 `field_path` 补齐材料后重新预检，直到 `ready=true`。预检是只读的，失败不消耗审核轮次，也不改变 Task 版本。

预检通过后读返回的 `provided_file_paths` 与 `changed_files_without_source`：

- `changed_files_without_source = changed_files − generated_files.path`。该列表是**覆盖信息，不是阻断闸**：当前没有「每个变更文件都必须交全文」的强制项。
- 对其中文件（**尤其是删除文件**）在 `self_test_summary` 或 `change_scope` 中主动说明为何没有全文、该变更的影响与验证方式。不要沉默略过。
- `checked` = `package_material_contract` / `task_scope` / `artifact_bytes` / `approved_files`；`not_checked` = `worker_completion` / `self_test_transition` / `reviewer_delivery` / `semantic_material_completeness` / `async_application`。
- → 预检**不证明**材料语义齐全、Worker 已完成或自测通过，**不代表 Reviewer PASS**，也不代替 `request_final_review` 的原有守卫。

## 满足原有条件后请求终审

只有「Task 处于 EXECUTING + Worker 自测链已完成 + `changed_files` 全部落在批准范围内 + 材料合法」这些**原有条件**都满足时，才调用 `request_final_review`：

- `begin_execution=false`：本技能只在 Worker 已完成、Task 处于 `EXECUTING` 时提交终审，故固定传 `false`；`true` 是转 EXECUTING 并 offer 工作项的另一步，不属于终审提交。`expected_version` 取当前 Task 版本；`idempotency_key` 用新的稳定键。
- 该工具**会自动先跑预检**；不要为了绕过报错改成 `begin_execution=true`、改版本或重投。

返回 `PENDING` 只是请求收据。随后做**有界查询**：`get_final_review(review_request_id)` 搭配 `get_task_status(task_id)`，按 Hub 实际落库结果判断。

- 不要求 Human 转述 Reviewer 的话，不推测 verdict，不新建轮次或 Task 规避错误，不手动 wake。
- 只有 Hub 显示真实 Reviewer 结果才可对外报告；PENDING 未落库或超时时如实说明并停止自动推进。

## 自行处理与单点提问

材料格式、路径、字段、JSON 编码这类在当前身份与权限内可修复的问题，自行修复并重跑预检，不向 Human 转交。

只有**需求歧义、权限不足、Human gate 或生产授权**时，才向用户提**一条**具体问题，包含：Task/RR、失败步骤、可行选项。不只贴日志。

## 禁止

mock、手动 wake、直接改业务数据库、用 Human Continue 制造正式通过证据。密钥沿用安全配置，不写入材料、聊天或日志。`operation_method` 等受内容过滤约束的字段只写相对路径。
