"""AI Memory MCP Server — tool registration layer."""
import logging
import os
import sys
from datetime import datetime, timedelta
from typing import Any, Dict

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .database import (
    db_add_decision,
    db_fts_search,
    db_get_summary_by_id,
    db_init_session,
    db_list_recent_sessions,
    db_maintenance,
    db_save_summary,
    db_search_summaries,
    db_store_vector_metadata,
    db_update_summary,
    db_vector_search_by_ids,
    db_weekly_review,
    error_response,
    init_db,
    success_response,
)
from .models import (
    AddDecisionInput,
    DEFAULT_DB_DIR_NAME,
    DEFAULT_ENV_FILE_NAME,
    DEFAULT_HOST,
    DEFAULT_PORT,
    ENV_VAR_DB_PATH,
    ENV_VAR_HOST,
    ENV_VAR_MODEL_PATH,
    ENV_VAR_PORT,
    GetSummaryByIdInput,
    INIT_SESSION_DAYS_BACK,
    INIT_SESSION_MAX_TASKS,
    InitSessionInput,
    ListRecentSessionsInput,
    SaveSummaryInput,
    SearchSummariesFtsInput,
    SearchSummariesInput,
    UpdateSummaryInput,
    WeeklyReviewInput,
)
from .vector_store import VECTOR_SUPPORT, VectorStore

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger('ai_memory_mcp')


class AiMemoryMcpServer(FastMCP):
    def __init__(self) -> None:
        from dotenv import load_dotenv
        home = os.path.expanduser("~")
        home_env = os.path.join(home, DEFAULT_DB_DIR_NAME, DEFAULT_ENV_FILE_NAME)
        if os.path.exists(home_env):
            load_dotenv(home_env, override=True)
            logger.info(f"已加载配置文件: {home_env}")

        host = os.environ.get(ENV_VAR_HOST, DEFAULT_HOST)
        port = int(os.environ.get(ENV_VAR_PORT, str(DEFAULT_PORT)))

        super().__init__(
            name="ai_memory",
            host=host,
            port=port,
            mount_path="/",
            sse_path="/sse",
            message_path="/messages/",
            streamable_http_path="/mcp",
        )

        env_path = os.environ.get(ENV_VAR_DB_PATH)
        if env_path:
            self.db_path = env_path
        else:
            db_dir = os.path.join(home, DEFAULT_DB_DIR_NAME)
            os.makedirs(db_dir, exist_ok=True)
            self.db_path = os.path.join(db_dir, "ai_memory.db")

        model_env_path = os.environ.get(ENV_VAR_MODEL_PATH)
        self.model_cache_dir = model_env_path or os.path.join(home, DEFAULT_DB_DIR_NAME, "models")
        os.makedirs(self.model_cache_dir, exist_ok=True)
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)

        logger.info(f"使用数据库路径: {self.db_path}")
        init_db(self.db_path)

        self._vector = VectorStore(self.db_path, self.model_cache_dir)

        self._register_tools()

    # ── write tools ───────────────────────────────────────────────────────────

    def save_summary(self, params: SaveSummaryInput) -> Dict[str, Any]:
        """保存会话摘要到数据库，同步更新全文索引和向量索引。

        Args:
            params (SaveSummaryInput): 包含：
                - session_id (str): 唯一会话 ID，不可重复
                - task_title (str): 任务标题
                - summary_content (str): 摘要正文内容
                - status (TaskStatus): 任务状态，默认 completed
                - next_steps (Optional[str]): 下一步计划
                - tags (Optional[str]): 标签，逗号分隔
                - module (Optional[str]): 所属模块
                - file_paths (Optional[str]): 涉及文件路径，逗号分隔
                - project_name (Optional[str]): 项目名称
                - branch_name (Optional[str]): 分支名称

        Returns:
            Dict: {"success": bool, "message": str}
        """
        resp, created_at = db_save_summary(
            self.db_path,
            session_id=params.session_id,
            task_title=params.task_title,
            summary_content=params.summary_content,
            status=params.status.value,
            next_steps=params.next_steps,
            tags=params.tags,
            module=params.module,
            file_paths=params.file_paths,
            project_name=params.project_name,
            branch_name=params.branch_name,
        )
        if resp.get("success") and created_at:
            self._vector.generate_and_store(
                session_id=params.session_id,
                task_title=params.task_title,
                summary_content=params.summary_content,
                tags=params.tags,
                created_at=created_at,
                db_store_callback=lambda **kw: db_store_vector_metadata(self.db_path, **kw),
            )
        return resp

    def update_summary(self, params: UpdateSummaryInput) -> Dict[str, Any]:
        """更新已有会话摘要的状态或内容，同步更新全文索引。

        Args:
            params (UpdateSummaryInput): 包含：
                - session_id (str): 要更新的会话 ID
                - new_status (Optional[TaskStatus]): 新状态
                - updated_content (Optional[str]): 新的摘要内容

        Returns:
            Dict: {"success": bool, "message": str}
        """
        return db_update_summary(
            self.db_path,
            session_id=params.session_id,
            new_status=params.new_status.value if params.new_status else None,
            updated_content=params.updated_content,
        )

    def add_decision(self, params: AddDecisionInput) -> Dict[str, Any]:
        """为指定会话添加关键决策记录。

        Args:
            params (AddDecisionInput): 包含：
                - session_id (str): 关联的会话 ID
                - decision_type (str): 决策类型，如 tech_stack / api_design / architecture
                - description (str): 决策描述
                - reasoning (Optional[str]): 决策理由

        Returns:
            Dict: {"success": bool, "message": str}
        """
        return db_add_decision(
            self.db_path,
            session_id=params.session_id,
            decision_type=params.decision_type,
            description=params.description,
            reasoning=params.reasoning,
        )

    def maintenance(self) -> Dict[str, Any]:
        """执行数据库维护：重建 FTS5 全文索引、压缩数据库，并持久化向量存储。

        Returns:
            Dict: {"success": bool, "message": str}
        """
        result = db_maintenance(self.db_path)
        if result.get("success"):
            self._vector.persist()
        return result

    # ── read-only tools ───────────────────────────────────────────────────────

    def search_summaries(self, params: SearchSummariesInput) -> Dict[str, Any]:
        """搜索会话摘要，支持关键词、标签、模块、状态、项目、分支过滤，以及 FTS5 全文检索和向量语义检索。

        Args:
            params (SearchSummariesInput): 包含：
                - query (Optional[str]): 搜索关键词
                - tags (Optional[str]): 标签过滤，模糊匹配
                - module (Optional[str]): 模块过滤，模糊匹配
                - status (Optional[TaskStatus]): 状态过滤，精确匹配
                - project_name (Optional[str]): 项目名称过滤，精确匹配
                - branch_name (Optional[str]): 分支名称过滤，精确匹配
                - use_fts (bool): 是否使用 FTS5 全文检索，默认 False
                - use_vector (bool): 是否使用向量语义检索，默认 False
                - limit (int): 最大返回条数，默认 10

        Returns:
            Dict: {"success": bool, "data": List[Dict]}
        """
        status = params.status.value if params.status else None
        try:
            if params.use_vector and params.query and self._vector.available:
                return self._vector_search(
                    params.query, params.project_name, params.branch_name, status, params.limit
                )

            results = db_search_summaries(
                self.db_path,
                query=params.query,
                tags=params.tags,
                module=params.module,
                status=status,
                project_name=params.project_name,
                branch_name=params.branch_name,
                use_fts=params.use_fts,
                limit=params.limit,
            )
            return success_response(data=results)
        except Exception as e:
            logger.error(f"搜索摘要失败: {e}")
            return error_response(str(e))

    def search_summaries_fts(self, params: SearchSummariesFtsInput) -> Dict[str, Any]:
        """使用 FTS5 全文索引搜索会话摘要，适合精确关键词匹配场景。

        Args:
            params (SearchSummariesFtsInput): 包含：
                - query (str): 全文检索关键词，支持 FTS5 查询语法
                - project_name (Optional[str]): 项目名称过滤，精确匹配
                - branch_name (Optional[str]): 分支名称过滤，精确匹配
                - status (Optional[TaskStatus]): 状态过滤，精确匹配
                - limit (int): 最大返回条数，默认 10

        Returns:
            Dict: {"success": bool, "data": List[Dict]}
        """
        try:
            results = db_fts_search(
                self.db_path,
                query=params.query,
                project_name=params.project_name,
                branch_name=params.branch_name,
                status=params.status.value if params.status else None,
                limit=params.limit,
            )
            return success_response(data=results)
        except Exception as e:
            logger.error(f"FTS5全文检索失败: {e}")
            return error_response(str(e))

    def get_summary_by_id(self, params: GetSummaryByIdInput) -> Dict[str, Any]:
        """根据 session_id 精确查询单条摘要记录。

        Args:
            params (GetSummaryByIdInput): 包含：
                - session_id (str): 目标会话 ID

        Returns:
            Dict: {"success": bool, "data": Dict}
        """
        try:
            row = db_get_summary_by_id(self.db_path, params.session_id)
            if row:
                return success_response(data=row)
            return error_response(f"未找到 session_id '{params.session_id}' 对应的摘要")
        except Exception as e:
            logger.error(f"获取摘要失败: {e}")
            return error_response(str(e))

    def list_recent_sessions(self, params: ListRecentSessionsInput) -> Dict[str, Any]:
        """列出最近的会话摘要，支持按项目和分支过滤。

        Args:
            params (ListRecentSessionsInput): 包含：
                - limit (int): 最大返回条数，默认 10
                - project_name (Optional[str]): 项目名称过滤，精确匹配
                - branch_name (Optional[str]): 分支名称过滤，精确匹配

        Returns:
            Dict: {"success": bool, "data": List[Dict]}
        """
        try:
            results = db_list_recent_sessions(
                self.db_path,
                limit=params.limit,
                project_name=params.project_name,
                branch_name=params.branch_name,
            )
            return success_response(data=results)
        except Exception as e:
            logger.error(f"列出最近会话失败: {e}")
            return error_response(str(e))

    def init_session(self, params: InitSessionInput) -> Dict[str, Any]:
        """会话启动时调用，返回最近 3 天内进行中的任务列表，帮助恢复上下文。

        Args:
            params (InitSessionInput): 包含：
                - project_name (Optional[str]): 项目名称过滤，精确匹配
                - branch_name (Optional[str]): 分支名称过滤，精确匹配

        Returns:
            Dict: {"success": bool, "data": List[Dict], "prompt": str}
        """
        try:
            three_days_ago = (
                datetime.now() - timedelta(days=INIT_SESSION_DAYS_BACK)
            ).strftime('%Y-%m-%d %H:%M:%S')
            tasks = db_init_session(
                self.db_path,
                three_days_ago=three_days_ago,
                max_tasks=INIT_SESSION_MAX_TASKS,
                project_name=params.project_name,
                branch_name=params.branch_name,
            )
            if not tasks:
                return success_response(data=[], message="没有找到最近的进行中任务")

            prompt_lines = ["上次我们有以下进行中的任务："]
            for i, task in enumerate(tasks, 1):
                next_steps = task.get('next_steps') or '无'
                prompt_lines.append(f"{i}. {task['task_title']} - 下一步: {next_steps}")
            prompt_lines.append("\n要继续处理这些任务中的哪一个？")

            result = success_response(data=tasks, message=f"找到 {len(tasks)} 个最近的进行中任务")
            result["prompt"] = "\n".join(prompt_lines)
            return result
        except Exception as e:
            logger.error(f"初始化会话失败: {e}")
            return error_response(str(e))

    def weekly_review(self, params: WeeklyReviewInput) -> Dict[str, Any]:
        """生成本周项目周报，汇总完成任务、关键决策和下一步建议。

        Args:
            params (WeeklyReviewInput): 包含：
                - project_name (Optional[str]): 项目名称过滤，精确匹配
                - branch_name (Optional[str]): 分支名称过滤，精确匹配

        Returns:
            Dict: {"success": bool, "data": {"report": str}}
        """
        try:
            today = datetime.now()
            week_start = (today - timedelta(days=today.weekday())).strftime('%Y-%m-%d 00:00:00')
            completed, decisions = db_weekly_review(
                self.db_path,
                week_start=week_start,
                project_name=params.project_name,
                branch_name=params.branch_name,
            )

            lines = [
                f"# 项目周报 ({week_start} 至 {today.strftime('%Y-%m-%d')})", "",
                "## 本周完成的功能",
            ]
            if completed:
                for t in completed:
                    lines.append(f"- **{t['task_title']}**")
                    if t.get('file_paths'):
                        lines.append(f"  - 涉及文件: {t['file_paths']}")
            else:
                lines.append("- 无")
            lines.append("")

            lines.append("## 关键决策")
            if decisions:
                for d in decisions:
                    lines.append(f"- **{d.get('decision_type', '决策')}**: {d['description']}")
                    if d.get('reasoning'):
                        lines.append(f"  - 理由: {d['reasoning']}")
            else:
                lines.append("- 无")
            lines.append("")

            lines.append("## 风险提示")
            lines.append("- 本周无完成任务，可能存在进度延迟" if not completed else "- 无明显风险")
            lines.append("")

            lines.append("## 下一步建议")
            has_next = False
            for t in completed:
                if t.get('next_steps'):
                    lines.append(f"- {t['task_title']}: {t['next_steps']}")
                    has_next = True
            if not has_next:
                lines.append("- 无")

            return success_response(data={"report": "\n".join(lines)}, message="周报生成成功")
        except Exception as e:
            logger.error(f"生成周报失败: {e}")
            return error_response(str(e))

    # ── private helpers ───────────────────────────────────────────────────────

    def _vector_search(
        self,
        query: str,
        project_name,
        branch_name,
        status,
        limit: int,
    ) -> Dict[str, Any]:
        try:
            overfetch = self._vector.overfetch_limit(limit)
            session_ids = self._vector.query_similar_ids(query, overfetch)
            if not session_ids:
                return success_response(data=[])
            db_results = db_vector_search_by_ids(self.db_path, session_ids, project_name, branch_name, status)
            order_map = {sid: i for i, sid in enumerate(session_ids)}
            db_results.sort(key=lambda x: order_map.get(x['session_id'], len(session_ids)))
            logger.info(f"向量检索完成，找到 {len(db_results)} 条结果")
            return success_response(data=db_results[:limit])
        except Exception as e:
            logger.error(f"向量检索失败: {e}")
            return error_response(str(e))

    def _register_tools(self) -> None:
        logger.info("注册 MCP 工具")

        write_tools = [
            (self.save_summary,     "保存会话摘要",         False, False, False),
            (self.update_summary,   "更新会话摘要",         False, False, True),
            (self.add_decision,     "添加关键决策",         False, False, False),
            (self.maintenance,      "数据库维护",           False, False, True),
        ]
        read_tools = [
            (self.search_summaries,     "搜索会话摘要",             True, False, True),
            (self.search_summaries_fts, "全文检索会话摘要",         True, False, True),
            (self.get_summary_by_id,    "按 ID 获取摘要",           True, False, True),
            (self.list_recent_sessions, "列出最近会话",             True, False, True),
            (self.init_session,         "初始化会话（恢复上下文）",  True, False, True),
            (self.weekly_review,        "生成项目周报",             True, False, True),
        ]

        for fn, title, read_only, destructive, idempotent in write_tools + read_tools:
            self.add_tool(
                fn,
                annotations=ToolAnnotations(
                    title=title,
                    readOnlyHint=read_only,
                    destructiveHint=destructive,
                    idempotentHint=idempotent,
                    openWorldHint=False,
                ),
            )

        logger.info("MCP 工具注册完成")


def main() -> None:
    logger.info("启动 AI 记忆管理 MCP Server")
    try:
        server = AiMemoryMcpServer()
        logger.info("MCP Server 初始化完成")
        if len(sys.argv) > 1 and sys.argv[1] == "--http":
            logger.info("以 HTTP 模式运行 MCP Server")
            server.run(transport="streamable-http")
        else:
            logger.info("以 STDIO 模式运行 MCP Server")
            server.run()
    except Exception as e:
        logger.error(f"MCP Server 启动失败: {e}")
        raise


if __name__ == "__main__":
    main()
