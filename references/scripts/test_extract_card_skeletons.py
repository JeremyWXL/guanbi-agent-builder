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

    @staticmethod
    def read_text(path):
        with open(path, encoding="utf-8") as f:
            return f.read()

    @staticmethod
    def read_json(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)

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
        text = self.read_text(os.path.join(skel, files[0]))
        self.assertIn("createCard(ChartType.PIE", text)
        self.assertIn(".setId(", text)
        self.assertIn('addRow(f("杯型名称"))', text)
        self.assertIn("AggrType.SUM", text)
        self.assertIn("setDescription", text)
        doc = self.read_json(os.path.join(out, "card-reuse.json"))
        self.assertEqual(doc["meta"]["count"], 1)
        self.assertEqual(doc["cards"][0]["cdId"], "c1")
        self.assertTrue(os.path.exists(os.path.join(out, "card-reuse-checklist.md")))

    def test_scroll_table_is_preserved_and_unknown_type_uses_valid_fallback(self):
        self.write_cards({"看板A": {"pgId": "pg1", "cards": [
            card("c1", "滚动表", "SCROLL_TABLE"), card("c2", "未知表", "NEW_UNKNOWN")]}})
        out = os.path.join(self.tmp, "out")
        r = self.run_script(self.tmp, "--cdIds", "c1,c2", "-o", out)
        self.assertEqual(r.returncode, 0, r.stderr)
        texts = [self.read_text(os.path.join(out, "card-skeletons", name))
                 for name in sorted(os.listdir(os.path.join(out, "card-skeletons")))]
        self.assertIn("ChartType.SCROLL_TABLE", texts[0])
        self.assertIn("ChartType.DETAIL_TABLE", texts[1])
        self.assertNotIn("ChartType.TABLE", "\n".join(texts))

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
        text = self.read_text(os.path.join(out, "card-skeletons", files[0]))
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
        text = self.read_text(os.path.join(out, "card-skeletons", files[0]))
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

    def test_multi_dataset_uses_distinct_aliases(self):
        self.write_cards({"看板A": {"pgId": "pg1", "cards": [
            card("c1", "A卡", ds="ds1"), card("c2", "B卡", ds="ds2", dims=["区域"])]}})
        out = os.path.join(self.tmp, "out")
        r = self.run_script(self.tmp, "--cdIds", "c1,c2", "-o", out)
        self.assertEqual(r.returncode, 0, r.stderr)
        texts = {}
        for name in os.listdir(os.path.join(out, "card-skeletons")):
            with open(os.path.join(out, "card-skeletons", name), encoding="utf-8") as f:
                texts[name] = f.read()
        self.assertIn(".bindDataset(DS1)", texts[next(n for n in texts if "card_01" in n)])
        second = texts[next(n for n in texts if "card_02" in n)]
        self.assertIn(".bindDataset(DS2)", second)
        self.assertIn('addRow(field(DS2, "区域"))', second)
        self.assertNotIn('addRow(f("区域"))', second)
        with open(os.path.join(out, "card-reuse.json"), encoding="utf-8") as f:
            doc = json.load(f)
        self.assertEqual(doc["meta"]["datasetAliases"], {"ds1": "DS1", "ds2": "DS2"})
        self.assertIn("--alias DS1,DS2", doc["meta"]["initCommand"])
        with open(os.path.join(out, "card-reuse-checklist.md"), encoding="utf-8") as f:
            checklist = f.read()
        self.assertIn("--alias DS1,DS2", checklist)

    def test_explicit_multi_dataset_aliases(self):
        self.write_cards({"看板A": {"pgId": "pg1", "cards": [
            card("c1", "A卡", ds="ds1"), card("c2", "B卡", ds="ds2")]}})
        out = os.path.join(self.tmp, "out")
        r = self.run_script(self.tmp, "--cdIds", "c1,c2",
                            "--dataset-alias", "ORDERS,SALES", "-o", out)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(os.path.join(out, "card-reuse.json"), encoding="utf-8") as f:
            doc = json.load(f)
        self.assertEqual(doc["meta"]["datasetAliases"],
                         {"ds1": "ORDERS", "ds2": "SALES"})

    def test_multi_dataset_alias_count_mismatch_exits_2(self):
        self.write_cards({"看板A": {"pgId": "pg1", "cards": [
            card("c1", "A卡", ds="ds1"), card("c2", "B卡", ds="ds2")]}})
        r = self.run_script(self.tmp, "--cdIds", "c1,c2",
                            "--dataset-alias", "ONLY", "-o", os.path.join(self.tmp, "out"))
        self.assertEqual(r.returncode, 2)
        self.assertIn("需要 2 个逗号分隔的变量名", r.stderr)

    def test_missing_dataset_is_rejected_before_generation(self):
        self.write_cards({"看板A": {"pgId": "pg1", "cards": [card("c1", "A卡", ds="")]}})
        out = os.path.join(self.tmp, "out")
        r = self.run_script(self.tmp, "--cdIds", "c1", "-o", out)
        self.assertEqual(r.returncode, 2)
        self.assertIn("缺少 dsId", r.stderr)

    def test_duplicate_or_invalid_aliases_rejected(self):
        self.write_cards({"看板A": {"pgId": "pg1", "cards": [
            card("c1", "A卡", ds="ds1"), card("c2", "B卡", ds="ds2")]}})
        for aliases in ("DS1,DS1", "DS-1,DS2"):
            r = self.run_script(self.tmp, "--cdIds", "c1,c2",
                                "--dataset-alias", aliases, "-o", os.path.join(self.tmp, "out"))
            self.assertEqual(r.returncode, 2, aliases)

    def test_rerun_removes_stale_skeletons(self):
        self.write_cards({"看板A": {"pgId": "pg1", "cards": [
            card("c1", "A卡"), card("c2", "B卡")]}})
        out = os.path.join(self.tmp, "out")
        self.assertEqual(self.run_script(self.tmp, "--cdIds", "c1,c2", "-o", out).returncode, 0)
        r = self.run_script(self.tmp, "--cdIds", "c2", "-o", out)
        self.assertEqual(r.returncode, 0, r.stderr)
        files = os.listdir(os.path.join(out, "card-skeletons"))
        self.assertEqual(len(files), 1)
        self.assertIn("card_01", files[0])

    def test_duplicate_cdids_are_deduped(self):
        self.write_cards({"看板A": {"pgId": "pg1", "cards": [card("c1", "A卡")]}})
        out = os.path.join(self.tmp, "out")
        r = self.run_script(self.tmp, "--cdIds", "c1,c1", "-o", out)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(os.listdir(os.path.join(out, "card-skeletons"))), 1)
        self.assertIn("已去重", r.stderr)
        with open(os.path.join(out, "card-reuse.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["meta"]["count"], 1)

    def test_multiline_formula_stays_in_comment(self):
        self.write_cards({"看板A": {"pgId": "pg1", "cards": [
            card("c1", "多行公式卡", measures=[{
                "name": "利润率", "alias": "利润率", "aggrType": None,
                "formula": "SUM([利润])\n/ SUM([销售额])"}])]}})
        out = os.path.join(self.tmp, "out")
        r = self.run_script(self.tmp, "--cdIds", "c1", "-o", out)
        self.assertEqual(r.returncode, 0, r.stderr)
        path = os.path.join(out, "card-skeletons",
                            os.listdir(os.path.join(out, "card-skeletons"))[0])
        with open(path, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("SUM([利润]) / SUM([销售额])", text)
        self.assertNotIn("\n/ SUM", text)
        if shutil.which("node"):
            checked = subprocess.run(["node", "--check", path],
                                     capture_output=True, text=True)
            self.assertEqual(checked.returncode, 0, checked.stderr)

    def test_map_without_measures_gets_colorby_todo(self):
        self.write_cards({"看板A": {"pgId": "pg1", "cards": [
            card("c1", "地图卡", ctype="BASIC_MAP", dims=["省份"])]}})
        out = os.path.join(self.tmp, "out")
        r = self.run_script(self.tmp, "--cdIds", "c1", "-o", out)
        self.assertEqual(r.returncode, 0, r.stderr)
        path = os.path.join(out, "card-skeletons",
                            os.listdir(os.path.join(out, "card-skeletons"))[0])
        with open(path, encoding="utf-8") as f:
            self.assertIn("缺少 colorBy", f.read())

    @unittest.skipUnless(os.path.exists(os.path.join(FIXTURE, "cards-raw.json")),
                         "真实夹具不存在")
    def test_real_fixture_runs(self):
        out = os.path.join(self.tmp, "out")
        r = self.run_script(FIXTURE, "--cdIds",
                            "m9f01f860542942aabec806b,o0de9755099914d23ad4e3ab",
                            "-o", out)
        self.assertEqual(r.returncode, 0, r.stderr)
        doc = self.read_json(os.path.join(out, "card-reuse.json"))
        self.assertEqual(doc["meta"]["count"], 2)
        names = [c["name"] for c in doc["cards"]]
        self.assertIn("商品杯型占比", names)


if __name__ == "__main__":
    unittest.main()
