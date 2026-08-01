"""后台论文核验：导入完成后异步触发，不阻塞导入 SSE 流。

导入流程在结构化解析结束后立即结束（SSE 关闭、卡片消失）。
论文核验在 daemon 线程池里跑，结果写回 DB，前端通过轮询刷新状态。
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Optional

# 全局线程池：daemon=True，进程退出时自动回收
_executor: Optional[threading.Thread] = None
_lock = threading.Lock()


def trigger_publication_verification(
    candidate_id: str,
    name: str,
    publications: list[str],
    raw_text: str,
) -> None:
    """启动一个 daemon 线程核验该候选人的论文，立刻返回不阻塞。"""
    t = threading.Thread(
        target=_run_verification,
        args=(candidate_id, name, publications, raw_text),
        daemon=True,
        name=f"pub-verify-{candidate_id}",
    )
    t.start()


def _run_verification(
    candidate_id: str,
    name: str,
    publications: list[str],
    raw_text: str,
) -> None:
    """实际核验逻辑：调 AMiner/OpenAlex → 写 DB。"""
    from agi_talent_radar.core.db.runtime import get_session
    from agi_talent_radar.core.db.orm import CandidateORM

    # 先标记 running
    try:
        with get_session() as session:
            cand = session.get(CandidateORM, candidate_id)
            if cand:
                cand.academic_check_status = "running"
                session.commit()
    except Exception:
        pass

    # 核验
    try:
        from agi_talent_radar.agents.academic.nodes import run_academic_check

        report = run_academic_check(
            name=name, publications=publications, raw_text=raw_text,
        )
        with get_session() as session:
            cand = session.get(CandidateORM, candidate_id)
            if cand:
                cand.academic_report = report.model_dump()
                cand.academic_check_status = "done"
                cand.academic_check_at = datetime.now(timezone.utc)
                session.commit()
    except Exception as exc:
        import warnings

        warnings.warn(f"论文核验失败 {candidate_id}: {exc}")
        # 失败也标记 done，但写真实的 unverifiable 报告（不再写空 {}）
        # 否则 _verification_result 会误判 verified 放行门禁
        from agi_talent_radar.agents.academic.models import AcademicReport, ClaimAlignment, PaperClaim

        fallback_report = AcademicReport(
            warnings=[f"论文核验失败：{exc}"],
            alignments=[
                ClaimAlignment(
                    claim=PaperClaim(title=str(pub)[:200]),
                    verdict="unverifiable",
                    note="核验失败，待人工核验",
                )
                for pub in publications
                if str(pub).strip()
            ],
        )
        with get_session() as session:
            cand = session.get(CandidateORM, candidate_id)
            if cand:
                cand.academic_report = fallback_report.model_dump()
                cand.academic_check_status = "done"
                cand.academic_check_at = datetime.now(timezone.utc)
                session.commit()
