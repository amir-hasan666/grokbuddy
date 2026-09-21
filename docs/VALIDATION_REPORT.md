# Phase 0 验证记录

范围仅为离线文档和设计契约。结果明细由 [phase0-checks.json](phase0-checks.json) 提供。此记录不证明 Hub/Mock/GitHub/Grok/WorkBuddy 运行闭环。

## 实际结果（2026-09-16）

| 检查 | 实际结果 | 证据 |
|---|---|---|
| 离线文档/协议检查 | **171/171 PASS，0 FAIL** | phase0-checks.json |
| 官方 Skill 校验 | **4/4 PASS** | [skill-checks.txt](skill-checks.txt) |
| 验证环境依赖一致性 | `pip check`：No broken requirements found | 本阶段命令输出，版本已锁定 |
| 外部环境 Gate | **BLOCKED** | [能力登记](CAPABILITY_VERIFICATION.md) |
| Phase 1 业务实现/运行 Demo | **NOT RUN / NOT STARTED** | 无 src、无 Hub 服务 |

171 项包括：18 个规定文档、相对链接/无核心源码/空 secret 模板 3 项、4 Skill frontmatter、日期格式 checker 启用 1 项、4 schema 元校验、6 正例、97 个必填字段删除反例、6 个未知字段反例、32 个其他结构反例。自动检查不评价整篇架构论证正确性，设计解释 D1–D5 仍待用户审阅。

首轮实际为 169/170，通过率不足的原因是 jsonschema 缺少可选 RFC3339 校验依赖，非法日期被接受。已补装并锁定 rfc3339-validator/six，并增加日期 checker 必须已启用的检查；复跑 171/171。没有隐藏该初始失败，也没有用跳过日期校验令测试变绿。

## 可复现命令

```powershell
Set-Location D:\Codex\grokbuddy
.\.venv-phase0\Scripts\python.exe scripts\validate_phase0.py
.\.venv-phase0\Scripts\python.exe -m pip check
$env:PYTHONUTF8 = '1'
$skillValidator = 'C:\Users\22241\.codex\skills\.system\skill-creator\scripts\quick_validate.py'
foreach ($skillName in @('architecture-gate','phase-execution','review-protocol-validator','async-workflow-test')) {
    .\.venv-phase0\Scripts\python.exe $skillValidator (Join-Path 'skills' $skillName)
    if ($LASTEXITCODE -ne 0) { throw "Skill validation failed: $skillName" }
}
```

验证环境：Python 3.12.14，隔离 `.venv-phase0`，精确验证依赖在 [requirements-phase0.txt](../requirements-phase0.txt)。官方 quick_validate.py 为已安装的 skill-creator 校验器，本项目没有复制/修改它。

## 验证类型

18 份规定文档非空；相对 Markdown 文件链接可解析；4 Skill frontmatter；无 src 核心实现；.env.example Secret 留空；4 JSON Schema 的元 schema 校验；6 个合成正例；每个必填项删除、未知字段、版本/枚举/类型/ID/hash/日期、PLAN/FINAL 混搭、证据缺失、Reviewer 伪写状态/新主键等反例。

校验器只验证这些明确的静态性质。它不实现 verdict 聚合、状态转换、审批、event handler 或去重，因此不把反例检查称为业务安全测试或异步运行测试。Schema 通过后仍需上下文语义检查，见 [PROTOCOL_V1](PROTOCOL_V1.md)。

## 未运行与未解决

未运行：SQLite/Hub/Application、MockReviewer 事件闭环、11 个 MCP Tool、真实 WorkBuddy handshake、Grok Routine、GitHub API/Pull/Webhook、独立 actor 实测、生产权限验证和 8 个业务 Demo。对应测试已设计在 [TEST_MATRIX](TEST_MATRIX.md)。

外部能力基于官方资料、有限本机观察和用户自述分别登记；用户自述已登录/已连接不替代 trigger/scopes/返回路线实测。外部环境 Gate 保持 BLOCKED。停止边界来自用户当前明确要求，不来自新增审批生命周期。
