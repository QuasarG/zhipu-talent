from __future__ import annotations

from dataclasses import dataclass

from agi_talent_radar.core.models import TrackKey


@dataclass(frozen=True)
class TrackDimensionSpec:
    key: str
    label: str
    max_points: float
    evidence_rule: str
    anchors: dict[float, str] | None = None

    def as_prompt_dict(self) -> dict[str, str | float | dict]:
        return {
            "key": self.key,
            "label": self.label,
            "max_points": self.max_points,
            "evidence_rule": self.evidence_rule,
            "anchors": self.anchors or {},
        }


@dataclass(frozen=True)
class TrackSpec:
    key: TrackKey
    label: str
    dimensions: tuple[TrackDimensionSpec, ...]
    evidence_focus: str
    high_score_rule: str

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
