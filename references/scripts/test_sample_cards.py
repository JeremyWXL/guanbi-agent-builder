#!/usr/bin/env python3
"""sample_cards.py 单测：--only-cdIds 定向采样与 --prune-keys 孤儿清理（增量学习用）"""
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
        self.assertEqual(set(index.keys()), {"页一__卡A", "页一__卡C"})
        self.assertTrue(os.path.exists(os.path.join(self.out, "页一__卡A.json")))
        self.assertFalse(os.path.exists(os.path.join(self.out, "页一__卡B.json")))

    def test_only_cdids_accepts_json_list(self):
        ids = os.path.join(self.dir, "ids.json")
        write_json(self.dir, "ids.json", ["c2"])
        index = self.run_sample(["--only-cdIds", ids])
        self.assertEqual(set(index.keys()), {"页一__卡B"})

    def test_without_only_cdids_samples_all(self):
        index = self.run_sample([])
        # SELECTOR 被 SKIP_TYPES 跳过，其余 3 张数据卡全采
        self.assertEqual(set(index.keys()), {"页一__卡A", "页一__卡B", "页一__卡C"})


class PruneKeysTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        write_json(self.dir, "cards.json", make_cards_doc())
        self.out = os.path.join(self.dir, "card-data")
        os.makedirs(self.out)
        # 预置三个采样文件：两个现行 + 一个孤儿（被删卡片的旧 key）
        for key in ("页一__卡A", "页一__卡B", "页一__被删卡"):
            write_json(self.out, f"{key}.json", ROWS)

    def test_prune_keys_deletes_orphans(self):
        keys = os.path.join(self.dir, "prune.txt")
        with open(keys, "w", encoding="utf-8") as f:
            f.write("页一__被删卡\n")
        argv = sys.argv
        sys.argv = ["sample_cards.py", os.path.join(self.dir, "cards.json"), self.out,
                    "--prune-keys", keys]
        with mock.patch.object(sample_cards, "preview", side_effect=lambda cd: (dict(ROWS), None)), \
             mock.patch("builtins.print"):
            try:
                sample_cards.main()
            finally:
                sys.argv = argv
        self.assertFalse(os.path.exists(os.path.join(self.out, "页一__被删卡.json")))
        self.assertTrue(os.path.exists(os.path.join(self.out, "页一__卡A.json")))
        # 现行卡片照常采样，index 只含数据卡
        with open(os.path.join(self.out, "_sample_index.json"), encoding="utf-8") as f:
            index = json.load(f)
        self.assertEqual(set(index.keys()), {"页一__卡A", "页一__卡B", "页一__卡C"})


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
        self.assertFalse(os.path.exists(os.path.join(self.out, "页一__卡A.json")))  # 整批拒绝，无部分采样

    def test_scope_pass_for_in_scope_cards(self):
        write_json(self.dir, "in-scope.json", {"页一": {"cards": [
            {"name": "卡A", "cdId": "c1", "type": "TABLE", "dims": [], "measures": []}]}})
        code = self.run_sample(os.path.join(self.dir, "in-scope.json"),
                               ["--scope", os.path.join(self.dir, "scope-cards.json")])
        self.assertEqual(code, 0)
        self.assertTrue(os.path.exists(os.path.join(self.out, "页一__卡A.json")))


if __name__ == "__main__":
    unittest.main()
