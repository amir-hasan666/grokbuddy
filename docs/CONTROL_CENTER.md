# V1 Control Center（本地只读实现）

Control Center 是 Hub 记录的 Human 只读页面。它不写 Task、Review、Finding 或 verdict。页面从同一 Hub SQLite 数据库查询 Task、Review Request、已 APPLY 的 Review、Artifact、Audit、Task Event、Finding Event、Worker Assignment 和 Human Approval。最近 Task 列表最多 100 条；可以用完整 Task ID 精确查找更早的记录。时间线每页 100 项，按 Hub 时间与稳定记录键排序，可一直翻到末页。

## 启用与访问

代码默认关闭。在受控 HTTPS 入口运行 composite 时，设置一个独立的至少 32 UTF-8 字节的 Human 只读 token 环境变量，并传入 --control-token-env GROKBUDDY_CONTROL_READ_TOKEN。Windows 启动脚本只有在服务配置的 controlCenterEnabled 设为 true 时才从 Credential Manager 的 GrokBuddy/GROKBUDDY_CONTROL_READ_TOKEN 目标读取它。当前配置为 false，此改动不会启动或重启服务。

访问 /control/ 时浏览器使用 HTTP Basic Auth：用户名 human，密码为上述 token。所有页面、API、预览和下载都要求该凭证。入口仅接受 GET/HEAD，响应禁缓存、禁跨域、设置 CSP；页面用文本节点渲染 Hub 内容。此凭证和 MCP、Webhook、Reviewer 凭证相互独立，不能写入配置文件、源码或日志。

## Hub 字段与展示边界

| 内容 | Hub 来源 | 缺项展示 |
| --- | --- | --- |
| Task 状态和冻结策略 | tasks | 旧记录按历史规则标注 |
| Human 原始需求、方案 V1/V2 | Task 原始 SOURCE_FILE、每轮 RR 的 input_artifact_id 指向 PLAN | “Hub 未留存” |
| GrokBot 文案和两轮理由 | 已 APPLY 的 reviews.result_snapshot 或 REVIEW_RESULT Artifact，另验 Reviewer 身份 | 无 Review 时显示等待、无效结果或技术故障 |
| WorkBuddy 独立业务文案 | 新的 WORKBUDDY_MESSAGE Artifact，固定 Builder 身份、阶段与 Hub 时间 | “Hub 未留存” |
| 操作方法、生成文件、代码、测试 | 每轮 FINAL_PACKAGE 的 operation_method、逐文件 generated_files、DIFF、TEST_RESULT | 逐项“Hub 未留存” |
| Human 决策 | human_approvals 和理由 Artifact；Task completion_basis | “Hub 未留存”，绝不转成 GrokBot PASS |
| 完整已留存时间线 | Audit、Task Event、Artifact、RR、Review、Worker、Finding、Human 记录 | 外部未入 Hub 的对话无法补造 |

GrokBot 标签只用于 Hub 已 APPLY、RR 已完成、Reviewer actor 为指定 Grok 身份且结果声明为同一 grok_bot 的 Review。Webhook ACK、Reviewer 取件、技术故障和 Human override 都不会显示为 GrokBot PASS。R2 有效产品结论只有 PASS 或 BLOCKED；R2 NEEDS_CHANGES 回传若被 Hub 拒绝，页面显示“结果无效”和安全故障码。方案 R2 BLOCKED 专区保留方案 V1、R1、方案 V2 和 R2 理由；终审 R2 BLOCKED 专区继续显示操作方法、文件、测试、R2 理由与“未验收通过”。

附件读取需要 Task ID 与 Artifact ID 双重绑定，并且 Artifact 必须从原始需求、轮次输入、WorkBuddy 文案、最终包文件/测试/差异或 Human 理由可追溯。读取时复核 Artifact 哈希和大小；不返回存储路径、原始 Audit JSON、运行日志或 Reviewer 原始负载。文件强制附件下载；仅接受 UTF-8 文本，并拒绝包含明显 Secret、Authorization header 或本机绝对路径的内容。若过滤器拦截一个历史文件，页面显示不可查看，而不以其他来源补造内容。

## 新 V1 留存调用

Builder 使用 record_workbuddy_message(task_id, stage, body, idempotency_key) 留存消息原文；阶段为 PLAN、PLAN_REVISION、CODE、TEST 或 DELIVERY。每次调用创建一个不可变 WORKBUDDY_MESSAGE Artifact 和 Audit。新 V1 Task 的 Final Package 必须含非空 operation_method 与 generated_files。每个文件项含批准范围内的相对路径、同 Task 的 SOURCE_FILE Artifact ID 和哈希。网关的 request_final_review 可接收 operation_method 与 {path, artifact_id} 文件项，并由 Hub 核查哈希、Task 归属和批准范围。

编排侧需要在真实 WorkBuddy 消息产生时调用留存工具，上传实际生成文件，再提交 Final Package。旧 Task 不迁移，未进入 Hub 的消息和文件保持缺失。这里的本地测试只验证实现行为；启用、生产数据留存和 V1 6.21/6.22 验收须另行执行，不能由本地 UI 测试替代。
