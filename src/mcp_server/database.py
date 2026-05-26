"""SQLite database initialization, migration, and CRUD operations."""
import sqlite3
import logging
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, Generator, List, Optional

from .models import DEFAULT_MODEL_NAME

logger = logging.getLogger('ai_memory_mcp')

_CREATE_SESSION_SUMMARIES = '''
CREATE TABLE IF NOT EXISTS session_summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT UNIQUE NOT NULL,
    timestamp DATETIME,
    task_title TEXT NOT NULL,
    status TEXT CHECK(status IN ('completed', 'in_progress', 'blocked', 'abandoned', 'pending')) NOT NULL,
    summary_content TEXT NOT NULL,
    next_steps TEXT,
    tags TEXT,
    module TEXT,
    file_paths TEXT,
    project_name TEXT,
    branch_name TEXT,
    created_at DATETIME,
    updated_at DATETIME
)
'''

_CREATE_KEY_DECISIONS = '''
CREATE TABLE IF NOT EXISTS key_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    decision_type TEXT,
    description TEXT NOT NULL,
    reasoning TEXT,
    FOREIGN KEY (session_id) REFERENCES session_summaries (session_id)
)
'''

_CREATE_SUMMARY_FTS = '''
CREATE VIRTUAL TABLE IF NOT EXISTS summary_fts USING fts5(
    session_id,
    task_title,
    summary_content,
    tags
)
'''

_CREATE_VECTOR_METADATA = '''
CREATE TABLE IF NOT EXISTS vector_metadata (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT UNIQUE NOT NULL,
    vector_id TEXT,
    model_name TEXT,
    embedding_dim INTEGER,
    created_at DATETIME
)
'''


@contextmanager
def get_db_connection(db_path: str, row_factory: bool = False) -> Generator[sqlite3.Connection, None, None]:
    """Context manager for SQLite connections with automatic commit/rollback."""
    conn = sqlite3.connect(db_path)
    if row_factory:
        conn.row_factory = sqlite3.Row
    try:
        yield conn
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def build_filter_conditions(
    conditions: List[str],
    params: List[Any],
    project_name: Optional[str] = None,
    branch_name: Optional[str] = None,
    status: Optional[str] = None,
) -> None:
    """Append WHERE clause fragments and matching params for common filters."""
    if project_name:
        conditions.append("project_name = ?")
        params.append(project_name)
    if branch_name:
        conditions.append("branch_name = ?")
        params.append(branch_name)
    if status:
        conditions.append("status = ?")
        params.append(status)


def success_response(data: Optional[Any] = None, message: str = "操作成功") -> Dict[str, Any]:
    result: Dict[str, Any] = {"success": True, "message": message}
    if data is not None:
        result["data"] = data
    return result


def error_response(message: str) -> Dict[str, Any]:
    return {"success": False, "message": message}


# ============ DB Lifecycle ============

def init_db(db_path: str) -> None:
    """Create all tables, indexes and run migrations."""
    logger.info(f"初始化数据库: {db_path}")
    try:
        with get_db_connection(db_path) as conn:
            cursor = conn.cursor()

            cursor.execute(_CREATE_SESSION_SUMMARIES)
            cursor.execute(_CREATE_KEY_DECISIONS)
            _migrate_add_missing_columns(cursor)

            # Indexes
            for idx_sql in [
                'CREATE INDEX IF NOT EXISTS idx_session_summaries_tags ON session_summaries (tags)',
                'CREATE INDEX IF NOT EXISTS idx_session_summaries_module ON session_summaries (module)',
                'CREATE INDEX IF NOT EXISTS idx_session_summaries_status ON session_summaries (status)',
                'CREATE INDEX IF NOT EXISTS idx_session_summaries_project ON session_summaries (project_name)',
                'CREATE INDEX IF NOT EXISTS idx_session_summaries_branch ON session_summaries (branch_name)',
            ]:
                cursor.execute(idx_sql)

            cursor.execute(_CREATE_SUMMARY_FTS)
            cursor.execute(_CREATE_VECTOR_METADATA)
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_vector_metadata_session_id ON vector_metadata (session_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_vector_metadata_vector_id ON vector_metadata (vector_id)')

            _migrate_status_constraint(cursor)
            conn.commit()

            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = cursor.fetchall()
            logger.info(f"数据库表: {[t[0] for t in tables]}")
            logger.info("数据库初始化成功")
    except Exception as e:
        logger.error(f"数据库初始化失败: {e}")
        raise


def _migrate_add_missing_columns(cursor: sqlite3.Cursor) -> None:
    """Add new columns that may be missing in older DB versions."""
    try:
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='session_summaries'")
        if not cursor.fetchone():
            return
        cursor.execute("PRAGMA table_info(session_summaries)")
        existing = {row[1] for row in cursor.fetchall()}
        for col, col_type in {'project_name': 'TEXT', 'branch_name': 'TEXT'}.items():
            if col not in existing:
                logger.info(f"添加缺失列: {col}")
                cursor.execute(f'ALTER TABLE session_summaries ADD COLUMN {col} {col_type}')
    except Exception as e:
        logger.error(f"列迁移失败: {e}")


def _migrate_status_constraint(cursor: sqlite3.Cursor) -> None:
    """Recreate session_summaries if the status CHECK constraint is outdated."""
    try:
        cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='session_summaries'")
        result = cursor.fetchone()
        if not result or "'pending'" in result[0].lower():
            return

        logger.info("检测到旧版状态约束，开始迁移...")
        cursor.execute("SELECT * FROM session_summaries")
        data = cursor.fetchall()
        cursor.execute("PRAGMA table_info(session_summaries)")
        columns = [row[1] for row in cursor.fetchall()]
        cursor.execute("DROP TABLE session_summaries")
        cursor.execute(_CREATE_SESSION_SUMMARIES.replace("IF NOT EXISTS ", ""))

        if data:
            placeholders = ','.join(['?'] * len(columns))
            col_names = ','.join(columns)
            for row in data:
                cursor.execute(f'INSERT INTO session_summaries ({col_names}) VALUES ({placeholders})', row)
        logger.info("状态约束迁移完成")
    except Exception as e:
        logger.error(f"状态约束迁移失败: {e}")


# ============ CRUD Operations ============

def db_save_summary(
    db_path: str,
    session_id: str,
    task_title: str,
    summary_content: str,
    status: str,
    next_steps: Optional[str],
    tags: Optional[str],
    module: Optional[str],
    file_paths: Optional[str],
    project_name: Optional[str],
    branch_name: Optional[str],
) -> Dict[str, Any]:
    local_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    try:
        with get_db_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT 1 FROM session_summaries WHERE session_id = ?', (session_id,))
            if cursor.fetchone():
                return error_response(f"session_id '{session_id}' 已存在，如需更新请使用 update_summary")

            cursor.execute('''
            INSERT INTO session_summaries
                (session_id, timestamp, task_title, status, summary_content,
                 next_steps, tags, module, file_paths, project_name, branch_name,
                 created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (session_id, local_time, task_title, status, summary_content,
                  next_steps, tags, module, file_paths, project_name, branch_name,
                  local_time, local_time))
            conn.commit()

            cursor.execute('SELECT id FROM session_summaries WHERE session_id = ?', (session_id,))
            row = cursor.fetchone()
            if row:
                cursor.execute(
                    'INSERT INTO summary_fts(rowid, session_id, task_title, summary_content, tags) VALUES (?, ?, ?, ?, ?)',
                    (row[0], session_id, task_title, summary_content, tags or ''),
                )
                conn.commit()

        return success_response(message="摘要保存成功"), local_time
    except sqlite3.IntegrityError as e:
        msg = str(e)
        if "session_id" in msg.lower() or "unique" in msg.lower():
            return error_response(f"session_id '{session_id}' 已存在，如需更新请使用 update_summary"), None
        logger.error(f"保存摘要完整性错误: {e}")
        return error_response(f"数据库约束错误: {e}"), None
    except Exception as e:
        logger.error(f"保存摘要失败: {e}")
        return error_response(str(e)), None


def db_update_summary(
    db_path: str,
    session_id: str,
    new_status: Optional[str],
    updated_content: Optional[str],
) -> Dict[str, Any]:
    if new_status is None and updated_content is None:
        return error_response("至少需要提供 new_status 或 updated_content 之一")

    local_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    updates: List[str] = []
    params: List[Any] = []

    if new_status is not None:
        updates.append("status = ?")
        params.append(new_status)
    if updated_content is not None:
        updates.append("summary_content = ?")
        params.append(updated_content)
    updates.append("updated_at = ?")
    params.append(local_time)
    params.append(session_id)

    sql = f"UPDATE session_summaries SET {', '.join(updates)} WHERE session_id = ?"

    try:
        with get_db_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            if cursor.rowcount == 0:
                return error_response(f"未找到 session_id '{session_id}'，无法更新")
            conn.commit()

            if updated_content is not None:
                cursor.execute('SELECT id FROM session_summaries WHERE session_id = ?', (session_id,))
                row = cursor.fetchone()
                if row:
                    cursor.execute('DELETE FROM summary_fts WHERE rowid = ?', (row[0],))
                    cursor.execute(
                        'SELECT task_title, summary_content, tags FROM session_summaries WHERE session_id = ?',
                        (session_id,)
                    )
                    r = cursor.fetchone()
                    if r:
                        cursor.execute(
                            'INSERT INTO summary_fts(rowid, session_id, task_title, summary_content, tags) VALUES (?, ?, ?, ?, ?)',
                            (row[0], session_id, r[0], r[1], r[2] or ''),
                        )
                conn.commit()
        return success_response(message="摘要更新成功")
    except Exception as e:
        logger.error(f"更新摘要失败: {e}")
        return error_response(str(e))


def db_search_summaries(
    db_path: str,
    query: Optional[str],
    tags: Optional[str],
    module: Optional[str],
    status: Optional[str],
    project_name: Optional[str],
    branch_name: Optional[str],
    use_fts: bool,
    limit: int,
) -> List[Dict[str, Any]]:
    with get_db_connection(db_path, row_factory=True) as conn:
        cursor = conn.cursor()
        if use_fts and query:
            sql = '''
            SELECT s.* FROM session_summaries s
            INNER JOIN summary_fts f ON s.id = f.rowid
            WHERE summary_fts MATCH ?
            '''
            fts_query = f'"{query}"'
            params: List[Any] = [fts_query]
            conditions: List[str] = []
            build_filter_conditions(conditions, params, project_name, branch_name, status)
            if conditions:
                sql += " AND " + " AND ".join(conditions)
            sql += " ORDER BY s.created_at DESC LIMIT ?"
            params.append(limit)
        else:
            sql = "SELECT * FROM session_summaries WHERE 1=1"
            params = []
            if query:
                sql += " AND (task_title LIKE ? OR summary_content LIKE ?)"
                params.extend([f"%{query}%", f"%{query}%"])
            if tags:
                sql += " AND tags LIKE ?"
                params.append(f"%{tags}%")
            if module:
                sql += " AND module LIKE ?"
                params.append(f"%{module}%")
            conditions = []
            build_filter_conditions(conditions, params, project_name, branch_name, status)
            if conditions:
                sql += " AND " + " AND ".join(conditions)
            sql += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)

        cursor.execute(sql, params)
        return [dict(row) for row in cursor.fetchall()]


def db_get_summary_by_id(db_path: str, session_id: str) -> Optional[Dict[str, Any]]:
    with get_db_connection(db_path, row_factory=True) as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM session_summaries WHERE session_id = ?', (session_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def db_list_recent_sessions(
    db_path: str,
    limit: int,
    project_name: Optional[str],
    branch_name: Optional[str],
) -> List[Dict[str, Any]]:
    with get_db_connection(db_path, row_factory=True) as conn:
        cursor = conn.cursor()
        sql = "SELECT * FROM session_summaries WHERE 1=1"
        params: List[Any] = []
        conditions: List[str] = []
        build_filter_conditions(conditions, params, project_name, branch_name)
        if conditions:
            sql += " AND " + " AND ".join(conditions)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        cursor.execute(sql, params)
        return [dict(row) for row in cursor.fetchall()]


def db_add_decision(
    db_path: str,
    session_id: str,
    decision_type: str,
    description: str,
    reasoning: Optional[str],
) -> Dict[str, Any]:
    try:
        with get_db_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                'INSERT INTO key_decisions (session_id, decision_type, description, reasoning) VALUES (?, ?, ?, ?)',
                (session_id, decision_type, description, reasoning),
            )
            conn.commit()
        return success_response(message="决策添加成功")
    except Exception as e:
        logger.error(f"添加决策失败: {e}")
        return error_response(str(e))


def db_maintenance(db_path: str) -> Dict[str, Any]:
    try:
        with get_db_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT INTO summary_fts(summary_fts) VALUES('rebuild')")
            conn.commit()
            cursor.execute("VACUUM")
            conn.commit()
        return success_response(message="数据库维护完成")
    except Exception as e:
        logger.error(f"维护操作失败: {e}")
        return error_response(str(e))


def db_init_session(
    db_path: str,
    three_days_ago: str,
    max_tasks: int,
    project_name: Optional[str],
    branch_name: Optional[str],
) -> List[Dict[str, Any]]:
    with get_db_connection(db_path, row_factory=True) as conn:
        cursor = conn.cursor()
        sql = "SELECT * FROM session_summaries WHERE status = 'in_progress' AND created_at >= ?"
        params: List[Any] = [three_days_ago]
        conditions: List[str] = []
        build_filter_conditions(conditions, params, project_name, branch_name)
        if conditions:
            sql += " AND " + " AND ".join(conditions)
        sql += f" ORDER BY created_at DESC LIMIT {max_tasks}"
        cursor.execute(sql, params)
        return [dict(row) for row in cursor.fetchall()]


def db_weekly_review(
    db_path: str,
    week_start: str,
    project_name: Optional[str],
    branch_name: Optional[str],
) -> tuple:
    """Return (completed_tasks, key_decisions) for the current week."""
    with get_db_connection(db_path, row_factory=True) as conn:
        cursor = conn.cursor()

        sql = "SELECT * FROM session_summaries WHERE status = 'completed' AND created_at >= ?"
        params: List[Any] = [week_start]
        conditions: List[str] = []
        build_filter_conditions(conditions, params, project_name, branch_name)
        if conditions:
            sql += " AND " + " AND ".join(conditions)
        sql += " ORDER BY created_at DESC"
        cursor.execute(sql, params)
        completed_tasks = [dict(row) for row in cursor.fetchall()]

        decision_sql = (
            "SELECT * FROM key_decisions WHERE session_id IN "
            "(SELECT session_id FROM session_summaries WHERE created_at >= ?"
        )
        d_params: List[Any] = [week_start]
        d_conditions: List[str] = []
        build_filter_conditions(d_conditions, d_params, project_name, branch_name)
        if d_conditions:
            decision_sql += " AND " + " AND ".join(d_conditions)
        decision_sql += ")"
        cursor.execute(decision_sql, d_params)
        key_decisions = [dict(row) for row in cursor.fetchall()]

    return completed_tasks, key_decisions


def db_fts_search(
    db_path: str,
    query: str,
    project_name: Optional[str],
    branch_name: Optional[str],
    status: Optional[str],
    limit: int,
) -> List[Dict[str, Any]]:
    with get_db_connection(db_path, row_factory=True) as conn:
        cursor = conn.cursor()
        sql = '''
        SELECT s.* FROM session_summaries s
        INNER JOIN summary_fts f ON s.id = f.rowid
        WHERE summary_fts MATCH ?
        '''
        fts_query = f'"{query}"'
        params: List[Any] = [fts_query]
        conditions: List[str] = []
        build_filter_conditions(conditions, params, project_name, branch_name, status)
        if conditions:
            sql += " AND " + " AND ".join(conditions)
        sql += " ORDER BY s.created_at DESC LIMIT ?"
        params.append(limit)
        cursor.execute(sql, params)
        return [dict(row) for row in cursor.fetchall()]


def db_store_vector_metadata(
    db_path: str,
    session_id: str,
    vector_id: str,
    embedding_dim: int,
    created_at: str,
) -> None:
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            'INSERT OR REPLACE INTO vector_metadata (session_id, vector_id, model_name, embedding_dim, created_at) VALUES (?, ?, ?, ?, ?)',
            (session_id, vector_id, DEFAULT_MODEL_NAME, embedding_dim, created_at),
        )
        conn.commit()


def db_vector_search_by_ids(
    db_path: str,
    session_ids: List[str],
    project_name: Optional[str],
    branch_name: Optional[str],
    status: Optional[str],
) -> List[Dict[str, Any]]:
    if not session_ids:
        return []
    with get_db_connection(db_path, row_factory=True) as conn:
        cursor = conn.cursor()
        placeholders = ','.join(['?'] * len(session_ids))
        sql = f"SELECT * FROM session_summaries WHERE session_id IN ({placeholders})"
        params: List[Any] = list(session_ids)
        conditions: List[str] = []
        build_filter_conditions(conditions, params, project_name, branch_name, status)
        if conditions:
            sql += " AND " + " AND ".join(conditions)
        sql += " ORDER BY created_at DESC"
        cursor.execute(sql, params)
        return [dict(row) for row in cursor.fetchall()]
