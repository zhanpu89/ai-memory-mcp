# 记忆丰富

任务执行过程中，实时沉淀关键信息到记忆库，避免信息丢失。

## 触发条件

任务执行中，以下事件发生时主动记录：

1. **关键技术决策**：选择了某个框架/库/架构方案，或放弃了某个替代方案
2. **非平凡 Bug 修复**：解决了非显而易见的问题，值得未来参考
3. **任务状态变更**：从 `in_progress` 变为 `blocked`，或发现了新的依赖
4. **里程碑达成**：完成了子任务的重要阶段

## Session ID 获取

使用任务开始时生成的 session_id。若当前尚未生成，按以下格式生成：

```
session_id = "session-{YYYYMMDD}-{task_slug}"
```

- date: YYYYMMDD 格式
- task_slug: 从当前任务标题提取核心关键词，连字符连接，不超过 30 字符
- 示例: `session-20260419-optimize-memory-skill`

## 决策记录

当识别到关键技术决策时，调用 `add_decision`：

```
add_decision(
  session_id = 当前会话ID,
  decision_type = 决策类型,
  description = 决策内容,
  reasoning = 选择理由（包含被放弃的替代方案及原因）
)
```

**参数验证规则**：
- `session_id` 和 `description` 不能为空

**响应格式**：
- 成功：`{"success": True, "message": "决策添加成功"}`
- 失败：`{"success": False, "message": "错误原因"}`

### 决策类型参考值

| decision_type | 说明 | 示例 |
|---------------|------|------|
| `architecture` | 架构设计决策 | 选择微服务而非单体架构 |
| `tech-choice` | 技术选型决策 | 选择 SQLite 而非 PostgreSQL |
| `bug-fix` | Bug 修复策略 | 通过重建索引而非清空数据修复 |
| `refactor` | 重构方案 | 提取公共模块而非复制代码 |
| `performance` | 性能优化方案 | 使用连接池替代每次新建连接 |
| `security` | 安全相关决策 | 使用参数化查询防止 SQL 注入 |
| `trade-off` | 权衡取舍 | 牺牲实时性换取数据一致性 |

reasoning 字段应包含：为什么选择此方案、被放弃的替代方案是什么、放弃的原因是什么。这些信息在未来遇到类似决策时极具参考价值。

## 状态更新

当任务状态发生重大变化时，调用 `update_summary`：

```
update_summary(
  session_id = 当前会话ID,
  new_status = 新状态,
  updated_content = 更新后的摘要内容（如有实质性变更）
)
```

**参数验证规则**：
- `session_id` 不能为空
- `new_status` 和 `updated_content` 至少提供其中之一
- `new_status` 必须是五种有效状态之一

**响应格式**：
- 成功：`{"success": True, "message": "摘要更新成功"}`
- 失败：`{"success": False, "message": "错误原因"}`

仅在状态发生实质性变化时更新，避免频繁调用。每次更新应反映真正的进展，而非微小的变动。

## 注意事项

- 决策记录应在决策发生时立即执行，不要等到任务结束再补录
- 一个会话中可能产生多条决策记录，每条独立调用 `add_decision`
