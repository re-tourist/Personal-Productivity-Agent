# PPA-R1.1 外围架构收尾

结论：R1.1 本地验收通过；全量 158 passed，0 failed/errors/warnings。
真实 Qwen 调用 0 次，预估/实际模型费用均为 0 元。GitHub 最新提交 CI 在推送后另行核实。

## 修改前核查与设计

2026-11-03。已 fetch 核对本地与远程分支、开放的 PR #12，基线均为
`a1b3d1513a212020f30e99671313279ac6ddf4dd`。原分支继续使用
`codex/r1-architecture-boundaries`，main 不修改。用户的 RELEASE_NOTES.md、exercises/ 保留。
修改前 Python 3.12.8 局部基线 32 passed（11.51s），未出现 failed/errors/warnings。
完整 R1 历史结果留在原报告，不能以本轮记录替换。

源码问题：routes/api.py 的 16 个 Endpoint 分属系统、任务读取、日程、草稿审批、Agent 问答；
它们共享协议，但查找目标和变化原因不同。security/identity.py 则同时处理凭证摘要和
thread_owners SQLite，导致只需账号验证的调用方也依赖归属存储实现。

本轮设计：

- 五个业务 Router 使用模块级 APIRouter，只注册接口，不持有 owner、bearer、Store 或 Graph。
  api_router() 按 System → Task Reads → Calendar → Draft Approval → Agent 组合，保留既有工厂入口。
  不为每组接口再创建 Service/Controller/Factory，避免无实际用途的包装。
- 两个草稿辅助函数归 drafts.py；routes/api.py 和旧 api/app.py 仍提供相同函数对象的别名。
  避免增加只有两个私有函数的 shared/utils 模块，也不让新草稿实现反向依赖聚合入口。
- Accounts、Identity、LEGACY_OWNER 归 security/accounts.py；ThreadOwnership 归
  persistence/thread_ownership.py；旧 security/identity.py 和 services/identity.py 仅兼容重导出。
  Bootstrap、业务存储、账号设置脚本及新增测试使用最终归属路径。
- Schema 文件仍是 HTTP 契约集合；本轮不增加对应的多组 Schema 文件。统一 Assistant Router、
  Business App、所有 Application/Domain 规则和模型实现保持原样。

验证计划：先保留原调用方与路由清单；比较两个完整 OpenAPI 和有序路由清单（含隐藏页面）；
检查迁移 Endpoint/身份类 AST 等价；新增独立导入、组合职责、无 SQLite 账号模块、无兼容反向
依赖和实现身份检查；执行局部/全量测试、离线评测、真实 HTTP/跨进程恢复、旧基线与 R1.0 数据兼容脚本。
所有输出在 reports/r1-1/，真实 Qwen 调用 0 次。实际结果见下文。

## 最终职责与目录

```text
interfaces/http/routes/
├── __init__.py
├── api.py          # 组合与草稿辅助函数兼容导出
├── assistant.py    # 统一会话接口，保持原样
├── system.py       # /、/app、health、system、me
├── tasks.py        # 任务列表/详情和操作查询
├── calendar.py     # 日程 JSON、自然语言日程与 SSE
├── drafts.py       # 草稿、状态、审批及对应辅助函数
└── agent.py        # 独立问答与 SSE
infrastructure/
├── security/
│   ├── __init__.py
│   ├── accounts.py
│   └── identity.py  # 兼容重导出
└── persistence/
    ├── __init__.py
    ├── task_store.py
    └── thread_ownership.py
```

新主实现直接导入 Accounts/Identity/LEGACY_OWNER 的 accounts 模块，以及 ThreadOwnership
持久化模块；两个模块互不依赖。Bootstrap 只改导入路径，middleware/dependencies 不直接
导入旧 identity 实现，原请求身份验证和资源绑定逻辑未改。旧 services/identity.py 与
security/identity.py 导出的类型和新主实现为同一对象，无复制实现或第二份状态。

每个 Router 只声明静态接口，执行时使用 Request 的资源；不在模块级缓存用户身份或 Graph。
api.py 从 250 行职责混合实现变为约 30 行组合入口（含注释与兼容导出）。
保持逐 Endpoint 的认证依赖，而不提升为整组依赖，避免改变公开页面/健康检查或依赖执行时机。
没有新增业务 Service、Controller、Port 或框架依赖。

## 兼容性与验证结果

R1.0 HEAD 和原始 main 两套兼容验证均通过，完整 OpenAPI 摘要仍为：

- Assistant：`0e24413ec9cf4055b2831df2c34c6d5f85d0d5eed49f947fceefe1601722d219`
- Business：`db25d3b15e9e0d2a95dc3871c82616fa3874c74db9499061ddead9fcbc1c606d`

有序路由清单分别为 26 和 11 条（含自动文档路由和隐藏页面；OpenAPI 路径数仍为 20 和 5）。
对比包括名称、路径、方法和 operationId，原注册顺序未变。真实 Calendar Graph 的 JSON、
SSE 文本、Content-Type/Cache-Control/X-Accel-Buffering 精确一致。基线任务可以读取，
待审批 Checkpoint 恢复后可批准，重复批准仍为 409。
原有真实 HTTP/SSE 错误与断流、认证、跨用户隔离、幂等、版本冲突、超时对账、进程恢复
测试继续保留，不以独立导入检查代替业务集成验收。

| 实际执行 | 结果 |
|---|---|
| 修改前局部测试 | 32 passed，0 failed/errors/warnings，11.51s |
| 修改后局部（含真实 SSE/断流） | 48 passed，0 failed/errors/warnings，19.78s |
| 全量 pytest | 158 passed，0 failed/errors/warnings，247.06s |
| pip check | No broken requirements found |
| compileall -q src tests | 通过 |
| 修改文件 Ruff、git diff --check | 通过 |
| M7 离线评测 | 10/10 |
| verify_final_delivery | PASS，真实认证 HTTP 三进程均退出，待审批/终态恢复通过 |
| verify_r1_compatibility 默认原始 main | PASS，原始数据/Checkpoint、OpenAPI、路由、JSON/SSE 与页面比较通过 |
| verify_r1_compatibility 指定 R1.0 HEAD | PASS，精确比较和数据恢复通过 |
| 迁移源码等价检查 | 21 个定义 AST 等价；所有冻结目录/模块无改动 |

同一 Python 3.12.8 环境执行下列命令，所有输出使用本轮隔离目录：

```powershell
$env:PPA_ENABLE_LIVE_QWEN='0'
$env:DASHSCOPE_API_KEY=''
$env:PPA_AUTH_CONFIG=''
$env:PPA_TASK_SERVICE_URL=''
$env:PPA_API_TOKEN=''
$env:LANGSMITH_TRACING='false'
$env:LANGCHAIN_TRACING_V2='false'
python -m pip check
python -m compileall -q src tests
python -m pytest -q
python -m productivity_agent.evaluation --out reports/r1-1/offline-evaluation.json
python -m scripts.verify_final_delivery --out reports/r1-1/local-delivery.json
python -m scripts.verify_r1_compatibility --out reports/r1-1/compatibility.json
python -m scripts.verify_r1_compatibility --baseline a1b3d1513a212020f30e99671313279ac6ddf4dd --out reports/r1-1/r1-head-compatibility.json
```

Ruff 覆盖五个新增 Router、聚合 api.py、accounts.py/identity.py/thread_ownership.py、
改动的 task_store.py、bootstrap.py、services/identity.py、api/app.py、账号设置脚本、
兼容验证脚本和 test_r1_architecture.py。迁移只重命名装饰器引用的局部 Router 变量，
21 个迁移定义的参数、装饰器元数据、函数体、类及 SQL 的 AST 保持等价。
正式 HTTP/子进程测试按已验证环境在批准的沙箱外执行，合成数据和日志不提交。

未执行：真实 Qwen、Docker、人工浏览器点击、生产多 Worker。本轮不新增上述验收范围；
模型请求 0 次，预估/实际模型费用均 0 元。没有修改依赖、凭证、原始历史报告内容或用户数据。

## 设计权衡与 R2 交接

- 按业务分组相较继续使用单一 api.py，直接降低定位成本；相较一 Endpoint 一文件，避免过度拆分。
- 模块级 Router 不持运行资源；api_router 保留原公开构建契约，不增加每组 Factory。
- HTTP schemas.py 仍集中定义约百行契约，本轮没有证据支持继续拆碎；若 R2 用例需要稳定输入/
  输出契约，应区分 Application 契约与 HTTP 模型，而不是机械搬动相同数据结构。
- Accounts 与 ThreadOwnership 按技术职责分离，而不是为了多一个目录；保留原算法和 SQL，
  不引入认证框架、Repository 或 Unit of Work。
- routes/api.py 的草稿辅助别名、旧 security/identity.py 及 services/identity.py 属兼容边界；
  新实现不依赖它们。内部调用迁移后再清理，公开启动入口继续支持。
- R2 仍需处理 workflows/tools、Graph API/Command/snapshot 审批用例、CalendarState 与 LLM
  输出契约、Store/失败分类/观测耦合及实际能力 Ports。本轮不创建 application/、memory/、rag/。
- 同一分支、同一 PR #12 交付 R1.1 独立提交；不合并 main，完成后等待架构审核。
