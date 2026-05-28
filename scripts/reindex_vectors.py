"""
Batch vector reindex script.
Regenerates embeddings for all session summaries and upserts into ChromaDB.

Usage:
    python scripts/reindex_vectors.py                          # only missing vectors
    python scripts/reindex_vectors.py --force                  # reindex all (existing + missing)
    python scripts/reindex_vectors.py --db-path ~/.ai-memory/ai_memory.db
    python scripts/reindex_vectors.py --force --batch-size 50
"""

import argparse
import logging
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.mcp_server.database import (
    db_store_vector_metadata,
    get_db_connection,
    init_db,
)
from src.mcp_server.models import DEFAULT_MODEL_SNAPSHOT_HASH
from src.mcp_server.vector_store import VectorStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("reindex_vectors")


def get_db_path(cli_path: str | None) -> str:
    if cli_path:
        return os.path.abspath(cli_path)
    env_path = os.environ.get("AI_MEMORY_DB_PATH")
    if env_path:
        return env_path
    return os.path.join(os.path.expanduser("~"), ".ai-memory", "ai_memory.db")


def main():
    parser = argparse.ArgumentParser(description="Batch vector reindex for AI Memory")
    parser.add_argument("--db-path", help="Path to SQLite database", default=None)
    parser.add_argument("--force", action="store_true", help="Reindex all summaries, not just missing")
    parser.add_argument("--batch-size", type=int, default=20, help="Number of summaries per batch")
    args = parser.parse_args()

    db_path = get_db_path(args.db_path)
    if not os.path.exists(db_path):
        logger.error(f"Database not found: {db_path}")
        sys.exit(1)

    logger.info(f"Database: {db_path}")
    init_db(db_path)

    model_cache_dir = os.environ.get(
        "AI_MEMORY_MODEL_PATH",
        os.path.join(os.path.expanduser("~"), ".ai-memory", "models"),
    )
    os.environ.pop("AI_MEMORY_DISABLE_VECTOR", None)

    logger.info("Initializing VectorStore...")
    vector_store = VectorStore(db_path, model_cache_dir)
    if not vector_store.available:
        logger.error("VectorStore not available (ChromaDB or model failed to load)")
        sys.exit(1)

    current_version = vector_store.model_version
    logger.info(f"Current model version: {DEFAULT_MODEL_SNAPSHOT_HASH}")

    with get_db_connection(db_path, row_factory=True) as conn:
        all_rows = conn.execute(
            "SELECT * FROM session_summaries ORDER BY created_at ASC"
        ).fetchall()

    total = len(all_rows)
    logger.info(f"Total summaries: {total}")

    if args.force:
        to_process = [dict(r) for r in all_rows]
        logger.info(f"Force mode: reindexing all {len(to_process)} summaries")
    else:
        existing = set()
        with get_db_connection(db_path) as conn:
            for row in conn.execute("SELECT session_id FROM vector_metadata WHERE model_version = ?", (current_version,)):
                existing.add(row[0])

        to_process = [dict(r) for r in all_rows if r["session_id"] not in existing]
        logger.info(
            f"Already indexed with current version: {len(existing)}. "
            f"To process: {len(to_process)}"
        )

    if not to_process:
        logger.info("Nothing to reindex.")
        return

    success = 0
    errors = 0
    batch_start = time.time()

    for i, s in enumerate(to_process, 1):
        try:
            created_at = s.get("created_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            vector_store.generate_and_store(
                session_id=s["session_id"],
                task_title=s["task_title"] or "",
                summary_content=s["summary_content"] or "",
                tags=s.get("tags"),
                created_at=created_at,
                db_store_callback=lambda **kw: db_store_vector_metadata(db_path, **kw),
            )
            success += 1
        except Exception as e:
            logger.error(f"[{i}/{total}] Failed for {s['session_id']}: {e}")
            errors += 1

        if i % args.batch_size == 0 or i == len(to_process):
            elapsed = time.time() - batch_start
            rate = args.batch_size / elapsed if elapsed > 0 else 0
            logger.info(
                f"[{i}/{len(to_process)}] "
                f"OK={success} ERR={errors} "
                f"({rate:.1f} items/sec)"
            )
            batch_start = time.time()

    logger.info(f"Done. Success: {success}, Errors: {errors}")


if __name__ == "__main__":
    main()
