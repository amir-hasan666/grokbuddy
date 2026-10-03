# 给 WorkBuddy 的当前 Task 续办提示词

仅在维护者已确认相关修复完成正式发布、Hub MCP 进程和工具缓存加载新版本后使用。仓库本地修改完成不满足这个前提。本提示词是供 Human 发给 WorkBuddy 的业务续办授权模板，本次 Codex 维护不会执行它。

```text
继续现有 TASK-84255b22-cd5c-487f-b2be-c8b9dbbbb7bd，按流水线走完。

先只读核对 Hub 最新 Task、终审 R1、Finding 状态，以及 grokbuddy-hub.begin_final_fix 是否可见。不要依据上次报告写死 version=10，不新建任务、不重写历史审核。

如状态仍为 FINAL_CHANGES_REQUIRED、已批准方案和范围有效、无活动 RR：
1. 读取三条 Finding 的当前状态与 final_fix_finding_ids。OPEN 项逐条 accept；已 ACCEPTED 不重复。已 FIXED 或已有整改 assignment 时核对证据和工作项，按实际状态续办。
2. 从批准的文件/模块范围整理这次实际整改的 proposed_scope，以最新 Task version 和稳定幂等键调用 begin_final_fix。集合只含本次整改的冻结 Finding ID。仅 EXECUTING 返回允许进入整改；PLAN_CHANGE_REQUIRED、权限或 Human gate 错误如实报告，不扩范围绕审。
3. 保存返回的 assignment ID/generation，通过独立 grokbuddy-worker 工具读取、claim、重新核验或完成整改，提交真实 EVIDENCE、report_progress、complete_task。原先已上传的探针/报告/JSON不等于新 assignment 已完成。Worker命令用工作项版本，Hub命令用Task版本。
4. 用本 Task 的有效 EVIDENCE/TEST_RESULT/DIFF 逐项 respond_to_review(fix)，保留 Worker 完成凭据和每条整改依据。每次取最新 Task version；不重复隐式执行，不传 begin_execution=true绕过入口。
5. 重新核对产物字节/hash、真实差异、自测结果、generated_files 和操作方法。把引擎/微信/人工测试仍未完成的项明确列入 unverified_items，不能声称已实测通过。先 preflight_final_review；Worker完成、本工作项Findings已FIXED及原有条件均满足后，begin_execution=false提交唯一终审R2。
6. PENDING只是收据，有界查询Hub真实结果及Reviewer verification，不承诺PASS。若R2 BLOCKED/Human gate，展示产物和理由并停止自动推进；不得新增R3、手动wake、直接改库或用Human Continue冒充PASS。

本次续办只针对Phase 0现有任务。Plan §3.3的真实安装、微信登录、测试好友与窗口状态验证门禁仍须满足，未满足不得进入后续V1业务编码。
```
