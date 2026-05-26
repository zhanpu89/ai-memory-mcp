"""AI Memory MCP Server — tool registration layer."""
import logging
import os
import sys
from datetime import datetime, timedelta
from typing import Any, Dict

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.prompts import Prompt
from mcp.types import ToolAnnotations

from .database import (
    db_add_decision,
    db_count_decisions_for_session,
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
        self._register_prompts()

    # ── write tools ───────────────────────────────────────────────────────────

    def save_summary(self, params: SaveSummaryInput) -> Dict[str, Any]:
        """保存会话摘要。任务完成或达到里程碑时调用，创建一条新的会话记录。

        使用时机（满足任一即可）：
        - 完成了一个功能模块
        - 修复了一个 Bug
        - 完成了一轮重构
        - 解决了环境/配置问题
        - 会话即将结束但任务未完

        调用前请确认：
        1. file_paths 已填写涉及的文件路径（逗号分隔）
        2. next_steps 已填写下一步计划
        3. tags 已填写标签（逗号分隔，如 "auth,jwt,backend"）
        4. 已向用户展示摘要预览并获得确认

        调用后：如需补充技术决策，调用 add_decision

        Args:
            params (SaveSummaryInput): 包含：
                - session_id (str): 唯一会话 ID，格式 session-YYYYMMDD-task_slug，不可重复
                - task_title (str): 任务标题
                - summary_content (str): 摘要正文
                - status (TaskStatus): 状态，默认 completed
                - next_steps (Optional[str]): 下一步计划
                - tags (Optional[str]): 标签，逗号分隔，如 "auth,jwt"
                - module (Optional[str]): 所属模块
                - file_paths (Optional[str]): 涉及文件路径，逗号分隔
                - project_name (Optional[str]): 项目名称
                - branch_name (Optional[str]): 分支名称

        Returns:
            Dict: {"success": bool, "message": str, "quality_warnings"?: List[str]}
        """
        quality_warnings = []
        if not params.file_paths:
            quality_warnings.append("缺少 file_paths（涉及文件路径），日后将无法按文件检索到此记录")
        if not params.next_steps:
            quality_warnings.append("缺少 next_steps（下一步计划），下次恢复时无法获知后续工作")
        if not params.tags:
            quality_warnings.append("缺少 tags（标签），会降低搜索召回率")
        if not params.module:
            quality_warnings.append("缺少 module（所属模块），会降低模块维度检索能力")

        if not params.project_name:
            quality_warnings.append("缺少 project_name（项目名称），跨项目检索时无法过滤")

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
        if resp.get("success"):
            if quality_warnings:
                resp["quality_warnings"] = quality_warnings
                resp["message"] += "\n⚠️ 质量提示（不影响保存，但建议补充）：\n" + "\n".join(f"- {w}" for w in quality_warnings)

            # Check if decisions exist for this session (only warn, don't block)
            try:
                dec_count = db_count_decisions_for_session(self.db_path, params.session_id)
                if dec_count == 0:
                    warning = "该会话暂无技术决策记录（add_decision），建议补充以丰富上下文"
                    resp.setdefault("quality_warnings", []).append(warning)
                    resp["message"] += f"\n- {warning}"
            except Exception:
                pass

            if created_at:
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
        """更新已有会话的状态或摘要内容。不创建新记录，只修改现有记录。

        使用时机：
        - 任务状态发生变化（如 in_progress → completed）
        - 摘要内容需要补充或修正

        调用前：确保 session_id 已存在（通过 save_summary 创建）

        Args:
            params (UpdateSummaryInput): 包含：
                - session_id (str): 要更新的会话 ID
                - new_status (Optional[TaskStatus]): 新状态
                - updated_content (Optional[str]): 新摘要内容

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
        """为指定会话添加关键技术决策。在任务执行中发现重要决策时立即调用，不等任务结束。

        使用时机（满足任一即可）：
        - 确定了技术选型（如 "选用 FastAPI 而非 Flask"）
        - 设计了架构方案
        - 修复了 Bug（记录根因）
        - 做了性能优化
        - 做了安全相关的决策
        - 做了重要的 trade-off 决策

        建议 decision_type 取值：architecture, tech_choice, bug_fix, refactor, performance, security, trade_off

        Args:
            params (AddDecisionInput): 包含：
                - session_id (str): 关联的会话 ID
                - decision_type (str): 决策类型，如 architecture / tech_choice / bug_fix
                - description (str): 决策描述
                - reasoning (Optional[str]): 决策理由（建议填写，帮助未来理解）

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
        """执行数据库维护：重建 FTS5 全文索引、压缩数据库空间、持久化向量存储。

        使用时机：
        - 每周执行一次
        - 大量导入/删除数据后
        - 用户明确要求时

        Args: 无

        Returns:
            Dict: {"success": bool, "message": str}
        """
        result = db_maintenance(self.db_path)
        if result.get("success"):
            self._vector.persist()
        return result

    # ── read-only tools ───────────────────────────────────────────────────────

    def search_summaries(self, params: SearchSummariesInput) -> Dict[str, Any]:
        """搜索会话摘要。默认使用 FTS5 全文检索，若无结果且向量可用时自动降级到语义检索。

        使用时机（满足任一即可）：
        - 遇到报错/异常，先搜索历史解决方案
        - 需要参考之前的技术选型或架构设计
        - 用户提到"之前做过/遇到过"
        - 讨论工具/库的用法

        搜索策略（自动按优先级执行）：
        1. FTS5 全文检索（精确匹配，适合错误信息、包名）—— 默认开启
        2. 若 FTS5 无结果，自动降级到向量语义检索（适合自然语言描述）
        3. 若向量不可用，回退到 LIKE 模糊匹配

        Args:
            params (SearchSummariesInput): 包含：
                - query (Optional[str]): 搜索关键词
                - tags (Optional[str]): 标签过滤，模糊匹配
                - module (Optional[str]): 模块过滤，模糊匹配
                - status (Optional[TaskStatus]): 状态过滤，精确匹配
                - project_name (Optional[str]): 项目名称过滤
                - branch_name (Optional[str]): 分支名称过滤
                - use_fts (bool): 是否使用 FTS5 全文检索，默认 True
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

            # Auto fallback: FTS5 无结果 → 自动降级
            if not results and params.query and params.use_fts:
                # 1) 优先向量语义检索
                if self._vector.available:
                    logger.info(f"FTS5 未找到结果，自动降级到向量检索: {params.query}")
                    vec_result = self._vector_search(
                        params.query, params.project_name, params.branch_name, status, params.limit
                    )
                    if vec_result.get("success") and vec_result.get("data"):
                        vec_result["message"] = "FTS5 未命中，已自动降级到语义检索（向量）"
                        return vec_result

                # 2) 最后兜底：LIKE 模糊匹配（对中文友好，兼容 FTS5 不支持中文分词的问题）
                logger.info(f"FTS5/向量均未命中，自动降级到 LIKE 检索: {params.query}")
                like_results = db_search_summaries(
                    self.db_path,
                    query=params.query,
                    tags=params.tags,
                    module=params.module,
                    status=status,
                    project_name=params.project_name,
                    branch_name=params.branch_name,
                    use_fts=False,
                    limit=params.limit,
                )
                if like_results:
                    return success_response(
                        data=like_results,
                        message="FTS5 未命中，已自动降级到模糊匹配",
                    )

            return success_response(data=results)
        except Exception as e:
            logger.error(f"搜索摘要失败: {e}")
            return error_response(str(e))

    def search_summaries_fts(self, params: SearchSummariesFtsInput) -> Dict[str, Any]:
        """使用 FTS5 全文索引进行精确关键词搜索。适合错误信息、函数名、包名等精确匹配场景。

        使用时机：
        - 需要精确匹配错误信息（如 "ImportError: No module named chromadb"）
        - 搜索特定的函数名、类名、包名
        - search_summaries 的 use_fts=True 不满足需求时（需要复杂 FTS5 语法时）

        FTS5 查询语法：支持 AND/OR/NOT，如 '"jwt" OR "oauth"'，支持前缀匹配如 'auth*'

        Args:
            params (SearchSummariesFtsInput): 包含：
                - query (str): 全文检索关键词，支持 FTS5 查询语法
                - project_name (Optional[str]): 项目名称过滤
                - branch_name (Optional[str]): 分支名称过滤
                - status (Optional[TaskStatus]): 状态过滤
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
        """根据 session_id 精确查询单条完整摘要。用于深入查看某条会话的完整上下文。

        使用时机：
        - 从 init_session 或 search_summaries 结果中看到某条记录，需要查看详情
        - 需要恢复某个特定任务的完整上下文（包括摘要、决策等）

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
        """列出最近的会话摘要，按创建时间降序排列。用于浏览近期工作历史。

        使用时机：
        - 用户想回顾最近做了什么
        - 需要浏览近期任务列表以选择继续哪一个
        - 适合 L3 级上下文加载（完整回顾）

        Args:
            params (ListRecentSessionsInput): 包含：
                - limit (int): 最大返回条数，默认 10
                - project_name (Optional[str]): 项目名称过滤
                - branch_name (Optional[str]): 分支名称过滤

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
        """【每次会话必须调用的第一条工具】返回最近 3 天内进行中的任务列表，帮助恢复上下文。

        使用时机（必须遵守）：
        - 每次新对话开始时，第一条工具调用必须是 init_session
        - 项目切换时再次调用
        - 用户说"恢复上下文/继续上次/加载记忆"时

        调用此工具前必须先执行：
        1. 项目上下文识别：查找 .project_name 文件获取 project_name
        2. 读取 git branch 获取 branch_name

        调用此工具后：
        1. 将返回的任务列表展示给用户
        2. 用户选择某个任务后，调用 get_summary_by_id 获取完整摘要
        3. 如果是全新任务，按 session-YYYYMMDD-task_slug 格式生成 session_id

        Args:
            params (InitSessionInput): 包含：
                - project_name (Optional[str]): 项目名称过滤
                - branch_name (Optional[str]): 分支名称过滤

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
        """生成本周项目周报。汇总本周完成的任务、关键决策和下一步建议，输出 Markdown 格式。

        使用时机：用户说"生成本周周报/本周总结/周报"

        Args:
            params (WeeklyReviewInput): 包含：
                - project_name (Optional[str]): 项目名称过滤
                - branch_name (Optional[str]): 分支名称过滤

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

    # ── MCP prompt templates ─────────────────────────────────────────────────

    def _register_prompts(self) -> None:
        logger.info("注册 MCP Prompt 模板")

        prompts = [
            Prompt.from_function(
                fn=self._prompt_start_session,
                name="memory-start-session",
                title="会话启动恢复上下文",
                description="[必调] 会话启动时调用，自动查询进行中任务并注入上下文。调用后方可回答用户问题。",
            ),
            Prompt.from_function(
                fn=self._prompt_search_error,
                name="memory-search-error",
                title="检索历史解决方案",
                description="[报错/问题] 自动搜索历史记录中相似的错误信息或技术方案，供回答时引用。",
            ),
            Prompt.from_function(
                fn=self._prompt_save_task,
                name="memory-save-task",
                title="保存任务摘要",
                description="[保存] 组织任务摘要并检查字段完整性，用户确认后调用 save_summary 保存。",
            ),
        ]
        for prompt in prompts:
            self.add_prompt(prompt)
        logger.info(f"MCP Prompt 模板注册完成 ({len(prompts)} 个)")

    # ── prompt handlers ──────────────────────────────────────────────────────

    def _prompt_start_session(
        self,
        project_name: str = "",
        branch_name: str = "",
    ) -> str:
        """返回进行中任务列表和会话上下文"""
        three_days_ago = (
            datetime.now() - timedelta(days=INIT_SESSION_DAYS_BACK)
        ).strftime('%Y-%m-%d %H:%M:%S')
        pn = project_name or None
        bn = branch_name or None
        tasks = db_init_session(self.db_path, three_days_ago, INIT_SESSION_MAX_TASKS, pn, bn)

        lines = ["## 进行中的任务", ""]
        if tasks:
            for i, t in enumerate(tasks, 1):
                ns = t.get("next_steps") or "无"
                lines.append(f"{i}. **{t['task_title']}**")
                lines.append(f"   - 状态: {t['status']}  下一步: {ns}")
                lines.append("")
            lines.append("请先查看以上任务，再回答用户的问题。")
            lines.append("如果用户要接续某个任务，先用 get_summary_by_id 获取完整摘要。")
        else:
            lines.append("当前没有进行中的任务。")
            lines.append("如果开始新任务，按 `session-YYYYMMDD-简短描述` 格式创建 session_id。")
        return "\n".join(lines)

    def _prompt_search_error(
        self,
        error_message: str = "",
        project_name: str = "",
    ) -> str:
        """根据报错信息搜索历史记录"""
        if not error_message:
            return "请提供 error_message 参数。"
        pn = project_name or None

        results = db_search_summaries(
            self.db_path,
            query=error_message,
            tags=None, module=None, status=None,
            project_name=pn, branch_name=None,
            use_fts=True, limit=5,
        )

        lines = [f"## 历史检索: {error_message}", ""]
        if results:
            lines.append(f"找到 {len(results)} 条相关记录：")
            lines.append("")
            for r in results:
                lines.append(f"- **{r['task_title']}**")
                lines.append(f"  摘要: {r['summary_content'][:200]}")
                if r.get("next_steps"):
                    lines.append(f"  下一步: {r['next_steps']}")
                lines.append("")
            lines.append("回答用户前，请先引用以上历史记录。")
        else:
            lines.append("未找到历史记录，请自行推理。")
        return "\n".join(lines)

    def _prompt_save_task(
        self,
        session_id: str = "",
        task_title: str = "",
        summary_content: str = "",
        status: str = "completed",
        file_paths: str = "",
        tags: str = "",
        next_steps: str = "",
    ) -> str:
        """检查保存字段完整性，返回可预览的摘要"""
        warnings = []
        if not file_paths:
            warnings.append("缺少 file_paths")
        if not next_steps:
            warnings.append("缺少 next_steps")
        if not tags:
            warnings.append("缺少 tags")
        if not session_id or not task_title or not summary_content:
            return "错误：session_id、task_title、summary_content 为必填项。"

        lines = [
            "## 摘要预览",
            "",
            f"- **session_id**: {session_id}",
            f"- **task_title**: {task_title}",
            f"- **status**: {status}",
            f"- **file_paths**: {file_paths or '(未填)'}",
            f"- **tags**: {tags or '(未填)'}",
            f"- **next_steps**: {next_steps or '(未填)'}",
            "",
            "### 摘要内容",
            summary_content,
            "",
        ]
        if warnings:
            lines.append("### ⚠️ 质量提示")
            for w in warnings:
                lines.append(f"- {w}")
            lines.append("")
            lines.append("建议补充以上缺项，便于未来检索。")
        lines.append("---")
        lines.append("向用户展示以上预览，**获得确认后**调用 save_summary 保存。")
        return "\n".join(lines)


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
