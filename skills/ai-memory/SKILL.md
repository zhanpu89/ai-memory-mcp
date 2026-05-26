---
name: ai-memory
description: >
  AI 记忆持久化管理——会话启动时恢复上下文、任务执行中记录决策、任务结束时保存摘要。
  当用户提到"加载记忆"、"恢复上下文"、"继续上次"、"保存记忆"、"生成摘要"、
  "搜索记忆"、"上次做到哪了"时触发。会话启动、项目切换时自动触发。
  遇到复杂问题需参考历史经验时也应触发。单纯的技术问答、代码解释不需要触发。
allowed-tools: mcp__ai_memory__*
---

# AI 记忆管理

管理 AI 助手的持久化记忆，覆盖四个阶段。每个阶段有独立的参考文件，仅在对应场景触发时加载。

## 阶段路由

根据当前场景，判断进入哪个阶段，然后读取对应的参考文件执行：

| 阶段 | 触发场景 | 参考文件 | 核心工具 |
|------|----------|----------|----------|
| 记忆加载 | 会话启动、项目切换、用户说"加载记忆/恢复上下文/继续上次" | `references/memory-load.md` | `init_session`, `get_summary_by_id`, `list_recent_sessions` |
| 记忆丰富 | 任务执行中发现关键决策、Bug 修复、状态变更 | `references/memory-enrich.md` | `add_decision`, `update_summary` |
| 记忆保存 | 任务结束、用户说"生成摘要/保存记忆"、里程碑达成 | `references/memory-save.md` | `save_summary`, `add_decision` |
| 记忆检索 | 遇到 Bug、技术选型、架构设计、用户提到历史任务 | `references/memory-search.md` | `search_summaries`, `search_summaries_fts`, `get_summary_by_id` |

**读取规则**：只加载当前阶段对应的参考文件，不要一次性读取全部。

## 公共前置：项目上下文识别

所有阶段在首次调用 MCP 工具前，都必须执行以下步骤：

### 步骤 1：定位项目根目录

从当前工作目录开始，向上查找 `.project_name` 文件，最多查找 2 层：
- 第 1 层：当前目录
- 第 2 层：父目录

找到后，该目录即为"项目根目录"。如果 2 层内均未找到，报错并提示用户在项目根目录（通常在 `src/` 同级或上级）创建 `.project_name` 文件。

### 步骤 2：读取 project_name

1. 读取项目根目录下的 `.project_name` 文件
2. 去除首尾空白字符，忽略空行和注释行（`#` 开头）
3. 取第一行有效内容作为 `project_name`
4. 如果文件不存在或内容为空：
   - 向用户提示："检测到当前项目缺少 `.project_name` 文件，请在项目根目录创建该文件，内容为一行项目名称（例如：`my-awesome-project`）"
   - 暂停执行，等待用户确认已创建
   - 用户确认后重新读取

### 步骤 3：读取 branch_name

1. 检查项目根目录是否存在 `.git` 目录
2. 存在：读取 `.git/HEAD` 提取分支名（如 `ref: refs/heads/main` → `main`）
3. 不存在：标记 `branch_name = "no-vcs"`

### 缓存机制

首次读取后，在会话上下文中记录当前 `project_name` 和 `branch_name`，后续工具调用直接引用这两个值，不重复读取文件。用户明确说"切换项目"时，重新执行上述步骤。

## Session ID 管理

- **生成时机**：任务开始时生成，格式为 `session-{YYYYMMDD}-{task_slug}`
- **复用规则**：同一任务的所有操作（保存、丰富、更新）使用同一 session_id
- **里程碑保存**：不生成新 ID，复用现有 ID，仅更新 status

## 状态值约束（严格遵守）

所有涉及 `status` 字段的操作，**必须且只能使用**以下五种状态值：

| 状态值 | 含义 | 使用场景 |
|--------|------|----------|
| `completed` | 已完成 | 任务所有目标已达成 |
| `in_progress` | 进行中 | 任务正在执行，或里程碑保存 |
| `pending` | 待处理 | 任务已计划但尚未开始 |
| `blocked` | 被阻塞 | 任务需要外部依赖或决策才能继续 |
| `abandoned` | 已放弃 | 任务确定不再继续 |

**禁止使用任何其他状态值**（如 `pending_review`、`waiting`、`paused` 等）。如需表达更复杂的状态，请在 `summary_content` 中用文字描述。

## 上下文窗口预算

记忆加载时控制 Token 占用，默认 L0，按需升级：

| 层级 | 触发条件 | 加载内容 | 预估 Token |
|------|----------|----------|-----------|
| L0 | 会话启动（默认） | `init_session` 返回的标题+下一步 | ~100-200 |
| L1 | 用户选择继续某任务 | `get_summary_by_id` 完整摘要 | ~500-1000 |
| L2 | 遇到复杂问题需历史参考 | `search_summaries(use_vector=True)` 3条 | ~1500-3000 |
| L3 | 用户明确要求完整回顾 | `list_recent_sessions` + 逐条详情 | ~3000+ |

每次升级前评估：加载的信息是否直接有助于当前任务？

## 周期性操作

- **周报**：用户说"生成本周周报/本周总结" → `weekly_review(project_name, branch_name)`
- **维护**：用户说"维护数据库/优化记忆库" → `maintenance()`

## 工具速查

| 工具 | 用途 | 响应格式 | 时机 |
|------|------|----------|------|
| `init_session` | 恢复进行中任务上下文 | `{"success": True, "data": [...], "message": "..."}` | 会话启动 |
| `search_summaries` | 多策略检索（LIKE/FTS/向量） | `{"success": True, "data": [...]}` | 需要历史经验 |
| `search_summaries_fts` | FTS5 专用全文检索 | `{"success": True, "data": [...]}` | 精确关键词 |
| `get_summary_by_id` | 获取单条完整摘要 | `{"success": True, "data": {...}}` 或 `{"success": False, "message": "..."}` | 深入查看 |
| `list_recent_sessions` | 列出最近会话 | `{"success": True, "data": [...]}` | 浏览近期任务 |
| `save_summary` | 保存新摘要 | `{"success": True, "message": "..."}` | 任务结束/里程碑 |
| `update_summary` | 更新摘要状态或内容 | `{"success": True, "message": "..."}` | 状态变更 |
| `add_decision` | 记录关键决策 | `{"success": True, "message": "..."}` | 发现重要决策 |
| `weekly_review` | 生成周报 | `{"success": True, "data": {"report": "..."}}` | 用户请求 |
| `maintenance` | 数据库维护 | `{"success": True, "message": "..."}` | 用户请求 |

## 统一响应格式规范

所有 MCP 工具均遵循统一的响应格式：

### 成功响应
```
{"success": True, "data": <结果数据>, "message": "<可选描述>"}
```

### 失败响应
```
{"success": False, "message": "<错误原因>"}
```

### 关键规则
1. **始终检查 `success` 字段**：调用任何工具后，先检查 `success` 是否为 `True`
2. **数据在 `data` 字段中**：成功时，结果数据在 `data` 字段中（而非顶层）
3. **错误信息在 `message` 字段中**：失败时，错误原因在 `message` 字段中
4. **输入验证**：工具会验证必填参数，调用前确保参数不为空

## 核心原则

1. **按需加载**：默认 L0 轻量，仅在必要时逐级升级
2. **实时沉淀**：重要决策在发生时立即记录，不等到任务结束
3. **语义优先**：检索时优先 `use_vector=True`，其次 FTS5，最后 LIKE
4. **标签一致性**：使用项目内统一的标签体系，确保跨会话可检索
5. **上下文预算**：每次加载记忆评估 Token 占用，避免信息过载
6. **闭环确认**：保存前必须向用户确认，确保摘要质量
