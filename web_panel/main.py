"""
AI Memory Web Panel — FastAPI application.
Provides a web UI for managing memories, viewing quality scores,
tracking memory hits, and getting usage suggestions.
"""

import logging
import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from mcp_server.database import (
    db_add_decision,
    db_count_decisions_for_session,
    db_get_summary_by_id,
    db_search_summaries,
    get_db_connection,
    init_db,
)
from mcp_server.models import DEFAULT_DB_DIR_NAME, ENV_VAR_DB_PATH

try:
    from .quality import score_memory, get_quality_distribution
except ImportError:
    from quality import score_memory, get_quality_distribution

try:
    from .i18n import SUPPORTED_LANGS, detect_lang, make_translator
except ImportError:
    from i18n import SUPPORTED_LANGS, detect_lang, make_translator

logger = logging.getLogger("ai_memory_web")
logging.basicConfig(level=logging.INFO)

HIT_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS memory_hits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    hit_type TEXT NOT NULL,
    query_text TEXT,
    hit_count INTEGER DEFAULT 1,
    first_hit_at DATETIME,
    last_hit_at DATETIME,
    FOREIGN KEY (session_id) REFERENCES session_summaries(session_id)
)
"""


def get_db_path() -> str:
    env_path = os.environ.get(ENV_VAR_DB_PATH)
    if env_path:
        return env_path
    home = Path.home()
    return str(home / DEFAULT_DB_DIR_NAME / "ai_memory.db")


def ensure_hit_table():
    db_path = get_db_path()
    with get_db_connection(db_path) as conn:
        conn.execute(HIT_TABLE_DDL)
        conn.commit()


def record_hit(session_id: str, hit_type: str, query_text: Optional[str] = None):
    db_path = get_db_path()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_db_connection(db_path) as conn:
        existing = conn.execute(
            "SELECT id, hit_count FROM memory_hits WHERE session_id = ? AND hit_type = ? AND (query_text IS ? OR (? IS NULL AND query_text IS NULL))",
            (session_id, hit_type, query_text, query_text),
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE memory_hits SET hit_count = hit_count + 1, last_hit_at = ? WHERE id = ?",
                (now, existing[0]),
            )
        else:
            conn.execute(
                "INSERT INTO memory_hits (session_id, hit_type, query_text, first_hit_at, last_hit_at) VALUES (?, ?, ?, ?, ?)",
                (session_id, hit_type, query_text, now, now),
            )
        conn.commit()


def get_hit_stats(session_id: Optional[str] = None) -> List[Dict[str, Any]]:
    db_path = get_db_path()
    with get_db_connection(db_path, row_factory=True) as conn:
        if session_id:
            rows = conn.execute(
                "SELECT * FROM memory_hits WHERE session_id = ? ORDER BY last_hit_at DESC", (session_id,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM memory_hits ORDER BY last_hit_at DESC LIMIT 50"
            ).fetchall()
        return [dict(r) for r in rows]


def get_top_hit_memories(limit: int = 10) -> List[Dict[str, Any]]:
    db_path = get_db_path()
    with get_db_connection(db_path, row_factory=True) as conn:
        rows = conn.execute(
            """SELECT mh.session_id, s.task_title, s.project_name,
                      SUM(mh.hit_count) as total_hits,
                      MAX(mh.last_hit_at) as last_hit
               FROM memory_hits mh
               JOIN session_summaries s ON s.session_id = mh.session_id
               GROUP BY mh.session_id
               ORDER BY total_hits DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [{"session_id": r[0], "task_title": r[1], "project_name": r[2], "total_hits": r[3], "last_hit": r[4]} for r in rows]


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db(get_db_path())
    ensure_hit_table()
    yield


templates_dir = Path(__file__).parent / "templates"
static_dir = Path(__file__).parent / "static"

app = FastAPI(title="AI Memory Web Panel", version="1.0.0", lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=500)

templates = Jinja2Templates(directory=str(templates_dir))

# Inject i18n context into all templates
def get_i18n_ctx(request: Request) -> Dict[str, Any]:
    query_lang = request.query_params.get("lang")
    cookie_lang = request.cookies.get("lang")
    accept_lang = request.headers.get("accept-language", "")
    lang = detect_lang(accept_lang, cookie_lang, query_lang)
    _ = make_translator(lang)
    return {
        "_": _,
        "current_lang": lang,
        "supported_langs": SUPPORTED_LANGS,
    }

def render(request: Request, template: str, context: Dict[str, Any]) -> HTMLResponse:
    i18n = get_i18n_ctx(request)
    ctx = {**context, **i18n}
    # Make _ available to macros via env globals
    templates.env.globals["current_lang"] = i18n["current_lang"]
    templates.env.globals["supported_langs"] = i18n["supported_langs"]
    templates.env.globals["_"] = i18n["_"]
    resp = templates.TemplateResponse(request, template, ctx)
    resp.set_cookie(key="lang", value=i18n["current_lang"], max_age=31536000, httponly=True)
    return resp

if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


# ── HTML Pages ──

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    db_path = get_db_path()
    ensure_hit_table()
    with get_db_connection(db_path, row_factory=True) as conn:
        total = conn.execute("SELECT COUNT(*) as c FROM session_summaries").fetchone()[0]
        completed = conn.execute("SELECT COUNT(*) as c FROM session_summaries WHERE status='completed'").fetchone()[0]
        in_progress = conn.execute("SELECT COUNT(*) as c FROM session_summaries WHERE status='in_progress'").fetchone()[0]
        decision_count = conn.execute("SELECT COUNT(*) as c FROM key_decisions").fetchone()[0]
        hit_count_row = conn.execute("SELECT COALESCE(SUM(hit_count), 0) as c FROM memory_hits").fetchone()
        total_hits = hit_count_row[0]
        projects = conn.execute("SELECT DISTINCT project_name FROM session_summaries WHERE project_name IS NOT NULL AND project_name != ''").fetchall()
        hits_rows = conn.execute(
            "SELECT DATE(last_hit_at) as day, SUM(hit_count) as cnt FROM memory_hits GROUP BY day ORDER BY day DESC LIMIT 14"
        ).fetchall()
        hits_over_time = [{"day": r[0], "count": r[1]} for r in hits_rows]

        project_list = [r[0] for r in projects]

        scores = []
        rows = conn.execute(
            "SELECT session_id, status, task_title, summary_content, tags, module, file_paths, "
            "next_steps, project_name, branch_name FROM session_summaries ORDER BY created_at DESC LIMIT 200"
        ).fetchall()
        if rows:
            ids = [r[0] for r in rows]
            placeholders = ",".join("?" for _ in ids)
            decision_map = {}
            for row in conn.execute(
                f"SELECT session_id, COUNT(*) as cnt FROM key_decisions WHERE session_id IN ({placeholders}) GROUP BY session_id",
                ids,
            ).fetchall():
                decision_map[row[0]] = row[1]
            for r in rows:
                session = dict(r)
                dc = decision_map.get(session["session_id"], 0)
                q = score_memory(session, dc)
                scores.append(q["percentage"])

        topics = []
        top_rows = conn.execute(
            """SELECT mh.session_id, s.task_title, s.project_name,
                      SUM(mh.hit_count) as total_hits
               FROM memory_hits mh
               JOIN session_summaries s ON s.session_id = mh.session_id
               GROUP BY mh.session_id ORDER BY total_hits DESC LIMIT 5"""
        ).fetchall()
        topics = [{"session_id": r[0], "task_title": r[1], "project_name": r[2], "total_hits": r[3]} for r in top_rows]

    dist = get_quality_distribution(scores)
    avg_score = round(sum(scores) / len(scores), 1) if scores else 0

    return render(request, "dashboard.html", {
        "total": total,
        "completed": completed,
        "in_progress": in_progress,
        "decisions": decision_count,
        "total_hits": total_hits,
        "projects": project_list,
        "quality_dist": dist,
        "avg_score": avg_score,
        "top_memories": topics,
        "hits_over_time": hits_over_time,
    })


@app.get("/memories", response_class=HTMLResponse)
async def memory_list(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=10, le=100),
    q: Optional[str] = None,
    project: Optional[str] = None,
    status: Optional[str] = None,
    sort: str = "created_at",
    order: str = "desc",
):
    db_path = get_db_path()
    ensure_hit_table()
    try:
        offset = (page - 1) * per_page
        conditions = []
        params: List[Any] = []

        if q:
            conditions.append("(task_title LIKE ? OR summary_content LIKE ?)")
            params.extend([f"%{q}%", f"%{q}%"])
        if project:
            conditions.append("project_name = ?")
            params.append(project)
        if status:
            conditions.append("status = ?")
            params.append(status)

        where = " AND ".join(conditions) if conditions else "1=1"
        order_dir = "DESC" if order == "desc" else "ASC"
        valid_sort = sort if sort in ("created_at", "updated_at", "task_title", "status") else "created_at"

        with get_db_connection(db_path, row_factory=True) as conn:
            count_row = conn.execute(f"SELECT COUNT(*) as c FROM session_summaries WHERE {where}", params).fetchone()
            total_count = count_row[0]
            rows = conn.execute(
                f"SELECT * FROM session_summaries WHERE {where} ORDER BY {valid_sort} {order_dir} LIMIT ? OFFSET ?",
                params + [per_page, offset],
            ).fetchall()

            summaries = [dict(r) for r in rows]
            if summaries:
                ids = [s["session_id"] for s in summaries]
                placeholders = ",".join("?" for _ in ids)
                decision_map = {}
                for row in conn.execute(
                    f"SELECT session_id, COUNT(*) as cnt FROM key_decisions WHERE session_id IN ({placeholders}) GROUP BY session_id",
                    ids,
                ).fetchall():
                    decision_map[row[0]] = row[1]
                for s in summaries:
                    dc = decision_map.get(s["session_id"], 0)
                    qs = score_memory(s, dc)
                    s["_quality"] = qs

            total_pages = max(1, (total_count + per_page - 1) // per_page)

            projects = conn.execute("SELECT DISTINCT project_name FROM session_summaries WHERE project_name IS NOT NULL AND project_name != ''").fetchall()
            project_list = [r[0] for r in projects]

        return render(request, "memories.html", {
            "summaries": summaries,
            "page": page,
            "per_page": per_page,
            "total": total_count,
            "total_pages": total_pages,
            "q": q or "",
            "project_filter": project or "",
            "status_filter": status or "",
            "sort": sort,
            "order": order,
            "projects": project_list,
        })
    except Exception as e:
        logger.error(f"Error listing memories: {e}", exc_info=True)
        raise HTTPException(500, str(e))


@app.get("/memories/{session_id}", response_class=HTMLResponse)
async def memory_detail(request: Request, session_id: str):
    db_path = get_db_path()
    ensure_hit_table()
    summary = db_get_summary_by_id(db_path, session_id)
    if not summary:
        raise HTTPException(404, "记忆未找到")

    record_hit(session_id, "direct_access", None)
    decision_count = db_count_decisions_for_session(db_path, session_id)

    with get_db_connection(db_path, row_factory=True) as conn:
        decisions = conn.execute(
            "SELECT * FROM key_decisions WHERE session_id = ? ORDER BY id DESC", (session_id,)
        ).fetchall()
        vector_row = conn.execute(
            "SELECT * FROM vector_metadata WHERE session_id = ?", (session_id,)
        ).fetchone()
        hits = conn.execute(
            "SELECT * FROM memory_hits WHERE session_id = ? ORDER BY last_hit_at DESC", (session_id,)
        ).fetchall()

    has_vector = vector_row is not None
    quality = score_memory(summary, decision_count, has_vector)
    hit_list = [dict(r) for r in hits]
    decision_list = [dict(r) for r in decisions]

    total_hits = sum(h["hit_count"] for h in hit_list)

    return render(request, "memory_detail.html", {
        "summary": summary,
        "quality": quality,
        "decisions": decision_list,
        "hits": hit_list,
        "total_hits": total_hits,
        "has_vector": has_vector,
    })


@app.get("/search", response_class=HTMLResponse)
async def search_page(request: Request, q: str = Query(""), mode: str = Query("fts")):
    db_path = get_db_path()
    ensure_hit_table()
    results: List[Dict[str, Any]] = []
    query_text = q.strip()

    if query_text:
        use_fts = mode == "fts"
        results = db_search_summaries(
            db_path, query_text, None, None, None, None, None, use_fts, 50
        )
        if results:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with get_db_connection(db_path) as conn:
                for s in results:
                    existing = conn.execute(
                        "SELECT id, hit_count FROM memory_hits WHERE session_id = ? AND hit_type = ? AND query_text = ?",
                        (s["session_id"], f"search_{mode}", query_text),
                    ).fetchone()
                    if existing:
                        conn.execute(
                            "UPDATE memory_hits SET hit_count = hit_count + 1, last_hit_at = ? WHERE id = ?",
                            (now, existing[0]),
                        )
                    else:
                        conn.execute(
                            "INSERT INTO memory_hits (session_id, hit_type, query_text, first_hit_at, last_hit_at) VALUES (?, ?, ?, ?, ?)",
                            (s["session_id"], f"search_{mode}", query_text, now, now),
                        )
                conn.commit()

            ids = [s["session_id"] for s in results]
            placeholders = ",".join("?" for _ in ids)
            with get_db_connection(db_path, row_factory=True) as conn:
                decision_map = {}
                for row in conn.execute(
                    f"SELECT session_id, COUNT(*) as cnt FROM key_decisions WHERE session_id IN ({placeholders}) GROUP BY session_id",
                    ids,
                ).fetchall():
                    decision_map[row[0]] = row[1]
            for s in results:
                dc = decision_map.get(s["session_id"], 0)
                qs = score_memory(s, dc)
                s["_quality"] = qs

    return render(request, "search.html", {
        "query": query_text,
        "mode": mode,
        "results": results,
    })


# ── API Endpoints ──

@app.get("/api/stats")
async def api_stats():
    db_path = get_db_path()
    with get_db_connection(db_path, row_factory=True) as conn:
        total = conn.execute("SELECT COUNT(*) as c FROM session_summaries").fetchone()[0]
        completed = conn.execute("SELECT COUNT(*) as c FROM session_summaries WHERE status='completed'").fetchone()[0]
        in_progress = conn.execute("SELECT COUNT(*) as c FROM session_summaries WHERE status='in_progress'").fetchone()[0]
        decision_count = conn.execute("SELECT COUNT(*) as c FROM key_decisions").fetchone()[0]
        hit_row = conn.execute("SELECT COALESCE(SUM(hit_count), 0) as c FROM memory_hits").fetchone()
        total_hits = hit_row[0]
    return {"total": total, "completed": completed, "in_progress": in_progress, "decisions": decision_count, "total_hits": total_hits}


@app.get("/api/quality/{session_id}")
async def api_quality(session_id: str):
    db_path = get_db_path()
    summary = db_get_summary_by_id(db_path, session_id)
    if not summary:
        raise HTTPException(404, "记忆未找到")
    dc = db_count_decisions_for_session(db_path, session_id)
    with get_db_connection(db_path, row_factory=True) as conn:
        has_vector = conn.execute("SELECT 1 FROM vector_metadata WHERE session_id = ?", (session_id,)).fetchone() is not None
    return score_memory(summary, dc, has_vector)


@app.get("/api/hits")
async def api_hits(top: int = Query(10, ge=1, le=50)):
    return {"hits": get_top_hit_memories(top)}


@app.get("/api/hits/{session_id}")
async def api_hits_detail(session_id: str):
    return {"hits": get_hit_stats(session_id)}


@app.delete("/api/memories/{session_id}")
async def api_delete_memory(session_id: str):
    db_path = get_db_path()
    with get_db_connection(db_path) as conn:
        conn.execute("DELETE FROM memory_hits WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM vector_metadata WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM key_decisions WHERE session_id = ?", (session_id,))
        row = conn.execute("SELECT id FROM session_summaries WHERE session_id = ?", (session_id,)).fetchone()
        if row:
            conn.execute("DELETE FROM summary_fts WHERE rowid = ?", (row[0],))
            conn.execute("DELETE FROM session_summaries WHERE session_id = ?", (session_id,))
            conn.commit()
            return {"success": True, "message": "记忆已删除"}
    raise HTTPException(404, "记忆未找到")


@app.post("/api/memories/{session_id}/decisions")
async def api_add_decision(session_id: str, data: Dict[str, str]):
    db_path = get_db_path()
    result = db_add_decision(
        db_path, session_id,
        data.get("decision_type", "general"),
        data.get("description", ""),
        data.get("reasoning"),
    )
    if result["success"]:
        return result
    raise HTTPException(400, result.get("message", "添加失败"))


@app.put("/api/memories/{session_id}")
async def api_update_memory(session_id: str, data: Dict[str, Any]):
    from mcp_server.database import db_update_summary
    db_path = get_db_path()
    result = db_update_summary(
        db_path, session_id,
        data.get("new_status"),
        data.get("updated_content"),
    )
    if result["success"]:
        return result
    raise HTTPException(400, result.get("message", "更新失败"))


# ── CLI entry point ──

def main():
    import uvicorn
    host = os.environ.get("AI_MEMORY_WEB_HOST", "127.0.0.1")
    port = int(os.environ.get("AI_MEMORY_WEB_PORT", "8080"))
    print(f"  🌐 AI Memory Web Panel: http://{host}:{port}")
    print(f"  📁 DB: {get_db_path()}")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
