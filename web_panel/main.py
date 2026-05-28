"""
AI Memory Web Panel — FastAPI application.
Provides a web UI for managing memories, viewing quality scores,
tracking memory hits, and getting usage suggestions.
"""

import logging
import os
import re
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

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

SEARCH_MISSES_DDL = """
CREATE TABLE IF NOT EXISTS search_misses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query_text TEXT NOT NULL,
    hit_count INTEGER DEFAULT 1,
    last_seen_at DATETIME,
    first_seen_at DATETIME
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
        conn.execute(SEARCH_MISSES_DDL)
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


def get_hit_count_for_session(db_path: str, session_id: str) -> int:
    with get_db_connection(db_path) as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(hit_count), 0) FROM memory_hits WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        return row[0] if row else 0


def get_hit_counts_for_sessions(db_path: str, session_ids: List[str]) -> Dict[str, int]:
    if not session_ids:
        return {}
    placeholders = ",".join("?" for _ in session_ids)
    with get_db_connection(db_path) as conn:
        rows = conn.execute(
            f"SELECT session_id, COALESCE(SUM(hit_count), 0) FROM memory_hits WHERE session_id IN ({placeholders}) GROUP BY session_id",
            session_ids,
        ).fetchall()
        return {r[0]: r[1] for r in rows}


def record_search_miss(query_text: str):
    if not query_text.strip():
        return
    db_path = get_db_path()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_db_connection(db_path) as conn:
        existing = conn.execute(
            "SELECT id, hit_count FROM search_misses WHERE query_text = ?", (query_text,)
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE search_misses SET hit_count = hit_count + 1, last_seen_at = ? WHERE id = ?",
                (now, existing[0]),
            )
        else:
            conn.execute(
                "INSERT INTO search_misses (query_text, hit_count, first_seen_at, last_seen_at) VALUES (?, 1, ?, ?)",
                (query_text, now, now),
            )
        conn.commit()


def get_top_search_misses(limit: int = 10) -> List[Dict[str, Any]]:
    db_path = get_db_path()
    with get_db_connection(db_path, row_factory=True) as conn:
        rows = conn.execute(
            "SELECT * FROM search_misses ORDER BY hit_count DESC, last_seen_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_similar_search_misses(query: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Find similar queries that also missed, to show cluster info."""
    db_path = get_db_path()
    with get_db_connection(db_path, row_factory=True) as conn:
        tokens = query.lower().split()
        suggestions: List[Dict[str, Any]] = []
        seen: set = set()
        for token in tokens:
            if len(token) < 3:
                continue
            rows = conn.execute(
                "SELECT * FROM search_misses WHERE query_text LIKE ? ORDER BY hit_count DESC LIMIT ?",
                (f"%{token}%", limit),
            ).fetchall()
            for r in rows:
                d = dict(r)
                if d["query_text"] not in seen and d["query_text"] != query:
                    suggestions.append(d)
                    seen.add(d["query_text"])
        return suggestions[:limit]


def clear_search_miss(query_text: str):
    db_path = get_db_path()
    with get_db_connection(db_path) as conn:
        conn.execute("DELETE FROM search_misses WHERE query_text = ?", (query_text,))
        conn.commit()


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
            "next_steps, project_name, branch_name, created_at, updated_at FROM session_summaries ORDER BY created_at DESC LIMIT 200"
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
            hit_map = get_hit_counts_for_sessions(db_path, ids)
            now = datetime.now()
            for r in rows:
                session = dict(r)
                dc = decision_map.get(session["session_id"], 0)
                hc = hit_map.get(session["session_id"], 0)
                days_since = (now - datetime.strptime(session.get("updated_at") or session.get("created_at") or now.strftime("%Y-%m-%d %H:%M:%S"), "%Y-%m-%d %H:%M:%S")).days if session.get("updated_at") or session.get("created_at") else None
                q = score_memory(session, dc, hit_count=hc, days_since_update=days_since)
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

        # Quality trend: past 12 weeks
        quality_trend = []
        for w in range(12):
            end = now - timedelta(weeks=11 - w)
            start = end - timedelta(days=6)
            wk_rows = conn.execute(
                """SELECT session_id, status, task_title, summary_content, tags, module,
                          file_paths, next_steps, project_name, branch_name, created_at, updated_at
                   FROM session_summaries
                   WHERE created_at >= ? AND created_at < ?""",
                (start.strftime("%Y-%m-%d 00:00:00"), (end + timedelta(days=1)).strftime("%Y-%m-%d 00:00:00")),
            ).fetchall()
            if wk_rows:
                wk_ids = [r[0] for r in wk_rows]
                wk_ph = ",".join("?" for _ in wk_ids)
                wk_dec_map = {}
                for row in conn.execute(
                    f"SELECT session_id, COUNT(*) as cnt FROM key_decisions WHERE session_id IN ({wk_ph}) GROUP BY session_id",
                    wk_ids,
                ):
                    wk_dec_map[row[0]] = row[1]
                wk_hit_map = get_hit_counts_for_sessions(db_path, wk_ids)
                wk_scores = []
                for r in wk_rows:
                    s = dict(r)
                    dc = wk_dec_map.get(s["session_id"], 0)
                    hc = wk_hit_map.get(s["session_id"], 0)
                    upd = s.get("updated_at") or s.get("created_at")
                    ds = (now - datetime.strptime(upd, "%Y-%m-%d %H:%M:%S")).days if upd else None
                    qs = score_memory(s, dc, hit_count=hc, days_since_update=ds)
                    wk_scores.append(qs["percentage"])
                avg_wk = round(sum(wk_scores) / len(wk_scores), 1) if wk_scores else 0
            else:
                avg_wk = 0
            quality_trend.append({"week": end.strftime("%m/%d"), "avg": avg_wk, "count": len(wk_rows) if wk_rows else 0})

    dist = get_quality_distribution(scores)
    avg_score = round(sum(scores) / len(scores), 1) if scores else 0

    search_misses = get_top_search_misses(8)
    # Cold memories: completed, >90 days since update, 0 hits
    cold_memories_count = 0
    if rows:
        now = datetime.now()
        for r in rows:
            s = dict(r)
            upd = s.get("updated_at") or s.get("created_at")
            if s["status"] == "completed" and upd:
                try:
                    d = (now - datetime.strptime(upd, "%Y-%m-%d %H:%M:%S")).days
                    if d > 90 and hit_map.get(s["session_id"], 0) == 0:
                        cold_memories_count += 1
                except ValueError:
                    pass

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
        "quality_trend": quality_trend,
        "search_misses": search_misses,
        "cold_memories_count": cold_memories_count,
    })


@app.get("/memories", response_class=HTMLResponse)
async def memory_list(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=10, le=100),
    q: Optional[str] = None,
    project: Optional[str] = None,
    status: Optional[str] = None,
    quality: Optional[str] = None,
    sort: str = "updated_at",
    order: str = "desc",
):
    db_path = get_db_path()
    ensure_hit_table()
    try:
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
        needs_quality_filter = quality in ("needs_improvement", "excellent", "good", "average", "below_average", "poor")

        with get_db_connection(db_path, row_factory=True) as conn:
            # If quality filter is active, we must fetch all matching records and filter in Python
            if needs_quality_filter:
                all_rows = conn.execute(
                    f"SELECT * FROM session_summaries WHERE {where} ORDER BY created_at DESC",
                    params,
                ).fetchall()
                all_summaries = [dict(r) for r in all_rows]
                if all_summaries:
                    ids = [s["session_id"] for s in all_summaries]
                    ph = ",".join("?" for _ in ids)
                    decision_map = {}
                    for row in conn.execute(
                        f"SELECT session_id, COUNT(*) as cnt FROM key_decisions WHERE session_id IN ({ph}) GROUP BY session_id",
                        ids,
                    ).fetchall():
                        decision_map[row[0]] = row[1]
                    hit_map = get_hit_counts_for_sessions(db_path, ids)
                    vector_set = set(
                        r[0] for r in conn.execute(
                            f"SELECT session_id FROM vector_metadata WHERE session_id IN ({ph})",
                            ids,
                        ).fetchall()
                    )
                    now = datetime.now()
                    for s in all_summaries:
                        dc = decision_map.get(s["session_id"], 0)
                        hc = hit_map.get(s["session_id"], 0)
                        hv = s["session_id"] in vector_set
                        upd = s.get("updated_at") or s.get("created_at")
                        days_since = (now - datetime.strptime(upd, "%Y-%m-%d %H:%M:%S")).days if upd else None
                        qs = score_memory(s, dc, hv, hit_count=hc, days_since_update=days_since)
                        s["_quality"] = qs

                    if quality == "needs_improvement":
                        all_summaries = [s for s in all_summaries if s["_quality"]["percentage"] < 50]
                    else:
                        q_map = {"excellent": 80, "good": 65, "average": 50, "below_average": 30, "poor": 0}
                        threshold = q_map.get(quality, 0)
                        next_threshold = {"excellent": 101, "good": 80, "average": 65, "below_average": 50, "poor": 30}.get(quality, 101)
                        all_summaries = [s for s in all_summaries if threshold <= s["_quality"]["percentage"] < next_threshold]

                total_count = len(all_summaries)
                total_pages = max(1, (total_count + per_page - 1) // per_page)
                offset = (page - 1) * per_page
                summaries = all_summaries[offset:offset + per_page]
            else:
                count_row = conn.execute(f"SELECT COUNT(*) as c FROM session_summaries WHERE {where}", params).fetchone()
                total_count = count_row[0]
                offset = (page - 1) * per_page
                rows = conn.execute(
                    f"SELECT * FROM session_summaries WHERE {where} ORDER BY {valid_sort} {order_dir} LIMIT ? OFFSET ?",
                    params + [per_page, offset],
                ).fetchall()

                summaries = [dict(r) for r in rows]
                if summaries:
                    ids = [s["session_id"] for s in summaries]
                    ph = ",".join("?" for _ in ids)
                    decision_map = {}
                    for row in conn.execute(
                        f"SELECT session_id, COUNT(*) as cnt FROM key_decisions WHERE session_id IN ({ph}) GROUP BY session_id",
                        ids,
                    ).fetchall():
                        decision_map[row[0]] = row[1]
                    hit_map = get_hit_counts_for_sessions(db_path, ids)
                    vector_set = set(
                        r[0] for r in conn.execute(
                            f"SELECT session_id FROM vector_metadata WHERE session_id IN ({ph})",
                            ids,
                        ).fetchall()
                    )
                    now = datetime.now()
                    for s in summaries:
                        dc = decision_map.get(s["session_id"], 0)
                        hc = hit_map.get(s["session_id"], 0)
                        hv = s["session_id"] in vector_set
                        upd = s.get("updated_at") or s.get("created_at")
                        days_since = (now - datetime.strptime(upd, "%Y-%m-%d %H:%M:%S")).days if upd else None
                        qs = score_memory(s, dc, hv, hit_count=hc, days_since_update=days_since)
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
            "quality_filter": quality or "",
            "sort": sort,
            "order": order,
            "projects": project_list,
        })
    except Exception as e:
        logger.error(f"Error listing memories: {e}", exc_info=True)
        raise HTTPException(500, str(e))


@app.get("/cold-memories", response_class=HTMLResponse)
async def cold_memories(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=10, le=100),
    q: Optional[str] = None,
):
    """冷记忆页面：30天零命中 / 90天未更新 completed + 0 hits"""
    db_path = get_db_path()
    ensure_hit_table()
    try:
        with get_db_connection(db_path, row_factory=True) as conn:
            base_sql = "SELECT * FROM session_summaries WHERE 1=1"
            params: List[Any] = []
            if q:
                base_sql += " AND (task_title LIKE ? OR summary_content LIKE ?)"
                params.extend([f"%{q}%", f"%{q}%"])

            all_rows = conn.execute(base_sql, params).fetchall()
            summaries = [dict(r) for r in all_rows]
            ids = [s["session_id"] for s in summaries]
            decision_map = {}
            if ids:
                ph = ",".join("?" for _ in ids)
                for row in conn.execute(
                    f"SELECT session_id, COUNT(*) as cnt FROM key_decisions WHERE session_id IN ({ph}) GROUP BY session_id",
                    ids,
                ).fetchall():
                    decision_map[row[0]] = row[1]

            hit_map = get_hit_counts_for_sessions(db_path, ids) if ids else {}
            now = datetime.now()

            cold_list = []
            for s in summaries:
                dc = decision_map.get(s["session_id"], 0)
                hc = hit_map.get(s["session_id"], 0)
                upd = s.get("updated_at") or s.get("created_at")
                days_since = (now - datetime.strptime(upd, "%Y-%m-%d %H:%M:%S")).days if upd else None
                qs = score_memory(s, dc, hit_count=hc, days_since_update=days_since)
                s["_quality"] = qs
                # 冷记忆判定：completed + >90天未更新 + 0命中
                if s["status"] == "completed" and days_since is not None and days_since > 90 and hc == 0:
                    s["_days_since"] = days_since
                    s["_hit_count"] = hc
                    s["_decision_count"] = dc
                    cold_list.append(s)

            total_count = len(cold_list)
            total_pages = max(1, (total_count + per_page - 1) // per_page)
            offset = (page - 1) * per_page
            page_items = cold_list[offset:offset + per_page]

    except Exception as e:
        logger.error(f"Error listing cold memories: {e}", exc_info=True)
        raise HTTPException(500, str(e))

    return render(request, "cold_memories.html", {
        "summaries": page_items,
        "page": page,
        "per_page": per_page,
        "total": total_count,
        "total_pages": total_pages,
        "q": q or "",
    })


@app.get("/memories/{session_id}", response_class=HTMLResponse)
async def memory_detail(request: Request, session_id: str):
    db_path = get_db_path()
    ensure_hit_table()
    summary = db_get_summary_by_id(db_path, session_id)
    if not summary:
        raise HTTPException(404, "记忆未找到")

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
    total_hits = sum(h["hit_count"] for h in hits)
    upd = summary.get("updated_at") or summary.get("created_at")
    days_since = (datetime.now() - datetime.strptime(upd, "%Y-%m-%d %H:%M:%S")).days if upd else None
    quality = score_memory(summary, decision_count, has_vector, hit_count=total_hits, days_since_update=days_since)
    hit_list = [dict(r) for r in hits]
    decision_list = [dict(r) for r in decisions]

    return render(request, "memory_detail.html", {
        "summary": summary,
        "quality": quality,
        "decisions": decision_list,
        "hits": hit_list,
        "total_hits": total_hits,
        "has_vector": has_vector,
    })


_QUERY_TAG_PATTERNS: List[Tuple[str, str]] = [
    (r'\b(auth|login|jwt|oauth|session|permission|rbac)\b', 'auth'),
    (r'\b(api|rest|graphql|endpoint|route)\b', 'api'),
    (r'\b(test|pytest|unittest|mock|coverage)\b', 'test'),
    (r'\b(db|sql|database|migration|schema|query|redis|postgres|mysql|sqlite)\b', 'database'),
    (r'\b(docker|container|k8s|kubernetes|deploy|ci/cd)\b', 'devops'),
    (r'\b(frontend|ui|vue|react|html|css|javascript|typescript)\b', 'frontend'),
    (r'\b(error|exception|bug|fix|debug|traceback)\b', 'bug'),
    (r'\b(refactor|clean|optimize|performance|perf)\b', 'refactor'),
    (r'\b(config|setting|env|environment|install)\b', 'config'),
    (r'\b(python|fastapi|flask|django|async|asyncio)\b', 'backend'),
    (r'\b(vector|embedding|chroma|semantic|rag|llm)\b', 'ai'),
    (r'\b(security|vuln|cve|xss|csrf|injection)\b', 'security'),
]


def _extract_query_tags(query: str) -> List[str]:
    """Extract tech tags from a search query to auto-filter results."""
    tags: List[str] = []
    seen: set = set()
    for pattern, tag in _QUERY_TAG_PATTERNS:
        if re.search(pattern, query, re.IGNORECASE) and tag not in seen:
            tags.append(tag)
            seen.add(tag)
    return tags


def _score_search_relevance(result: Dict[str, Any], query_tags: List[str]) -> float:
    """Compute a relevance boost: tag matches, quality score, hit frequency."""
    boost = 0.0
    # Tag overlap
    result_tags = (result.get("tags") or "").lower().split(",")
    result_tags = [t.strip() for t in result_tags if t.strip()]
    if result_tags and query_tags:
        overlap = len(set(result_tags) & set(query_tags))
        boost += overlap * 15
    # Module overlap
    module = (result.get("module") or "").lower().strip()
    if module and any(t == module for t in query_tags):
        boost += 10
    # Quality score
    qs = result.get("_quality_pct", result.get("_quality", {}).get("percentage", 0))
    if qs >= 80:
        boost += 20
    elif qs >= 65:
        boost += 10
    # Hit count popularity (log scale)
    hc = result.get("_hit_count", 0)
    if hc >= 5:
        boost += 10
    elif hc >= 2:
        boost += 5
    return boost


@app.get("/search", response_class=HTMLResponse)
async def search_page(request: Request, q: str = Query(""), mode: str = Query("fts")):
    db_path = get_db_path()
    ensure_hit_table()
    results: List[Dict[str, Any]] = []
    query_text = q.strip()

    if query_text:
        use_fts = mode == "fts"
        query_tags = _extract_query_tags(query_text)
        results = db_search_summaries(
            db_path, query_text, None, None, None, None, None, use_fts, 50
        )

        if not results and query_tags:
            # Auto-fallback: search again with tag filter
            for tag in query_tags:
                tag_results = db_search_summaries(
                    db_path, query_text, tag, None, None, None, None, use_fts, 50
                )
                if tag_results:
                    results = tag_results
                    break

    suggest_misses = []
    if query_text and not results:
        record_search_miss(query_text)
        suggest_misses = get_similar_search_misses(query_text)

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
            hit_map = get_hit_counts_for_sessions(db_path, ids)
            now_dt = datetime.now()
            for s in results:
                dc = decision_map.get(s["session_id"], 0)
                hc = hit_map.get(s["session_id"], 0)
                upd = s.get("updated_at") or s.get("created_at")
                days_since = (now_dt - datetime.strptime(upd, "%Y-%m-%d %H:%M:%S")).days if upd else None
                qs = score_memory(s, dc, hit_count=hc, days_since_update=days_since)
                s["_quality"] = qs
                s["_quality_pct"] = qs["percentage"]
                s["_hit_count"] = hc
                s["_relevance_boost"] = _score_search_relevance(s, query_tags)

            # Composite ranking: BM25 rank (lower=better) + relevance boost
            if use_fts:
                results.sort(key=lambda x: (x.get("bm25_rank", 9999), -x.get("_relevance_boost", 0)))
            else:
                results.sort(key=lambda x: -(x.get("_quality_pct", 0) + x.get("_relevance_boost", 0)))

    return render(request, "search.html", {
        "query": query_text,
        "mode": mode,
        "results": results,
        "query_tags": _extract_query_tags(query_text),
        "suggest_misses": suggest_misses,
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
    hc = get_hit_count_for_session(db_path, session_id)
    upd = summary.get("updated_at") or summary.get("created_at")
    days_since = (datetime.now() - datetime.strptime(upd, "%Y-%m-%d %H:%M:%S")).days if upd else None
    with get_db_connection(db_path, row_factory=True) as conn:
        has_vector = conn.execute("SELECT 1 FROM vector_metadata WHERE session_id = ?", (session_id,)).fetchone() is not None
    return score_memory(summary, dc, has_vector, hit_count=hc, days_since_update=days_since)


@app.get("/api/agents")
async def api_agents():
    db_path = get_db_path()
    ensure_hit_table()
    with get_db_connection(db_path, row_factory=True) as conn:
        rows = conn.execute(
            "SELECT agent_source, COUNT(*) as count FROM session_summaries WHERE agent_source IS NOT NULL GROUP BY agent_source ORDER BY count DESC"
        ).fetchall()
        agents = [dict(r) for r in rows]
        if agents:
            ids_by_agent = {}
            for a in agents:
                src = a["agent_source"]
                r2 = conn.execute(
                    "SELECT * FROM session_summaries WHERE agent_source = ?",
                    (src,),
                ).fetchall()
                summaries = [dict(s) for s in r2]
                s_ids = [s["session_id"] for s in summaries]
                ph = ",".join("?" for _ in s_ids) if s_ids else ""
                decision_map = {}
                hit_map = {}
                if s_ids:
                    for row in conn.execute(
                        f"SELECT session_id, COUNT(*) as cnt FROM key_decisions WHERE session_id IN ({ph}) GROUP BY session_id",
                        s_ids,
                    ):
                        decision_map[row[0]] = row[1]
                    for row in conn.execute(
                        f"SELECT session_id, SUM(hit_count) as total FROM memory_hits WHERE session_id IN ({ph}) GROUP BY session_id",
                        s_ids,
                    ):
                        hit_map[row[0]] = row[1]
                scores = []
                now = datetime.now()
                for s in summaries:
                    dc = decision_map.get(s["session_id"], 0)
                    hc = hit_map.get(s["session_id"], 0)
                    upd = s.get("updated_at") or s.get("created_at")
                    days_since = (now - datetime.strptime(upd, "%Y-%m-%d %H:%M:%S")).days if upd else None
                    qs = score_memory(s, dc, hit_count=hc, days_since_update=days_since)
                    scores.append(qs["percentage"])
                a["avg_quality"] = round(sum(scores) / len(scores), 1) if scores else 0
                a["memory_count"] = len(summaries)
    return {"agents": agents}


@app.get("/api/hits")
async def api_hits(top: int = Query(10, ge=1, le=50)):
    return {"hits": get_top_hit_memories(top)}


@app.get("/api/hits/{session_id}")
async def api_hits_detail(session_id: str):
    return {"hits": get_hit_stats(session_id)}


@app.get("/api/history/{session_id}")
async def api_history(session_id: str):
    from mcp_server.database import get_summary_history
    db_path = get_db_path()
    history = get_summary_history(db_path, session_id)
    return {"success": True, "data": history}


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


# ── Bulk Operations ──

class BulkActionInput(BaseModel):
    session_ids: List[str] = Field(..., min_length=1)
    new_status: Optional[str] = None
    add_tags: Optional[str] = None
    action: str = Field(..., pattern="^(status|tags|delete)$")

@app.post("/api/bulk")
async def api_bulk(data: BulkActionInput):
    db_path = get_db_path()
    ids = data.session_ids
    placeholders = ",".join("?" for _ in ids)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with get_db_connection(db_path) as conn:
            if data.action == "delete":
                for sid in ids:
                    row = conn.execute("SELECT id FROM session_summaries WHERE session_id = ?", (sid,)).fetchone()
                    if row:
                        conn.execute("DELETE FROM summary_fts WHERE rowid = ?", (row[0],))
                conn.execute(f"DELETE FROM memory_hits WHERE session_id IN ({placeholders})", ids)
                conn.execute(f"DELETE FROM vector_metadata WHERE session_id IN ({placeholders})", ids)
                conn.execute(f"DELETE FROM key_decisions WHERE session_id IN ({placeholders})", ids)
                conn.execute(f"DELETE FROM session_summaries WHERE session_id IN ({placeholders})", ids)
                conn.commit()
                return {"success": True, "message": f"已删除 {len(ids)} 条记忆"}
            elif data.action == "status" and data.new_status:
                conn.execute(
                    f"UPDATE session_summaries SET status = ?, updated_at = ? WHERE session_id IN ({placeholders})",
                    [data.new_status, now] + ids,
                )
                conn.commit()
                return {"success": True, "message": f"已更新 {len(ids)} 条记忆状态为 {data.new_status}"}
            elif data.action == "tags" and data.add_tags:
                tag_suffix = f",{data.add_tags}" if data.add_tags else ""
                conn.execute(
                    f"UPDATE session_summaries SET tags = CASE WHEN tags IS NULL OR tags = '' THEN ? ELSE tags || ? END, updated_at = ? WHERE session_id IN ({placeholders})",
                    [data.add_tags, tag_suffix, now] + ids,
                )
                # Also update FTS index for affected rows
                for sid in ids:
                    row = conn.execute("SELECT id FROM session_summaries WHERE session_id = ?", (sid,)).fetchone()
                    if row:
                        conn.execute("DELETE FROM summary_fts WHERE rowid = ?", (row[0],))
                        r = conn.execute(
                            "SELECT task_title, summary_content, tags FROM session_summaries WHERE session_id = ?",
                            (sid,),
                        ).fetchone()
                        if r:
                            conn.execute(
                                "INSERT INTO summary_fts(rowid, session_id, task_title, summary_content, tags) VALUES (?, ?, ?, ?, ?)",
                                (row[0], sid, r[0], r[1], r[2] or ''),
                            )
                conn.commit()
                return {"success": True, "message": f"已为 {len(ids)} 条记忆添加标签 {data.add_tags}"}
            else:
                raise HTTPException(400, "无效的批量操作")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


# ── Search Misses API ──

@app.get("/api/search-misses")
async def api_search_misses(limit: int = Query(10, ge=1, le=50)):
    return {"misses": get_top_search_misses(limit)}


@app.delete("/api/search-misses")
async def api_clear_search_miss(query: str = Query(...)):
    clear_search_miss(query)
    return {"success": True, "message": f"已清除查询 '{query}' 的记录"}


# ── Export API ──

@app.get("/api/export")
async def api_export(
    request: Request,
    format: str = Query("json"),
    project: Optional[str] = None,
    status: Optional[str] = None,
):
    db_path = get_db_path()
    conditions = []
    params: List[Any] = []
    if project:
        conditions.append("project_name = ?")
        params.append(project)
    if status:
        conditions.append("status = ?")
        params.append(status)
    where = " AND ".join(conditions) if conditions else "1=1"

    with get_db_connection(db_path, row_factory=True) as conn:
        rows = conn.execute(
            f"SELECT * FROM session_summaries WHERE {where} ORDER BY created_at DESC",
            params,
        ).fetchall()
        summaries = [dict(r) for r in rows]
        ids = [s["session_id"] for s in summaries]
        ph = ",".join("?" for _ in ids) if ids else ""
        decision_map: Dict[str, int] = {}
        hit_map: Dict[str, int] = {}
        if ids:
            for row in conn.execute(
                f"SELECT session_id, COUNT(*) as cnt FROM key_decisions WHERE session_id IN ({ph}) GROUP BY session_id",
                ids,
            ):
                decision_map[row[0]] = row[1]
            for row in conn.execute(
                f"SELECT session_id, SUM(hit_count) as total FROM memory_hits WHERE session_id IN ({ph}) GROUP BY session_id",
                ids,
            ):
                hit_map[row[0]] = row[1]

    now = datetime.now()
    for s in summaries:
        dc = decision_map.get(s["session_id"], 0)
        hc = hit_map.get(s["session_id"], 0)
        upd = s.get("updated_at") or s.get("created_at")
        days_since = (now - datetime.strptime(upd, "%Y-%m-%d %H:%M:%S")).days if upd else None
        q = score_memory(s, dc, hit_count=hc, days_since_update=days_since)
        s["quality_score"] = q["percentage"]
        s["quality_level"] = q["level"]
        s["decision_count"] = dc
        s["total_hits"] = hc

    export_fields = [
        "session_id", "task_title", "status", "summary_content",
        "tags", "module", "file_paths", "project_name", "branch_name",
        "next_steps", "created_at", "updated_at",
        "quality_score", "quality_level", "decision_count", "total_hits",
    ]

    if format == "json":
        export = [{k: s.get(k) for k in export_fields} for s in summaries]
        return JSONResponse(
            content={"exported_at": now.strftime("%Y-%m-%d %H:%M:%S"), "count": len(export), "records": export},
            headers={"Content-Disposition": "attachment; filename=ai-memory-export.json"},
        )
    else:
        import csv
        import io
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=export_fields)
        writer.writeheader()
        for s in summaries:
            writer.writerow({k: (s.get(k) or "") for k in export_fields})
        return Response(
            content=output.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=ai-memory-export.csv"},
        )


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
