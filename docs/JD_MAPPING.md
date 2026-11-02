# 实习 JD 对应能力

| 目标能力 | 代码位置 | 可以演示的证据 | 现有限制 |
|---|---|---|---|
| LangGraph 工作流与条件路由 | `workflows/calendar.py` | `test_m1_calendar.py` | 业务为本地模拟 |
| LLM 结构化提取与 Pydantic 校验 | `domain/intent.py`, `workflows/natural_language.py` | `test_m2_*` | 千问真实准确率未测 |
| Tool Calling 与循环决策 | `workflows/tool_agent.py`, `tools/productivity.py` | `test_m3_tools.py` | 只读模拟数据 |
| 失败恢复与规划调整 | `workflows/reliable_task.py`, `calendar_replanning.py` | `test_m4_*`, `evaluation.py` | 不是开放环境的通用规划器 |
| 幂等、数据一致性 | `services/task_store.py` | 同一 ID 重放、并发重复请求 | 本地 SQLite 事务 |
| 多轮上下文与人工确认 | `workflows/chat_memory.py`, `approval_session.py` | `test_m5_*` | 未做跨会话用户画像持久化 |
| Python Async 与流式 API | `api/app.py` | `test_m6_*`, `test_m7_http.py` | 本地单进程 |
| 自动化评测 | `evaluation.py`, `tests/`, GitHub Actions | 结构化 JSON、测试记录 | 非模型成功率基准 |
| PostgreSQL 与 gRPC | `docs/grpc-interface.proto` | 接口草案与扩展方向 | **尚未实现** |

遇到面试官追问，应分别解释“完成了什么”和“尚未完成什么”。特别不要用 HTTP 200 代替业务任务成功，也不能用确定性测试 100% 代替真实 LLM 成功率。
