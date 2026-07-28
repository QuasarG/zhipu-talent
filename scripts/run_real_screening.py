"""用真实报名简历做能力评分审计：遍历标签文件夹的 PDF 并输出标签对照。

输出：
- 每组历史标签的 mean/min/max，仅供人工复盘
- 分数与历史筛选结果不一致的案例，提示核查方向匹配、名额或人工原因
- 当前 scoring_version（标注用哪套参数跑的）

禁止将 passed/failed 标签用作评分权重或封顶规则的调参目标。
"""
from __future__ import annotations

import json
import statistics
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agi_talent_radar.core.resume_ingestion import load_pdf_resume
from agi_talent_radar.core.runner import run_candidate
from agi_talent_radar.core.scoring_version import current_scoring_version

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
        "common_score": evaluation.common_score,
        "tracks": [
            {"track": t.track, "weight": t.weight, "calibrated_score": t.calibrated_score}
            for t in evaluation.track_evaluations
        ],
        "evaluation": evaluation.model_dump(exclude={"evidence"}),
    }


def _stats(scores: list[int]) -> dict:
    if not scores:
        return {"n": 0}
    return {
        "n": len(scores),
        "mean": round(statistics.mean(scores), 1),
        "median": statistics.median(scores),
        "min": min(scores),
        "max": max(scores),
        "stdev": round(statistics.stdev(scores), 1) if len(scores) > 1 else 0.0,
    }


def _label_audit_report(results: list[dict]) -> dict:
    """历史筛选标签与能力评分的只读对照。"""
    passed = [r for r in results if r["label"] == "passed" and "overall_score" in r]
    failed = [r for r in results if r["label"] == "failed" and "overall_score" in r]
    passed_scores = [r["overall_score"] for r in passed]
    failed_scores = [r["overall_score"] for r in failed]
    p_stats = _stats(passed_scores)
    f_stats = _stats(failed_scores)
    failed_max = f_stats.get("max", 0)
    passed_min = p_stats.get("min", 100)
    passed_below_failed_max = [r for r in passed if r["overall_score"] < failed_max]
    failed_above_passed_min = [r for r in failed if r["overall_score"] > passed_min]

    return {
        "passed": p_stats,
        "failed": f_stats,
        "label_overlap": bool(passed_below_failed_max or failed_above_passed_min),
        "passed_below_failed_max": [{"name": r["name"], "score": r["overall_score"], "file": r["file"]} for r in sorted(passed_below_failed_max, key=lambda x: x["overall_score"])],
        "failed_above_passed_min": [{"name": r["name"], "score": r["overall_score"], "file": r["file"]} for r in sorted(failed_above_passed_min, key=lambda x: x["overall_score"], reverse=True)],
    }


def main() -> None:
    jobs = [
        (pdf, label)
        for dirname, label in LABEL_DIRS.items()
        for pdf in sorted((RESUME_ROOT / dirname).glob("*.pdf"))
    ]
    print(f"共 {len(jobs)} 份简历，并发 {WORKERS}")
    print(f"参数版本: {current_scoring_version()}")
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

    report = _label_audit_report(results)
    output = {
        "scoring_version": current_scoring_version(),
        "separation_report": report,
        "evaluations": results,
    }
    (OUTPUT_DIR / "real_evaluations.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 控制台摘要
    print(f"\n{'='*50}")
    print(f"参数版本: {report and current_scoring_version()}")
    p, f = report["passed"], report["failed"]
    print(f"通过组: n={p['n']} mean={p.get('mean','-')} min={p.get('min','-')} max={p.get('max','-')}")
    print(f"未通过: n={f['n']} mean={f.get('mean','-')} min={f.get('min','-')} max={f.get('max','-')}")
    print("历史标签仅用于审计，不用于评分参数调优。")
    print(f"标签与评分区间重叠: {'是' if report['label_overlap'] else '否'}")
    if report["passed_below_failed_max"]:
        print(f"通过标签但能力分低于未通过最高分({len(report['passed_below_failed_max'])}人):")
        for m in report["passed_below_failed_max"]:
            print(f"  {m['score']} {m['name']} ({m['file']})")
    if report["failed_above_passed_min"]:
        print(f"未通过标签但能力分高于通过最低分({len(report['failed_above_passed_min'])}人):")
        for m in report["failed_above_passed_min"]:
            print(f"  {m['score']} {m['name']} ({m['file']})")
    errors = [r for r in results if "error" in r]
    if errors:
        print(f"失败 {len(errors)} 份: {[r['file'] for r in errors]}")


if __name__ == "__main__":
    main()
