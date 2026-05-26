# 🧠 AI Memory MCP

> Persistent session memory for AI assistants — store, search and retrieve conversation summaries via the [Model Context Protocol](https://modelcontextprotocol.io).

[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![MCP](https://img.shields.io/badge/MCP-1.6%2B-green)](https://modelcontextprotocol.io)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-24%20passed-brightgreen)](#testing)

---

## What is this?

AI assistants forget everything between sessions. **AI Memory MCP** solves that by giving your AI a structured long-term memory:

- 📝 **Save** session summaries with status, tags, modules and file paths
- 🔍 **Search** by keyword, full-text (FTS5), or **semantic vector similarity**
- 🔄 **Restore context** at the start of each session with one tool call
- 📊 **Generate weekly reports** from completed tasks automatically
- 🏷️ **Multi-project / multi-branch** support out of the box

Works with **Claude Desktop**, **Cursor**, **VS Code**, **Windsurf**, and any MCP-compatible client.

---

## Quick Start

### 1 — Install

```bash
# From PyPI (recommended)
pip install ai-memory-mcp

# With vector search support (adds ~500 MB for embedding model)
pip install "ai-memory-mcp[vector]"

# From source
git clone https://github.com/zhanpu89/ai-memory-mcp
cd ai-memory-mcp
pip install -e .
```

### 2 — Configure your AI client

Pick the config snippet for your tool and add it to its MCP settings file:

<details>
<summary><b>Claude Desktop</b> — <code>~/Library/Application Support/Claude/claude_desktop_config.json</code></summary>

```json
{
  "mcpServers": {
    "ai-memory": {
      "command": "ai-memory-mcp"
    }
  }
}
```
</details>

<details>
<summary><b>Cursor</b> — <code>~/.cursor/mcp.json</code></summary>

```json
{
  "mcpServers": {
    "ai-memory": {
      "command": "ai-memory-mcp"
    }
  }
}
```
</details>

<details>
<summary><b>VS Code (GitHub Copilot)</b> — <code>.vscode/mcp.json</code></summary>

```json
{
  "servers": {
    "ai-memory": {
      "type": "stdio",
      "command": "ai-memory-mcp"
    }
  }
}
```
</details>

<details>
<summary><b>Windsurf</b> — <code>~/.codeium/windsurf/mcp_config.json</code></summary>

```json
{
  "mcpServers": {
    "ai-memory": {
      "command": "ai-memory-mcp"
    }
  }
}
```
</details>

<details>
<summary><b>HTTP mode</b> (remote / Docker / team)</summary>

Start the server:
```bash
ai-memory-mcp --http
# or: python service.py start
```

Then point your client at:
```json
{
  "mcpServers": {
    "ai-memory": {
      "url": "http://localhost:8000/mcp"
    }
  }
}
```
</details>

> **All config snippets** are available in [`integrations/`](integrations/).

### 3 — Use it

At the start of every session, tell your AI:

```
Load my memory for project "my-project"
```

The AI will call `init_session` and restore your previous context automatically.

---

## Features

| Feature | Details |
|---|---|
| **Storage** | SQLite — zero external services, single file |
| **Full-text search** | SQLite FTS5 — fast, no extra deps |
| **Semantic search** | ChromaDB + `all-MiniLM-L6-v2` (optional) |
| **Multi-project** | Filter by `project_name` + `branch_name` |
| **Task lifecycle** | `pending → in_progress → completed / blocked / abandoned` |
| **Key decisions** | Attach architectural decisions to sessions |
| **Weekly reports** | Auto-generated Markdown report |
| **Transport** | stdio (local) or streamable-HTTP (remote) |
| **Docker** | Single-container deployment included |

---

## Architecture

```
┌─────────────────────────────────────────────────┐
│               AI Client (Claude / Cursor …)      │
│                    MCP Protocol                  │
└──────────────────────┬──────────────────────────┘
                       │ stdio / HTTP
┌──────────────────────▼──────────────────────────┐
│              AiMemoryMcpServer (FastMCP)         │
│                                                  │
│  ┌──────────────┐    ┌──────────────────────┐   │
│  │  SQLite DB   │    │  ChromaDB (optional) │   │
│  │  FTS5 index  │    │  Sentence-Transformers│  │
│  └──────────────┘    └──────────────────────┘   │
└─────────────────────────────────────────────────┘
```

**Data lives in `~/.ai-memory/`** — completely separate from your project files.

---

## Tool Reference

→ See **[TOOLS.md](TOOLS.md)** for the full schema of all 10 tools.

| Tool | Description |
|---|---|
| `save_summary` | Persist a new session summary |
| `update_summary` | Update status / content |
| `add_decision` | Record a key technical decision |
| `search_summaries` | Keyword / FTS5 / vector search |
| `search_summaries_fts` | Dedicated FTS5 full-text search |
| `get_summary_by_id` | Exact lookup by session ID |
| `list_recent_sessions` | List latest sessions |
| `init_session` | Restore context at session start |
| `weekly_review` | Generate Markdown weekly report |
| `maintenance` | Rebuild index, VACUUM, persist vectors |

---

## Configuration

All settings are optional — sensible defaults work out of the box.

| Env var | Default | Description |
|---|---|---|
| `AI_MEMORY_DB_PATH` | `~/.ai-memory/ai_memory.db` | SQLite database path |
| `AI_MEMORY_MODEL_PATH` | `~/.ai-memory/models` | Embedding model cache |
| `AI_MEMORY_HOST` | `127.0.0.1` | HTTP server bind address |
| `AI_MEMORY_PORT` | `8000` | HTTP server port |

Create `~/.ai-memory/.env` to persist settings:

```env
AI_MEMORY_DB_PATH=/custom/path/ai_memory.db
AI_MEMORY_PORT=9000
```

---

## Docker

**Optimized for China:** Uses Tsinghua pip mirror + HuggingFace mirror for fast downloads.

```bash
# Option 1: Core-only (lightweight, ~200 MB image)
docker compose up -d

# Option 2: Full (with vector search)
# Step 1: Pre-download model to avoid large image
python3 scripts/download_model_for_docker.py --output ./models

# Step 2: Build with vector support (~700 MB image + 500 MB external model)
docker compose build --build-arg INSTALL_VECTOR=true
docker compose up -d

# View logs
docker compose logs -f
```

The MCP endpoint will be available at `http://localhost:8000/mcp`.

**📖 Full deployment guide:** See [DOCKER.md](DOCKER.md) for:
- Image size optimization strategies
- Chinese mirror configuration
- Model pre-downloading
- Production deployment examples

---

## Development

```bash
# Clone and install in editable mode with dev extras
git clone https://github.com/zhanpu89/ai-memory-mcp
cd ai-memory-mcp
pip install -e ".[dev]"

# Run tests
pytest

# Run tests with coverage
pytest --cov=src/mcp_server --cov-report=term-missing

# Start in HTTP mode for manual testing
ai-memory-mcp --http
```

### Project Structure

```
ai-memory-mcp/
├── src/mcp_server/
│   ├── __init__.py
│   └── server.py          # All 10 MCP tools + server class
├── tests/
│   ├── unit/              # 24 unit tests
│   └── integration/
├── scripts/
│   ├── download_model.py  # Manual model download
│   ├── migrate_db.py      # Database migration helper
│   └── migrate_vector.py  # Vector store migration
├── integrations/          # Ready-to-use MCP client configs
│   ├── claude_desktop_config.json
│   ├── cursor_mcp.json
│   ├── vscode_mcp.json
│   ├── windsurf_mcp.json
│   └── http_mode_config.json
├── TOOLS.md               # Full tool schema reference
├── INSTALL.md             # Detailed installation guide
├── Dockerfile
├── docker-compose.yml
└── pyproject.toml
```

---

## Testing

```
24 passed in 7s
```

```bash
pytest tests/unit/test_mcp_server.py -v
```

All 24 unit tests cover: save/update/search/FTS/vector/decisions/maintenance/init/review/schema.

---

## Requirements

- Python 3.10+
- `mcp >= 1.6.0`
- `python-dotenv >= 1.0.0`

**Optional (vector search):**
- `chromadb >= 0.6.0`
- `sentence-transformers >= 3.0.0`

---

## License

[MIT](LICENSE) © AI Memory Team
