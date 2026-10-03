# 审核交接优化记录（2026-10-02）

本次是 Human 授权的 Codex 仓库维护，针对替 WorkBuddy 与 GrokBot 传话、查错、补材料的问题。不扩展多用户能力，不改变 V1 裁决、审核轮数或历史结论。工作树中已有 Profile、方案整改及文档修改，本次保留。下表只记录交接优化。

| 断点 | 本次变化 | 边界 |
| --- | --- | --- |
| HTTP 结果 schema 缺少公共依赖 | 认证 GET `/reviewer/contracts` 返回四份 schema，按 `$id` 建 registry | 不变更协议版本或现有 schema；旧地址保留 |
| 手抄字段、提交后发现结构/版本错误 | 取件新增 result_bindings；POST `/reviewer/requests/<RR>/validate-result` 检查结构、冻结绑定、Reviewer、当前 CAS | 与正式处理共用 Domain 规则；不入箱、不 ACK、不耗轮次，不证明 Finding/裁决语义通过 |
| 202 后缺少明确接纳依据 | ingress 回执新增 request_status、Hub task、匹配结果哈希的 accepted_review | READY、REJECTED、ReviewStarted、LATE_EVENT 不显示为有效完成；reported/effective verdict 分开 |
| 方案引用源码却无材料绑定 | submit_plan 支持 supporting_artifact_ids，冻结同 Task 的 SOURCE_FILE/EVIDENCE 到 RR context | 同 Task 未引用和跨 Task 材料不开放；更新方案不改旧 RR 清单 |
| 清单不证明材料可读 | GET `/reviewer/requests/<RR>/materials/check` 检查白名单字节/哈希 | 不 ACK、不推进任务，不代替阅读和质量判断 |
| 终审材料错误在自测状态改变后才暴露 | 新只读 preflight_final_review；request_final_review 在状态命令前自动检查 | 缺操作方法/文件、错类型、跨 Task、损坏字节、超范围先拒绝；正式提交仍重验并执行原守卫 |

终审预检返回 provided_file_paths 和 changed_files_without_source。Human 尚未确认是否每个变更文件必须交全文及删除文件说明方式；本次保留原 generated_files 非空且属于 changed_files 的正式规则，不新增此类阻断，将 semantic_material_completeness 标为未检查。

## 外部接入

后续规则更新与本机技能源收敛见 [2026-10-03 接入核对](REVIEW_HANDOFF_INTEGRATION_20261003.md)。下段保留 10-02 交付时的连接器与安装边界，不代表外部两端一直没有更新。

当前没有可直接更新 WorkBuddy/GrokBot 常驻规则的连接器，仓内文件不会自动安装到外部两端。复制 [WorkBuddy 提示词](WORKBUDDY_REVIEW_HANDOFF_PROMPT.md) 和 [GrokBot 提示词](GROKBOT_REVIEW_HANDOFF_PROMPT.md) 到现有对应会话，只更新规则、检查能力，不建业务 Task、不重投旧 RR、不发送假结果。

代码加载与外部规则更新后，正式使用情况须由下一次 Human 正常触发的需求检验，本地 fixture 不能代替正式证据。

## 验证与部署

新增 tests/test_review_handoff.py 的 20 个本地用例通过：无状态变更的预检、结构/绑定错误、版本刷新、READY/接纳区分、重放、历史材料冻结、损坏材料及 Final 自动检查。全部是临时 Hub、合成事件，不是正式 Reviewer 验收。

最终全量回归：922 passed in 230.53s。文档与合同检查：272/272 PASS。Git diff 格式检查通过。第一次全量运行中有一处旧工具清单断言未纳入 preflight_final_review；按最终清单核对后，上述最终全量无失败。Remote MCP 的只读工具范围未扩大。

本次未生产部署/重启、改 Credential、修改正式业务数据或执行 GitHub 写操作；不宣称新接口已在正式进程生效。部署/重启须按 AGENTS 硬规则第 6 条取得明确授权。新定义 6.21/6.22 不因本地检查改变状态。
