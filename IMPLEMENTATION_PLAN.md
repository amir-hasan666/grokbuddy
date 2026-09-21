# 实施计划与 Gate

2026-09-17 用户确认 Phase 0–3 本地退出已关闭，并明确授权 Phase 3.5 的真实 GitHub 联调范围。Phase 3.5 仅放行签名 Webhook 公网投递验证、正式 PR binding、`pull_request:synchronize` 到既有 Final Review `PENDING`，以及普通 PR/Issue Comment read/create/update；不放行 Grok、ACP、WorkBuddy wake-up、merge/approve 或 Phase 4。2026-09-18 的续跑仅额外授权从 `main` 创建 `phase35-probe`、两个无功能 probe commit 与一个保持打开的 PR；禁止 force-push、修改 `main`、merge、approve、删除分支或改仓库设置。

本轮 Phase 3 采用更窄的授权边界：只实现本地签名 Webhook、Adapter delivery 去重、`pull_request:synchronize` 到既有 Final Review request 的 `PENDING` 终点，以及完成结果到本地 Comment mock 的 marker/upsert 投影。原 Phase 3 路线中的 Pull 与测试仓库真实 API 调用未获本轮授权，不实施、不以 mock 冒充。

## 当前架构审阅决策

| ID | 本阶段采用的设计解释 | 原因 |
|---|---|---|
| D1 | 自动 PASS 要求所有 Finding VERIFIED/WAIVED，不能只是没有 OPEN | 避免 FIXED/ACCEPTED 跳过验证 |
| D2 | RR 保留 TIMED_OUT，Task ESCALATED | 保留超时原因，不让两个状态枚举混淆 |
| D3 | 创建 evaluation 预留并占用 round，重投递不加轮；最后允许轮仍可 PASS | 防止失败循环绕过预算；不用额外 phantom RR |
| D4 | Hub 生成 finding_id，预分配 review_id；跨轮 verification 引用旧 finding_id | 幂等与稳定历史 |
| D5 | 按用户补充，以 PR 事件 pr-comment/review-* 为 primary 候选，定时检查为 fallback；均 disabled，外部 Gate BLOCKED | 用户指定设计方向不等于当前产品已支持；Issue Comment 唤醒 UNVERIFIED |

## 当前 Gate（用户 2026-09-17 决定）

| Gate | 要求 | 当前 |
|---|---|---|
| G0-SCOPE | 规定 18 文档、4 Skill、无核心实现；本地检查通过 | 见验证报告 |
| G0-DESIGN | 用户审核 Phase 0 文档与离线契约 | PASSED，用户明确确认 |
| LOCAL-CORE-ENTRY | 允许完全离线实现 Phase 1 | PASSED，用户明确授权 |
| EXTERNAL-WORKBUDDY | WorkBuddy MCP 当前兼容性 | LOCAL_SERVER_READY：5.5.6 stdio/配置字段已确认，本地 legacy handshake 与 11 tools 通过；用户级注册和真实 WorkBuddy call 仍 BLOCKED |
| EXTERNAL-ACTOR | GitHub Builder / Reviewer 独立身份与权限 | BLOCKED；对应正式集成前必须 VERIFIED |
| EXTERNAL-GROK | Grok Trigger、评论与 Artifact 回写 | BLOCKED；对应正式集成前必须 VERIFIED |
| PHASE2-AUTHORIZATION | 允许进入客户端接口阶段 | PASSED，用户 2026-09-17 明确授权 |
| PHASE3-AUTHORIZATION | 允许进入 GitHub Adapter | PASSED；仅限本地 Webhook + Comment mock 投影 |
| PHASE3-LOCAL-EXIT | 签名、delivery 幂等、PR synchronize→PENDING、result→Comment、全回归 | PASSED；见 [Phase 3 报告](docs/PHASE3_REPORT.md)，等待 Human Gate |
| PHASE3.5-AUTHORIZATION | 允许真实 GitHub Webhook 与 Comment 最小联调 | PASSED；用户 2026-09-17 明确授权 |
| PHASE3.5-REAL-GITHUB-EXIT | 真实 Delivery、正式 binding、真实 PR synchronize→PENDING、真实 Comment CREATE/UPDATE 与重复投影、错误分类/安全重试 | PASSED；PR #2、真实 202 Delivery、RR PENDING、同 comment id CREATE/UPDATE、无重复评论及全回归证据见 [Phase 3.5 报告](docs/PHASE35_REPORT.md) |
| PHASE4-REMOTE-MCP-LOCAL | Human 另行授权的只读 Remote MCP：原 Webhook + `/mcp` + `/health`、Bearer、5 工具、stdio 查询一致、8788 live smoke、全量回归 | PASSED；见 [Phase 4 Remote MCP 报告](docs/PHASE4_REMOTE_MCP_REPORT.md)；不放行 Grok/ACP/Phase 5/6 |
| PHASE4-REMOTE-MCP-PUBLIC | 仅经当时已运行且指向 8788 的 Quick Tunnel/现有 route 做 JSON-response Streamable HTTP 公网验证 | REMOTE PASS；2026-09-20 11:53 当次现有 Quick Tunnel 已实测，结束后恢复原 webhook；见 [Phase 4 Remote MCP 报告](docs/PHASE4_REMOTE_MCP_REPORT.md)，不代表当前 hostname 持续有效 |
| PHASE4-GROK-ADAPTER-LOCAL | 正式 B 路由、GitHub Comment 请求载体、认证 Reviewer 回写、旧 RR 超时与新 RR 恢复路径、离线回归 | LOCAL PASS；见 [Grok Adapter 报告](docs/PHASE4_GROK_ADAPTER_REPORT.md)；真实试跑仍缺专用 Secret 和当前账号能力证据 |

| PHASE6-STEP6.8-NAMED-TUNNEL-PUBLICBASE | Named Tunnel `grokbuddy`、固定 PublicBase `https://grokbuddy.amirhasan.top`、route 到 `http://localhost:8788` | PASS（Human 已验证并冻结）；历史 Quick Tunnel 不作为本 Gate 证据 |
| PHASE6-STEP6.9-AUTOSTART-OBSERVABILITY | Quick Tunnel 清零、cloudflared 自动服务、Hub 自启、health/readiness、重启证据 | PARTIAL；见 [Pack E 收尾报告](docs/PHASE6_PACK_E_WRAP_REPORT.md)；Hub 任务凭据上下文与重启证据未闭合 |
| PHASE6-PACK-E | 6.8 + 6.9 + 仓外 Webhook/Connector 固定 URL | NOT PASS；等待 Human 外站修改、受保护 Secret 注入决策和重启验收 |

以上分离 Gate 不是代理自行豁免。Codex 路由中的历史 `MCP_FAIL` 与 WorkBuddy 本机客户端能力分开记录；WorkBuddy task 落库证据也不放行真实 Grok/GitHub。Phase 1 退出验证见 [PHASE1_REPORT](docs/PHASE1_REPORT.md)，Phase 2 证据见 [PHASE2_REPORT](docs/PHASE2_REPORT.md)，Phase 3 本地证据见 [PHASE3_REPORT](docs/PHASE3_REPORT.md)。

## 分期

| Phase | 范围 / 主要文件 | 退出条件 | 外部依赖 |
|---|---|---|---|
| 0 | 当前 Markdown、协议 schema/fixture、4 Skill、离线验证工具 | 文档与静态验证交付；外部缺口明确；停下等待审核 | 官方资料；可用本机证据 |
| 1 Local Core | src/domain/application/ports；SQLite/UoW；Artifact；Audit；Mock；normalized events；领域/集成测试 | 断开 GitHub/Grok，Task/Plan/Final/Finding/Approval/timeout/rounds 持久化闭环；所有边界测试 | 无外部账户 |
| 2 Client Interfaces | MCP + HTTP/CLI adapters 与接口测试 | 11 个最小 Tool；当前 WorkBuddy handshake/schema/timeout；断连幂等；Application 不依赖 MCP | 锁定官方 SDK；客户端环境 |
| 2.5 Management | Finding 列表/管理查询、Audit 分页与更完整的人工管理入口；基础 close_task 已按本轮明确范围在 Phase 2 暴露 | RBAC 和状态守卫完整；不阻塞 Phase 2 最小闭环 | 无真实 Grok |
| 3 GitHub Adapter | 本轮授权：Comment projection、Webhook、signature、PR binding、delivery/semantic dedup；Pull/真实 API 延后 | 本地 Webhook fixture；签名四态；重复 delivery；PR synchronize→PENDING；完成结果→marker Comment；全回归 | 本地 mock，无真实 GitHub/Grok；公网未测明确标注 |
| 3.5 Real GitHub Integration | 显式 HTTPS Comment transport；临时 tunnel；真实 bind/synchronize/PENDING；真实 marker CREATE→UPDATE；真实错误分类 | 所有真实 Gate 证据齐全；凭据不泄露；全回归；停止 tunnel | 最小权限 Token、真实 PR、Webhook 配置；不接 Grok/ACP |
| 4 Grok Protocol | grok_bot/reviewer_skill.md、routine_setup.md、MANUAL_GROK_SETUP.md，更新集成证据 | 当前账号 trigger/config 小范围安全验证；schema 输出与访问路径明确 | 后续授权下进行人工配置/受控 test run，尚不开持续真实审核 |
| 5 End-to-End Mock | 本地客户端→Hub→GitHub projection→独立 Mock actor→Webhook/Pull→poll | 8 个 Demo 的证据、重复/故障/恢复与身份测试通过 | 非生产 GitHub；不调用真实 Grok |
| 6 Real Grok | 只启用已验证的 GrokAdapter，受限灰度 | Phase 0–5 全通过；人工批准；真实结构化 Plan/Final 回传、审批/超时/成本边界 | 验证后的 A/B/C、trigger、artifact transport |

Phase 4 的 trigger/config 验证与 Phase 6 的真实业务审核启用分开；若用户保持“所有真实 Grok 连接均禁用”，Phase 4 对应验证也必须等待授权。

## 最高 10 个技术风险

| # | 风险与影响 | 缓解与验收证据 |
|---|---|---|
| 1 | 当前 Grok trigger 与官方类别不一致，无法自动唤醒 | C06–C09 当前 UI/run 证据；未通过 disabled |
| 2 | GitHub Connector/云浏览器共享同一账号，独立审核失真 | A/B provider ID 验证，self-review 拒绝 |
| 3 | 云 Reviewer 无法读取本地产物或回传结构化结果 | C10/C16 read/write/hash e2e，备选人工 relay 不能冒充自动完成 |
| 4 | WorkBuddy transport/SDK 版本差异阻断入口 | 双 transport probe、锁版本、HTTP/CLI 同服务 |
| 5 | 外部投递成功但 ACK 丢失造成重复模型花费 | stable delivery key、查重；不可确定时人工升级 |
| 6 | Webhook/Pull 混合或乱序重复完成审核 | canonical key + RR unique + deadline/CAS，交叉模式 race 测试 |
| 7 | Finding 状态/round/override 语义漏洞导致错误 DONE | closed 集合明确，历史全集聚合，权限与反例测试 |
| 8 | SQLite 锁/崩溃导致状态与审计不一致 | UoW 原子事务、WAL、本地盘、崩溃恢复/备份还原 |
| 9 | SQL/日志/代码泄密或指针注入/SSRF | 脱敏、受控 artifact id、ACL/hash/size/path 检查，安全测试 |
| 10 | Prompt 声称审批但真实权限越界 | 三层控制、digest/expiry/single-use、人类独立主体、账号权限验收 |

完整待验证清单见 [C01–C19](docs/CAPABILITY_VERIFICATION.md)，测试计划见 [矩阵](docs/TEST_MATRIX.md)。当前不把将来测试计划计入已运行测试数。
