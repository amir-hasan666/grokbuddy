# Review handoff 正式发布记录（2026-10-03）

状态：**正式 Hub 已加载统一版本；本机只读 HTTP 验收通过。真实业务整改和审核端到端验收未执行。**

## 授权与目标

Human 在本 Codex 会话先授权提交当前工作区全部未提交代码，随后明确回复“授权执行”，授权以统一提交受控发布并重启正式 Hub，之后只读验收。目标为 `904e51b06b243d7aa9aaa3846bbda8b7464e3d0c`，包含两个对话的 70 个维护文件，见 [统一提交记录](UNIFIED_MAINTENANCE_COMMIT_20261003.md)。没有执行 GitHub push。

正式启动入口仍是 Windows Scheduled Task `GrokBuddy Hub` → `scripts/windows/Start-GrokBuddyHub.ps1` → `scripts/grokbuddy_composite.py`。配置、凭证、身份和正式运行目录均保持原样：`var/github-manual`、Reviewer `grok-reviewer-b`、127.0.0.1:8788，Supervisor 与 Control Center 已配置启用。

## 重启前检查与回滚

- 工作区干净且 HEAD 等于批准版本；service config SHA256 为 `f74926f311f56f925b368ecb4835502d9ca88da7d5d06f8fd977f4400666291e`。
- 无活动 RR、待处理 inbox/outbox 或未完成 Worker assignment；8 项现有 Credential Manager 目标均可读取，仅报告 PRESENT。
- 统一版本已有全量 922 项测试、272 项合同/文档检查、两份技能检查通过。另在正式 launcher 选择的 `.venv-phase0` 环境运行相关测试，47 passed in 43.01s。
- 代码回滚目录：`var/service/rollback/unified-review-handoff-20261003-103931/`。父提交不足以单独代表旧生产源码；旧生产三份 Reviewer 文件在隔离目录重建，并逐份匹配 2026-09-30 部署 manifest 的 deployed SHA。另三份配置/运行时文件匹配同一部署记录的既有 SHA，共 6 份核对通过。回滚副本不含业务数据库或凭证。
- 保存了 24 张表的记录数、规范化记录哈希和 schema 版本，只读连接采用 `mode=ro`、`query_only=ON`，没有直接 Hub 调用或 SQL DML。

2026-10-03 10:48:46 上海，由正式 `Restart-GrokBuddyHubTask.ps1 -ReadyTimeoutSeconds 60` 重启原计划任务。旧 PID 34064 被停止，新 PID 12180 于 10:48:51 启动；仓库、runtime 与 contracts 路径均匹配。重启脚本返回 Ready=True、Supervisor=ok。新日志含一次 Supervisor started 标记，未见 Supervisor worker error/failed 标记。

## 重启后只读验收

2026-10-03 10:49–10:50 上海，使用既有 Reviewer 认证 GET **本机正式 HTTP**。凭证没有发送到公网，响应只保存状态码、匹配布尔值、材料检查数量和既有状态摘要。

| 项目 | 重启前 | 重启后 |
| --- | --- | --- |
| `GET /reviewer/contracts` | 404 | 200；4 份 schema 内容与仓内合同一致 |
| `GET /reviewer/contracts/review-result.schema.json` | 200 | 200 |
| 原 Plan R2 的 `GET /materials/check` | 404 | 200、valid=true，5 项材料均可读且 hash 校验通过 |
| 历史 Final 的 `GET /materials/check` | 404 | 200、valid=true，13 项材料均可读且 hash 校验通过 |
| `GET /validate-result` | 404 | 405；证明 POST 路由已加载。本次没有 POST，未验收结果预检执行 |
| 原拒绝 ingress 的 `GET` | 200，无新增诊断键 | 200；`reason_code`、`rejection_details`、`rejection_details_source` 已出现 |

Plan 请求为 `RR-29621b23-87c6-4590-801d-4fae9fead2a1`，Final 请求为 `RR-50b72684-998b-4c2f-9ca4-386e70c2277d`。读取历史材料没有 ACK、重投或恢复审核。

无凭证运行正式 runtime probe：本机与固定公网入口均为 health=200、ready=200、root=404，ready 含 database=ok、supervisor=ok；cloudflared 为 Running/Automatic，Hub 计划任务为 Running。公网 Reviewer contracts 无认证返回 401，认证闸保留。

重启后 24 张表的全部记录哈希、数量和 `user_version=4` 与重启前一致。原 Task 仍为 `PLAN_HUMAN_REVIEW` v8、automation frozen；原 R2 仍 TIMED_OUT，原 ingress 仍 REJECTED/ILLEGAL_TRANSITION，两条 Finding 仍 OPEN v0。没有 Human Gate 操作，也没有改写历史拒绝详情。

## 验收边界与后续使用

- 旧 ingress 未保存过具体拒绝详情，因此新读取响应的详情仍为 null。新增诊断写入路径有本地回归证据；本次没有制造新的生产拒绝或回填历史记录。
- Finding 的 Plan fix 和准备度入口已随统一源码发布，有本地回归证据；本次没有实际 accept/fix Finding，也没有在正式会话执行整改链。
- 两项额外探针被自动审批拒绝，均未执行：公网认证 GET 加完整响应留存（凭证外发与敏感响应留存范围不足）；在正式库新起 MCP stdio 探针（初始化涉及 `LocalRuntime` 边界与潜在写入）。前者改为本机认证 GET 与脱敏摘要，公网仅无凭证 probe；后者不绕过，实际调用留给 WorkBuddy 既有 MCP 连接验收。
- 不能把本次部署和只读检查写成 V1 6.21/6.22 或外部 GrokBot 真实审核 PASS。新需求可以通过 WorkBuddy 正式入口启动；应刷新技能及工具 schema，按现行合同预检，在首个正常授权 RR 中核对实际结果。
- 原超时 Task 的 Human Gate 独立保留，不得向旧 RR 重投、恢复 R2 或自动创建第三轮。

原始安全证据位于上述回滚目录的 `pre-restart-manifest.json`、`pre-service.json`、`restart-evidence.json`、`before-reviewer-get.json`、`after-reviewer-get.json`、`runtime-probes.json`、`post-service.json` 和 `post-restart-manifest.json`。本文只维护本次发布事实，既有带日期报告的历史结论保持原样。
