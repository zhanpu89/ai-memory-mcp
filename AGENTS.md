# AI Memory MCP — Agent Guide

## Setup & dev commands
- Install: `pip install -e .` (or `pip install -e ".[dev]"` for pytest)
- Venv: `.venv/` exists; activate with `source .venv/bin/activate`
- Test: `pytest` (27 tests). Tests auto-create a tmp DB via `tmp_path` fixture + `AI_MEMORY_DISABLE_VECTOR=1`.
- Coverage: `pytest --cov=src/mcp_server --cov-report=term-missing`
- Run server: `ai-memory-mcp` (stdio mode), `ai-memory-mcp --http` (HTTP @ port 8000), or `python service.py start` (background daemon with PID/log mgmt).
- Web panel: `ai-memory-web` (FastAPI @ port 8080), reads same DB.
- Python >= 3.10. Requires `mcp>=1.6.0`, `python-dotenv>=1.0.0`.

## Architecture
- `src/mcp_server/server.py` — `AiMemoryMcpServer(FastMCP)` registers 10 MCP tools + 3 MCP Prompt templates
- `src/mcp_server/database.py` — SQLite CRUD with FTS5 full-text index, auto-migration on startup
- `src/mcp_server/vector_store.py` — ChromaDB + `all-MiniLM-L6-v2` (optional; ~500 MB model)
- `src/mcp_server/models.py` — Pydantic v2 input models for all tools
- CLI entrypoints in `pyproject.toml`: `ai-memory-mcp` / `ai-memory` → `mcp_server:main`; `ai-memory-web` → `web_panel:main`

## Web panel capabilities (ref: `web_panel/`)
- **Quality scoring**: 12-dimension engine (`web_panel/quality.py`): tags, module, file_paths, next_steps, project/branch, decisions, vector, **content_quality** (replaces simple length — detects tech entities via 15 regex patterns), title, status, **hit_frequency** (new), **cold_penalty** (new, -5 for completed + 90d untouched + 0 hits). Pass `hit_count`, `days_since_update`, and optional `decisions` (for reasoning-aware scoring) to `score_memory()`.
- **Bulk operations**: `/api/bulk` POST with `session_ids[]` + `action` (`status`/`tags`/`delete`). UI: checkbox select + bulk action bar in memories list.
- **Search misses**: `search_misses` DB table tracks zero-result queries. Displayed in Dashboard. API: `GET /api/search-misses`, `DELETE /api/search-misses?query=`.
- **Quality filter**: `?quality=needs_improvement` on `/memories` filters to quality < 50%. Cold memories link from Dashboard.
- **i18n**: locale files in `web_panel/locales/`. Add new keys to both `zh_CN.json` and `en_US.json`.

## Key conventions
- **Session ID format**: `session-YYYYMMDD-task_slug` (e.g., `session-20260528-fix-auth`). Generated at task start, reused within same task.
- **Task status** — only these 5 values: `completed`, `in_progress`, `blocked`, `abandoned`, `pending`
- **First tool call**: `init_session(project_name, branch_name)` — mandatory before answering any coding question. Project name from `.project_name` file, branch from `.git/HEAD`.
- **Auto-enrich on save**: `save_summary` calls `_auto_enrich()` first — regex-detects `file_paths` (from content), `module` (from path top-level dirs), and `tags` (from 15 tech keyword patterns like api/auth/test/python). Only fills missing fields; AI-provided values are never overwritten.
- **Search context injection**: `init_session()` stores `project_name`/`branch_name` in `self._last_context`; `search_summaries()` auto-injects them when params don't explicitly provide them.
- **Model version tracking**: `vector_metadata.model_version` column stores the snapshot hash. `scripts/reindex_vectors.py` batch reindexes all summaries (use `--force` for full rebuild).- **Quality guardrails**: `save_summary` returns non-blocking `quality_warnings` when file_paths/next_steps/tags/module/project_name are missing.
- **Search auto-fallback**: `search_summaries` auto-degrades: FTS5 → vector → LIKE. No need to toggle flags for most queries.
- **Env config**: Loads `~/.ai-memory/.env` on startup. Env vars: `AI_MEMORY_DB_PATH`, `AI_MEMORY_MODEL_PATH`, `AI_MEMORY_HOST`, `AI_MEMORY_PORT`, `AI_MEMORY_WEB_HOST`, `AI_MEMORY_WEB_PORT`.
- **Vector skip in tests**: Set `AI_MEMORY_DISABLE_VECTOR=1` to skip model download.

## Testing quirks
- Tests append `sys.path` manually to pick up `src/` — run `pytest` from project root only.
- Tests instantiate `AiMemoryMcpServer` directly with `AI_MEMORY_DB_PATH` pointing to `tmp_path` + `AI_MEMORY_DISABLE_VECTOR=1`.
- DB, FTS index, and indexes are all verified in tests.
- Integration test (`tests/integration/test_integration.py`) covers the full CRUD workflow.

## Docker
- Multi-stage Dockerfile: targets `ai-memory` (with vector) and `ai-memory-web` (web panel only)
- Uses Tsinghua pip mirror + HuggingFace mirror (`hf-mirror.com`) for China network
- Model cache mounted externally as volume (~500 MB), not embedded in image
- `docker compose up -d` for core; add `--build-arg INSTALL_VECTOR=true` for vector search
