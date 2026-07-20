from __future__ import annotations

import base64
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agi_talent_radar.integrations.zai_vision import VisionPage, ZaiVisionClient


# 1x1 PNG，用于发起一次最小化的真实多模态请求。
CHECK_IMAGE = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def main() -> None:
    client = ZaiVisionClient(timeout_seconds=60)
    result = client.analyze_resume(
        [
            VisionPage(
                page_number=1,
                mime_type="image/png",
                data_base64=base64.b64encode(CHECK_IMAGE).decode("ascii"),
            )
        ],
        '返回 JSON 对象 {"ok": true}。',
    )
    if result.get("ok") is not True:
        raise RuntimeError(f"模型返回了非预期结果: {result}")
    print(f"智谱原生多模态模型联通成功: {client.model}")


if __name__ == "__main__":
    main()
