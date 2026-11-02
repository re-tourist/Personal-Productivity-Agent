# 测试与评测证据入口

最新：[TASK 02 工程基线与集成验收](audits/TASK_02_2026-11-02.md)。默认 pytest 已通过安全的每会话临时目录方案验证；运行方法见 [工程基线](ENGINEERING_BASELINE.md)。

- [本轮审计与测试报告](audits/TASK_01_2026-11-02.md)：默认目录 37 passed / 31 errors；可写临时目录 68 passed / 13 warnings。
- 原始日志与环境（本地审计附件，未随公开源码分发）：整理前后结果、完整 traceback、离线 JSON。
- [验收矩阵](ACCEPTANCE_MATRIX.md)：pytest 通过不等于所有 Gate 完成。
- [历史 M7 局部验收](history/M7_EVALUATION_ORIGINAL.md)：旧生成环境 Python 3.13.5、34 passed、缺框架依赖；不代表当前环境。

先确认解释器。本轮有效解释器是 `.venv/Scripts/python.exe`（Python 3.14.6）；推荐的 Python 3.12 环境尚未完成本轮验收。

```powershell
$env:PPA_ENABLE_LIVE_QWEN = '0'
$env:DASHSCOPE_API_KEY = ''
.venv/Scripts/python.exe -m pytest -q --basetemp=reports/task01-2026-11-02/tmp-local-check
.venv/Scripts/python.exe -m productivity_agent.evaluation --out reports/task01-2026-11-02/evaluation-local.json
```

`--basetemp` 由 pytest 管理，重跑会清空指定目录；只指向专用测试目录。原测试、配置及业务代码未因目录问题修改。环境变量只影响当前终端及子进程，在线调用仍须单独授权。
