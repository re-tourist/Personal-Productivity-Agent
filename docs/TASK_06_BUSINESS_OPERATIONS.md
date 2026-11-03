# TASK 06 — Business Operations & HTTP Integration

归属 M8，GitHub 跟踪 Issue：<https://github.com/re-tourist/Personal-Productivity-Agent/issues/3>。
本文件记录本轮实施边界，不修改 M0～M7 历史定义。代码待审核，不 Push。

## 功能与边界

统一助手支持创建、列表、按 ID 详情、修改标题/到期时间、完成任务，以及审批后读回核验。
所有修改/完成必须经过已有 LangGraph interrupt 与明确布尔审批；目标快照与稳定 operation_id
保存在原 Checkpointer 中。相同审批重放直接返回终态，存储层另有事务幂等保护。
同名目标不默认选第一条，返回候选及 ID；可用原到期时间或 ID 消歧。任务超过查询窗口时要求 ID。
任务删除、恢复为未完成、任意复杂中文表达、生产认证/第三方生产 API 均未交付。
离线规则仅覆盖本文示例；Qwen Structured Output 已扩展字段，真实 Qwen 新动作效果尚未验证。

## 数据兼容与并发策略

SQLiteTaskStore 在 BEGIN IMMEDIATE 事务中检查列并增补 version（初值 1）、status（初值 pending），
新增 task_changes 保存修改请求及不可变操作结果；原 tasks ID、title、due_at、task_operations 保留。
迁移可重复启动，不删除旧数据。使用现有数据库前请停止写入并自行备份数据库（含 WAL，如存在）；
本轮只在合成数据库验证迁移，没有操作个人数据库。旧版应用回滚不能视为已验证，旧版不认识新状态。

修改必须带审批时的 expected_version。事务内串行检查版本、修改、版本加一、写入操作记录并提交；
其他同版本操作返回冲突，必须重读并重新审批。operation_id 同参数重放不再增加版本，异参数复用拒绝。
完成操作也是版本化变更。所有到期时间必须带偏移，数据库统一存 UTC。

## 本地 HTTP/JSON 契约

独立业务服务是本地测试服务，只监听 loopback；approved 是可信调用方声明，不是身份认证或授权凭据。
不可把该服务直接暴露公网。用户批准在 Agent 已有审批图中执行；HTTP 适配器不交给 LLM。

| 方法/路径 | 输入 | 成功输出 |
|---|---|---|
| GET /health | 无 | status、local_test_service |
| GET /tasks?limit=100 | limit 为 1～1000 | items：任务数组 |
| GET /tasks/{id} | 明确 ID | id/title/due_at/status/version |
| POST /tasks | operation_id、approved:true、title、due_at（带偏移） | status:created/replayed、task |
| PATCH /tasks/{id} | operation_id、approved:true、expected_version、action:update_task/complete_task；可选 title/due_at | status:updated/replayed、task |
| GET /operations/{operation_id} | 稳定操作 ID | operation；未提交/不存在时为 null |

400：无效字段、时间、动作、空 patch 或未明确批准；404：任务不存在；409：版本/幂等冲突。
5xx/连接错误/写入超时均不能证明未提交。修改分支先查 operation，再读任务，核对请求及最终快照；
只要不能核实就返回 needs_review。不会因为 PATCH 超时而自动重发 PATCH。
创建继续使用原 M4 有界重试/对账图，所有重试复用同一个 operation_id；HTTP 服务共享同一事务存储语义。
若核验时资源又被后续操作改变，也不谎报当前状态与本次结果一致。

## 两个终端启动（全部使用合成目录）

终端 A：

```powershell
$env:PPA_DATA_DIR='.pytest_cache/task06-demo-business'
.venv-py312/Scripts/python.exe -m uvicorn productivity_agent.api.task_service:create_task_service --factory --host 127.0.0.1 --port 18765
```

终端 B：

```powershell
$env:PPA_ENABLE_LIVE_QWEN='0'
$env:PPA_DATA_DIR='.pytest_cache/task06-demo-agent'
$env:PPA_TASK_SERVICE_URL='http://127.0.0.1:18765'
.venv-py312/Scripts/python.exe -m uvicorn productivity_agent.api.app:create_app --factory --host 127.0.0.1 --port 18766
```

访问 <http://127.0.0.1:18766/app>。保留已有演示 Token 设置；如配置了 Token，在页面填入。
移除 PPA_TASK_SERVICE_URL 后恢复 SQLite 直连模式。两种模式使用同一业务存储与统一图，不合并业务库与检查点。
httpx 已从开发可选项提升为运行依赖，无主要依赖升级。

## Web 演示（无需编辑数据库或 JSON）

1. 输入“明天下午三点提醒我准备组会”，检查后批准。
2. 输入“把准备组会改到后天上午十点”，检查目标 ID、旧值和新值，批准。
3. 输入“查看我的任务”，核对 ID 不变、版本增加、没有新增任务。
4. 再输入“明天下午三点提醒我准备组会”并批准，生成第二条不同时间的同名任务。
5. 输入“把准备组会改到后天上午十点”，必须先出现两条候选；回复“明天下午三点的那个”。
6. 点击拒绝，再查询；第二条任务的时间和版本均应保持不变。
7. 输入“把<ID>改为新标题”或“把<ID>改到明天凌晨一点”，检查审批内容再批准。
8. 输入“完成任务 <ID>”并批准，然后“查询任务 <ID>”，状态应为 completed。

跨午夜补充示例：“今晚十一点提醒我跨日任务” → 批准 → “把<ID>改到稍后” →
“明天凌晨一点” → 批准。reference_now 与 timezone 由页面发送，后端要求有偏移时间及有效时区。

## 诊断与复现

ppa.agent 记录 request_id/thread_id/operation_id、动作、目标 ID、节点与最终状态；ppa.http
记录关联字段、HTTP 状态、耗时与错误类别；业务服务沿用请求关联 ID。日志不输出用户正文、任务标题、Key 或凭据。
每个修改审批通过稳定 operation_id 与原消息关联，可定位 PATCH、对账 GET、图最终状态。
故障注入仅在 tests/helpers/business_server.py 中，不提供产品故障开关或公开注入端点。

```powershell
.venv-py312/Scripts/python.exe -m pytest tests/test_task06_operations.py -vv
.venv-py312/Scripts/python.exe -m pytest -q --junitxml=reports/task06/pytest.xml --log-file=reports/task06/pytest.log --log-file-level=INFO
.venv-py312/Scripts/python.exe -m productivity_agent.evaluation --out reports/task06/offline-evaluation.json
```

执行事实、故障根因、测试限制见 [本轮报告](audits/TASK_06_2026-11-03.md)。
