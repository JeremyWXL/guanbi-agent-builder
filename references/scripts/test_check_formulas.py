#!/usr/bin/env python3
"""check_formulas.py 的单测：v4.9 PARAM_DEPENDENT 分类（含 DYNAMIC_PARAMS 的公式
优先于 ROW_LOGIC 命中、禁止 SQL 内联）+ seed 种子 safety 透传"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_formulas as cf


class TestClassifyParamDependent(unittest.TestCase):
    def test_dynamic_params_hits_param_dependent(self):
        cls, _ = cf.classify("case [DYNAMIC_PARAMS.指标选取] when '营业额' then sum([金额]) end")
        self.assertEqual(cls, "PARAM_DEPENDENT")

    def test_param_beats_row_logic(self):
        # case when 行级逻辑与参数引用同时出现时，参数依赖优先（取值随参数变化，无静态口径）
        cls, _ = cf.classify("case when instr([DYNAMIC_PARAMS.渠道指标],'收入')>0 then [收入] else null end")
        self.assertEqual(cls, "PARAM_DEPENDENT")

    def test_param_beats_free_sum(self):
        cls, _ = cf.classify("if([价格]>[DYNAMIC_PARAMS.阈值],[销量],0)")
        self.assertEqual(cls, "PARAM_DEPENDENT")

    def test_plain_formulas_unaffected(self):
        self.assertEqual(cf.classify("sum([销售额])/sum([目标])")[0], "FREE")
        self.assertEqual(cf.classify("case when [区域]='华东' then [金额] end")[0], "ROW_LOGIC")

    def test_unknown_formula_is_not_free(self):
        cls, note = cf.classify("approx_count_distinct([客户])")
        self.assertNotEqual(cls, "FREE")
        self.assertNotIn("仅含可加", note)


class TestMainParamDependent(unittest.TestCase):
    """main() 集成：含参数公式进 formulas.json 标 PARAM_DEPENDENT，seed 透传 safety"""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        raw = {
            "看板A": {"pgId": "p1", "cards": [
                {"name": "趋势卡", "cdId": "c1", "filterDetails": [], "dims": ["月份"],
                 "measures": [{"name": "指标", "alias": "", "fdId": "f1",
                               "formula": "case [DYNAMIC_PARAMS.指标选取] when '营业额' then sum([金额]) else null end"}]},
                {"name": "汇总卡", "cdId": "c2", "filterDetails": [], "dims": [],
                 "measures": [{"name": "销售额", "alias": "", "fdId": "f2",
                               "formula": "sum([金额])"}]},
            ]},
            "_meta": {"dsFormulas": {}},
        }
        with open(os.path.join(self.dir, "cards-raw.json"), "w", encoding="utf-8") as f:
            json.dump(raw, f, ensure_ascii=False)

    def run_main(self, extra=()):
        old = sys.argv
        sys.argv = ["check_formulas.py", self.dir, *extra]
        try:
            cf.main()
        finally:
            sys.argv = old

    def test_formulas_json_classification(self):
        self.run_main()
        with open(os.path.join(self.dir, "formulas.json"), encoding="utf-8") as f:
            doc = json.load(f)
        by_name = {m["name"]: m for m in doc["metrics"]}
        self.assertEqual(by_name["指标"]["classification"], "PARAM_DEPENDENT")
        self.assertIn("禁止内联", by_name["指标"]["classificationNote"])
        self.assertEqual(by_name["销售额"]["classification"], "FREE")
        self.assertEqual(doc["_meta"]["classification"].get("PARAM_DEPENDENT"), 1)

    def test_seed_metrics_safety(self):
        self.run_main(extra=["--seed-metrics"])
        with open(os.path.join(self.dir, "metrics-seed.json"), encoding="utf-8") as f:
            seed = json.load(f)
        by_name = {m["name"]: m for m in seed["metrics"]}
        self.assertEqual(by_name["指标"]["safety"], "PARAM_DEPENDENT")
        self.assertIn("DYNAMIC_PARAMS", by_name["指标"]["formula"])

    def test_plain_aliases_keep_conflicts_and_seed(self):
        with open(os.path.join(self.dir, "cards-raw.json"), encoding="utf-8") as f:
            raw = json.load(f)
        raw["看板A"]["cards"][0]["measures"] = [
            {"name": "金额A", "alias": "销售额", "formula": "sum([A])", "advType": ""}]
        raw["看板A"]["cards"][1]["measures"] = [
            {"name": "金额B", "alias": "销售额", "formula": "sum([B])", "advType": ""}]
        with open(os.path.join(self.dir, "cards-raw.json"), "w", encoding="utf-8") as f:
            json.dump(raw, f, ensure_ascii=False)
        self.run_main(extra=["--seed-metrics"])
        with open(os.path.join(self.dir, "formulas.json"), encoding="utf-8") as f:
            formulas = json.load(f)
        self.assertEqual(len(formulas["conflicts"]), 1)
        with open(os.path.join(self.dir, "metrics-seed.json"), encoding="utf-8") as f:
            seed = json.load(f)
        self.assertIn("销售额", {m["name"] for m in seed["metrics"]})


if __name__ == "__main__":
    unittest.main()
