#!/usr/bin/env python3
"""
check_dims.py 最小单测：结构/同义词撞车/取值重叠与相似/种子生成的关键路径。
运行: python3 -m unittest discover -s references/scripts -p 'test_*.py' -v
不触网：全部用临时目录构造 cards-raw.json / metrics.json / _sample_index.json。
"""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_dims


def write_json(d, name, obj):
    fp = os.path.join(d, name)
    os.makedirs(os.path.dirname(fp), exist_ok=True)
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)


def dim(name, **kw):
    d = {"name": name, "field": name, "synonyms": [], "values": ["甲", "乙"],
         "valueAliases": {}, "source": "card"}
    d.update(kw)
    return d


class TestPureHelpers(unittest.TestCase):
    def test_norm(self):
        self.assertEqual(check_dims.norm(" 华东 "), "华东")
        self.assertEqual(check_dims.norm("ＡＢＣ"), "abc")  # 全角转半角 + 小写
        self.assertEqual(check_dims.norm("A B"), "ab")

    def test_card_dims_skips_meta(self):
        raw = {"_meta": {"cards": [{"dims": ["不应收"]}]},
               "看板A": {"cards": [{"dims": ["大区"], "filterDetails": []},
                                  {"cdType": "SELECTOR", "dims": [],
                                   "filterDetails": [{"field": "月份"}]}]}}
        self.assertEqual(check_dims.card_dims(raw), {"大区", "月份"})

    def test_metric_words(self):
        doc = {"metrics": [{"name": "净收入", "synonyms": ["净额"]}]}
        self.assertEqual(check_dims.metric_words(doc), {"净收入": "净收入", "净额": "净收入"})


class TestValidate(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def run_main(self, dims_doc):
        write_json(self.dir, "dimensions.json", dims_doc)
        buf = io.StringIO()
        code = None
        with contextlib.redirect_stdout(buf):
            argv = sys.argv
            sys.argv = ["check_dims.py", self.dir]
            try:
                check_dims.main()
            except SystemExit as e:
                code = e.code if isinstance(e.code, int) else 1
            finally:
                sys.argv = argv
        return code, buf.getvalue()

    def test_clean_pass(self):
        code, out = self.run_main({"dimensions": [dim("大区"), dim("省份", values=["杭"])]})
        self.assertIsNone(code, out)
        self.assertIn("校验通过", out)

    def test_duplicate_name(self):
        code, out = self.run_main({"dimensions": [dim("大区"), dim("大区")]})
        self.assertEqual(code, 1)
        self.assertIn("重名", out)

    def test_synonym_collision_between_dims(self):
        code, out = self.run_main({"dimensions": [dim("销售大区", synonyms=["区域"]),
                                                  dim("战区", synonyms=["区域"])]})
        self.assertEqual(code, 1)
        self.assertIn("撞车", out)

    def test_collision_with_metric(self):
        write_json(self.dir, "metrics.json",
                   {"metrics": [{"name": "门店", "formula": "sum([x])"}]})
        code, out = self.run_main({"dimensions": [dim("门店")]})
        self.assertEqual(code, 1)
        self.assertIn("指标", out)

    def test_value_alias_dangling_target(self):
        code, out = self.run_main({"dimensions": [
            dim("大区", values=["华东"], valueAliases={"华东区": "华东大区"})]})
        self.assertEqual(code, 1)
        self.assertIn("values 未收录", out)

    def test_value_alias_ok(self):
        code, out = self.run_main({"dimensions": [
            dim("大区", values=["华东"], valueAliases={"华东区": "华东"})]})
        self.assertIsNone(code, out)

    def test_shared_value_warns_not_blocks(self):
        code, out = self.run_main({"dimensions": [dim("销售大区", values=["华东"]),
                                                  dim("财务大区", values=["华东"])]})
        self.assertIsNone(code, out)
        self.assertIn("跨维度重叠", out)

    def test_similar_values_warn(self):
        code, out = self.run_main({"dimensions": [dim("大区", values=["华东", "华东区"])]})
        self.assertIsNone(code, out)
        self.assertIn("互为包含", out)

    def test_metric_dims_coverage_warn(self):
        write_json(self.dir, "metrics.json",
                   {"metrics": [{"name": "净收入", "formula": "sum([x])", "dims": ["渠道"]}]})
        code, out = self.run_main({"dimensions": [dim("大区")]})
        self.assertIsNone(code, out)
        self.assertIn("未在 dimensions.json 收编", out)


class TestSeed(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        write_json(self.dir, "cards-raw.json", {
            "_meta": {},
            "看板A": {"cards": [{"name": "c1", "dims": ["大区", "销售大区"], "filterDetails": []},
                                {"name": "sel", "cdType": "SELECTOR", "dims": [],
                                 "filterDetails": [{"field": "月份"}]}]}})
        write_json(self.dir, "card-data/_sample_index.json", {
            "看板A__c1": {"profile": {"大区": {"type": "text", "distinct": 2,
                                              "enum": ["华东", "华南"]},
                                     "销售额": {"type": "number", "min": 1, "max": 9}}}})

    def test_seed_generates(self):
        argv = sys.argv
        sys.argv = ["check_dims.py", self.dir, "--seed-dims"]
        with contextlib.redirect_stdout(io.StringIO()):
            try:
                check_dims.main()
            finally:
                sys.argv = argv
        with open(os.path.join(self.dir, "dimensions-seed.json"), encoding="utf-8") as f:
            seed = json.load(f)
        names = {d["name"] for d in seed["dimensions"]}
        self.assertEqual(names, {"大区", "销售大区", "月份"})
        by_name = {d["name"]: d for d in seed["dimensions"]}
        self.assertEqual(by_name["大区"]["values"], ["华东", "华南"])
        self.assertEqual(by_name["月份"]["values"], [])  # 无枚举画像则为空，待第 4 步补
        self.assertIn("大区", by_name["销售大区"]["similarTo"])  # 名称包含 → 易混建议
        self.assertIn("销售大区", by_name["大区"]["similarTo"])

    def test_seed_requires_cards_raw(self):
        empty = tempfile.mkdtemp()
        argv = sys.argv
        sys.argv = ["check_dims.py", empty, "--seed-dims"]
        with self.assertRaises(SystemExit):
            with contextlib.redirect_stdout(io.StringIO()):
                check_dims.main()
        sys.argv = argv


if __name__ == '__main__':
    unittest.main()
