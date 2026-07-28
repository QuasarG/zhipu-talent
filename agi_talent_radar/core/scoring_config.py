"""评分参数单一真相源：所有影响最终分数的魔法数字集中于此。

之前散落在 common_potential/nodes.py、tracks/shared/engine.py、
aggregation/nodes.py、formatter.py、workbench.py 五处，且 90/80/60 阈值
复制了三次、2.5/3.5 封顶值两处实现有细微差异。本模块统一收口。

调参时只改这里，config_version 会自动反映。
"""
from __future__ import annotations

from dataclasses import dataclass, field

# 维度分基础：LLM 输出 0-5，加权公式 = score / RAW_MAX * max_points。
# 该值纳入配置版本；如调整量表，必须与 score_value 的输入校验同步修改。
RAW_MAX = 5.0

COMMON_WEIGHTS = {
    "problem_definition": 8,
    "research_rigor": 9,
    "learning_transfer": 3,
    "ownership": 8,
    "evidence_credibility": 9,
    "growth_trajectory": 3,
}

@dataclass(frozen=True)
class Caps:
    """证据校准封顶值（score 范围 0-5）。"""
    no_evidence: float = 1.0        # 无可追溯证据
    no_verification: float = 2.5    # 缺量化指标/对照/复现/正式发表
    no_high_score_support: float = 3.5  # 高分缺动作+指标+ownership 组合

    def for_no_evidence(self, score: float) -> float:
        return min(score, self.no_evidence)

    def for_no_verification(self, score: float) -> float:
        return min(score, self.no_verification)

    def for_no_high_score(self, score: float) -> float:
        return min(score, self.no_high_score_support)


@dataclass(frozen=True)
class PortfolioFloors:
    """通用潜力 portfolio floor：强证据组合触发时各维度保底分。

    之前硬编码在 common_potential/nodes.py _apply_research_portfolio_floors。
    """
    strong_sources_min: int = 6     # strength>=4 的不同来源数
    owned_min: int = 3              # has_ownership 证据数
    published_min: int = 2          # 正式发表成果数
    floors: dict = field(default_factory=lambda: {
        "problem_definition": 4.0,
        "research_rigor": 4.0,
        "learning_transfer": 3.5,
        "ownership": 4.5,
        "evidence_credibility": 4.5,
        "growth_trajectory": 4.0,
    })


@dataclass(frozen=True)
class AggregateBounds:
    """汇总封顶边界。"""
    common_max: float = 40.0
    overall_max: float = 100.0
    overall_min: float = 0.0


@dataclass(frozen=True)
class LevelThresholds:
    """等级与沟通建议阈值，之前复制在 aggregation/formatter/workbench 三处。"""
    s: int = 90
    a: int = 80
    b: int = 60

    def level_for_score(self, score: int) -> str:
        if score >= self.s:
            return "S"
        if score >= self.a:
            return "A"
        if score >= self.b:
            return "B"
        return "C"

    def tier_for_score(self, score: int) -> str:
        if score >= self.a:
            return "强烈建议沟通"
        if score >= self.b:
            return "建议沟通"
        return "暂缓 / 需补充信息"

    def pool_for_score(self, score: int) -> str:
        """前端分组用（对应 shortlisted/alternative/rejected）。"""
        if score >= self.a:
            return "shortlisted"
        if score >= self.b:
            return "alternative"
        return "rejected"

    def routing_note(self) -> str:
        """供界面和批量结果复用的分流说明。"""
        return (
            f"{self.a} 分及以上进入优选库，{self.b}-{self.a - 1} 分进入备选库，"
            f"低于 {self.b} 分进入不建议后续沟通。"
        )


@dataclass(frozen=True)
class ScoringConfig:
    """评分参数单一真相源。调参只改这里。"""
    caps: Caps = field(default_factory=Caps)
    portfolio_floors: PortfolioFloors = field(default_factory=PortfolioFloors)
    aggregate_bounds: AggregateBounds = field(default_factory=AggregateBounds)
    thresholds: LevelThresholds = field(default_factory=LevelThresholds)
    def weighted_score(self, score: float, max_points: float) -> float:
        """统一加权公式：score / RAW_MAX * max_points。"""
        return round(score / RAW_MAX * max_points, 2)

    def stage_note(self, stage: str) -> str:
        """早期阶段候选人的潜力预期线提示（不改分数，只增强可解释性）。

        博一/本科等早期候选人缺乏发表成果属正常，不应与高年级同尺衡量。
        """
        s = (stage or "").strip()
        early_markers = ("本科", "博一", "研一", "硕士一", "直博一", "硕博连读一")
        if any(m in s for m in early_markers):
            return "处于早期阶段，发表/成果积累有限属正常，潜力信号（问题定义、学习迁移、成长轨迹）值得重点关注。"
        return ""


# 全局默认实例（模块级单例，绝大多数调用直接用这个）
DEFAULT = ScoringConfig()
