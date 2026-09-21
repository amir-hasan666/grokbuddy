# Grok Bot Routine 配置记录（Phase 4，保持 disabled）

日期：2026-09-18（Asia/Shanghai）。状态：`DISABLED`。本文件只记录候选配置、当前账号只读可见项和后续受控验证要求；不是已创建 Routine 的导出。

## 当前账号只读观察

账号核对唯一允许的证据路径是：已登录 Grok Bot 桌面客户端 → 点击“workbuddy审核员”聊天标题 → 信息页 → `Routines`。本轮电脑控制面未开放原生应用访问，无法进入该路径。

| 观察面 | 实际可见内容 | 可得结论 |
|---|---|---|
| “workbuddy审核员”信息页 | 未能在 Grok Bot 桌面客户端打开 | `UNVERIFIED` |
| `Routines` | 未能进入 | Routine 列表、状态均 `UNVERIFIED` |
| 实际 trigger 名称 | 未在授权的桌面路径看到 | `UNVERIFIED` |
| 实际过滤字段 | 未在授权的桌面路径看到 | repo、PR、action、branch、actor、label 等均 `UNVERIFIED` |
| GitHub notification event integration | 未在授权的桌面路径看到 | 连接状态、主体、权限、event/subtype、filter、返回能力均 `UNVERIFIED` |
| “市场”中的 GitHub 插件 | 不作为本轮 Routine 证据 | 插件存在或已连接不证明 trigger，也不证明独立 Reviewer |

此前网页端自动化观察已由 Human 明确作废，本文件不再将其作为账号证据，也不从网页端或“市场”补推 Routine 能力。没有创建/编辑/启用 Routine，没有点击 Test run，没有模型调用。

公开官方文档只确认两类能力：Routine 可按 schedule 运行；Cursor account integrations 在支持时可由 GitHub notification 等 event 启动，而且 event integration 与普通 GitHub plugin 分开。官方文档没有为本项目列出可直接采用的 PR event 枚举或机器回调 API。

## primary 候选：PR 事件映射

设计标签：`pr-comment / review-*`。它们不是已确认的 Grok 官方事件名，也不是可直接注册的通配符。

目标是在以后获批的桌面 UI 中，寻找实际存在的 GitHub notification trigger，并确认能否严格限制：

- repository：`amir-hasan666/grokbuddy`，immutable repository id `1372874264`；
- resource：Pull Request；
- event/action：只允许确认为审核请求所需的实际选项；
- request：必须含一个 Hub 已存在、当前且 `PENDING` 的 `review_request_id` 和 AI-COLLAB v1 marker；
- identity：Routine owner 是独立 Reviewer B，provider identity 与 Builder A 不同；
- dedup：同一 RR 只认领一次，重投递不生成新轮次；
- exclusions：PR #2、`phase35-probe`、`TASK-7db0acee-8d15-425c-91b6-86177a86e70e`。

以上是项目必须满足的过滤条件，不声称是当前 UI 的字段名。当前 trigger 名、filter 字段、匹配表达式、GitHub connector 主体和结果 destination 全部 `UNVERIFIED`。primary 保持 disabled。

## fallback 候选：定时检查

仅当 primary 经证据确认不可用且 Human 另行选择时，才考虑一个定时 Routine 检查指定协作仓库/Hub 的待审指针。

必须限制一个 Reviewer B、一个 repository、一个当前 RR；使用 Hub RR ID 认领和去重；扫描窗口、时区、最坏等待必须小于冻结 deadline；查不到当前数据、Artifact/hash 不一致或权限不足时停止。不能同时与 primary 对同一 RR 唤醒，也不能把一次轮询当成新审核轮次。

当前账号的 schedule 字段、最小间隔、时区显示、pause 开关、长期无人值守策略均未在 Grok Bot 客户端看到，状态为 `ACCOUNT_UNVERIFIED`。fallback 保持 disabled。

## 输入、输出和失败路径

输入：GitHub 只承载短 marker/metadata/受控 pointer；完整 request、Profile 快照、Final Package、diff、日志和 Review JSON 属于 Artifact Store。Cloud Reviewer 不能假定读取本机路径。

输出：完整 AI-REVIEW v1 JSON 应进入不可变 `REVIEW_RESULT` Artifact，carrier 只返回短 pointer；Hub 再验 B 身份、hash、schema、冻结字段、Finding scope、deadline 和幂等。当前账号是否能写 Artifact、发 PR Comment、调用受限 Hub upload 或产生可拉取结果全部 `UNVERIFIED`。

失败：任何触发/过滤/身份/Artifact/返回路径不确定时，Routine 必须停止并在自己的会话报告失败；不得发送 PASS、不得改 GitHub/Hub 状态、不得盲重试、不得创建新轮次、不得切换成人工 Relay 后声称自动 E2E 完成。

## 后续受控 test run 的独立 Gate

本轮不执行。未来需 Human 新授权，并使用非 PR #2、非现有真实业务 Task 的一次性安全 fixture，才可核对：实际 trigger 名、严格 repo/PR filter、A != B、一次认领、Artifact read、结构化结果 write/carrier、Hub 拒绝错误 actor/hash/schema、timeout 与重复结果。任何一项缺证据，H8 不通过，Routine 继续 disabled。
