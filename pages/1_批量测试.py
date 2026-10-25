# -*- coding: utf-8 -*-
"""
批量测试页：选择测试套件 → 批量执行 → 查看结果与统计。
"""
import pandas as pd
import streamlit as st

from aigc_tester.runner import run_suite
from aigc_tester.providers import project_root

st.set_page_config(page_title="批量测试", page_icon="📋", layout="wide")
st.title("📋 批量测试")
st.caption("批量执行结构化用例，自动记录请求参数、接口响应、耗时与异常（JSONL 日志）")

# 列出套件
suite_dir = project_root() / "testcases"
suites = [f.name for f in sorted(suite_dir.glob("*.yaml"))]
col1, col2 = st.columns([2, 1])
with col1:
    suite_name = st.selectbox("选择测试套件", suites)
with col2:
    st.write("")
    st.write("")
    run_clicked = st.button("▶️ 开始执行", type="primary", use_container_width=True)

if run_clicked:
    suite_path = str(suite_dir / suite_name)
    with st.spinner("正在执行全部用例..."):
        summary = run_suite(suite_path)

    st.session_state["last_run_summary"] = summary

    # 统计卡片
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("总记录", summary["total"])
    c2.metric("成功", summary["success"])
    c3.metric("失败", summary["failed"])
    c4.metric("跳过", summary["skipped"])
    st.success(f"执行完成，日志：{summary['log_path']}")

summary = st.session_state.get("last_run_summary")
if summary:
    st.subheader("执行明细")
    rows = []
    for r in summary["records"]:
        rows.append({
            "用例ID": r.get("case_id"),
            "场景": r.get("scene"),
            "轮次": r.get("round", "-"),
            "状态": r.get("status"),
            "耗时(ms)": r.get("latency_ms"),
            "输出": r.get("output"),
            "错误": r.get("error"),
        })
    df = pd.DataFrame(rows)

    def color_status(val):
        if val == "success":
            return "color: green"
        if val == "failed":
            return "color: red"
        if val == "skipped":
            return "color: gray"
        return ""

    st.dataframe(
        df.style.map(color_status, subset=["状态"]),
        use_container_width=True,
        hide_index=True,
    )

    # 展示成功产出的图片/GIF
    st.subheader("产出预览")
    outputs = [r["output"] for r in summary["records"] if r.get("output")]
    if outputs:
        cols = st.columns(3)
        for i, out in enumerate(outputs):
            with cols[i % 3]:
                st.image(str(project_root() / out), caption=out)
