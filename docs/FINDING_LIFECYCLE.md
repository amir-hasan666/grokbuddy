# Finding 稳定身份与复审

Hub 在首次有效 FINAL ReviewCompleted 事务内生成 `FND-<UUIDv4>`。Reviewer 新问题传 `external_finding_key`，以 `(review_id, external_finding_key)` 唯一映射；不能由 R001 直接充当主键。后续请求明确附已有 `finding_id` 及其证据快照。

| From | 操作 / Actor | To / 条件 |
|---|---|---|
| OPEN | accept / Builder | ACCEPTED |
| OPEN / ACCEPTED | reject with evidence / Builder | REJECTED_WITH_EVIDENCE；必须 evidence artifact |
| ACCEPTED | fix / Builder | FIXED；必须新内容 hash、修复证据、自检 |
| REJECTED_WITH_EVIDENCE | retract rejection / Builder | ACCEPTED；保留原拒绝记录 |
| FIXED / REJECTED_WITH_EVIDENCE | verify / Reviewer 在新的 evaluation 中 | VERIFIED；给出验证证据与理由 |
| FIXED / REJECTED_WITH_EVIDENCE | reject verification / Reviewer | OPEN；附反证 |
| OPEN / ACCEPTED / FIXED / REJECTED_WITH_EVIDENCE | waive / Human | WAIVED_BY_HUMAN；独立授权、原因、风险范围 |

旧 Task 仅 VERIFIED、WAIVED_BY_HUMAN 是关闭态。Builder 不可自行 VERIFIED，Reviewer 不可 waive。关闭后若在新版本发现回归，创建新 finding_id 并以 parent_finding_id 关联原问题，保留原验证历史。

V1 双轮策略增加 `advisory=true`、`actionable=false` 当前标记：仅第二轮 Reviewer 可把已有 LOW Finding 凭证据、理由和保留建议转为非阻断建议；原 status 不改为 VERIFIED 或 WAIVED。原 Finding 与追加事件保留，并在 V1 verdict 聚合与可执行 Finding 查询中排除。旧 Task 不能产生这个标记。见 [V1 双轮决策合同](contracts/V1_REVIEW_DECISION_POLICY.md)。

重复出现同一问题：Reviewer 引用原 finding_id，更新通过 finding_events 记录观察，不另建重复主键。新问题用新 external key，Hub 分配新 ID。`supersedes=old_finding_id` 表示取代关系；`parent_finding_id` 表示拆分/衍生关系；两者须同任务、无自引用/环。**建立关系不自动关闭旧 Finding**，旧问题仍需 Reviewer VERIFIED 或 Human WAIVED。

`review_findings` 当前 status/version 可以更新，但最初发现内容和每次 review artifact、finding_events 保持不可变。新的 evidence、comment、状态理由追加事件，不能用后一轮覆盖前一轮判断。展示层 R001/R002 可按页面重新编号，所有回应必须解析并确认稳定 ID。

整改回应、accept/reject/fix 不增加 round；真正复审才新建 RR。已有 OPEN/ACCEPTED/FIXED/REJECTED_WITH_EVIDENCE 全部进入下一轮核查清单，空 findings 的 PASS 无法把它们抹掉。

Phase 1 待测：重复结果不重复建 ID；第二轮 verification 引用第一轮 ID；新问题另建；split/supersedes 不自动关闭；错 task ID 拒绝；Builder verify 拒绝；原 Review/Audit 不变。
