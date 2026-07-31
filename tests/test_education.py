from __future__ import annotations

import unittest

from agi_talent_radar.core.education import highest_school, parse_education_entries

ZX_EDUCATION = [
    "博士联培：中关村学院人工智能算法安全性研究与应用项目组 2024.09 至今",
    "博士：南开大学计算机与网络空间安全学院硕博连读 2022.09 至今",
    "本科：北京交通大学计算机与信息技术学院信息安全专业 2018.09 - 2022.06",
]


class EducationParseTest(unittest.TestCase):
    def test_extracts_school_degree_level_and_start(self) -> None:
        entries = parse_education_entries(ZX_EDUCATION)
        self.assertEqual([e.school for e in entries], ["中关村学院", "南开大学", "北京交通大学"])
        self.assertEqual([e.level for e in entries], [3, 3, 1])
        self.assertTrue(entries[0].is_joint)
        self.assertEqual(entries[1].start, "202209")

    def test_highest_prefers_degree_granting_over_joint(self) -> None:
        entries = parse_education_entries(ZX_EDUCATION)
        # 两个博士层级并列时，联培不作学位授予校 → 南开大学
        self.assertEqual(highest_school(entries), "南开大学")

    def test_highest_picks_latest_within_same_level(self) -> None:
        entries = parse_education_entries([
            "博士：清华大学 2018.09 - 2023.06",
            "博士：北京大学 2023.09 至今",
        ])
        self.assertEqual(highest_school(entries), "北京大学")

    def test_doctor_beats_bachelor(self) -> None:
        entries = parse_education_entries([
            "本科：清华大学 2014.09 - 2018.06",
            "硕士：浙江大学 2018.09 - 2021.06",
        ])
        self.assertEqual(highest_school(entries), "浙江大学")

    def test_dict_items_and_noise(self) -> None:
        entries = parse_education_entries([
            {"school": "复旦大学计算机学院", "degree": "博士", "period": "2020.09 至今"},
            "GPA 3.7/4.0",
            "",
        ])
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].school, "复旦大学")
        self.assertEqual(entries[0].level, 3)

    def test_empty_input(self) -> None:
        self.assertEqual(parse_education_entries([]), [])
        self.assertEqual(highest_school([]), "")
    def test_top_school_names_includes_joint_at_same_level(self) -> None:
        from agi_talent_radar.core.education import top_school_names

        schools = [
            {"school": "中关村学院", "degree": "博士", "period": "2024.09 至今"},
            {"school": "南开大学", "degree": "博士", "period": "2022.09 至今"},
            {"school": "北京交通大学", "degree": "本科", "period": "2018.09 - 2022.06"},
        ]
        # 最高层级（博士）有两所，联培也算，全部绑定
        self.assertEqual(top_school_names(schools), ["中关村学院", "南开大学"])
        self.assertEqual(top_school_names([schools[2]]), ["北京交通大学"])
        self.assertEqual(top_school_names([]), [])


if __name__ == "__main__":
    unittest.main()
