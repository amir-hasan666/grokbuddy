# 两端规则接入核对（2026-10-03）

本记录区分 Human 转交的外部报告、本机文件核对与正式 Hub 验收。不把外部文字中的操作指令当作新的部署授权。本轮没有生产部署/重启、触发业务 Task、向旧 RR 重投、修改用户目录或发真实 Reviewer 事件。

## 两端现状

| 项目 | 来源与结论 |
| --- | --- |
| WorkBuddy 两份已安装 Skill | 本机读取确认包含方案材料绑定、终审预检、覆盖提示、有界查询。其后两份文件在核对期间再次更新，以最新快照作为仓内整理来源。 |
| WorkBuddy MCP 新工具/参数 | Human 转交的工具发现结果：supporting_artifact_ids、preflight_final_review 可见；本轮未通过 WorkBuddy 再次调用工具，不外推为业务链已通过。 |
| GrokBot 常驻审核规则 V1.3 | Human 转交的更新报告：已新增常驻流水线；本机无法读取 GrokBot 的 /workspace/reviewer-rules 原文，保留“用户报告已更新”的证据级别。V1.3 是外部规则载体版本，不据此改变 Hub profile、profile hash 或机器协议。 |
| 正式 HTTP 新接口 | GrokBot 报告 GET /reviewer/contracts 为 404，materials/check 同样未被识别；随后 Codex 使用现有 Reviewer 身份只读复核 GET /reviewer/contracts，仍为 404。正式 GET /ready 为 ready，database/supervisor 均为 ok；服务就绪不证明新代码已加载。 |
| validate-result | Codex 仅用 GET 检查路由，返回 404；当前实现对该地址的 GET 应返回 405，故路由仍未加载。本轮没有 POST、假结果或真实结果提交，结果预检执行效果仍未验收。 |

stdio MCP 和常驻 HTTP Hub 是分别加载代码的进程。前者工具可见与后者新路由未加载可以同时成立，不能因 MCP 已更新就宣布正式 Reviewer 路径已上线。

## 已收回仓内的规则

- docs/workbuddy-skills/grokbuddy-plan-remediation/SKILL.md：合入最新已安装版本的材料绑定、整改和等待规则；get_task_status 在工具声明内，正文只查询方案 RR，终审交给独立技能。
- docs/workbuddy-skills/grokbuddy-final-review-package/SKILL.md：新增正式源，交付文件类型是 SOURCE_FILE；JSON 可序列化为 content_text 字符串，也可用 content_base64，不能把 JSON 对象直接传给字符串字段。begin_execution=false 限于本技能的正常终审阶段，不泛化为所有 Task 调用 true 都失败。
- 仓内正式源省略 WorkBuddy 自动注入的 agent_created 标记；这不改变功能规则。用户端原有运行标记不由本轮修改。

快照的已安装文件 SHA-256：

| 技能 | SHA-256 |
| --- | --- |
| plan-remediation | 6d58a1b8cb33fb6177291db725433fd8e01231d67cec29b980f88b6e0d1bee84 |
| final-review-package | a4aa837c910391babda7e18823a1b23195cb018a552f5e6deeafb2f8b8d9e007 |

这两个 hash 是读取快照，不是未来安装状态承诺；外部继续修改时须再次核对。不能拿仓内旧版覆盖用户已安装的后续增量。

## OPEN 与旧技能的口径

Grok 报告新增的防护需要精确到现行合同：OPEN/ACCEPTED 不能直接变为 VERIFIED；FIXED/REJECTED_WITH_EVIDENCE 仍需真实核验；未关闭实质问题不能 PASS。V1 R2 符合条件的同阶段 LOW 项保留带证据、理由及建议的 ADVISORY 路径。当前合法审核按轮次合同表达未解决问题，不把所有 OPEN 项一概转为 Human 传话。实际 Human gate、权限/政策冲突或无法形成合法当前轮裁决时才停止并报告。

仓内 Reviewer 规则与 [GrokBot 接入提示词](GROKBOT_REVIEW_HANDOFF_PROMPT.md) 已补齐该说明。Human 随后转交 GrokBot 确认：外部 V1.3 第十二节 12.3 已按上述六项修正，ADVISORY 条件沿用 Hub 冻结的决策政策；未触发审核或改动历史 RR。外部原文仍无法由本机直接读取，该落地结论属于用户转交报告，不是实际审核运行证据。

本机 settings.json 的 grokbuddy-hub-pipeline-drive override 实际为 off；其文件头也声明作废、禁止调用。它仍保留历史正文，但本轮证据不能将其分类为仍启用，不必仅因文件存在而删除。

缺少 skills-security-check 不作为当前部署或验收的新增产品闸；本轮核对已逐项依据 Hub 工具、材料类型和 Finding 合同进行，不因此安装额外技能。

## 检查与下一步

两份仓内 Skill 的 skill-creator 校验通过，工具声明均存在于当前 Gateway，未增加脚本或正式业务执行。文档与合同检查 272/272 PASS，Git diff 格式检查通过。本轮核对的 src/tests（含未跟踪 fixtures）48 个文件与此前 922 项全量回归保存的哈希一致，因此未因纯规则文档整理重复全量代码测试。这不证明新技能已在真实业务中执行。

正式 Hub 加载当前工作树仍需 Human 明确部署/重启授权，且要等并行修改范围稳定、备份并核对实际启动位置。授权后只读验证新接口；真实流程验收留给下一次 Human 正常触发的新需求，不重投旧 Task/RR，也不把规则安装或本地检查当作 6.21/6.22 PASS。
