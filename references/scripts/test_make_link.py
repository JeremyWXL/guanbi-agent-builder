#!/usr/bin/env python3
"""
make_link.py 最小单测：筛选器候选规则（只认筛选栏成员且有联动）、FIRST_PICK 告警、
load_pages 的 _meta 跳过与形态兼容、链接生成与错误路径。
运行: python3 -m unittest discover -s references/scripts -p 'test_*.py' -v
不触网：_meta.biBaseUrl 预置，避免 fallback 调 guancli；CLI 级用临时目录 + subprocess。
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import make_link

SCRIPT = os.path.abspath(make_link.__file__)


def run_cli(*args):
    return subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True)


def sel_card(name, cdid, field, **kw):
    c = {"name": name, "cdId": cdid, "type": "SELECTOR",
         "filters": [field] if field else []}
    c.update(kw)
    return c


class TestSelectorsOf(unittest.TestCase):
    def setUp(self):
        self.page = {"cards": [
            sel_card("月份筛选", "cd1", "月份", inFilterBar=True, linkedCardCount=3),
            sel_card("同名但不在栏", "cd2", "月份", inFilterBar=False, linkedCardCount=3),
            sel_card("无联动", "cd3", "渠道", inFilterBar=True, linkedCardCount=0),
            sel_card("旧版收割", "cd4", "大区"),  # 无 inFilterBar/linkedCardCount → 按可用处理
            sel_card("无cdId", "", "区域", inFilterBar=True, linkedCardCount=1),
            {"name": "数据卡", "cdId": "cd9"},  # 非筛选器，不收
        ]}

    def test_candidate_rules(self):
        sels = make_link.selectors_of(self.page)
        by_id = {s[1]: s for s in sels}
        self.assertNotIn("", by_id)                       # 无 cdId 被过滤
        self.assertEqual(len(sels), 4)                    # 数据卡不收
        self.assertTrue(by_id["cd1"][3])                  # 筛选栏成员且有联动 → 可用
        self.assertTrue(by_id["cd4"][3])                  # 旧版收割（字段缺失）→ 按可用
        self.assertFalse(by_id["cd2"][3])
        self.assertEqual(by_id["cd2"][4], "不在筛选栏")
        self.assertFalse(by_id["cd3"][3])
        self.assertIn("无联动", by_id["cd3"][4])

    def test_field_from_filter_details_fallback(self):
        page = {"cards": [{"name": "月份筛选", "cdId": "cd1", "cdType": "SELECTOR",
                           "filterDetails": [{"field": "月份"}]}]}
        sels = make_link.selectors_of(page)
        self.assertEqual(sels[0][2], "月份")


class TestFirstPickWarning(unittest.TestCase):
    def test_first_pick_in_bar_warns(self):
        page = {"cards": [sel_card("月份筛选", "cd1", "月份", inFilterBar=True,
                                   linkedCardCount=2, defaultValueType="FIRST_PICK")]}
        sels = make_link.selectors_of(page)
        warn = make_link.first_pick_warning(page, sels)
        self.assertIn("首选项", warn)

    def test_first_pick_outside_bar_still_warns(self):
        # 保守告警：FIRST_PICK 的首屏取数竞态取决于默认值解析是否卡住数据请求，
        # 与是否在筛选栏无必然关系；漏告警的代价是静默未筛选的链接（铁律禁止），
        # 误报 only 多一句"请实机确认"，因此栏外的 FIRST_PICK 同样告警
        page = {"cards": [
            sel_card("栏内筛选", "cd1", "月份", inFilterBar=True, linkedCardCount=2),
            sel_card("栏外首选", "cd2", "渠道", inFilterBar=False,
                     defaultValueType="FIRST_PICK")]}
        sels = make_link.selectors_of(page)
        self.assertIn("首选项", make_link.first_pick_warning(page, sels))

    def test_no_first_pick_no_warn(self):
        page = {"cards": [sel_card("月份筛选", "cd1", "月份", inFilterBar=True,
                                   linkedCardCount=2, defaultValueType="FIXED_VALUE")]}
        sels = make_link.selectors_of(page)
        self.assertEqual(make_link.first_pick_warning(page, sels), "")


class TestLoadPages(unittest.TestCase):
    def test_skips_meta_and_normalizes_dict_cards(self):
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "cards.json"), "w", encoding="utf-8") as f:
            json.dump({
                "_meta": {"biBaseUrl": "https://bi.example.com"},
                "看板A": {"pgId": "pg1", "cards": {"卡1": {"cdId": "c1"}}},
            }, f, ensure_ascii=False)
        pages, meta = make_link.load_pages(d)
        self.assertEqual(list(pages), ["看板A"])            # _meta 跳过
        self.assertEqual(pages["看板A"]["pgId"], "pg1")
        self.assertEqual(pages["看板A"]["cards"][0]["name"], "卡1")  # 字典形态 → 列表
        self.assertEqual(meta["biBaseUrl"], "https://bi.example.com")


class TestMainCLI(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        with open(os.path.join(self.dir, "cards.json"), "w", encoding="utf-8") as f:
            json.dump({
                "_meta": {"biBaseUrl": "https://bi.example.com"},
                "销售看板": {"pgId": "pg123", "cards": [
                    sel_card("月份筛选", "cd1", "月份", inFilterBar=True, linkedCardCount=2),
                    sel_card("栏外同名", "cd2", "月份", inFilterBar=False, linkedCardCount=2),
                    {"name": "总览卡", "cdId": "cd9"},
                ]},
            }, f, ensure_ascii=False)

    def test_link_single_value(self):
        r = run_cli(self.dir, "销售看板", "--filter", "月份=2020-04")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("https://bi.example.com/page/pg123?cd1=2020-04", r.stdout)

    def test_link_multi_value_repeats_param(self):
        r = run_cli(self.dir, "销售看板", "--filter", "月份=2020-04,2020-05")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("cd1=2020-04&cd1=2020-05", r.stdout)

    def test_unknown_field_refused_with_available_list(self):
        r = run_cli(self.dir, "销售看板", "--filter", "不存在字段=值")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("没有对应的页面筛选器", r.stderr)
        self.assertIn("月份", r.stderr)  # 列出可用筛选器，禁止静默忽略

    def test_anchor_appended(self):
        r = run_cli(self.dir, "销售看板", "--filter", "月份=2020-04", "--anchor", "总览卡")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("anchor=cd9", r.stdout)

    def test_list_shows_usable_and_marks_unusable(self):
        r = run_cli(self.dir, "--list", "销售看板")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("月份（筛选器「月份筛选」）", r.stdout)
        self.assertIn("✗", r.stdout)
        self.assertIn("不在筛选栏", r.stdout)

    def test_partial_page_name_match(self):
        r = run_cli(self.dir, "销售", "--filter", "月份=2020-04")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("/page/pg123?", r.stdout)


if __name__ == '__main__':
    unittest.main()
