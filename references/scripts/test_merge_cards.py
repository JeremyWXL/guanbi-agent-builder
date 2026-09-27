#!/usr/bin/env python3
"""merge_cards.py 单测：新页加入/未变页跳过/变更页 diff/整页移除/哨兵/备份/受影响清单"""
import json, os, sys, tempfile, unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import merge_cards


def make_card(cd_id, name, ctype="TABLE", ds_id="ds1", filtered=False):
    return {"name": name, "cdId": cd_id, "type": ctype, "inPool": False, "dsId": ds_id,
            "filters": [], "filterDetails": [], "unitHints": {}, "dims": ["日期"],
            "measures": [{"name": "金额", "alias": "", "fdId": "f1", "dsId": "", "aggrType": "SUM"}],
            "filtered": filtered}


def make_page(pid, title, cards, mtime="2026-09-27 10:00:00+0800"):
    return {"title": title, "pgId": pid, "mtime": mtime,
            "dsIds": sorted({c["dsId"] for c in cards if c["dsId"]}),
            "dsUsage": {c["dsId"]: {"cards": 1, "filteredCards": 1 if c.get("filtered") else 0}
                         for c in cards if c["dsId"]},
            "cards": cards}


def meta_page(title, cards):
    return {"title": title, "mtime": "2026-09-20 10:00:00+0800", "cardCount": len(cards),
            "cardHash": merge_cards.structure_hash(cards),
            "cards": [{"cdId": c["cdId"], "name": c["name"]} for c in cards]}


def slim(card):
    return {"name": card["name"], "cdId": card["cdId"], "type": card["type"],
            "dsId": card["dsId"], "filtered": card.get("filtered", False),
            "dims": card["dims"], "measures": card["measures"], "filters": [],
            "filterDetails": [], "unitHints": {}}


class MergeCardsTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.pkg = os.path.join(self.dir, "pkg")
        os.makedirs(os.path.join(self.pkg, "references"))
        self.workdir = os.path.join(self.dir, "work")
        os.makedirs(self.workdir)
        # 交付包：页一（2 卡）+ 页二（1 卡）
        self.p1_cards = [make_card("c1", "卡A"), make_card("c2", "卡B", filtered=True)]
        self.p2_cards = [make_card("c3", "卡C", ds_id="ds2")]
        base = {
            "notes": {"unit": "测试"},
            "_meta": {
                "builtAt": "2026-09-26 10:00", "builderVersion": "4.3.0",
                "biBaseUrl": "https://bi.example.com", "parser": "raw",
                "pages": {"p1": meta_page("页一", self.p1_cards),
                          "p2": meta_page("页二", self.p2_cards)},
                "dsFormulas": {"ds1": {"dsName": "数据集1", "virtualColumns": []}},
            },
            "页一": {"title": "页一", "pgId": "p1",
                     "dsUsage": {"ds1": {"cards": 2, "filteredCards": 1}},
                     "cards": [slim(c) for c in self.p1_cards]},
            "页二": {"title": "页二", "pgId": "p2",
                     "dsUsage": {"ds2": {"cards": 1, "filteredCards": 0}},
                     "cards": [slim(c) for c in self.p2_cards]},
        }
        with open(os.path.join(self.pkg, "references", "cards.json"), "w", encoding="utf-8") as f:
            json.dump(base, f, ensure_ascii=False)
        # 交付包示例库：Q1 路由到页一卡B
        ex = {"version": 1, "updatedAt": "2026-09-26 10:00", "_readme": "",
              "scenarios": {"问数": [{"id": "Q1", "question": "卡B 多少？",
                                     "route": {"pageId": "p1", "pageName": "页一", "cards": ["卡B"]},
                                     "fetch": {"type": "card", "file": "card-data/页一__卡B.json"},
                                     "expect": {"values": [1], "tolerance": 0.02, "keywords": []},
                                     "answerPoints": [], "humanConfirmed": True}]}}
        with open(os.path.join(self.pkg, "references", "examples.json"), "w", encoding="utf-8") as f:
            json.dump(ex, f, ensure_ascii=False)

    def merge(self, pages=(), remove=()):
        self.fresh = {pid: self._fresh_pages[pid] for pid in pages}
        with mock.patch.object(merge_cards.parse_page, "parse_page",
                               side_effect=lambda pid: self.fresh.get(pid, {"error": "无此页"})), \
             mock.patch.object(merge_cards.parse_page, "fetch_ds_formulas", return_value={}):
            r = merge_cards_main(self.workdir, self.pkg, list(pages), list(remove))
        return r

    def read_merged(self):
        with open(os.path.join(self.workdir, "cards-merged.json"), encoding="utf-8") as f:
            return json.load(f)

    def read_report(self):
        with open(os.path.join(self.workdir, "incr-report.json"), encoding="utf-8") as f:
            return json.load(f)

    def backups(self):
        return [fn for fn in os.listdir(self.workdir) if fn.startswith("cards.json.bak-incr-")]


class NewPageTest(MergeCardsTest):
    def setUp(self):
        super().setUp()
        self._fresh_pages = {"px": make_page("px", "新页", [make_card("cx1", "新卡1"), make_card("cx2", "新卡2", ds_id="ds9")])}

    def test_new_page_added(self):
        self.merge(pages=["px"])
        m = self.read_merged()
        self.assertIn("新页", m)
        self.assertEqual(m["新页"]["pgId"], "px")
        self.assertEqual(len(m["新页"]["cards"]), 2)
        self.assertEqual(m["新页"]["cards"][0]["name"], "新卡1")
        # 旧页保留
        self.assertIn("页一", m)
        self.assertEqual(len(m["页一"]["cards"]), 2)
        # _meta 更新 + incrLog + 数据集
        self.assertEqual(m["_meta"]["pages"]["px"]["cardCount"], 2)
        self.assertEqual(len(m["_meta"]["incrLog"]), 1)
        self.assertEqual(m["_meta"]["incrLog"][0]["addedPages"], ["px"])
        self.assertEqual(m["_meta"]["dsFormulas"]["ds1"]["dsName"], "数据集1")  # 旧公式保留
        # 报告
        r = self.read_report()
        self.assertEqual(r["addedPages"][0]["title"], "新页")
        self.assertEqual(sorted(r["resampleCdIds"]), ["cx1", "cx2"])
        self.assertEqual(r["datasets"]["added"], ["ds9"])
        self.assertEqual(r["datasets"]["lost"], [])
        self.assertEqual(r["pruneSampleKeys"], [])
        self.assertEqual(r["affectedExamples"], [])
        self.assertEqual(r["affectedMetrics"], [])


class UnchangedPageTest(MergeCardsTest):
    def setUp(self):
        super().setUp()
        self._fresh_pages = {"p1": make_page("p1", "页一", [make_card("c1", "卡A"), make_card("c2", "卡B", filtered=True)])}

    def test_unchanged_page_skipped(self):
        self.merge(pages=["p1"])
        m = self.read_merged()
        self.assertEqual(len(m["页一"]["cards"]), 2)  # 原样保留
        r = self.read_report()
        self.assertEqual(r["unchangedPages"], [{"pgId": "p1", "title": "页一"}])
        self.assertEqual(r["resampleCdIds"], [])  # 未变页不重采样
        self.assertEqual(r["addedPages"], [])
        self.assertEqual(r["changedPages"], [])


class ChangedPageTest(MergeCardsTest):
    def setUp(self):
        super().setUp()
        # 页一改版：卡B 被删
        self._fresh_pages = {"p1": make_page("p1", "页一", [make_card("c1", "卡A")])}
        # 工作目录 formulas.json：指标"卡B指标"的来源引用《页一》卡B
        fdoc = {"_meta": {}, "metrics": [
                    {"name": "卡B指标", "classification": "FREE", "consensus": True,
                     "occurrences": 1, "sources": [{"page": "页一", "card": "卡B", "dims": [], "scope": []}]},
                    {"name": "卡A指标", "classification": "FREE", "consensus": True,
                     "occurrences": 1, "sources": [{"page": "页一", "card": "卡A", "dims": [], "scope": []}]}],
                "conflicts": [], "candidateRules": []}
        with open(os.path.join(self.workdir, "formulas.json"), "w", encoding="utf-8") as f:
            json.dump(fdoc, f, ensure_ascii=False)

    def test_changed_page_diff_and_affected(self):
        self.merge(pages=["p1"])
        m = self.read_merged()
        self.assertEqual([c["name"] for c in m["页一"]["cards"]], ["卡A"])
        r = self.read_report()
        self.assertEqual(r["changedPages"][0]["removed"], ["卡B"])
        self.assertEqual(r["changedPages"][0]["added"], [])
        self.assertEqual(r["pruneSampleKeys"], ["页一__卡B"])
        self.assertEqual(r["resampleCdIds"], ["c1"])  # 变更页整页重采样
        self.assertEqual(r["affectedExamples"][0]["id"], "Q1")
        self.assertEqual(r["affectedMetrics"], ["卡B指标"])
        # 被删卡片不进 tombstone：合并结果里没有卡B
        self.assertFalse(any(c["cdId"] == "c2" for c in m["页一"]["cards"]))


class RenamedPageTest(MergeCardsTest):
    """页面改名但卡片未变：cardHash 相同也要走变更路径（采样 key 含页面名，改名即孤儿）"""
    def setUp(self):
        super().setUp()
        self._fresh_pages = {"p1": make_page("p1", "页一（新）",
                                             [make_card("c1", "卡A"), make_card("c2", "卡B", filtered=True)])}

    def test_page_rename_detected(self):
        self.merge(pages=["p1"])
        m = self.read_merged()
        self.assertIn("页一（新）", m)
        self.assertNotIn("页一", m)  # 旧标题键移除
        self.assertEqual(m["_meta"]["pages"]["p1"]["title"], "页一（新）")
        r = self.read_report()
        self.assertEqual(r["renamedPages"], [{"pgId": "p1", "old": "页一", "new": "页一（新）"}])
        self.assertEqual(r["changedPages"][0]["renamedFrom"], "页一")
        self.assertEqual(r["unchangedPages"], [])  # 未误判为"未变跳过"
        # 旧页面名下全部采样 key 成为孤儿；整页重采样换新 key
        self.assertEqual(sorted(r["pruneSampleKeys"]), ["页一__卡A", "页一__卡B"])
        self.assertEqual(sorted(r["resampleCdIds"]), ["c1", "c2"])
        # 引用旧采样文件的已验收示例被点名
        self.assertEqual(r["affectedExamples"][0]["id"], "Q1")


class TitleCollisionTest(MergeCardsTest):
    def test_new_page_same_title_rejected(self):
        # 新页 pgId 不同但标题与已学《页一》同名：cards.json 以名为键，同名会互相覆盖，拒绝
        self._fresh_pages = {"py": make_page("py", "页一", [make_card("cy1", "异卡")])}
        with self.assertRaises(SystemExit) as cm:
            self.merge(pages=["py"])
        self.assertEqual(cm.exception.code, 1)
        self.assertFalse(os.path.exists(os.path.join(self.workdir, "cards-merged.json")))


class RemovePageTest(MergeCardsTest):
    def test_removed_page(self):
        self.merge(remove=["p2"])
        m = self.read_merged()
        self.assertNotIn("页二", m)
        self.assertIn("页一", m)
        r = self.read_report()
        self.assertEqual(r["removedPages"][0]["pgId"], "p2")
        self.assertEqual(r["removedPages"][0]["cards"], ["卡C"])
        self.assertEqual(r["datasets"]["lost"], ["ds2"])
        self.assertIn("p2", m["_meta"]["incrLog"][0]["removedPages"])
        self.assertNotIn("p2", m["_meta"]["pages"])


class SentinelTest(MergeCardsTest):
    def test_zero_cards_exit2(self):
        self._fresh_pages = {"pz": make_page("pz", "空页", [])}
        with self.assertRaises(SystemExit) as cm:
            self.merge(pages=["pz"])
        self.assertEqual(cm.exception.code, 2)
        self.assertFalse(os.path.exists(os.path.join(self.workdir, "cards-merged.json")))


class BackupTest(MergeCardsTest):
    def test_backup_created(self):
        self._fresh_pages = {"px": make_page("px", "新页", [make_card("cx1", "新卡1")])}
        self.merge(pages=["px"])
        self.assertEqual(len(self.backups()), 1)
        # 备份内容 = 合并前的交付包 cards.json
        with open(os.path.join(self.workdir, self.backups()[0]), encoding="utf-8") as f:
            bak = json.load(f)
        self.assertNotIn("新页", bak)


def merge_cards_main(workdir, pkg, pages, remove):
    """直接调用 merge_cards.main() 的参数构造版（绕过 argparse）"""
    import argparse
    args = argparse.Namespace(workdir=workdir, package=pkg, pages=pages,
                              remove_pages=remove, workers=4)
    merge_cards.main(args)


if __name__ == "__main__":
    unittest.main()
