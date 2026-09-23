PHASE6-CONTROL-PLANE-DETEMPORALIZE: LOCAL PASS / DOCS ONLY

# Phase 6 Control Plane Detemporalize Report

日期：2026-09-22（Asia/Shanghai）
范围：仅去时态化根 `AGENTS.md` / `README.md`，并新增可变生产基线指针；不改 Runtime、Hub/MCP/DB/Credential、状态机或业务代码。

## 1. 结论与证据边界

根控制面现分为两层：

- `AGENTS.md` 与 `README.md` 只保留跨阶段长期规则、架构边界、安全纪律和导航。
- `docs/CURRENT_PRODUCTION_BASELINE.md` 单独维护可变的 Phase/Gate 指针、正式部署事实、当前具体生产入口拓扑与最新阻塞报告引用。

本步只做仓内文档编辑和静态自检，没有重启 Hub/WorkBuddy，没有调用真实 MCP、Grok、GitHub 或生产数据库，没有运行 Runtime/E2E，也没有产生新的 6.20 证据。结论仅为 **LOCAL PASS / DOCS ONLY**，不等于 Phase 6.20 PASS。

## 2. 删除或迁移的阶段性语义

从根 `AGENTS.md` 删除了 Phase 3.5/4 进度叙事、旧 PR/Mock RR/Secret 现场、“禁止 Phase 5/6”、旧试跑停止点以及会过期的具体状态迁移枚举。阶段与 Gate 状态现在只由 `CURRENT_PRODUCTION_BASELINE.md` 指向既有报告。

从根 `README.md` 删除了以下被当作“当前”的旧内容：

- Phase 3.5/4 当前状态和“Phase 5/6 尚未开始”的 Roadmap；
- MockReviewer 作为当前拓扑分支；
- `worker-once`、`project-once`、`project-github-once` 等一次性调试流程；
- Quick Tunnel、旧 `8787` 服务示例、`var/client` / `var/github` 等旧 runtime 指引；
- 旧 Grok wake-up、Secret 缺口和 Functional Exit 叙事。

历史内容未删除，也未改写任何带日期 Phase 报告。需要追溯时仍从 `docs/PHASE*.md` 读取当时事实，但不得把它们当作当前运维配置。

## 3. 长期控制面与拓扑边界

`AGENTS.md` 现在明确：

- Hub 持久化业务状态为运行中的唯一业务 SoT，外部系统是输入/通信/投影；
- 正式 production-path evidence 必须经过 `CURRENT_PRODUCTION_BASELINE.md` 指定的生产入口与 adapter；
- Manual Glue = 0，direct Gateway、`LocalRuntime`、mock、临时 driver、`run_until_idle`、`*_once` 和人工改库不能替代正式证据；
- Secret、身份、高风险 Human approval、Reviewer 只读审核权限、禁止伪结果以及未经授权不得 merge/push/force-push/改默认分支/直接 DB DML 等边界继续长期生效；
- 状态机细节只指向 `STATE_MACHINE.md`、production contract、`docs/contracts/` 与符合它们的实现，不再复制易过期枚举；
- Phase/Gate/部署拓扑不在根规则中维护。

`AGENTS.md` 没有写死三个当前 MCP server 的名称或职责；`README.md` 也只导航到基线、runbook 与集成文档。当前具体拓扑只写入可整体替换的 `CURRENT_PRODUCTION_BASELINE.md`。

## 4. 优先级与 drift 处理

新基线按要求固定以下优先级：

1. 已冻结的现行 production contract + `docs/contracts/`；
2. 正式 runtime config；
3. `CURRENT_PRODUCTION_BASELINE.md`；
4. 必须符合前三项的现行实现代码；
5. 带日期的历史 Phase 报告；
6. 根 `AGENTS.md` / `README.md`；
7. legacy / 更旧阶段材料。

因此代码没有被置于 contract 之上。代码与现行合同冲突时必须报告 **implementation/contract drift**，不得修改合同迁就错误实现。该规则直接避免把实现缺口或绿测误当作合同已经改变。

## 5. 当前基线引用边界

`CURRENT_PRODUCTION_BASELINE.md`：

- 只把 6.17 与 6.19 列为已关闭门禁，并逐项链接既有 PASS 报告；
- 以当前工作树中的 `config/grokbuddy.service.json` 记录 runtimeDir、contractsDir、host/port、PublicBase、Reviewer actor、Supervisor 与 Comment token env 名称；
- 把具体正式生产入口拓扑集中在该文件；
- 原样标注最新报告的 `LOCAL PASS / WAITING HUMAN RESTART+CONTINUE` 为“报告状态”，没有把本审计写成 restart/Continue 证据；
- 仅复述 Reviewer Delivery 报告已成立的 `PLAN_HUMAN_REVIEW`、`REVIEW_TIMEOUT`、旧 RR `TIMED_OUT`、旧 outbox `CANCELLED`/attempts `0` 和 Hub 从未投递；
- 明确 Human restart/Continue、新 RR、自动 Reviewer intake、真实 APPLY/E2E 均未由本步执行，Phase 6.20 仍为 `NOT PASS`。

本步没有“纠正”或覆盖任何历史报告，也没有新造 PASS。

## 6. 文件清单

| 文件 | 变更 |
| --- | --- |
| `AGENTS.md` | 重写为 timeless 长期控制面；移除阶段进度与具体 MCP 拓扑。 |
| `README.md` | 重写为 timeless 项目入口、架构边界、导航与本地开发说明。 |
| `docs/CURRENT_PRODUCTION_BASELINE.md` | 新增可变当前基线指针。 |
| `docs/PHASE6_CONTROL_PLANE_DETEMPORALIZE_REPORT.md` | 新增本次 DOCS ONLY 变更报告。 |

未修改生产代码、配置、`var/**`、数据库、Credential、`mcp.json`、默认 Reviewer、ingress allowlist、`owner_id`、状态机或既有 Phase 报告。

## 7. 验证与停止点

| 检查 | 结果 |
| --- | --- |
| `rg` 检查根 AGENTS/README 的旧阶段句、once/Quick Tunnel/8787/`var/client` 与三个当前 MCP server 名称 | PASS；无匹配 |
| `Get-Content -TotalCount 1` 对照 6.17、6.19、MCP scope、Supervisor、Reviewer Delivery 报告首行 | PASS；BASELINE 引文逐字一致 |
| `ConvertFrom-Json config/grokbuddy.service.json` 后逐项比对 BASELINE 的 9 个配置字段 | PASS |
| 扫描 `skills/` 中过期阶段禁令或 mock 生产默认 | PASS；无匹配，技能无需修改 |
| 4 个交付文件的相对链接、严格 UTF-8/no BOM、尾随空白 | PASS |
| `git diff --check -- AGENTS.md README.md docs/CURRENT_PRODUCTION_BASELINE.md docs/PHASE6_CONTROL_PLANE_DETEMPORALIZE_REPORT.md` | PASS；仅 Git 提示工作区未来可能 LF→CRLF，无 whitespace error |

未运行 pytest、Runtime、Restart 或 E2E；这些不属于 DOCS ONLY Gate。

到此停止。未 Restart Hub，未 Continue Task，未操作 WorkBuddy，未 push。
