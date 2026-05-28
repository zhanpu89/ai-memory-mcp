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

class VectorStore:
    """Manages ChromaDB collection and SentenceTransformer embedding model."""

    def __init__(self, db_path: str, model_cache_dir: str) -> None:
        self.db_path = db_path
        self.model_cache_dir = model_cache_dir
        self._collection = None
        self._model: Optional[Any] = None
        self._client = None

        self._init(db_path, model_cache_dir)

    # ── public interface ──────────────────────────────────────────────────────

    @property
    def available(self) -> bool:
        return self._collection is not None and self._model is not None

    @property
    def model_version(self) -> str:
        return DEFAULT_MODEL_SNAPSHOT_HASH

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
                model_version=self.model_version,
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
        # 设置 AI_MEMORY_DISABLE_VECTOR=1 可在测试或受限环境中跳过向量初始化
        if os.environ.get("AI_MEMORY_DISABLE_VECTOR") == "1":
            logger.info("向量初始化已被 AI_MEMORY_DISABLE_VECTOR 禁用")
            return
        try:
            from chromadb import PersistentClient
            from sentence_transformers import SentenceTransformer
        except Exception as e:
            logger.warning(f"向量库依赖未安装或导入失败: {e}")
            return

        try:
            vector_db_path = os.path.join(os.path.dirname(os.path.abspath(db_path)), VECTOR_DB_DIR_NAME)
            os.makedirs(vector_db_path, exist_ok=True)

            self._client = PersistentClient(path=vector_db_path)
            self._collection = self._client.get_or_create_collection(
                name=VECTOR_COLLECTION_NAME,
                metadata={"hnsw:space": VECTOR_METRIC_SPACE},
            )

            model_candidates = self._resolve_model_paths(model_cache_dir)
            for candidate in model_candidates:
                if self._is_model_valid(candidate):
                    logger.info(f"加载本地模型: {candidate}")
                    self._model = SentenceTransformer(candidate)
                    break
                if self._is_path_writable(candidate):
                    logger.info(f"本地模型缺失，从镜像下载到: {candidate}")
                    if self._download_model(DEFAULT_MODEL_NAME, candidate):
                        self._model = SentenceTransformer(candidate)
                        break
                    logger.warning(f"模型下载失败，尝试下一个路径: {candidate}")
            else:
                logger.error(
                    "所有模型路径均无法使用。请预下载模型或确保 AI_MEMORY_MODEL_PATH 指向可写目录"
                )
                self._collection = None
                self._client = None
                return

            logger.info("向量存储初始化成功")
        except Exception as e:
            logger.error(f"向量存储初始化失败: {e}")
            self._collection = None
            self._model = None
            self._client = None

    def _resolve_model_paths(self, model_cache_dir: str) -> List[str]:
        relative = os.path.join(
            "models--sentence-transformers--all-MiniLM-L6-v2",
            "snapshots",
            DEFAULT_MODEL_SNAPSHOT_HASH,
        )
        paths = [os.path.join(model_cache_dir, relative)]
        data_dir = os.path.join(os.path.dirname(os.path.abspath(self.db_path)), "models")
        fallback = os.path.join(data_dir, relative)
        if fallback != paths[0]:
            paths.append(fallback)
        return paths

    @staticmethod
    def _is_model_valid(local_model_path: str) -> bool:
        safetensors = os.path.join(local_model_path, "model.safetensors")
        return (
            os.path.exists(local_model_path)
            and os.path.exists(safetensors)
            and os.path.getsize(safetensors) > MIN_MODEL_FILE_SIZE_BYTES
        )

    @staticmethod
    def _is_path_writable(path: str) -> bool:
        parent = os.path.dirname(path)
        try:
            os.makedirs(parent, exist_ok=True)
            test_file = os.path.join(parent, ".ai_memory_write_test")
            with open(test_file, "w") as f:
                f.write("test")
            os.remove(test_file)
            return True
        except (OSError, PermissionError):
            return False

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
