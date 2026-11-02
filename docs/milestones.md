# M0～M7：项目交付与状态

所有 M 均属于同一 `personal-productivity-agent` 仓库，不再创建相互独立的教学项目。

| Milestone | 对应组件 | 实现情况 | 本次可验证边界 |
|---|---|---|---|
| M0 Foundation | Python package、CI、CLI | 已提供源码 | 基础 Python 测试 |
| M1 Calendar Graph | 状态路由、时间搜索 | 已提供源码 | 真实 LangGraph 集成需在依赖安装后执行 |
| M2 Structured Intent | Pydantic、结构化意图、澄清 | 已提供源码 | 离线 Fake LLM；在线 Qwen 需 Key |
| M3 Tool Agent | Qwen Tool Calling、只读工具 | 已提供源码 | Fake Model 通过后可显式尝试线上 |
| M4 Failure Recovery | 幂等 SQLite、超时对账、重试、冲突重规划 | 已提供源码 | 数据库直接验收 + Graph 测试 |
| M5 Session and Memory | Checkpointer、Interrupt、Command | 已提供源码 | 跨进程/跨 Thread 集成需 LangGraph SQLite Saver |
| M6 Backend | FastAPI、SSE、Async、端点 | 已提供源码 | HTTP mock/真实图集成分别验收 |
| M7 Evaluation & Release | UI、测试、报告、CI、Dockerfile、文档 | 已提供源码 | 报告区分离线/真实模型与生产范围 |

## 验收方式

1. 本地 Conda Python 3.12：`python -m pip install -e ".[dev]"`。
2. `python -m pytest -q` 全量回归。
3. `python -m productivity_agent.evaluation --out reports/m7-offline-evaluation.json`。
4. `python -m uvicorn productivity_agent.api.app:create_app --factory --host 127.0.0.1 --port 8000`，访问 `/app` 实测任务审批。
5. 如有百炼 Key，在 `.env` 中显式开启千问，然后做小额联通与工具调度验证。

## 明确未实现（不能用于标称完成）

- 真实第三方日历、任务平台集成与生产用户身份授权。
- 多租户资源隔离和多个 Worker 共同安全审批同一 Thread。
- PostgreSQL 持久化及 gRPC Server（提供 `.proto` 设计草案）。
- 公开数据集上的 Qwen Agent 成功率基准、压力测试或线上 SLA。
