"""人工别名表的保守合并边界。"""

import unittest

from agi_talent_radar.scholarship.graph_identity import (
    ADVISOR_ALIASES,
    SCHOOL_ALIASES,
    canonical_advisor,
    canonical_school,
)


class TestGraphIdentity(unittest.TestCase):
    def test_confirmed_school_aliases_share_one_identity(self):
        self.assertEqual(canonical_school("The University of Hong Kong"), "香港大学")
        self.assertEqual(canonical_school("香港大学（The University of Hong Kong）"), "香港大学")

    def test_campuses_and_joint_programs_remain_distinct(self):
        self.assertNotEqual(canonical_school("香港科技大学"), canonical_school("香港科技大学（广州）"))
        self.assertNotEqual(canonical_school("浙江大学"), canonical_school("浙江大学-西湖大学联合培养"))

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
