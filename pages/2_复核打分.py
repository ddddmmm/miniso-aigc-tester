# -*- coding: utf-8 -*-
"""
复核打分页：选择一次运行 → 逐图按维度打分、记录问题 → 保存打分表。
打分表结构与 report.py 兼容（reviews 列表，含 case_id/round/scene/image/scores/problems）。
"""
import streamlit as st

from aigc_tester.review import (
    DIMENSIONS,
    dimensions_for_scene,
    build_review_sheet,
    write_review_sheet,
    load_run_records,
    mean_score,
    is_pass,
    PASS_THRESHOLD,
)
from aigc_tester.providers import project_root

st.set_page_config(page_title="复核打分", page_icon="✅", layout="wide")
st.title("✅ 复核打分")
st.caption("评分维度直接来自岗位 JD：图片主体/构图/风格/文字，视频动作/镜头衔接/角色一致性")

# 列出所有运行日志
logs_dir = project_root() / "logs"
logs = sorted(logs_dir.glob("*.jsonl"), reverse=True)
run_ids = [p.stem.replace("run_", "") for p in logs]
run_id = st.selectbox("选择运行批次", run_ids)

if run_id:
    records = load_run_records(str(logs_dir / f"run_{run_id}.jsonl"))

    # 只对成功记录打分（与 build_review_sheet 一致，含多轮）
    success_records = [r for r in records if r.get("status") == "success"]

    if not success_records:
        st.warning("该批次没有可打分的成功产出")
        st.stop()

    # 预生成打分表（含示例初始分数）
    sheet = build_review_sheet(records, run_id)
    initial = {(rv["case_id"], rv["round"]): rv for rv in sheet["reviews"]}

    st.divider()
    for r in success_records:
        case_id = r["case_id"]
        round_no = r.get("round", 1)
        scene = r.get("scene", "图片")
        dims = dimensions_for_scene(scene)
        key_prefix = f"{case_id}_r{round_no}"

        init_rv = initial.get((case_id, round_no), {})
        init_scores = init_rv.get("scores", {})
        init_problems = init_rv.get("problems", [])

        with st.container(border=True):
            c_img, c_form = st.columns([1, 1.4])
            with c_img:
                out_path = project_root() / r.get("output", "")
                st.image(str(out_path), caption=f"{case_id} · 第{round_no}轮")

            with c_form:
                st.markdown(f"**{case_id}** · {scene} · 第{round_no}轮")
                scores = {}
                for dim_key, dim_label in dims.items():
                    scores[dim_key] = st.slider(
                        f"{dim_label}",
                        min_value=1, max_value=5,
                        value=int(init_scores.get(dim_key, 4)),
                        key=f"{key_prefix}_{dim_key}",
                    )
                problem_text = st.text_area(
                    "问题记录（多条用换行分隔）",
                    value="\n".join(init_problems),
                    key=f"{key_prefix}_problem",
                )
                m = mean_score(scores)
                icon = "🟢" if m >= PASS_THRESHOLD else "🔴"
                st.markdown(f"{icon} 均分 **{m:.2f}**（阈值 {PASS_THRESHOLD}）")

    st.divider()
    if st.button("💾 保存打分表", type="primary"):
        final_reviews = []
        for r in success_records:
            case_id = r["case_id"]
            round_no = r.get("round", 1)
            scene = r.get("scene", "图片")
            dims = dimensions_for_scene(scene)
            key_prefix = f"{case_id}_r{round_no}"

            scores = {k: st.session_state[f"{key_prefix}_{k}"] for k in dims}
            problems = [
                line.strip()
                for line in st.session_state[f"{key_prefix}_problem"].splitlines()
                if line.strip()
            ]
            final_reviews.append({
                "case_id": case_id,
                "round": round_no,
                "scene": scene,
                "image": r.get("output", ""),
                "scores": scores,
                "problems": problems,
                "mean": mean_score(scores),
                "pass": is_pass(scores),
            })

        out_sheet = {
            "run_id": run_id,
            "pass_threshold": PASS_THRESHOLD,
            "note": "每项 1~5 分（5最好）；由 Streamlit 复核打分页生成。",
            "reviews": final_reviews,
        }
        path = write_review_sheet(out_sheet, str(project_root() / "reviews"))
        st.success(f"打分表已保存：{path}")
