# 架构设计与边界

本项目从 M1 到 M7 逐步演进为：`HTTP 入口 → LangGraph → 业务工具 → 本地数据库`。解析与执行都受确定性业务校验约束。

## 组件层次

- `domain/`：独立于框架的日程区间运算、时间转换、状态数据契约、Pydantic 意图规则。
- `workflows/calendar.py`：有状态 M1 图，使用 `domain/calendar_rules.py` 实现确定性冲突与候选区间搜索。
- `workflows/natural_language.py`：M2 图，使用结构化 LLM 输出后归一化，再复用 M1；输入不完整返回澄清请求。
- `workflows/tool_agent.py`：M3 图，模型动态选择只读模拟工具，工具结果返回模型，限制单次模型调用次数与单轮工具数量。
- `services/task_store.py` + `workflows/reliable_task.py`：M4 将同一业务 `operation_id` 与请求摘要绑定，任务写入和幂等索引共享 SQLite 事务，超时之后先查询操作记录。
- `workflows/approval_session.py`：M5 使用 Checkpointer 保存待确认状态，`interrupt()` 让审批节点暂停，`Command(resume=...)` 恢复。审批通过后调用 M4 逻辑；中断前没有写入操作。
- `api/app.py`：M6 HTTP + SSE + 请求校验和资源管理。`Thread ID` 用于执行恢复，**不是**身份凭证。SQLite 只建议在单机演示使用。
- `static/index.html`：M7 无构建依赖的浏览器面板。
- `evaluation.py`：M7 可重复运行的确定性场景集合。

## 重要的工程选择

### 1. 执行状态和业务事实分离

Checkpointer 用于恢复节点状态，业务 SQLite 用于存储真实创建的本地任务。即使 Graph 从检查点恢复重放 `execute` 节点，仍应依靠业务写入幂等索引保护副作用。

### 2. 模型只负责模糊的语义和工具选择

时间区间重叠判断、开始结束时间先后、幂等键冲突都由 Python 和数据库约束处理，避免增加 LLM 的成本与不确定性。

### 3. 单用户本地演示与生产系统之间存在明确边界

当前通过 Loopback 绑定、可选 Demo Token 和默认禁用在线模型降低风险，但**没有真实用户身份认证**；不建议部署公网。

### 4. 测试可不调用任何模型

M2 使用 Fake Extractor；M3 使用 Fake Chat Model；M4 使用可注入的写入故障；M5 使用 SQLite Saver；M6 有 HTTP Fake Graph 与真实 Graph 测试。M7 默认评测完全离线。

## 已知技术限制

- 日程采用带 UTC 偏移的 ISO-8601，不负责 IANA 时区和 DST 规则变更；候选时间限定在请求当日的 18:00 前。
- M3 模拟任务与 M4 SQLite 业务表是不同的演示数据源，尚未合并为真实外部业务集成。
- Agent 的工具预算是本地调用层的限制；缺少生产环境限流、审计和租户级 Token 预算。
- Stream 使用节点更新事件，不等同于逐 Token 生成；没有真实客户端断线续传。
- PostgreSQL/gRPC 只列出升级方向，当前没有实现。
