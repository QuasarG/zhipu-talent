"""探查 AMiner MCP 服务：列工具 + 试调 person_search。

一次性脚本，确认 MCP 连接与工具能力，不进正式代码。
"""
import asyncio
import os
import sys

from dotenv import load_dotenv
from mcp import ClientSession
from mcp.client.sse import sse_client

load_dotenv()

MCP_URL = os.getenv("AMINER_MCP_URL", "https://mcp.aminer.cn/sse")
TOKEN = os.getenv("AMINER_AUTH_TOKEN", "")


async def main():
    if not TOKEN:
        print("缺少 AMINER_AUTH_TOKEN", file=sys.stderr)
        sys.exit(1)
    headers = {"Authorization": f"Bearer {TOKEN}"}
    print(f"连接 {MCP_URL} ...")
    try:
        async with sse_client(url=MCP_URL, headers=headers) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                print("\n=== 可用工具 ===")
                for t in tools.tools:
                    print(f"- {t.name}: {(t.description or '')[:80]}")
                    if t.inputSchema:
                        props = t.inputSchema.get("properties", {})
                        required = t.inputSchema.get("required", [])
                        for prop, spec in props.items():
                            mark = "*" if prop in required else " "
                            print(f"    {mark} {prop}: {spec.get('type', '?')} - {spec.get('description', '')[:50]}")
                # 试调 search_person -> get_person_detail
                print("\n=== 试调 search_person ===")
                try:
                    result = await session.call_tool("search_person", {"name": "唐杰", "org": "清华大学", "size": 3})
                    text = result.content[0].text if result.content and hasattr(result.content[0], "text") else str(result.content)
                    print(text[:2000])
                    # 拿第一个 person_id 试 get_person_detail
                    import json
                    data = json.loads(text)
                    person_id = ""
                    if isinstance(data, list) and data:
                        person_id = str(data[0].get("id") or data[0].get("person_id") or "")
                    elif isinstance(data, dict) and data.get("data"):
                        first = data["data"][0] if data["data"] else {}
                        person_id = str(first.get("id") or "")
                    if person_id:
                        print(f"\n=== get_person_detail(id={person_id}) ===")
                        detail = await session.call_tool("get_person_detail", {"id": person_id})
                        dt = detail.content[0].text if detail.content and hasattr(detail.content[0], "text") else str(detail.content)
                        print(dt[:3000])
                except Exception as exc:
                    print(f"调用失败: {type(exc).__name__}: {exc}")
    except Exception as exc:
        print(f"连接失败: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
