# 记忆保存

任务结束或里程碑达成时，生成结构化摘要并持久化到记忆库。

## 触发条件

以下任一条件满足时执行：

1. **用户明确请求**：说"生成摘要"、"总结本次会话"、"保存记忆"
2. **任务自然结束**：用户确认任务完成，或所有待办事项已清空
3. **里程碑节点**：复杂任务的重要阶段完成（此时 status 设为 `in_progress`）
4. **会话即将结束**：检测到对话即将终止（如用户说"今天就到这里"）

## 保存流程

### 第一步：获取项目上下文

使用已缓存的 `project_name` 和 `branch_name`（首次调用时由"公共前置：项目上下文识别"流程获取）。

### 第二步：确认 session_id

使用任务开始时生成的 session_id。若当前任务尚未生成 session_id，按以下格式生成：

```
session_id = "session-{YYYYMMDD}-{task_slug}"
```

- date: YYYYMMDD 格式
- task_slug: 从 task_title 提取核心关键词，连字符连接，不超过 30 字符
- 示例: `session-20260419-optimize-memory-skill`

### 第三步：分析对话历史

回顾本次会话，提炼：

- **核心任务目标**：一句话描述本次任务要达成什么
- **关键技术决策及理由**：每个决策包含选择和放弃的替代方案
- **非平凡问题及解决方案**：值得未来参考的问题解决经验
- **修改或新增的文件列表**：精确到文件路径
- **当前任务完成状态**：必须使用以下五种状态之一：
  - `completed`：任务已完成，所有目标达成
  - `in_progress`：任务进行中，里程碑保存时使用
  - `pending`：任务已计划但尚未开始
  - `blocked`：任务被阻塞，需要外部依赖或决策
  - `abandoned`：任务已放弃，不再继续
- **明确的下一步行动计划**：具体可执行，而非模糊描述

### 第四步：质量检查

逐项检查，全部通过后才可保存：

- [ ] 包含至少一项**技术决策**及其理由
- [ ] 列出**至少一个**具体的文件路径
- [ ] 下一步计划**具体可执行**（非模糊描述）
- [ ] 项目上下文已识别（project_name、branch_name）
- [ ] 摘要内容足够详细，能生成有意义的向量 Embedding
- [ ] tags 包含有检索价值的标签（技术栈、模块名、问题类型）

若未满足，重新审视对话并补充缺失内容。

### 第五步：构建标签

按四个维度生成标签：

```
tags = "{技术栈},{模块},{问题类型},{项目特征}"
```

| 维度 | 示例 | 规则 |
|------|------|------|
| 技术栈 | python, react, sqlite, chromadb | 核心技术 |
| 模块 | auth, api, database, ui | 涉及模块 |
| 问题类型 | bug-fix, refactor, optimization, feature | 变更性质 |
| 项目特征 | mcp, vector-search, full-text-search | 项目标签 |

规则：至少 2 个标签，推荐 3-5 个；优先使用项目已有标签保持一致性；英文小写连字符分隔；避免过于宽泛（如 code, fix, update）。

### 第六步：构建摘要内容

使用以下模板：

```markdown
# 任务摘要：{task_title}

## 项目信息
- **项目名称**: {project_name}
- **分支名称**: {branch_name}

## 核心目标
{核心目标描述}

## 关键技术决策
- **{决策1}**: {理由}（替代方案: {被放弃的方案}，原因: {放弃原因}）
- **{决策2}**: {理由}

## 主要问题与解决方案
- **问题**: {问题描述}
  **解决**: {解决方案}
  **根因**: {根本原因，如有}

## 涉及文件清单
- `{file_path_1}` — {变更说明}
- `{file_path_2}` — {变更说明}

## 下一步计划
1. {具体可执行的步骤1}
2. {具体可执行的步骤2}
```

### 第七步：向用户确认

**在调用保存工具前**，展示预览并请求确认：

```
我已生成以下摘要内容，请确认是否保存：

📌 {task_title}
- 项目：{project_name} / {branch_name}
- 状态：{status}
- 文件：{file_count} 个
- 决策：{decision_count} 项
- 标签：{tags}

[确认保存 / 修改内容 / 取消]
```

只有用户明确确认后，才调用 MCP 工具保存。

### 第八步：调用 MCP 工具存储

```
save_summary(
  session_id, task_title, summary_content, status,
  next_steps, tags, module, file_paths,
  project_name, branch_name
)
```

**参数验证规则**（调用前确保）：
- `session_id`、`task_title`、`summary_content` 均不能为空
- `status` 必须是以下五种之一：`completed`, `in_progress`, `pending`, `blocked`, `abandoned`

**响应格式**：
- 成功：`{"success": True, "message": "摘要保存成功"}`
- 失败：`{"success": False, "message": "错误原因"}`

对于未在记忆丰富阶段记录的重要技术决策，额外调用 `add_decision()` 逐条补充。
- **add_decision 响应格式**：`{"success": True, "message": "决策添加成功"}` 或 `{"success": False, "message": "..."}`

如果是里程碑保存（status=in_progress），提示用户："已保存里程碑摘要。下次会话启动时可自动恢复此上下文。"

### 第九步：完成确认

```
✅ 摘要已保存 (session_id: {session_id})

💡 提示：
- 下次新会话启动时，可说"加载记忆"恢复上下文
- 遇到类似问题时，系统会自动检索相关历史经验
- 可随时说"搜索记忆: {关键词}"查找特定历史记录
```
