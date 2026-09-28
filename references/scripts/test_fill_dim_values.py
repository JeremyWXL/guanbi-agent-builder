#!/usr/bin/env python3
"""fill_dim_values.py 单测：空 values 从采样画像机械回填、已有值不动、
精确匹配、备份生成、seed 回退、画像缺失降级"""
import json, os, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "fill_dim_values.py")


def write_json(workdir, rel, doc):
    fp = os.path.join(workdir, rel)
    os.makedirs(os.path.dirname(fp), exist_ok=True)
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)


def read_json(workdir, rel):
    with open(os.path.join(workdir, rel), encoding="utf-8") as f:
        return json.load(f)


SAMPLE_INDEX = {
    "页一__卡A": {"profile": {
        "展示渠道": {"type": "text", "distinct": 5, "enum": ["淘系", "京东系", "抖音"]},
        "净收入": {"type": "number", "min": 1, "max": 99},
    }},
    "页一__卡B": {"profile": {
        "展示渠道": {"type": "text", "distinct": 5, "enum": ["京东系", "快手"]},
        "统计月份": {"type": "text", "distinct": 3, "enum": ["2026-06", "2026-07"]},
    }},
}

DIMS = {"dimensions": [
    {"name": "展示渠道", "field": "展示渠道", "values": []},
    {"name": "统计月份", "field": "统计月份", "values": ["2026-05"]},  # 已确认，不动
    {"name": "展示BU", "field": "展示BU", "values": []},              # 画像无此列
]}


class FillDimValuesTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def run_script(self):
        return subprocess.run([sys.executable, SCRIPT, self.dir],
                              capture_output=True, text=True)

    def test_fills_empty_values_and_merges_across_cards(self):
        write_json(self.dir, "dimensions.json", DIMS)
        write_json(self.dir, "card-data/_sample_index.json", SAMPLE_INDEX)
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        doc = read_json(self.dir, "dimensions.json")
        by_name = {d["name"]: d for d in doc["dimensions"]}
        # 跨卡片合并去重：淘系/京东系/抖音 + 快手
        self.assertEqual(by_name["展示渠道"]["values"], ["淘系", "京东系", "抖音", "快手"])
        # 已确认值不动
        self.assertEqual(by_name["统计月份"]["values"], ["2026-05"])
        # 画像无匹配列保持空
        self.assertEqual(by_name["展示BU"]["values"], [])
        # 备份生成
        self.assertTrue(any(f.startswith("dimensions.json.bak-fill-") for f in os.listdir(self.dir)))
        self.assertIn("展示BU", r.stdout)  # 无匹配列有提示

    def test_falls_back_to_seed(self):
        write_json(self.dir, "dimensions-seed.json", DIMS)
        write_json(self.dir, "card-data/_sample_index.json", SAMPLE_INDEX)
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        doc = read_json(self.dir, "dimensions-seed.json")
        self.assertEqual(doc["dimensions"][0]["values"], ["淘系", "京东系", "抖音", "快手"])

    def test_dataset_profile_as_source(self):
        write_json(self.dir, "dimensions.json", DIMS)
        write_json(self.dir, "datasets-raw.json", {
            "ds一": {"sample": {"profile": {"展示BU": {"enum": ["BU1", "BU2"]}}}},
        })
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        doc = read_json(self.dir, "dimensions.json")
        by_name = {d["name"]: d for d in doc["dimensions"]}
        self.assertEqual(by_name["展示BU"]["values"], ["BU1", "BU2"])

    def test_no_archive_exit2(self):
        r = self.run_script()
        self.assertEqual(r.returncode, 2)

    def test_no_enum_data_degrades(self):
        write_json(self.dir, "dimensions.json", DIMS)
        r = self.run_script()
        self.assertEqual(r.returncode, 0)
        self.assertIn("没有可用枚举值", r.stdout)


if __name__ == "__main__":
    unittest.main()
