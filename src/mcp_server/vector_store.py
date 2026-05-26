"""Vector store initialization, embedding generation and semantic search."""
import os
import logging
from typing import Any, Dict, List, Optional

from .models import (
    DEFAULT_MODEL_NAME,
    DEFAULT_MODEL_SNAPSHOT_HASH,
    HF_MIRROR_ENDPOINT,
    MIN_MODEL_FILE_SIZE_BYTES,
    VECTOR_COLLECTION_NAME,
    VECTOR_DB_DIR_NAME,
    VECTOR_METRIC_SPACE,
    VECTOR_SEARCH_OVERFETCH_FACTOR,
)

logger = logging.getLogger('ai_memory_mcp')

try:
    import chromadb
    from chromadb.config import Settings
    from sentence_transformers import SentenceTransformer
    VECTOR_SUPPORT = True
    logger.info("向量库导入成功")
except Exception as _e:
    logger.warning(f"向量库导入失败: {_e}")
    VECTOR_SUPPORT = False


class VectorStore:
    """Manages ChromaDB collection and SentenceTransformer embedding model."""

    def __init__(self, db_path: str, model_cache_dir: str) -> None:
        self.db_path = db_path
        self.model_cache_dir = model_cache_dir
        self._collection = None
        self._model: Optional[Any] = None
        self._client = None

        if not VECTOR_SUPPORT:
            logger.info("向量支持已禁用")
            return

        self._init(db_path, model_cache_dir)

    # ── public interface ──────────────────────────────────────────────────────

    @property
    def available(self) -> bool:
        return VECTOR_SUPPORT and self._collection is not None and self._model is not None

    def generate_and_store(
        self,
        session_id: str,
        task_title: str,
        summary_content: str,
        tags: Optional[str],
        created_at: str,
        db_store_callback,
    ) -> None:
        """Encode text and upsert into ChromaDB; then persist metadata via callback."""
        if not self.available:
            logger.info("向量支持不可用，跳过 Embedding 生成")
            return
        try:
            text = f"{task_title}\n{summary_content}\n{tags or ''}"
            embedding = self._model.encode(text).tolist()
            vector_id = f"vector_{session_id}"

            self._collection.upsert(
                ids=[vector_id],
                embeddings=[embedding],
                metadatas=[{"session_id": session_id, "task_title": task_title, "created_at": created_at}],
                documents=[text],
            )

            db_store_callback(
                session_id=session_id,
                vector_id=vector_id,
                embedding_dim=len(embedding),
                created_at=created_at,
            )
            logger.info(f"成功为会话 {session_id} 生成并存储 Embedding")
        except Exception as e:
            logger.error(f"生成或存储 Embedding 失败: {e}")

    def query_similar_ids(self, query: str, n_results: int) -> List[str]:
        """Return session_ids ordered by cosine similarity."""
        if not self.available:
            return []
        try:
            query_embedding = self._model.encode(query).tolist()
            results = self._collection.query(
                query_embeddings=[query_embedding],
                n_results=n_results,
            )
            session_ids: List[str] = []
            for metadata in results.get('metadatas', [[]])[0]:
                if metadata and 'session_id' in metadata:
                    session_ids.append(metadata['session_id'])
            return session_ids
        except Exception as e:
            logger.error(f"向量检索失败: {e}")
            return []

    def overfetch_limit(self, limit: int) -> int:
        return int(limit * VECTOR_SEARCH_OVERFETCH_FACTOR) + 1

    def persist(self) -> None:
        # ChromaDB >= 0.4 使用 PersistentClient，写入时自动持久化，无需手动调用 persist()
        if self._client is not None:
            logger.info("向量存储持久化已由 PersistentClient 自动处理")

    # ── private helpers ───────────────────────────────────────────────────────

    def _init(self, db_path: str, model_cache_dir: str) -> None:
        try:
            vector_db_path = os.path.join(os.path.dirname(os.path.abspath(db_path)), VECTOR_DB_DIR_NAME)
            os.makedirs(vector_db_path, exist_ok=True)

            from chromadb import PersistentClient
            self._client = PersistentClient(path=vector_db_path)
            self._collection = self._client.get_or_create_collection(
                name=VECTOR_COLLECTION_NAME,
                metadata={"hnsw:space": VECTOR_METRIC_SPACE},
            )

            local_model_path = os.path.join(
                model_cache_dir,
                "models--sentence-transformers--all-MiniLM-L6-v2",
                "snapshots",
                DEFAULT_MODEL_SNAPSHOT_HASH,
            )
            if self._is_model_valid(local_model_path):
                logger.info(f"加载本地模型: {local_model_path}")
                self._model = SentenceTransformer(local_model_path)
            else:
                logger.info(f"本地模型缺失，从镜像下载: {DEFAULT_MODEL_NAME}")
                if self._download_model(DEFAULT_MODEL_NAME, local_model_path):
                    self._model = SentenceTransformer(local_model_path)
                else:
                    raise FileNotFoundError("模型下载失败，请检查网络或手动运行 scripts/download_model.py")

            logger.info("向量存储初始化成功")
        except Exception as e:
            logger.error(f"向量存储初始化失败: {e}")
            self._collection = None
            self._model = None
            self._client = None

    @staticmethod
    def _is_model_valid(local_model_path: str) -> bool:
        safetensors = os.path.join(local_model_path, "model.safetensors")
        return (
            os.path.exists(local_model_path)
            and os.path.exists(safetensors)
            and os.path.getsize(safetensors) > MIN_MODEL_FILE_SIZE_BYTES
        )

    @staticmethod
    def _download_model(model_name: str, local_model_path: str) -> bool:
        try:
            os.environ["HF_ENDPOINT"] = HF_MIRROR_ENDPOINT
            from huggingface_hub import snapshot_download
            logger.info(f"开始下载模型: {model_name} -> {local_model_path}")
            os.makedirs(local_model_path, exist_ok=True)
            snapshot_download(
                repo_id=model_name,
                local_dir=local_model_path,
                local_dir_use_symlinks=False,
                resume_download=True,
            )
            safetensors = os.path.join(local_model_path, "model.safetensors")
            if os.path.exists(safetensors):
                logger.info(f"模型下载完成，大小: {os.path.getsize(safetensors):,} bytes")
                return True
            logger.error("下载完成但未找到 model.safetensors")
            return False
        except Exception as e:
            logger.error(f"模型下载失败: {e}")
            return False
