from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from agi_talent_radar.integrations.vision_mcp import (
    MCPProtocolError,
    ZaiVisionMCPClient,
    _extract_tool_text,
    _resolve_server_command,
    get_vision_mcp_client,
)


class VisionMCPTest(unittest.TestCase):
    def test_default_client_uses_zai_configuration(self) -> None:
        with patch.dict(os.environ, {"Z_AI_API_KEY": "secret-value", "VISION_MCP_ADAPTER": ""}):
            self.assertIsInstance(get_vision_mcp_client(), ZaiVisionMCPClient)

    def test_local_server_command_uses_installed_entrypoint(self) -> None:
        command = _resolve_server_command()
        self.assertTrue(command[0])
        self.assertTrue(
            command[1].endswith("node_modules\\@z_ai\\mcp-server\\build\\index.js")
            or command[1].endswith("node_modules/@z_ai/mcp-server/build/index.js")
        )

    def test_extract_tool_text_rejects_mcp_tool_error(self) -> None:
        with self.assertRaises(MCPProtocolError):
            _extract_tool_text({"isError": True, "content": [{"type": "text", "text": "Error: denied"}]})

    def test_extract_tool_text_combines_text_blocks(self) -> None:
        result = _extract_tool_text(
            {"content": [{"type": "text", "text": "first"}, {"type": "text", "text": "second"}]}
        )
        self.assertEqual(result, "first\nsecond")


if __name__ == "__main__":
    unittest.main()
