import pytest
import os
import sys
import sqlite3

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from src.mcp_server.server import AiMemoryMcpServer
from src.mcp_server.models import (
    SaveSummaryInput, UpdateSummaryInput, SearchSummariesInput,
    GetSummaryByIdInput, ListRecentSessionsInput, AddDecisionInput,
)


def _save(server, session_id, task_title, summary_content, **kwargs):
    return server.save_summary(SaveSummaryInput(
        session_id=session_id,
        task_title=task_title,
        summary_content=summary_content,
        **kwargs,
    ))


class TestIntegration:
    @pytest.fixture
    def server(self, tmp_path):
        test_db_path = str(tmp_path / "test_integration_ai_memory.db")
        os.environ["AI_MEMORY_DB_PATH"] = test_db_path
        os.environ["AI_MEMORY_DISABLE_VECTOR"] = "1"  # skip model download in tests
        server = AiMemoryMcpServer()
        yield server
        os.environ.pop("AI_MEMORY_DB_PATH", None)
        os.environ.pop("AI_MEMORY_DISABLE_VECTOR", None)

    def test_full_workflow(self, server):
        """测试完整的工作流程"""
        # 1. 保存摘要
        save_result = _save(server, "integration-session-1", "集成测试任务",
                            "这是集成测试摘要内容", status="in_progress",
                            next_steps="完成集成测试", tags="integration,test",
                            module="test_module", file_paths="test_integration.py")
        assert save_result["success"] is True

        # 2. 添加决策
        decision_result = server.add_decision(AddDecisionInput(
            session_id="integration-session-1",
            decision_type="test_strategy",
            description="使用 pytest 进行测试",
            reasoning="pytest 是 Python 中最流行的测试框架",
        ))
        assert decision_result["success"] is True

        # 3. 搜索摘要
        search_result = server.search_summaries(SearchSummariesInput(query="集成测试"))
        assert search_result["success"] is True
        assert len(search_result["data"]) == 1
        assert search_result["data"][0]["session_id"] == "integration-session-1"

        # 4. 更新摘要状态
        update_result = server.update_summary(UpdateSummaryInput(
            session_id="integration-session-1", new_status="completed"))
        assert update_result["success"] is True

        # 5. 获取更新后的摘要
        get_result = server.get_summary_by_id(GetSummaryByIdInput(
            session_id="integration-session-1"))
        assert get_result["success"] is True
        assert get_result["data"]["status"] == "completed"

        # 6. 列出最近会话
        list_result = server.list_recent_sessions(ListRecentSessionsInput(limit=5))
        assert list_result["success"] is True
        assert len(list_result["data"]) == 1
        assert list_result["data"][0]["session_id"] == "integration-session-1"

    def test_database_integrity(self, server):
        """测试数据库完整性"""
        for i in range(3):
            result = _save(server, f"integrity-session-{i}",
                           f"完整性测试任务{i}", f"这是完整性测试摘要内容{i}",
                           status="completed")
            assert result["success"] is True

        conn = sqlite3.connect(server.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM session_summaries")
        assert cursor.fetchone()[0] == 3

        cursor.execute("PRAGMA index_list('session_summaries')")
        indexes = {row["name"] for row in cursor.fetchall()}
        assert "idx_session_summaries_tags" in indexes
        assert "idx_session_summaries_module" in indexes
        assert "idx_session_summaries_status" in indexes
        conn.close()

    def test_error_handling(self, server):
        """测试错误处理"""
        _save(server, "error-session-1", "错误处理测试", "这是错误处理测试内容")

        # 重复 session_id 应返回失败
        duplicate_result = _save(server, "error-session-1", "错误处理测试", "这是错误处理测试内容")
        assert duplicate_result["success"] is False
        assert "error-session-1" in duplicate_result["message"] or "已存在" in duplicate_result["message"]

        # 获取不存在的摘要
        get_result = server.get_summary_by_id(GetSummaryByIdInput(session_id="non-existent-session"))
        assert get_result["success"] is False
        assert (
            "non-existent-session" in get_result["message"]
            or "不存在" in get_result["message"]
            or "未找到" in get_result["message"]
        )
