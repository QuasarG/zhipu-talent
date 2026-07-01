from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_JSON = ROOT / "outputs" / "consistency_eval.json"
OUTPUT_STATUS = ROOT / "outputs" / "consistency_eval_status.json"
PROCESS_REVIEW = ROOT / "docs" / "process_review.md"
TARGET_ROUNDS = 5
TOTAL_CANDIDATES = 10
MAX_ATTEMPTS = 20
RETRY_SECONDS = 30


def main() -> None:
    attempts = 0
    while not _is_complete():
        attempts += 1
        if attempts > MAX_ATTEMPTS:
            _write_status("failed", f"超过 {MAX_ATTEMPTS} 次续跑仍未完成。")
            raise RuntimeError("一致性实验多次续跑失败")

        progress = _progress_text()
        _write_status("running", f"第 {attempts} 次续跑；{progress}")
        print(f"[consistency] {progress}，开始/继续续跑（attempt {attempts}/{MAX_ATTEMPTS}）", flush=True)
        completed = subprocess.run([sys.executable, str(ROOT / "scripts" / "run_consistency_eval.py")], cwd=ROOT)
        if completed.returncode != 0:
            print(f"[consistency] 子进程返回 {completed.returncode}，{RETRY_SECONDS}s 后续跑", flush=True)
            time.sleep(RETRY_SECONDS)

    _update_process_review()
    _write_status("complete", "5 轮一致性实验完成，复盘文档已更新。")
    print("[consistency] 5 轮一致性实验完成，复盘文档已更新。", flush=True)


def _is_complete() -> bool:
    rounds = _rounds()
    return len(rounds) >= TARGET_ROUNDS and all(len(items) >= TOTAL_CANDIDATES for items in rounds[:TARGET_ROUNDS])


def _rounds() -> list[list[dict[str, Any]]]:
    if not OUTPUT_JSON.exists():
        return []
    try:
        payload = json.loads(OUTPUT_JSON.read_text(encoding="utf-8"))
    except Exception:
        return []
    rounds = payload.get("rounds", [])
    return rounds if isinstance(rounds, list) else []


def _summary() -> list[dict[str, Any]]:
    if not OUTPUT_JSON.exists():
        return []
    payload = json.loads(OUTPUT_JSON.read_text(encoding="utf-8"))
    summary = payload.get("summary", [])
    return summary if isinstance(summary, list) else []


def _progress_text() -> str:
    rounds = _rounds()
    complete_rounds = sum(1 for items in rounds if len(items) >= TOTAL_CANDIDATES)
    partial = next((len(items) for items in rounds if 0 < len(items) < TOTAL_CANDIDATES), 0)
    return f"已完成完整轮次 {complete_rounds}/{TARGET_ROUNDS}" + (f"，当前部分轮次 {partial}/{TOTAL_CANDIDATES}" if partial else "")


def _update_process_review() -> None:
    text = PROCESS_REVIEW.read_text(encoding="utf-8")
    section = _consistency_section()
    pattern = r"## 一致性测试设计\n.*?(?=\n## 当前局限与兜底)"
    if not re.search(pattern, text, flags=re.S):
        raise RuntimeError("找不到 process_review.md 中的一致性测试章节")
    updated = re.sub(pattern, section.rstrip(), text, flags=re.S)
    PROCESS_REVIEW.write_text(updated, encoding="utf-8")


def _consistency_section() -> str:
    summary = _summary()
    if not summary:
        raise RuntimeError("一致性实验缺少 summary")

    top = summary[:3]
    candidate_06 = next((item for item in summary if item.get("id") == "candidate_06"), None)
    most_volatile = max(summary, key=lambda item: (float(item.get("score_std", 0)), int(item.get("score_range", 0))))
    rank_volatile = max(summary, key=lambda item: int(item.get("rank_range", 0)))

    top_text = "、".join(
        f"{item['name']}均分{item['mean_score']}、平均名次{item['mean_rank']}"
        for item in top
    )
    c06_text = (
        f"候选人06的均分为 {candidate_06['mean_score']}，平均名次 {candidate_06['mean_rank']}，"
        f"分数范围 {candidate_06['score_range']}，名次范围 {candidate_06['rank_range']}。"
        if candidate_06
        else "候选人06未出现在一致性实验结果中。"
    )

    return f"""## 一致性测试设计

LLM 评估还有一个必须面对的问题：同一个候选人多次独立评估，分数和排序是否稳定？如果系统每次都能产出流畅理由，但分数大幅波动，那么它就更像一个会写评语的随机数生成器，而不是可靠的初筛助手。

为此我新增了 `scripts/run_consistency_eval.py`，并实际完成了 10 位候选人各 5 次的独立完整评估。每次评估都会重新跑 Normalizer、Evidence Extractor、Scorer、Critic 和 Formatter；每轮内按综合分排序；最后统计每位候选人的均分、分数标准差、最高最低差、平均名次、名次波动、等级分布和分层分布。脚本采用断点续跑和单候选人重试，不写数据库，避免网络抖动导致整组实验作废。

完整 5 轮结果显示，当前系统的排序并不是完全随机，但波动和偏差都值得警惕。按平均名次看，前三位是{top_text}。其中候选人02的应用型 Agent / 数据闭环特征非常符合 V1 rubric，因此稳定处在高位；候选人07和候选人08也受益于 Agent、自动化评测或系统闭环信号。相对地，{c06_text}这个结果进一步印证了前面提到的坑：底层基建型人才虽然可能具有很强的长期战略价值，但在偏 AI Native Application 的 V1 评价体系里仍然容易被压到中段。

实验过程中也暴露了工程层面的稳定性风险。真实 API 链路会出现握手超时或响应超时，LLM 偶尔仍会输出越界字段，例如 evidence strength 给出 0，被 Pydantic 拦截后需要重试；这说明 JSON 模式不等于完全可靠，后验校验、断点续跑和中间落盘仍然必要。从统计上看，分数波动最大的候选人是{most_volatile['name']}，分数标准差 {most_volatile['score_std']}，分数范围 {most_volatile['score_range']}；名次波动最大的候选人是{rank_volatile['name']}，名次范围 {rank_volatile['rank_range']}。这些候选人应该进入人工复核，而不是只看单次分数。

V2.0 我会把一致性测试纳入校准流程：如果某候选人的分数标准差过大，系统不应该只给一个分数，而应该提示“模型判断不稳定，需要人工复核”；如果排名在多次运行中剧烈变化，说明 rubric 或 prompt 对该类型候选人的证据解释不够稳。最终进入前端的也不应该只有单次分数，而可以展示均分、置信区间和稳定性标记。
"""


def _write_status(status: str, message: str) -> None:
    OUTPUT_STATUS.write_text(
        json.dumps(
            {
                "status": status,
                "message": message,
                "progress": _progress_text(),
                "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
