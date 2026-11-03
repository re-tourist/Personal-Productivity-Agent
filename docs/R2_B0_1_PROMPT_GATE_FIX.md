# PPA R2-B0.1：Prompt 兼容性 Gate 修复

范围：只修改验收工具、测试、错误快照和文档。正式 `src/`、Graph、Prompt、数据库 Schema、
依赖版本与原 179 项测试及其断言保持不变。没有开始 R2-B1。

固定原始契约来源仍为 `40d837c19f42ffd373686c30f4797df2e2598e23`；修复前 R2 HEAD 为
`fd158bea8b8a1af913c6644facb10ab864df164b`，PR #13 开放，Push/PR CI 均成功。
CI 成功不能弥补原 Prompt 采集缺口，以下单独记录更正及有效性证据。

## 1. 原始缺口与更正

原采集器扫描 `workflows/*.py` 的 AST，只选择含换行的字符串常量。
Assistant 的相邻字符串字面量拼接没有换行；Natural Language 的 Prompt 包含动态时间拼接，
其常量也没有换行。于是实际快照中两者分别只有函数/模块 docstring。
Tool Agent 的多行常量被采到，但仍是包含 `{reference_now}` 的原模板，没有实际消息或工具往返。

| 子系统 | 修复前真实快照 | 修复后实际模型边界契约 |
|---|---|---|
| Assistant | `invalid_numeric_clock` 文档字符串；无系统 Prompt | 3 场景/3 次调用：fresh、待澄清且有 pending/candidates/18 条历史、已有历史但不承接 pending |
| Natural Language | 模块文档字符串；无系统 Prompt | 2 场景/2 次调用：日程解析、带不同 UTC 偏移的 unsupported 合成请求 |
| Tool Agent | 模块文档 + 未格式化 SYSTEM_PROMPT | 1 场景/2 次调用：完整历史、当前用户消息、真实 ToolNode 往返、AI tool_call 和 ToolMessage |

此次授权修正 `tests/fixtures/r2_b0/contracts.json`。已比较修复前 Git blob 与新快照：
**只有 `contracts.prompts` 分节改变**；完整 OpenAPI、HTTP/SSE、Graph、Schema、Tool 和 Store
签名等其他分节均相同，依赖版本相同。原错误快照仍可从修复前提交复核；原始 B0 报告新增醒目更正说明，
保留历史验收次数、失败和执行记录，没有将其改写为已覆盖实际 Prompt。

## 2. 运行时采集与严格比较

`scripts/r2_baseline_worker.py` 的 `capture_prompts()` 构建真实 Graph、Store、Saver 和 ToolNode。
只在模型边界注入 CapturingExtractor / CapturingScriptedModel，固定返回现有 Pydantic Schema
或 AIMessage，不构造模型 SDK，不发模型请求。采集数据库的持久任务条数断言为 0。

保留内容：

- 实际 messages 容器类型；tuple 的角色/正文及 BaseMessage 类名和完整 `model_dump` 字段。
- 完整系统指令和原始用户消息，含引号、中文、换行和合成的“忽略指令”文字。
- Assistant 原始 context JSON：message、reference_now、timezone、history、candidates、pending，
  不解析后再序列化替换原文；另独立断言所有字段、18→12 条窗口、pending 条件、UTC→Asia/Shanghai 换算。
- Natural Language 系统指令实际拼接后的两种 reference_now，以及完全相等的 human 内容。
- Tool Agent 格式化后的时间、两轮消息序列、工具调用/结果、默认绑定的三个只读 Tool。
- 合成输入、固定模型响应、实际 Graph 完整 outcome；其他 B0 行为矩阵仍独立运行。

Prompt 正文和 JSON 字符串**逐字比较**，不做空白、时间、UUID、角色或字段的模糊匹配。
仅对框架生成的 `BaseMessage.id` UUID 做字段级一致映射，保留其字段与引用关系；
不在系统指令、用户消息或 context JSON 内做 UUID 替换，也不改变原有 HTTP/任务快照的 UUID 映射。

`assert_contract_equal()` 是实际 Gate 的统一比较器，递归核对字段集合、列表顺序、值和 Python/JSON
值类型，避免 Python 的 `True == 1` 被误当作契约一致。类型变化、缺字段和额外字段均有负向测试。
采集器遇到未记录的对象类型会失败，不通过 `str()` 静默丢失对象结构。

Pydantic 响应记录类名和完整数据，现有 `llm_schemas` 分节仍精确核对完整 Schema；
不把项目模型的定义文件位置当作 Prompt 内容。没有删除 Graph 字段/类型检查，也没有全局去除模块名。

## 3. 固定来源与定义位置独立性

验收器继续用 `git archive 40d837c… src/productivity_agent` 生成旧源码。
producer 和 consumer 在不同进程、不同源码根执行；实际 import 根、版本和源码哈希有记录。
刷新快照时写入的 frozen 值只来自 producer，而且必须先精确比较候选契约。
没有用候选结果作为基线期望，后续任务不应再次刷新此已更正快照。

运行时采集不读取任何 Prompt 源文件，不假设 Prompt 的变量名、AST 形状或目录。
Graph 构造函数仍通过现有兼容入口导入；未来迁移 Graph 入口须按兼容计划保留或显式更新驱动，
不能把 ImportError 变成 skip。Prompt 定义位置的变化不需要修改采集器。
测试专用 `candidate_source` 参数只选择隔离候选源码；它不能更换固定 producer SHA。
正常 CLI 和原有恢复测试默认仍使用当前工作树的 `src/`。

纯搬家正向控制在缓存中的候选副本里：

1. 将 Assistant 系统文本移为函数，将 Natural Language 动态拼接移为接收 reference_now 的函数，
   将 Tool Agent SYSTEM_PROMPT 常量移入 `application/agent/llm/prompts.py`。
2. 原 Graph 只改为导入/调用这些定义，保留完整原文与动态参数。
3. 通过实际 `verify(..., checkpoints=False, candidate_source=...)` 运行固定旧来源 → 候选完整契约比较。

**实际结果：通过，源码 manifest 已改变，完整契约仍精确相等。**
AST 在这里仅用于构造隔离的搬家试验副本，不用于采集期望 Prompt。
正式工作树没有创建 `application/`，也没有实施 Application 代码迁移。

## 4. 负向控制与恢复证据

三种控制均在隔离副本中改变一条实际指令，运行同一个完整契约 Gate。
`pytest.raises` 必须捕获 `$.prompts` 下的值变化；其他原因的失败不能算通过。
finally 恢复候选原文，再核对其与固定旧源码相等。正式 `src/` 从未改动。

| 控制 | 预期/实际 |
|---|---|
| Assistant：“不执行写入”改为“可以执行写入” | Gate 拒绝；`$.prompts.assistant[0].calls[0].messages[0].items[1]` |
| Natural Language：“不执行任何操作”改为“可以执行操作” | Gate 拒绝；`$.prompts.natural_language[0].calls[0].messages[0].items[1]` |
| Tool Agent：“不能编造”改为“可以编造” | Gate 拒绝；`$.prompts.tool_agent[0].calls[0].messages[0].fields.content` |
| 将三个 Prompt 定义搬到新位置，原文不变 | Gate 通过，完整非 Prompt 契约也相等 |
| bool→int、缺字段、额外字段 | 三项均被严格比较器拒绝 |

`tests/fixtures/r2_b0/prompt-correction-summary.json` 保存实际 worker 产物派生的控制结果、失败路径、
候选原文恢复哈希和采集范围。它是观察摘要，不用来替代运行时生成的期望值。

## 5. 本轮验收

以下 python 指现有 `.venv-py312/Scripts/python.exe`（Python 3.12.8）；依赖版本未改。
模型、Key 和 tracing 均关闭，使用固定时间和隔离合成数据。

| 实际命令 | 结果 |
|---|---|
| `python -m pytest -q tests/test_r2_b0_prompt_contracts.py` | **8 passed**，45.71s；0 failed/errors/warnings |
| `python -m scripts.verify_r2_baseline --refresh-snapshot --contracts-only --out reports/r2-b0-1/contracts-final.json` | PASS，固定旧来源与候选逐字段/类型精确一致，仅修正 prompts 分节 |
| `python -m pytest -q` | **187 passed**，625.89s；0 failed / 0 errors / 0 warnings，原 179 项 + 新增 8 项全部通过 |
| 固定旧来源跨版本恢复矩阵 | PASS；原 `test_fixed_baseline_producer_candidate_consumer_and_restart` 在全量 pytest 中实际执行；17 个 worker、四种 Web 模式和 M5 Approval/Chat，op/Task ID/版本/写入记录核对通过 |
| `python -m productivity_agent.evaluation --out reports/r2-b0-1/offline-evaluation.json` | **10/10**，0 模型调用/费用 |
| `python -m scripts.verify_final_delivery --out reports/r2-b0-1/local-delivery.json` | PASS；真实认证 HTTP、三进程重启恢复 |
| `python -m scripts.verify_r1_compatibility --baseline 40d837c19f42ffd373686c30f4797df2e2598e23 --out reports/r2-b0-1/r1-compatibility.json` | PASS；两个 App 的完整 HTTP 契约和旧 Draft Checkpoint |
| `python -m pip check` | No broken requirements found |
| `python -m compileall -q src tests scripts` | 退出码 0 |
| `python -m ruff check scripts/r2_baseline_worker.py scripts/verify_r2_baseline.py tests/test_r2_b0_prompt_contracts.py` | All checks passed |
| `git diff --check`；`git diff -- src` | 无空白错误；业务源码差异为空 |

原 179 项测试文件和断言保持原样；新增 8 项，不删除/跳过测试。
已提交的 B0 历史摘要与旧快照 Git blob 保留。既有恢复测试固定写入
`reports/r2-b0/pytest-compatibility.json`；本轮新生成的矩阵另归档为 `reports/r2-b0-1/compatibility.json`。
其他本轮原始日志均在 `reports/r2-b0-1/`；数据库/临时副本在新的缓存目录。

## 6. 边界与交付

真实 Qwen/付费服务调用 **0 次**，模型费用预估/实际 **0 元**。
Scripted 模型仅用于验证输入/输出契约，不证明在线模型能力或任意输入的行为。
B0.1 修复 Prompt Gate，不改变 B0 已记录的 Adapter 差异、未知提交、认证、SSE 或子 Graph 恢复语义。
本轮候选正式业务实现仍与固定基线相同；未来真实迁移必须继续运行完整历史恢复矩阵。

不验证 Docker、OS 硬断电、其他依赖版本或任意用户私有数据库。
仅在现有 R2 分支提交、推送并更新 PR #13，等待最新 HEAD 的 CI。
不合并 main、不自动进入 B1；完成后等待架构审核。
