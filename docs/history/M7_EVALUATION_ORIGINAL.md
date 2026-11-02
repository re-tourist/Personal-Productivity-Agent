# M7 验收报告（当前运行环境的实际记录）

## 结论

这是**离线代码层与 HTTP 传输层的局部验收**，不是“LangGraph 全量测试已通过”。最终需要在正确安装依赖的 Python 3.12 Conda 环境或 GitHub Actions 中完成全量框架测试。

| 项目 | 实际结果 | 解释 |
|---|---|---|
| Python 源码/测试字节码编译 | **通过** | `python -m compileall -q src tests` |
| Python 包安装（不安装依赖） | **通过** | `pip install --no-build-isolation --no-deps -e .`，版本 1.0.0 |
| Wheel 打包检查 | **通过** | Python 发行 Wheel 内含 `productivity_agent/static/index.html` |
| 无 LangGraph 的离线 `pytest` | **34 passed** | M0 4，M2 Intent 5，M4 SQLite 8，M6 HTTP Fake 8，M7 业务 3 + HTTP 6 |
| M7 确定性场景评测 | **10 / 10 passed** | 日程 5、SQLite 任务 5；零模型调用 |
| 全量 `pytest` | **未能执行完整** | 缺少 LangGraph/LangChain；PyPI 无法访问，8 项测试模块在收集阶段发生导入错误（另有 1 项被跳过） |
| 千问百炼在线调用 | **未执行** | 没有用户 API Key；避免未经授权产生费用 |
| Docker 运行、PostgreSQL、gRPC Server | **未执行或未实现** | 提供 Dockerfile；PostgreSQL/gRPC 仅为后续方向 |

### 离线命令和结果

```bash
PYTHONPATH=src python -m pytest -q \
  tests/test_m0_foundation.py tests/test_m2_intent.py \
  tests/test_m4_store.py tests/test_m6_api.py \
  tests/test_m7_offline.py tests/test_m7_http.py
# 34 passed in 0.80s

PYTHONPATH=src python -m productivity_agent.evaluation \
  --out reports/m7-offline-evaluation.json
# M7 offline acceptance: 10/10 passed
```

本次执行容器 Python 版本为 **3.13.5**；建议在用户 Conda **Python 3.12** 环境运行完整版。由于网络/DNS 限制，无法在该容器获取 `langgraph` 和 `langchain-core`，因此不能声称 M1～M6 所有真实 Graph、Interrupt、SQLite Saver 与 ToolNode 的集成测试都通过。

### 10 个确定性场景

1. 日程无冲突。
2. 日程有冲突，推荐首次可行的备选时间。
3. 左闭右开区间端点相接不判冲突。
4. 无效时间区间被拒绝。
5. 截止时间之前没有可用时段。
6. 相同业务 ID 重放，不重复写入。
7. 数据库提交后超时，基于操作 ID 对账。
8. 数据库提交前失败，后续安全重试。
9. 同一业务 ID 配不同参数被拒绝。
10. 6 个并发请求使用相同业务 ID，只有一个写入。

原始机器可读记录：[reports/m7-offline-evaluation.json](../../reports/m7-offline-evaluation.json)。本次运行的**平均单场景用时约 3.94 ms，最长约 15.86 ms**，只反映当前本地内存计算/SQLite 文件模拟环境，**不得解读为 Agent 线上延迟或真实 Qwen 能力**。

### 如何补齐最终验收

在能访问 PyPI 的机器或 GitHub Actions 运行：

```bash
python -m pip install -e '.[dev]'
python -m pytest -q
python -m productivity_agent.evaluation --out reports/m7-offline-evaluation.json
```

如果真实 Graph 测试出现失败，应根据堆栈定位并修复，不要仅删除或跳过测试以制造全绿结果。

在线千问联通测试独立运行 `python scripts/qwen_smoke.py --live`，需要先配置用户自己的 API Key。它只验证模型能返回文本，不等价于完整 Agent 的任务成功率。
