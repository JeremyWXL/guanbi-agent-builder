#!/usr/bin/env python3
"""learn_dataset.py 的单测：字段合并/列画像/条目结构 + check_formulas/check_dims 回退 datasets-raw 集成"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

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
    """check_formulas / check_dims 在 cards-raw.json 缺失时回退 datasets-raw.json"""

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


if __name__ == "__main__":
    unittest.main()
