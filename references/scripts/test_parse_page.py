#!/usr/bin/env python3
"""parse_page.py 的单测：v4.2 取数加速层分级（_is_filtered / _ds_usage）+ 结构指纹稳定性
+ v4.4 实机踩坑回归（SELECTOR 卡片 defaultValue 为字符串）"""
import json
import os
import sys
import unittest
from unittest import mock

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


class TestSelectorDefaultValue(unittest.TestCase):
    """v4.4 merge_cards 实机首跑踩坑：部分看板 SELECTOR 卡片的 content.defaultValue
    是字符串而非 dict，`.get("valueType")` 直接崩溃——isinstance 防护的回归"""
    def _parse(self, default_value):
        raw = {"data": {"name": "页", "utime": "", "dsInfos": [],
                        "meta": {"backlogLayout": [], "filterLayout": []},
                        "cards": [{"cdId": "s1", "cdType": "SELECTOR", "name": "月份",
                                   "content": {"chartType": "SELECTOR",
                                               "source": {"field": {"name": "月份"}},
                                               "defaultValue": default_value}}]}}
        with mock.patch.object(pp, "run_guancli", return_value=(0, json.dumps(raw), "")):
            return pp.parse_page_raw("pg1")

    def test_string_default_value_no_crash(self):
        info = self._parse("上月")
        self.assertNotIn("error", info)
        self.assertEqual(info["cards"][0]["defaultValueType"], "")

    def test_dict_default_value_reads_value_type(self):
        info = self._parse({"valueType": "DYNAMIC", "value": "本月"})
        self.assertEqual(info["cards"][0]["defaultValueType"], "DYNAMIC")


if __name__ == "__main__":
    unittest.main()
