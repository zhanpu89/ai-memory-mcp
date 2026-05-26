# 弱模型专用规则（精简版）

> 替代 SKILL.md 的简化版本，供 Qwen/Doubao/Kimi 等弱模型使用。
> 规则无可选分支，每条必须执行。

---

## 规则 1：会话必须先加载记忆

每次对话开始，**第一步**：
1. 查找 `.project_name` 文件 → 得到 `project_name`
2. 查看 `.git/HEAD` 文件 → 得到 `branch_name`
3. 调用 prompt `memory-start-session`（或者工具 `init_session`）

**禁止**：做完上述之前回答任何问题。

---

## 规则 2：遇到报错必须先搜历史

用户遇到报错、配置问题、架构讨论时：
1. 调用 prompt `memory-search-error`（或者工具 `search_summaries`）
2. 有结果就引用历史方案，没有结果再自己推理

**禁止**：不搜历史直接回答。

---

## 规则 3：完成任务必须保存

以下节点主动问用户"是否保存摘要"：
- 修复 Bug、完成功能、重构完毕、解决环境问题
- 用户说"今天到这"

确认后调用 prompt `memory-save-task`（或者工具 `save_summary`）

---

## 规则 4：保存摘要必须填全字段

| 字段 | 必须 | 格式 |
|------|------|------|
| `session_id` | 是 | `session-YYYYMMDD-描述` |
| `file_paths` | 是 | 逗号分隔 |
| `next_steps` | 是 | 具体可执行的下一步 |
| `tags` | 是 | `技术栈,模块,类型,特征` |
| `status` | 是 | 只能用 `completed/in_progress/blocked/abandoned/pending` |

---

## 工具速查

| 工具/prompt | 什么时候用 |
|-------------|-----------|
| `memory-start-session` | 【每次会话开始】必调第一条 |
| `init_session` | 如果上面那个不行，用这个代替 |
| `memory-search-error` | 遇到报错、搜历史方案 |
| `search_summaries(query=...)` | 如果上面那个不行，用这个代替 |
| `memory-save-task` | 用户确认保存后，用它自动组织格式 |
| `save_summary(...)` | 如果上面那个不行，用这个代替 |
| `add_decision(...)` | 做了技术选型、架构决定时立即调用 |
