#!/usr/bin/env python3
"""sample_cards.py 单测：--only-cdIds 定向采样与 --prune-keys 孤儿清理（增量学习用）、
采样文件键带 cdId 防碰撞（非法字符归一化/截断后同名不再互相覆盖）、同键重复整批拒绝"""
import json, os, sys, tempfile, unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sample_cards

ROWS = [{"大区": "华东", "销售额": "123.5"}, {"大区": "华南", "销售额": "456.0"}]


def write_json(workdir, name, doc):
    with open(os.path.join(workdir, name), "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)


def make_cards_doc():
    return {"_meta": {},
            "页一": {"title": "页一", "pgId": "p1", "dsUsage": {},
                     "cards": [
                         {"name": "卡A", "cdId": "c1", "type": "TABLE", "dims": [], "measures": []},
                         {"name": "卡B", "cdId": "c2", "type": "TABLE", "dims": [], "measures": []},
                         {"name": "卡C", "cdId": "c3", "type": "TABLE", "dims": [], "measures": []},
                         {"name": "筛选器", "cdId": "s1", "type": "SELECTOR", "dims": [], "measures": []},
                     ]}}


class OnlyCdIdsTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        write_json(self.dir, "cards.json", make_cards_doc())
        self.out = os.path.join(self.dir, "card-data")

    def run_sample(self, extra_args):
        argv = sys.argv
        sys.argv = ["sample_cards.py", os.path.join(self.dir, "cards.json"), self.out] + extra_args
        with mock.patch.object(sample_cards, "preview", side_effect=lambda cd: (dict(ROWS), None)), \
             mock.patch("builtins.print"):
            try:
                sample_cards.main()
            finally:
                sys.argv = argv
        with open(os.path.join(self.out, "_sample_index.json"), encoding="utf-8") as f:
            return json.load(f)

    def test_only_cdids_samples_listed_cards(self):
        ids = os.path.join(self.dir, "ids.txt")
        with open(ids, "w", encoding="utf-8") as f:
            f.write("c1\nc3\n")
        index = self.run_sample(["--only-cdIds", ids])
        self.assertEqual(set(index.keys()), {"页一__卡A__c1", "页一__卡C__c3"})
        self.assertTrue(os.path.exists(os.path.join(self.out, "页一__卡A__c1.json")))
        self.assertFalse(os.path.exists(os.path.join(self.out, "页一__卡B__c2.json")))

    def test_only_cdids_accepts_json_list(self):
        ids = os.path.join(self.dir, "ids.json")
        write_json(self.dir, "ids.json", ["c2"])
        index = self.run_sample(["--only-cdIds", ids])
        self.assertEqual(set(index.keys()), {"页一__卡B__c2"})

    def test_without_only_cdids_samples_all(self):
        index = self.run_sample([])
        # SELECTOR 被 SKIP_TYPES 跳过，其余 3 张数据卡全采
        self.assertEqual(set(index.keys()), {"页一__卡A__c1", "页一__卡B__c2", "页一__卡C__c3"})


class PruneKeysTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        write_json(self.dir, "cards.json", make_cards_doc())
        self.out = os.path.join(self.dir, "card-data")
        os.makedirs(self.out)
        # 预置采样文件：两个现行（新格式）+ 一个新格式孤儿 + 一个旧格式孤儿（升级前遗留命名）
        for key in ("页一__卡A__c1", "页一__卡B__c2", "页一__被删卡__c9", "页一__旧格式卡"):
            write_json(self.out, f"{key}.json", ROWS)

    def test_prune_keys_deletes_orphans(self):
        keys = os.path.join(self.dir, "prune.txt")
        with open(keys, "w", encoding="utf-8") as f:
            f.write("页一__被删卡__c9\n页一__旧格式卡\n")
        argv = sys.argv
        sys.argv = ["sample_cards.py", os.path.join(self.dir, "cards.json"), self.out,
                    "--prune-keys", keys]
        with mock.patch.object(sample_cards, "preview", side_effect=lambda cd: (dict(ROWS), None)), \
             mock.patch("builtins.print"):
            try:
                sample_cards.main()
            finally:
                sys.argv = argv
        self.assertFalse(os.path.exists(os.path.join(self.out, "页一__被删卡__c9.json")))
        self.assertFalse(os.path.exists(os.path.join(self.out, "页一__旧格式卡.json")))
        self.assertTrue(os.path.exists(os.path.join(self.out, "页一__卡A__c1.json")))
        # 现行卡片照常采样，index 只含数据卡
        with open(os.path.join(self.out, "_sample_index.json"), encoding="utf-8") as f:
            index = json.load(f)
        self.assertEqual(set(index.keys()), {"页一__卡A__c1", "页一__卡B__c2", "页一__卡C__c3"})


class KeyCollisionTest(unittest.TestCase):
    """采样文件键 = 页面名__卡片名__cdId：非法字符归一化/截断后同名的不同卡片不再互相覆盖；
    同一 key 仍重复出现（同 cdId 被列两次）即整批拒绝（exit 2），禁止静默覆盖"""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.out = os.path.join(self.dir, "card-data")

    def run_sample(self, doc):
        cards_file = os.path.join(self.dir, "cards.json")
        write_json(self.dir, "cards.json", doc)
        argv = sys.argv
        sys.argv = ["sample_cards.py", cards_file, self.out]
        with mock.patch.object(sample_cards, "preview", side_effect=lambda cd: (dict(ROWS), None)), \
             mock.patch("builtins.print"):
            try:
                sample_cards.main()
            except SystemExit as e:
                return e.code
            finally:
                sys.argv = argv
        return 0

    def test_normalized_name_collision_both_sampled(self):
        # 「收入/本月」与「收入:本月」safe_name 后都是「收入_本月」——cdId 后缀保住两份采样
        doc = {"页一": {"cards": [
            {"name": "收入/本月", "cdId": "c1", "type": "TABLE", "dims": [], "measures": []},
            {"name": "收入:本月", "cdId": "c2", "type": "TABLE", "dims": [], "measures": []}]}}
        code = self.run_sample(doc)
        self.assertEqual(code, 0)
        self.assertTrue(os.path.exists(os.path.join(self.out, "页一__收入_本月__c1.json")))
        self.assertTrue(os.path.exists(os.path.join(self.out, "页一__收入_本月__c2.json")))

    def test_truncated_name_collision_both_sampled(self):
        # 前 60 字符相同的长名称：safe_name 截断后同名，cdId 后缀区分
        prefix = "超长卡片名称" * 10
        doc = {"页一": {"cards": [
            {"name": prefix + "甲", "cdId": "c1", "type": "TABLE", "dims": [], "measures": []},
            {"name": prefix + "乙", "cdId": "c2", "type": "TABLE", "dims": [], "measures": []}]}}
        code = self.run_sample(doc)
        self.assertEqual(code, 0)
        with open(os.path.join(self.out, "_sample_index.json"), encoding="utf-8") as f:
            index = json.load(f)
        self.assertEqual(len(index), 2)
        self.assertEqual({v["cdId"] for v in index.values()}, {"c1", "c2"})

    def test_duplicate_key_rejects_batch(self):
        # 同页重复列出同一张卡（同 cdId）→ 同 key 重复，整批拒绝（exit 2），禁止静默覆盖
        card = {"name": "卡A", "cdId": "c1", "type": "TABLE", "dims": [], "measures": []}
        doc = {"页一": {"title": "页一", "cards": [card, dict(card)]}}
        code = self.run_sample(doc)
        self.assertEqual(code, 2)
        # 冲突在采样前的预检拦截：无部分采样、无 index 落盘
        self.assertFalse(os.path.exists(os.path.join(self.out, "页一__卡A__c1.json")))
        self.assertFalse(os.path.exists(os.path.join(self.out, "_sample_index.json")))


class ScopeTest(unittest.TestCase):
    """--scope：待采卡片 cdId 必须 ∈ 白名单，越界整批拒绝（exit 2 哨兵）"""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        # 白名单：页一 2 卡（c1/c2）
        write_json(self.dir, "scope-cards.json", {
            "_meta": {"pages": {"p1": {"title": "页一"}}},
            "页一": {"title": "页一", "pgId": "p1", "dsUsage": {"ds1": {"cards": 2, "filteredCards": 0}},
                     "cards": [{"name": "卡A", "cdId": "c1", "type": "TABLE"},
                               {"name": "卡B", "cdId": "c2", "type": "TABLE"}]}})
        self.out = os.path.join(self.dir, "card-data")

    def run_sample(self, cards_file, extra_args):
        argv = sys.argv
        sys.argv = ["sample_cards.py", cards_file, self.out] + extra_args
        with mock.patch.object(sample_cards, "preview", side_effect=lambda cd: (dict(ROWS), None)), \
             mock.patch("builtins.print"):
            try:
                sample_cards.main()
            except SystemExit as e:
                sys.argv = argv
                return e.code
            sys.argv = argv
            return 0

    def test_scope_violation_rejects_batch(self):
        # 待采文件混入覆盖外 cdId（c9 属于没学过的看板）
        write_json(self.dir, "mixed.json", {"页一": {"cards": [
            {"name": "卡A", "cdId": "c1", "type": "TABLE", "dims": [], "measures": []},
            {"name": "外来卡", "cdId": "c9", "type": "TABLE", "dims": [], "measures": []}]}})
        code = self.run_sample(os.path.join(self.dir, "mixed.json"),
                               ["--scope", os.path.join(self.dir, "scope-cards.json")])
        self.assertEqual(code, 2)
        self.assertFalse(os.path.exists(os.path.join(self.out, "页一__卡A__c1.json")))  # 整批拒绝，无部分采样

    def test_scope_pass_for_in_scope_cards(self):
        write_json(self.dir, "in-scope.json", {"页一": {"cards": [
            {"name": "卡A", "cdId": "c1", "type": "TABLE", "dims": [], "measures": []}]}})
        code = self.run_sample(os.path.join(self.dir, "in-scope.json"),
                               ["--scope", os.path.join(self.dir, "scope-cards.json")])
        self.assertEqual(code, 0)
        self.assertTrue(os.path.exists(os.path.join(self.out, "页一__卡A__c1.json")))


if __name__ == "__main__":
    unittest.main()
