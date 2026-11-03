# TASK 07 — M9 多用户测试系统

范围：可信测试账号、任务/会话/审批/幂等隔离、真实HTTP与重启验证；不做生产认证或公网部署。
M8 PR #6 已按受限范围合并，合并提交 `f470c419895668307d2b7d71dade242256615a10`；
[Linux CI](https://github.com/re-tourist/Personal-Productivity-Agent/actions/runs/41585281049)通过。
删除[#7](https://github.com/re-tourist/Personal-Productivity-Agent/issues/7)、复杂定位[#8](https://github.com/re-tourist/Personal-Productivity-Agent/issues/8)继续待办，M8仍Open。
M9使用独立分支/PR，不自动合并或关闭M9。

## 可信身份

设置 PPA_AUTH_CONFIG 启用认证。服务端只读取受信账号文件中的稳定账号ID与token_sha256；
客户端发 Authorization: Bearer <token>，服务端计算SHA-256并常量时间比较，验证通过才得到主体。
不信任X-User-ID、user_id或owner_id请求字段；不能以thread_id/operation_id或旧演示Token代替身份。
无效/缺失Bearer返回401；配置损坏、空账号表、重复凭证等启动失败，不能回退匿名模式。
普通Web/health/OpenAPI仅公开静态内容与版本，不返回业务资源。

保留旧单用户演示兼容：未设置PPA_AUTH_CONFIG时仍是legacy模式，system明确返回auth_enabled=false，
旧X-PPA-Token仍可用。这不是多用户安全模式。多用户验收必须明确设置配置文件。

生成两账号的私有测试凭证（只在本地文件保存，不打印Token，不覆盖已有文件）：

```powershell
.venv-py312/Scripts/python.exe -m scripts.setup_test_accounts --out-dir .ppa-data/m9-auth
$env:PPA_AUTH_CONFIG=(Resolve-Path .ppa-data/m9-auth/accounts.auth.json).Path
$env:PPA_ENABLE_LIVE_QWEN='0'
$env:PPA_DATA_DIR='.ppa-data/m9-agent'
$env:PPA_TASK_SERVICE_URL=''
.venv-py312/Scripts/python.exe -m uvicorn productivity_agent.api.app:create_app --factory --host 127.0.0.1 --port 8000
```

client-tokens.auth.json仅供本机测试客户端使用，勿粘贴到报告/Issue。文件和*.auth.json均被忽略。
服务端配置只保存摘要；每个Token由32字节随机数生成。文件权限继承本机环境，生产凭证管理不在此范围。
Web访问令牌框会发Bearer；切换令牌清除会话/展示缓存并拒绝旧请求回填。令牌不写localStorage。
客户端按账户分别发送请求；GET /v1/me显示验证后的owner_id及auth_enabled。

## 数据与持久化边界

- tasks增补owner_id，默认`__legacy__`。旧任务不删除、不自动认领给alice/bob；旧操作记录原样保留。
  新账号不能读取legacy任务。没有管理/认领接口；真实数据迁移须另行备份与审核，本轮只操作合成库。
- 服务端OwnedTaskStore绑定已验证主体，所有创建/列表/详情/修改/完成及操作结果查询按owner过滤。
  修改在同一BEGIN IMMEDIATE事务内先验证owner，再重放或比较version后UPDATE，拒绝越权先于副作用。
- 为保留旧幂等表及其原始operation_id行，legacy操作沿用原键；新用户操作的内部键为
  SHA256([owner_id, operation_id])命名空间。相同输入ID在两个用户下互不重放；查询还核验实际任务owner。
  命名空间不是身份凭据，业务层仍执行资源归属检查。
- access.sqlite持久化(kind, thread_id, owner_id)绑定；先授权，再读/恢复/审批Checkpointer。
  Checkpointer键也含服务端owner前缀，图的owner_id只从验证后的请求初始化，模型不能指定。
  旧无绑定会话在安全模式下隔离，不允许自动认领。
- 外人资源与不存在资源统一404，不暴露资源存在性；操作查询无结果也不暴露其他用户结果。
  SSE在发送业务事件/读取图状态之前授权，流中只含本人会话与任务。

## HTTP服务及API

沿用原统一助手/草稿接口，新增GET /v1/me、GET /v1/tasks/{id}、GET /v1/operations/{id}。
创建/修改/完成仍经已有人工审批图；业务服务写入契约要求approved=true，不能当作认证凭据。
持有本人Token的直接业务API调用者可以显式批准自己的写入；不提供独立签名审批票据。
LLM不接收Bearer，也不获得未经批准的写入能力。

两服务模式下，业务服务和Agent均设置同一账号配置，使用不同数据目录；启动方法沿用
[M8 HTTP步骤](TASK_06_BUSINESS_OPERATIONS.md)，额外在两个终端设置PPA_AUTH_CONFIG。
请求级Graph/Store绑定凭证，不在全局可变对象中切换用户。HTTP Client转发已验证的Bearer，
调用资源之前GET /identity核对业务端认证已启用且主体一致；若业务端仍匿名或主体不一致就拒绝。
TASK08移除身份验证缓存，每次资源请求均重新核验；legacy业务端拒绝Authorization请求，防止认证服务重启降级或预检后切换造成错误身份读写，见[修复记录](TASK_08_M9_CLOSURE.md)。
带凭证的HTTP Client仅允许loopback地址，避免误发凭证到外部服务。没有新增微服务基础设施。

## 可复核验收

```powershell
$env:PPA_ENABLE_LIVE_QWEN='0'
.venv-py312/Scripts/python.exe -m pytest tests/test_task07_security.py -vv
.venv-py312/Scripts/python.exe -m pytest -q
.venv-py312/Scripts/python.exe -m productivity_agent.evaluation --out reports/task07/m9-offline.json
.venv-py312/Scripts/python.exe -m pip check
```

测试覆盖真实FastAPI、SQLite、LangGraph直连，以及两个独立Uvicorn进程和真实TCP：

本机Python3.12完整127 passed，0 failed/errors/warnings；M7离线10/10；pip check无冲突；修改Python文件Ruff通过。
新增loopback配置限制后定向用例另有1 passed。原始数据库SELECT摘录及测试统计见
[去敏验收摘要](../reports/task07/m9-summary.json)，包含直连/HTTP下两账户各1条任务，以及并发/重启后alice/completed/version3的四组快照。

1. A创建待审批操作；B不能GET/恢复/发送消息/SSE/批准A的会话，A批准后B仍无法读取任务或操作结果。
2. B猜A任务ID修改不进入审批；业务HTTP PATCH也返回404；同名任务各归其主，列表/SSE不混淆。
3. 旧草稿API也检查归属；不能用X-User-ID或请求owner_id冒充主体。
4. 同一用户两个同版本审批并发，只有一个updated，另一个conflict；数据库版本只增加一次。
5. HTTP模式真正停止并重启Agent与业务服务；B仍不能恢复/审批，A可继续原审批并重放，最终版本3/completed。
6. 原始SQLite SELECT核验两账户各1条任务，以及重启后owner/status/version；操作ID在账户间独立。
7. 旧表迁移保留旧任务/幂等行，新账号看不到；旧无绑定会话不可认领。
8. 账号设置脚本不打印或覆盖凭证；未认证业务端和主体混淆的HTTP适配拒绝，不发生写入。

首次SSE测试误把B自己输入的猜测ID回显当成泄露，改为干净B会话保留同一强断言；没有弱化旧测试。
结果与公开的去敏验收摘要见本轮PR。原始日志/数据库/账号文件只留在忽略的测试缓存目录。

## 安全边界与后续

这是单机多用户测试系统：静态测试Token、可信本地配置、loopback传输，不是生产多租户认证。
未实现OAuth、登录/登出令牌生命周期、到期/刷新、在线撤销、速率限制、管理员/角色、数据库加密、
跨主机TLS部署或防有权限的本机操作者读文件。账号配置在启动时加载；换Token需重启，不能把账户名交给不同主体复用。
同一进程的Thread锁不提供多Worker会话互斥承诺；SQLite事务仍保护业务写入，部署保持单Worker。
生产部署/日志追踪/回滚归M10；删除与复杂语义仍未完成。本轮真实Qwen调用0次、费用0元。
