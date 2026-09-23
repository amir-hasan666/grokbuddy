# Verdict Aggregation v1

本文件是旧 Task 的聚合规则。带 `grokbuddy-v1-dual-round` 冻结策略的新 Task 还须遵守 [V1 双轮决策合同](contracts/V1_REVIEW_DECISION_POLICY.md)：R2 仅 PASS/BLOCK；LOW 问题只有经 Reviewer 明确转 ADVISORY 并留痕后才不阻断 PASS；R2 语义不自洽的 PASS 拒绝 APPLY，不降为 NEEDS_CHANGES。

输入是任务截至本次有效 FINAL 结果的**全部** Finding 当前状态（本轮 new findings + 本轮有效 verification + 既有历史未关闭项），不能只统计本次 JSON 的 findings 数组。

`closed = status in {VERIFIED, WAIVED_BY_HUMAN}`。按以下顺序聚合：

1. 有任意 CRITICAL 且未 closed → BLOCK。
2. 其他任意未 closed 的 HIGH/MEDIUM/LOW → NEEDS_CHANGES（包括 blocking=true）。
3. 所有 Finding closed 或从未存在 Finding → PASS。

blocking=true AND OPEN 明确禁止 PASS；blocking 本身不把 LOW 升成 CRITICAL。未关闭的 ACCEPTED/FIXED/REJECTED_WITH_EVIDENCE 仍阻止 PASS。

需求中“没有 OPEN 或全部 VERIFIED/WAIVED”存在文字歧义：若按字面可让全部 FIXED 无验证直接通过，与前文“未关闭 → NEEDS_CHANGES”冲突。这里采用保守且与完整生命周期一致的解释：**没有任何未关闭问题**才允许自动 PASS；该解释列为人工审阅决策 D1。

`reported_verdict` 保存 Reviewer 原文枚举；`effective_verdict` 是 Hub 规则裁决。Hub 不自动把 Reviewer 的 BLOCK/NEEDS_CHANGES 降到 PASS：取 Reviewer 与聚合结果的较严格值（BLOCK > NEEDS_CHANGES > PASS），并保存 VERDICT_MISMATCH。结构/身份校验失败不能进行聚合；合法但漏报问题的 PASS 可被 Hub 降级。EVIDENCE_INSUFFICIENT 是 finding.category 或 plan risk code，不是第四个 verdict；Reviewer 应给 NEEDS_CHANGES/BLOCK 及证据缺口。

| 条件 | 聚合 | 备注 |
|---|---|---|
| 空问题集，Reviewer PASS | PASS | 仍要 package/self-test/revision 守卫 |
| CRITICAL FIXED | BLOCK | 修复未验证 |
| LOW ACCEPTED | NEEDS_CHANGES | 没有 OPEN 也不能通过 |
| HIGH REJECTED_WITH_EVIDENCE | NEEDS_CHANGES | 等待 Reviewer 判断 |
| LOW blocking=true OPEN | NEEDS_CHANGES | 禁止 PASS |
| 全 VERIFIED/WAIVED，Reviewer PASS | PASS | 包括人工 waiver |
| 全关闭，Reviewer BLOCK | BLOCK | 不替 Reviewer 降级 |

PLAN Review 使用轻量 `comments[]/risks[]/suggestions[]` 与总 verdict，不强制 Finding 生命周期；但语义不自洽的 PASS + blocking risk 拒绝。PLAN PASS → PLAN_APPROVED，并不直接 DONE。

HUMAN_OVERRIDE 是独立人工决策类型，不加进 verdict enum，不改旧 Review。Human 指定 PLAN/FINAL、输入 hash、范围、未关闭问题、理由、expiry，经审计后才影响 Task。Override 不是 waiver，也不是生产动作批准；它不会把 unresolved findings 伪写为 VERIFIED。
