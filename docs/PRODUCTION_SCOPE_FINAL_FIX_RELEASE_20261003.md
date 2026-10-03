# Scope 与 Final 整改入口正式发布记录（2026-10-03）

状态：**正式 Hub 已加载发布代码；本机认证 GET 与本机/公网就绪核对通过。WorkBuddy 工具缓存刷新及真实终审整改链尚未验证。**

## 授权与发布范围

Human 明确回复“授权发布”，随后报告误关闭 Hub，并授权必要时再次重启。本次发布包含 [Plan scope 修复](PLAN_SCOPE_HANDOFF_FIX_20261003.md) 与 [Final-fix 客户端修复](FINAL_FIX_MCP_REPAIR_20261003.md)，共 25 个维护文件，固化为本地提交 `b9580f4dcedf7cba12d58011fa6813bf19ae7e3c`。未执行 GitHub push。

启动入口保持 Windows Scheduled Task `GrokBuddy Hub` → `scripts/windows/Start-GrokBuddyHub.ps1` → `scripts/grokbuddy_composite.py`。配置、Credential、Reviewer、contracts 和 runtime 路径未修改：`var/github-manual`、`grok-reviewer-b`、127.0.0.1:8788、Supervisor 每 5 秒、既有 Control Center 配置。

## 发布前证据与回滚

- 维护代码此前完整本地回归 **961 passed**。本次另在正式 launcher 选择的 `.venv-phase0` 环境运行 `tests/test_final_fix_mcp.py tests/test_plan_scope_handoff.py tests/test_v1_dual_round_decisions.py`：**55 passed in 72.83s**。
- 发布候选文件字节与 `code-manifest.json` 一致，发布前工作区干净。8 个既有 Credential Manager 目标仅检查为 PRESENT，没有读取值到输出或更改 Credential。
- 无活动 RR、待处理 inbox/outbox 或未完成 Worker assignment。只读快照使用 SQLite `mode=ro`、`query_only=ON` 和读事务，保存 24 张表的记录数量及规范化哈希、schema 哈希、`user_version=4` 和配置哈希，不保存完整业务行。
- 回滚目录：`var/service/rollback/scope-final-fix-20261003-142106/`。17 个已有文件的旧版本以精确 Git bytes 重建；基线为 `7da4943`，其运行时代码与先前加载的 `904e51b` 一致。8 个新增文件为文档/示例/测试，代码回滚无需删除它们。目录只保留源码、文档、哈希和脱敏证据，不备份数据库或密钥。
- 服务配置 SHA256 保持 `f74926f311f56f925b368ecb4835502d9ca88da7d5d06f8fd977f4400666291e`；Reviewer registry 哈希也保持不变。回滚说明为上述目录的 `RESTORE.md`，回滚不触碰业务数据。

## 两次启动与误关闭恢复

原生产 PID 为 `12180`，于 10:48:51 启动。第一次执行既有 `Restart-GrokBuddyHubTask.ps1 -ReadyTimeoutSeconds 60` 后，Human 报告关闭了 Hub 窗口。随后只读确认：无 8788 监听、`/ready` 不可用，计划任务为 Ready、LastTaskResult=`3221225786`；第一次就绪等待超时，证据另存 `restart-first-attempt.json`。

按新增授权再次启动同一个计划任务。任务于 **14:31:47 上海**启动，新 Hub PID **35428** 于 **14:31:52 上海**启动；脚本返回 Ready=True、Supervisor=ok。实际启动目录、runtime、contracts、Reviewer registry 与配置均匹配。日志摘要为一个 Supervisor started 标记、零 Traceback、零 Supervisor worker error/failed 标记；没有保存或输出日志正文。

## 发布后只读核对

14:32–14:33 上海，认证仅发往 localhost，关闭重定向；响应正文只在内存解析，证据只保留状态码、计数和布尔值。公网核对不带凭证。

| 项目 | 重启前 | 重启后 |
| --- | --- | --- |
| `GET /reviewer/contracts` | 200；内容不匹配新合同，缺 scope snapshot 定义 | 200；四份 schema 与发布合同一致，`common.$defs.plan_scope_snapshot_v1` 存在 |
| 当前 Task 的已完成 Plan R1 `/materials/check` | 200、valid=true，7 项材料 | 200、valid=true，7 项材料；无不可读项 |
| 当前 Task 的已完成 Final R1 `/materials/check` | 200、valid=true，10 项材料 | 200、valid=true，10 项材料；无不可读项 |
| Plan RR 的 `GET /validate-result` | 405 | 405；只确认 POST 路由存在，本次未 POST |
| 本机/公网 `/health`、`/ready` | 重启前本机 ready | 重启后均 200，database=ok、supervisor=ok |
| 公网 Reviewer contracts（无认证） | 本次未重启前核对 | 401，认证闸保留 |

Plan RR 为 `RR-bc4bd19b-1033-4cd1-9cf7-0945107b6682`，Final RR 为 `RR-95a9569b-5623-40d4-80bf-fc0ed7d8d16a`。读取其历史材料没有 ACK、重投或恢复审核。新 scope 冻结字段只作用于后续新创建的 v2 Plan RR，不回填已完成 RR；本次没有创建 RR 来演练该行为。

重启后 **24/24 表全部记录哈希及数量不变**，schema 哈希和 `user_version=4` 不变，service config 和 Reviewer registry 哈希不变。新 Task `TASK-84255b22-cd5c-487f-b2be-c8b9dbbbb7bd` 仍为 `FINAL_CHANGES_REQUIRED v10`、无活动 RR、completion_basis=null；旧 Task `TASK-fc069b71-7dc1-4da1-9558-2ce70da1bebc` 仍为 `CANCELLED v15`。没有 accept/fix Finding、begin_final_fix、Worker claim、终审提交、Human gate、手动 wake 或直接业务 DML。

## WorkBuddy 接入与验收边界

Hub HTTP 与 WorkBuddy stdio MCP 分别加载代码。此次成功重启 HTTP Hub **不能证明 WorkBuddy 已加载新 MCP 工具**；未另起 MCP/LocalRuntime 指向正式库做探针，也未擅自杀掉 WorkBuddy 客户端进程。

WorkBuddy 还需重新连接既有 `grokbuddy-hub`、`grokbuddy-worker`、`grokbuddy-ingress` MCP 服务、刷新工具 schema，并从仓内同步 [方案技能](workbuddy-skills/grokbuddy-plan-remediation/SKILL.md) 与 [终审技能](workbuddy-skills/grokbuddy-final-review-package/SKILL.md)。服务标识以本机既有配置为准，不为刷新而修改连接配置或身份。先确认 `begin_final_fix`、`planned_changed_files` 与材料绑定能力可见；再由 Human 给予 [当前 Task 续办提示词](WORKBUDDY_FINAL_FIX_RESUME_PROMPT.md)，走新的 Worker 整改链及唯一终审 R2。

GrokBot 的 Plan-scope 审核规则仍按 [同步提示词](GROKBOT_REVIEW_HANDOFF_PROMPT.md) 更新；本机不能直接核验其外部常驻规则。Final-fix 工具没有新增 Reviewer 结果协议，FIXED 仍须独立核验。本次没有操作外部规则、运行真实业务整改或验证 Final R2 PASS，不能作为 V1 6.21/6.22 验收通过。Phase 0 的真实引擎/微信/人工门禁仍保留。

## 原始安全证据

上述回滚目录包含 `code-manifest.json`、`candidate-verification.json`、`before-database.json`、`after-database.json`、`before-service.json`、`after-service.json`、`before-reviewer-get.json`、`after-reviewer-get.json`、两次 restart 证据、`runtime-probes.json`、只读验证脚本与恢复说明。此前发布及带日期 Phase 报告保持原结论。

发布后只补充本记录、当前生产基线和两份本地修复记录的发布链接，没有更改运行时代码。文档检查 25/25 与 `git diff --check` 通过；这类记录更新无需再次重启或重复全部代码测试。
