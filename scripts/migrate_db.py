"""
数据库迁移脚本
用于将 v1.0.0 的数据库迁移到 v1.1.0

迁移内容：
1. 为 session_summaries 表添加 project_name 和 branch_name 字段
2. 创建 FTS5 虚拟表 summary_fts
3. 创建新的索引
4. 同步现有数据到 FTS 表
"""

import sqlite3
import os
import sys
import logging
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('db_migration')

class DatabaseMigration:
    def __init__(self, db_path):
        self.db_path = db_path
        self.conn = None
        self.cursor = None
    
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
    
    def get_current_version(self):
        """获取当前数据库版本"""
        try:
            self.cursor.execute("SELECT version FROM db_version WHERE id = 1")
            result = self.cursor.fetchone()
            return result[0] if result else "1.0.0"
        except sqlite3.OperationalError:
            return "1.0.0"
    
    def create_version_table(self):
        """创建版本记录表"""
        try:
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS db_version (
                    id INTEGER PRIMARY KEY,
                    version TEXT NOT NULL,
                    migrated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            self.conn.commit()
            logger.info("版本表已创建")
        except Exception as e:
            logger.error(f"创建版本表失败: {e}")
            raise
    
    def check_column_exists(self, table_name, column_name):
        """检查列是否存在"""
        self.cursor.execute(f"PRAGMA table_info({table_name})")
        columns = [row[1] for row in self.cursor.fetchall()]
        return column_name in columns
    
    def check_index_exists(self, index_name):
        """检查索引是否存在"""
        self.cursor.execute("SELECT name FROM sqlite_master WHERE type='index' AND name=?", (index_name,))
        return self.cursor.fetchone() is not None
    
    def check_fts_table_exists(self):
        """检查 FTS 表是否存在"""
        self.cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='summary_fts'")
        return self.cursor.fetchone() is not None
    
    def migrate_to_1_1_0(self):
        """迁移到 v1.1.0"""
        logger.info("开始数据库迁移...")
        
        # 1. 添加 project_name 字段
        if not self.check_column_exists('session_summaries', 'project_name'):
            self.cursor.execute('''
                ALTER TABLE session_summaries ADD COLUMN project_name TEXT
            ''')
            logger.info("已添加 project_name 字段")
        else:
            logger.info("project_name 字段已存在，跳过")
        
        # 2. 添加 branch_name 字段
        if not self.check_column_exists('session_summaries', 'branch_name'):
            self.cursor.execute('''
                ALTER TABLE session_summaries ADD COLUMN branch_name TEXT
            ''')
            logger.info("已添加 branch_name 字段")
        else:
            logger.info("branch_name 字段已存在，跳过")
        
        # 3. 创建项目索引
        if not self.check_index_exists('idx_session_summaries_project'):
            self.cursor.execute('''
                CREATE INDEX idx_session_summaries_project ON session_summaries (project_name)
            ''')
            logger.info("已创建 idx_session_summaries_project 索引")
        else:
            logger.info("idx_session_summaries_project 索引已存在，跳过")
        
        # 4. 创建分支索引
        if not self.check_index_exists('idx_session_summaries_branch'):
            self.cursor.execute('''
                CREATE INDEX idx_session_summaries_branch ON session_summaries (branch_name)
            ''')
            logger.info("已创建 idx_session_summaries_branch 索引")
        else:
            logger.info("idx_session_summaries_branch 索引已存在，跳过")
        
        # 5. 创建 FTS5 虚拟表
        if not self.check_fts_table_exists():
            self.cursor.execute('''
                CREATE VIRTUAL TABLE summary_fts USING fts5(
                    session_id,
                    task_title,
                    summary_content,
                    tags
                )
            ''')
            logger.info("已创建 summary_fts FTS5 表")
        else:
            logger.info("summary_fts 表已存在，跳过")
        
        # 6. 同步现有数据到 FTS 表
        self.sync_fts_data()
        
        # 7. 提交更改
        self.conn.commit()
        
        # 8. 更新版本号
        self.update_version("1.1.0")
        
        logger.info("数据库迁移完成!")
    
    def sync_fts_data(self):
        """同步现有数据到 FTS 表"""
        logger.info("开始同步数据到 FTS 表...")
        
        self.cursor.execute('''
            SELECT session_id, task_title, summary_content, tags FROM session_summaries
        ''')
        rows = self.cursor.fetchall()
        
        count = 0
        for row in rows:
            try:
                self.cursor.execute('''
                    INSERT INTO summary_fts (session_id, task_title, summary_content, tags)
                    VALUES (?, ?, ?, ?)
                ''', row)
                count += 1
            except Exception as e:
                logger.warning(f"同步数据失败 session_id={row[0]}: {e}")
        
        logger.info(f"已同步 {count} 条数据到 FTS 表")
    
    def update_version(self, version):
        """更新数据库版本"""
        try:
            self.cursor.execute("SELECT version FROM db_version WHERE id = 1")
            result = self.cursor.fetchone()
            
            if result:
                self.cursor.execute("UPDATE db_version SET version = ? WHERE id = 1", (version,))
            else:
                self.cursor.execute("INSERT INTO db_version (id, version) VALUES (1, ?)", (version,))
            
            logger.info(f"数据库版本已更新为: {version}")
        except Exception as e:
            logger.error(f"更新版本失败: {e}")
            raise
    
    def run(self):
        """执行迁移"""
        try:
            self.connect()
            self.create_version_table()
            
            current_version = self.get_current_version()
            logger.info(f"当前数据库版本: {current_version}")
            
            if current_version == "1.0.0":
                self.migrate_to_1_1_0()
            elif current_version == "1.1.0":
                logger.info("数据库已是最新版本，无需迁移")
            else:
                logger.warning(f"未知版本 {current_version}，跳过迁移")
            
            return True
            
        except Exception as e:
            logger.error(f"迁移失败: {e}")
            self.conn.rollback()
            return False
        finally:
            self.close()


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='AI Memory MCP 数据库迁移工具')
    parser.add_argument(
        '--db-path',
        type=str,
        default='ai_memory.db',
        help='数据库文件路径 (默认: ai_memory.db)'
    )
    parser.add_argument(
        '--version',
        action='store_true',
        help='只显示当前数据库版本'
    )
    
    args = parser.parse_args()
    
    migration = DatabaseMigration(args.db_path)
    
    if args.version:
        try:
            migration.connect()
            version = migration.get_current_version()
            print(f"当前数据库版本: {version}")
            migration.close()
        except Exception as e:
            print(f"获取版本失败: {e}")
            sys.exit(1)
    else:
        success = migration.run()
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
