"""
Memory quality scoring engine.
Evaluates each memory on completeness, context richness, and usefulness.
"""

from typing import Any, Dict, List, Optional, Tuple


QUALITY_WEIGHTS = {
    "has_tags": 15,
    "has_module": 10,
    "has_file_paths": 15,
    "has_next_steps": 10,
    "has_project_name": 5,
    "has_branch_name": 5,
    "has_decisions": 15,
    "has_vector_embedding": 5,
    "summary_length_adequate": 10,
    "title_specific": 5,
    "complete_status": 5,
}

MAX_SCORE = sum(QUALITY_WEIGHTS.values())


def score_memory(
    summary: Dict[str, Any],
    decision_count: int = 0,
    has_vector: bool = False,
) -> Dict[str, Any]:
    items: Dict[str, Any] = {}
    total = 0

    tags = summary.get("tags") or ""
    has_tags = bool(tags.strip())
    items["has_tags"] = {"score": QUALITY_WEIGHTS["has_tags"] if has_tags else 0, "max": QUALITY_WEIGHTS["has_tags"], "label": "标签", "ok": has_tags}
    total += items["has_tags"]["score"]

    module = summary.get("module") or ""
    has_module = bool(module.strip())
    items["has_module"] = {"score": QUALITY_WEIGHTS["has_module"] if has_module else 0, "max": QUALITY_WEIGHTS["has_module"], "label": "所属模块", "ok": has_module}
    total += items["has_module"]["score"]

    file_paths = summary.get("file_paths") or ""
    has_file_paths = bool(file_paths.strip())
    items["has_file_paths"] = {"score": QUALITY_WEIGHTS["has_file_paths"] if has_file_paths else 0, "max": QUALITY_WEIGHTS["has_file_paths"], "label": "关联文件", "ok": has_file_paths}
    total += items["has_file_paths"]["score"]

    next_steps = summary.get("next_steps") or ""
    has_next_steps = bool(next_steps.strip())
    items["has_next_steps"] = {"score": QUALITY_WEIGHTS["has_next_steps"] if has_next_steps else 0, "max": QUALITY_WEIGHTS["has_next_steps"], "label": "后续计划", "ok": has_next_steps}
    total += items["has_next_steps"]["score"]

    project_name = summary.get("project_name") or ""
    has_project_name = bool(project_name.strip())
    items["has_project_name"] = {"score": QUALITY_WEIGHTS["has_project_name"] if has_project_name else 0, "max": QUALITY_WEIGHTS["has_project_name"], "label": "项目名称", "ok": has_project_name}
    total += items["has_project_name"]["score"]

    branch_name = summary.get("branch_name") or ""
    has_branch_name = bool(branch_name.strip())
    items["has_branch_name"] = {"score": QUALITY_WEIGHTS["has_branch_name"] if has_branch_name else 0, "max": QUALITY_WEIGHTS["has_branch_name"], "label": "分支名称", "ok": has_branch_name}
    total += items["has_branch_name"]["score"]

    has_decisions = decision_count > 0
    items["has_decisions"] = {"score": QUALITY_WEIGHTS["has_decisions"] if has_decisions else 0, "max": QUALITY_WEIGHTS["has_decisions"], "label": "技术决策", "ok": has_decisions}
    total += items["has_decisions"]["score"]

    has_vector = bool(has_vector)
    items["has_vector_embedding"] = {"score": QUALITY_WEIGHTS["has_vector_embedding"] if has_vector else 0, "max": QUALITY_WEIGHTS["has_vector_embedding"], "label": "向量索引", "ok": has_vector}
    total += items["has_vector_embedding"]["score"]

    content = summary.get("summary_content") or ""
    length_ok = len(content.strip()) > 100
    items["summary_length_adequate"] = {"score": QUALITY_WEIGHTS["summary_length_adequate"] if length_ok else 0, "max": QUALITY_WEIGHTS["summary_length_adequate"], "label": "内容长度 (>100字)", "ok": length_ok}
    total += items["summary_length_adequate"]["score"]

    title = summary.get("task_title") or ""
    title_ok = len(title.strip()) > 10
    items["title_specific"] = {"score": QUALITY_WEIGHTS["title_specific"] if title_ok else 0, "max": QUALITY_WEIGHTS["title_specific"], "label": "标题描述清晰", "ok": title_ok}
    total += items["title_specific"]["score"]

    status = summary.get("status") or ""
    status_ok = status in ("completed", "in_progress")
    raw = QUALITY_WEIGHTS["complete_status"]
    items["complete_status"] = {"score": raw if status_ok else 0, "max": raw, "label": "有效状态", "ok": status_ok}
    total += items["complete_status"]["score"]

    pct = round(total / MAX_SCORE * 100, 1) if MAX_SCORE else 0

    if pct < 30:
        level = "poor"
        label = "待完善"
        suggestion = "记忆内容严重不完整，建议补充标签、文件路径、技术决策等关键信息，以提高记忆的可用性和检索效率。"
    elif pct < 50:
        level = "below_average"
        label = "一般"
        suggestion = "记忆基本结构存在，但缺少多个关键维度（标签、文件路径、技术决策等）。建议逐项补充缺失信息。"
    elif pct < 65:
        level = "average"
        label = "良好"
        suggestion = "记忆质量处于中等水平。建议补充技术决策记录和后续计划，让记忆更完整可追溯。"
    elif pct < 80:
        level = "good"
        label = "优秀"
        suggestion = "记忆质量较高，关键信息基本完备。可考虑添加更多技术决策和注释来丰富上下文。"
    else:
        level = "excellent"
        label = "完美"
        suggestion = "记忆质量极佳，信息完备。建议保持此标准，未来检索时将有最佳体验。"

    return {
        "score": total,
        "max_score": MAX_SCORE,
        "percentage": pct,
        "level": level,
        "level_label": label,
        "suggestion": suggestion,
        "dimensions": items,
    }


def get_quality_distribution(scores: List[float]) -> Dict[str, int]:
    dist: Dict[str, int] = {"excellent": 0, "good": 0, "average": 0, "below_average": 0, "poor": 0}
    for s in scores:
        if s >= 80:
            dist["excellent"] += 1
        elif s >= 65:
            dist["good"] += 1
        elif s >= 50:
            dist["average"] += 1
        elif s >= 30:
            dist["below_average"] += 1
        else:
            dist["poor"] += 1
    return dist
