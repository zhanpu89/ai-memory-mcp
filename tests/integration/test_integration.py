import pytest
import os
import sys
import time
import sqlite3

# 添加当前目录到Python路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from src.mcp_server.server import AiMemoryMcpServer

class TestIntegration:
    @pytest.fixture
    def server(self):
        # 使用临时数据库文件
        test_db_path = "test_integration_ai_memory.db"
        # 清理旧的测试数据库
        if os.path.exists(test_db_path):
            os.remove(test_db_path)
        # 创建新的服务器实例
        server = AiMemoryMcpServer()
        server.db_path = test_db_path
        # 重新初始化数据库
        server._init_db()
        yield server
        # 清理测试数据库
        if os.path.exists(test_db_path):
            os.remove(test_db_path)
    
    def test_full_workflow(self, server):
        """测试完整的工作流程"""
        # 1. 保存摘要
        save_result = server.save_summary(
            session_id="integration-session-1",
            task_title="集成测试任务",
            summary_content="这是集成测试摘要内容",
            status="in_progress",
            next_steps="完成集成测试",
            tags="integration,test",
            module="test_module",
            file_paths="test_integration.py"
        )
        assert save_result["success"] is True
        
        # 2. 添加决策
        decision_result = server.add_decision(
            session_id="integration-session-1",
            decision_type="test_strategy",
            description="使用 pytest 进行测试",
            reasoning="pytest 是 Python 中最流行的测试框架"
        )
        assert decision_result["success"] is True
        
        # 3. 搜索摘要
        search_result = server.search_summaries(query="集成测试")
        assert search_result["success"] is True
        assert len(search_result["data"]) == 1
        assert search_result["data"][0]["session_id"] == "integration-session-1"
        
        # 4. 更新摘要状态
        update_result = server.update_summary(
            session_id="integration-session-1",
            new_status="completed"
        )
        assert update_result["success"] is True
        
        # 5. 获取更新后的摘要
        get_result = server.get_summary_by_id(session_id="integration-session-1")
        assert get_result["success"] is True
        assert get_result["data"]["status"] == "completed"
        
        # 6. 列出最近会话
        list_result = server.list_recent_sessions(limit=5)
        assert list_result["success"] is True
        assert len(list_result["data"]) == 1
        assert list_result["data"][0]["session_id"] == "integration-session-1"
    
    def test_database_integrity(self, server):
        """测试数据库完整性"""
        # 保存多个摘要
        for i in range(3):
            result = server.save_summary(
                session_id=f"integrity-session-{i}",
                task_title=f"完整性测试任务{i}",
                summary_content=f"这是完整性测试摘要内容{i}",
                status="completed"
            )
            assert result["success"] is True
        
        # 验证数据库中的数据
        conn = sqlite3.connect(server.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # 验证 session_summaries 表
        cursor.execute('SELECT COUNT(*) FROM session_summaries')
        count = cursor.fetchone()[0]
        assert count == 3
        
        # 验证索引存在
        cursor.execute("PRAGMA index_list('session_summaries')")
        indexes = [row["name"] for row in cursor.fetchall()]
        assert "idx_session_summaries_tags" in indexes
        assert "idx_session_summaries_module" in indexes
        assert "idx_session_summaries_status" in indexes
        
        conn.close()
    
    def test_error_handling(self, server):
        """测试错误处理"""
        # 测试保存重复 session_id
        server.save_summary(
            session_id="error-session-1",
            task_title="错误处理测试",
            summary_content="这是错误处理测试内容"
        )
        
        duplicate_result = server.save_summary(
            session_id="error-session-1",
            task_title="错误处理测试",
            summary_content="这是错误处理测试内容"
        )
        assert duplicate_result["success"] is False
        # message contains the session_id and a hint to use update_summary
        assert "error-session-1" in duplicate_result["message"] or "已存在" in duplicate_result["message"]
        
        # 测试获取不存在的摘要
        get_result = server.get_summary_by_id(session_id="non-existent-session")
        assert get_result["success"] is False
        assert "non-existent-session" in get_result["message"] or "不存在" in get_result["message"] or "未找到" in get_result["message"]
