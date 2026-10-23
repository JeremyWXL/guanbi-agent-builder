#!/usr/bin/env python3
"""extract_card_skeletons.py 单测：选中卡抽取、骨架生成、公式 TODO、错误路径。"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "extract_card_skeletons.py")
FIXTURE = os.path.join(
    os.path.dirname(os.path.dirname(HERE)), "_preview", "_sandbox-v4.9.1")


def card(cd_id, name, ctype="PIE", ds="ds1", dims=None, measures=None,
         filters=None, dynamic=None):
    return {
        "cdId": cd_id, "name": name, "type": ctype, "dsId": ds,
        "dims": dims or [], "measures": measures or [],
        "filters": filters or [], "filterDetails": [],
        "dynamicParams": dynamic or [], "unitHints": {},
    }


class ExtractTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_cards(self, pages, name="cards-raw.json"):
        path = os.path.join(self.tmp, name)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(pages, f, ensure_ascii=False)
        return path

    def run_script(self, *args):
        return subprocess.run([sys.executable, SCRIPT, *args],
                              capture_output=True, text=True, timeout=60)

    def test_pie_skeleton_and_outputs(self):
        self.write_cards({"看板A": {"pgId": "pg1", "cards": [
            card("c1", "杯型占比", "PIE", dims=["杯型名称"],
                 measures=[{"name": "销售杯数", "alias": "销售杯数",
                            "aggrType": "SUM"}],
                 filters=["日期"]),
        ]}})
        out = os.path.join(self.tmp, "out")
        r = self.run_script(self.tmp, "--cdIds", "c1", "-o", out)
        self.assertEqual(r.returncode, 0, r.stderr)
        skel = os.path.join(out, "card-skeletons")
        files = os.listdir(skel)
        self.assertEqual(len(files), 1)
        text = open(os.path.join(skel, files[0]), encoding="utf-8").read()
        self.assertIn("createCard(ChartType.PIE", text)
        self.assertIn(".setId(", text)
        self.assertIn('addRow(f("杯型名称"))', text)
        self.assertIn("AggrType.SUM", text)
        self.assertIn("setDescription", text)
        doc = json.load(open(os.path.join(out, "card-reuse.json"), encoding="utf-8"))
        self.assertEqual(doc["meta"]["count"], 1)
        self.assertEqual(doc["cards"][0]["cdId"], "c1")
        self.assertTrue(os.path.exists(os.path.join(out, "card-reuse-checklist.md")))

    def test_formula_measure_gets_todo_not_fake_metric(self):
        self.write_cards({"看板A": {"pgId": "pg1", "cards": [
            card("c2", "趋势", "STACKED_COLUMN", dims=["月"],
                 measures=[{"name": "指标", "alias": "指标", "aggrType": None,
                            "formula": "case when x then sum(y) end"}]),
        ]}})
        out = os.path.join(self.tmp, "out")
        r = self.run_script(self.tmp, "--cdIds", "c2", "-o", out)
        self.assertEqual(r.returncode, 0, r.stderr)
        files = os.listdir(os.path.join(out, "card-skeletons"))
        text = open(os.path.join(out, "card-skeletons", files[0]), encoding="utf-8").read()
        self.assertIn("TODO 计算字段", text)
        self.assertIn("case when x then sum(y) end", text)
        self.assertNotIn('addMetric(f("指标"', text)

    def test_dataset_alias_and_page_filter(self):
        self.write_cards({
            "看板A": {"pgId": "pg1", "cards": [card("c1", "A卡")]},
            "看板B": {"pgId": "pg2", "cards": [card("c2", "B卡")]},
        })
        out = os.path.join(self.tmp, "out")
        r = self.run_script(self.tmp, "--cdIds", "c1", "--page", "看板A",
                            "--dataset-alias", "DS1", "-o", out)
        self.assertEqual(r.returncode, 0, r.stderr)
        files = os.listdir(os.path.join(out, "card-skeletons"))
        text = open(os.path.join(out, "card-skeletons", files[0]), encoding="utf-8").read()
        self.assertIn(".bindDataset(DS1)", text)

    def test_missing_cdid_exits_2(self):
        self.write_cards({"看板A": {"pgId": "pg1", "cards": [card("c1", "A卡")]}})
        r = self.run_script(self.tmp, "--cdIds", "nope", "-o", os.path.join(self.tmp, "out"))
        self.assertEqual(r.returncode, 2)
        self.assertIn("nope", r.stderr)

    def test_missing_cards_raw_exits_2(self):
        r = self.run_script(self.tmp, "--cdIds", "c1", "-o", os.path.join(self.tmp, "out"))
        self.assertEqual(r.returncode, 2)
        self.assertIn("cards-raw.json", r.stderr)

    def test_unknown_page_exits_2(self):
        self.write_cards({"看板A": {"pgId": "pg1", "cards": [card("c1", "A卡")]}})
        r = self.run_script(self.tmp, "--cdIds", "c1", "--page", "不存在",
                            "-o", os.path.join(self.tmp, "out"))
        self.assertEqual(r.returncode, 2)
        self.assertIn("未找到看板", r.stderr)

    @unittest.skipUnless(os.path.exists(os.path.join(FIXTURE, "cards-raw.json")),
                         "真实夹具不存在")
    def test_real_fixture_runs(self):
        out = os.path.join(self.tmp, "out")
        r = self.run_script(FIXTURE, "--cdIds",
                            "m9f01f860542942aabec806b,o0de9755099914d23ad4e3ab",
                            "-o", out)
        self.assertEqual(r.returncode, 0, r.stderr)
        doc = json.load(open(os.path.join(out, "card-reuse.json"), encoding="utf-8"))
        self.assertEqual(doc["meta"]["count"], 2)
        names = [c["name"] for c in doc["cards"]]
        self.assertIn("商品杯型占比", names)


if __name__ == "__main__":
    unittest.main()
