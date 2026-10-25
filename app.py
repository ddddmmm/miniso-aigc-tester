# -*- coding: utf-8 -*-
"""
Streamlit 首页：素材生成（选模板 → 编辑提示词 → 上传参考图 → 生成 → 保存）
运行方式：streamlit run app.py
"""
import os
from datetime import datetime
from pathlib import Path

import streamlit as st

from aigc_tester.providers import (
    get_provider,
    VALID_SIZES,
    VALID_VIDEO_RATIOS,
    project_root,
)
from aigc_tester.config import config_manager

st.set_page_config(page_title="MINISO AIGC 素材测试", page_icon="🛍️", layout="wide")


def list_templates():
    """列出 templates 下所有模板（相对路径 → 绝对路径）。"""
    tpl_dir = project_root() / "templates"
    items = []
    for f in sorted(tpl_dir.rglob("*.md")):
        items.append((str(f.relative_to(tpl_dir)), f))
    return items


st.title("🛍️ 名创优品 AIGC 营销素材测试工具")
st.caption("生成 → 记录 → 复核 → 报告 一站式（默认离线 mock，不联网不花钱）")

with st.sidebar:
    st.header("⚙️ 设置")
    provider_name = st.selectbox("模型提供方", ["mock", "openai", "ark"])
    media_type = st.radio("素材类型", ["🖼️ 图片", "🎬 视频"])
    st.divider()
    st.page_link("pages/1_批量测试.py", label="批量测试", icon="📋")
    st.page_link("pages/2_复核打分.py", label="复核打分", icon="✅")
    st.page_link("pages/3_报告查看.py", label="报告查看", icon="📊")

left, right = st.columns([1.1, 1])

with left:
    # 1. 模板选择
    st.subheader("1️⃣ 选择提示词模板")
    templates = list_templates()
    tpl_labels = ["不使用模板"] + [label for label, _ in templates]
    chosen = st.selectbox("模板", tpl_labels)

    if chosen != "不使用模板":
        tpl_path = dict(templates)[chosen]
        tpl_content = tpl_path.read_text(encoding="utf-8")
        if st.button("📥 载入模板内容"):
            # 直接写入 text_area 的 keyed session state，下次渲染生效
            st.session_state.prompt_box = tpl_content

    # 2. 提示词编辑
    st.subheader("2️⃣ 编辑提示词")
    prompt = st.text_area(
        "提示词",
        height=220,
        key="prompt_box",
    )

    # 3. 参考图上传
    st.subheader("3️⃣ 参考图（可选）")
    ref_file = st.file_uploader("上传商品原图 / IP 角色图", type=["png", "jpg", "jpeg", "webp"])
    ref_path = None
    if ref_file is not None:
        ref_dir = project_root() / "references"
        ref_dir.mkdir(exist_ok=True)
        ref_path = ref_dir / ref_file.name
        ref_path.write_bytes(ref_file.getvalue())
        st.image(ref_file, caption="已上传参考图", width=200)

    # 4. 参数
    st.subheader("4️⃣ 生成参数")
    is_video = media_type.startswith("🎬")
    if is_video:
        ratio = st.selectbox("画面比例", VALID_VIDEO_RATIOS)
        duration = st.number_input("时长（秒）", min_value=1, max_value=120, value=5)
    else:
        if provider_name == "ark":
            model = st.selectbox(
                "模型",
                ["doubao-seedream-5-0-flash-260915", "doubao-seedream-5-0-lite-260128", "doubao-seedream-4-5-251128", "doubao-seedream-4-0-250828"],
            )
        else:
            model = st.selectbox("模型", ["gpt-image-1", "dall-e-3", "dall-e-2"])
        size = st.selectbox("尺寸", VALID_SIZES[model])
        quality = st.selectbox("质量", ["high", "medium", "low"])

    generate_clicked = st.button("🚀 生成", type="primary", use_container_width=True)

with right:
    st.subheader("生成结果")
    if generate_clicked:
        if not prompt.strip():
            st.error("提示词不能为空")
            st.stop()

        config = config_manager.load_config()
        if provider_name == "openai":
            api_key = config.openai_api_key or os.getenv("OPENAI_API_KEY")
        elif provider_name == "ark":
            api_key = config.ark_api_key or os.getenv("ARK_API_KEY") or os.getenv("ark_api_key") or os.getenv("AIGC_API")
        else:
            api_key = None

        try:
            provider = get_provider(provider_name, api_key)
            ts = datetime.now().strftime("%H%M%S")
            with st.spinner("正在生成..."):
                if is_video:
                    result = provider.generate_video(
                        prompt, model="seedance", size=ratio, duration=duration
                    )
                    out_path = project_root() / "outputs" / f"web_{ts}.gif"
                    out_path.write_bytes(result.video_data)
                    st.image(str(out_path), caption="视频占位 GIF")
                else:
                    result = provider.generate(
                        prompt,
                        model=model,
                        size=size,
                        quality=quality,
                        references=[str(ref_path)] if ref_path else None,
                    )
                    out_path = project_root() / "outputs" / f"web_{ts}.png"
                    out_path.write_bytes(result.image_data)
                    st.image(str(out_path), caption="生成结果")

            st.success(f"已保存：{out_path.relative_to(project_root())}（耗时 {result.latency_ms}ms）")
            with st.expander("查看接口响应"):
                st.json(result.raw_response)
        except Exception as e:
            st.error(f"生成失败：{type(e).__name__}: {e}")
