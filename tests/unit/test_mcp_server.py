import pytest
import os
import sys
import sqlite3

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from src.mcp_server.server import AiMemoryMcpServer
from src.mcp_server.models import (
    SaveSummaryInput, UpdateSummaryInput, SearchSummariesInput,
    SearchSummariesFtsInput, GetSummaryByIdInput, ListRecentSessionsInput,
    AddDecisionInput, InitSessionInput, WeeklyReviewInput,
)


def _save(server, session_id, task_title, summary_content, **kwargs):
    """便捷包装：用关键字参数构造 SaveSummaryInput 并调用 save_summary。"""
    return server.save_summary(SaveSummaryInput(
        session_id=session_id,
        task_title=task_title,
        summary_content=summary_content,
        **kwargs,
    ))


class TestAiMemoryMcpServer:
    @pytest.fixture
    def server(self, tmp_path):
        test_db_path = str(tmp_path / "test_ai_memory.db")
        os.environ["AI_MEMORY_DB_PATH"] = test_db_path
        os.environ["AI_MEMORY_DISABLE_VECTOR"] = "1"  # skip model download in tests
        server = AiMemoryMcpServer()
        yield server
        os.environ.pop("AI_MEMORY_DB_PATH", None)
        os.environ.pop("AI_MEMORY_DISABLE_VECTOR", None)

    # ── save_summary ──────────────────────────────────────────────────────────

    def test_save_summary(self, server):
        """测试保存摘要功能"""
        result = _save(server, "test-session-1", "测试任务", "这是测试摘要内容",
                       status="completed", next_steps="下一步计划",
                       tags="test,unit", module="test_module",
                       file_paths="test.py,test.txt")
        assert result["success"] is True
        assert "摘要保存成功" in result["message"]

        # 重复 session_id 应失败
        result = _save(server, "test-session-1", "测试任务", "这是测试摘要内容")
        assert result["success"] is False
        assert "test-session-1" in result["message"] or "已存在" in result["message"]

    def test_save_summary_auto_enrich(self, server):
        """自动标签/路径提取：应从内容中检测 file_paths, tags, module"""
        result = _save(server, "test-auto-enrich-1", "修复登录 API 的认证 Bug",
                       "修复了 src/api/auth/login.py 中的 JWT token 验证错误\n"
                       "在 tests/test_auth.py 中添加了测试用例\n"
                       "使用了 Python 的 unittest 框架",
                       status="completed")
        assert result["success"] is True

        saved = server.get_summary_by_id(GetSummaryByIdInput(session_id="test-auto-enrich-1"))
        assert saved["success"] is True
        data = saved["data"]

        assert data["file_paths"] is not None
        assert "src/api/auth/login.py" in data["file_paths"]
        assert "tests/test_auth.py" in data["file_paths"]

        assert data["tags"] is not None
        assert "api" in data["tags"]
        assert "auth" in data["tags"]
        assert "bugfix" in data["tags"]
        assert "test" in data["tags"]

        assert data["module"] is not None
        assert "src" in data["module"] or "tests" in data["module"]

    def test_save_summary_auto_enrich_does_not_overwrite(self, server):
        """自动提取不覆盖 AI 已提供的字段"""
        result = _save(server, "test-auto-enrich-2", "手动指定标签",
                       "这段内容提到 src/api/route.py 和 auth token",
                       status="completed",
                       tags="manual-tag,explicit",
                       file_paths="custom/path.py")
        assert result["success"] is True

        saved = server.get_summary_by_id(GetSummaryByIdInput(session_id="test-auto-enrich-2"))
        assert saved["success"] is True
        data = saved["data"]

        assert data["tags"] == "manual-tag,explicit"
        assert data["file_paths"] == "custom/path.py"

    def test_search_summaries_context_injection(self, server):
        """搜索时自动注入 init_session 的项目/分支上下文"""
        _save(server, "test-ctx-search-1", "项目任务", "实现了数据库 CRUD",
              status="completed", project_name="ai-memory", branch_name="main",
              tags="test", file_paths="test.py")
        _save(server, "test-ctx-search-2", "其他任务", "另一个任务",
              status="completed", project_name="other-project", branch_name="main",
              tags="test", file_paths="test.py")

        server._last_context = {"project_name": "ai-memory", "branch_name": "main"}

        result = server.search_summaries(SearchSummariesInput(query="CRUD"))
        assert result["success"] is True
        assert len(result["data"]) == 1
        assert result["data"][0]["session_id"] == "test-ctx-search-1"

    def test_save_summary_with_project_info(self, server):
        """测试保存带项目信息的摘要功能"""
        result = _save(server, "test-session-project", "测试任务", "这是测试摘要内容",
                       status="completed", project_name="mcp_ai_memory",
                       branch_name="feature/new-function", tags="test",
                       file_paths="test.py")
        assert result["success"] is True

        saved = server.get_summary_by_id(GetSummaryByIdInput(session_id="test-session-project"))
        assert saved["success"] is True
        assert saved["data"]["project_name"] == "mcp_ai_memory"
        assert saved["data"]["branch_name"] == "feature/new-function"

    # ── update_summary ────────────────────────────────────────────────────────

    def test_update_summary(self, server):
        """测试更新摘要功能"""
        _save(server, "test-session-2", "测试任务", "初始摘要内容", status="in_progress")

        result = server.update_summary(UpdateSummaryInput(
            session_id="test-session-2", new_status="completed"))
        assert result["success"] is True
        assert result["message"] == "摘要更新成功"

        result = server.update_summary(UpdateSummaryInput(
            session_id="test-session-2", updated_content="更新后的摘要内容"))
        assert result["success"] is True

        result = server.update_summary(UpdateSummaryInput(
            session_id="test-session-2", new_status="in_progress",
            updated_content="再次更新的摘要内容"))
        assert result["success"] is True

    # ── search_summaries ──────────────────────────────────────────────────────

    def test_search_summaries(self, server):
        """测试搜索摘要功能"""
        _save(server, "test-session-3", "测试任务1", "这是测试摘要内容1",
              status="completed", tags="test,search", module="module1")
        _save(server, "test-session-4", "测试任务2", "这是测试摘要内容2",
              status="in_progress", tags="test,search", module="module2")

        result = server.search_summaries(SearchSummariesInput(query="测试任务1"))
        assert result["success"] is True
        assert len(result["data"]) >= 1

        result = server.search_summaries(SearchSummariesInput(tags="search"))
        assert result["success"] is True
        assert len(result["data"]) >= 1

        result = server.search_summaries(SearchSummariesInput(module="module1"))
        assert result["success"] is True
        assert len(result["data"]) == 1

        result = server.search_summaries(SearchSummariesInput(status="completed"))
        assert result["success"] is True
        assert len(result["data"]) >= 1

        result = server.search_summaries(SearchSummariesInput(query="测试", tags="search", limit=5))
        assert result["success"] is True

    def test_search_summaries_with_project_filter(self, server):
        """测试按项目筛选搜索"""
        _save(server, "ss-proj-1", "任务1", "项目A的内容", project_name="project_a")
        _save(server, "ss-proj-2", "任务2", "项目B的内容", project_name="project_b")
        _save(server, "ss-proj-3", "任务3", "项目A的另一个任务", project_name="project_a")

        result = server.search_summaries(SearchSummariesInput(project_name="project_a"))
        assert result["success"] is True
        assert len(result["data"]) == 2

    def test_search_summaries_with_branch_filter(self, server):
        """测试按分支筛选搜索"""
        _save(server, "ss-br-1", "任务1", "分支A的内容",
              project_name="test_proj", branch_name="feature-a")
        _save(server, "ss-br-2", "任务2", "分支B的内容",
              project_name="test_proj", branch_name="feature-b")

        result = server.search_summaries(SearchSummariesInput(
            project_name="test_proj", branch_name="feature-a"))
        assert result["success"] is True
        assert len(result["data"]) == 1
        assert result["data"][0]["branch_name"] == "feature-a"

    # ── search_summaries_fts ──────────────────────────────────────────────────

    def test_search_summaries_fts(self, server):
        """测试 FTS5 全文检索"""
        _save(server, "test-session-fts-1", "fts payment task",
              "payment feature for user", tags="payment")
        _save(server, "test-session-fts-2", "fts user profile",
              "user profile management", tags="user")

        result = server.search_summaries_fts(SearchSummariesFtsInput(query="payment"))
        assert result["success"] is True
        assert len(result["data"]) >= 1

        result = server.search_summaries_fts(SearchSummariesFtsInput(query="user"))
        assert result["success"] is True
        assert len(result["data"]) >= 1

    def test_search_summaries_fts_with_filters(self, server):
        """测试带筛选条件的 FTS5 全文检索"""
        _save(server, "test-session-11", "payment task",
              "payment feature development", status="completed",
              project_name="proj1", tags="payment")
        _save(server, "test-session-12", "payment task 2",
              "payment feature development", status="in_progress",
              project_name="proj2", tags="payment")

        result = server.search_summaries_fts(SearchSummariesFtsInput(
            query="payment", project_name="proj1", status="completed"))
        assert result["success"] is True
        assert len(result["data"]) == 1
        assert result["data"][0]["project_name"] == "proj1"

    def test_search_summaries_fts_special_chars(self, server):
        """测试 FTS5 特殊字符不导致异常（句点和连字符）"""
        _save(server, "test-fts-special", "SKILL.md 技能文件",
              "ai-memory 工作流", tags="skill")

        result = server.search_summaries_fts(SearchSummariesFtsInput(query="SKILL.md"))
        assert result["success"] is True

        result = server.search_summaries_fts(SearchSummariesFtsInput(query="ai-memory"))
        assert result["success"] is True

    # ── get_summary_by_id ─────────────────────────────────────────────────────

    def test_get_summary_by_id(self, server):
        """测试根据 ID 获取摘要功能"""
        _save(server, "test-session-13", "测试任务", "这是测试摘要内容")

        result = server.get_summary_by_id(GetSummaryByIdInput(session_id="test-session-13"))
        assert result["success"] is True
        assert result["data"]["session_id"] == "test-session-13"
        assert result["data"]["task_title"] == "测试任务"

        result = server.get_summary_by_id(GetSummaryByIdInput(session_id="non-existent-session"))
        assert result["success"] is False
        assert "non-existent-session" in result["message"] or "未找到" in result["message"]

    # ── list_recent_sessions ──────────────────────────────────────────────────

    def test_list_recent_sessions(self, server):
        """测试列出最近会话功能"""
        for i in range(5):
            _save(server, f"test-session-list-{i}", f"测试任务{i}", f"摘要内容{i}")

        result = server.list_recent_sessions(ListRecentSessionsInput())
        assert result["success"] is True
        assert len(result["data"]) == 5

        result = server.list_recent_sessions(ListRecentSessionsInput(limit=3))
        assert result["success"] is True
        assert len(result["data"]) == 3

    def test_list_recent_sessions_with_project_filter(self, server):
        """测试按项目筛选列出最近会话"""
        _save(server, "test-session-proj1", "任务1", "项目A的内容", project_name="project_a")
        _save(server, "test-session-proj2", "任务2", "项目B的内容", project_name="project_b")
        _save(server, "test-session-proj3", "任务3", "项目A的另一个任务", project_name="project_a")

        result = server.list_recent_sessions(ListRecentSessionsInput(project_name="project_a"))
        assert result["success"] is True
        assert len(result["data"]) == 2
        for item in result["data"]:
            assert item["project_name"] == "project_a"

    def test_list_recent_sessions_with_branch_filter(self, server):
        """测试按分支筛选列出最近会话"""
        _save(server, "test-branch-1", "任务1", "分支A的内容",
              project_name="test_proj", branch_name="feature-a")
        _save(server, "test-branch-2", "任务2", "分支B的内容",
              project_name="test_proj", branch_name="feature-b")

        result = server.list_recent_sessions(ListRecentSessionsInput(
            project_name="test_proj", branch_name="feature-a"))
        assert result["success"] is True
        assert len(result["data"]) == 1
        assert result["data"][0]["branch_name"] == "feature-a"

    # ── add_decision ──────────────────────────────────────────────────────────

    def test_add_decision(self, server):
        """测试添加决策功能"""
        _save(server, "test-session-14", "测试任务", "这是测试摘要内容")

        result = server.add_decision(AddDecisionInput(
            session_id="test-session-14",
            decision_type="tech_stack",
            description="使用 Python 作为开发语言",
            reasoning="Python 拥有丰富的库和生态系统",
        ))
        assert result["success"] is True
        assert result["message"] == "决策添加成功"

        result = server.add_decision(AddDecisionInput(
            session_id="test-session-14",
            decision_type="api_design",
            description="使用 RESTful API 设计",
        ))
        assert result["success"] is True

    # ── maintenance ───────────────────────────────────────────────────────────

    def test_maintenance(self, server):
        """测试数据库维护功能"""
        for i in range(3):
            _save(server, f"test-session-maint-{i}", f"任务{i}", f"摘要内容{i}", status="completed")

        result = server.maintenance()
        assert result["success"] is True
        assert result["message"] == "数据库维护完成"

    # ── init_session / weekly_review ──────────────────────────────────────────

    def test_init_session(self, server):
        """测试会话初始化功能"""
        _save(server, "test-init-1", "进行中任务", "这是一个进行中任务",
              status="in_progress", project_name="test_project")

        result = server.init_session(InitSessionInput(project_name="test_project"))
        assert result["success"] is True
        assert "data" in result
        assert "prompt" in result
        assert "进行中任务" in result["prompt"]

    def test_weekly_review(self, server):
        """测试周报生成功能"""
        _save(server, "test-review-1", "已完成任务", "这是一个已完成任务",
              status="completed", project_name="test_project",
              next_steps="下一步计划")

        result = server.weekly_review(WeeklyReviewInput(project_name="test_project"))
        assert result["success"] is True
        assert "data" in result
        assert "report" in result["data"]
        assert "项目周报" in result["data"]["report"]
        assert "已完成任务" in result["data"]["report"]

    # ── DB schema checks ──────────────────────────────────────────────────────

    def test_database_fts_table_created(self, server):
        """测试 FTS5 表是否正确创建"""
        conn = sqlite3.connect(server.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='summary_fts'")
        result = cursor.fetchone()
        conn.close()
        assert result is not None and result[0] == "summary_fts"

    def test_database_indexes_created(self, server):
        """测试索引是否正确创建"""
        conn = sqlite3.connect(server.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='index'")
        indexes = {row[0] for row in cursor.fetchall()}
        conn.close()
        for expected in [
            "idx_session_summaries_tags",
            "idx_session_summaries_module",
            "idx_session_summaries_status",
            "idx_session_summaries_project",
            "idx_session_summaries_branch",
        ]:
            assert expected in indexes

    def test_project_and_branch_columns_exist(self, server):
        """测试 project_name 和 branch_name 字段是否存在"""
        conn = sqlite3.connect(server.db_path)
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(session_summaries)")
        columns = {row[1] for row in cursor.fetchall()}
        conn.close()
        assert "project_name" in columns
        assert "branch_name" in columns

    def test_vector_metadata_table_and_columns(self, server):
        """测试向量元数据表及字段"""
        conn = sqlite3.connect(server.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='vector_metadata'")
        assert cursor.fetchone() is not None
        cursor.execute("PRAGMA table_info(vector_metadata)")
        columns = {row[1] for row in cursor.fetchall()}
        conn.close()
        for col in ("session_id", "vector_id", "model_name", "embedding_dim", "created_at"):
            assert col in columns

    # ── vector support ────────────────────────────────────────────────────────

    def test_vector_support_state_consistent(self, server):
        """向量存储不可用时，两者均应为 None；可用时均不为 None。"""
        vs = server._vector
        if vs.available:
            assert vs._collection is not None
        else:
            assert vs._collection is None

    def test_save_summary_with_embedding(self, server):
        """保存摘要时若向量可用，应写入 vector_metadata"""
        result = _save(server, "test-embedding-1", "测试 Embedding 生成",
                       "这是一个测试摘要，用于测试 Embedding 生成功能",
                       tags="test,embedding")
        assert result["success"] is True

        conn = sqlite3.connect(server.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM vector_metadata WHERE session_id = ?", ("test-embedding-1",))
        row = cursor.fetchone()
        conn.close()

        if server._vector.available:
            assert row is not None
            assert row[2]  # vector_id
            assert row[3]  # model_name
            assert row[4]  # embedding_dim
        # 向量不可用时 row 为 None，属正常

    def test_search_summaries_with_vector(self, server):
        """向量可用时测试向量检索路径"""
        _save(server, "test-vector-1", "Python 开发", "使用 Python 开发了一个 Web 应用",
              tags="python,web")
        _save(server, "test-vector-2", "Java 开发", "使用 Java 开发了一个后端服务",
              tags="java,backend")

        if server._vector.available:
            result = server.search_summaries(SearchSummariesInput(
                query="Python web development", use_vector=True))
            assert result["success"] is True
            assert len(result["data"]) > 0
