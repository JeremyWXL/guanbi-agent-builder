#!/usr/bin/env python3
"""learn_dataset.py 的单测：字段合并/列画像/条目结构 + check_formulas/check_dims 回退 datasets-raw 集成"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import learn_dataset as ld

SCRIPTS = os.path.dirname(os.path.abspath(__file__))

DS_PAYLOAD = {
    "name": "测试数据集", "dsId": "ds1", "rowCount": 5000, "utime": "2026-09-20 10:00:00+0800",
    "columns": [
        {"name": "年月", "fdId": "f1", "metaType": "DIM", "fdType": "DATE", "calculationType": "normal"},
        {"name": "大区", "fdId": "f2", "metaType": "DIM", "fdType": "STRING", "calculationType": "normal"},
        {"name": "销售额", "fdId": "f3", "metaType": "METRIC", "fdType": "DOUBLE", "calculationType": "normal"},
    ],
    "virtualColumns": [
        {"name": "达成率", "fdId": "v1", "formula": "sum([销售额])/sum([目标])",
         "calculationType": "aggregation", "aggrType": "SUM"},
    ],
}

ROWS = [{"年月": "2026-01-01", "大区": "华东", "销售额": "123.5"},
        {"年月": "2026-02-01", "大区": "华南", "销售额": "456.0"},
        {"年月": "2026-03-01", "大区": "华东", "销售额": "789.0"}]


def write_json(workdir, name, doc):
    with open(os.path.join(workdir, name), "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)


def write_datasets_raw(workdir):
    entry = ld.build_entry("ds1", DS_PAYLOAD, ROWS, 200)
    entry.pop("_name", None)
    doc = {"测试数据集": entry,
           "_meta": {"builtAt": "2026-09-26 12:00", "builderVersion": ld.BUILDER_VERSION,
                     "mode": "dataset",
                     "dsFormulas": {"ds1": {"dsName": "测试数据集",
                                            "virtualColumns": DS_PAYLOAD["virtualColumns"]}}}}
    with open(os.path.join(workdir, "datasets-raw.json"), "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False)


class TestExtractColumns(unittest.TestCase):
    def test_physical_and_virtual_merged(self):
        cols = ld.extract_columns(DS_PAYLOAD)
        by_name = {c["name"]: c for c in cols}
        self.assertEqual(len(cols), 4)
        self.assertEqual(by_name["大区"]["metaType"], "DIM")
        self.assertEqual(by_name["达成率"]["formula"], "sum([销售额])/sum([目标])")
        self.assertEqual(by_name["达成率"]["calcType"], "aggregation")

    def test_virtual_column_dedupes_existing_fdid(self):
        payload = json.loads(json.dumps(DS_PAYLOAD))
        payload["virtualColumns"][0]["fdId"] = "f3"  # 与物理列同 fdId：合并而非新增
        cols = ld.extract_columns(payload)
        self.assertEqual(len(cols), 3)
        f3 = next(c for c in cols if c["fdId"] == "f3")
        self.assertEqual(f3["formula"], "sum([销售额])/sum([目标])")

    def test_skips_nameless_columns(self):
        payload = {"columns": [{"fdId": "x"}], "virtualColumns": [{"formula": "1"}]}
        self.assertEqual(ld.extract_columns(payload), [])


class TestProfile(unittest.TestCase):
    def test_number_date_enum(self):
        p = ld.profile(ROWS)
        self.assertEqual(p["销售额"]["type"], "number")
        self.assertEqual(p["销售额"]["min"], 123.5)
        self.assertEqual(p["年月"]["type"], "date")
        self.assertEqual(p["大区"]["type"], "text")
        self.assertIn("华东", p["大区"]["enum"])

    def test_empty_rows(self):
        self.assertEqual(ld.profile([]), {})


class TestBuildEntry(unittest.TestCase):
    def test_structure(self):
        e = ld.build_entry("ds1", DS_PAYLOAD, ROWS, 200)
        self.assertEqual(e["dsId"], "ds1")
        self.assertEqual(e["rowCount"], 5000)
        self.assertTrue(e["sample"]["truncated"])  # rowCount 5000 > 采样 3 行
        self.assertEqual(e["sample"]["sampledRows"], 3)

    def test_no_preview_degrades(self):
        e = ld.build_entry("ds1", DS_PAYLOAD, None, 200)
        self.assertNotIn("sample", e)
        self.assertEqual(len(e["columns"]), 4)


class TestDownstreamFallback(unittest.TestCase):
    """check_formulas / check_dims 在 cards-raw.json 缺失时回退 datasets-raw.json，再回退 cards.json（增量模式）"""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        write_datasets_raw(self.dir)

    def test_check_formulas_fallback(self):
        r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "check_formulas.py"),
                            self.dir, "--seed-metrics"], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(os.path.join(self.dir, "formulas.json"), encoding="utf-8") as f:
            doc = json.load(f)
        names = [m["name"] for m in doc["metrics"]]
        self.assertIn("达成率", names)
        with open(os.path.join(self.dir, "metrics-seed.json"), encoding="utf-8") as f:
            seed = json.load(f)
        m = next(x for x in seed["metrics"] if x["name"] == "达成率")
        self.assertEqual(m["source"], "dataset")
        self.assertEqual(m["formula"], "sum([销售额])/sum([目标])")

    def test_check_dims_seed_fallback(self):
        r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "check_dims.py"),
                            self.dir, "--seed-dims"], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(os.path.join(self.dir, "dimensions-seed.json"), encoding="utf-8") as f:
            doc = json.load(f)
        dims = {d["name"]: d for d in doc["dimensions"]}
        self.assertIn("大区", dims)
        self.assertIn("年月", dims)
        self.assertNotIn("销售额", dims)  # METRIC 不当维度
        self.assertEqual(dims["大区"]["source"], "dataset")
        self.assertIn("华东", dims["大区"]["values"])  # 枚举值来自内嵌 sample.profile

    def test_check_formulas_missing_both_exits(self):
        os.remove(os.path.join(self.dir, "datasets-raw.json"))
        r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "check_formulas.py"), self.dir],
                           capture_output=True, text=True, timeout=30)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("learn_dataset.py", r.stderr or r.stdout)

    def test_check_formulas_fallback_cards_json(self):
        """增量模式：只有交付 slim cards.json 时，口径字典从卡片 measures 生成"""
        d = tempfile.mkdtemp()
        write_json(d, "cards.json", {
            "_meta": {"dsFormulas": {}},
            "页一": {"title": "页一", "pgId": "p1",
                     "dsUsage": {"ds1": {"cards": 1, "filteredCards": 0}},
                     "cards": [{"name": "卡A", "cdId": "c1", "type": "TABLE", "dsId": "ds1",
                                "filtered": False, "dims": ["大区"],
                                "measures": [{"name": "销售额", "alias": "", "fdId": "f1",
                                              "dsId": "", "aggrType": "SUM",
                                              "formula": "sum([销售额])"}],
                                "filters": [], "filterDetails": [], "unitHints": {}}]}})
        r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "check_formulas.py"),
                            d, "--seed-metrics"], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(os.path.join(d, "formulas.json"), encoding="utf-8") as f:
            doc = json.load(f)
        names = [m["name"] for m in doc["metrics"]]
        self.assertIn("销售额", names)
        m = next(x for x in doc["metrics"] if x["name"] == "销售额")
        self.assertEqual(m["sources"][0]["page"], "页一")
        self.assertEqual(m["sources"][0]["card"], "卡A")

    def test_check_dims_seed_fallback_cards_json(self):
        """增量模式：只有交付 slim cards.json 时，维度种子从卡片 dims/filterDetails 生成"""
        d = tempfile.mkdtemp()
        write_json(d, "cards.json", {
            "_meta": {"dsFormulas": {}},
            "页一": {"title": "页一", "pgId": "p1",
                     "dsUsage": {"ds1": {"cards": 1, "filteredCards": 0}},
                     "cards": [{"name": "卡A", "cdId": "c1", "type": "TABLE", "dsId": "ds1",
                                "filtered": False, "dims": ["大区"],
                                "measures": [],
                                "filters": ["月份"],
                                "filterDetails": [{"field": "月份", "filterType": "eq", "filterValue": "2026-09"}],
                                "unitHints": {}}]}})
        r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "check_dims.py"),
                            d, "--seed-dims"], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(os.path.join(d, "dimensions-seed.json"), encoding="utf-8") as f:
            doc = json.load(f)
        names = {x["name"] for x in doc["dimensions"]}
        self.assertEqual(names, {"大区", "月份"})

    def test_check_formulas_missing_all_exits(self):
        d = tempfile.mkdtemp()
        r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "check_formulas.py"), d],
                           capture_output=True, text=True, timeout=30)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("merge_cards.py", r.stderr or r.stdout)


class TestMainBatch(unittest.TestCase):
    """批量学习出口哨兵：同名数据集冲突 / 部分失败——禁止档案与 _meta 不一致的静默交付"""

    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def out_file(self):
        return os.path.join(self.dir, "datasets-raw.json")

    def run_main(self, ds_ids, learned, extra=()):
        old = sys.argv
        sys.argv = ["learn_dataset.py", *ds_ids, "-o", self.dir, *extra]
        try:
            with mock.patch.object(ld, "learn_one", side_effect=lambda d, _rows: (d, learned[d])), \
                 mock.patch.object(ld, "bi_base_url", return_value=""):
                ld.main()
        finally:
            sys.argv = old

    @staticmethod
    def ok(name, ds_id):
        entry = ld.build_entry(ds_id, DS_PAYLOAD, ROWS, 200)
        return {"name": name, "entry": entry, "virtualColumns": []}

    def test_same_name_datasets_rejected(self):
        """不同 dsId 同名数据集：名称键互相覆盖（档案少一个、dsFormulas 仍两个），exit 2 且不写产物"""
        learned = {"d1": self.ok("销售数据集", "d1"), "d2": self.ok("销售数据集", "d2")}
        with self.assertRaises(SystemExit) as cm:
            self.run_main(["d1", "d2"], learned)
        self.assertEqual(cm.exception.code, 2)
        self.assertFalse(os.path.exists(self.out_file()))

    def test_partial_failure_rejected_by_default(self):
        """部分数据集失败默认 exit 2，且不写产物"""
        learned = {"d1": self.ok("销售数据集", "d1"), "d2": {"error": "ds get 失败: 无权限"}}
        with self.assertRaises(SystemExit) as cm:
            self.run_main(["d1", "d2"], learned)
        self.assertEqual(cm.exception.code, 2)
        self.assertFalse(os.path.exists(self.out_file()))

    def test_allow_partial_writes_report_with_failed_ids(self):
        """--allow-partial：成功项正常写出，失败 dsId 记入 _meta.failedDatasets（机器可读）"""
        learned = {"d1": self.ok("销售数据集", "d1"), "d2": {"error": "ds get 失败: 无权限"}}
        self.run_main(["d1", "d2"], learned, extra=["--allow-partial"])
        with open(self.out_file(), encoding="utf-8") as f:
            doc = json.load(f)
        self.assertIn("销售数据集", doc)
        self.assertEqual(doc["_meta"]["failedDatasets"], ["d2"])
        self.assertEqual(set(doc["_meta"]["dsFormulas"].keys()), {"d1"})  # 档案与元数据一致


if __name__ == "__main__":
    unittest.main()
