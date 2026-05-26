# 记忆检索

任务执行过程中，按需检索历史记忆以辅助当前决策。

## 触发条件

以下场景应主动检索历史记忆：

1. **遇到 Bug 或错误**：检索是否曾遇到类似问题及解决方案
2. **技术选型**：检索项目中是否有相关技术决策记录
3. **架构设计**：检索是否有类似模块的设计经验
4. **用户提到历史任务**：检索相关会话摘要
5. **重复模式识别**：发现当前操作与历史经验相关

### 编码场景强制触发（优先级最高）

**规则：遇到以下编码信号时，必须先检索历史再回答，禁止直接推理。**

| 编码信号 | 示例 | 检索策略 |
|---------|------|---------|
| **Python/Node 异常** | `AttributeError`, `TypeError`, `ENOENT` | FTS5 精确匹配错误类型 |
| **构建/环境报错** | `docker build failed`, `pip install error` | FTS5 + 错误关键词 |
| **依赖/版本冲突** | `chromadb >= 0.4`, `peer dependency` | FTS5 + 包名+版本号 |
| **配置问题** | `Dockerfile cache`, `.env missing` | FTS5 + 配置文件名 |
| **性能/优化问题** | "构建太慢", "查询很慢" | 向量语义搜索 + 性能关键词 |
| **询问工具/库用法** | "chromadb 怎么用", "fastmcp 示例" | FTS5 + 工具名 |
| **提到历史功能** | "上次的缓存优化", "之前的重构" | 向量语义搜索 + 功能描述 |

**执行流程**（两阶段检索）：
```
# 阶段1：精确匹配（速度快，适合报错信息）
search_summaries_fts(query="错误关键词", project_name=..., limit=3)

# 阶段2：若未命中，语义搜索（覆盖面广）
if len(results) == 0:
    search_summaries(query="问题自然语言描述", use_vector=True, project_name=..., limit=3)
```

## 检索策略

根据场景选择最优检索方式：

### 场景 1：精确关键词查找

```
search_summaries(query=关键词, use_fts=True, limit=3)
```

**响应格式**：`{"success": True, "data": [...]}` 或 `{"success": False, "message": "..."}`

适用于：已知确切术语、文件名、模块名。

### 场景 2：语义相似度搜索（推荐默认）

```
search_summaries(query=自然语言描述, use_vector=True, limit=3)
```

**响应格式**：`{"success": True, "data": [...]}` 或 `{"success": False, "message": "..."}`

适用于：模糊概念、问题描述、经验查找。向量检索能理解语义相似性，即使措辞不同也能找到相关记录。

### 场景 3：按标签/模块筛选

```
search_summaries(tags=标签, module=模块名, limit=5)
```

**响应格式**：`{"success": True, "data": [...]}`

适用于：浏览特定类别的历史记录。

### 场景 4：按项目+分支精确查找

```
search_summaries(project_name=项目名, branch_name=分支名, status=状态, limit=5)
```

**响应格式**：`{"success": True, "data": [...]}`

适用于：查看特定项目分支的任务历史。

### 场景 5：获取完整详情

```
get_summary_by_id(session_id)
```

**响应格式**：`{"success": True, "data": {...摘要对象...}}` 或 `{"success": False, "message": "..."}`

适用于：从检索结果中获取某条摘要的完整内容。通常在场景 1-4 返回摘要列表后，选择最相关的一条深入查看。

### 场景 6：FTS5 全文检索

```
search_summaries_fts(query, project_name, branch_name, status, limit=10)
```

**参数验证**：`query` 不能为空

**响应格式**：`{"success": True, "data": [...]}` 或 `{"success": False, "message": "..."}`

适用于：需要精确全文匹配的场景。

## 检索优先级

向量语义搜索 > FTS5 全文检索 > LIKE 模糊匹配

优先使用 `use_vector=True`，因为向量检索能理解语义相似性，即使措辞不同也能匹配。FTS5 适合精确术语匹配，LIKE 仅作为最后的降级方案。

## 检索结果处理

### 命中时

- 提取与当前任务直接相关的信息
- 向用户简要说明参考了哪条历史记录
- 格式："根据历史经验（{task_title}），{关键信息摘要}"

### 未命中时

- 不提及检索行为，避免干扰
- 正常继续当前任务

### 矛盾信息时

- 向用户指出矛盾点
- 展示不同时期的决策及理由
- 请用户确认以哪个为准
