# PPA-R1 实施计划（修改源码前）

日期：2026-11-03。已 fetch 并确认 origin/main 与本地 HEAD 均为
`0ea0a340de5f43d0f234905930ba40c1d88cc62c`。用户的未跟踪
`RELEASE_NOTES.md`、`exercises/` 保留，不纳入 R1。

## 迁移与边界

| 原路径/职责 | 新主实现 |
|---|---|
| api/app.py 工厂与装配 | interfaces/http/assistant_app.py + bootstrap.py |
| api/app.py 路由 | interfaces/http/routes/api.py（保留既有路径） |
| api/assistant.py 会话 HTTP | interfaces/http/routes/assistant.py |
| 三组 HTTP 请求模型 | interfaces/http/schemas.py |
| api/resources.py、身份请求访问 | interfaces/http/dependencies.py |
| services/identity.py HTTP 认证 | interfaces/http/middleware.py |
| services/identity.py 账号/归属持久化 | infrastructure/security/identity.py |
| api/task_service.py | interfaces/http/business_app.py + bootstrap.py |
| SSE 编码、Business 错误映射 | interfaces/http/streaming.py、errors.py |
| cli.py | interfaces/cli.py |
| services/task_store.py | infrastructure/persistence/task_store.py |
| services/http_task_store.py | infrastructure/integrations/http_task_store.py |
| services/operation_trace.py | infrastructure/observability/operation_trace.py |
| providers/qwen.py、offline_intent.py | infrastructure/models/ 同名模块 |
| providers/qwen_meter.py | infrastructure/observability/qwen_meter.py |
| domain/state.py 的纯业务 TypedDict | domain/contracts.py；CalendarState 留旧路径 |
| task_store.py 的纯业务校验/冲突错误 | domain/tasks.py；存储异常仍归持久化 |

不创建空 Application 抽象；workflows/、tools/ 的内部逻辑与源码保持不变。
domain/agent_intent.py、domain/intent.py 的模型输出契约和 CalendarState 暂留，R2 处理。
旧 api/、services/、providers/、cli.py 保留显式重导出，指向唯一主实现。
新主实现只导入新路径，禁止反向依赖这些兼容模块。

## 风险与控制

- 路由拆分可能改变顺序、operationId 和 Schema：修改前已保存两 App 完整
  路由/OpenAPI 快照到隔离 reports/r1-before.json，修改后做精确比较。
- 保留校验、SQL、事务、指纹/归属算法及错误映射；以 AST 等价检查和现有集成验收核实。
- 认证 Middleware 只负责 HTTP，账号摘要和 thread ownership SQL 留基础设施；
  每请求资源独立绑定，不将 bearer/owner 写到共享 store/graph。
- Bootstrap 负责环境读取、Store/Graph/Saver 生命周期，依赖模块只做请求绑定；
  保留延迟导入、测试注入、现有数据库文件名、进程内锁和单 Worker 约束。
- 静态页面保持原包数据位置，迁移后的定位改为包根资源；检查安装后页面可达。

## 验证

先记录原始 pytest；PATH Python 缺 pytest，使用已存在的 .venv-py312（3.12.8）。
原始运行与环境异常完整日志保存在被忽略的 reports/r1-*。
执行 editable 安装、pip check、compileall、相关集成测试、全量 pytest、10 场景离线评测、
verify_final_delivery 的真实认证 HTTP 三进程恢复。现有测试覆盖独立 Business HTTP、
跨用户隔离、超时对账、版本冲突、SSE 错误/断流；新增边界和兼容导入检查。
定向 Ruff 沿用仓库规则（不大面积格式化）。Docker/人工浏览器若未运行须单独标明。
真实 Qwen 调用严格 0 次。重要验证通过后分批 commit、push 独立分支并创建 PR；不合并。
