# Phase 6.21 Case G — same-RR re-wake Human 演练卡

状态：**仅供部署后演练；当前 Case G 仍 BLOCKED。** 本卡不改写任何带日期的历史 Phase 报告，不授权创建 Task、生产部署、重启或人工补数据。

## 开始门禁

1. 仓内 same-RR re-wake 专项与全量 regression PASS，审阅修改范围和非 Secret Audit 字段。
2. Human 按现有正式 Windows 运维流程部署已审阅代码并重启正式 Hub；记录代码版本、PID/启动时间和 `/ready` 中 `database=ok`、`supervisor=ok`，确认常驻 worker 包含 `reviewer_wake`。不得把本地 `LocalRuntime`、`*_once` 或测试日志当成生产部署证据。
3. 只读确认 `config/grokbuddy.service.json` 指向正式 runtime，wake 环境变量名已配置，Credential probe 仅报告 `PRESENT`；不读取、打印或写出 URL、key、token。
4. 上述三项缺一则停止，不创建新的 G Task。RR deadline 已过的历史样本不能复活。

## 首次暂停状态码诊断（先于 Case G）

正式代码已部署且第 1–3 项通过后，下一次 Human 授权的受控暂停 consumer 测试只承担 wake HTTP 分类取证，不计入 Case G。按正式入口形成一个隔离 RR，保持 Hub/Supervisor 常驻；暂停 webhook consumer 后等 Supervisor 自行尝试 wake，再只读记录对应收据和 Audit 的 `last_http_status_code`、安全错误码、attempt、`next_retry_at`、`terminal_reason`。随后恢复 consumer 原状态。不得手动 POST、Run poller、改库或复活旧 timeout RR。

如果返回已知可恢复类别，观察 same-RR 自动 retry、认证 intake ACK 和真实 ReviewCompleted/APPLY；如果返回未知 4xx，保留 fail-closed 结果，不以这条诊断 RR 继续 Case G。依据这次真实状态码和平台含义审定精确分类，完成针对性代码、回归、再次部署验证后，才开始下列 Case G 演练。仅有历史 `WAKE_HTTP_REJECTED` 而无状态码时不得推断类别。

## 演练步骤

1. Human 记录 Reviewer poller 与 webhook consumer 原状态，使用各自正式控制面临时暂停两者。Hub/Supervisor 保持运行。记录暂停时间、操作者、恢复计划。
2. 经正式 `grokbuddy-ingress` 创建 Case G 专用 Task A 和隔离哨兵 Task B；只使用已授权的 `grokbuddy-hub` 命令为 A 提交 Plan，并用固定 idempotency key 请求一次 Plan RR。重放相同命令和 key 一次，确认返回原 RR。B 的建单期 SOURCE_FILE 以 S0 快照为准。
3. 对正式 Hub 库作**只读** S0/S1 快照：A 的 Task/RR/round/outbox/intake/wake receipt ID 与计数、RR deadline、`expected_task_version`、`expected_reviewer_actor_id`、envelope hash、outbox `delivery_key`、wake `attempts/next_retry_at/recovery_reason/terminal_reason`；B 的原有 Artifact ID 集与 Task/RR/round/Review/Finding/assignment/outbox/inbox/Audit 基线。不得直接 DML。
4. 等待常驻 Supervisor 自行产生 wake 失败或 transport ACK 但 HTTP intake 未 ACK 的收据。只读记录 `last_http_status_code`、安全错误码、Audit、`next_retry_at` 和 deadline。历史暂停窗口只保存 `WAKE_HTTP_REJECTED`，不能推断它的状态码；下一次受控暂停若再次返回 4xx，先以这次新字段取证并停止 Case G，把真实状态码与平台语义审定后再更新分类和部署，不能临时把整个 4xx 类别改成可重试。已确认的 `WAKE_CONSUMER_UNAVAILABLE`、`WAKE_TIMEOUT`、`WAKE_NETWORK_ERROR`、`WAKE_HTTP_RETRYABLE`，或 transport `ACKED` 且 intake `READY` 才可继续；身份/route 错配、RR stale 或 deadline 到达立即停止。Human 不手动 Run poller、不手动 POST wake。
5. 在 RR 仍 PENDING 且距 deadline 足够覆盖下一次 `next_retry_at`、Reviewer 执行和 APPLY 时，由 Human 按现有运维流程做一次正式 Hub restart。记录旧/新 PID、启动时间与 `/ready`。在新进程中只读确认原 wake 收据、attempt、`next_retry_at` 与冻结 RR/outbox 字段未丢失。
6. Human 恢复 webhook consumer 至步骤 1 记录的原状态；保持 poller 暂停，直到 webhook 自动恢复链取证结束。等待正式 Supervisor 到期自动发送**原 RR** wake。依据 durable attempt/Audit 和接收端记录核对：没有手动 Run、手动 POST、临时 driver、`*_once`、LocalRuntime、mock 或人工改库。
7. 等待真实 Reviewer B 通过认证 HTTP intake ACK、提交 ReviewCompleted，常驻 Supervisor APPLY。只读 S2 核对：同一 RR `COMPLETED`、一条 Review、原 round、原 outbox `SENT`、Reviewer actor 与冻结身份一致、Task 的真实结果、wake 收据终止原因为 `REVIEWER_INTAKE_ACKED` 或 `REVIEW_COMPLETED`；ACK/Completed 之后没有新 wake attempt。A 的 RR 与 round 增量各只能是 1，第二 RR 数为 0；B 相对 S0 不得发生 A 引起的业务变化。
8. Human 将 poller 与 webhook consumer 都恢复为步骤 1 的原状态，记录恢复时间。保存只读计数、hash、Audit、启动/ready 证据和 forbidden-path 计数 0。按当前 6.21 治理流程清理演练 Task，保留不可变历史。

## 停止判据

任何时点发现 deadline 到达、RR 非 PENDING、身份/route/冻结字段不匹配、不可恢复 4xx、重复业务 RR/round、B 串写、生产代码版本未证明、或需要人工数据搬运，立即标记 Case G `BLOCKED`。不要复活 RR、重发 dispatcher `SENT` outbox、修改旧报告或通过手动 poller/POST 补齐。由现有 TimeoutService 处理到期 RR，再由正式治理路径处理后续 Task。
