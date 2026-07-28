"""Settings Provider 测试。

覆盖（与决策记录 §2.7 对齐）：

1. 敏感 Key 返回脱敏状态（configured + masked），不返回原文。
2. 非敏感 Key 返回原值。
3. mask_key 保留首尾 2 字符。
4. 未配置的敏感 Key 返回 configured=False。
5. refresh 原子刷新。
"""
from __future__ import annotations

import unittest

from agi_talent_radar.core.settings import (
    SENSITIVE_KEYS,
    Settings,
    SettingsProvider,
    mask_key,
)


class TestMaskKey(unittest.TestCase):
    def test_long_key_masks_middle(self) -> None:
        masked = mask_key("sk-abcdef123456")
        self.assertTrue(masked.startswith("sk"))
        self.assertTrue(masked.endswith("56"))
        self.assertIn("*", masked)
        self.assertNotIn("abcdef", masked)

    def test_short_key_full_mask(self) -> None:
        self.assertEqual(mask_key("abc"), "***")
        self.assertEqual(mask_key(""), "")


class TestSettingsPublicDict(unittest.TestCase):
    def test_sensitive_keys_are_masked(self) -> None:
        settings = Settings(values={
            "DEEPSEEK_API_KEY": "sk-very-secret-key-123456",
            "OPENAI_MODEL": "deepseek-v4-flash",
        })
        public = settings.to_public_dict()
        # 敏感字段
        deepseek = public["DEEPSEEK_API_KEY"]
        self.assertTrue(deepseek["configured"])
        self.assertIn("*", deepseek["masked"])
        self.assertNotIn("very-secret", deepseek["masked"])
        self.assertNotIn("very-secret", str(public))
        # 非敏感字段返回原值
        self.assertEqual(public["OPENAI_MODEL"], "deepseek-v4-flash")

    def test_unconfigured_sensitive_key(self) -> None:
        settings = Settings(values={})
        public = settings.to_public_dict()
        for key in SENSITIVE_KEYS:
            self.assertIn(key, public)
            self.assertFalse(public[key]["configured"])
            self.assertEqual(public[key]["masked"], "")


class TestSettingsProvider(unittest.TestCase):
    def test_load_from_env_extracts_relevant_keys(self) -> None:
        provider = SettingsProvider()
        provider.load_from_env({
            "DEEPSEEK_API_KEY": "sk-test",
            "OPENAI_MODEL": "deepseek-v4-flash",
            "UNRELATED_VAR": "ignore-me",
        })
        snap = provider.snapshot()
        self.assertEqual(snap.get("DEEPSEEK_API_KEY"), "sk-test")
        self.assertEqual(snap.get("OPENAI_MODEL"), "deepseek-v4-flash")
        self.assertNotIn("UNRELATED_VAR", snap.values)

    def test_refresh_replaces_snapshot(self) -> None:
        provider = SettingsProvider()
        provider.load_from_env({"DEEPSEEK_API_KEY": "sk-old"})
        provider.refresh({"DEEPSEEK_API_KEY": "sk-new"})
        self.assertEqual(provider.snapshot().get("DEEPSEEK_API_KEY"), "sk-new")

    def test_snapshot_is_independent_copy(self) -> None:
        provider = SettingsProvider()
        provider.load_from_env({"OPENAI_MODEL": "v1"})
        snap = provider.snapshot()
        snap.values["OPENAI_MODEL"] = "tampered"
        # 原 provider 不受影响
        self.assertEqual(provider.snapshot().get("OPENAI_MODEL"), "v1")

    def test_is_configured(self) -> None:
        settings = Settings(values={"DEEPSEEK_API_KEY": "sk-x", "Z_AI_API_KEY": ""})
        self.assertTrue(settings.is_configured("DEEPSEEK_API_KEY"))
        self.assertFalse(settings.is_configured("Z_AI_API_KEY"))
        self.assertFalse(settings.is_configured("NONEXISTENT"))


if __name__ == "__main__":
    unittest.main()