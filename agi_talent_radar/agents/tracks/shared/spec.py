from __future__ import annotations

from dataclasses import dataclass

from agi_talent_radar.core.models import TrackKey


@dataclass(frozen=True)
class TrackDimensionSpec:
    key: str
    label: str
    max_points: float
    evidence_rule: str

    def as_prompt_dict(self) -> dict[str, str | float]:
        return {
            "key": self.key,
            "label": self.label,
            "max_points": self.max_points,
            "evidence_rule": self.evidence_rule,
        }


@dataclass(frozen=True)
class TrackSpec:
    """Track 评估规格：JD 池驱动，LLM 起草 + 人批激活，入库持久化（不再是硬编码）。"""

    key: TrackKey
    label: str
    dimensions: tuple[TrackDimensionSpec, ...]
    evidence_focus: str
    high_score_rule: str
    # 路由关键词：LLM 起草时生成，用于资格校验与保守回退（替代原硬编码关键词表）
    keywords: tuple[str, ...] = ()

    @property
    def max_points(self) -> float:
        return sum(item.max_points for item in self.dimensions)

    def as_prompt_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "label": self.label,
            "max_points": self.max_points,
            "evidence_focus": self.evidence_focus,
            "high_score_rule": self.high_score_rule,
            "dimensions": [item.as_prompt_dict() for item in self.dimensions],
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.as_prompt_dict(), "keywords": list(self.keywords)}

    @staticmethod
    def from_dict(raw: dict[str, object]) -> "TrackSpec":
        dimensions = tuple(
            TrackDimensionSpec(
                key=str(item.get("key", "")),
                label=str(item.get("label", "")),
                max_points=float(item.get("max_points", 0)),
                evidence_rule=str(item.get("evidence_rule", "")),
            )
            for item in raw.get("dimensions", [])  # type: ignore[union-attr]
        )
        return TrackSpec(
            key=str(raw.get("key", "")),
            label=str(raw.get("label", "")),
            dimensions=dimensions,
            evidence_focus=str(raw.get("evidence_focus", "")),
            high_score_rule=str(raw.get("high_score_rule", "")),
            keywords=tuple(str(word) for word in raw.get("keywords", [])),  # type: ignore[union-attr]
        )
