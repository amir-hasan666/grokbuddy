# 方案 V1：allslowcheck —— 中间层 IIS 服务器上的「终端卡顿只读归因」APP

## 0. 元信息与已确认前提
- 触发：WorkBuddy 用户消息（含触发语），Task 由入口取证创建。
- 部署位置：中间层 IIS 服务器（Windows）。交付目录：allslowcheck/（相对项目根）。
- Human 已确认四项前提：① 采集范围 = 仅服务端 + 网络侧（不登录终端、不装代理、零终端扰动）；② DB 口径 = 复用既有 Oracle 只读链路；③ 交付形态 = 便携 Python + 控制台；④ 外发 = 严格脱敏。

## 1. 需求逐条映射
| # | 需求 | 设计落点 |
| --- | --- | --- |
| 1 | 检查软件卡顿原因 | 五维采集（DB / 中间层进程与 IIS / 主机资源 / 网络 / 应用日志）+ 量化归因 |
| 2 | 部署在中间层 IIS | 便携目录、零安装、只读、不改 IIS |
| 3 | 学习 SlowSQLTool | 迁移其 assert_readonly 双闸门范式、白名单 variants、对象级脱敏、便携 python + instantclient 路线 |
| 4 | 覆盖网络 / IIS / CPU / 内存 | probe.py 五个采集器：system / iis / network / db / applog |
| 5 | DeepSeek 实时分析与定向复查 | ai_director.py：每轮产出「根因判定 + 下一批白名单检查项」；不超过 5 轮；达 5 轮触发 human gate；定位根因即终止 |
| 6 | 按影响因子占比降序 | rank_score = 影响量(ms) × 置信权重 × 影响面权重，报告按此降序 |
| 7 | 全程只读 | 命令级只读白名单（远超 SQL 关键字闸门）+ 只读事务 + 除 output/ 外不写任何文件 |
| 8 | 报告简洁 | 只列可能造成终端卡顿的因子 + 一行式「已排除项」 |
| 9 | 先做隐性需求与隐患分析 | 见第 2 节，结论已硬化为设计约束 |
| 10 | 输出到 allslowcheck | 见第 8 节 |

## 2. 隐性需求与生产隐患（需求 9）→ 已转成硬约束
### 2.1 隐性需求
- H1 因果链跨机：app 只能直采「中间层主机 + 网络 + DB」，终端本机不可见 → 用「到终端的网络往返/丢包」作为终端侧可得的最强代理证据，并在报告中显式标注该边界。
- H2 需要目标清单：config.json 必须提供 终端 / 中间层 / DB 三类目标；缺清单即拒绝运行并给出填写指引。
- H3 需要命令级只读闸门（非 SQL 关键字）：本 app 会调 PowerShell / WMI / netsh / appcmd / socket，风险面远大于 SlowSQLTool。
- H4 需要可中断交互面 + 无人值守模式。
- H5 需要量化排序口径，否则排序主观。
- H6 需与 CFLAWMSPC / LADBAJC / SlowSQLTool 去重：本 app 是「编排 + 统一归因层」，采集模板化、不重复造 exe。
- H7 需要排除规则，才能满足「简洁」。

### 2.2 生产隐患与规避（全部落为设计约束）
- P1 Oracle Diagnostics Pack 许可：AWR / DBA_HIST_* / ASH 属收费选件 → 默认仅查 V$ / GV$ 实时视图；AWR 由 enable_awr = false 默认关闭，开启需显式人工确认并记录合规提示。
- P2 诊断自身造成负载：并发 = 1、单条超时、单轮条数上限、总时长预算、全局限行数。
- P3 数据外发合规：默认严格脱敏；原文只落本机 *_raw.json 并带警告头。
- P4 误触写操作：结构化模板（exe + 子命令 + 受限参数）替代自由字符串；元字符硬拒；写动词黑名单；每条执行前打印并落审计 JSONL。
- P5 密钥管理：独立 config.json，不复用 SlowSQLTool 的配置；报告 / 日志 / AI 载荷永不回显密钥；README 提示轮换既有明文 key。
- P6 服务器准入：零安装（不写注册表、不装服务、不改 IIS、不建计划任务）。
- P7 中文路径：沿用「启动时自动复制到临时 ASCII 目录」兜底（Oracle Thick 限制）。
- P8 间歇性卡顿：支持 window_seconds 窗口内多次采样取分位，报告标注采样窗口。

## 3. 架构与数据流
run.bat → main.py
1. 加载 config.json（校验目标清单 / 阈值 / 轮次预算）
2. Round 0 基线采集：probe.py 执行 system / iis / network / db / applog
3. 归一化为 findings[]（含 impact_ms / confidence / scope / evidence）
4. 排序，并生成「本机原文产物」与「可外发脱敏摘要」
5. ai_director.py → DeepSeek（thinking = disabled）；回包 = {root_cause_found, ranked_findings[], next_checks[模板 id + 受限参数]}
6. 白名单选择题 → 校验 → 只读执行 → 证据并入 findings[]
7. 若 root_cause_found 或达到 5 轮 → 退出循环
8. 输出 report.txt + findings.json + findings_raw.json + audit_commands.jsonl + ai_rounds.json

轮次上限 max_rounds = 5；每满 5 轮触发 human gate（控制台 y / N）；human_gate_mode 支持 interactive（默认）与 auto_stop（无人值守：直接停止并输出「现有结果 + 下一步排查目标」）。

## 4. 影响因子模型与排序口径（需求 6）
每条 finding 字段：
- impact_ms：对终端一次业务操作可见延迟的贡献估计（DB 等待按「窗口内该等待累计 ÷ 并发会话」折算；主机资源按「超标比例 × 经验系数」折算；网络按「RTT 增量 × 往返次数」折算）。
- confidence：high = 直接量测 / medium = 间接推导 / low = 启发式，权重 1.0 / 0.6 / 0.3。
- scope：all = 影响所有终端 / subset = 部分 / single，权重 1.0 / 0.7 / 0.4。
- rank_score = impact_ms × confidence_weight × scope_weight，降序排列。
- 排除规则：rank_score 低于 exclude_threshold（默认 50 ms 当量），或 confidence = low 且无二次证据 → 只进「已排除项」，不进正文。

因子清单（首版模板，全部只读）：
- DB：会话与等待事件分布、活动会话与阻塞链（enqueue / lock）、top SQL 的 elapsed / CPU / 物理读、log file sync 与日志切换、undo / temp 压力、会话数与进程数水位。
- 中间层进程与 IIS：w3wp CPU / 内存 / 句柄、应用池状态与请求队列长度、请求执行时间分位、5xx 与超时计数、工作进程重启与回收记录。
- 主机资源：CPU 总占用与处理器队列、可用内存与 pagefile、磁盘队列长度与写延迟（数据盘 / 日志盘分层）。
- 网络：服务器到 DB 的 RTT 与丢包；服务器到终端 RTT / 丢包 / TCP 重传；若终端经 HTTP 访问则含 HTTP 往返与 DNS 解析耗时。
- 应用日志：IIS 日志与中间层应用日志中的超时 / 异常峰值、连接池耗尽迹象。

## 5. 只读安全设计（需求 7；本方案核心）
- 结构化模板：所有可执行动作登记为模板 {id, exe, args_spec, readonly_basis, dimension}；args_spec 只允许数值 / 枚举 / 白名单主机名占位符。
- AI 只能选 id + 填受限参数；越界即拒（等价于 SlowSQLTool 的白名单选择题）。
- 自由生成通道默认关闭；开启时仍须过四道关：① 元字符与写动词闸门 → ② 模板归约（必须能映射回某个模板）→ ③ 打印全文与依据 → ④ 执行时套条数与超时上限。不通过即硬拒，人工确认也不放行。
- 元字符硬拒：分号、竖线、大于小于号、与号、美元符、圆括号、花括号、换行、反引号、双与号、双竖线、重定向。
- 写动词硬拒（不区分大小写）：iisreset；appcmd 的 set / add / delete / start / stop / recycle / backup / restore；netsh 的 set / add / delete；reg add | delete | import；以 New- / Set- / Remove- / Stop- / Start- / Restart- / Enable- / Disable- 开头的 PowerShell 动词；sc create | config | delete；schtasks 的 create / delete / change；Invoke-Expression | iex | cmd /c；takeown | icacls /grant。
- SQL 闸门（迁移自 SlowSQLTool）：FORBIDDEN_RE 关键字闸门 + 必须 SELECT 开头 + 禁分号多语句 + assert_no_business_call（禁任何 A.B( 形式的包 / 函数调用）+ SET TRANSACTION READ ONLY。
- 文件系统只读：仅允许写 output/ 下产物；不触碰 IIS 日志、不轮转、不删除任何文件。
- 审计：每条命令写 audit_commands.jsonl（时间、模板 id、命令全文、依据、耗时、结果摘要）。
- 失败降级：单条失败记「不可用 + 原因」，不中断整体，不做任何重试性写操作。

## 6. AI 定向补查与轮次 / human gate（需求 5）
- 模型：deepseek-flash（V4.1-Flash），thinking = disabled，max_tokens 不低于 4096，temperature 不高于 0.2（规避 V4 默认开思考吃掉 completion 的已知问题）。
- 每轮输入：脱敏摘要 + 已执行检查清单 + 已排除项 + 上一轮 AI 输出（仅文本，不含原文）。
- 每轮输出（严格 JSON）：{root_cause_found, confidence, ranked_findings[], next_checks[{template_id, params, rationale}]}；解析失败降级为「不推进、输出当前结果」。
- 终止条件：root_cause_found = true 且证据强度不低于 medium；或轮次达到 5。
- human gate：达 5 轮时控制台提问「是否继续深入 5 轮？(y/N)」。y → 再开 5 轮（累计预算由 max_total_rounds 兜底）；N 或无 stdin（auto_stop）→ 输出「现有结果 + 下一步排查目标」并结束。
- 不进入无界循环：单次运行总轮次有硬上限；任何一轮不得重复已执行的同一检查。

## 7. 报告形态（需求 8 + 6）
输出 output/<YYYYMMDD-HHMMSS>/report.txt（纯文本，不含图表）：
- 抬头：采样窗口、目标（中间层 / DB / 终端 N 台）。
- 一、根因判定：一句话 + 置信度。
- 二、按影响因子降序：每条含「影响 X ms · 影响面 · 置信度」+「问题 / 证据 / 归因 / 只读建议手段」。
- 三、已排除项（不影响终端速度）：一行一条。
- 四、下一步排查目标（未闭环项）。
- 五、边界声明：终端本机资源不可见（本轮采集范围 = 服务端 + 网络侧）。
不堆 SQL 全文，不列全部查询。

## 8. 交付物清单与变更范围
- allslowcheck/main.py —— 入口、配置校验、编排循环、human gate、排序与报告
- allslowcheck/probe.py —— 只读命令白名单执行器 + 五维采集器（system / iis / network / db / applog）
- allslowcheck/ai_director.py —— DeepSeek 客户端、脱敏摘要、白名单选择题、四道关、轮次控制
- allslowcheck/_selftest.py —— 自检（排序 / 排除 / 脱敏不泄漏 / 闸门拦截 / human gate / 解析容错）
- allslowcheck/config.example.json —— 配置样例（目标清单 / 阈值 / 轮次预算 / 闸门开关）
- allslowcheck/run.bat —— 双击启动（纯 ASCII、无 BOM）
- allslowcheck/README.txt —— 部署与使用说明（含安全边界与运维提示）
运行期依赖（便携 python、instantclient）按 README 步骤从既有 SlowSQLTool 目录复制，不纳入本任务变更范围。

## 9. 验证计划
- 离线桩测试（_selftest.py）：排序单调性、排除规则、脱敏不泄漏（断言输出中不含给定主机名 / IP / 表名 / 密钥）、只读闸门对 30 条以上写命令与元字符样本 100% 拦截、human gate 无 stdin 时 auto_stop、AI 响应解析容错（截断 / 非 JSON / 字段缺失）。
- 现场试跑（需 Human 在中间层执行，本任务不代为操作）：run.bat 单轮采集，确认零写、报告可读。
- 明确不做：不改 IIS、不改 DB、不装服务、不动终端。

## 10. 未验证项与已知限制（如实声明）
- U1 终端本机 CPU / 内存 / 磁盘不可见（本轮范围外），报告中显式声明边界。
- U2 真实环境（中间层 / DB / 终端）不可在本机复现，现场试跑须 Human 执行。
- U3 Oracle 版本与权限差异会导致部分视图不可用；采集器按「能力探测 + 不可用清单」降级，不报错中断。
- U4 AWR 通道默认关闭，未验证开启路径的现场效果（合规优先）。
- U5 _selftest.py 为桩测试，不代表真实目标环境通过。
