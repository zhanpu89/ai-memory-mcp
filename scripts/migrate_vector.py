"""
向量数据迁移脚本
用于将现有的会话摘要迁移到向量存储系统

功能：
1. 扫描现有会话摘要
2. 为每个摘要生成 Embedding
3. 存储到 ChromaDB
4. 保存向量元数据到 SQLite
"""

import sqlite3
import os
import logging
from datetime import datetime

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('vector_migration')

class VectorMigration:
    def __init__(self, db_path):
        self.db_path = db_path
        self.conn = None
        self.cursor = None
        self.vector_store = None
        self.embedding_model = None
    
    def connect(self):
        """连接到数据库"""
        if not os.path.exists(self.db_path):
            raise FileNotFoundError(f"数据库文件不存在: {self.db_path}")
        
        self.conn = sqlite3.connect(self.db_path)
        self.cursor = self.conn.cursor()
        logger.info(f"已连接到数据库: {self.db_path}")
    
    def close(self):
        """关闭数据库连接"""
        if self.conn:
            self.conn.close()
            logger.info("数据库连接已关闭")
    
    def init_vector_store(self):
        """初始化向量存储系统"""
        try:
            from chromadb import PersistentClient
            from sentence_transformers import SentenceTransformer
            
            # 创建向量存储目录
            vector_db_path = os.path.join(os.path.dirname(os.path.abspath(self.db_path)), "vector_db")
            os.makedirs(vector_db_path, exist_ok=True)
            
            # 初始化 ChromaDB
            self.vector_store = PersistentClient(path=vector_db_path)
            
            # 创建或获取集合
            self.collection = self.vector_store.get_or_create_collection(
                name="session_summaries",
                metadata={"hnsw:space": "cosine"}
            )
            
            # 加载 Embedding 模型
            self.embedding_model = SentenceTransformer("all-MiniLM-L6-v2")
            logger.info("向量存储系统初始化成功")
            logger.info(f"Embedding 模型: all-MiniLM-L6-v2")
            logger.info(f"向量维度: {self.embedding_model.get_sentence_embedding_dimension()}")
            
        except Exception as e:
            logger.error(f"向量存储系统初始化失败: {e}")
            self.vector_store = None
            self.embedding_model = None
    
    def get_existing_summaries(self):
        """获取所有现有会话摘要"""
        try:
            # 只获取没有向量元数据的摘要
            self.cursor.execute('''
                SELECT s.* FROM session_summaries s
                LEFT JOIN vector_metadata v ON s.session_id = v.session_id
                WHERE v.session_id IS NULL
            ''')
            
            results = []
            for row in self.cursor.fetchall():
                results.append({
                    'session_id': row[1],
                    'task_title': row[3],
                    'summary_content': row[5],
                    'tags': row[7],
                    'created_at': row[12]
                })
            
            logger.info(f"找到 {len(results)} 个需要迁移的摘要")
            return results
            
        except Exception as e:
            logger.error(f"获取摘要失败: {e}")
            return []
    
    def generate_and_store_embedding(self, summary):
        """为摘要生成并存储 Embedding"""
        try:
            # 构建用于生成 Embedding 的文本
            embedding_text = f"{summary['task_title']}\n{summary['summary_content']}\n{summary.get('tags', '')}"
            
            # 生成 Embedding
            embedding = self.embedding_model.encode(embedding_text).tolist()
            embedding_dim = len(embedding)
            
            # 生成向量 ID
            vector_id = f"vector_{summary['session_id']}"
            
            # 存储到 ChromaDB
            self.collection.add(
                ids=[vector_id],
                embeddings=[embedding],
                metadatas=[{
                    "session_id": summary['session_id'],
                    "task_title": summary['task_title'],
                    "created_at": summary['created_at']
                }],
                documents=[embedding_text]
            )
            
            # 保存向量元数据到 SQLite
            self.cursor.execute('''
            INSERT OR REPLACE INTO vector_metadata 
            (session_id, vector_id, model_name, embedding_dim, created_at)
            VALUES (?, ?, ?, ?, ?)
            ''', (summary['session_id'], vector_id, "all-MiniLM-L6-v2", embedding_dim, summary['created_at']))
            
            self.conn.commit()
            
            logger.info(f"成功为会话 {summary['session_id']} 生成并存储 Embedding")
            return True
            
        except Exception as e:
            logger.error(f"生成或存储 Embedding 失败: {e}")
            return False
    
    def run(self):
        """执行迁移"""
        try:
            self.connect()
            self.init_vector_store()
            
            if not self.vector_store or not self.embedding_model:
                logger.error("向量存储系统初始化失败，无法继续迁移")
                return False
            
            summaries = self.get_existing_summaries()
            
            success_count = 0
            total_count = len(summaries)
            
            for i, summary in enumerate(summaries, 1):
                logger.info(f"处理摘要 {i}/{total_count}: {summary['session_id']}")
                if self.generate_and_store_embedding(summary):
                    success_count += 1
            
            logger.info(f"迁移完成: 成功 {success_count}/{total_count}")
            return True
            
        except Exception as e:
            logger.error(f"迁移失败: {e}")
            if self.conn:
                self.conn.rollback()
            return False
        finally:
            self.close()


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='AI Memory 向量数据迁移工具')
    parser.add_argument(
        '--db-path',
        type=str,
        default='ai_memory.db',
        help='数据库文件路径 (默认: ai_memory.db)'
    )
    
    args = parser.parse_args()
    
    migration = VectorMigration(args.db_path)
    success = migration.run()
    
    if success:
        logger.info("迁移成功完成！")
    else:
        logger.error("迁移失败，请检查日志")


if __name__ == "__main__":
    main()
