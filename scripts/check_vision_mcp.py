from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agi_talent_radar.integrations.vision_mcp import ZaiVisionMCPClient


def main() -> None:
    client = ZaiVisionMCPClient(timeout_seconds=20)
    tools = client.list_tools()
    if "analyze_image" not in tools:
        raise RuntimeError(f"视觉 MCP 未注册 analyze_image，当前工具: {tools}")

    print("智谱视觉 MCP 联通成功。")
    print("已注册工具:", ", ".join(tools))


if __name__ == "__main__":
    main()
