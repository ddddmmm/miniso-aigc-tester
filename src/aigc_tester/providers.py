#!/usr/bin/env python3
"""
模型调用层（providers）：把"调用哪个模型"这件事统一封装起来。

- BaseProvider：统一接口，所有模型都实现 generate() / generate_video()
- MockProvider：离线模拟，不联网、不花钱，返回项目自带样例图 / 占位 GIF
- OpenAIProvider：真实调用 OpenAI 图片生成接口（支持参考图 images.edit）
- ArkProvider：火山引擎豆包（OpenAI 兼容接口，国内直连）

命令行和 Streamlit 网页都只调用这里的函数，不直接碰模型。
"""

import base64
import io
import time
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List

import openai
from PIL import Image, ImageDraw


@dataclass
class GenerationResult:
    """一次图片生成的结果：图片数据 + 元信息（供日志和报告使用）。"""
    image_data: bytes
    provider: str
    model: str
    latency_ms: int
    raw_response: dict


@dataclass
class VideoResult:
    """一次视频生成的结果：视频数据 + 元信息。"""
    video_data: bytes
    provider: str
    model: str
    latency_ms: int
    raw_response: dict


def project_root() -> Path:
    """获取项目根目录。本文件位于 src/aigc_tester/ 下，根目录在上两级。"""
    return Path(__file__).resolve().parents[2]


# 视频比例 → 占位尺寸
_VIDEO_DIMS = {
    "9:16": (360, 640),
    "16:9": (640, 360),
    "1:1": (480, 480),
}


def make_mock_gif(size_ratio: str = "9:16", frames_n: int = 8) -> bytes:
    """用样例图生成一个占位 GIF（移动色条 + 帧文字），用于 mock 视频流程。"""
    width, height = _VIDEO_DIMS.get(size_ratio, (360, 640))

    sample = Image.open(project_root() / "assets" / "abstract_art_with_vibrant_colo.png")
    sample = sample.convert("RGB").resize((width, height))

    frames = []
    for i in range(frames_n):
        frame = sample.copy().convert("RGBA")
        overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        # 从上往下移动的红色条
        y = int(height * (i + 1) / (frames_n + 1))
        draw.rectangle([0, y - 6, width, y + 6], fill=(230, 0, 18, 130))

        # 帧文字
        draw.rectangle([0, 0, width, 34], fill=(0, 0, 0, 140))
        draw.text((10, 9), f"MINISO Mock Video  {i+1}/{frames_n}", fill=(255, 255, 255, 255))

        frame = Image.alpha_composite(frame, overlay).convert("RGB")
        frames.append(frame)

    buf = io.BytesIO()
    frames[0].save(
        buf,
        format="GIF",
        save_all=True,
        append_images=frames[1:],
        duration=300,
        loop=0,
    )
    return buf.getvalue()


class BaseProvider:
    """所有 provider 的基类，定义统一接口。"""
    name: str = "base"

    def generate(
        self,
        prompt: str,
        model: str = "gpt-image-1",
        size: str = "1536x1024",
        quality: str = "high",
        style: Optional[str] = None,
        output_format: str = "png",
        references: Optional[List[str]] = None,
    ) -> GenerationResult:
        raise NotImplementedError

    def generate_video(
        self,
        prompt: str,
        model: str = "seedance",
        size: str = "9:16",
        duration: int = 5,
        references: Optional[List[str]] = None,
    ) -> VideoResult:
        raise NotImplementedError


class MockProvider(BaseProvider):
    """离线模拟：不联网、不花钱，返回样例图 / 占位 GIF。"""
    name = "mock"

    def generate(
        self,
        prompt: str,
        model: str = "gpt-image-1",
        size: str = "1536x1024",
        quality: str = "high",
        style: Optional[str] = None,
        output_format: str = "png",
        references: Optional[List[str]] = None,
    ) -> GenerationResult:
        started = time.time()

        if not prompt or not prompt.strip():
            raise ValueError("模拟接口报错：提示词不能为空（prompt is empty）")

        time.sleep(random.uniform(0.3, 0.8))

        sample = project_root() / "assets" / "abstract_art_with_vibrant_colo.png"
        image_data = sample.read_bytes()

        latency_ms = int((time.time() - started) * 1000)
        return GenerationResult(
            image_data=image_data,
            provider=self.name,
            model=model,
            latency_ms=latency_ms,
            raw_response={
                "mocked": True,
                "model": model,
                "size": size,
                "quality": quality,
                "references_count": len(references or []),
                "data": [{"b64_json": f"<{len(image_data)} bytes>"}],
            },
        )

    def generate_video(
        self,
        prompt: str,
        model: str = "seedance",
        size: str = "9:16",
        duration: int = 5,
        references: Optional[List[str]] = None,
    ) -> VideoResult:
        started = time.time()

        if not prompt or not prompt.strip():
            raise ValueError("模拟接口报错：提示词不能为空（prompt is empty）")

        time.sleep(random.uniform(0.3, 0.8))
        video_data = make_mock_gif(size_ratio=size)

        latency_ms = int((time.time() - started) * 1000)
        return VideoResult(
            video_data=video_data,
            provider=self.name,
            model=model,
            latency_ms=latency_ms,
            raw_response={
                "mocked": True,
                "model": model,
                "size": size,
                "duration": duration,
                "frames": 8,
            },
        )


class OpenAIProvider(BaseProvider):
    """真实调用 OpenAI 图片生成接口；有参考图时走 images.edit。"""
    name = "openai"

    def __init__(self, api_key: str):
        self.client = openai.OpenAI(api_key=api_key)

    def generate(
        self,
        prompt: str,
        model: str = "gpt-image-1",
        size: str = "1536x1024",
        quality: str = "high",
        style: Optional[str] = None,
        output_format: str = "png",
        references: Optional[List[str]] = None,
    ) -> GenerationResult:
        started = time.time()

        # 有参考图：走 images.edit（图生图）
        if references:
            ref_path = Path(references[0])
            with open(ref_path, "rb") as img_file:
                edit_params = {
                    "image": img_file,
                    "prompt": prompt,
                    "model": model,
                    "size": size,
                }
                if model == "gpt-image-1":
                    edit_params["output_format"] = output_format
                else:
                    edit_params["response_format"] = "b64_json"
                response = self.client.images.edit(**edit_params)
            image_data = base64.b64decode(response.data[0].b64_json)
        else:
            # 文生图
            max_lengths = {"gpt-image-1": 32000, "dall-e-2": 1000, "dall-e-3": 4000}
            max_length = max_lengths.get(model, 32000)
            if len(prompt) > max_length:
                prompt = prompt[:max_length] + "..."

            api_params = {
                "model": model,
                "prompt": prompt,
                "n": 1,
                "size": size,
                "quality": quality,
            }
            if model == "gpt-image-1":
                api_params["output_format"] = output_format
            elif model == "dall-e-3":
                if style in ["vivid", "natural"]:
                    api_params["style"] = style
                api_params["response_format"] = "b64_json"
            elif model == "dall-e-2":
                api_params["response_format"] = "b64_json"

            response = self.client.images.generate(**api_params)
            image_data = base64.b64decode(response.data[0].b64_json)

        latency_ms = int((time.time() - started) * 1000)
        return GenerationResult(
            image_data=image_data,
            provider=self.name,
            model=model,
            latency_ms=latency_ms,
            raw_response={
                "model": model,
                "size": size,
                "created": getattr(response, "created", None),
                "references_count": len(references or []),
            },
        )


class ArkProvider(OpenAIProvider):
    """火山引擎豆包（方舟）：OpenAI 兼容接口，国内网络直连。"""
    name = "ark"

    def __init__(self, api_key: str):
        self.client = openai.OpenAI(
            api_key=api_key,
            base_url="https://ark.cn-beijing.volces.com/api/v3",
        )

    def generate(
        self,
        prompt: str,
        model: str = "doubao-seedream-5-0-flash-260915",
        size: str = "2K",
        quality: str = "high",
        style: Optional[str] = None,
        output_format: str = "png",
        references: Optional[List[str]] = None,
    ) -> GenerationResult:
        started = time.time()

        response = self.client.images.generate(
            model=model,
            prompt=prompt,
            size=size,
            response_format="b64_json",
        )
        image_data = base64.b64decode(response.data[0].b64_json)

        latency_ms = int((time.time() - started) * 1000)
        return GenerationResult(
            image_data=image_data,
            provider=self.name,
            model=model,
            latency_ms=latency_ms,
            raw_response={
                "model": model,
                "size": size,
                "created": getattr(response, "created", None),
            },
        )


def get_provider(name: str, api_key: Optional[str] = None) -> BaseProvider:
    """工厂函数：按名称获取 provider。"""
    if name == "mock":
        return MockProvider()
    if name == "openai":
        if not api_key:
            raise ValueError(
                "使用 openai 需要先配置 API Key：aigc config set openai_api_key '你的key'"
            )
        return OpenAIProvider(api_key)
    if name in ("ark", "doubao"):
        if not api_key:
            raise ValueError(
                "使用火山引擎豆包需要先配置 Key：aigc config set ark_api_key '你的key'"
            )
        return ArkProvider(api_key)
    raise ValueError(f"未知 provider：{name}（可选：mock / openai / ark）")


# 各模型支持的尺寸清单（统一放在模型层，供 CLI 和 runner 共用）
VALID_SIZES = {
    "gpt-image-1": ["1024x1024", "1536x1024", "1024x1536"],
    "dall-e-2": ["256x256", "512x512", "1024x1024"],
    "dall-e-3": ["1024x1024", "1792x1024", "1024x1792"],
    # 火山引擎豆包 Seedream：支持像素档位（总像素 92万~1677万）或 1K/2K/4K
    "doubao-seedream-4-0-250828": ["1024x1024", "1536x1024", "1024x1536", "2048x2048", "1K", "2K", "4K"],
    "doubao-seedream-4-5-251128": ["1024x1024", "1536x1024", "1024x1536", "2048x2048", "1K", "2K", "4K"],
    "doubao-seedream-5-0-lite-260128": ["1024x1024", "1536x1024", "1024x1536", "2048x2048", "1K", "2K", "4K"],
    # Seedream 5.0 flash：档位 1K/1.5K/2K（默认 2K），像素总像素 92万~462万
    "doubao-seedream-5-0-flash-260915": ["1K", "1.5K", "2K", "1024x1024", "1536x1024", "1024x1536", "2048x2048"],
}

# 视频支持的画面比例
VALID_VIDEO_RATIOS = ["9:16", "16:9", "1:1"]


def validate_model_size(model: str, size: str) -> bool:
    """校验尺寸是否被模型支持。"""
    return size in VALID_SIZES.get(model, [])
