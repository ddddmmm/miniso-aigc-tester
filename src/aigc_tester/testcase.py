#!/usr/bin/env python3
"""
测试用例读取层（testcase）：把 YAML 套件解析成结构化对象。

结构层级：
  套件（suite）= 多个 TestCase
  TestCase = 基本信息 + 参数 + 检查点 + 多轮记录（Round）
"""

from pathlib import Path
from typing import List, Optional

import yaml
from pydantic import BaseModel, Field


class CaseParams(BaseModel):
    """生成参数。"""
    model: str = "gpt-image-1"
    size: str = "1536x1024"
    quality: str = "high"
    duration: Optional[int] = None


class Round(BaseModel):
    """一轮交互记录：本轮说明 + 对基础参数的覆盖值。"""
    note: str = ""
    params: dict = Field(default_factory=dict)


class TestCase(BaseModel):
    """一条测试用例。"""
    id: str
    scene: str = "商品图"
    title: str = ""
    enabled: bool = True
    provider: str = "mock"
    template: Optional[str] = None
    prompt: str = ""
    references: List[str] = Field(default_factory=list)
    params: CaseParams = Field(default_factory=CaseParams)
    checkpoints: List[str] = Field(default_factory=list)
    rounds: List[Round] = Field(default_factory=list)


def load_suite(suite_path) -> List[TestCase]:
    """读取 YAML 套件文件，返回用例列表。"""
    suite_path = Path(suite_path)
    with open(suite_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not data:
        return []

    return [TestCase(**item) for item in data]
