from __future__ import annotations

import json
import re
from typing import Any


def dimension_items(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, str):
        try:
            return dimension_items(json.loads(value))
        except json.JSONDecodeError:
            return []
    if isinstance(value, list):
        rows: list[dict[str, Any]] = []
        for item in value:
            rows.extend(dimension_items(item))
        return rows
    if not isinstance(value, dict):
        return []
    if value.get("key"):
        return [value]

    rows = []
    for key, item in value.items():
        if isinstance(item, dict):
            row = dict(item)
            row.setdefault("key", str(key))
        else:
            row = {"key": str(key), "score": item}
        rows.append(row)
    return rows


def score_value(value: Any) -> float:
    if isinstance(value, (int, float)):
        score = float(value)
    elif isinstance(value, str):
        match = re.search(r"-?\d+(?:\.\d+)?", value)
        score = float(match.group()) if match else 0.0
    else:
        score = 0.0
    return max(0.0, min(5.0, round(score, 1)))


def string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value]
    return []
