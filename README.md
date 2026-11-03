# Personal Productivity Agent

面向 Agent 应用工程实习的本地作品集：Python 3.12、LangGraph、Qwen、FastAPI、SQLite。
自然语言 → 结构化意图 → 确定性校验/工具路由 → 人工审批 → 事务与幂等写入 → 真实业务状态核验。

支持创建、列表/详情、改标题/到期时间、完成任务；支持版本冲突、重复确认、会话持久化与重启恢复。
默认使用有限离线规则，不需要模型Key。配置测试账号后可验证双用户任务/会话/审批/SSE隔离。
提醒只表示待办到期时间，不主动通知；日历为明确标识的模拟数据，不是企业生产API。

## 清洁安装与认证启动

在新checkout的项目根目录执行，先确认 `python --version` 是 **3.12**。已有环境可替换解释器路径，不覆盖已有环境。

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -e ".[dev]"
.venv/Scripts/python.exe -m pip check
.venv/Scripts/python.exe -m scripts.setup_test_accounts --out-dir .ppa-data/demo-auth
$env:PPA_AUTH_CONFIG=(Resolve-Path .ppa-data/demo-auth/accounts.auth.json).Path
$env:PPA_ENABLE_LIVE_QWEN='0'
$env:PPA_TASK_SERVICE_URL=''
$env:PPA_DATA_DIR='.ppa-data/demo'
.venv/Scripts/python.exe -m uvicorn productivity_agent.api.app:create_app --factory --host 127.0.0.1 --port 8000 --workers 1
```

Linux/macOS用 `.venv/bin/python`，并以 `export PPA_AUTH_CONFIG="$PWD/.ppa-data/demo-auth/accounts.auth.json"` 等设置相同环境变量。
账号脚本不会打印Token或覆盖已有文件；Token仅保存在被忽略的client-tokens.auth.json，服务端配置保存摘要。
不要将Token粘贴到Issue、日志或截图。`PPA_AUTH_CONFIG`未设置时保留旧legacy单用户模式，**不是多用户安全模式**。

## Web演示

访问 <http://127.0.0.1:8000/app>，本地查看client-tokens.auth.json，将alice令牌填入访问令牌框并开启新会话。

1. “明天下午三点提醒我准备组会” → 核对卡片 → 批准。
2. 复制返回的Task ID，输入“把<ID>改到后天上午十点” → 核对旧值/新值及ID → 批准。
3. “查询任务 <ID>” → 核对同一ID、版本增加、没有新建任务。
4. “完成任务 <ID>” → 批准 → 再次查询应为completed。
5. 切换bob令牌开启新会话，不能读取alice的任务、会话或审批；切换账号会清理页面会话缓存。

拒绝修改不写入。在线模型遇到同名、纯原时间或不可靠指代时要求明确ID，不猜测目标。
复杂自然语言消歧/纯原时间跨午夜定位仍延期[#8](https://github.com/re-tourist/Personal-Productivity-Agent/issues/8)，
删除仍延期[#7](https://github.com/re-tourist/Personal-Productivity-Agent/issues/7)。不把旧离线回放冒充在线能力通过。

API文档：<http://127.0.0.1:8000/docs>；业务请求使用 `Authorization: Bearer <测试Token>`，不能通过user_id或X-User-ID指定主体。
[多用户安全设计](docs/TASK_07_M9_SECURITY.md) · [独立HTTP业务服务契约](docs/TASK_06_BUSINESS_OPERATIONS.md)。

## 一条命令复现启动与恢复

```powershell
.venv/Scripts/python.exe -m scripts.verify_final_delivery --out reports/local-delivery.json
```

脚本只生成隔离合成数据和测试账号，不调用Qwen；通过真实loopback HTTP完成认证、创建、审批、查询、修改及核验。
它实际停止/启动三个单Worker进程，恢复待审批Checkpoint并审批，再次重启核对业务SQLite与终态会话。
这是**本地进程验收，不是Docker实测**。Token、数据库和原始日志不提交。

## Docker（本轮未通过实测）

当前宿主PATH和标准Docker Desktop路径均未发现Docker CLI；未执行镜像构建/容器启动，没有修复宿主环境。
本轮以清洁Python环境的真实HTTP/重启证据替代。以下仅供Docker可用环境复现，不能作为已通过证据：

```powershell
docker build -t ppa:portfolio .
New-Item -ItemType Directory -Force .ppa-data/docker-demo | Out-Null
$authFile=(Resolve-Path .ppa-data/demo-auth/accounts.auth.json).Path
$demoData=(Resolve-Path .ppa-data/docker-demo).Path
docker run -d --name ppa-portfolio-demo -p 127.0.0.1:8000:8000 --mount "type=bind,source=$authFile,target=/run/ppa-accounts.auth.json,readonly" --mount "type=bind,source=$demoData,target=/app/.ppa-data" -e PPA_AUTH_CONFIG=/run/ppa-accounts.auth.json -e PPA_ENABLE_LIVE_QWEN=0 ppa:portfolio
docker restart ppa-portfolio-demo
```

沿用相同Web步骤核验重启后ID/任务/待审批会话；Dockerfile默认单Worker，容器内绑定0.0.0.0，宿主发布端口限定127.0.0.1。
`.dockerignore`排除环境、认证文件、数据库、日志及私人文件；不把Key或账号文件烘焙进镜像。

## 工程验收与边界

```powershell
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m productivity_agent.evaluation --out reports/task08/offline-evaluation.json
.venv/Scripts/python.exe -m pip check
```

M9收尾完整130 passed，离线10/10；认证降级风险已真实复现并修复：[修复记录](docs/TASK_08_M9_CLOSURE.md)。
最新交付结果见[M10验收报告](docs/TASK_08_FINAL_DELIVERY.md)及[GitHub Actions](https://github.com/re-tourist/Personal-Productivity-Agent/actions)。
CI执行全量回归、离线评测、依赖检查和实际认证HTTP进程重启脚本；不会收费调用模型。

本项目是单机多用户测试系统，不是生产多租户服务：静态测试Token无到期/在线撤销，缺少生产角色/限流/TLS部署，
不承诺多Worker会话锁；legacy旧数据隔离而非自动认领。没有真实定时通知、第三方日历、动态重规划、RAG或Multi-Agent。
M8/M9范围与原始失败记录保留，不改写历史验收事实。

真实Qwen配置使用本地.env与同地域Key；默认qwen3.7-flash，不自动换更贵模型。旧收费授权已用完，本轮0次/0元，
新在线调用需要单独授权。历史真实验证见[Qwen报告](docs/ONLINE_VALIDATION.md)和[M8失败记录](docs/audits/TASK_06B_2026-11-03.md)。
[文档索引](docs/README.md) · [架构](docs/architecture.md) · [安全设计](docs/TASK_07_M9_SECURITY.md)

## R1 架构导航

HTTP / CLI 主实现位于 `interfaces/`，纯业务契约与规则位于 `domain/`，SQLite、HTTP
客户端、身份存储和模型实现位于 `infrastructure/`，资源装配与生命周期位于 `bootstrap.py`。
现有 `workflows/`、`tools/` 和 Graph/LLM 契约留给 R2；当前没有未使用的 Application 抽象。

旧 Assistant、Business、CLI、模块命令和 Docker 入口均保留兼容重导出。新主入口也可独立启动：

```powershell
python -m uvicorn productivity_agent.interfaces.http.assistant_app:create_app --factory --host 127.0.0.1 --port 8000 --workers 1
python -m uvicorn productivity_agent.interfaces.http.business_app:create_task_service --factory --host 127.0.0.1 --port 8001 --workers 1
```

两条命令在不同终端执行；按上文配置测试账号并为各进程指定独立 `PPA_DATA_DIR`。
Assistant 使用远程业务模式时设置 `PPA_TASK_SERVICE_URL=http://127.0.0.1:8001`，两端使用同一账号配置。
默认仍为离线、本地 SQLite 模式。详细迁移、兼容性证据与 R2 清单见
[R1 工程报告](docs/R1_ARCHITECTURE_REFACTOR.md)和[当前架构](docs/architecture.md)。
