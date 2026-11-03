# TASK 07 — M8 受限范围验收

用户审核决定暂缓在线自然语言同名多轮自动消歧与仅原时间定位跨午夜修改，不再调整Prompt或调用真实模型。
TASK06/06B代码、测试和真实失败账本保留。删除任务独立追踪：[#7](https://github.com/re-tourist/Personal-Productivity-Agent/issues/7)；
复杂定位：[#8](https://github.com/re-tourist/Personal-Productivity-Agent/issues/8)。M8仍Open。

在线Qwen路径增加保守选择门槛：没有明确ID时，必须在当前消息中存在实际标题且仅匹配一个任务；
同名任务不能再靠模型原时间推断排除候选，纯时间定位及不可靠指代要求明确Task ID。
明确ID后仍需参数验证、人工批准、版本检查与业务状态核验。无效数字时钟不能进入审批。
既有确定性离线解析与失败回放继续保留，不把它们说成真实模型已通过的复杂语义能力。

tests/test_task07_scope.py 用模拟在线抽取器回放同名、纯时间、虚构标题、无效时钟和明确ID请求，
断言不可靠目标无审批、无写入，明确ID完成操作仍可用。不是收费模型调用。

本机Python3.12完整118 passed，0 failed/errors/warnings；M7离线10/10；修改文件Ruff通过。
原事务、HTTP异常/对账、版本冲突、重复确认、迁移及恢复测试均保留并通过。
本轮真实模型调用0次、费用0元。PR #6需本次提交的Linux CI成功后才Ready/合并，保留旧失败事实，不虚报M8整体完成。

M9将从合并后的main建立独立分支/PR；M9完成后不自动合并或关闭Milestone。
