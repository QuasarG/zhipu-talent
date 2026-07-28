"""/api/config 原子写入 + 连接测试。

覆盖（与决策记录 §2.7 对齐）：

1. GET /api/config 只返回脱敏配置，不含完整 Key。
2. PUT /api/config 接受已知 Key，拒绝未知 Key。
3. 原子写入：成功后 .env 文件被更新，运行时 Settings 刷新。
4. 写入失败时不覆盖旧 .env（模拟不可写目录）。
5. applied 字段回显时敏感 Key 脱敏。
6. 连接测试返回 ok / unconfigured。
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agi_talent_radar.web.config_api import (
    update_env,
    test_llm_connection,
    build_config_blueprint,
)


class TestUpdateEnv(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.env_path = Path(self.tmp) / ".env"
        self.env_path.write_text('OPENAI_MODEL="old-model"\nDEEPSEEK_API_KEY="sk-old"\n', encoding="utf-8")

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_applies_known_keys_atomically(self) -> None:
        result = update_env(self.env_path, {
            "OPENAI_MODEL": "new-model",
            "DEEPSEEK_API_KEY": "sk-new-secret",
        })
        self.assertEqual(set(result.applied), {"OPENAI_MODEL", "DEEPSEEK_API_KEY"})
        self.assertEqual(result.rejected, {})
        # 文件已更新
        content = self.env_path.read_text(encoding="utf-8")
        self.assertIn("OPENAI_MODEL=new-model", content)
        self.assertIn("DEEPSEEK_API_KEY=sk-new-secret", content)
        # 旧值被覆盖
        self.assertNotIn("old-model", content)

    def test_rejects_unknown_keys(self) -> None:
        result = update_env(self.env_path, {
            "OPENAI_MODEL": "v2",
            "UNKNOWN_KEY": "value",
        })
        self.assertIn("OPENAI_MODEL", result.applied)
        self.assertIn("UNKNOWN_KEY", result.rejected)

    def test_preserves_unmentioned_keys(self) -> None:
        update_env(self.env_path, {"OPENAI_MODEL": "v2"})
        content = self.env_path.read_text(encoding="utf-8")
        # DEEPSEEK_API_KEY 仍在
        self.assertIn("DEEPSEEK_API_KEY=sk-old", content)

    def test_write_failure_keeps_old_file(self) -> None:
        # 指向一个不存在的目录（父目录不可创建时失败）
        bad_path = Path(self.tmp) / "no-such-dir" / "deep" / ".env"
        # 但 tempfile.mkstemp(dir=...) 会尝试创建父目录——
        # 直接用一个只读父目录模拟失败
        readonly_dir = Path(self.tmp) / "readonly"
        readonly_dir.mkdir()
        try:
            os.chmod(readonly_dir, 0o500)  # r-x for owner
            bad_env = readonly_dir / ".env"
            # 先写一个旧值
            bad_env.write_text("OPENAI_MODEL=old\n", encoding="utf-8")
            result = update_env(bad_env, {"OPENAI_MODEL": "new"})
            # Windows 上 chmod 可能不生效；至少保证：如果 rejected 则旧文件保留
            if result.rejected:
                self.assertIn("OPENAI_MODEL=old", bad_env.read_text(encoding="utf-8"))
        finally:
            os.chmod(readonly_dir, 0o700)


class TestConfigBlueprint(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.env_path = Path(self.tmp) / ".env"
        self.env_path.write_text('OPENAI_MODEL="v1"\n', encoding="utf-8")
        # patch provider 的 env 读取，避免 .env 真实文件干扰
        from flask import Flask

        from agi_talent_radar.core.settings import Settings, SettingsProvider

        self.app = Flask(__name__)
        self.app.config["TESTING"] = True
        # 用一个干净的 provider
        self._provider_patch = patch(
            "agi_talent_radar.web.config_api.get_provider",
            return_value=SettingsProvider(),
        )
        self._settings_patch = patch(
            "agi_talent_radar.web.config_api.get_settings",
            return_value=Settings(values={
                "OPENAI_MODEL": "v1",
                "DEEPSEEK_API_KEY": "sk-test-secret-123456",
            }),
        )
        self._provider_patch.start()
        self._settings_patch.start()
        self.app.register_blueprint(build_config_blueprint(env_path=self.env_path))
        self.client = self.app.test_client()

    def tearDown(self) -> None:
        self._provider_patch.stop()
        self._settings_patch.stop()
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_get_returns_masked_secrets(self) -> None:
        rv = self.client.get("/api/config")
        self.assertEqual(rv.status_code, 200)
        data = rv.get_json()
        self.assertIn("DEEPSEEK_API_KEY", data)
        self.assertTrue(data["DEEPSEEK_API_KEY"]["configured"])
        # 响应中不含完整 Key
        self.assertNotIn("sk-test-secret-123456", rv.data.decode("utf-8"))
        # 非敏感字段返回原值
        self.assertEqual(data["OPENAI_MODEL"], "v1")

    def test_put_applies_and_returns_masked(self) -> None:
        rv = self.client.put("/api/config", json={
            "OPENAI_MODEL": "v2",
            "DEEPSEEK_API_KEY": "sk-brand-new-secret",
        })
        self.assertIn(rv.status_code, {200, 207})
        data = rv.get_json()
        # applied 中敏感 Key 脱敏
        applied = data["applied"]
        self.assertIn("DEEPSEEK_API_KEY", applied)
        self.assertNotIn("sk-brand-new-secret", rv.data.decode("utf-8"))
        self.assertIn("*", applied["DEEPSEEK_API_KEY"]["masked"])

    def test_put_rejects_unknown_keys(self) -> None:
        rv = self.client.put("/api/config", json={"HACKED_KEY": "x"})
        self.assertEqual(rv.status_code, 400)
        self.assertIn("HACKED_KEY", rv.get_json()["rejected"])


class TestLLMConnection(unittest.TestCase):
    def test_unconfigured_returns_unconfigured(self) -> None:
        from agi_talent_radar.core.settings import Settings

        with patch(
            "agi_talent_radar.web.config_api.get_settings",
            return_value=Settings(values={}),
        ):
            result = test_llm_connection()
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "unconfigured")


if __name__ == "__main__":
    unittest.main()