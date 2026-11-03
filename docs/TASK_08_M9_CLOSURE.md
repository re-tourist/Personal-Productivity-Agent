# TASK 08 — M9 身份降级风险收尾

基线3933a1b中风险真实存在：HTTPTaskStore首次验证后缓存identity_verified；在相同loopback地址/端口，
真实业务服务停止并重启为legacy模式时，同一客户端继续GET /tasks，未抛出BusinessUnavailable，
会按legacy身份读取合成的legacy数据。最小回归在修复前实际失败：`DID NOT RAISE BusinessUnavailable`。
只使用隔离合成任务，未访问个人库或泄露真实凭证。

最小修复：

- 删除身份已验证缓存，每次资源请求前重新GET /identity并核对认证模式及主体。
- 业务服务在legacy模式下拒绝携带Authorization的请求（401），不能静默降级为__legacy__。
  即使模式在预检GET与写入POST之间改变，也先拒绝、无副作用。
- 原无Bearer单用户客户端保持兼容；原演示API与Web行为保留。

`tests/test_task08_identity_downgrade.py`三个真实网络场景：

1. 同一客户端、同一URL真实重启为legacy后，读取/写入均拒绝；alice及legacy原数据不变。
2. legacy业务端的Bearer GET/POST均401且无写入；无Bearer演示创建仍成功。
3. 合成业务服务在identity预检后、POST前切换为legacy，写入仍被拒绝，两个owner的行数均0。

Windows第一次夹具对已知端口重复探测绑定遇到10013，改为让Uvicorn直接重启该端口后，
才获得业务风险的失败证据；没有修改宿主网络。测试保留原断言，未使用MockTransport。

复现/回归命令：

```powershell
.venv-py312/Scripts/python.exe -m pytest tests/test_task08_identity_downgrade.py -q
.venv-py312/Scripts/python.exe -m pytest -q
.venv-py312/Scripts/python.exe -m productivity_agent.evaluation --out reports/task08/m9-offline.json
```

定向3 passed；完整130 passed，0 failed/errors/warnings；M7离线10/10，修改文件Ruff及diff检查通过。最新Linux CI通过后才合并PR #9。M9仅按约定本地多用户测试范围验收，
不宣称生产认证、令牌生命周期、多Worker会话锁或公网安全完成。本轮真实Qwen调用0次，费用0元。
