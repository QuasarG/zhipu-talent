from __future__ import annotations

import json
import os
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agi_talent_radar.core.io import load_resumes
from agi_talent_radar.core.runner import run_candidate


OUTPUT_JSON = ROOT / "outputs" / "consistency_eval.json"
OUTPUT_MD = ROOT / "outputs" / "consistency_eval.md"
RUNS_PER_CANDIDATE = 5
MAX_RETRIES = 3
RETRY_SECONDS = 8
DEFAULT_WORKERS = 10
SAVE_LOCK = Lock()


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("用法: python scripts/run_consistency_eval.py <resume-file>")
    resumes = load_resumes(Path(sys.argv[1]))
    rounds = _load_checkpoint()

    for round_index in range(1, RUNS_PER_CANDIDATE + 1):
        round_results = _round_results(rounds, round_index)
        print(f"开始第 {round_index}/{RUNS_PER_CANDIDATE} 轮评估", flush=True)
        existing_ids = {item["id"] for item in round_results}
        pending = []
        for resume in resumes:
            if resume.id in existing_ids:
                print(f"  {resume.id}: 已存在，跳过", flush=True)
            else:
                pending.append(resume)
        if pending:
            workers = min(_worker_count(), len(pending))
            print(f"  并发评估 {len(pending)} 位候选人，workers={workers}", flush=True)
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {executor.submit(_run_with_retry, resume): resume for resume in pending}
                for future in as_completed(futures):
                    resume = futures[future]
                    evaluation = future.result()
                    item = _evaluation_item(round_index, evaluation)
                    round_results.append(item)
                    _save(rounds)
                    print(f"  {evaluation.id}: 能力摘要 {evaluation.overall_score}", flush=True)

        if round_results not in rounds:
            rounds.append(round_results)
        _save(rounds)

    print(f"已写入 {OUTPUT_JSON}")
    print(f"已写入 {OUTPUT_MD}")


def _evaluation_item(round_index: int, evaluation) -> dict[str, Any]:
    return {
        "round": round_index,
        "id": evaluation.id,
        "name": evaluation.name,
        "target_role": evaluation.target_role,
        "overall_score": evaluation.overall_score,
        "one_liner": evaluation.one_liner,
    }


def _worker_count() -> int:
    raw = os.getenv("CONSISTENCY_WORKERS", str(DEFAULT_WORKERS)).strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return DEFAULT_WORKERS


def _run_with_retry(resume):
    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return run_candidate(resume)
        except Exception as exc:
            last_error = exc
            print(f"  {resume.id}: 第 {attempt}/{MAX_RETRIES} 次失败：{exc}", flush=True)
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_SECONDS * attempt)
    raise RuntimeError(f"{resume.id} 连续失败 {MAX_RETRIES} 次") from last_error


def _load_checkpoint() -> list[list[dict[str, Any]]]:
    if not OUTPUT_JSON.exists():
        return []
    try:
        payload = json.loads(OUTPUT_JSON.read_text(encoding="utf-8"))
        rounds = payload.get("rounds", [])
        return rounds if isinstance(rounds, list) else []
    except Exception:
        return []


def _round_results(rounds: list[list[dict[str, Any]]], round_index: int) -> list[dict[str, Any]]:
    for items in rounds:
        if items and int(items[0].get("round", 0)) == round_index:
            return items
    items: list[dict[str, Any]] = []
    rounds.append(items)
    return items


def _save(rounds: list[list[dict[str, Any]]]) -> None:
    with SAVE_LOCK:
        completed_rounds = [items for items in rounds if items]
        summary = _summarize(completed_rounds) if completed_rounds else []
        payload = {"runs_per_candidate": RUNS_PER_CANDIDATE, "summary": summary, "rounds": completed_rounds}
        OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        OUTPUT_MD.write_text(_render_markdown(summary, completed_rounds), encoding="utf-8")


def _summarize(rounds: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    by_id: dict[str, list[dict[str, Any]]] = {}
    for round_results in rounds:
        for item in round_results:
            by_id.setdefault(item["id"], []).append(item)

    summary: list[dict[str, Any]] = []
    for candidate_id, items in by_id.items():
        scores = [int(item["overall_score"]) for item in items]
        summary.append(
            {
                "id": candidate_id,
                "name": items[0]["name"],
                "target_role": items[0]["target_role"],
                "scores": scores,
                "mean_score": round(statistics.mean(scores), 2),
                "score_std": round(statistics.pstdev(scores), 2),
                "score_range": max(scores) - min(scores),
            }
        )
    return sorted(summary, key=lambda item: item["id"])


def _render_markdown(summary: list[dict[str, Any]], rounds: list[list[dict[str, Any]]]) -> str:
    completed_runs = [items for items in rounds if len(items) == len(summary)]
    lines = [
        "# 一致性评估实验",
        "",
        f"- 计划每位候选人独立评估次数：{RUNS_PER_CANDIDATE}",
        f"- 当前已完成完整轮次：{len(completed_runs)}",
        "- 实验方式：每轮重新跑完整评估链路，观察能力摘要分的稳定性。",
        "- 脚本支持断点续跑；再次执行会跳过已经完成的候选人。",
        "",
        "## 汇总",
        "",
        "| 候选人 | 能力摘要均分 | 分数标准差 | 分数范围 |",
        "| --- | ---: | ---: | ---: |",
    ]
    for item in summary:
        lines.append(
            "| {name} | {mean_score} | {score_std} | {score_range} |".format(
                name=item["name"],
                mean_score=item["mean_score"],
                score_std=item["score_std"],
                score_range=item["score_range"],
            )
        )

    lines.extend(["", "## 每轮结果", ""])
    for round_results in rounds:
        round_index = round_results[0]["round"] if round_results else 0
        lines.extend([f"### 第 {round_index} 轮", ""])
        for item in round_results:
            lines.append(f"- {item['name']}：能力摘要 {item['overall_score']}")
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
