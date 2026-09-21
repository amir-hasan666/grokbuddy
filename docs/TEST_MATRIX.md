# 运行测试矩阵

历史计划表；Phase 1、Phase 2、Phase 3 本地 Webhook/Comment mock，以及 Phase 3.5 HTTP Comment transport 的离线错误分类/重试覆盖已执行，实际结果见对应 PHASE 报告。2026-09-18 又完成了真实 GitHub Delivery、正式 PR binding、synchronize→PENDING 与 Comment create/update；Pull 与 Grok 仍不在本轮范围。

这里只列 Phase 1–6 必须实现的测试；Phase 0 实际检查单独见 [VALIDATION_REPORT](VALIDATION_REPORT.md)。Domain 单测、Repository/worker 集成、接口、幂等、重试、超时、安全/actor/protocol 不能仅靠 schema 示例替代。

| ID | 场景 | 关键断言 | Phase |
|---|---|---|---|
| T01 | create_task/计划提交 | NEW→PLANNING，Artifact、Audit、版本一致 | 1 |
| T02 | PLAN PENDING | 提交后立即返回，Reviewer 不响应也不阻塞；outbox 原子 | 1/2 |
| T03 | PLAN PASS / NEEDS_CHANGES | PLAN_APPROVED / PLAN_CHANGES_REQUIRED，不混 verdict 与 Task | 1 |
| T04 | Plan 二轮 PASS | 第一轮修改、第二轮通过；新请求与旧审计保留 | 1 |
| T05 | FINAL PASS | 自检/快照齐全、无未关闭问题才 DONE | 1 |
| T06 | FINAL HIGH finding | 稳定 ID、NEEDS_CHANGES、原始 review 不变 | 1 |
| T07 | ACCEPT / FIX / VERIFY | 角色守卫、证据、OPEN→ACCEPTED→FIXED→VERIFIED | 1 |
| T08 | REJECTED_WITH_EVIDENCE | 不加 round、不视为 closed；复审可 VERIFIED 或 OPEN | 1 |
| T09 | CRITICAL → BLOCK | 即使 FIXED 也 BLOCK，直到 verified/waived | 1 |
| T10 | Human Waive | 人类限定、理由、原 finding_id、Audit；Reviewer 无此权限 | 1/2.5 |
| T11 | Human Override | 不改旧 verdict、不批准生产动作；PLAN/FINAL 分开 | 1/2.5 |
| T12 | Human Approval | digest/expiry/single-use、参数变更、拒绝/过期、独立身份 | 1/2.5 |
| T13 | 非法状态跳转 | 全未列边默认拒绝，终态不可复活，Task/Audit 原子 | 1 |
| T14 | 重复 Webhook | 相同 delivery / 改 header 重放均无重复 Review/Finding | 3 |
| T15 | 重复 Poll + 跨模式 | 同资源 webhook/pull/重复分页只应用一次 | 3 |
| T16 | 错误/缺签名 | 拒绝、safe Audit、Task 不变，原始 bytes 验签 | 3 |
| T17 | 未知/缺协议版本 | 有协议 marker 但无 version 拒绝；无 marker ignore | 1/3 |
| T18 | 无效 Review JSON/未知字段/错误类型 | quarantine/Audit，Task/RR 不变 | 1/3 |
| T19 | Artifact missing/hash mismatch | 发起前拒绝或结果隔离，无 SSRF/path escape | 1/3 |
| T20 | GitHub API timeout/5xx/429/401/403 | 本地 transport 契约已覆盖分类、限次重试与安全 metadata；真实 API 仍待 Gate；Hub 已提交状态不回滚 | 3/3.5 |
| T21 | Reviewer timeout | RR TIMED_OUT，Task ESCALATED，无自动再调 | 1 |
| T22 | max rounds | Plan 2/Final 3 的最后一轮可通过，否则升级；transport retry 不加轮 | 1 |
| T23 | max_task_duration | 包含人工等待；重启后期限不延长；停止自动调度 | 1 |
| T24 | 同 Actor Builder/Reviewer | 生产拒绝；不同 token 同 provider ID 也拒绝 | 3/6 |
| T25 | Finding 数量保护 | per-review cap；total_findings_created 只统计，不按总数量停机 | 1 |
| T26 | worker 崩溃/lease/outbox | commit 前后故障、delivery unknown 不盲目重新唤醒 | 1/3 |
| T27 | timeout/completed 并发、迟到、乱序 | 单一结果；过期不复活；先完成后 Started 忽略审计 | 1/3 |
| T28 | 冻结 revision/Profile | 旧 package/hash/profile 结果不能批准新内容 | 1 |
| T29 | supersedes/split/regression | 原 ID 历史保留，跨 task/环拒绝，关系不自动关闭旧项 | 1 |
| T30 | Windows artifact IO/backup restore | 中文/空格、junction/UNC、partial write、恢复 hash 正确 | 1 |
| T31 | MCP/HTTP/CLI parity | 三入口同用例权限/幂等；stdio stdout 干净；客户端断连不重复命令 | 2 |
| T32 | Grok trigger / fallback / result | 当前 UI event 确认、B 身份、准确一次意图、结构化返回、证据可取 | 4/6 |
| T33 | Secret/Prompt injection/RBAC | payload 不能授予权限或改 Profile；日志脱敏；下载范围绑定 | 1/3/6 |

## 八个 Demo 的退出证据

| Demo | 路线与验收 | 证据最少包含 |
|---|---|---|
| 1 Plan Review | NEEDS_CHANGES→第二轮 PASS→PLAN_APPROVED | 两个 RR、轮次、事件和 Audit |
| 2 Final Review | HIGH→accept/fix→下一轮 verify→PASS→DONE | 同 finding_id、两次 review artifact、测试与验证证据 |
| 3 Deduplication | 同 GitHub Event 发两次 | 一条业务效果，多次 ingress/duplicate Audit |
| 4 Webhook Security | 错误签名 | 拒绝响应、Audit、状态未变 |
| 5 Loop Protection | 最后一轮仍需改进 | Task ESCALATED，后续 dispatch 数为零 |
| 6 Async + Timeout | PENDING 即返回，Reviewer 沉默 | 请求耗时证据、超时 RR、升级 Task、无自动再调 |
| 7 GitHub Disconnect | 禁用 GitHub，完整 Mock 闭环 | Task/Plan/Final/Finding/Audit 持久化与重启恢复 |
| 8 Artifact Pointer | 大 diff/log/html 经 store | bytes/hash/ACL；Comment 仅指针、metadata/短摘要 |

Demo 1/2/5/6/7 的本地版本已在 Phase 1 覆盖；Phase 3 新增 T14 delivery/semantic dedup、T16 签名四态及本地 Comment marker/upsert。Phase 3.5 增加 T20 的离线 HTTP transport 覆盖，并已完成真实 Delivery/PR/Comment 的窄范围外部 Gate；这不等于 Phase 5 的完整八 Demo，也不包含真实 Grok。真实 Grok 版本仍属于 Phase 6。
