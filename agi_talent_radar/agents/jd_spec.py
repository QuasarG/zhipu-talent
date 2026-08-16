"""JD → TrackSpec 起草器：LLM 按 schema 约束起草，人批激活后才参与评估。

预算约束：单 track 的 dimensions max_points 之和必须等于 TRACK_POINT_BUDGET（60），
与聚合层 overall = common(≤40) + Σtrack_weight×track_score(≤60) 的量纲一致。
"""
from __future__ import annotations

import re

from agi_talent_radar.agents.tracks.shared.spec import TrackSpec
from agi_talent_radar.core import llm_client

TRACK_POINT_BUDGET = 60.0

JD_SPEC_PROMPT = """
你是 AI 人才评估系统里的【岗位 Track 起草 Agent】。
只输出 JSON 对象。

任务：把一份招聘 JD 起草成一个候选人评估 Track（评估规格），供后续对候选人按该岗位方向打分。

输出格式：
{
  "key": "ascii_slug",           // 小写字母/数字/下划线，概括岗位领域，如 multimodal_generation
  "label": "中文 Track 名",       // 如 多模态生成
  "evidence_focus": "一句话说明该 Track 关注什么证据",
  "high_score_rule": "一句话说明什么样的证据组合才配拿高分",
  "keywords": ["路由关键词"],     // 8-15 个，中英混合，用于判断候选人是否涉及该方向
  "dimensions": [
    {"key": "ascii_slug", "label": "中文维度名", "max_points": 数字, "evidence_rule": "该维度看什么证据"}
  ]
}

硬性约束：
1. dimensions 3-6 个，max_points 之和必须精确等于 60。
2. 维度从 JD 的实际工作内容抽象（如 JD 含 RL/加速/工程多个子方向，可各成一维），不要照抄 JD 章节标题。
3. evidence_rule 必须写"看什么实质证据"，不得写"看学校/机构/名气"。
4. 职位要求里的技能关键词（框架、算法名）进 keywords；加分项（顶会、竞赛）写进 high_score_rule。
5. key 必须能稳定标识该岗位领域，不与常见词冲突。
不要输出 Markdown。
""".strip()


def draft_track_spec(title: str, team: str, raw_text: str) -> TrackSpec:
    response = llm_client.call_llm_json(
        JD_SPEC_PROMPT,
        {"title": title, "team": team, "jd": raw_text},
        temperature=0.1,
    )
    spec = TrackSpec.from_dict(response)
    return _normalize_spec(spec)


def _normalize_spec(spec: TrackSpec) -> TrackSpec:
    """兜底归一：slug 净化、维度预算强制收敛到 60 分。"""
    key = re.sub(r"[^a-z0-9_]+", "_", spec.key.lower()).strip("_") or "jd_track"
    dimensions = [d for d in spec.dimensions if d.key and d.max_points > 0][:6]
    total = sum(d.max_points for d in dimensions)
    if dimensions and abs(total - TRACK_POINT_BUDGET) > 1e-6:
        # 按比例缩放到预算，保留一位小数后把零头补给最大维度
        scale = TRACK_POINT_BUDGET / total
        scaled = [round(d.max_points * scale, 1) for d in dimensions]
        scaled[scaled.index(max(scaled))] += round(TRACK_POINT_BUDGET - sum(scaled), 1)
        dimensions = [d.__class__(d.key, d.label, points, d.evidence_rule) for d, points in zip(dimensions, scaled)]
    return TrackSpec(
        key=key,
        label=spec.label or key,
        dimensions=tuple(dimensions),
        evidence_focus=spec.evidence_focus,
        high_score_rule=spec.high_score_rule,
        keywords=spec.keywords,
    )
