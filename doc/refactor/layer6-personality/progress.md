# Layer 6: Personality / Session / 记忆绑定 — 进度

## 状态

未开始。

## 已完成

- [x] 设计文档（README.md）

## 待完成

### Step 1：强制 session_id = role_id
- [ ] Repository 强制 session_id 来自 role_id
- [ ] SessionManager 不再允许创建非 role_id 的 session
- [ ] 数据库迁移合并现有 session

### Step 2：统一 Personality 管理
- [ ] 废弃根目录 `personality.json`
- [ ] `personalities/{role_id}.json` 成为唯一数据源
- [ ] `PersonalityManager` 实现

### Step 3：情绪状态绑定
- [ ] `EmotionalState` 持久化到 personality 文件
- [ ] 运行时从 RoleSession 读取/写回

### Step 4：睡眠状态绑定
- [ ] `.sleep_state.{role_id}` 按 role_id 命名
- [ ] 睡眠状态纳入 RoleSession

### Step 5：多角色验证
- [ ] 创建测试角色验证隔离
- [ ] 切换角色不串数据

## 阻塞项

- 需要先明确多角色产品形态（是否允许同角色多 session）
