"""用真实报名简历做筛选校准：遍历标签文件夹的 PDF，评估并按标签统计均分。"""
from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agi_talent_radar.core.resume_ingestion import load_pdf_resume
from agi_talent_radar.core.runner import run_candidate

RESUME_ROOT = Path("/mnt/c/Users/zexin/Documents/项目/智谱/简历材料/中关村智谱联合实验室-网安模型项目报名简历")
LABEL_DIRS = {"通过筛选": "passed", "未通过筛选": "failed"}
OUTPUT_DIR = ROOT / "outputs_real"
WORKERS = 4


def _evaluate(pdf: Path, label: str) -> dict:
    resume = load_pdf_resume(pdf.read_bytes(), pdf.name)
    evaluation = run_candidate(resume)
    return {
        "file": pdf.name,
        "label": label,
        "id": evaluation.id,
        "name": evaluation.name,
        "overall_score": evaluation.overall_score,
        "level": evaluation.level,
        "tier": evaluation.tier,
        "common_score": evaluation.common_score,
        "tracks": [
            {"track": t.track, "weight": t.weight, "calibrated_score": t.calibrated_score}
            for t in evaluation.track_evaluations
        ],
        "evaluation": evaluation.model_dump(exclude={"evidence"}),
    }


def main() -> None:
    jobs = [
        (pdf, label)
        for dirname, label in LABEL_DIRS.items()
        for pdf in sorted((RESUME_ROOT / dirname).glob("*.pdf"))
    ]
    print(f"共 {len(jobs)} 份简历，并发 {WORKERS}")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    results = []
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(_evaluate, pdf, label): (pdf, label) for pdf, label in jobs}
        for future in as_completed(futures):
            pdf, label = futures[future]
            try:
                record = future.result()
            except Exception as exc:
                record = {"file": pdf.name, "label": label, "error": f"{type(exc).__name__}: {exc}"}
            results.append(record)
            print(f"[{len(results)}/{len(jobs)}] {label} {pdf.stem} -> {record.get('overall_score', 'ERR')}", flush=True)

    (OUTPUT_DIR / "real_evaluations.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    for label in LABEL_DIRS.values():
        scores = [r["overall_score"] for r in results if r["label"] == label and "overall_score" in r]
        if scores:
            print(f"{label}: n={len(scores)} mean={sum(scores) / len(scores):.1f} min={min(scores)} max={max(scores)}")
    errors = [r for r in results if "error" in r]
    if errors:
        print(f"失败 {len(errors)} 份: {[r['file'] for r in errors]}")


if __name__ == "__main__":
    main()
