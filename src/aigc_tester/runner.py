#!/usr/bin/env python3
"""
批量执行引擎（runner）：读取套件 → 逐轮执行 → 保存结果 → 写 JSONL 日志。

日志位置：logs/run_YYYYMMDD_HHMMSS.jsonl，每一行记录一个"用例-轮次"的完整信息。
本模块不依赖任何界面，CLI 和 Streamlit 都可以直接调用 run_suite()。
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from .providers import (
    get_provider,
    validate_model_size,
    VALID_SIZES,
    VALID_VIDEO_RATIOS,
)
from .testcase import load_suite, CaseParams, Round
from .config import config_manager


def _resolve_key(provider: str, override_key: Optional[str]) -> Optional[str]:
    """按 provider 从配置/环境变量解析对应 API Key（mock 不需要）。"""
    if override_key:
        return override_key
    cfg = config_manager.load_config()
    if provider in ("ark", "doubao"):
        return cfg.ark_api_key or os.getenv("ARK_API_KEY") or os.getenv("ark_api_key") or os.getenv("AIGC_API")
    if provider == "openai":
        return cfg.openai_api_key or os.getenv("OPENAI_API_KEY")
    return None


def _now_iso() -> str:
    """当前时间（ISO 格式，秒）。"""
    return datetime.now().isoformat(timespec="seconds")


def save_image(image_data: bytes, output_path: Path) -> None:
    """保存图片二进制到文件。"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(image_data)


def run_suite(
    suite_path: str,
    output_dir: str = "outputs",
    logs_dir: str = "logs",
    api_key: Optional[str] = None,
) -> dict:
    """执行一整套测试用例。

    Returns:
        汇总字典：run_id、log_path、records（全部记录）、统计计数。
    """
    cases = load_suite(suite_path)

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = Path(logs_dir) / f"run_{run_id}.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    records: List[dict] = []

    for case in cases:
        # 停用的用例：记录跳过，不执行
        if not case.enabled:
            skip_record = {
                "ts": _now_iso(),
                "run_id": run_id,
                "case_id": case.id,
                "scene": case.scene,
                "status": "skipped",
                "error": None,
            }
            records.append(skip_record)
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(skip_record, ensure_ascii=False) + "\n")
            continue

        # 没有显式 rounds 时，构造一个默认单轮
        rounds = case.rounds if case.rounds else [Round(note="单轮执行")]
        multi_round = len(rounds) > 1

        for round_idx, round_spec in enumerate(rounds, start=1):
            # 合并基础参数和本轮覆盖参数
            merged = case.params.model_dump()
            merged.update(round_spec.params)
            params = CaseParams(**merged)

            is_video = case.scene == "视频"

            # 结果文件命名：多轮时带 _r1/_r2 后缀；视频用 .gif
            suffix = f"_r{round_idx}" if multi_round else ""
            ext = ".gif" if is_video else ".png"
            output_path = Path(output_dir) / f"{case.id}{suffix}{ext}"

            record = {
                "ts": _now_iso(),
                "run_id": run_id,
                "case_id": case.id,
                "scene": case.scene,
                "round": round_idx,
                "round_note": round_spec.note,
                "provider": case.provider,
                "request": {
                    "model": params.model,
                    "size": params.size,
                    "prompt": case.prompt,
                    "references": case.references,
                },
                "latency_ms": None,
                "status": None,
                "output": None,
                "error": None,
            }
            if is_video:
                record["request"]["duration"] = params.duration or 5
            else:
                record["request"]["quality"] = params.quality

            try:
                # 1. 调用前校验：空提示词
                if not case.prompt or not case.prompt.strip():
                    raise ValueError("提示词不能为空（prompt is empty）")

                provider = get_provider(case.provider, _resolve_key(case.provider, api_key))

                if is_video:
                    # 2. 视频：校验画面比例
                    if params.size not in VALID_VIDEO_RATIOS:
                        raise ValueError(
                            f"视频比例 {params.size} 不支持，合法比例：{VALID_VIDEO_RATIOS}"
                        )
                    # 3. 调用视频生成
                    result = provider.generate_video(
                        case.prompt,
                        model=params.model,
                        size=params.size,
                        duration=params.duration or 5,
                    )
                    save_image(result.video_data, output_path)
                else:
                    # 2. 图片：校验尺寸合法性
                    if not validate_model_size(params.model, params.size):
                        valid = VALID_SIZES.get(params.model, [])
                        raise ValueError(
                            f"尺寸 {params.size} 不被模型 {params.model} 支持，合法尺寸：{valid}"
                        )
                    # 3. 调用图片生成
                    result = provider.generate(
                        case.prompt,
                        model=params.model,
                        size=params.size,
                        quality=params.quality,
                        references=case.references or None,
                    )
                    save_image(result.image_data, output_path)

                # 4. 记录结果
                record["latency_ms"] = result.latency_ms
                record["raw_response"] = result.raw_response
                record["status"] = "success"
                record["output"] = str(output_path).replace("\\", "/")

            except Exception as e:
                record["status"] = "failed"
                record["error"] = f"{type(e).__name__}: {e}"

            # 写日志 + 收集记录
            records.append(record)
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

    # 汇总统计
    summary = {
        "run_id": run_id,
        "log_path": str(log_path).replace("\\", "/"),
        "records": records,
        "total": len(records),
        "success": sum(1 for r in records if r["status"] == "success"),
        "failed": sum(1 for r in records if r["status"] == "failed"),
        "skipped": sum(1 for r in records if r["status"] == "skipped"),
    }
    return summary
