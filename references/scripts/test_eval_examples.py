#!/usr/bin/env python3
"""
eval_examples.py 最小单测：数值容差解析（货币符号/千分位/百分号/中文单位）、
期望值命中、卡片评测路径、主流程退出码与 references/ 回退。
运行: python3 -m unittest discover -s references/scripts -p 'test_*.py' -v
不触网：全部用临时目录构造 examples.json / card-data；SQL 路径不测（依赖 run_sql.py 与环境）。
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import eval_examples

SCRIPT = os.path.abspath(eval_examples.__file__)


def run_cli(*args):
    return subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True)


def write_json(d, name, obj):
    fp = os.path.join(d, name)
    os.makedirs(os.path.dirname(fp), exist_ok=True)
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)


def card_example(**kw):
    ex = {"id": "q1", "question": "团购上月收入多少",
          "fetch": {"type": "card", "file": "card-data/看板A__卡1.json"},
          "expect": {"values": [710000], "keywords": ["团购"]},
          "answerPoints": ["团购是主要拖累"],
          "humanConfirmed": True}
    ex.update(kw)
    return ex


class TestNumCandidates(unittest.TestCase):
    def test_currency_symbols(self):
        self.assertEqual(eval_examples.num_candidates("￥1,234"), [1234.0])
        self.assertEqual(eval_examples.num_candidates("¥71万"), [710000.0])
        self.assertEqual(eval_examples.num_candidates("$3.5亿"), [350000000.0])

    def test_percent_gives_two_candidates(self):
        cands = eval_examples.num_candidates("35%")
        self.assertIn(35.0, cands)
        self.assertIn(0.35, cands)

    def test_passthrough_and_rejects(self):
        self.assertEqual(eval_examples.num_candidates(3.5), [3.5])
        self.assertEqual(eval_examples.num_candidates(-7), [-7.0])
        self.assertEqual(eval_examples.num_candidates(True), [])   # bool 不是数值
        self.assertEqual(eval_examples.num_candidates("abc"), [])
        self.assertEqual(eval_examples.num_candidates(""), [])

    def test_num_token_finds_prefixed_numbers(self):
        text = "销售额￥1,234，达成率95%，GMV $3.5亿，净额-2,000"
        toks = eval_examples.NUM_TOKEN.findall(text)
        flat = []
        for t in toks:
            flat.extend(eval_examples.num_candidates(t))
        for want in (1234.0, 0.95, 350000000.0, -2000.0):
            self.assertIn(want, flat)


class TestValueHit(unittest.TestCase):
    def test_relative_tolerance(self):
        self.assertTrue(eval_examples.value_hit(100, [101.5], 0.02))
        self.assertFalse(eval_examples.value_hit(100, [103], 0.02))

    def test_zero_expected(self):
        self.assertTrue(eval_examples.value_hit(0, [0.0], 0.02))
        self.assertFalse(eval_examples.value_hit(0, [0.5], 0.02))


class TestCheckExpect(unittest.TestCase):
    def test_values_and_keywords(self):
        ok, reasons = eval_examples.check_expect(card_example(), "团购 收入", [710000.0])
        self.assertTrue(ok, reasons)

    def test_missing_value_and_keyword(self):
        ex = card_example()
        ok, reasons = eval_examples.check_expect(ex, "别的词", [123.0])
        self.assertFalse(ok)
        self.assertEqual(len(reasons), 2)  # 数值未命中 + 关键词未出现


class TestEvalCard(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        write_json(self.dir, "card-data/看板A__卡1.json",
                   {"rows": [{"渠道": "团购", "收入": 710000}]})

    def test_pass(self):
        status, reasons, points = eval_examples.eval_card(self.dir, card_example())
        self.assertEqual(status, "pass")
        self.assertEqual(points, ["团购是主要拖累"])

    def test_value_miss_fails(self):
        ex = card_example(expect={"values": [999]})
        status, reasons, _ = eval_examples.eval_card(self.dir, ex)
        self.assertEqual(status, "fail")
        self.assertIn("未在数据中找到", reasons[0])

    def test_missing_file_fails(self):
        ex = card_example(fetch={"type": "card", "file": "card-data/不存在.json"})
        status, reasons, _ = eval_examples.eval_card(self.dir, ex)
        self.assertEqual(status, "fail")
        self.assertIn("采样文件缺失", reasons[0])


class TestMainFlow(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def _setup_workdir(self, examples_in_references=False):
        target = os.path.join(self.dir, "references") if examples_in_references else self.dir
        write_json(target, "examples.json", {"scenarios": {"问数": [card_example()]}})
        write_json(target, "card-data/看板A__卡1.json",
                   {"rows": [{"渠道": "团购", "收入": 710000}]})

    def test_all_pass_exit0(self):
        self._setup_workdir()
        r = run_cli(self.dir)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("通过 1", r.stdout)

    def test_fail_exit1(self):
        self._setup_workdir()
        write_json(self.dir, "examples.json",
                   {"scenarios": {"问数": [card_example(expect={"values": [999]})]}})
        r = run_cli(self.dir)
        self.assertEqual(r.returncode, 1)
        self.assertIn("❌", r.stdout)

    def test_missing_examples_exit2(self):
        r = run_cli(self.dir)
        self.assertEqual(r.returncode, 2)
        self.assertIn("未找到 examples.json", r.stderr)

    def test_references_fallback(self):
        # 交付包形态：examples.json 与 card-data 都在 references/ 下
        self._setup_workdir(examples_in_references=True)
        r = run_cli(self.dir)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)

    def test_pending_only_exit0(self):
        self._setup_workdir()
        write_json(self.dir, "examples.json",
                   {"scenarios": {"问数": [card_example(humanConfirmed=False)]}})
        r = run_cli(self.dir)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("待人工确认 1", r.stdout)

    def test_scenario_filter(self):
        self._setup_workdir()
        r = run_cli(self.dir, "--scenario", "不存在的场景")
        self.assertEqual(r.returncode, 2)
        self.assertIn("不存在", r.stderr)
        r = run_cli(self.dir, "--scenario", "问数")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_json_output_shape(self):
        self._setup_workdir()
        r = run_cli(self.dir, "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        doc = json.loads(r.stdout)
        self.assertEqual(doc["total"]["pass"], 1)
        self.assertEqual(doc["total"]["passRate"], 1.0)

    def test_fetch_mix_stats(self):
        # v4.2 取数路径统计：card=应答缓存，sql=现算；run_sql 不可用记 skip 不影响统计
        self._setup_workdir()
        write_json(self.dir, "examples.json", {"scenarios": {"问数": [
            card_example(),
            {"id": "q2", "question": "自定义切片", "fetch": {"type": "sql", "dsId": "d1", "sql": "SELECT 1"},
             "expect": {"values": [1]}, "humanConfirmed": True},
        ]}})
        r = run_cli(self.dir)
        self.assertIn("缓存占比 50%", r.stdout)
        r = run_cli(self.dir, "--json")
        doc = json.loads(r.stdout)
        self.assertEqual(doc["fetchMix"], {"card": 1, "sql": 1, "cacheShare": 0.5})


if __name__ == '__main__':
    unittest.main()
