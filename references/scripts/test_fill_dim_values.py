#!/usr/bin/env python3
"""fill_dim_values.py 单测：空 values 从采样画像机械回填、已有值不动、
精确匹配、备份生成、seed 回退、画像缺失降级；
--full 全量枚举回填（mock run_sql 的 subprocess，不真调 guancli）：
并集不删已有值、超上限走 note、字段匹配不上跳过、查询失败降级不阻断"""
import contextlib, io, json, os, re, subprocess, sys, tempfile, unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fill_dim_values

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


DATASETS_RAW_FULL = {
    "_meta": {"dsFormulas": {"ds1": {"dsName": "fact_sales", "virtualColumns": []}}},
    "fact_sales": {
        "dsId": "ds1",
        "columns": [
            {"name": "store_id", "metaType": "DIM", "fdType": "STRING"},
            {"name": "sku_id", "metaType": "DIM", "fdType": "STRING"},
            {"name": "biz_date", "metaType": "DIM", "fdType": "DATE"},
            {"name": "amount", "metaType": "METRIC", "fdType": "DOUBLE"},
        ],
    },
}

FULL_DIMS = {"dimensions": [
    {"name": "store_id", "field": "store_id", "values": ["S001"], "note": "用户确认备注"},
    {"name": "sku_id", "field": "sku_id", "values": []},
    {"name": "biz_date", "field": "biz_date", "values": []},
    {"name": "region", "field": "region", "values": []},   # 数据集无此物理字段
]}


class FullModeTest(unittest.TestCase):
    """--full 全量枚举回填：mock fill_dim_values 调 run_sql 的 subprocess.run"""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        write_json(self.dir, "dimensions.json", FULL_DIMS)
        write_json(self.dir, "datasets-raw.json", DATASETS_RAW_FULL)
        self.calls = []

    def fake_run(self, counts, enums, fail=False):
        """counts/enums 以 (dsId, 列名) 为键；fail=True 模拟 run_sql 整体不可用"""
        def _run(cmd, **kw):
            ds_id, sql = cmd[2], cmd[3]
            self.calls.append(sql)
            m = mock.Mock()
            if fail:
                m.returncode = 1
                m.stdout = ""
                return m
            col = re.search(r"`([^`]+)`", sql).group(1)
            m.returncode = 0
            if "COUNT(DISTINCT" in sql:
                m.stdout = json.dumps([{"n": str(counts[(ds_id, col)])}])
            else:
                m.stdout = json.dumps([{col: v} for v in enums[(ds_id, col)]])
            return m
        return _run

    def run_full(self, side_effect):
        argv = sys.argv
        sys.argv = ["fill_dim_values.py", self.dir, "--full"]
        buf = io.StringIO()
        code = 0
        with contextlib.redirect_stdout(buf), \
                mock.patch.object(fill_dim_values.subprocess, "run", side_effect=side_effect):
            try:
                fill_dim_values.main()
            except SystemExit as e:
                code = e.code
            finally:
                sys.argv = argv
        return code, buf.getvalue()

    def by_name(self):
        doc = read_json(self.dir, "dimensions.json")
        return {d["name"]: d for d in doc["dimensions"]}

    def test_full_unions_and_keeps_existing(self):
        counts = {("ds1", "store_id"): 3, ("ds1", "sku_id"): 2}
        enums = {("ds1", "store_id"): ["S001", "S002", "S003"],
                 ("ds1", "sku_id"): ["R100-S", "R100-M"]}
        code, out = self.run_full(self.fake_run(counts, enums))
        self.assertEqual(code, 0)
        by = self.by_name()
        # 并集：已有值 S001 不丢且在序，新值追加
        self.assertEqual(by["store_id"]["values"], ["S001", "S002", "S003"])
        self.assertEqual(by["sku_id"]["values"], ["R100-S", "R100-M"])
        self.assertEqual(by["store_id"]["note"], "用户确认备注")  # 已有 note 不动
        self.assertTrue(any(f.startswith("dimensions.json.bak-fill-")
                            for f in os.listdir(self.dir)))
        # 日期型字段不做成员枚举（不发 SQL）
        self.assertFalse(any("biz_date" in s for s in self.calls))

    def test_full_over_cap_writes_note(self):
        counts = {("ds1", "store_id"): 12000, ("ds1", "sku_id"): 2}
        enums = {("ds1", "sku_id"): ["A", "B"]}
        code, out = self.run_full(self.fake_run(counts, enums))
        self.assertEqual(code, 0)
        by = self.by_name()
        self.assertEqual(by["store_id"]["values"], ["S001"])  # 超上限不塞爆 values
        self.assertIn("取值未全量枚举（实际 12000 个），消歧前先 SQL 枚举确认",
                      by["store_id"]["note"])
        self.assertIn("用户确认备注", by["store_id"]["note"])  # 追加不覆盖
        # 超上限维度不发 SELECT DISTINCT（COUNT 预检拦截）
        self.assertFalse(any("DISTINCT `store_id` FROM" in s for s in self.calls))

    def test_full_unmatched_field_skipped(self):
        counts = {("ds1", "store_id"): 2, ("ds1", "sku_id"): 1}
        enums = {("ds1", "store_id"): ["S001"], ("ds1", "sku_id"): ["A"]}
        code, out = self.run_full(self.fake_run(counts, enums))
        self.assertEqual(code, 0)
        by = self.by_name()
        self.assertEqual(by["region"]["values"], [])
        self.assertFalse(any("region" in s for s in self.calls))
        self.assertIn("region", out)  # 匹配不上有提示

    def test_full_sql_failure_degrades(self):
        code, out = self.run_full(self.fake_run({}, {}, fail=True))
        self.assertEqual(code, 0)  # 失败不阻断
        by = self.by_name()
        self.assertEqual(by["store_id"]["values"], ["S001"])  # values 保持原样
        self.assertIn("⚠️", out)

    def test_full_idempotent_second_run_no_write(self):
        counts = {("ds1", "store_id"): 12000, ("ds1", "sku_id"): 2}
        enums = {("ds1", "sku_id"): ["A", "B"]}
        code, _ = self.run_full(self.fake_run(counts, enums))
        self.assertEqual(code, 0)
        first = read_json(self.dir, "dimensions.json")
        baks = [f for f in os.listdir(self.dir) if f.startswith("dimensions.json.bak-fill-")]
        self.assertEqual(len(baks), 1)
        # 第二次跑：零改动 → 不写回、不再备份、note 不重复追加
        code, out = self.run_full(self.fake_run(counts, enums))
        self.assertEqual(code, 0)
        self.assertEqual(read_json(self.dir, "dimensions.json"), first)
        self.assertEqual([f for f in os.listdir(self.dir)
                          if f.startswith("dimensions.json.bak-fill-")], baks)
        self.assertIn("无需回填", out)


if __name__ == "__main__":
    unittest.main()
