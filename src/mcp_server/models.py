"""Pydantic input models and shared constants for AI Memory MCP Server."""
from typing import Optional
from enum import Enum
from pydantic import BaseModel, Field, ConfigDict

# ============ Constants ============

VALID_STATUSES = ('completed', 'in_progress', 'blocked', 'abandoned', 'pending')

DEFAULT_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_MODEL_SNAPSHOT_HASH = "c9745ed1d9f207416be6d2e6f8de32d1f16199bf"
HF_MIRROR_ENDPOINT = "https://hf-mirror.com"

DEFAULT_DB_DIR_NAME = ".ai-memory"
DEFAULT_ENV_FILE_NAME = ".env"
ENV_VAR_DB_PATH = "AI_MEMORY_DB_PATH"
ENV_VAR_MODEL_PATH = "AI_MEMORY_MODEL_PATH"
ENV_VAR_HOST = "AI_MEMORY_HOST"
ENV_VAR_PORT = "AI_MEMORY_PORT"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000

VECTOR_COLLECTION_NAME = "session_summaries"
VECTOR_METRIC_SPACE = "cosine"
VECTOR_DB_DIR_NAME = "vector_db"

INIT_SESSION_DAYS_BACK = 3
INIT_SESSION_MAX_TASKS = 3

VECTOR_SEARCH_OVERFETCH_FACTOR = 1.5
MIN_MODEL_FILE_SIZE_BYTES = 1_000_000

DEFAULT_SEARCH_LIMIT = 10


# ============ Enums ============

class TaskStatus(str, Enum):
    """任务状态枚举"""
    COMPLETED = "completed"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    ABANDONED = "abandoned"
    PENDING = "pending"


# ============ Pydantic Input Models ============

class SaveSummaryInput(BaseModel):
    """保存会话摘要的输入参数模型"""
    model_config = ConfigDict(str_strip_whitespace=True)

    session_id: str = Field(..., description="唯一会话 ID，不可重复", min_length=1)
    task_title: str = Field(..., description="任务标题", min_length=1)
    summary_content: str = Field(..., description="摘要正文内容", min_length=1)
    status: TaskStatus = Field(default=TaskStatus.COMPLETED, description="任务状态")
    next_steps: Optional[str] = Field(default=None, description="下一步计划")
    tags: Optional[str] = Field(default=None, description="标签，逗号分隔")
    module: Optional[str] = Field(default=None, description="所属模块")
    file_paths: Optional[str] = Field(default=None, description="涉及文件路径，逗号分隔")
    project_name: Optional[str] = Field(default=None, description="项目名称")
    branch_name: Optional[str] = Field(default=None, description="分支名称")


class UpdateSummaryInput(BaseModel):
    """更新会话摘要的输入参数模型"""
    model_config = ConfigDict(str_strip_whitespace=True)

    session_id: str = Field(..., description="要更新的会话 ID", min_length=1)
    new_status: Optional[TaskStatus] = Field(default=None, description="新状态")
    updated_content: Optional[str] = Field(default=None, description="新的摘要内容")


class SearchSummariesInput(BaseModel):
    """搜索会话摘要的输入参数模型"""
    model_config = ConfigDict(str_strip_whitespace=True)

    query: Optional[str] = Field(default=None, description="搜索关键词")
    tags: Optional[str] = Field(default=None, description="标签过滤，模糊匹配")
    module: Optional[str] = Field(default=None, description="模块过滤，模糊匹配")
    status: Optional[TaskStatus] = Field(default=None, description="状态过滤，精确匹配")
    project_name: Optional[str] = Field(default=None, description="项目名称过滤，精确匹配")
    branch_name: Optional[str] = Field(default=None, description="分支名称过滤，精确匹配")
    use_fts: bool = Field(default=False, description="是否使用 FTS5 全文检索")
    use_vector: bool = Field(default=False, description="是否使用向量语义检索")
    limit: int = Field(default=DEFAULT_SEARCH_LIMIT, description="最大返回条数", ge=1, le=100)


class AddDecisionInput(BaseModel):
    """添加关键决策的输入参数模型"""
    model_config = ConfigDict(str_strip_whitespace=True)

    session_id: str = Field(..., description="关联的会话 ID", min_length=1)
    decision_type: str = Field(..., description="决策类型，如 tech_stack / api_design / architecture", min_length=1)
    description: str = Field(..., description="决策描述", min_length=1)
    reasoning: Optional[str] = Field(default=None, description="决策理由")


class GetSummaryByIdInput(BaseModel):
    """根据 ID 获取摘要的输入参数模型"""
    model_config = ConfigDict(str_strip_whitespace=True)

    session_id: str = Field(..., description="目标会话 ID", min_length=1)


class ListRecentSessionsInput(BaseModel):
    """列出最近会话的输入参数模型"""
    limit: int = Field(default=DEFAULT_SEARCH_LIMIT, description="最大返回条数", ge=1, le=100)
    project_name: Optional[str] = Field(default=None, description="项目名称过滤，精确匹配")
    branch_name: Optional[str] = Field(default=None, description="分支名称过滤，精确匹配")


class InitSessionInput(BaseModel):
    """初始化会话的输入参数模型"""
    project_name: Optional[str] = Field(default=None, description="项目名称过滤，精确匹配")
    branch_name: Optional[str] = Field(default=None, description="分支名称过滤，精确匹配")


class WeeklyReviewInput(BaseModel):
    """生成周报的输入参数模型"""
    project_name: Optional[str] = Field(default=None, description="项目名称过滤，精确匹配")
    branch_name: Optional[str] = Field(default=None, description="分支名称过滤，精确匹配")


class SearchSummariesFtsInput(BaseModel):
    """FTS5 全文检索的输入参数模型"""
    model_config = ConfigDict(str_strip_whitespace=True)

    query: str = Field(..., description="全文检索关键词，支持 FTS5 查询语法", min_length=1)
    project_name: Optional[str] = Field(default=None, description="项目名称过滤，精确匹配")
    branch_name: Optional[str] = Field(default=None, description="分支名称过滤，精确匹配")
    status: Optional[TaskStatus] = Field(default=None, description="状态过滤，精确匹配")
    limit: int = Field(default=DEFAULT_SEARCH_LIMIT, description="最大返回条数", ge=1, le=100)
