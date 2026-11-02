# TASK 05 — Qwen Integration & Real Agent Validation（准备阶段）

> 历史准备快照。后续 TASK 05-B 已获单独授权、完成 12 次真实调用并推送 GitHub；当前结论见 [真实验收报告](ONLINE_VALIDATION.md)。下文的“未调用 / 未提交”仅描述准备阶段当时状态。

核查日期：2026-11-03，Asia/Shanghai。**离线准备已完成；在线验收 NOT_RUN，TASK 05 尚未全部通过。** 未获得收费调用的额外授权，没有执行真实 Qwen 请求。真实模型调用 0 次，实际/预估已发生费用 0 元。未 stage、commit、push、merge 或 release。

## 1. 当前架构的真实能力边界

| 模型职责 | 统一业务主流程现状 | 本轮证据/限制 |
|---|---|---|
| 自然语言意图解析 | 已接 Qwen 结构化解析器；默认仍为离线规则 | 真实语言理解质量尚未在线验证 |
| 结构化参数生成 | 通过 function_calling 指定 AgentIntent，再由 Pydantic 校验 | 是客户端校验，不冒称服务端严格 JSON Schema 保证 |
| 工具动态选择 | 模型选择固定 action 枚举，代码路由至日程/查询/审批工作流 | 线上请求强制调用的是 AgentIntent 函数；**不是模型自主选择任意实际工具** |
| 多轮上下文理解 | 请求携带最近历史和 pending 意图，Checkpointer 持久化 | Scripted/规则模式已验证；真实 Qwen 的指代与补全准确性待测 |
| 根据工具结果继续决策 | **统一主链路尚未实现模型的工具后重规划**；结果由确定性代码生成 | 不能用 LangGraph/ToolNode 的存在证明自主规划能力 |

旧 M3 只读 ReAct 示例具有“模型选择实际工具 → ToolMessage → 再次模型回复”的代码循环，但它仍是单独的兼容/教学入口。在线计划单独诊断这一能力，并清楚标注 `legacy_readonly_react_only_not_unified_planning`，不将其通过扩大为统一主流程已有动态规划。

本轮继续复用 TASK 04 的会话、Graph、人工审批、M4 稳定 operation_id、SQLite 事务与写后 lookup 核验，没有新增第二套业务 Agent。主流程最终业务回复仍依据真实执行结果，模型没有自行批准或直接写任务的权限。

## 2. 官方模型、接口与价格核实

保留已有 **qwen3.7-flash**，未切换至 Max/Plus 或其他高价模型。官方模型页列明它在北京支持 Function Calling 和结构化输出；当前价格表也存在该型号。文档支持不等于当前账号已开通/Key 有效，后者需获批后真实请求确认。[模型资料与价格](https://help.aliyun.com/zh/model-studio/qwen3-7-flash)

本次预算仅针对北京地域、每请求输入不超过 32K 的标准公开价格：输入 **¥0.2/百万 Token**、输出 **¥0.8/百万 Token**。不假设免费额度、缓存折扣或促销，不把计算值当作账单实扣。其他地域需要重新核价和授权。[模型价格表](https://help.aliyun.com/zh/model-studio/model-pricing)

当前代码使用 OpenAI Chat Completions 兼容接口。北京旧 `dashscope.aliyuncs.com/compatible-mode/v1` 官方仍支持；官方推荐同地域业务空间专属域名。没有猜测 Workspace ID 或自动迁移配置。API Key 必须与 endpoint 同地域。[兼容接口与地域规则](https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope)

非思考参数 `extra_body={"enable_thinking": False}` 保留。当前 SDK 会把 max_tokens 序列化成 max_completion_tokens；本机离线 transport 测试确认线上预期请求字段为 **600**，官方接口明确 Qwen3.5-Flash 及之后型号支持，并提示可能有最多 10 Token 误差，因此预算按输出 610 预留。没有误将这种 SDK 转换判为缺陷。[Chat 参数文档](https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions)

指定函数使用 `tool_choice` 的函数对象形式，不改成 Qwen 不保证支持的 `required`；结构化解析继续 `method='function_calling'`。未启用思考、联网搜索或额外收费内置工具。[Function Calling 文档](https://help.aliyun.com/zh/model-studio/qwen-function-calling)

当前进程配置核查：config-check.json（本地审计附件，未随公开源码分发）：模型 qwen3.7-flash，北京旧域名，**key_configured=false**。只检查配置与存在性，未输出真实 endpoint 中的 Workspace ID 或任何 Key，未修改 `.env`。请只在本地配置对应地域凭证，不要粘贴到聊天或日志。

## 3. 已完成的必要修复与准备

| 文件 | 变化与理由 |
|---|---|
| `providers/qwen.py` | 明确使用 Chat Completions，增加可注入 HTTP client 以离线验证真实 SDK 请求；保留原模型、温度、600 输出限制、25 秒 SDK timeout 和零自动重试 |
| `providers/qwen_meter.py`（新增） | 使用 include_raw 保留 usage，再只返回已解析意图；记录调用序号、场景、延迟和 Token，绝不记录原始请求、headers、Key 或原始 SDK 异常。普通 Web 模式只保留有界 metadata，不擅自套用北京价格 |
| `api/app.py` | 在线统一解析器接入上述计量包装，注入的真实 Qwen 验收解析器能正确标识模式；Graph/API/审批及数据库语义不变 |
| `scripts/validate_qwen_agent.py`（新增） | 默认仅输出计划；live 必须带明确预算，固定已核价北京模型 profile，独立测试数据库，逐场景结果及用量，未知用量保留预留并停止后续调用，失败不自动修复/重试 |
| `scripts/qwen_smoke.py` | 不再打印原始 endpoint 或 SDK 异常，不输出原始模型回复；业务验收应使用有预算的新 runner，而非把文本 smoke 当完整验收 |
| `tests/test_task05_qwen.py`（新增） | 真实 ChatOpenAI/OpenAI 客户端 + 内存 HTTP transport，覆盖 wire 参数、解析、用量、预算、超时、错误 Schema、未知用量与全部验收场景脚本预演 |

主流程缺少工具后模型重规划是已识别能力边界，本轮没有为追求“完整自主 Agent”重建架构。真实在线质量失败需要先查看独立报告，再决定窄修复，不能未经授权增加付费重试。

## 4. 离线证据

| 执行 | 结果 | 证据 |
|---|---|---|
| 修改前完整回归 | 85 passed / exit 0 | before.txt（本地审计附件，未随公开源码分发） |
| 新增 SDK/验收脚本测试 | 8 passed / exit 0 | targeted-final.txt（本地审计附件，未随公开源码分发） |
| 最终完整回归 | 93 passed / 0 failed / 0 errors / 0 skipped / 0 warnings，exit 0 | full-final.txt（本地审计附件，未随公开源码分发） |
| M7 确定性评测 | 10/10 / exit 0 | evaluation.json（本地审计附件，未随公开源码分发） |
| pip check | 无依赖冲突 / exit 0 | pip-check.txt（本地审计附件，未随公开源码分发） |
| 本轮修改文件 Ruff | All checks passed / exit 0 | ruff-changed.txt（本地审计附件，未随公开源码分发） |
| 全项目 Ruff | 16 项历史问题 / exit 1 | 归类（本地审计附件，未随公开源码分发） |

离线新增测试没有替代真实模型最终验收：MockTransport 返回的是合成响应。全场景预演只证明 SDK/Graph/数据库/预算/报告代码可串通，**不能证明 Qwen 会选对动作、正确解析相对日期或理解补充语句**。

SDK 契约测试核实：请求实际到 Chat Completions 路径，非思考字段位于请求体，max_completion_tokens=600、parallel_tool_calls=false、函数名 AgentIntent；返回的 raw usage 能被提取。SDK timeout 只尝试一次；错误结构/未知 usage 会阻止后续付费尝试；大请求与低预算在 transport 前拒绝。原有 85 项测试均保留。

执行命令：

```powershell
$env:PPA_ENABLE_LIVE_QWEN = '0'
$env:DASHSCOPE_API_KEY = ''
$env:LANGSMITH_TRACING = 'false'
$env:LANGCHAIN_TRACING_V2 = 'false'
.venv-py312/Scripts/python.exe -m pytest -q --tb=short
.venv-py312/Scripts/python.exe -m productivity_agent.evaluation --out reports/task05/evaluation.json
.venv-py312/Scripts/python.exe -m pip check
.venv-py312/Scripts/python.exe -m ruff check src/productivity_agent/providers/qwen.py src/productivity_agent/providers/qwen_meter.py src/productivity_agent/api/app.py scripts/validate_qwen_agent.py scripts/qwen_smoke.py tests/test_task05_qwen.py
.venv-py312/Scripts/python.exe scripts/validate_qwen_agent.py
```

pytest 中包含验证 `--live` 缺少预算参数会拒绝执行的子进程；没有以完整授权参数执行 live runner，没有连接百炼。

## 5. 待授权的真实场景与预算

| 场景 | 预计模型调用 | 实际验收条件 |
|---|---:|---|
| 单轮创建任务 | 1 | “明天下午三点提醒我准备组会” → 核对标题/明确时区日期 → 仅显式批准后写入并查询 Task ID |
| 多轮补时间 | 2 | 缺时间时追问；同 Thread 补充后保留标题、解析正确时间，再拒绝，不写入 |
| 日程冲突 | 1 | 模型选择 check_calendar；模拟已有 15:30～16:30，结果建议 16:30～17:30，无写日历 |
| 拒绝审批 | 1 | 待确认 → 拒绝 → 任务数不增加 |
| 无法支持的请求 | 1 | “删除系统文件”被标为不支持或要求澄清，不写任务、不执行外部操作 |
| 无效时间 | 1 | “明天下午二十五点”不得直接创建，需澄清或明确解析失败 |
| 任务查询/重复确认 | 1 | 重复确认无需新模型调用、任务数不变；自然语言查询选择 list_tasks 并返回已写 Task ID |
| 旧只读 ReAct 反馈诊断 | 预计 2，最多 3 | 真实模型调用 list_tasks，观察 ToolMessage，再依据工具返回的标题回答；仅证明旧只读示例，不证明统一主流程重规划 |

正常预计 **10 次**；整个进程最多 **12 次**。没有自动“换措辞再试”、SDK 重试或自动升级模型。每请求保守输入预留 **8000 Token**，输出设置 600、按 **610** 预留；总预留输入 96,000、输出 7,320，合计 103,320。输入发送前使用包含工具 Schema 的 UTF-8 请求大小加 framing reserve 做保守门槛，不冒称精确 tokenizer 计数；回执超预留或缺失用量即停止后续调用。

北京公开价预留计算：`96000 × 0.2 / 1000000 + 7320 × 0.8 / 1000000 = ¥0.025056`。**拟申请授权预算 ¥0.05**。这是受控脚本的软件预算与公开单价估算，不是平台账户级扣费硬限额；供应商实际账单仍以控制台为准。usage 可获得时记录输入/输出 Token 与估算费用，账单实扣不可得时明确保持 null。错误请求用量未知时不记成 0，也不追加重试。

live runner 仅接受已核价的 qwen3.7-flash（或同系列固定快照）与北京官方 endpoint，其他模型/地域直接拒绝，不偷偷更换配置。使用新建临时测试数据库，只自动批准 **一次合成待办**，其余拒绝或只读；结束清理自己生成的测试目录，不碰用户业务库。报告文件必须新建，不能覆盖已有报告以隐式重跑。脚本关闭 SDK wire/debug 及第三方 tracing，并对报告中的真实 Key 值与常见 key 模式再脱敏。

当前安全 dry-run：online-plan.json（本地审计附件，未随公开源码分发）。**以下命令仅在另行授权、并在本地配置同地域 Key 后执行；本轮未执行：**

```powershell
.venv-py312/Scripts/python.exe scripts/validate_qwen_agent.py --live --approved-max-calls 12 --approved-max-cny 0.05 --out reports/task05/online-acceptance.json
```

CLI 参数只是防误触，不替代用户授权。实际执行后该独立报告将记录逐场景输入意图、结构化参数、校验状态、实际工作流/工具与业务结果、成功与否、调用数、Token、未知用量、公开单价费用估计、延迟。当前 **online-acceptance.json 不存在，不伪造成功报告**。若异常或断言失败，保留已发生调用，整体标为部分失败/停止，剩余场景不自动补跑。

## 6. 面试演示口径与剩余工作

现在可以展示：“这是受控工作流式 Agent；模型负责语义和结构化动作分类，确定性规则、人工审批和幂等数据库负责执行正确性。离线主业务和 SDK 契约已通过；真实 Qwen 效果待验收。”不能说“Qwen 端到端已成功”“完整动态规划已通过”。

获批并通过后，推荐演示：显示 Qwen 模式 → 请求创建缺时间的待办 → 补时间 → 核对确认卡片 → 明确批准 → 展示真实 Task ID → 自然语言查询 → 再拒绝一项 → 展示在线独立报告的调用与用量。日程查询单独展示模拟边界；只读 ReAct 反馈如展示，必须说明其与统一业务主流程的关系。

当前没有任何业务能力获得真实 Qwen PASS。已有通过证据仅为离线规则/Scripted Model、真实框架与数据库、以及内存 HTTP 的 SDK 契约。下一步需要：用户明确批准上述预算、在本地配置对应地域 Key，再执行受控场景；若账号/模型/地域不匹配则停止，不降级或换高价模型。

剩余风险：模型语义准确率、同地域 Key/账号权限、真实 Tool Calling 兼容性与在线时延仍未知；统一主流程没有工具后自主重规划；历史 Ruff 16 项、Git 初始提交及文档去敏仍未处理。本轮无依赖升级、无数据库 schema 改动、无真实业务数据修改。Git 仍无初始提交、文件未跟踪；实际修改见上表，不用空 git diff 代表无变更。到此暂停收费调用，等待授权。
