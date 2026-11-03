# Personal Productivity Agent

一个面向 AI Agent 工程实习作品集的本地个人效率助手，使用 **Python 3.12、LangGraph、Qwen（百炼）、FastAPI、Pydantic 与 SQLite**。

主业务链路：自然语言 → 结构化意图 → 参数校验/多轮补充 → 确定性工具路由 → 人工审批 → 幂等写入 → 查询核验真实 Task ID。

## 功能与边界

- 创建带到期时间的待办：批准后才写入 SQLite，拒绝不写入。
- 同一会话补充缺失时间；Checkpointer 支持重启恢复。
- 重复确认和提交后超时由稳定 operation_id、事务与对账保护。
- 查询本地任务；查询明确标识的模拟日历，检查冲突并推荐时间。
- 按 ID 详情、审批后修改标题/到期时间或完成任务；版本冲突拒绝覆盖，HTTP不确定写入先对账。
- 轻量 Web 对话、确认按钮、SSE 节点进度；无需 Node.js 前端构建。
- 默认离线规则模式，无需 Key；Qwen 模式使用同一业务图。

**提醒目前仅表示待办到期时间，不会主动发送通知。** 没有接入真实第三方日历。模型选择固定业务动作，Python/LangGraph 负责路由与执行；统一主流程不具备工具后自主重规划。旧只读 ReAct 示例单独保留，不与主流程能力混淆。本项目仅供单用户本地演示，不是生产多租户服务。

## 本地安装与运行

M8 当前为部分验收：[业务/HTTP契约与演示](docs/TASK_06_BUSINESS_OPERATIONS.md)、[真实Qwen结果与剩余缺口](docs/audits/TASK_06B_2026-11-03.md)。同名多轮及纯时间定位的在线验收尚未通过，不宣称M8完成。

在项目根目录，使用 Python 3.12：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
$env:PPA_ENABLE_LIVE_QWEN = '0'
$env:PPA_DATA_DIR = '.ppa-data/demo'
.\.venv\Scripts\python.exe -m uvicorn productivity_agent.api.app:create_app --factory --host 127.0.0.1 --port 8000
```

打开 **<http://127.0.0.1:8000/>**（自动进入 `/app`）；API 文档：<http://127.0.0.1:8000/docs>。保持启动终端运行。已有 `.venv-py312` 环境也可将上述解释器路径替换为 `.venv-py312/Scripts/python.exe`。

Linux/macOS 可使用 `.venv/bin/python` 执行相同 pip、pytest、uvicorn 命令。Windows 时区数据依赖已在 pyproject.toml 声明。

### 三条演示请求

1. “明天下午三点提醒我准备组会” → 检查确认卡片 → 点击批准 → 返回真实 Task ID。
2. “帮我创建一个准备组会的任务” → 收到追问 → 同一会话输入“明天下午三点” → 批准或拒绝。
3. “帮我看看明天下午三点能不能安排一小时组会” → 查询本地模拟日历 → 返回冲突与候选时间，不修改日程。

可继续输入“查看我的任务”，或使用页面任务查询按钮核实记录。

## Qwen 配置与费用

复制 `.env.example` 为 `.env`，仅在本地填写同地域的 `DASHSCOPE_API_KEY`、`DASHSCOPE_BASE_URL` 和 `PPA_MODEL`。默认保留低成本 `qwen3.7-flash`；不自动更换高价模型。启用在线模式需设置 `PPA_ENABLE_LIVE_QWEN=1` 并重启服务，后续请求会消耗模型额度。

`.env`、`docs/ali/`、虚拟环境和业务数据库不会进入 Git。不要向 Issue、日志或截图粘贴 Key。首次演示可保持离线模式；模式条会明确区分在线 Qwen 和有限离线规则。

受控验收脚本默认不联网：

```powershell
.\.venv\Scripts\python.exe scripts/validate_qwen_agent.py
```

2026-11-03 已完成真实 `qwen3.7-flash` 业务验收：单轮创建、多轮补时间、日程冲突、拒绝、查询和重复确认保护。共 12 次调用，输入 9,090 / 输出 726 Token，按北京公开价格估算 ¥0.0023988（不是实扣账单）。在线测试发现的日程漏参数及无效时间问题已窄修复并复测；原始失败记录保留。详见 [真实 Qwen 验收报告](docs/ONLINE_VALIDATION.md)。

## 测试与架构

```powershell
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m productivity_agent.evaluation --out reports/m7-offline-evaluation.json
```

最终 Windows/Python 3.12 回归：**97 passed，0 failed / errors / warnings**，确定性场景 **10/10**。测试包含真实框架、SQLite、HTTP、跨进程恢复和 TCP 断流；Fake/Scripted Model 及内存 HTTP 不产生模型费用。pytest 自动使用工作区中新建的独占测试目录，无需指定可能清空数据的 basetemp。历史 Ruff 16 项单独保留，不通过删改测试制造通过率。

```text
src/productivity_agent/
  domain/       Pydantic 意图与确定性规则
  providers/    Qwen、有限离线规则、调用计量
  workflows/    LangGraph 会话、审批、恢复与业务编排
  tools/        模拟日历工具、授权后的可靠写工具
  services/     SQLite 业务事实与幂等事务
  api/          FastAPI、会话 API、SSE
  static/       单页 Web 演示
```

[文档索引](docs/README.md) · [MVP 功能和接口](docs/TASK_04_MVP.md) · [架构](docs/architecture.md) · [安全边界](docs/SECURITY.md) · [在线准备与预算](docs/TASK_05_QWEN_PREPARATION.md)

GitHub Actions 已在 Ubuntu/Python 3.12 [通过初始基线回归](https://github.com/re-tourist/Personal-Productivity-Agent/actions/runs/41484594861)，后续提交以 [Actions 最新记录](https://github.com/re-tourist/Personal-Productivity-Agent/actions) 为准。Dockerfile 已提供但容器尚未实测；真实定时通知、第三方日历和统一主流程的动态重规划仍待后续开发。
