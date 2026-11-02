# 工程基线与本地验收

先在已安装 `.[dev]` 的环境确认 `python -c "import sys; print(sys.executable)"`，使用同一解释器执行 pip、pytest 和服务，不混用 PATH 中其他 `pytest.exe`。依赖声明仍以 pyproject.toml 为准，本轮未升级版本。

```powershell
$env:PPA_ENABLE_LIVE_QWEN = '0'
$env:DASHSCOPE_API_KEY = ''
python -m pip check
python -m pytest -q
python -m productivity_agent.evaluation --out reports/m7-offline-evaluation.json
```

本机本轮验证解释器为 `.venv/Scripts/python.exe`、Python 3.14.6；推荐 Python 3.12 尚需在 CI 复核。本轮报告输出保存在 `reports/task02-2026-11-02/`，不覆盖历史评测。

## 安全临时目录

`tests/conftest.py` 在未指定 `--basetemp` 时，独占创建 `.pytest_cache/ppa-tmp/session-<随机值>`，然后交给 pytest。每个会话是全新目录，不扫描系统 Temp、不复用固定目录、不清空已有会话；并行运行不会共享同一个 basetemp。拒绝缓存目录重定向到其他路径。普通 pytest、IDE、verify 脚本和 CI 自动使用相同规则，无需写死 Windows 路径。

pytest 会清理 basetemp，因此**不要把业务数据、源码、仓库根目录或已有证据目录传给 `--basetemp`**。显式 CLI 覆盖仍按 pytest 原生行为处理，由调用者负责；本项目不将 CLI 指向的任意路径重新解释为安全目录。新会话目录保留用于失败诊断，长期开发需按需人工清理 `.pytest_cache/ppa-tmp` 中已结束会话，不在测试开始时自动递归清理其他会话。系统 ACL 未改动。

## 初始 Git 方案（只建议，未提交）

建议先建立一个可审阅的本地初始快照，包含源码、原有及新增测试、pyproject/requirements、脚本、CI、Docker、License、协作约定和文档。选择性纳入去敏后的评测 JSON 与审计摘要。TASK 01/02 原始机器日志含本机路径，应先审阅，避免直接 `git add .`。

不纳入 `.env`/令牌、`.venv`、`.idea`/`.vscode`、`.ppa-data`、缓存、测试数据库、临时服务器文件、生成测试目录。`.env.example` 仅允许占位符模板。检查 `git status --short --untracked-files=all`、`git check-ignore`，用户授权暂存后再审阅 `git diff --cached`，经授权才 commit。Push/Merge/Release 均是独立授权动作。

当前无 HEAD，`git diff` 为空不能证明未修改；本轮使用前后 SHA-256 和 unified patch 记录变化。模式扫描仅覆盖候选文本，不读取真实凭证或业务数据库，也不是无敏感信息的绝对保证。

## 新增验收边界

- 三个独立 OS 进程依次通过真实 FastAPI + AsyncSqliteSaver 创建草稿、审批、重查与拒绝重放；批准/拒绝参数化，业务 SQLite 行数及任务 ID 有断言。
- 同进程真实 HTTP 并发审批只允许一个 200，其余 409；相同 payload 两次草稿是两个独立操作，第二个拒绝不写入。草稿 POST 不具有跨请求幂等语义；存储 operation_id 幂等仍由原测试验证。
- SSE 使用 Scripted Model + 真 LangGraph/ToolNode，断言完成事件唯一且最后发送；工具 RuntimeError 返回去敏 error，没有伪造 done。
- 独立 Uvicorn 子进程仅监听 loopback 随机端口；真实 TCP 客户端收到进度后断开，断言上游异步流 finally 被执行、服务仍健康，最终回收子进程。

这些是离线本地集成测试，不是在线 Qwen 或浏览器人工验收。断流用可取消的异步流验证资源释放，不承诺已经运行的同步工具/远端调用可被撤回，也不包含断点续传。
