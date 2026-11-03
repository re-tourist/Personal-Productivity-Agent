# PPA-R1 工程审查与 R2 交接

日期：2026-11-03（Asia/Shanghai）。结论：R1 外围重构及本地离线验收通过；
不表示真实 Qwen、生产多租户、Docker 或 R2 已验收。模型调用 0 次，预估/实际费用均 0 元。

## 范围与基线

- 执行前实际 fetch 的 origin/main、本地 main/HEAD：`0ea0a340de5f43d0f234905930ba40c1d88cc62c`。
- 独立分支：`codex/r1-architecture-boundaries`；不更新或合并 main。
- 初始未跟踪 `RELEASE_NOTES.md`、`exercises/` 保留，未覆盖、未加入 R1 提交。
- 修改前计划：[R1_IMPLEMENTATION_PLAN.md](R1_IMPLEMENTATION_PLAN.md)。
- `workflows/`、`tools/`、静态页面、数据库 SQL/事务/迁移、Prompt、模型配置、依赖声明、Docker 和 CI 启动命令未修改。
- 历史审计与验收报告未改写；本轮只更新当前架构导航和协作约定。

## 模块迁移与依赖

| 旧主实现 | R1 新主实现/职责 |
|---|---|
| api/app.py | interfaces/http/assistant_app.py 工厂；routes/api.py 原 HTTP 路由；schemas.py 请求模型；bootstrap.py 装配 |
| api/assistant.py | interfaces/http/routes/assistant.py、schemas.py |
| api/task_service.py | interfaces/http/business_app.py、schemas.py、errors.py、middleware.py |
| api/resources.py | interfaces/http/dependencies.py 请求绑定与缓存；bootstrap.bind_user_resources 构建资源 |
| services/identity.py | infrastructure/security/identity.py 账号/归属存储；HTTP 部分进 dependencies.py / middleware.py |
| services/task_store.py | infrastructure/persistence/task_store.py；纯校验和业务冲突进 domain/tasks.py |
| services/http_task_store.py | infrastructure/integrations/http_task_store.py |
| services/operation_trace.py | infrastructure/observability/operation_trace.py |
| providers/qwen.py、offline_intent.py | infrastructure/models/ 同名实现 |
| providers/qwen_meter.py | infrastructure/observability/qwen_meter.py |
| cli.py | interfaces/cli.py |
| domain/state.py 中纯业务 TypedDict | domain/contracts.py；原路径重导出，CalendarState 暂留 |

旧模块显式重导出单一实现，无转发类、无复制业务算法。主实现不导入旧兼容层。
Domain 不依赖 Interfaces/Infrastructure/Graph；Infrastructure 不依赖 FastAPI 或旧兼容模块；
Interfaces 不含 SQLite SQL/事务。直接与函数内延迟导入均检查，无源码导入环。
请求绑定缓存只写 request.state；不会将当前 owner/bearer 写入共享 Store/Graph。
三个数据库的职责、路径和稳定幂等键保持不变；生产能力边界见[当前架构](architecture.md)。

## 兼容性证据

- Assistant 与 Business 完整 OpenAPI JSON 精确一致（包含路径、方法、Schema、operationId、响应定义）。
  Assistant 20 个路径，Business 5 个路径；隐藏的根重定向和静态页面另外实测。
- 原有 `api.app:create_app`、`api.task_service:create_task_service`、`cli:main`、`ppa`、
  `python -m productivity_agent` 保留；CLI 默认输出和 `ppa --demo` 实际执行成功。
- 两个 App 的旧入口用于既有真实 HTTP/子进程验收；新入口用于独立基线数据恢复验证。
- 新脚本[verify_r1_compatibility.py](../scripts/verify_r1_compatibility.py)从 Git 基线恢复独立源码，
  使用基线代码生成合成业务 SQLite 和待审批 Checkpoint，再启动 R1 新入口：读取原任务不变、
  恢复待审批、批准生成第二条任务、重复批准返回原有 409。
- 基线和 R1 静态页面响应字节 SHA-256 均为
  `add98fbfec4de7951a34b9f6b19ec4ee3cb056159a4a524223c118860201e188`。
- OpenAPI SHA-256（UTF-8、sort_keys、ensure_ascii=False）：
  Assistant `0e24413ec9cf4055b2831df2c34c6d5f85d0d5eed49f947fceefe1601722d219`；
  Business `db25d3b15e9e0d2a95dc3871c82616fa3874c74db9499061ddead9fcbc1c606d`。
- 24 个迁移定义（含 Store、身份、HTTP 客户端、模型/解析器、CLI）与基线 AST 精确等价；
  workflows/、tools/ 文件内容逐一保持不变。SSE 两类接口各自保留原 JSON 转义/序列化行为。

## 实际验证

使用已有 `.venv-py312/Scripts/python.exe`，Python 3.12.8。
依赖版本：LangGraph 1.2.19、checkpoint-sqlite 3.1.3、FastAPI 0.162.0、Pydantic 2.14.2、
HTTPX 0.28.1、pytest 9.2.0、Ruff 0.17.3；未升级主要依赖。
所有业务/账号/Checkpoint 数据均为隔离合成数据，历史 reports 未覆盖。

| 验证 | 结果 |
|---|---|
| 修改前全量（verbose + 30 秒诊断堆栈） | 130 passed，0 failed/errors/warnings，265.50s |
| 修改后局部 HTTP/架构验收 | 32 passed，0 failed/errors/warnings，10.38s |
| 修改后标准全量 pytest -q | 145 passed，0 failed/errors/warnings，292.26s |
| pip install -e ".[dev]" | 成功，无运行依赖升级 |
| pip check | No broken requirements found |
| compileall -q src tests | 通过 |
| 定向 Ruff（新/迁移文件及已有约定范围） | All checks passed |
| M7 离线评测 | 10/10 |
| verify_final_delivery | PASS，三个独立真实 HTTP 进程均退出；待审批与终态恢复成功 |
| verify_r1_compatibility | PASS，精确 OpenAPI/页面比较及基线数据恢复成功 |
| wheel 构建及包数据探针 | PASS，从构建 wheel 的隔离解包目录导入两个新 App，/app、/docs、Business /health 通过，页面字节摘要一致 |
| 原有身份/幂等/超时/对账/版本/SSE | 全量测试覆盖并通过，含独立 Business HTTP、跨用户隔离、并发、断流和去敏错误 |

可复现命令（项目根目录，同一已安装 dev 依赖的 Python；不读取/打印真实凭证）：

```powershell
$env:PPA_ENABLE_LIVE_QWEN='0'
$env:DASHSCOPE_API_KEY=''
$env:PPA_AUTH_CONFIG=''
$env:PPA_TASK_SERVICE_URL=''
$env:PPA_API_TOKEN=''
$env:LANGSMITH_TRACING='false'
$env:LANGCHAIN_TRACING_V2='false'
python -m pip install -e ".[dev]"
python -m pip check
python -m compileall -q src tests
python -m pytest -q
python -m productivity_agent.evaluation --out reports/r1/offline-evaluation.json
python -m scripts.verify_final_delivery --out reports/r1/local-delivery.json
python -m scripts.verify_r1_compatibility --out reports/r1/baseline-compatibility.json
python -m pip wheel . --no-deps --wheel-dir .pytest_cache/r1-wheel
```

完整机器日志和快照在本地被忽略的 `reports/r1-*`、`reports/r1/`；不提交令牌、
数据库、私密日志和临时数据。Ruff 只覆盖 R1 新/改 Python 文件，加既有
tests/conftest.py、test_task02_integration.py、test_task02_sse.py、test_task02_temp.py 和 tests/helpers。
扩展检查曾发现未改动 time_utils.py 的既有 UP035，不借机整理该文件，定向范围最终通过。

环境/验证过程中的非通过项均保留原日志：PATH Python 缺 pytest；沙箱内 pytest 停滞后终止，
正式 HTTP/子进程验收在批准的沙箱外执行。安装首次受系统临时目录 ACL 阻断，工作区临时目录
重试又受网络限制，批准后安装成功。诊断基线中超过 30 秒的测试产生堆栈，随后通过。
迁移首次装配发现缺少 FastAPI 注解符号，已移除 Bootstrap 的协议类型耦合；
可选 QwenMeter 延迟导入路径已修正并补检查，没有调用模型。
基线数据脚本首次精确页面比较因 Git LF 与工作树 CRLF 不同而失败，修正为按 checkout
过滤规则还原基线后精确比较通过，未放宽断言，生产页面未修改。

未执行：真实 Qwen、Docker 构建/运行、人工浏览器点击验收、生产多 Worker。
模型装配测试仅使用不可调用的 AssemblyOnlyModel，不能作为在线模型证据。

## R2 交接清单

| 待处理位置 | 保留原因与下一步 |
|---|---|
| workflows/、tools/ | 本轮冻结；R2 迁到 Application 的 Workflows/Agent/Tools，保持审批与对账控制 |
| domain/state.py:CalendarState | Graph 运行状态而非实体，迁入 Application；保留业务 contracts 的独立性 |
| domain/intent.py、agent_intent.py | ScheduleIntent/AgentIntent 属 LLM 输出契约；前者还混合归一化，R2 审核拆分位置 |
| infrastructure/models/offline_intent.py | 实现仍消费历史 AgentIntent；随 Agent 契约迁移修正依赖，不改变解析策略 |
| HTTP 路由中的 Graph API / Command、snapshot/审批流程 | 用例与执行控制暂留现有 HTTP 适配；R2 用业务用例接口承接，不复制状态机 |
| HTTPTaskStore 对持久化异常/指纹的复用 | R2 定义操作结果、未知提交、版本冲突、任务查询/写入/操作查询能力接口 |
| workflows/reliable_task.py 的 SQLite/Store 耦合 | R2 分离持久化能力和失败分类，保留 timeout 先对账、稳定 operation_id 语义 |
| workflows/assistant.py 的追踪 decorator/Store 耦合 | R2 评估能力接口和观测边界，不能让日志侵入业务规则 |
| api/assistant.py、api/resources.py、services/、providers/ | 内部调用迁移后清理兼容重导出，并迁移相关测试导入 |
| api/app.py、api/task_service.py、cli.py、__main__.py | 对外启动兼容入口继续支持，内部调用不应依赖它们 |
| Bootstrap 的 Graph 具体构建与原有测试注入参数 | R2 有实际用例/能力接口后再调整，不先创建空 Port/Repository/UoW |

R2 不能借迁移改变 Prompt、时间验证、状态转换、事务/迁移/owner/幂等算法或审批前副作用边界。
Memory/RAG 仅属于后续规划，本轮没有目录占位或实现。

## 风险与 Git 交付

没有发现阻断 R1 的回归；系统仍是本地单 Worker 演示，静态测试令牌、进程锁与 SQLite
不等于生产多租户能力。在线 Qwen 的行为只有历史证据，本轮验证的是迁移兼容性和装配。
PR 不自动合并；分支提交与推送结果在最终交付及 PR 中记录，不将提交 SHA 自引用写入本文。

## 附录：修改前后源码目录

以下只列可分发源码和包数据，排除缓存、egg-info 与运行数据。

### 修改前

```text
└── src
    └── productivity_agent
        ├── __init__.py
        ├── __main__.py
        ├── api
        │   ├── __init__.py
        │   ├── app.py
        │   ├── assistant.py
        │   ├── resources.py
        │   └── task_service.py
        ├── cli.py
        ├── demo_data.py
        ├── demo_m2.py
        ├── demo_m3.py
        ├── demo_m4.py
        ├── demo_m5.py
        ├── demo_m5_chat.py
        ├── domain
        │   ├── __init__.py
        │   ├── agent_intent.py
        │   ├── calendar_rules.py
        │   ├── intent.py
        │   ├── policy.py
        │   ├── state.py
        │   └── time_utils.py
        ├── evaluation.py
        ├── providers
        │   ├── __init__.py
        │   ├── offline_intent.py
        │   ├── qwen.py
        │   └── qwen_meter.py
        ├── services
        │   ├── __init__.py
        │   ├── http_task_store.py
        │   ├── identity.py
        │   ├── operation_trace.py
        │   └── task_store.py
        ├── static
        │   └── index.html
        ├── tools
        │   ├── __init__.py
        │   ├── productivity.py
        │   └── reliable_task.py
        └── workflows
            ├── __init__.py
            ├── approval_session.py
            ├── assistant.py
            ├── calendar.py
            ├── calendar_replanning.py
            ├── chat_memory.py
            ├── natural_language.py
            ├── reliable_task.py
            └── tool_agent.py
```

### 修改后

```text
└── src
    └── productivity_agent
        ├── __init__.py
        ├── __main__.py
        ├── api
        │   ├── __init__.py
        │   ├── app.py
        │   ├── assistant.py
        │   ├── resources.py
        │   └── task_service.py
        ├── bootstrap.py
        ├── cli.py
        ├── demo_data.py
        ├── demo_m2.py
        ├── demo_m3.py
        ├── demo_m4.py
        ├── demo_m5.py
        ├── demo_m5_chat.py
        ├── domain
        │   ├── __init__.py
        │   ├── agent_intent.py
        │   ├── calendar_rules.py
        │   ├── contracts.py
        │   ├── intent.py
        │   ├── policy.py
        │   ├── state.py
        │   ├── tasks.py
        │   └── time_utils.py
        ├── evaluation.py
        ├── infrastructure
        │   ├── __init__.py
        │   ├── integrations
        │   │   ├── __init__.py
        │   │   └── http_task_store.py
        │   ├── models
        │   │   ├── __init__.py
        │   │   ├── offline_intent.py
        │   │   └── qwen.py
        │   ├── observability
        │   │   ├── __init__.py
        │   │   ├── operation_trace.py
        │   │   └── qwen_meter.py
        │   ├── persistence
        │   │   ├── __init__.py
        │   │   └── task_store.py
        │   └── security
        │       ├── __init__.py
        │       └── identity.py
        ├── interfaces
        │   ├── __init__.py
        │   ├── cli.py
        │   └── http
        │       ├── __init__.py
        │       ├── assistant_app.py
        │       ├── business_app.py
        │       ├── dependencies.py
        │       ├── errors.py
        │       ├── middleware.py
        │       ├── routes
        │       │   ├── __init__.py
        │       │   ├── api.py
        │       │   └── assistant.py
        │       ├── schemas.py
        │       └── streaming.py
        ├── providers
        │   ├── __init__.py
        │   ├── offline_intent.py
        │   ├── qwen.py
        │   └── qwen_meter.py
        ├── services
        │   ├── __init__.py
        │   ├── http_task_store.py
        │   ├── identity.py
        │   ├── operation_trace.py
        │   └── task_store.py
        ├── static
        │   └── index.html
        ├── tools
        │   ├── __init__.py
        │   ├── productivity.py
        │   └── reliable_task.py
        └── workflows
            ├── __init__.py
            ├── approval_session.py
            ├── assistant.py
            ├── calendar.py
            ├── calendar_replanning.py
            ├── chat_memory.py
            ├── natural_language.py
            ├── reliable_task.py
            └── tool_agent.py
```

## R1.1 外围架构收尾补充

上文保留 R1.0 的原始目录、测试次数与验证过程。后续 R1.1 在同一分支、同一 PR #12 中，
将 routes/api.py 拆为业务 Router，并分离 Accounts 与 ThreadOwnership；独立补充记录见
[R1.1 设计、验收和 R2 交接](R1_1_ARCHITECTURE_CLOSEOUT.md)。当前目录以 architecture.md 为准。
