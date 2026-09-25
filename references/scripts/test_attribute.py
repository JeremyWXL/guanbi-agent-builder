#!/usr/bin/env python3
"""
attribute.py 最小单测：数值解析、加法拆解闭环与方向约定、Shapley 乘法拆解
（闭环/对称性/零起步因子/因子个数闸门）。
运行: python3 -m unittest discover -s references/scripts -p 'test_*.py' -v
不触网：纯函数直接导入，CLI 级用临时文件 + subprocess。
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import attribute

SCRIPT = os.path.abspath(attribute.__file__)


def run_cli(*args):
    return subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True)


class TestParseNum(unittest.TestCase):
    def test_plain_and_thousands(self):
        self.assertEqual(attribute.parse_num("1234"), 1234.0)
        self.assertEqual(attribute.parse_num("1,234.5"), 1234.5)
        self.assertEqual(attribute.parse_num("1，234"), 1234.0)  # 全角逗号
        self.assertEqual(attribute.parse_num(" -34 "), -34.0)

    def test_percent_to_decimal(self):
        self.assertAlmostEqual(attribute.parse_num("35%"), 0.35)
        self.assertAlmostEqual(attribute.parse_num("103.6%"), 1.036)

    def test_chinese_units(self):
        self.assertEqual(attribute.parse_num("71万"), 710000.0)
        self.assertEqual(attribute.parse_num("1.2亿"), 120000000.0)
        self.assertEqual(attribute.parse_num("-3.5万"), -35000.0)

    def test_accounting_negative(self):
        self.assertEqual(attribute.parse_num("(123)"), -123.0)
        self.assertEqual(attribute.parse_num("(1,234.5)"), -1234.5)

    def test_passthrough(self):
        self.assertEqual(attribute.parse_num(42), 42.0)
        self.assertEqual(attribute.parse_num(3.5), 3.5)

    def test_errors_with_context(self):
        for bad in ("", None, "abc"):
            with self.assertRaises(ValueError):
                attribute.parse_num(bad)
        with self.assertRaises(ValueError) as cm:
            attribute.parse_num("abc", "华东 的 收入")
        self.assertIn("华东 的 收入", str(cm.exception))


class TestFmtNum(unittest.TestCase):
    def test_integer_thousands(self):
        self.assertEqual(attribute.fmt_num(1234567), "1,234,567")
        self.assertEqual(attribute.fmt_num(-180000), "-180,000")

    def test_decimal_trimmed(self):
        self.assertEqual(attribute.fmt_num(0.35), "0.35")
        self.assertEqual(attribute.fmt_num(None), "—")


class TestShapley(unittest.TestCase):
    @staticmethod
    def prod(xs):
        p = 1.0
        for x in xs:
            p *= x
        return p

    def test_two_factor_inactive_factor_zero(self):
        # 店数不变、单店业绩 0.71→0.37：全部贡献归单店业绩
        contrib = attribute.shapley_contributions([100, 0.71], [100, 0.37])
        self.assertAlmostEqual(contrib[0], 0.0)
        self.assertAlmostEqual(contrib[1], -34.0)

    def test_closure_3_and_4_factors(self):
        for base, curr in [([2, 3, 4], [3, 3, 5]), ([2, 3, 4, 5], [3, 4, 2, 6])]:
            contrib = attribute.shapley_contributions(base, curr)
            self.assertAlmostEqual(sum(contrib), self.prod(curr) - self.prod(base), places=9)

    def test_order_symmetry(self):
        # 打乱因子顺序重算，同一因子的贡献必须不变（Shapley 与排列顺序无关）
        base, curr = [2, 3, 4], [3, 5, 2]
        c1 = attribute.shapley_contributions(base, curr)
        order = [2, 0, 1]
        c2 = attribute.shapley_contributions([base[i] for i in order], [curr[i] for i in order])
        for idx, i in enumerate(order):
            self.assertAlmostEqual(c2[idx], c1[i])

    def test_zero_start_factor(self):
        # 新店 0→10、另一因子不变：全部贡献归新店因子（Shapley 天然处理 0 起步）
        contrib = attribute.shapley_contributions([0, 5], [10, 5])
        self.assertAlmostEqual(contrib[0], 50.0)
        self.assertAlmostEqual(contrib[1], 0.0)


class TestAddCLI(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.csv = os.path.join(self.dir, "data.csv")
        with open(self.csv, "w", encoding="utf-8") as f:
            f.write("渠道,上月收入,本月收入\n团购,71万,37万\nKA,50万,66万\n")

    def test_add_closure_top_and_direction(self):
        r = run_cli("add", self.csv, "渠道", "上月收入", "本月收入", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        doc = json.loads(r.stdout)
        self.assertEqual(doc["total_change"], -180000.0)
        self.assertTrue(doc["closure_check"]["passed"])
        members = {m["dim"]: m for m in doc["members"]}
        top = [m for m in doc["members"] if m["is_top"]]
        self.assertEqual(len(top), 1)
        self.assertEqual(top[0]["dim"], "团购")
        # 总变化为负：同向下降的团购贡献率为正且标记拖累；反向增长的 KA 贡献率为负
        self.assertAlmostEqual(members["团购"]["contribution_rate"], -340000 / -180000)
        self.assertEqual(members["团购"]["direction"], "拖累↓")
        self.assertLess(members["KA"]["contribution_rate"], 0)
        self.assertEqual(members["KA"]["direction"], "拉动↑")
        # 贡献率合计闭环 100%
        self.assertAlmostEqual(sum(m["contribution_rate"] for m in doc["members"]), 1.0)

    def test_add_needs_two_members(self):
        single = os.path.join(self.dir, "single.csv")
        with open(single, "w", encoding="utf-8") as f:
            f.write("渠道,上月,本月\n团购,1,2\n")
        r = run_cli("add", single, "渠道", "上月", "本月")
        self.assertEqual(r.returncode, 2)
        self.assertIn("至少需要 2 个维度成员", r.stderr)

    def test_missing_file_exit2(self):
        r = run_cli("add", os.path.join(self.dir, "nope.csv"), "d", "b", "c")
        self.assertEqual(r.returncode, 2)
        self.assertIn("文件不存在", r.stderr)

    def test_bad_column_exit2(self):
        r = run_cli("add", self.csv, "渠道", "不存在列", "本月收入")
        self.assertEqual(r.returncode, 2)
        self.assertIn("找不到基期列", r.stderr)


class TestMulCLI(unittest.TestCase):
    def test_mul_json_closure_and_known_contrib(self):
        r = run_cli("mul", "--factors", "店数,单店业绩",
                    "--base", "100,0.71", "--curr", "90,0.37", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        doc = json.loads(r.stdout)
        self.assertTrue(doc["closure_check"]["passed"])
        self.assertAlmostEqual(sum(c["contribution"] for c in doc["contributions"]),
                               doc["total_change"])
        # 店数贡献 = 两种排序边际贡献的平均：(90*0.71-100*0.71 + 90*0.37-100*0.37)/2
        contrib = {c["factor"]: c["contribution"] for c in doc["contributions"]}
        self.assertAlmostEqual(contrib["店数"], (-7.1 + -3.7) / 2, places=9)

    def test_factor_count_limits(self):
        r = run_cli("mul", "--factors", "a,b,c,d,e",
                    "--base", "1,1,1,1,1", "--curr", "1,1,1,1,1")
        self.assertEqual(r.returncode, 2)
        self.assertIn("因子个数需为 2~4", r.stderr)
        r = run_cli("mul", "--factors", "a", "--base", "1", "--curr", "2")
        self.assertEqual(r.returncode, 2)

    def test_mismatched_values_exit2(self):
        r = run_cli("mul", "--factors", "a,b", "--base", "1", "--curr", "1,2")
        self.assertEqual(r.returncode, 2)
        self.assertIn("数值个数须与因子数一致", r.stderr)

    def test_file_rows_mode(self):
        csv_path = os.path.join(tempfile.mkdtemp(), "f.csv")
        with open(csv_path, "w", encoding="utf-8") as f:
            f.write("店数,单店业绩\n100,0.71\n90,0.37\n")
        r = run_cli("mul", csv_path, "--factors", "店数,单店业绩",
                    "--base-row", "0", "--curr-row", "1", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        doc = json.loads(r.stdout)
        self.assertTrue(doc["closure_check"]["passed"])
        self.assertAlmostEqual(doc["total_change"], 90 * 0.37 - 100 * 0.71)


if __name__ == '__main__':
    unittest.main()
