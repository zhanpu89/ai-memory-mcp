import pytest
import os
import sys
import sqlite3

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from src.mcp_server.server import AiMemoryMcpServer

class TestAiMemoryMcpServer:
    @pytest.fixture
    def server(self):
        test_db_path = "test_ai_memory.db"
        # 清理所有可能的测试数据库文件
        if os.path.exists(test_db_path):
            os.remove(test_db_path)
        # 设置环境变量指定测试数据库路径
        os.environ["AI_MEMORY_DB_PATH"] = test_db_path
        # 创建新的服务器实例
        server = AiMemoryMcpServer()
        # 确保使用测试数据库
        server.db_path = test_db_path
        # 重新初始化数据库
        server._init_db()
        yield server
        # 清理测试数据库
        if os.path.exists(test_db_path):
            os.remove(test_db_path)
        # 清理环境变量
        if "AI_MEMORY_DB_PATH" in os.environ:
            del os.environ["AI_MEMORY_DB_PATH"]
    
    def test_save_summary(self, server):
        """测试保存摘要功能"""
        result = server.save_summary(
            session_id="test-session-1",
            task_title="测试任务",
            summary_content="这是测试摘要内容",
            status="completed",
            next_steps="下一步计划",
            tags="test,unit",
            module="test_module",
            file_paths="test.py,test.txt"
        )
        assert result["success"] is True
        assert result["message"] == "摘要保存成功"
        
        result = server.save_summary(
            session_id="test-session-1",
            task_title="测试任务",
            summary_content="这是测试摘要内容"
        )
        assert result["success"] is False
        assert "test-session-1" in result["message"] or "已存在" in result["message"]
    
    def test_save_summary_with_project_info(self, server):
        """测试保存带项目信息的摘要功能"""
        result = server.save_summary(
            session_id="test-session-project",
            task_title="测试任务",
            summary_content="这是测试摘要内容",
            status="completed",
            project_name="mcp_ai_memory",
            branch_name="feature/new-function",
            tags="test",
            file_paths="test.py"
        )
        assert result["success"] is True
        
        saved = server.get_summary_by_id("test-session-project")
        assert saved["success"] is True
        assert saved["data"]["project_name"] == "mcp_ai_memory"
        assert saved["data"]["branch_name"] == "feature/new-function"
    
    def test_update_summary(self, server):
        """测试更新摘要功能"""
        server.save_summary(
            session_id="test-session-2",
            task_title="测试任务",
            summary_content="初始摘要内容",
            status="in_progress"
        )
        
        result = server.update_summary(
            session_id="test-session-2",
            new_status="completed"
        )
        assert result["success"] is True
        assert result["message"] == "摘要更新成功"
        
        result = server.update_summary(
            session_id="test-session-2",
            updated_content="更新后的摘要内容"
        )
        assert result["success"] is True
        assert result["message"] == "摘要更新成功"
        
        result = server.update_summary(
            session_id="test-session-2",
            new_status="in_progress",
            updated_content="再次更新的摘要内容"
        )
        assert result["success"] is True
        assert result["message"] == "摘要更新成功"
    
    def test_search_summaries(self, server):
        """测试搜索摘要功能"""
        server.save_summary(
            session_id="test-session-3",
            task_title="测试任务1",
            summary_content="这是测试摘要内容1",
            status="completed",
            tags="test,search",
            module="module1"
        )
        server.save_summary(
            session_id="test-session-4",
            task_title="测试任务2",
            summary_content="这是测试摘要内容2",
            status="in_progress",
            tags="test,search",
            module="module2"
        )
        
        result = server.search_summaries(query="测试任务1")
        assert result["success"] is True
        assert len(result["data"]) == 1
        assert result["data"][0]["task_title"] == "测试任务1"
        
        result = server.search_summaries(tags="search")
        assert result["success"] is True
        assert len(result["data"]) == 2
        
        result = server.search_summaries(module="module1")
        assert result["success"] is True
        assert len(result["data"]) == 1
        assert result["data"][0]["module"] == "module1"
        
        result = server.search_summaries(status="completed")
        assert result["success"] is True
        assert len(result["data"]) == 1
        assert result["data"][0]["status"] == "completed"
        
        result = server.search_summaries(query="测试", tags="search", limit=5)
        assert result["success"] is True
        assert len(result["data"]) == 2
    
    def test_search_summaries_with_project_filter(self, server):
        """测试按项目筛选搜索摘要功能"""
        server.save_summary(
            session_id="test-session-5",
            task_title="任务A",
            summary_content="项目A的摘要",
            status="completed",
            project_name="project_a"
        )
        server.save_summary(
            session_id="test-session-6",
            task_title="任务B",
            summary_content="项目B的摘要",
            status="completed",
            project_name="project_b"
        )
        
        result = server.search_summaries(project_name="project_a")
        assert result["success"] is True
        assert len(result["data"]) == 1
        assert result["data"][0]["task_title"] == "任务A"
        assert result["data"][0]["project_name"] == "project_a"
    
    def test_search_summaries_with_branch_filter(self, server):
        """测试按分支筛选搜索摘要功能"""
        server.save_summary(
            session_id="test-session-7",
            task_title="任务1",
            summary_content="分支1的摘要",
            status="completed",
            project_name="test_project",
            branch_name="feature-a"
        )
        server.save_summary(
            session_id="test-session-8",
            task_title="任务2",
            summary_content="分支2的摘要",
            status="completed",
            project_name="test_project",
            branch_name="feature-b"
        )
        
        result = server.search_summaries(project_name="test_project", branch_name="feature-a")
        assert result["success"] is True
        assert len(result["data"]) == 1
        assert result["data"][0]["branch_name"] == "feature-a"
    
    def test_search_summaries_fts(self, server):
        """测试FTS5全文检索功能"""
        server.save_summary(
            session_id="test-session-9",
            task_title="payment module",
            summary_content="implement payment with alipay and wechat",
            status="completed",
            tags="payment,alipay,wechat"
        )
        server.save_summary(
            session_id="test-session-10",
            task_title="user module",
            summary_content="implement user registration and login",
            status="completed",
            tags="user,auth"
        )
        
        result = server.search_summaries_fts(query="payment")
        assert result["success"] is True
        assert len(result["data"]) >= 1
        
        result = server.search_summaries_fts(query="user")
        assert result["success"] is True
        assert len(result["data"]) >= 1
    
    def test_search_summaries_fts_with_filters(self, server):
        """测试带筛选条件的FTS5全文检索"""
        server.save_summary(
            session_id="test-session-11",
            task_title="payment task",
            summary_content="payment feature development",
            status="completed",
            project_name="proj1",
            tags="payment"
        )
        server.save_summary(
            session_id="test-session-12",
            task_title="payment task 2",
            summary_content="payment feature development",
            status="in_progress",
            project_name="proj2",
            tags="payment"
        )
        
        result = server.search_summaries_fts(
            query="payment",
            project_name="proj1",
            status="completed"
        )
        assert result["success"] is True
        assert len(result["data"]) == 1
        assert result["data"][0]["project_name"] == "proj1"
    
    def test_get_summary_by_id(self, server):
        """测试根据 ID 获取摘要功能"""
        server.save_summary(
            session_id="test-session-13",
            task_title="测试任务",
            summary_content="这是测试摘要内容"
        )
        
        result = server.get_summary_by_id(session_id="test-session-13")
        assert result["success"] is True
        assert result["data"]["session_id"] == "test-session-13"
        assert result["data"]["task_title"] == "测试任务"
        
        result = server.get_summary_by_id(session_id="non-existent-session")
        assert result["success"] is False
        assert "non-existent-session" in result["message"] or "未找到" in result["message"]
    
    def test_list_recent_sessions(self, server):
        """测试列出最近会话功能"""
        for i in range(5):
            server.save_summary(
                session_id=f"test-session-list-{i}",
                task_title=f"测试任务{i}",
                summary_content=f"这是测试摘要内容{i}"
            )
        
        result = server.list_recent_sessions()
        assert result["success"] is True
        assert len(result["data"]) == 5
        
        result = server.list_recent_sessions(limit=3)
        assert result["success"] is True
        assert len(result["data"]) == 3
    
    def test_list_recent_sessions_with_project_filter(self, server):
        """测试按项目筛选列出最近会话功能"""
        server.save_summary(
            session_id="test-session-proj1",
            task_title="任务1",
            summary_content="项目A的内容",
            project_name="project_a"
        )
        server.save_summary(
            session_id="test-session-proj2",
            task_title="任务2",
            summary_content="项目B的内容",
            project_name="project_b"
        )
        server.save_summary(
            session_id="test-session-proj3",
            task_title="任务3",
            summary_content="项目A的另一个任务",
            project_name="project_a"
        )
        
        result = server.list_recent_sessions(project_name="project_a")
        assert result["success"] is True
        assert len(result["data"]) == 2
        for item in result["data"]:
            assert item["project_name"] == "project_a"
    
    def test_list_recent_sessions_with_branch_filter(self, server):
        """测试按分支筛选列出最近会话功能"""
        server.save_summary(
            session_id="test-session-branch1",
            task_title="任务1",
            summary_content="分支A的内容",
            project_name="test_proj",
            branch_name="feature-a"
        )
        server.save_summary(
            session_id="test-session-branch2",
            task_title="任务2",
            summary_content="分支B的内容",
            project_name="test_proj",
            branch_name="feature-b"
        )
        
        result = server.list_recent_sessions(project_name="test_proj", branch_name="feature-a")
        assert result["success"] is True
        assert len(result["data"]) == 1
        assert result["data"][0]["branch_name"] == "feature-a"
    
    def test_add_decision(self, server):
        """测试添加决策功能"""
        server.save_summary(
            session_id="test-session-14",
            task_title="测试任务",
            summary_content="这是测试摘要内容"
        )
        
        result = server.add_decision(
            session_id="test-session-14",
            decision_type="tech_stack",
            description="使用 Python 作为开发语言",
            reasoning="Python 拥有丰富的库和生态系统"
        )
        assert result["success"] is True
        assert result["message"] == "决策添加成功"
        
        result = server.add_decision(
            session_id="test-session-14",
            decision_type="api_design",
            description="使用 RESTful API 设计"
        )
        assert result["success"] is True
        assert result["message"] == "决策添加成功"
    
    def test_maintenance(self, server):
        """测试数据库维护功能"""
        for i in range(3):
            server.save_summary(
                session_id=f"test-session-maint-{i}",
                task_title=f"任务{i}",
                summary_content=f"摘要内容{i}",
                status="completed"
            )
        
        result = server.maintenance()
        assert result["success"] is True
        assert result["message"] == "数据库维护完成"
    
    def test_database_fts_table_created(self, server):
        """测试FTS5表是否正确创建"""
        conn = sqlite3.connect(server.db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='summary_fts'")
        result = cursor.fetchone()
        
        assert result is not None
        assert result[0] == 'summary_fts'
        
        conn.close()
    
    def test_database_indexes_created(self, server):
        """测试索引是否正确创建"""
        conn = sqlite3.connect(server.db_path)
        cursor = conn.cursor()
        
        expected_indexes = [
            'idx_session_summaries_tags',
            'idx_session_summaries_module',
            'idx_session_summaries_status',
            'idx_session_summaries_project',
            'idx_session_summaries_branch'
        ]
        
        cursor.execute("SELECT name FROM sqlite_master WHERE type='index'")
        indexes = [row[0] for row in cursor.fetchall()]
        
        for expected_index in expected_indexes:
            assert expected_index in indexes
        
        conn.close()
    
    def test_project_and_branch_columns_exist(self, server):
        """测试project_name和branch_name字段是否存在"""
        conn = sqlite3.connect(server.db_path)
        cursor = conn.cursor()
        
        cursor.execute("PRAGMA table_info(session_summaries)")
        columns = {row[1] for row in cursor.fetchall()}
        
        assert 'project_name' in columns
        assert 'branch_name' in columns
        
        conn.close()
    
    def test_vector_metadata_table_exists(self, server):
        """测试向量元数据表是否存在"""
        conn = sqlite3.connect(server.db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='vector_metadata'")
        result = cursor.fetchone()
        
        assert result is not None
        assert result[0] == 'vector_metadata'
        
        conn.close()
    
    def test_vector_metadata_columns_exist(self, server):
        """测试向量元数据表字段是否存在"""
        conn = sqlite3.connect(server.db_path)
        cursor = conn.cursor()
        
        cursor.execute("PRAGMA table_info(vector_metadata)")
        columns = {row[1] for row in cursor.fetchall()}
        
        assert 'session_id' in columns
        assert 'vector_id' in columns
        assert 'model_name' in columns
        assert 'embedding_dim' in columns
        assert 'created_at' in columns
        
        conn.close()
    
    def test_init_session(self, server):
        """测试会话初始化功能"""
        # 保存一个进行中任务
        server.save_summary(
            session_id="test-init-1",
            task_title="进行中任务",
            summary_content="这是一个进行中任务",
            status="in_progress",
            project_name="test_project"
        )
        
        # 测试初始化会话
        result = server.init_session(project_name="test_project")
        assert result["success"] is True
        assert "data" in result
        assert "prompt" in result
        assert "进行中任务" in result["prompt"]
    
    def test_weekly_review(self, server):
        """测试周报生成功能"""
        # 保存一个已完成任务
        server.save_summary(
            session_id="test-review-1",
            task_title="已完成任务",
            summary_content="这是一个已完成任务",
            status="completed",
            project_name="test_project",
            next_steps="下一步计划"
        )
        
        # 测试生成周报
        result = server.weekly_review(project_name="test_project")
        assert result["success"] is True
        assert "data" in result
        assert "report" in result["data"]
        assert "项目周报" in result["data"]["report"]
        assert "已完成任务" in result["data"]["report"]
    
    def test_vector_support(self, server):
        """测试向量支持是否可用"""
        # 向量存储系统取决于环境是否有模型，在没有网络的环境下可能为 None
        from src.mcp_server.server import VECTOR_SUPPORT
        if VECTOR_SUPPORT and server.vector_store is not None:
            assert server.embedding_model is not None
        # 当向量库导入成功但模型不可用时，两者均应为 None
        if server.vector_store is None:
            assert server.embedding_model is None
    
    def test_save_summary_with_embedding(self, server):
        """测试保存摘要时是否生成 Embedding"""
        result = server.save_summary(
            session_id="test-embedding-1",
            task_title="测试 Embedding 生成",
            summary_content="这是一个测试摘要，用于测试 Embedding 生成功能",
            tags="test,embedding"
        )
        assert result["success"] is True
        
        # 检查向量元数据是否保存
        conn = sqlite3.connect(server.db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM vector_metadata WHERE session_id = ?", ("test-embedding-1",))
        result = cursor.fetchone()
        
        if result:
            assert result[2]  # vector_id
            assert result[3]  # model_name (full name e.g. sentence-transformers/all-MiniLM-L6-v2)
            assert result[4]  # embedding_dim
        
        conn.close()
    
    def test_search_summaries_with_vector(self, server):
        """测试向量检索功能"""
        # 保存测试数据
        server.save_summary(
            session_id="test-vector-search-1",
            task_title="Python 开发",
            summary_content="使用 Python 开发了一个 Web 应用",
            tags="python,web"
        )
        
        server.save_summary(
            session_id="test-vector-search-2",
            task_title="Java 开发",
            summary_content="使用 Java 开发了一个后端服务",
            tags="java,backend"
        )
        
        # 测试向量检索
        from src.mcp_server.server import VECTOR_SUPPORT
        if VECTOR_SUPPORT and server.vector_store:
            result = server.search_summaries(
                query="Python web development",
                use_vector=True
            )
            assert result["success"] is True
            assert len(result["data"]) > 0

