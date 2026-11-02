# TASK 05-B：真实 Qwen 与 GitHub 交付

日期：2026-11-03，Asia/Shanghai。**核心业务真实验收完成，包含发现问题后的复测；不是一次性全场景零失败。** 原始脚本保留 `PARTIAL_WITH_WEB_CONTINUATION`，不把初次失败改写成通过。所有请求来自用户授权的同一笔 **12 次 / ¥0.05** 预算，SDK 自动重试为 0；现已停止服务及收费调用。

## 实测场景

| 场景 | 实际调用序号 | 核验结果 |
|---|---|---|
| A 单轮任务 | 1；Web 6、最终版本 11 | 解析“明天下午三点帮我创建一个准备组会的任务”；确认前无写入，批准后 SQLite 写入且查询到真实 Task ID |
| B 多轮补充 | 2、3 | “帮我创建一个准备组会的任务”请求时间；同 Thread 补充“明天下午三点”保留标题并进入审批；随后拒绝，任务数不变 |
| C 模拟日程 | 4 初次失败；5 复测通过 | 初次只返回 action，其他参数 null，安全追问。补充 Schema 描述及提取提示后，得到组会、次日 15:00、60 分钟，M1 检出 15:30～16:30 冲突并建议 16:30～17:30；没有修改日程 |
| D Web 拒绝 | 7 | 真实模型生成确认卡片，点击拒绝后 cancelled，数据库仍仅有此前批准的一条任务 |
| E 无效时间 | 8 初次失败；9 复测通过 | “明天25点”初次被模型错误改为零点，人工拒绝且未写入。增加无效时间提示及数字时钟 Python 校验后，模型返回 at=null，系统要求纠正且无审批/写入 |
| E 不支持意图 | 10 | “删除我的系统文件”被判 unsupported，无工具副作用 |
| 查询与重复保护 | 12；重复批准额外 0 次 | 真实 Qwen 选择 list_tasks；SQLite 返回第 11 次请求批准创建的同一 ID。第 6 次请求创建后重放相同批准，HTTP 200 返回同一 ID，前后任务集合相等 |

本次相对日期以请求中的明确当前时间及 Asia/Shanghai 解析，“明天”是 **2026-11-04**。最终 Web 任务：`6509d2c3-699b-4db4-bb65-8f53a67a1f99`，标题“准备组会”，到期 `2026-11-04T15:00:00+08:00`（数据库 UTC 为 `07:00:00+00:00`）。第一次 Web 服务任务为 `bb718324-9114-49a3-abaf-d0ad38544463`。每次服务使用独立临时业务库和 Checkpointer，仅合成任务，停止后清理自己创建的目录；不修改个人业务库。

[累计调用账本、初次失败与 Web 核验记录](../reports/task05b/online-acceptance.json) · [Web 实测截图](../reports/task05b/web-qwen.jpg)

## 模型角色与未验证项

Qwen 通过强制 `AgentIntent` Function Calling 生成固定动作枚举及结构化参数，支持真实多轮上下文。Pydantic 验参，Python/LangGraph 确定性选择读工具或审批节点，批准后执行 M4 幂等事务、lookup 核验并生成最终回复。模型既不自行授权写入，也不凭文本宣布成功。

**本次没有证明模型自主选择任意业务工具，也没有实现工具结果后的模型自主重规划。** 旧只读 ReAct 诊断因优先保留业务修复复测预算，本次未在线执行。工具故障、SDK timeout、无效 Schema、未知用量、真实 TCP 断流和跨进程恢复属于离线可复现集成证据，不冒称真实供应商异常实测。提醒仅创建待办，不主动通知；日历仍为明确标识的本地模拟。

数字时间防护只覆盖显式数字点/时和 HH:MM 的范围检查，不能替代完整自然语言日期语义验证；所有写入仍必须由用户核对确认。单次小样本通过也不代表长期模型准确率。

## 调用与费用

模型 `qwen3.7-flash`，北京业务空间兼容接口，非思考模式，输出限制 600。保留用户已有模型和地域，没有自动升级或额外连接测试。

- 实际调用 **12/12**，含两次初次业务失败；usage 全部可得，未知用量 0。
- 输入 **9,090**、输出 **726**，共 **9,816 Token**。
- 模型调用延迟均值 **1,227.67 ms**，范围 **594.52～2,744.86 ms**；不含全部浏览器人工交互时间，不是生产延迟基准。
- 按北京 <=32K 输入 ¥0.2 / 百万、输出 ¥0.8 / 百万的[官方公开价格](https://help.aliyun.com/zh/model-studio/qwen3-7-flash)估算 **¥0.0023988**。最保守软件预留 ¥0.025056，低于授权 ¥0.05；**真实账单实扣不可得，记录为 null**，不假设优惠或免费额度。

所有续跑保留同一累计账本；新增 `--resume-web-only` 不重置调用数，未知 usage 不允许续跑。Web 服务注入同一受控 meter，避免普通服务绕过验收预算。普通在线演示会按新输入继续计费，不共享本轮已用完的验收授权。

## 修改与工程证据

- `domain/agent_intent.py`、`workflows/assistant.py`：明确参数语义、日程完整提取和无效时刻处理；没有替换主流程。
- `providers/qwen_meter.py`：仅受控合成验收保存已校验意图，普通应用不保存内容。
- `scripts/validate_qwen_agent.py`：共享预算 Web 演示、安全续跑、保留历次数据库核验摘要。
- `tests/test_task04_assistant.py`、`tests/test_task05_qwen.py`：新增 3 个无效数字时钟业务回归和 1 个累计账本保护测试；原测试全部保留。
- `.gitignore` / `.dockerignore`：排除全部 `docs/ali/`、环境、数据库、缓存和私人配置。README、必要文档去敏，原始审计日志保留本地。

Python 3.12.8：`python -m pytest -q` → **97 passed / 0 failed / 0 errors / 0 warnings**，见[完整输出](../reports/task05b/final-tests.txt)。`python -m productivity_agent.evaluation --out reports/task05b/offline-evaluation.json` → [10/10](../reports/task05b/offline-evaluation.json)。`python -m pip check` 无冲突，六个修改 Python 文件 Ruff 通过；全项目仍有 16 项历史 Ruff 问题。

受限 Windows 沙箱内的一次 M7 执行出现临时目录权限错误（5/10），原始日志仅本地保留；相同评测在正常权限下 10/10。一次沙箱内定向 pytest 无输出被中止，正常权限下同一组 21/21 及完整 97/97 通过。没有为通过而改写评测、删除测试或放宽断言。

## GitHub 与演示

远端 [re-tourist/Personal-Productivity-Agent](https://github.com/re-tourist/Personal-Productivity-Agent) 初始检查为空，main 已完成真实初始提交 `7f6f21d1e7632a0c7da3c4afa6aa8fc2d59c8d3e`，没有制造历史、强推或创建 Release。初始 Ubuntu/Python 3.12 [CI 已通过](https://github.com/re-tourist/Personal-Productivity-Agent/actions/runs/41484594861)，最终修复以 [Actions 最新运行](https://github.com/re-tourist/Personal-Productivity-Agent/actions) 为准。

已建立两个实际待办：[真实提醒与通知 #1](https://github.com/re-tourist/Personal-Productivity-Agent/issues/1)、[受控工具反馈与动态重规划 #2](https://github.com/re-tourist/Personal-Productivity-Agent/issues/2)。Dockerfile 提供但容器尚未验收；没有扩展无关基础设施。

本地安装、在线/离线配置、启动与三条面试演示请求见 [README](../README.md)。默认仍为离线，真实 Key 仅在忽略的本地 `.env`，私有账号导出从未暂存或上传。公开证据仅含合成任务和去敏模型用量。

安全检查区分公开提交与工具快照：公开 main / origin/main 及拟提交文件的真实 Key、私有 endpoint 匹配均为 0。本机 Codex 自动维护的隐藏快照引用包含过私有导出，因此不能声称整个本地 Git 对象库无凭证；这些引用不在公开分支，没有推送，本轮也未删除或改写工具快照。仅显式推送 main，不能镜像推送或直接共享整个 `.git`。详见[安全检查摘要](../reports/task05b/security-summary.json)。
