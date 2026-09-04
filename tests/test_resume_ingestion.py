from __future__ import annotations

import threading
import unittest

from agi_talent_radar.core.resume_ingestion import _ocr_state, take_last_ocr_sections


class OcrSectionIsolationTest(unittest.TestCase):
    def test_parallel_imports_keep_their_own_ocr_sections(self) -> None:
        barrier = threading.Barrier(2)
        results: dict[str, list[dict[str, str]] | None] = {}

        def consume(label: str) -> None:
            _ocr_state.sections = [{"name": "基本信息", "text": label}]
            barrier.wait()
            results[label] = take_last_ocr_sections()

        threads = [threading.Thread(target=consume, args=(label,)) for label in ("甲文件", "乙文件")]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(results["甲文件"], [{"name": "基本信息", "text": "甲文件"}])
        self.assertEqual(results["乙文件"], [{"name": "基本信息", "text": "乙文件"}])


if __name__ == "__main__":
    unittest.main()
