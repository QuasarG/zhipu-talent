from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agi_talent_radar.core.runner import run_batch_from_file


INPUT_PATH = Path("10_ai_phd_resumes.jsonl")
OUTPUT_DIR = Path("outputs")


def main() -> None:
    input_path = Path(sys.argv[1]) if len(sys.argv) > 1 else INPUT_PATH
    output_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else OUTPUT_DIR
    result = run_batch_from_file(input_path, output_dir)
    print(f"已评估 {len(result.evaluations)} 位候选人")
    for index, item in enumerate(result.evaluations, start=1):
        print(f"{index}. {item.name} {item.overall_score} {item.level} {item.tier}")


if __name__ == "__main__":
    main()
