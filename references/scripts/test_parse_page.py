#!/usr/bin/env python3
"""parse_page.py 的单测：v4.2 取数加速层分级（_is_filtered / _ds_usage）+ 结构指纹稳定性"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import parse_page as pp


class TestIsFiltered(unittest.TestCase):
    def test_filter_with_value_is_card_level(self):
        fd = [{"field": "区域", "filterType": "EQUAL", "filterValue": ["华东"], "level": ""}]
        self.assertTrue(pp._is_filtered(fd, ["区域"]))

    def test_empty_filter_value_is_dataset_level(self):
        fd = [{"field": "区域", "filterType": "EQUAL", "filterValue": [], "level": ""},
              {"field": "月份", "filterType": "EQUAL", "filterValue": None, "level": ""}]
        self.assertFalse(pp._is_filtered(fd, ["区域", "月份"]))

    def test_no_filters_is_dataset_level(self):
        self.assertFalse(pp._is_filtered([], []))

    def test_text_fallback_uses_filters_list(self):
        # 文本回退路径 filterDetails 为空：filters 非空兜底判卡片级
        self.assertTrue(pp._is_filtered([], ["区域"]))
        self.assertFalse(pp._is_filtered([], []))


class TestDsUsage(unittest.TestCase):
    def test_usage_counts(self):
        cards = [
            {"type": "BASIC_BAR", "dsId": "ds1", "filtered": False},
            {"type": "PIE", "dsId": "ds1", "filtered": True},
            {"type": "PIVOT_TABLE", "dsId": "ds2", "filtered": False},
            {"type": "SELECTOR", "dsId": "ds3"},          # 筛选器不计
            {"type": "TEXT"},                              # 文本卡不计
            {"type": "BASIC_BAR", "dsId": "", "filtered": False},  # 无 dsId 不计
        ]
        u = pp._ds_usage(cards)
        self.assertEqual(u, {"ds1": {"cards": 2, "filteredCards": 1},
                             "ds2": {"cards": 1, "filteredCards": 0}})

    def test_empty(self):
        self.assertEqual(pp._ds_usage([]), {})


class TestStructureHash(unittest.TestCase):
    def test_stable_and_order_insensitive(self):
        a = [{"cdId": "c1", "name": "甲"}, {"cdId": "c2", "name": "乙"}]
        b = [{"cdId": "c2", "name": "乙"}, {"cdId": "c1", "name": "甲"}]
        self.assertEqual(pp._structure_hash(a), pp._structure_hash(b))
        c = [{"cdId": "c1", "name": "甲"}]
        self.assertNotEqual(pp._structure_hash(a), pp._structure_hash(c))


if __name__ == "__main__":
    unittest.main()
