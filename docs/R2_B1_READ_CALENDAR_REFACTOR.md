# PPA R2-B1：Application 读取与日程能力重构

日期：2026-11-04，Asia/Shanghai。本阶段建立读取能力并迁移 M1/M2/M3，未实施 B2–B6。

## 1. 基线与中断核对

用户明确授权以 Merge Commit 合并 PR #13。执行前再次确认 HEAD 为
`c0ce413f96e5c02c5bb571f1361d7b793d974213`，Push/PR CI 均成功，MERGEABLE/CLEAN。
Merge API 使用 expected HEAD 防止误合并未经审核的变更，实际合并提交为
`da613cee972d0f083b9ba2df50d2a5b9d6cfd656`。fetch 后确认 origin/main 相同，
与审核 HEAD 代码树无差异；直接从它创建 `codex/r2-b1-read-calendar`。
没有改写历史、删分支或创建 Release。B1 PR 不自动合并。

未修改源码的完整测试基线：**187 passed，426.16s，0 failed/errors/warnings**。
用户中途要求继续后，重新核实工作树、远程 main、PR 合并状态和测试进程，没有残留运行任务；
已有 70 项相关回归和原始基线日志实际存在，未凭记忆将未完成验证计为通过。
原有 `RELEASE_NOTES.md`、`exercises/` 始终未跟踪、未改动、未清理。

## 2. 职责问题与具体设计

重构前，TaskStore 的读调用散在两个 HTTP App 和 Assistant 中；M3 模拟后端与 Tool 同文件；
普通日程提案也必须构建 Graph。Assistant 日程读取先调用 Tool，再进入 Calendar Graph。
CalendarState、ScheduleIntent 和模型意图归一化混在 Domain，模型指令留在工作流内部。

采用少量函数式能力模块和结构化 Protocol，不增加 Repository、UoW、Service/Factory 类。
每个 Port 都有实际调用方和既有实现，不要求 Adapter 继承基类。这个切片的主实现如下：

```text
application/
├── ports/
│   ├── tasks.py              # TaskReader：list/get/get_operation，同步、已绑定 owner
│   ├── calendar.py           # CalendarReader：单日展示与全量冲突区间
│   └── llm.py                # M2 的 StructuredExtractor，泛型返回契约
├── use_cases/
│   ├── tasks.py              # 两个 HTTP App、Assistant 共享读取入口
│   └── calendar.py           # 校验、检查、备选与提案；没有框架依赖
└── agent/
    ├── workflows/calendar.py, natural_language.py, tool_agent.py
    ├── tools/productivity.py # 模型 Tool 适配，保留名称/参数/描述/输出
    └── llm/contracts.py, normalization.py, prompts.py

infrastructure/integrations/mock_productivity.py
                              # 原 MockProductivityBackend，保留内存模拟写入行为
```

包标记文件仅用于 Python 包导入，没有初始化模型或存储的副作用。未创建 Memory/RAG、
TaskStore 写 Port、Session Service 或其他未来占位抽象。

### 实际迁移与调用方向

| 原位置/职责 | 当前归属及实际调用 |
|---|---|
| 两 App 的任务列表、详情、操作查询 | HTTP 参数/错误映射保留，改调 use_cases/tasks；继续 to_thread 或 FastAPI 同步线程池 |
| M1 Graph、CalendarState | agent/workflows/calendar；节点是 State patch/路由适配，校验和结果组装复用无框架日程步骤 |
| M2 Schema、归一化、Prompt、Graph | agent/llm + agent/workflows/natural_language；完整 Schema/消息/条件分支保持 |
| M3 Tool、Tool Agent | agent/tools/productivity + agent/workflows/tool_agent；预算、ToolNode、只读默认值保持 |
| MockProductivityBackend | Infrastructure；新增明确 busy_slots/list_mock_tasks 读取视角，原事件顺序/复制/模拟 ID 不变 |
| calendar_replanning | use_cases/calendar.propose_calendar_replan；直接业务调用不再创建 Graph |
| Assistant read_tools | 直接调用共享任务/日历读取；取消 LangChain Tool 中转，保留原位置 Calendar 子图驱动 |
| Bootstrap、CLI、M2/M3/M4 demo 装配 | 导入迁移后的主实现；demo 仅改导入，未实际调用在线模型 |

新 Application 不依赖 Infrastructure 具体类或旧 `services/providers/api/workflows/tools` facade；
Port/Use Case 不依赖 Agent、HTTP、LangGraph 或 LangChain。Infrastructure 通过结构满足 Port，
不反向导入 Agent。Bootstrap 选择并绑定实现。

旧 `workflows/calendar/natural_language/tool_agent/calendar_replanning`、`tools/productivity`、
`domain/state`、`domain/intent` 仅重导出同一份对象。新主实现不绕回这些路径。
Domain 两个 facade 是 D1 已批准例外；`domain/agent_intent.py` 留 B4，不扩展例外名单。
写入、审批、可靠执行、会话控制和 Assistant 的意图选择算法保留原实现；没有重写主 Graph。

## 3. 为什么保留小型 Graph 驱动

实际探针在改动前运行原 Assistant，并在 Calendar.check_conflict 内抛出测试专用 BaseException。
观察到父 thread_id/SqliteSaver 被继承，SQLite 存在 `read_tools:<task-id>` 子 namespace；
父 next 为 read_tools，子图停在已完成校验、待检查冲突的位置。恢复后仍能得到跨午夜冲突和备选时间。
因此“只读”并不表示它没有持久执行状态。

方案取舍：

- 没有把 Calendar Graph 换成单节点，否则会改变 SSE、节点契约及历史恢复。
- Assistant 读取移除 Tool 中转，但保持同一调用位置的 Calendar Graph，以消费历史子状态。
- M3 Tool 的 Calendar 驱动也保留，因为 Tool Agent 被父图调用时同样可以继承 Saver。
- 驱动负责执行与恢复，日程算法和决策步骤来自可独立调用的业务模块，不复制一套算法。

这不是根据源码猜测。新增 `scripts.verify_r2_b1_reads` 用固定旧源码生成中断，
候选恢复，再由第三进程重读终态；**四条路径、12 个 worker 均已通过**：

| 路径 | Saver/实际恢复 |
|---|---|
| Assistant legacy | 原 HTTP App + AsyncSqliteSaver，GET 显示 interrupted，候选 /recover 完成 |
| Assistant auth | 同上，另一 owner 404、未认证 401，原 owner 恢复 |
| M2 自然语言图嵌套调用 | SqliteSaver，保留外层/M2/Calendar 子 namespace 和结果 |
| M3 Tool Agent 嵌套调用 | SqliteSaver，保留 ToolNode、Calendar 子 namespace、模型消息和工具结果 |

断点处实际 namespace（含 task ID）在 producer/consumer 完全相等，所有旧子 namespace 仍存在，
第三进程不再进入检查节点。全程没有业务写入；恢复得到同一跨午夜冲突，展示事件为空，备选从 01:00 开始。
故障注入模拟节点执行中断，不声称验证断电、磁盘损坏或任意用户自建 Graph 的兼容性。

## 4. 保留的细节与数据源边界

1. CalendarReader 分开 events_on 和 busy_slots。前者按 start_at 日期展示；后者返回全量区间，
   包括前一日开始、当前日仍重叠的事件。不能用展示结果代替冲突输入。
2. TaskReader 只接收已绑定 owner 的真实 Store。M3 工具的模拟任务仍调用 list_mock_tasks，
   不把 Mock Backend 伪装成 TaskReader，也不把模型默认绑定到持久写入。
   Tool 局部的 MockToolBackend 只声明原工厂实际需要的模拟能力，不是新的真实写 Port。
3. 读取错误不统一、不吞掉：不可见任务仍抛 KeyError，成功查不到操作仍返回 None，HTTP 不可用仍抛
   BusinessUnavailable。UI 404 与 Business operation=null 的区别保留在 Interfaces。
4. 操作回执仍保留创建时查当前 Task、修改时返回历史 result_json 的差异；不在读取用例中伪造统一快照。
5. 原 Graph 对非字符串 title 的 AttributeError 文本与 domain.assess_calendar 的诊断不同。
   因此提取原 Graph 校验步骤及顺序，未直接用 Domain helper 替换，也未顺便统一原行为。
   日程重叠与备选搜索仍只使用原 Domain 算法；原 assess_calendar 独立 API 保留。
6. Assistant 读取结果仍保留原 JSON 数据边界、中文回复、history 和 status；Calendar Graph 节点名不变。
   StructuredExtractor 继续调用原 invoke/Schema 验证，Prompt 仅迁移定义位置，未改字句或变量值。

## 5. 验证方法与证据

Python 为现有 `.venv-py312/Scripts/python.exe`（3.12.8），依赖版本不变。
模型/Key/tracing 关闭，测试数据和临时源码均为新建隔离目录。没有刷新任何固定快照。

| 实际命令 | 结果 |
|---|---|
| 改动前 `python -m pytest -q` | 187 passed，426.16s；0 failed/errors/warnings |
| 既有 M1/M2/M3、Assistant、架构、Prompt 控制的相关 pytest | 70 passed，44.84s；0 failed/errors/warnings |
| `python -m pytest -q tests/test_r2_b1_reads.py` | 19 passed，58.47s；0 failed/errors/warnings |
| `python -m scripts.verify_r2_baseline --contracts-only --out reports/r2-b1/contracts.json` | PASS，完整 OpenAPI/路由/Graph/Prompt/Schema/Tool 精确一致 |
| `python -m scripts.verify_r2_b1_reads --out reports/r2-b1/nested-read-compatibility.json` | PASS，固定旧源码读取子图恢复，4 路径/12 进程 |
| `python -m pytest -q` | **206 passed，573.63s，0 failed/errors/warnings**；原 187 项 + 新增 19 项 |
| `python -m scripts.verify_r2_baseline --out reports/r2-b1/compatibility.json` | PASS；17 个独立 worker 的完整矩阵，实际 implementation_changed=true，固定基线仍为 40d837c |
| `python -m productivity_agent.evaluation --out reports/r2-b1/offline-evaluation.json` | 10/10，0 模型请求/费用 |
| `python -m scripts.verify_final_delivery --out reports/r2-b1/local-delivery.json` | PASS；真实认证 HTTP 和三进程重启恢复 |
| `python -m scripts.verify_r1_compatibility --baseline 40d837c19f42ffd373686c30f4797df2e2598e23 --out reports/r2-b1/r1-compatibility.json` | PASS；两个 App 的完整 OpenAPI/路由/静态页/SSE、历史 Draft 数据恢复 |
| `python -m productivity_agent --demo` | 退出码 0，真实 M1 Graph 输出 conflict 和备选时段 |
| `python -m pip check` | No broken requirements found |
| `python -m compileall -q src tests scripts` | 退出码 0 |
| 修改/新增 Python 文件的 `ruff check`、`git diff --check` | 通过；不格式化无关文件 |

新增测试不是把新 Graph 与自身比较：11 个日程/非法输入样本在独立进程导入固定旧源码求值，
再比较新业务用例、新 Graph 和旧提案入口，包含 cutoff、半开边界、跨午夜、类型/字段/时间错误。
另验证无框架 import 的真实 SQLite 调用、双 Adapter 可信 scope 隔离、失败读取不冒充 None、
mock/真实任务不混源、别名身份和新增主实现的依赖边界。

逐项源码审查还确认 Assistant understand/validate/execute/finish 的 AST 不变，
审批/可靠图、原可靠 Tool、业务存储/HTTP Adapter、统一会话 Router、AgentIntent 源码不变。
公开验收摘要见 [R2_B1_ACCEPTANCE.json](R2_B1_ACCEPTANCE.json)，由实际报告提取，移除宿主路径、
凭证和临时数据库内容；它是证据摘要，不是替代固定旧来源的测试期望。
CI 除保留原兼容 artifact，另上传 `r2-b1-read-recovery`，可核对本次读取子图的真实执行记录。

旧 187 项测试、B0/B0.1 工具和固定 `tests/fixtures/r2_b0/` 保持原样；新增测试不替代它们。
既有 pytest 会重写其固定输出 `reports/r2-b0/pytest-compatibility.json`，本阶段独立 CLI 的完整矩阵
另存 `reports/r2-b1/compatibility.json`。报告运行时 candidate_head 是当时基线，实际候选代码由源码哈希记录，
最终提交由 GitHub CI 再验证。没有将旧日志当作新版本的通过证据。

一次命令的自动权限审核等待超时，未执行且未计作产品失败；检查日志后重试的实际契约 Gate 通过。
中断前后原日志均保留在忽略目录，未以删除/跳过测试解决问题。

## 6. 未解决项与下一阶段边界

无写入/审批语义变更；M4/M5 和 Assistant 写入/定位仍在原路径，并可能依赖旧 services/Tool。
这些是 B2–B5 的明确工作，不是假称完整 Application 已完成。B1 的 facade 暂不删除，B6 再审议。
后续提取可靠执行器须保留 B0 已证实的 execute 子 namespace；读取改动也须继续跑新增读取恢复 Gate。
模型默认无真实持久写权限，原显式内存模拟写开关保持。

真实 Qwen/付费服务调用 **0 次**，预估/实际模型费用 **0 元**。
未执行 Docker、硬断电、线上模型能力、任意私人历史数据库恢复或生产多 Worker 验收。
源码迁移不是这些能力的证明；本轮只交付本地工程的兼容读取切片。
完成后停止并等待审核，不合并 B1 PR、不自动开始 B2。
