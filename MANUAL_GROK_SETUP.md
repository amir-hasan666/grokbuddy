# Grok Bot Reviewer 人工配置手册（Phase 4，未执行）

本手册用于以后获得单独 Human 授权后的 Grok Bot 桌面端配置和受控 test run。本轮只完成协议与配置核对；没有创建 Routine、没有 Test run、没有真实模型调用，也没有处理 PR #2 或现有 Task。

## 当前结论

- primary：PR 事件映射候选，设计标签 `pr-comment / review-*`，实际 Grok trigger 名与过滤项 `UNVERIFIED`；disabled。
- fallback：定时检查候选，公开文档确认 schedule 类别，当前账号字段与行为 `ACCOUNT_UNVERIFIED`；disabled。
- 此前网页端自动化观察已由 Human 明确作废，不再作为账号证据。账号核对只允许走 Grok Bot 桌面客户端“workbuddy审核员”聊天标题 → 信息页 → `Routines`。
- B 独立身份、严格 repo/PR 过滤、Artifact 访问、结构化结果 carrier 均 `UNVERIFIED`。

## 访问路径

```text
Hub DB (SoT)
  -> 冻结 ReviewRequest + Profile snapshot + input artifact/hash
  -> GitHub 短 AI-COLLAB marker / 受控 pointer
  -> 经当前账号验证的 Grok Bot trigger（尚未确认）
  -> 独立 Reviewer B 读取受认证或不可变 artifact
  -> REVIEW_RESULT artifact + 短 AI-REVIEW carrier（尚未确认）
  -> signed webhook 或 authenticated pull
  -> Hub inbox -> 身份/hash/schema/语义/deadline/幂等校验
  -> normalized event handler -> Hub commit + Audit + Outbox
```

GitHub、Routine 和 Comment 都不是事实源。Human Relay 只能以 `HUMAN_RELAY` provenance 登记原始输出，不能冒充 Reviewer B 自动回传。

## A. 仅查看配置（本轮允许的边界）

1. 在已登录的 Grok Bot 桌面客户端点击“workbuddy审核员”聊天标题，进入信息页，再打开 `Routines`。
2. 只记录现有 Routine、状态、实际 trigger 下拉名称和实际 filter 字段；不要创建、编辑、启用、暂停或删除。
3. 检查 event integration 是否单独于 GitHub plugin/connector，记录当前连接主体的不可变 provider identity；不要读取或复制 Token。
4. 记录是否能选择明确的 repository id、Pull Request resource、event/action、PR/branch/actor 等过滤项。只写 UI 实际文字；看不到就写 `UNVERIFIED`。
5. 记录结果可以返回到哪里：Bot conversation、GitHub Comment、文件/Artifact、Webhook/其他。不要尝试写入。
6. “市场”中的 GitHub 已连接只说明插件存在，不算 Routine trigger，也不能证明独立 Reviewer；不得把它写成账号 Gate 证据。
7. 若无法进入上述桌面客户端路径，停止；不得用网页端、“市场”或 xAI 模型 API替代。

本轮因无法进入 Grok Bot 桌面客户端，上述账号项未完成，只留下明确 `UNVERIFIED`。

## B. 后续配置前置 Gate（需要新授权）

必须同时具备：

- 一个注册为 Reviewer 的独立 B principal；其 provider ID 与 Builder A 不同；
- 仅目标测试仓库的读取/评论最小权限，无 admin、deploy、merge/approve、生产 contents write；
- Hub 冻结的 review request 和 Profile snapshot；
- 经验证的云端 Artifact 读取与结果写入方案；
- 一次性非生产 PR/Task fixture，明确排除 PR #2、`phase35-probe` 和 `TASK-7db0acee-8d15-425c-91b6-86177a86e70e`；
- 人工批准的成本、deadline、停止和清理边界。

任一缺失则不创建 Routine。

## C. 后续 primary 配置（不要在本轮执行）

1. 选择实际 UI 中存在的 GitHub notification event integration；不要输入文档里没有出现的 event 名。
2. 将实际 trigger 名原样记录到 Phase 报告。`pr-comment / review-*` 仅用于对照设计意图。
3. 按 UI 实际字段把范围缩到 repository id `1372874264`、Pull Request 和批准的测试 resource；如果不能严格过滤 repo/PR，停止。
4. 设置 Routine owner 为独立 B，并验证 provider ID；不能靠 display name 判断。
5. 引用 `grok_bot/reviewer_skill.md`；不要复制 Profile 业务规则，运行时读取冻结快照并校验 hash。
6. 配置缺数据、stale data、deadline、重复认领、模糊投递和权限请求的停止行为。
7. 保持 disabled，保存前再次确认没有 Test run、没有 PR #2/真实 Task、没有持续监听。

是否存在“保存但 disabled”的 UI 行为当前未验证；若保存会立即启用或触发运行，取消并停止。

## D. 后续 fallback 配置（不要在本轮执行）

只有 primary 已证实不可用且 Human 明确选择 fallback 时，才创建定时检查。必须记录实际 schedule 字段、时区、最小周期、pause/active 控件；把扫描限制到一个当前 RR，并以 RR ID 去重。不得与 primary 同时消费同一 RR。

## E. 后续受控 test run（单独授权）

Test run 会执行真实工作，不能由 Phase 4 文档验收自动授权。未来测试至少覆盖：

1. 一个安全 fixture 的 trigger -> run provenance；
2. B != A 与错误 actor 拒绝；
3. Profile/input Artifact 可读且 hash 相符；
4. PLAN 或 FINAL 的严格 JSON schema；
5. 结果 Artifact/hash/carrier 可由 Hub取得；
6. invalid JSON、错误 hash、错误 actor、重复结果、超时均不推进 Task；
7. 一次 RR 只产生一次 evaluation，不新建轮次；
8. 结束后 Routine 回到 disabled，无持续真实审核。

所有 run ID、resource ID、RR ID、hash 和脱敏截图/记录进入 Phase 6 之前的受控证据；Secret、原始长 JSON、日志和业务 Artifact 不贴 GitHub Comment。

## F. 立即停止条件

- UI 无法严格限制 repository/PR；
- 当前身份可能与 Builder A 相同；
- 只支持聊天文本，无法保留可验证的原始结果 provenance；
- 云端无法读取冻结 Artifact 或结果无不可变 hash；
- 页面要求 Token 明文、扩大权限、contents write、merge/approve 或生产动作；
- Test run 会命中 PR #2、现有 Task 或持续监听；
- 任何配置、投递或回调状态不确定。

停止后只报告 `UNVERIFIED` / `BLOCKED` 和缺失证据，不重构 Hub，不切换到 xAI 模型 API，不进入 Phase 5/6。
