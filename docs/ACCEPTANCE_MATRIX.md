# PPA v1.0 — 验收矩阵与证据口径

> 原则：**源码存在 ≠ 测试通过 ≠ 模型有效 ≠ 可用于生产**。验收以用户本地环境、可复制命令和真实运行日志为准。

前端入口修复：用户已要求支持根地址。当前 `GET /` 应返回 307 并跳转 `/app`，跟随跳转后应为 200 HTML。下文历史记录中的“根路由 404”只代表修复前状态。

TASK 02 已补充真实跨进程审批恢复、真实 HTTP 拒绝/并发重放和 SSE 异常/断流测试；最新执行与限制见 [TASK 02 报告](audits/TASK_02_2026-11-02.md)，标准 pytest 的临时目录规则见 [工程基线](ENGINEERING_BASELINE.md)。以下旧记录继续保留。

## 1. 交接时状态（历史记录）

2026-11-02 最新复核：默认临时目录复现 37 passed / 31 errors；指定工作区可写临时目录后同源码 68 passed / 13 warnings。G1 在明确解释器与临时目录的条件下通过，默认命令仍受目录权限阻断；G5 真正跨进程恢复仍未验收。详细 Gate 判定见 [审计报告](audits/TASK_01_2026-11-02.md)。以下保留交接时状态，不替代最新证据。

| 层次 | 证据 | 结论 |
|---|---|---|
| Pytest 全量 | 用户：`37 passed, 13 warnings, 31 errors in 9.15s` | ❌ 未通过；错误尚未聚类 |
| M7 确定性离线场景 | 用户：`10/10 passed`，JSON 报告已生成 | ✅ 局部验收通过 |
| Uvicorn 进程启动 | `Application startup complete` | ✅ 启动阶段成功 |
| HTTP 根路由 | `GET /` 404，`favicon.ico` 404 | ◻️ 可能是正常未定义路由，非功能验收结果 |
| `/app` 浏览器操作 | 未提供实测记录 | ⏳ 待验收 |
| LangGraph 图集成与 SQLite Checkpointer | 全量测试有 errors，缺完整 traceback | ⏳ 待定位 |
| Qwen 实际 API | 未提供在线模型调用结果 | ⏳ 待用户授权后验证 |
| GitHub Actions / Docker | 无最新运行证据 | ⏳ 待验证 |

## 2. M7 最终验收 Gate

| ID | 类型 | 验收要求 | 无付费 API | 优先级 |
|---|---|---|---|---|
| G0 | 环境 | Python、依赖、解释器路径可记录；`python -m pip check` 无依赖错误 | 是 | P0 |
| G1 | 自动化回归 | `python -m pytest -q` **0 failed / 0 errors**，warnings 分类说明；不得删改测试掩盖失败 | 是 | P0 |
| G2 | 确定性业务 | `python -m productivity_agent.evaluation --out reports/m7-offline-evaluation.json` 输出 10/10 且记录有效 | 是 | P0 |
| G3 | HTTP | `/health`、`/docs`、`/app` 返回预期；日程检查与非法输入的状态码正确 | 是 | P0 |
| G4 | 审批/事务 | 草稿→待审批→拒绝不写入；草稿→批准只写一条；重放响应正确 | 是 | P0 |
| G5 | 恢复 | 同一 thread 的待审批状态可跨新进程重启恢复；不同 thread 隔离 | 是 | P0 |
| G6 | 失败注入 | 提交前失败可有界重试；提交后响应超时可对账；同一 `operation_id` 不重复写入，异 payload 拒绝 | 是 | P0 |
| G7 | SSE | 返回符合 SSE 格式的进度与完成事件；错误场景不泄漏内部敏感信息 | 是 | P0 |
| G8 | Tool Agent | Fake Model 工具选择、工具结果反馈、调用预算限制均受测试覆盖 | 是 | P0 |
| G9 | 千问在线 Smoke | 显式批准后使用低成本已核实模型，证明最小文本与 Tool Calling 调用；报告模型/地域/调用次数/Token 使用情况 | **否** | P1 |
| G10 | Release | README、架构图、API、限制说明、演示脚本、测试报告一致；Git 工作区状态清晰 | 是 | P1 |

M7 的**本地原型验收**可以在 G0～G8 成立后完成；如果要在简历中宣称“真实千问 Tool Calling 已集成验证”，必须额外通过 G9。PostgreSQL、gRPC、生产多用户授权不属于当前 Gate，不得暗示已完成。

## 3. 推荐验收命令（PowerShell）

```powershell
python --version
python -c "import sys; print(sys.executable)"
python -m pip check
python -m pytest -q
python -m productivity_agent.evaluation --out reports/m7-offline-evaluation.json
python -m uvicorn productivity_agent.api.app:create_app --factory --host 127.0.0.1 --port 8000
```

浏览器验收入口：`http://127.0.0.1:8000/app`、`/docs`、`/health`。`GET /` 为 404 不构成 Gate 失败，除非之后明确增加根路由需求。

## 4. 每轮修复必须保留的证据

1. 环境：Python 与关键依赖版本，`git status --short --branch`（脱敏）。
2. 执行：完整命令、执行时间、退出码、passed/failed/errors/warnings。
3. 代码：修改文件、影响接口、diff 摘要、为何能修复根因。
4. 回归：关联模块测试 + 全量 pytest + 离线评测；若未运行，要写具体阻断原因。
5. API：状态码、关键字段和操作次数；不要保存个人敏感信息。
6. 模型：真实调用与 Mock 严格区分；未授权默认 **0 次在线调用**。

## 5. 建议状态标识

- `PASS`：有实测证据，符合 Gate。
- `FAIL`：有实测证据，不符合 Gate。
- `BLOCKED`：环境/资源阻断，未执行完成。
- `NOT_RUN`：尚未进行。
- `OUT_OF_SCOPE`：本阶段不要求。

不得用 `PASS` 代替 `BLOCKED/NOT_RUN`，也不得把 Fake Agent 测试描述为真实百炼 API 的成功率。
