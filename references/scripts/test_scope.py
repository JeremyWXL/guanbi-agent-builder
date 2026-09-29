#!/usr/bin/env python3
"""scope.py 单测：看板模式/数据集直通模式提取、旧档案降级、全缺失返回 None"""
import json, os, sys, tempfile, unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scope


def write_json(workdir, name, doc):
    with open(os.path.join(workdir, name), "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)


def make_cards_doc(with_meta_pages=True):
    doc = {
        "_meta": {"builtAt": "2026-09-26 10:00", "builderVersion": "4.4.0",
                  "biBaseUrl": "https://bi.example.com", "parser": "raw",
                  "dsFormulas": {"ds1": {"dsName": "数据集1", "virtualColumns": []}}},
        "页一": {"title": "页一", "pgId": "p1",
                 "dsUsage": {"ds1": {"cards": 2, "filteredCards": 1}},
                 "cards": [{"name": "卡A", "cdId": "c1", "type": "TABLE", "dsId": "ds1", "filtered": False},
                           {"name": "卡B", "cdId": "c2", "type": "TABLE", "dsId": "ds1", "filtered": True}]},
        "页二": {"title": "页二", "pgId": "p2",
                 "dsUsage": {"ds2": {"cards": 1, "filteredCards": 0}},
                 "cards": [{"name": "卡C", "cdId": "c3", "type": "TABLE", "dsId": "ds2", "filtered": False}]},
    }
    if with_meta_pages:
        doc["_meta"]["pages"] = {
            "p1": {"title": "页一", "mtime": "2026-09-20 10:00:00+0800", "cardCount": 2,
                   "cardHash": "abc123", "cards": [{"cdId": "c1", "name": "卡A"}, {"cdId": "c2", "name": "卡B"}]},
            "p2": {"title": "页二", "mtime": "2026-09-20 10:00:00+0800", "cardCount": 1,
                   "cardHash": "def456", "cards": [{"cdId": "c3", "name": "卡C"}]},
        }
    return doc


class DashboardModeTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        write_json(self.dir, "cards.json", make_cards_doc())

    def test_extracts_all_whitelists(self):
        s = scope.load_scope(candidates=[os.path.join(self.dir, "cards.json")])
        self.assertEqual(set(s["pgIds"].keys()), {"p1", "p2"})
        self.assertEqual(s["pgIds"]["p1"], "页一")
        self.assertEqual(s["dsIds"], {"ds1", "ds2"})
        self.assertEqual(set(s["cdIds"].keys()), {"c1", "c2", "c3"})
        self.assertEqual(s["cdIds"]["c2"], "页一__卡B")
        self.assertEqual(sorted(s["titles"]), ["页一", "页二"])
        self.assertTrue(s["source"].endswith("cards.json"))

    def test_legacy_doc_without_meta_pages_degrades(self):
        # v3.1 前档案无 _meta.pages：pgIds 空集，dsIds/cdIds 照常提取
        write_json(self.dir, "cards.json", make_cards_doc(with_meta_pages=False))
        s = scope.load_scope(candidates=[os.path.join(self.dir, "cards.json")])
        self.assertEqual(s["pgIds"], {})
        self.assertEqual(s["dsIds"], {"ds1", "ds2"})
        self.assertEqual(set(s["cdIds"].keys()), {"c1", "c2", "c3"})


class DatasetDirectModeTest(unittest.TestCase):
    def test_datasets_json_extracts_dsids(self):
        d = tempfile.mkdtemp()
        write_json(d, "datasets.json", {
            "_meta": {"dsFormulas": {}},
            "数据集甲": {"dsId": "dsX", "mtime": "2026-09-20 10:00:00+0800", "rowCount": 10, "columns": []},
            "数据集乙": {"dsId": "dsY", "mtime": "2026-09-20 10:00:00+0800", "rowCount": 20, "columns": []},
        })
        s = scope.load_scope(candidates=[os.path.join(d, "datasets.json")])
        self.assertEqual(s["dsIds"], {"dsX", "dsY"})
        self.assertEqual(s["pgIds"], {})
        self.assertEqual(s["cdIds"], {})


class MetricIdsTest(unittest.TestCase):
    """v4.8 指标中心引用白名单：从 scope 文件同目录的 metrics.json 提取 governedRef.metricId"""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        write_json(self.dir, "cards.json", make_cards_doc())

    def load(self):
        return scope.load_scope(candidates=[os.path.join(self.dir, "cards.json")])

    def test_governed_ref_metric_ids_extracted(self):
        write_json(self.dir, "metrics.json", {"metrics": [
            {"name": "净收入", "governedRef": {"metricId": "m100", "name": "净收入", "status": "PUBLISHED"}},
            {"name": "毛利率"},  # 无 governedRef，不收录（多数指标没有引用，正常）
            {"name": "达成率", "governedRef": {"metricId": "m200", "name": "达成率"}},
        ]})
        s = self.load()
        self.assertEqual(s["metricIds"], {"m100", "m200"})

    def test_no_metrics_json_empty_set(self):
        # 旧档案无 metrics.json → 空集，不报错
        s = self.load()
        self.assertEqual(s["metricIds"], set())

    def test_metrics_without_governed_ref_empty_set(self):
        write_json(self.dir, "metrics.json", {"metrics": [{"name": "净收入", "formula": "sum([x])"}]})
        s = self.load()
        self.assertEqual(s["metricIds"], set())

    def test_broken_metrics_json_empty_set(self):
        with open(os.path.join(self.dir, "metrics.json"), "w", encoding="utf-8") as f:
            f.write("{not json")
        s = self.load()
        self.assertEqual(s["metricIds"], set())

    def test_dataset_mode_also_extracts(self):
        d = tempfile.mkdtemp()
        write_json(d, "datasets.json", {"数据集甲": {"dsId": "dsX"}})
        write_json(d, "metrics.json", {"metrics": [
            {"name": "净收入", "governedRef": {"metricId": "m100", "name": "净收入"}}]})
        s = scope.load_scope(candidates=[os.path.join(d, "datasets.json")])
        self.assertEqual(s["metricIds"], {"m100"})


class MissingFileTest(unittest.TestCase):
    def test_returns_none_when_no_scope_file(self):
        d = tempfile.mkdtemp()
        self.assertIsNone(scope.load_scope(candidates=[os.path.join(d, "cards.json")]))
        self.assertIsNone(scope.load_scope(candidates=[os.path.join(d, "datasets.json")]))


if __name__ == "__main__":
    unittest.main()
