# AI-COLLAB v1 / AI-REVIEW v1

本项目自有协议设计；不是 Grok 或 WorkBuddy 已存在的 API。参考实现尚未编写。正式机器字段契约在 [contracts](contracts/review-request.schema.json)，仅描述审核封包。

## Control Plane

第一行必须精确 marker。后续为 UTF-8 `key=value`，每个 key 只允许一次，不允许多行 value；值包含换行拒绝。空白行可忽略。长度上限 4096 bytes、summary ≤500 字符。字段不转义执行、不当 shell/SQL，不解析任意 Markdown 中隐藏命令。

| 字段 | AI-COLLAB | AI-REVIEW |
|---|---|---|
| protocol_version | 必填 v1，与 marker 一致 | 同左 |
| type | PLAN_REVIEW / FINAL_REVIEW | REVIEW_COMPLETED |
| task_id / review_request_id / review_id | 必填 Hub ID（review_id 预分配） | 回显必须相符 |
| round | 正整数，对应数据平面 review_round | 同左 |
| artifact_id / artifact_sha256 / artifact_pointer | 待审 input artifact | REVIEW_RESULT artifact |
| verdict | 不允许 | 必填 PASS/NEEDS_CHANGES/BLOCK，必须与 JSON 一致 |
| summary | 可选短摘要 | 可选短摘要 |
| commit_sha / path / url | 可选、经 Hub 注册的 locator metadata | 可选，不替代 hash/鉴权 |

没有任何协议 Marker 的普通评论 ignore（不推进状态）；出现 `[AI-COLLAB]`、`[AI-REVIEW]` 但缺版本 reject；未知版本 reject；重复 key、非法 key、缺 required、版本不一致均 VALIDATION_FAILURE + Audit。不能从自然语言 PASS 一词推断 verdict。

## Data Plane 必填字段

请求：protocol_version、task_id、review_request_id、review_id、review_type、review_round、content_revision、review_profile、review_profile_version、profile_sha256、profile_artifact_id、input_artifact_id、input_sha256、expected_reviewer_actor_id、deadline_at。严格对象无额外字段，schema 使用 JSON Schema Draft 2020-12。

结果公共字段：protocol_version、task_id、review_request_id、review_id、review_type、review_round、content_revision、review_profile、review_profile_version、profile_sha256、input_sha256、verdict、summary、reviewer{type,id}、timestamp。reviewer.type 是 mock/grok_bot/未来 adapter 名，id 为 Hub 注册 principal；不从 type 自动授予身份。

PLAN 结果额外必填 comments[]、risks[]（code/description/blocking）、suggestions[]。FINAL 结果额外必填 findings[]、verifications[]；schema 的 oneOf 禁止混搭。

新 Finding：external_finding_key、severity(CRITICAL/HIGH/MEDIUM/LOW)、blocking、category、title、finding、evidence{artifact_id,locator,description}、impact、recommendation；可选 supersedes、parent_finding_id 引用原 Hub ID。**不允许 Reviewer 给新 Finding 自定主键或写 status**。

Verification：finding_id、outcome(VERIFIED/REOPENED)、evidence、reason；仅用于既有 FIXED/REJECTED_WITH_EVIDENCE，REOPENED 映射状态 OPEN，不加入 Finding enum。Hub 校验该 ID 属于当前 task，追加对应 finding_event。

## 结构之后的语义检查

1. 认证来源/Reviewer actor 独立性、仓库与资源映射。
2. RR 存在、未终结、未超时，review_id/type/round/revision/Profile/hash 与冻结快照相同。
3. Artifact 可读、hash/长度正确、输入/证据 task scope 合法；指针仅从注册表解析。
4. per-review Finding 上限、external key 不重复、verification ID 不重复，无同 ID 相反操作；supersedes/parent 同 task 且无环。
5. PLAN PASS 不能伴 blocking risk；FINAL 在全部历史问题基础上聚合，不相信漏项 PASS。
6. dedup/唯一约束与状态迁移在同一事务生效，所有 failure 不改变 Task。业务拒绝与 transport 接收 ACK 分开。

现有 JSON Schema 只覆盖形状、enum、ID 格式、required、未知字段；这些跨实体检查安排 Phase 1。`max_findings_per_review` 是 Hub 动态上限，不在 schema 固定死另一个值。

## Event Envelope（内部 Port）

ReviewStarted / ReviewCompleted / ReviewFailed 由 adapter 规范化，包含 event_id、event_type、source、correlation_id、review_request_id、task_id、review_id、actor_id、received_at、deduplication_key、payload_artifact_id/hash。GitHub 附带 repo/resource/revision；Mock 没有 GitHub 字段。ReviewCompleted 解引用的内容须符合 result schema。

完成结果重复且内容一致 → 原收据，不重复 Review/Finding；相同 RR 出现不同结果 hash → CONFLICT，审计与人工处理，不能覆盖首次结果。修改已发评论不能修改评审历史。协议升级必须新版本 schema/fixture 与迁移决策，不静默接受 v2。
