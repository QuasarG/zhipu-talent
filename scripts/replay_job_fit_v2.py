"""只读回放少量真实简历，验证同一候选人在不同 JD 下得到独立结论。"""
from __future__ import annotations

import json

from agi_talent_radar.agents.job_fit import evaluate_candidate_against_jobs
from agi_talent_radar.core.db.orm import CandidateORM
from agi_talent_radar.core.db.runtime import get_session
from agi_talent_radar.core.models import CandidateResume, JobDefinition
from agi_talent_radar.services.talent_service import _candidate_orm_to_resume


CANDIDATE_IDS = (
    "candidate_56d53d83",  # 张琳浩：Agent 评测强匹配
    "candidate_fe36255d",  # 梁广：多模态训练/Infra 强，生成直接性待验证
    "Runxi_WANG_-_Multimodal_System_A",  # 王润熙：有 Benchmark，但 Agent 直接经验弱
)

JOBS = (
    JobDefinition(
        id="agent_evaluation",
        title="算法工程师（Agent 评测方向）",
        raw_text=(
            "负责 Agent Benchmark、long-horizon、Web/GUI/Coding Agent、Verifier、"
            "LLM-as-a-Judge，以及评测到数据和训练的闭环。必须有实习经验，"
            "能够长期实习一年；有 Agent 评测或 Agent 后训练经验优先。"
        ),
    ),
    JobDefinition(
        id="multimodal_generation",
        title="多模态生成算法研究",
        raw_text=(
            "负责多模态生成模型研究和训练，重点关注图像/视频生成、Diffusion 或统一理解生成架构，"
            "需要大模型训练、数据构建、效果评测和工程落地经验。"
        ),
    ),
    JobDefinition(
        id="pretraining_data",
        title="预训练数据算法工程师",
        raw_text=(
            "负责大模型预训练数据的获取、清洗、合成、质量评估和数据闭环，"
            "需要能用模型和规则发现数据问题，并证明数据对训练效果的增益。"
        ),
    ),
)


def main() -> None:
    with get_session() as session:
        rows = [session.get(CandidateORM, candidate_id) for candidate_id in CANDIDATE_IDS]
        resumes: list[CandidateResume] = [
            _candidate_orm_to_resume(row)
            for row in rows
            if row is not None
        ]

    results = []
    for resume in resumes:
        evaluation = evaluate_candidate_against_jobs(resume, JOBS)
        results.append(
            {
                "candidate_id": resume.id,
                "candidate_name": resume.name,
                "best_fit": evaluation.best_fit_jd_title,
                "assessments": [
                    {
                        "jd": item.jd_title,
                        "decision": item.decision,
                        "fit_score": item.fit_score,
                        "hard_requirements": [
                            {"requirement": req.requirement, "status": req.status}
                            for req in item.hard_requirements
                        ],
                        "reason": item.decision_reason,
                    }
                    for item in evaluation.assessments
                ],
            }
        )
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
