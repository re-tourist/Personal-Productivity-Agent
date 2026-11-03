# TASK 08 — Final Integration & Delivery

定位：可运行、可复现、可展示的本地Agent实习作品集，不是生产多租户服务。
M10独立分支/PR仅交付工程验收、复现脚本和文档，等待用户审核，不自动合并、不创建Release。

## M9已收尾

[PR #9](https://github.com/re-tourist/Personal-Productivity-Agent/pull/9)合并为
`913cee8b346d7953e834a8e3fa50bd49a9d05260`；修复头33292d0的
[Linux CI成功](https://github.com/re-tourist/Personal-Productivity-Agent/actions/runs/41592458358)。
M9/#4仅按约定的本地测试账号、资源/会话隔离、并发与恢复范围关闭。

真实同地址/同客户端重启复现identity_verified缓存风险，原测试出现DID NOT RAISE。
取消缓存并在legacy业务端拒绝Authorization，预检后切换也不能提交写入；三项真实网络回归通过。
完整130 passed、离线10/10、修改文件Ruff及安全检查通过，见[修复记录](TASK_08_M9_CLOSURE.md)。

## Docker：未验证，未通过容器验收

实际检查PATH docker命令与标准Docker Desktop可执行文件路径，均未找到CLI。
没有构建镜像、启动或重启容器，也没有安装或修复宿主环境。没有将Mock或本地进程算作Docker通过。
[阻塞记录](../reports/task08/docker-status.json)。Dockerfile保持原样，单Worker；仅加强.dockerignore，
排除认证文件、数据库、日志以及原有私人未跟踪文件/配置，避免后续构建上下文包含它们。
README提供Docker可用环境下的待验证命令，使用宿主loopback端口、只读账号配置和独立持久化数据目录。

## 清洁Python环境与真实HTTP替代证据

用Python3.12新建`.pytest_cache/task08-clean-venv`，未复用原环境或修改其依赖，实际执行：

```powershell
.venv-py312/Scripts/python.exe -m venv .pytest_cache/task08-clean-venv
.pytest_cache/task08-clean-venv/Scripts/python.exe -m pip install -e ".[dev]"
.pytest_cache/task08-clean-venv/Scripts/python.exe -m pip check
.pytest_cache/task08-clean-venv/Scripts/python.exe -m scripts.verify_final_delivery --out reports/task08/local-delivery.json
```

安装退出0，pip check无冲突。实际解析的Python/依赖版本见[清洁环境记录](../reports/task08/clean-environment.json)。
按README同一安装/账号配置/启动路径执行，仅将目录换为隔离合成目录保护个人数据。

复现脚本在全新环境中生成两测试账号，通过真实HTTP执行认证、创建草稿、显式审批请求、查询、修改及再次查询；
Bob不能审批/恢复Alice会话，也不能读取Alice任务。模型强制为offline_rules，真实模型调用0。
脚本实际启动并停止3个不同PID的Uvicorn进程，单Worker、127.0.0.1：

1. 首次进程创建并批准任务，读回版本1；发起修改，保留待审批状态后停止。
2. 第二进程恢复同一审批/operation_id，批准并读回同一Task ID的版本2；重复批准不变，再自然语言查询。
3. 第三进程读回相同业务任务与会话终态，独立只读SQLite查询确认一条alice任务、version2。

本次合成Task ID `7cc7b6c2-1788-41d3-bb57-bd3cbf6f9653`：
到期2026-11-04 15:00+08（UTC07:00）→2026-11-05 10:00+08（UTC02:00），ID不变，无额外任务。
[实际HTTP/SQLite/恢复结果](../reports/task08/local-delivery.json)。这不是Docker证据。

## 最终回归与GitHub复现

清洁环境执行完整pytest、M7离线评测、pip check和修改Python脚本Ruff，实际130 passed，0 failed/errors/warnings，离线10/10，pip check与Ruff通过；统计见
[最终摘要](../reports/task08/final-summary.json)。原130项测试全部保留，包含M8/M9真实HTTP异常、幂等、权限隔离、
并发、SSE与跨进程恢复，没有为通过而删改断言。README更新安装、认证、Web和安全边界；旧真实模型失败账本保持原样。

GitHub Actions额外执行pip check及同一个真实HTTP启动/恢复脚本，并上传去敏结果artifact。
CI中的该脚本同样不等于Docker验证。M10 PR最终CI链接见PR检查与交付回复，PR保持开放待审核。

## 安全检查与展示标准

选择性提交代码、文档和去敏摘要；检查拟提交内容、可达Git历史及本轮日志中的当前Key/私有endpoint、
常见凭证模式，不提交.env、*.auth.json、业务库、Checkpointer或原始机器日志。
私人RELEASE_NOTES.md、exercises/保持未跟踪、未读取/覆盖。证据只包含合成账号名、任务、Token用量0等元数据。

已经证明本地清洁安装、认证核心业务、审批与持久化恢复可复现，适合按明确边界进行实习展示；
Docker容器验收仍阻塞，不能展示成已通过。没有生产OAuth、令牌到期/撤销、限流/TLS部署或多Worker会话锁，
没有真实通知/第三方生产API、删除或复杂自然语言定位。删除#7与复杂语义#8仍待办，M8保持Open。
M10保持Open等待审核，不为“完美”扩展基础设施。本轮真实Qwen 0次、费用0元，没有个人业务数据操作。
