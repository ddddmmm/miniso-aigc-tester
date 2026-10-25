#!/usr/bin/env python3
"""
复核打分模块（review）：按 JD 原话定义评分维度，生成/读取打分表。

工作流：
  1. aigc review --latest   → 依据最近一次运行结果生成打分表 reviews/review_<run_id>.yaml
  2. 人工在 YAML 中填写 1~5 分、记录问题（已预填示例分数，可直接修改）
  3. report.py 读取打分表生成 HTML 报告
"""

import json
from pathlib import Path
from typing import Dict, List, Optional

import yaml

# 评分维度（key: 中文说明）——直接对应 JD 第 2 条复核要求
DIMENSIONS = {
    "商品图": {
        "subject": "主体准确性（商品像不像）",
        "composition": "构图",
        "style": "风格一致性",
        "text_logo": "文字与logo正确性",
    },
    "IP创意图": {
        "subject": "主体准确性（角色像不像）",
        "composition": "构图",
        "style": "风格一致性",
        "text_logo": "文字与logo正确性",
        "character_consistency": "角色五官/服装/配色一致性",
    },
    "视频": {
        "motion": "动作流畅度",
        "shot_transition": "镜头衔接",
        "video_character": "角色一致性",
        "storyboard": "分镜还原度",
    },
}

PASS_THRESHOLD = 3.5  # 平均分 >= 3.5 判定通过


def dimensions_for_scene(scene: str) -> Dict[str, str]:
    """返回该场景适用的评分维度。"""
    return DIMENSIONS.get(scene, DIMENSIONS["商品图"])


def mean_score(scores: Dict[str, int]) -> float:
    """计算平均分。"""
    if not scores:
        return 0.0
    return round(sum(scores.values()) / len(scores), 2)


def is_pass(scores: Dict[str, int]) -> bool:
    """根据平均分判定是否通过。"""
    return mean_score(scores) >= PASS_THRESHOLD


def find_latest_log(logs_dir: str = "logs") -> Optional[Path]:
    """找到最新的运行日志。"""
    logs = sorted(Path(logs_dir).glob("run_*.jsonl"))
    return logs[-1] if logs else None


def load_run_records(log_path) -> List[dict]:
    """读取 JSONL 运行日志为记录列表。"""
    records = []
    with open(log_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _scores_and_problems(note: str, dims: Dict[str, str]):
    """根据轮次备注生成示例分数和问题（讲述完整的调优故事，可人工修改）。"""
    scores = {k: 5 for k in dims}
    problems: List[str] = []

    if "裁切" in note:
        scores = {k: 4 for k in dims}
        scores["composition"] = 2
        problems = ["构图问题：商品底部被裁切，画面不完整"]
    elif "丢失" in note:
        scores = {k: 4 for k in dims}
        weak_key = "character_consistency" if "character_consistency" in scores else "subject"
        scores[weak_key] = 2
        problems = ["角色特征丢失：头顶呆毛未生成，与官方设定不一致"]

    return scores, problems


def build_review_sheet(records: List[dict], run_id: str) -> dict:
    """根据运行记录生成打分表（仅对成功结果打分）。"""
    reviews = []
    for r in records:
        if r["status"] != "success":
            continue

        scene = r["scene"]
        round_no = r.get("round", 1)
        dims = dimensions_for_scene(scene)
        note = r.get("round_note", "")
        scores, problems = _scores_and_problems(note, dims)

        reviews.append({
            "case_id": r["case_id"],
            "round": round_no,
            "scene": scene,
            "image": r.get("output", ""),
            "scores": scores,
            "problems": problems,
            "mean": mean_score(scores),
            "pass": is_pass(scores),
        })

    return {
        "run_id": run_id,
        "pass_threshold": PASS_THRESHOLD,
        "note": "打分说明：每项 1~5 分（5最好）；改完分数后 mean/pass 会在报告中自动重算。",
        "reviews": reviews,
    }


def write_review_sheet(sheet: dict, reviews_dir: str = "reviews") -> Path:
    """把打分表写入 YAML 文件。"""
    out_dir = Path(reviews_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"review_{sheet['run_id']}.yaml"
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(sheet, f, allow_unicode=True, sort_keys=False)
    return path


def load_review_sheet(path) -> dict:
    """读取打分表 YAML。"""
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def find_review_for_run(run_id: str, reviews_dir: str = "reviews") -> Optional[Path]:
    """找到指定 run_id 的打分表。"""
    path = Path(reviews_dir) / f"review_{run_id}.yaml"
    return path if path.exists() else None
