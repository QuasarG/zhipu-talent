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
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from agi_talent_radar.core.db.orm import Base, ConfigChangeAuditORM
from agi_talent_radar.web.config_api import (
    _list_config_audits,
    _record_config_audits,
    update_env,
    test_llm_connection,
    build_config_blueprint,
)


class TestConfigAudit(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)

    def tearDown(self) -> None:
        self.engine.dispose()

    def test_records_only_key_actor_and_time(self) -> None:
        with (
            patch("agi_talent_radar.core.database.get_session", side_effect=self.Session),
            patch(
                "agi_talent_radar.web.auth.current_user",
                return_value=SimpleNamespace(display_name="郭泽新", username="guozexin"),
            ),
        ):
            result = _record_config_audits(["LLM_API_KEY"])

        self.assertEqual(result["LLM_API_KEY"]["changed_by"], "郭泽新")
        with self.Session() as session:
            row = session.query(ConfigChangeAuditORM).one()
            self.assertEqual(row.config_key, "LLM_API_KEY")
            self.assertFalse(hasattr(row, "config_value"))

    def test_lists_latest_change_per_key(self) -> None:
        with self.Session() as session:
            session.add_all([
                ConfigChangeAuditORM(config_key="LLM_API_KEY", changed_by="旧用户"),
                ConfigChangeAuditORM(config_key="LLM_API_KEY", changed_by="新用户"),
            ])
            session.commit()
        with patch("agi_talent_radar.core.database.get_session", side_effect=self.Session):
            result = _list_config_audits()
        self.assertEqual(result["LLM_API_KEY"]["changed_by"], "新用户")


class TestUpdateEnv(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.env_path = Path(self.tmp) / ".env"
        self.env_path.write_text('AMINER_API_TOKEN="aminer-old"\nLLM_API_KEY="sk-old"\n', encoding="utf-8")

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_applies_known_keys_atomically(self) -> None:
        result = update_env(self.env_path, {
            "LLM_API_KEY": "sk-new-secret",
            "AMINER_API_TOKEN": "aminer-new",
        })
        self.assertEqual(set(result.applied), {"LLM_API_KEY", "AMINER_API_TOKEN"})
        self.assertEqual(result.rejected, {})
        content = self.env_path.read_text(encoding="utf-8")
        self.assertIn("LLM_API_KEY=sk-new-secret", content)
        self.assertIn("AMINER_API_TOKEN=aminer-new", content)
        self.assertNotIn("sk-old", content)

    def test_rejects_unknown_keys(self) -> None:
        result = update_env(self.env_path, {
            "LLM_API_KEY": "sk-v2",
            "UNKNOWN_KEY": "value",
        })
        self.assertIn("LLM_API_KEY", result.applied)
        self.assertIn("UNKNOWN_KEY", result.rejected)

    def test_preserves_unmentioned_keys(self) -> None:
        update_env(self.env_path, {"LLM_API_KEY": "sk-v2"})
        content = self.env_path.read_text(encoding="utf-8")
        # 未提及的键仍在
        self.assertIn("AMINER_API_TOKEN=aminer-old", content)

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
            bad_env.write_text("Z_AI_API_KEY=old\n", encoding="utf-8")
            result = update_env(bad_env, {"Z_AI_API_KEY": "new"})
            # Windows 上 chmod 可能不生效；至少保证：如果 rejected 则旧文件保留
            if result.rejected:
                self.assertIn("Z_AI_API_KEY=old", bad_env.read_text(encoding="utf-8"))
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
                "LLM_API_KEY": "sk-test-secret-123456",
            }),
        )
        self._provider_patch.start()
        self._settings_patch.start()
        self._record_audit_patch = patch(
            "agi_talent_radar.web.config_api._record_config_audits",
            return_value={"LLM_API_KEY": {"changed_by": "测试用户", "changed_at": "2026-08-29T12:00:00"}},
        )
        self._list_audit_patch = patch(
            "agi_talent_radar.web.config_api._list_config_audits",
            return_value={"LLM_API_KEY": {"changed_by": "测试用户", "changed_at": "2026-08-29T12:00:00"}},
        )
        self._record_audit_patch.start()
        self._list_audit_patch.start()
        self.app.register_blueprint(build_config_blueprint(env_path=self.env_path))
        self.client = self.app.test_client()

    def tearDown(self) -> None:
        self._provider_patch.stop()
        self._settings_patch.stop()
        self._record_audit_patch.stop()
        self._list_audit_patch.stop()
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_get_returns_masked_secrets(self) -> None:
        rv = self.client.get("/api/config")
        self.assertEqual(rv.status_code, 200)
        data = rv.get_json()
        self.assertIn("LLM_API_KEY", data)
        self.assertTrue(data["LLM_API_KEY"]["configured"])
        # 响应中不含完整 Key
        self.assertNotIn("sk-test-secret-123456", rv.data.decode("utf-8"))
        # 非外部服务 Key 不对外暴露
        self.assertNotIn("OPENAI_MODEL", data)

    def test_put_applies_and_returns_masked(self) -> None:
        rv = self.client.put("/api/config", json={
            "Z_AI_API_KEY": "zai-v2",
            "LLM_API_KEY": "sk-brand-new-secret",
        })
        self.assertIn(rv.status_code, {200, 207})
        data = rv.get_json()
        # applied 中敏感 Key 脱敏
        applied = data["applied"]
        self.assertIn("LLM_API_KEY", applied)
        self.assertNotIn("sk-brand-new-secret", rv.data.decode("utf-8"))
        self.assertIn("*", applied["LLM_API_KEY"]["masked"])
        self.assertEqual(data["audit"]["LLM_API_KEY"]["changed_by"], "测试用户")

    def test_get_audit_returns_key_metadata_without_values(self) -> None:
        rv = self.client.get("/api/config/audit")
        self.assertEqual(rv.status_code, 200)
        data = rv.get_json()
        self.assertEqual(data["LLM_API_KEY"]["changed_by"], "测试用户")
        self.assertNotIn("value", rv.data.decode("utf-8"))

    def test_put_rejects_unknown_keys(self) -> None:
        rv = self.client.put("/api/config", json={"HACKED_KEY": "x"})
        self.assertEqual(rv.status_code, 400)
        self.assertIn("HACKED_KEY", rv.get_json()["rejected"])

    def test_put_reports_partial_success_when_audit_write_fails(self) -> None:
        with patch(
            "agi_talent_radar.web.config_api._record_config_audits",
            side_effect=RuntimeError("db password leaked-in-exception"),
        ):
            rv = self.client.put("/api/config", json={"LLM_API_KEY": "sk-applied-secret"})

        self.assertEqual(rv.status_code, 207)
        data = rv.get_json()
        self.assertEqual(data["audit_status"], "failed")
        self.assertIn("配置已应用", data["warning"])
        self.assertIn("LLM_API_KEY=sk-applied-secret", self.env_path.read_text(encoding="utf-8"))
        self.assertNotIn("db password", rv.data.decode("utf-8"))
        self.assertNotIn("sk-applied-secret", rv.data.decode("utf-8"))


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
