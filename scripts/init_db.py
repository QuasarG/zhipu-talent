import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agi_talent_radar.core.database import init_db


def main() -> None:
    init_db()
    print("数据库表已初始化")


if __name__ == "__main__":
    main()
