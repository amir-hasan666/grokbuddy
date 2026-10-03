# 给 WorkBuddy 的接入提示词

请更新我个人现有 GrokBuddy 规则或 Skill，让以下步骤在以后的正式任务中自动执行。此次只维护规则、核对工具，不建业务 Task、不重投历史 Task/RR、不触发审核、不部署或重启 Hub。不要让我重复粘贴本提示词。

先在现有 grokbuddy-hub 工具清单确认 submit_plan.supporting_artifact_ids、get_plan_review_readiness.planned_changed_files、preflight_final_review、begin_final_fix 可用；并检查 submit_plan 的 files 说明为整个 Task 后续变更白名单。不可见则报告进程未加载修改，不改连接配置、换身份或绕过工具。

以后执行正式任务时：

1. 方案依赖已有源码、配置或调查证据时，主动读取，以当前 Task 的 SOURCE_FILE/EVIDENCE 上传，向 submit_plan 传 supporting_artifact_ids。只绑定本方案实际需要的材料，不收集整个任务历史；保持非空 approved_scope。自己读取、上传、绑定，不要求 Human 转交。
   approved_scope.files 是整个 Task 拟新增、修改、删除的文件白名单，可以列尚未创建的后续编码文件；components 覆盖实际模块。它不等于冻结材料清单，不得泛化为“只列已提交文件”。从 Plan 的整个交付清单独立整理 planned_changed_files，在首次请求和 R2 前调用 get_plan_review_readiness；处理 scope_readiness.issues/missing_planned_files，未检查覆盖不得报告范围完整。不能通过这份只读清单扩大批准权限。
2. 终审前上传当前 Task 的差异、真实测试结果、交付文件全文，提供操作方法。generated_files 每项只传 path、artifact_id，SHA 由 Hub 生成。调用 preflight_final_review，输入是终审材料字段，不包含 expected_version、idempotency_key、begin_execution、reviewer_id。依据错误补材料并重新预检，直到 ready=true。
3. 检查 changed_files_without_source，说明没有全文的文件，尤其删除文件。该列表是覆盖信息，当前没有新增强制每个变更文件给全文的闸。预检不证明材料语义齐全、Worker 完成或测试通过，不代表 Reviewer PASS。原有条件满足后才调用 request_final_review；该工具会自动预检。
4. 方案整改先查 get_plan_review_readiness，按 Hub 当前 Finding 状态提交响应和证据，不把 OPEN/ACCEPTED 当已修复。返回 PENDING 后有界查询匹配的 get_plan_review/get_final_review 和 get_task_status，等待 Hub 实际结果。不要求 Human 转述 Grok 的话，不新建轮次或 Task 逃过错误。
5. 当前身份与权限能修复的材料、格式问题自行处理。只有需求歧义、权限不足、Human gate 或生产授权时向我提一条具体问题，带 Task/RR、失败步骤、可行选项，不只贴日志。
6. 终审 R1 整改按仓内终审技能：读取当前 Finding，OPEN 先 accept，已 ACCEPTED 不重复；在批准范围内调用 begin_final_fix，完成返回的新 Worker 工作项，再用当前 Task 证据逐项 fix。v2 fix 不自动启动执行，不用 request_final_review.begin_execution=true 替代；Worker 完成且本工作项 Findings 已 FIXED 后重做材料、自测和预检，提交 R2。FIXED 不等于 VERIFIED，不承诺 R2 PASS，最多两轮不变。

保留现有触发隔离、身份分离、Hub 唯一事实源、方案 PASS 后才编码、每阶段最多两轮和真实异步审核规则。禁止 mock、手动 wake、改业务数据库或 Human Continue 制造正式通过证据。密钥沿用安全配置，不输出到材料、聊天或日志。

完成后只回报：修改了哪份规则、新能力是否可见、尚缺什么。不宣称已做正式端到端验收。
