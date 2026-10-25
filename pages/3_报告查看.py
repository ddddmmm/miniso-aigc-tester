# -*- coding: utf-8 -*-
"""
报告查看页：生成报告、列出已有报告、下载 HTML。
"""
import os
import streamlit as st

from aigc_tester.report import generate_report
from aigc_tester.providers import project_root

st.set_page_config(page_title="报告查看", page_icon="📊", layout="wide")
st.title("📊 报告查看")
st.caption("自包含 HTML 报告：通过率、维度均分、用例明细、问题清单、回归对比")

reports_dir = project_root() / "reports"
reports_dir.mkdir(exist_ok=True)

col1, col2 = st.columns([2, 1])
with col1:
    st.write("对最新一次运行生成报告（需先完成批量测试和复核打分）")
with col2:
    gen_clicked = st.button("🔄 生成最新报告", type="primary", use_container_width=True)

if gen_clicked:
    try:
        with st.spinner("正在生成报告..."):
            result = generate_report(reports_dir=str(reports_dir))
        st.success(
            f"报告已生成：{result['html_path']}"
            f"（{'含打分表' if result['has_reviews'] else '仅执行结果，建议先复核打分'}）"
        )
    except FileNotFoundError as e:
        st.error(str(e))
    except Exception as e:
        st.error(f"生成失败：{type(e).__name__}: {e}")

st.divider()
st.subheader("已有报告")

html_files = sorted(reports_dir.glob("*.html"), reverse=True)
if not html_files:
    st.info("暂无报告")
else:
    for f in html_files:
        size_kb = f.stat().st_size / 1024
        with st.container(border=True):
            c1, c2 = st.columns([3, 1])
            with c1:
                st.markdown(f"**{f.name}**  ·  {size_kb/1024:.1f} MB")
            with c2:
                with open(f, "rb") as fh:
                    st.download_button(
                        "⬇️ 下载",
                        data=fh.read(),
                        file_name=f.name,
                        mime="text/html",
                        key=f"dl_{f.name}",
                        use_container_width=True,
                    )
