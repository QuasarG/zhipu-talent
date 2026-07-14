from agi_talent_radar.agents.tracks.shared.spec import TrackDimensionSpec as D
from agi_talent_radar.agents.tracks.shared.spec import TrackSpec


SPEC = TrackSpec(
    key="multimodal",
    label="Multimodal 多模态",
    evidence_focus="跨模态表征、对齐、感知推理、数据构建、鲁棒性、时空与 3D Grounding 证据。",
    high_score_rule="必须解释模态如何表示和融合、数据如何构建以及跨域后是否有效，调用视觉 API 不能高分。",
    dimensions=(
        D("cross_modal_alignment", "跨模态表征与对齐", 10, "看编码器、投影、Token 对齐、融合和训练目标。"),
        D("perception_reasoning", "感知、推理与生成深度", 11, "看视觉理解、跨模态推理、生成和任务复杂度。"),
        D("multimodal_data", "多模态数据构建与合成", 8, "看采集、标注、合成、负样本与质量控制。"),
        D("multimodal_robustness", "评测、鲁棒性与 OOD", 10, "看扰动、长尾、幻觉、跨域和模态缺失。"),
        D("spatiotemporal_grounding", "空间、时序与 3D Grounding", 8, "看视频时序、空间关系、3D 几何和具身 Grounding。"),
        D("multimodal_system", "模型与系统集成", 7, "看训练、推理、部署、数据流水线和效率。"),
        D("multimodal_originality", "跨模态原创性", 6, "看新的对齐、推理、数据或任务范式。"),
    ),
)
