from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StageProfile:
    key: str
    label: str
    evidence_expectation: str
    project_potential_first: bool = False
    external_verification_expected: bool = False


EARLY = StageProfile(
    key="early",
    label="早期培养阶段",
    evidence_expectation="重点看项目中的问题定义、本人动作、技术深度、验证思路和学习迁移；发表数量不足不单独扣分。",
    project_potential_first=True,
)

ADVANCED = StageProfile(
    key="advanced",
    label="高年级/成熟阶段",
    evidence_expectation="除项目能力外，应重点核验论文、代码库、系统产物或正式交付的真实性、作者贡献和持续产出。",
    external_verification_expected=True,
)

STANDARD = StageProfile(
    key="standard",
    label="阶段未细分",
    evidence_expectation="按项目、论文、工程产物和本人贡献的可追溯证据综合评价。",
)


def profile_for_stage(stage: str) -> StageProfile:
    text = (stage or "").replace(" ", "").lower()
    if any(marker in text for marker in ("本科", "大一", "大二", "大三", "大四", "博一", "博士一年", "研一", "硕一", "硕士一年", "直博一", "硕博连读一")):
        return EARLY
    if any(marker in text for marker in ("博士候选", "博士后", "博四", "博五", "博士四", "博士五", "博士后期", "接近毕业", "毕业年")):
        return ADVANCED
    return STANDARD
