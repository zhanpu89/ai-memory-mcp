"""Memory quality scoring engine — 12 dimensions with graduated scoring."""
import re
from typing import Any, Dict, List, Optional, Tuple

QUALITY_WEIGHTS = {
    "has_tags": 10,
    "has_module": 10,
    "has_file_paths": 15,
    "has_next_steps": 10,
    "has_project_name": 5,
    "has_branch_name": 5,
    "has_decisions": 15,
    "has_vector_embedding": 5,
    "content_quality": 10,
    "title_specific": 5,
    "complete_status": 5,
    "hit_frequency": 5,
}

MAX_SCORE = sum(QUALITY_WEIGHTS.values())

TECH_PATTERNS = [
    (r'(error|exception|traceback|fail)', 2),
    (r'(class|def|function|async\s+def)', 2),
    (r'(import|from\s+\w+\s+import)', 2),
    (r'(api|endpoint|route|http(s)?://)', 2),
    (r'(config|setting|env|docker)', 1),
    (r'(test|assert|mock|pytest)', 1),
    (r'(migrate|schema|ddl|sql|query)', 1),
    (r'(install|pip|npm|yarn|brew)', 1),
    (r'(refactor|optimize|extract|rename)', 1),
    (r'(use\s+case|architecture|pattern|design)', 1),
    (r'(version|release|changelog|breaking)', 1),
]


def _score_tags(tags_str: Optional[str]) -> Dict[str, Any]:
    raw = QUALITY_WEIGHTS["has_tags"]
    tags = (tags_str or "").strip()
    if not tags:
        return {"score": 0, "max": raw, "label": "标签", "ok": False}
    count = len([t for t in tags.split(",") if t.strip()])
    if count >= 3:
        return {"score": raw, "max": raw, "label": f"标签 ({count}个)", "ok": True}
    if count == 2:
        return {"score": int(raw * 0.6), "max": raw, "label": f"标签 ({count}个)", "ok": True}
    return {"score": int(raw * 0.3), "max": raw, "label": f"标签 ({count}个)", "ok": True}


def _score_decisions(decision_count: int, decisions: Optional[List[Dict]] = None) -> Dict[str, Any]:
    raw = QUALITY_WEIGHTS["has_decisions"]
    if decision_count == 0:
        return {"score": 0, "max": raw, "label": "技术决策", "ok": False}

    # Check if any decision has reasoning
    has_reasoning = False
    if decisions:
        has_reasoning = any(bool(d.get("reasoning")) for d in decisions)

    if decision_count >= 2 and has_reasoning:
        return {"score": raw, "max": raw, "label": f"技术决策 ({decision_count}条, 含理由)", "ok": True}
    if decision_count >= 2:
        return {"score": int(raw * 0.8), "max": raw, "label": f"技术决策 ({decision_count}条)", "ok": True}
    if has_reasoning:
        return {"score": int(raw * 0.65), "max": raw, "label": "技术决策 (1条, 含理由)", "ok": True}
    return {"score": int(raw * 0.45), "max": raw, "label": "技术决策 (1条)", "ok": True}


def _score_content_quality(content: Optional[str]) -> Dict[str, Any]:
    raw = QUALITY_WEIGHTS["content_quality"]
    text = (content or "").strip()
    if not text:
        return {"score": 0, "max": raw, "label": "内容质量", "ok": False}

    length_ok = len(text) > 100
    tech_score = 0
    for pattern, weight in TECH_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            tech_score += weight

    info_density = min(10, tech_score + (2 if length_ok else 0))
    if info_density >= raw:
        return {"score": raw, "max": raw, "label": "内容质量 (技术信息丰富)", "ok": True}
    if length_ok and tech_score > 0:
        return {"score": int(raw * 0.6), "max": raw, "label": "内容质量", "ok": True}
    if length_ok:
        return {"score": int(raw * 0.3), "max": raw, "label": "内容质量 (无技术细节)", "ok": True}
    return {"score": int(raw * 0.1), "max": raw, "label": "内容质量 (过短)", "ok": False}


def score_memory(
    summary: Dict[str, Any],
    decision_count: int = 0,
    has_vector: bool = False,
    hit_count: int = 0,
    days_since_update: Optional[int] = None,
    decisions: Optional[List[Dict]] = None,
) -> Dict[str, Any]:
    items: Dict[str, Any] = {}
    total = 0

    # Tags — graduated by count
    tag_item = _score_tags(summary.get("tags"))
    items["has_tags"] = tag_item
    total += tag_item["score"]

    # Module
    module = summary.get("module") or ""
    has_module = bool(module.strip())
    items["has_module"] = {"score": QUALITY_WEIGHTS["has_module"] if has_module else 0, "max": QUALITY_WEIGHTS["has_module"], "label": "所属模块", "ok": has_module}
    total += items["has_module"]["score"]

    # File paths
    file_paths = summary.get("file_paths") or ""
    has_file_paths = bool(file_paths.strip())
    items["has_file_paths"] = {"score": QUALITY_WEIGHTS["has_file_paths"] if has_file_paths else 0, "max": QUALITY_WEIGHTS["has_file_paths"], "label": "关联文件", "ok": has_file_paths}
    total += items["has_file_paths"]["score"]

    # Next steps
    next_steps = summary.get("next_steps") or ""
    has_next_steps = bool(next_steps.strip())
    items["has_next_steps"] = {"score": QUALITY_WEIGHTS["has_next_steps"] if has_next_steps else 0, "max": QUALITY_WEIGHTS["has_next_steps"], "label": "后续计划", "ok": has_next_steps}
    total += items["has_next_steps"]["score"]

    # Project name
    project_name = summary.get("project_name") or ""
    has_project_name = bool(project_name.strip())
    items["has_project_name"] = {"score": QUALITY_WEIGHTS["has_project_name"] if has_project_name else 0, "max": QUALITY_WEIGHTS["has_project_name"], "label": "项目名称", "ok": has_project_name}
    total += items["has_project_name"]["score"]

    # Branch name
    branch_name = summary.get("branch_name") or ""
    has_branch_name = bool(branch_name.strip())
    items["has_branch_name"] = {"score": QUALITY_WEIGHTS["has_branch_name"] if has_branch_name else 0, "max": QUALITY_WEIGHTS["has_branch_name"], "label": "分支名称", "ok": has_branch_name}
    total += items["has_branch_name"]["score"]

    # Decisions — graduated by count + reasoning quality
    dec_item = _score_decisions(decision_count, decisions)
    items["has_decisions"] = dec_item
    total += dec_item["score"]

    # Vector embedding
    has_vector = bool(has_vector)
    items["has_vector_embedding"] = {"score": QUALITY_WEIGHTS["has_vector_embedding"] if has_vector else 0, "max": QUALITY_WEIGHTS["has_vector_embedding"], "label": "向量索引", "ok": has_vector}
    total += items["has_vector_embedding"]["score"]

    # Content quality — semantic check replaces simple length check
    content_item = _score_content_quality(summary.get("summary_content"))
    items["content_quality"] = content_item
    total += content_item["score"]

    # Title specificity
    title = summary.get("task_title") or ""
    title_ok = len(title.strip()) > 10
    items["title_specific"] = {"score": QUALITY_WEIGHTS["title_specific"] if title_ok else 0, "max": QUALITY_WEIGHTS["title_specific"], "label": "标题描述清晰", "ok": title_ok}
    total += items["title_specific"]["score"]

    # Status
    status = summary.get("status") or ""
    status_ok = status in ("completed", "in_progress")
    raw = QUALITY_WEIGHTS["complete_status"]
    items["complete_status"] = {"score": raw if status_ok else 0, "max": raw, "label": "有效状态", "ok": status_ok}
    total += items["complete_status"]["score"]

    # Hit frequency
    hit_score = 0
    if hit_count >= 5:
        hit_score = QUALITY_WEIGHTS["hit_frequency"]
    elif hit_count >= 2:
        hit_score = int(QUALITY_WEIGHTS["hit_frequency"] * 0.6)
    elif hit_count >= 1:
        hit_score = int(QUALITY_WEIGHTS["hit_frequency"] * 0.2)
    items["hit_frequency"] = {"score": hit_score, "max": QUALITY_WEIGHTS["hit_frequency"], "label": "命中频率", "ok": hit_count > 0}
    total += hit_score

    # Cold penalty
    cold_penalty = 0
    if status == "completed" and days_since_update is not None and days_since_update > 90 and hit_count == 0:
        cold_penalty = -5
    if cold_penalty:
        items["cold_penalty"] = {"score": cold_penalty, "max": 0, "label": "冷记忆降级", "ok": False}

    total += cold_penalty
    pct = round(max(0, total) / MAX_SCORE * 100, 1) if MAX_SCORE else 0

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

    if cold_penalty:
        suggestion = "此记忆超过 90 天未访问，已被冷降级。补充标签或添加技术决策可提升检索曝光。"

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
