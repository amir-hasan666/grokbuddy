# Phase 4 Grok Protocol 证据报告

日期：2026-09-18（Asia/Shanghai）。授权范围只包括 Grok 协议/配置文档、当前账号只读核对和本地回归；禁止进入 Phase 5/6，禁止持续真实审核。

## 开始前核对

| 项目 | 核对结果 |
|---|---|
| Phase 3.5 | `PHASE3.5-REAL-GITHUB-EXIT: PASSED`；证据见 `docs/PHASE35_REPORT.md` |
| Phase 4 / Phase 6 边界 | Phase 4 只交付 Skill/配置手册与小范围账号核对；Phase 6 才是经人工批准的真实 Grok 灰度 |
| primary | PR 事件映射候选；`pr-comment / review-*` 仅是设计标签，不是官方事件枚举；disabled |
| fallback | 定时检查候选；disabled |
| 既有 schema | `docs/contracts/review-request.schema.json`、`review-result.schema.json`，AI-COLLAB/AI-REVIEW v1 |
| Profile 契约 | Hub `review_profiles` 是运行时权威；RR 固定 `review_profile/version/profile_sha256/profile_artifact_id`；Skill 不复制规则 |
| Phase 4 交付文件（核对时） | `grok_bot/reviewer_skill.md`、`grok_bot/routine_setup.md`、`MANUAL_GROK_SETUP.md` 和本报告此前均不存在 |
| 冲突 | 未发现要求修改 Hub/状态机/幂等/backup/provider_id/SoT/MCP/HTTP/CLI/Webhook/Secret 的冲突 |

本阶段文件：

- `grok_bot/reviewer_skill.md`
- `grok_bot/routine_setup.md`
- `MANUAL_GROK_SETUP.md`
- `docs/PHASE4_REPORT.md`

## 账号只读核对

Human 已明确撤销此前网页端自动化观察；该结果作废，不作为当前账号证据。账号核对唯一允许的路径是：已登录 Grok Bot 桌面客户端 → 点击“workbuddy审核员”聊天标题 → 信息页 → `Routines`。

本轮尝试获取桌面应用清单时，当前电脑控制面未提供原生应用接口，无法进入 Grok Bot 桌面客户端；没有改用网页端，也没有进入“市场”补推结论。“市场”中 GitHub 已连接即使可见，也只说明插件存在，不算 Routine trigger，不证明独立 Reviewer。

因此没有看到任何获准证据面中的 trigger 名称或过滤项；没有创建/编辑/启用 Routine，没有点击 Test run，没有模型调用。下列账号能力继续为 `UNVERIFIED`：

| 能力 | 状态 | 缺失证据 |
|---|---|---|
| 实际 PR trigger 名称 | UNVERIFIED | “workbuddy审核员”信息页 `Routines` 中的实际 trigger 文字未能读取 |
| 实际过滤字段 | UNVERIFIED | `Routines` 中 repository/PR/event/action/actor/branch 等实际字段未能读取 |
| GitHub integration 连接主体/scopes | UNVERIFIED | 当前账号的不可变 provider identity 与权限 |
| B 独立身份 | UNVERIFIED | B provider ID != Builder A provider ID |
| 严格 repo/PR 过滤 | UNVERIFIED | 能固定 repository id `1372874264` 且排除 PR #2 的 UI/run 证据 |
| 结果返回路径 | UNVERIFIED | REVIEW_RESULT Artifact 写入和短 carrier 的实际可用路径 |
| 云端 Artifact 读取 | UNVERIFIED | 受认证下载或不可变 Git locator 的 hash E2E |
| H8 | NOT PASSED | 当前账号通道没有完成受控验证 |

公开官方文档核对：

- [Skills and routines](https://docs.x.ai/grok-bot/skills-routines-and-automations) 确认 schedule Routine 和“在支持时由 GitHub notification 等 event 启动”的类别，并说明 event integration 与普通 plugin 分开；未提供本项目可直接采用的 PR event 枚举。
- [Grok Bot overview](https://docs.x.ai/grok-bot/overview) 和 [Get started](https://docs.x.ai/grok-bot/get-started) 将 Bot/Routine 管理定位在桌面/移动客户端；网页 Grok 自动化不能替代该账号核对。

因此公开类别为 `DOC_CONFIRMED`，当前账号具体 trigger/config、过滤、身份和回传仍是 `ACCOUNT_UNVERIFIED`。

## 协议与 SoT 一致性

| Gate | 证据 | 结果 |
|---|---|---|
| Hub SoT | Skill 明确 GitHub/Routine/Comment 只作输入或投影；Hub 验证后提交才成立 | PASS（文档） |
| 异步边界 | request -> PENDING -> event -> terminal；Routine 不同步返回 verdict、不创建轮次 | PASS（文档） |
| Request schema | Skill 列出并冻结现有 15 个 request 字段，不增加 Bot 私有字段 | PASS（文档） |
| Result schema | PLAN/FINAL 分支与 `review-result.schema.json` 一致，禁止额外字段 | PASS（文档） |
| Profile 快照 | 只读 `profile_artifact_id` 并校验 `profile_sha256`；不复制 Oracle/其他规则 | PASS（文档） |
| Identity | 结果声明 `reviewer.type=grok_bot` 和冻结 actor；Hub 仍验 A != B/provider identity | PASS（设计）；账号证据缺失 |
| Artifact | 本地路径不可假定云端可读；结果 JSON 不放 Comment | PASS（文档）；传输 E2E 缺失 |
| 失败停止 | trigger/filter/identity/artifact/carrier 不确定时停止，无 PASS、无盲重试、无新轮次 | PASS（文档） |

Schema 形状通过不等于语义或真实集成通过。认证 actor、冻结 RR、Artifact scope/hash、Finding 生命周期、deadline、dedup 和状态迁移仍由现有 Hub Application/EventService 校验。

## 冻结项与外部动作

- 未改状态机、命令幂等、backup、provider_id、Source of Truth、MCP/HTTP/CLI、GitHub Webhook、Secret 或 `GITHUB_COMMENT_TOKEN`。
- 未 merge、approve、push、修改 `main`、删除 `phase35-probe` 或改仓库设置。
- 未向真实 Grok 发送 PR #2、`phase35-probe` 或 `TASK-7db0acee-8d15-425c-91b6-86177a86e70e`。
- 未使用 xAI 模型 API，未触发 ACP/WorkBuddy，未进入 Phase 5/6。
- 当前工作目录未暴露 `.git` 元数据，`git status` 返回“不是 Git 仓库”；因此本报告只能列文件和测试，不能提供本轮 Git diff/status 证据，也未尝试重建 `.git`。

## 验证命令与结果

本轮执行：

```powershell
.\.venv-phase0\Scripts\python.exe -m pytest tests\test_phase3_github.py -q --tb=short
.\.venv-phase0\Scripts\python.exe -m pytest -q --tb=short
.\.venv-phase0\Scripts\python.exe scripts\validate_phase0.py --allow-core
.\.venv-phase0\Scripts\python.exe -m pip check
```

- Phase 3 GitHub tests：`25 passed in 17.75s`。
- 全量 pytest：`473 passed in 103.60s`，0 failed。
- contract validator：`171/171 passed; 0 failed`；工具仍正确报告 `External environment gate: BLOCKED (no live integrations executed)`，与本轮未做 Grok test run 一致。
- pip check：`No broken requirements found.`

未运行：Grok Routine Test run、真实模型、真实 PR 唤醒、B 写回、Artifact 云端读写、Phase 5 Demo、Phase 6 灰度。

## Gate

文档交付与本地回归完成后，仍缺当前 Grok Bot 桌面账号的实际 trigger/filter、B 独立身份、严格 repo/PR 过滤和结果回传路径；受控 test run 需要下一次明确授权。

`PHASE4-GROK-PROTOCOL-EXIT: BLOCKED`
