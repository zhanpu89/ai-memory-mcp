# AI Memory MCP — Tool Reference

> Complete schema reference for all 10 MCP tools exposed by `ai-memory-mcp`.
> Tool names follow the `ai_memory_<action>_<resource>` convention.

---

## Table of Contents

| Tool | Type | Description |
|---|---|---|
| [`save_summary`](#save_summary) | ✏️ Write | Persist a new session summary |
| [`update_summary`](#update_summary) | ✏️ Write | Update status or content of an existing summary |
| [`add_decision`](#add_decision) | ✏️ Write | Record a key technical decision for a session |
| [`maintenance`](#maintenance) | 🔧 Admin | Rebuild FTS index, VACUUM database, persist vectors |
| [`search_summaries`](#search_summaries) | 🔍 Read | Multi-mode search (keyword / FTS5 / vector) |
| [`search_summaries_fts`](#search_summaries_fts) | 🔍 Read | Full-text search via SQLite FTS5 |
| [`get_summary_by_id`](#get_summary_by_id) | 🔍 Read | Retrieve a single summary by session ID |
| [`list_recent_sessions`](#list_recent_sessions) | 🔍 Read | List most-recent sessions, newest first |
| [`init_session`](#init_session) | 🔍 Read | Restore context — returns in-progress tasks from last 3 days |
| [`weekly_review`](#weekly_review) | 🔍 Read | Generate a Markdown weekly-report for the current week |

---

## Common Response Envelope

Every tool returns a JSON object with this shape:

```json
{
  "success": true,
  "message": "操作成功",
  "data": { ... }
}
```

| Field | Type | Always present | Description |
|---|---|---|---|
| `success` | `boolean` | ✅ | `true` = ok, `false` = error |
| `message` | `string` | ✅ | Human-readable status / error text |
| `data` | `any` | conditional | Present on read tools; absent on pure write tools |

On error, only `success` and `message` are returned:

```json
{ "success": false, "message": "session_id 'x' 已存在，如需更新请使用 update_summary" }
```

---

## Session Summary Object

All read tools return one or more **Session Summary** objects:

```json
{
  "id":              1,
  "session_id":      "2024-01-15-feature-auth",
  "timestamp":       "2024-01-15 10:30:00",
  "task_title":      "实现用户认证模块",
  "status":          "completed",
  "summary_content": "完成了 JWT 认证流程，包括登录、刷新和登出接口...",
  "next_steps":      "编写单元测试，覆盖边界情况",
  "tags":            "auth,jwt,backend",
  "module":          "auth",
  "file_paths":      "src/auth/jwt.py,src/auth/views.py",
  "project_name":    "my-project",
  "branch_name":     "feature/auth",
  "created_at":      "2024-01-15 10:30:00",
  "updated_at":      "2024-01-15 11:00:00"
}
```

**Valid `status` values:** `completed` · `in_progress` · `blocked` · `abandoned` · `pending`

---

## Tools

### `save_summary`

Persist a **new** session summary. Fails if `session_id` already exists — use [`update_summary`](#update_summary) to modify.

**Annotations:** `readOnlyHint=false` · `destructiveHint=false` · `idempotentHint=false`

#### Parameters

| Name | Type | Required | Description |
|---|---|---|---|
| `session_id` | `string` | ✅ | Unique ID for the session (e.g. `"2024-01-15-feat-auth"`) |
| `task_title` | `string` | ✅ | Short title describing the task |
| `summary_content` | `string` | ✅ | Detailed summary of what was done |
| `status` | `string` | — | One of the valid status values. Default: `"completed"` |
| `next_steps` | `string` | — | Follow-up actions |
| `tags` | `string` | — | Comma-separated tags (e.g. `"auth,jwt"`) |
| `module` | `string` | — | Module or component name |
| `file_paths` | `string` | — | Comma-separated file paths touched |
| `project_name` | `string` | — | Project identifier |
| `branch_name` | `string` | — | Git branch name |

#### Example

```json
{
  "session_id":      "2024-01-15-feat-auth",
  "task_title":      "实现用户认证模块",
  "summary_content": "完成 JWT 登录/刷新/登出接口，通过所有单元测试",
  "status":          "completed",
  "tags":            "auth,jwt",
  "module":          "auth",
  "project_name":    "my-project",
  "branch_name":     "feature/auth"
}
```

#### Response

```json
{ "success": true, "message": "摘要保存成功" }
```

---

### `update_summary`

Update the **status** and/or **content** of an existing summary. At least one of `new_status` or `updated_content` must be supplied. Also syncs the FTS5 index when content changes.

**Annotations:** `readOnlyHint=false` · `destructiveHint=false` · `idempotentHint=true`

#### Parameters

| Name | Type | Required | Description |
|---|---|---|---|
| `session_id` | `string` | ✅ | ID of the summary to update |
| `new_status` | `string` | — | New status value |
| `updated_content` | `string` | — | Replacement summary content |

#### Example

```json
{ "session_id": "2024-01-15-feat-auth", "new_status": "completed" }
```

#### Response

```json
{ "success": true, "message": "摘要更新成功" }
```

---

### `add_decision`

Attach a **key technical decision** to an existing session.

**Annotations:** `readOnlyHint=false` · `destructiveHint=false` · `idempotentHint=false`

#### Parameters

| Name | Type | Required | Description |
|---|---|---|---|
| `session_id` | `string` | ✅ | Session to attach the decision to |
| `decision_type` | `string` | ✅ | Category (e.g. `tech_stack`, `api_design`, `architecture`) |
| `description` | `string` | ✅ | What was decided |
| `reasoning` | `string` | — | Why this decision was made |

#### Example

```json
{
  "session_id":    "2024-01-15-feat-auth",
  "decision_type": "tech_stack",
  "description":   "选择 PyJWT 而非 python-jose",
  "reasoning":     "PyJWT 更轻量，社区更活跃，无依赖冲突"
}
```

#### Response

```json
{ "success": true, "message": "决策添加成功" }
```

---

### `maintenance`

Rebuild the FTS5 full-text index, run `VACUUM` to reclaim disk space, and persist the vector store. Call periodically (e.g. weekly) or after bulk imports.

**Annotations:** `readOnlyHint=false` · `destructiveHint=false` · `idempotentHint=true`

#### Parameters

_None_

#### Response

```json
{ "success": true, "message": "数据库维护完成" }
```

---

### `search_summaries`

Flexible multi-mode search. Supports plain keyword, FTS5 full-text, and semantic vector search — controlled via `use_fts` and `use_vector` flags.

**Annotations:** `readOnlyHint=true` · `idempotentHint=true`

#### Parameters

| Name | Type | Required | Description |
|---|---|---|---|
| `query` | `string` | — | Search keywords |
| `tags` | `string` | — | Tag filter (fuzzy match) |
| `module` | `string` | — | Module filter (fuzzy match) |
| `status` | `string` | — | Status filter (exact match) |
| `project_name` | `string` | — | Project filter (exact match) |
| `branch_name` | `string` | — | Branch filter (exact match) |
| `use_fts` | `boolean` | — | Use FTS5 full-text index (requires `query`). Default: `false` |
| `use_vector` | `boolean` | — | Use semantic vector search (requires `query` + vector deps). Default: `false` |
| `limit` | `integer` | — | Max results. Default: `10` |

#### Search Mode Decision Guide

| Goal | Recommended flags |
|---|---|
| Find by exact keyword | `use_fts=true` |
| Find semantically similar content | `use_vector=true` |
| Filter by project/branch/status | all flags `false`, use filter params |
| Combined filter + keyword | `use_fts=false`, set `query` + filter params |

#### Response

```json
{
  "success": true,
  "message": "操作成功",
  "data": [ { ...SessionSummary }, ... ]
}
```

---

### `search_summaries_fts`

Dedicated FTS5 full-text search. Supports SQLite FTS5 query syntax (e.g. `"jwt" OR "oauth"`, `auth*`).

**Annotations:** `readOnlyHint=true` · `idempotentHint=true`

#### Parameters

| Name | Type | Required | Description |
|---|---|---|---|
| `query` | `string` | ✅ | FTS5 query string |
| `project_name` | `string` | — | Project filter |
| `branch_name` | `string` | — | Branch filter |
| `status` | `string` | — | Status filter |
| `limit` | `integer` | — | Max results. Default: `10` |

#### Example

```json
{ "query": "jwt authentication", "project_name": "my-project", "limit": 5 }
```

---

### `get_summary_by_id`

Exact lookup of a single session by its `session_id`.

**Annotations:** `readOnlyHint=true` · `idempotentHint=true`

#### Parameters

| Name | Type | Required | Description |
|---|---|---|---|
| `session_id` | `string` | ✅ | Exact session ID |

#### Response

```json
{
  "success": true,
  "message": "操作成功",
  "data": { ...SessionSummary }
}
```

---

### `list_recent_sessions`

Return sessions ordered by `created_at DESC`, with optional project/branch filters.

**Annotations:** `readOnlyHint=true` · `idempotentHint=true`

#### Parameters

| Name | Type | Required | Description |
|---|---|---|---|
| `limit` | `integer` | — | Max results. Default: `10` |
| `project_name` | `string` | — | Project filter |
| `branch_name` | `string` | — | Branch filter |

---

### `init_session`

**Call at the start of every AI session.** Returns up to 3 `in_progress` tasks created within the last 3 days, plus a `prompt` string ready to paste into the conversation to restore context.

**Annotations:** `readOnlyHint=true` · `idempotentHint=true`

#### Parameters

| Name | Type | Required | Description |
|---|---|---|---|
| `project_name` | `string` | — | Filter to a specific project |
| `branch_name` | `string` | — | Filter to a specific branch |

#### Response

```json
{
  "success": true,
  "message": "找到 2 个最近的进行中任务",
  "data": [ { ...SessionSummary }, ... ],
  "prompt": "上次我们有以下进行中的任务：\n1. 实现用户认证模块 - 下一步: 编写单元测试\n\n要继续处理这些任务中的哪一个？"
}
```

> **Integration tip:** Pass the `prompt` value directly into your system prompt or first user message to seamlessly resume prior work.

---

### `weekly_review`

Generate a **Markdown weekly report** for the current calendar week, covering completed tasks, key decisions, risks, and next steps.

**Annotations:** `readOnlyHint=true` · `idempotentHint=true`

#### Parameters

| Name | Type | Required | Description |
|---|---|---|---|
| `project_name` | `string` | — | Filter to a specific project |
| `branch_name` | `string` | — | Filter to a specific branch |

#### Response

```json
{
  "success": true,
  "message": "周报生成成功",
  "data": {
    "report": "# 项目周报 (2024-01-15 00:00:00 至 2024-01-19)\n\n## 本周完成的功能\n..."
  }
}
```

---

## Recommended Workflow for AI Agents

```
Session Start
  └─► init_session(project_name="my-project")
        → receive task list + prompt, inject into context

During Work
  ├─► save_summary(session_id, task_title, summary_content, status="in_progress", ...)
  └─► add_decision(session_id, decision_type, description, reasoning)

Task Complete
  └─► update_summary(session_id, new_status="completed")

Search Past Work
  ├─► search_summaries(query="...", use_vector=True)   ← semantic
  ├─► search_summaries_fts(query="jwt auth")           ← keyword
  └─► search_summaries(project_name="x", status="in_progress")  ← filter

Weekly
  └─► weekly_review(project_name="my-project")
```
