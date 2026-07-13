# 修复 Proactive 循环访问 WebAgent.last_activity_time 报错

## 问题
WebSocket 连接建立后，proactive 循环立即报错：

```
Proactive error: 'WebAgent' object has no attribute 'last_activity_time'
```

原因是 `web/server.py` 中的 proactive / sleep / message 处理代码直接读写 `agent.last_activity_time`，但 `WebAgent` 类只暴露了 `last_activity` property，没有同名属性。

## 改动
- `web/session.py`
  - 为 `WebAgent` 新增 `last_activity_time` property（getter/setter），代理到内部的 `self.agent.last_activity_time`。
  - 保留原有的 `last_activity` property 以兼容 `SessionManager.cleanup_old()` 等调用点。

## 效果
proactive 循环可以正常读取空闲时间、更新活动时间，主动消息和睡眠唤醒逻辑恢复正常。

## 验证
- `python -m py_compile web/session.py web/server.py` 通过。
- 重启服务后 WebSocket 初始化不再出现 `Proactive error: 'WebAgent' object has no attribute 'last_activity_time'`。
