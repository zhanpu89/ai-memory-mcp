# AI Memory MCP — Tool Reference

> Complete schema reference for all 10 MCP tools exposed by `ai-memory-mcp`.
> Tool names follow the `ai_memory_<action>_<resource>` convention.
> Each tool's MCP description now includes **when-to-call, before-call and after-call guidance** — weaker models (Qwen/Doubao/Kimi) can follow these descriptions without reading external reference files.

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

> **New:** `save_summary` may also return `quality_warnings` — non-blocking hints about missing optional fields (file_paths, tags, next_steps, decisions) that improve future retrievability.

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

> **When to call:** Task complete, bug fix, refactor done, milestone reached, or session ending.
> **Before calling:** Ensure file_paths, next_steps, tags are filled. **Confirm with the user first.**
> **After calling:** Optionally call `add_decision` to document key technical choices.

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
{ "success": true, "message": "摘要保存成功", "quality_warnings": ["缺少 file_paths..."] }
```

> `quality_warnings` is an optional array field. It does not block the save, but guides the model to fill in missing info for better retrievability.

---

### `update_summary`

Update the **status** and/or **content** of an existing summary. At least one of `new_status` or `updated_content` must be supplied. Also syncs the FTS5 index when content changes.

> **When to call:** Task status changes (e.g. `in_progress → completed`), or summary content needs amending.
> **Before calling:** Ensure `session_id` already exists (created via `save_summary`).

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

> **When to call:** Immediately when a decision is made — tech choice, architecture design, bug root-cause, performance optimization, security decision.
> **Suggested `decision_type` values:** `architecture`, `tech_choice`, `bug_fix`, `refactor`, `performance`, `security`, `trade_off`.

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

> **When to call:** Weekly, after bulk import/delete, or on user request.

**Annotations:** `readOnlyHint=false` · `destructiveHint=false` · `idempotentHint=true`

#### Parameters

_None_

#### Response

```json
{ "success": true, "message": "数据库维护完成" }
```

---

### `search_summaries`

Flexible multi-mode search with **auto-fallback chain**. Default mode is FTS5 (fast, exact match). If FTS5 returns 0 results, automatically degrades to vector semantic search (if available), then to LIKE fuzzy match.

> **When to call:** Error/exception encountered, need to reference past work, user mentions "previously", discussing tool/library usage.
> **Calling tips:** Just pass `query` — the tool handles search strategy selection. No need to toggle `use_fts`/`use_vector` manually.

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
| `use_fts` | `boolean` | — | Use FTS5 full-text index. **Default: `true`** |
| `use_vector` | `boolean` | — | Use semantic vector search (requires vector deps). Default: `false` |
| `limit` | `integer` | — | Max results. Default: `10` |

#### Search Mode Decision Guide

| Goal | Recommended approach |
|---|---|
| Search anything (recommended) | Just pass `query` — auto fallback handles the rest |
| Exact error message / package name | Pass `query` (FTS5 default will match precisely) |
| Semantic similarity | Set `use_vector=true` for targeted semantic search |
| Filter-only (no keyword) | Set filter params only, leave `query` unset |

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

> **When to call:** Need precise FTS5 query syntax (AND/OR/NOT), or `search_summaries` default FTS5 is not enough.

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

> **When to call:** After `init_session` or `search_summaries` returns a relevant record; use this to get full context.

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

> **When to call:** User wants to review recent work, or browse recent tasks to pick which to continue.

**Annotations:** `readOnlyHint=true` · `idempotentHint=true`

#### Parameters

| Name | Type | Required | Description |
|---|---|---|---|
| `limit` | `integer` | — | Max results. Default: `10` |
| `project_name` | `string` | — | Project filter |
| `branch_name` | `string` | — | Branch filter |

---

### `init_session`

**Must-call-first tool at the start of every AI session.** Returns up to 3 `in_progress` tasks created within the last 3 days, plus a `prompt` string ready to paste into the conversation to restore context.

> **When to call:** Every new conversation, **before answering any coding question**. Also on project switch, or when user says "load memory / continue / restore".
> **Before calling:** First detect project context — find `.project_name` for `project_name`, read `.git/HEAD` for `branch_name`.
> **After calling:** Show results to user. If user picks a task, call `get_summary_by_id` for full context. For new tasks, generate session_id as `session-YYYYMMDD-task_slug`.

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

> **When to call:** User says "generate weekly report / weekly summary".

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
Session Start (MANDATORY — before ANY coding answer)
  1. Detect project context → get project_name, branch_name
  2. └─► init_session(project_name, branch_name)         ← FIRST tool call
  3. Show task list to user, ask which to continue

During Work (record decisions immediately)
  └─► add_decision(session_id, decision_type, description, reasoning)

Milestone / Task Complete (ask user before saving)
  └─► save_summary(session_id, task_title, summary, status="completed", ...)
       ↳ Quality check runs server-side; missing fields trigger warnings

Search Past Work (auto fallback handles strategy)
  └─► search_summaries(query="error message or description")
       ↳ FTS5 → vector → LIKE (no flag toggling needed)

Status Change
  └─► update_summary(session_id, new_status="completed")

Weekly
  └─► weekly_review(project_name="my-project")
```

> **Key changes for easier model adoption:**
> - `search_summaries` now defaults to FTS5 and auto-falls back through vector to LIKE — one call covers all scenarios
> - `save_summary` returns `quality_warnings` to guide the model without blocking
> - All tool descriptions embed when-to-call / before / after guidance — no external reference files needed for basic usage
