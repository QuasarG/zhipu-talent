"""人工别名表的保守合并边界。"""

import unittest

from agi_talent_radar.scholarship.graph_identity import (
    ADVISOR_ALIASES,
    SCHOOL_ALIASES,
    canonical_advisor,
    canonical_school,
    guess_school_from_title,
)


class TestGraphIdentity(unittest.TestCase):
    def test_confirmed_school_aliases_share_one_identity(self):
        self.assertEqual(canonical_school("The University of Hong Kong"), "香港大学")
        self.assertEqual(canonical_school("香港大学（The University of Hong Kong）"), "香港大学")

    def test_campuses_and_joint_programs_remain_distinct(self):
        self.assertNotEqual(canonical_school("香港科技大学"), canonical_school("香港科技大学（广州）"))
        self.assertNotEqual(canonical_school("浙江大学"), canonical_school("浙江大学-西湖大学联合培养"))

    def test_cas_institutes_unify_under_one_node(self):
        # 中科院各研究所不是独立大学，统一归并到「中国科学院」
        for name in ("中国科学院计算技术研究所", "中国科学院自动化研究所",
                     "中国科学院软件研究所", "中国科学院数学与系统科学研究院",
                     "中国科学院杭州医学研究所"):
            self.assertEqual(canonical_school(name), "中国科学院")
        self.assertEqual(canonical_school("中国科学院计算技术研究所 中国科学院大学"), "中国科学院")
        # 国科大是独立高校，保持独立
        self.assertNotEqual(canonical_school("中国科学院大学"), "中国科学院")

    def test_confirmed_advisor_aliases_share_one_identity(self):
        self.assertEqual(canonical_advisor("LI Qing"), "李青")
        self.assertEqual(canonical_advisor("李青（Qing Li，香港理工大学）"), "李青")

    def test_unverified_same_name_affiliations_remain_distinct(self):
        self.assertNotEqual(canonical_advisor("聂礼强"), canonical_advisor("聂礼强（哈工大深圳，nieliqiang@gmail.com）"))

    def test_confirmed_email_and_career_aliases_share_identity(self):
        self.assertEqual(canonical_advisor("罗平（西湖大学，pluo.lhi@gmail.com）"), "罗平")
        self.assertEqual(canonical_advisor("乔宇（中科院深圳理工/SIAT）"), "乔宇")

    def test_alias_targets_are_final_labels(self):
        self.assertFalse(set(SCHOOL_ALIASES.values()) & set(SCHOOL_ALIASES))
        self.assertFalse(set(ADVISOR_ALIASES.values()) & set(ADVISOR_ALIASES))

    def test_guess_school_picks_own_segment_in_multi_advisor_title(self):
        # 多导师拼接：只取本导师分段的学校，不得张冠李戴
        title = "聂礼强，哈尔滨工业大学（深圳）教授、信息学部主任；尉寅玮，山东大学软件学院教授、副院长"
        self.assertEqual(guess_school_from_title(title, "尉寅玮"), "山东大学")
        self.assertEqual(guess_school_from_title(title, "聂礼强"), "哈尔滨工业大学（深圳）")

    def test_guess_school_cas_institute_and_fallbacks(self):
        self.assertEqual(
            guess_school_from_title("许倩倩，中国科学院计算技术研究所研究员", "许倩倩"),
            "中国科学院")
        self.assertEqual(guess_school_from_title("张小平，清华大学信息化工作办公室主任", "张小平"), "清华大学")
        # 快照里没有学校信息 → 空串（交由人工核验/推荐信补录）
        self.assertEqual(guess_school_from_title("朱靖波，教授", "朱靖波"), "")
        self.assertEqual(guess_school_from_title("", "张三"), "")
