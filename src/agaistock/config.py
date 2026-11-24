"""配置读取：评分维度与点评师注册表。

只读仓库内的 JSON 配置，不读宿主的任何私有配置文件（主规格 D3）。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def repo_root() -> Path:
    """仓库根目录：src/agaistock/config.py -> src/agaistock -> src -> 根。"""
    return Path(__file__).resolve().parents[2]


def _load_json(relative_path: str) -> Any:
    path = repo_root() / relative_path
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_scoring() -> dict:
    """返回 {"dimensions": [{"name": str, "weight": float}, ...]}"""
    data = _load_json("config/scoring.json")
    dimensions = data.get("dimensions")
    if not isinstance(dimensions, list) or not dimensions:
        raise ValueError("config/scoring.json 缺少 dimensions")
    for item in dimensions:
        if "name" not in item or "weight" not in item:
            raise ValueError(f"维度定义缺字段: {item}")
    return {"dimensions": dimensions}


def load_reviewers() -> list[dict]:
    """返回点评师注册列表，按配置顺序。"""
    data = _load_json("config/reviewers.json")
    reviewers = data.get("reviewers")
    if not isinstance(reviewers, list):
        raise ValueError("config/reviewers.json 缺少 reviewers")
    for item in reviewers:
        for key in ("id", "enabled", "module", "weight"):
            if key not in item:
                raise ValueError(f"点评师注册缺字段 {key}: {item}")
    return reviewers
