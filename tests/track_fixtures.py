from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import patch

from agi_talent_radar.agents.tracks.shared.spec import TrackDimensionSpec, TrackSpec


def make_spec(key: str, label: str = "", keywords: tuple[str, ...] = (), dims: tuple = ()) -> TrackSpec:
    """构造 JD 风格的动态 TrackSpec（默认二维 60 分预算）。"""
    dims = dims or (("depth", "方法深度", 30), ("delivery", "工程交付", 30))
    return TrackSpec(
        key=key,
        label=label or key,
        dimensions=tuple(TrackDimensionSpec(k, lbl, pts, f"{lbl}的证据") for k, lbl, pts in dims),
        evidence_focus=f"{label or key} 相关证据",
        high_score_rule="多源交叉验证方可高分",
        keywords=tuple(keywords),
    )


def make_dynamic_specs() -> dict[str, TrackSpec]:
    """一组覆盖 mock 路由输出的动态 spec（与 llm_fixtures 的 track key 对齐）。"""
    return {
        "agent": make_spec("agent", "Agent", keywords=("agent", "智能体")),
        "ai_infra": make_spec("ai_infra", "AI Infra", keywords=("cuda", "triton")),
        "base": make_spec("base", "Base", keywords=("预训练", "transformer")),
        "multimodal": make_spec("multimodal", "多模态", keywords=("多模态", "视觉")),
        "safety": make_spec("safety", "安全", keywords=("安全", "angr", "hook")),
        "ai4science": make_spec("ai4science", "AI4Science", keywords=("生物", "蛋白")),
    }


@contextmanager
def patch_active_specs(specs=None):
    """全链路测试用：把三处 load_active_specs 统一替换成动态 spec fixture。"""
    specs = specs if specs is not None else make_dynamic_specs()
    with (
        patch("agi_talent_radar.agents.tracks.registry.load_active_specs", return_value=specs),
        patch("agi_talent_radar.agents.routing.track_router.load_active_specs", return_value=specs),
        patch("agi_talent_radar.agents.evidence_extractor.load_active_specs", return_value=specs),
    ):
        yield specs
