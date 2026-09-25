#!/usr/bin/env python3
"""
memory.py 最小单测：init 幂等（用户资产不覆盖）、log 追加与兜底初始化、
recall 相似排序与纠错失效标注、correct 校验与台账、status/distilled 蒸馏计数、
clear 备份清空、references 目录解析。
运行: python3 -m unittest discover -s references/scripts -p 'test_*.py' -v
不触网：全部用临时目录。
"""
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import memory

SCRIPT = os.path.abspath(memory.__file__)


def run_cli(*args):
    return subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True)


class TestInit(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def test_init_creates_four_files(self):
        r = run_cli("init", self.dir)
        self.assertEqual(r.returncode, 0, r.stderr)
        for fn in ("profile.md", "qa-log.jsonl", "corrections.json", "_meta.json"):
            self.assertTrue(os.path.isfile(os.path.join(self.dir, "memory", fn)), fn)

    def test_init_idempotent_never_overwrites(self):
        run_cli("init", self.dir)
        profile = os.path.join(self.dir, "memory", "profile.md")
        with open(profile, "w", encoding="utf-8") as f:
            f.write("# 用户手写画像，升级/init 都不许动\n")
        r = run_cli("init", self.dir)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("未覆盖", r.stdout)
        with open(profile, encoding="utf-8") as f:
            self.assertIn("用户手写画像", f.read())

    def test_references_dir_resolves_to_parent(self):
        ref = os.path.join(self.dir, "references")
        os.makedirs(ref)
        self.assertEqual(memory.memory_dir(ref), os.path.join(self.dir, "memory"))


class TestLog(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def test_log_appends_and_auto_inits(self):
        # 不先 init，log 应兜底初始化
        r = run_cli("log", self.dir, "--question", "3月淘系收入多少",
                    "--route", "《销售总览》/收入卡", "--note", "710万",
                    "--choice", "华东=销售大区")
        self.assertEqual(r.returncode, 0, r.stderr)
        entries = memory.read_log(self.dir)
        self.assertEqual(len(entries), 1)
        e = entries[0]
        self.assertEqual(e["question"], "3月淘系收入多少")
        self.assertEqual(e["choices"], {"华东": "销售大区"})
        self.assertFalse(e["correction"])
        self.assertTrue(e["ts"])

    def test_log_requires_question(self):
        r = run_cli("log", self.dir, "--route", "x")
        self.assertEqual(r.returncode, 1)

    def test_log_append_only(self):
        run_cli("log", self.dir, "--question", "问题一")
        run_cli("log", self.dir, "--question", "问题二")
        self.assertEqual(len(memory.read_log(self.dir)), 2)


class TestRecall(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        run_cli("init", self.dir)
        run_cli("log", self.dir, "--question", "华东大区3月收入多少",
                "--route", "《销售总览》/大区收入卡", "--note", "710万",
                "--choice", "华东=销售大区")
        run_cli("log", self.dir, "--question", "门店营业时间几点")

    def test_recall_ranks_similar_first(self):
        r = run_cli("recall", self.dir, "华东区3月的收入是多少", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        doc = json.loads(r.stdout)
        self.assertGreaterEqual(len(doc["hits"]), 1)
        self.assertIn("华东", doc["hits"][0]["question"])
        self.assertEqual(doc["hits"][0]["choices"], {"华东": "销售大区"})

    def test_recall_no_hit(self):
        r = run_cli("recall", self.dir, "完全无关的问题xyz")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("未找到相似历史", r.stdout)

    def test_recall_marks_stale_after_correction(self):
        # 对相似问题记一次纠错 → 旧问答标 stale，禁止沿用
        run_cli("correct", self.dir, "--type", "口径",
                "--before", "华东大区收入按发货金额", "--after", "按开票金额",
                "--target", "metrics.json", "--question", "华东大区3月收入多少")
        r = run_cli("recall", self.dir, "华东大区3月收入", "--json")
        doc = json.loads(r.stdout)
        stale = [h for h in doc["hits"] if h["stale"]]
        self.assertTrue(stale, doc)
        self.assertIn("以 references 最新档案为准", stale[0]["staleReason"])


class TestCorrect(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def test_correct_appends(self):
        r = run_cli("correct", self.dir, "--type", "口径",
                    "--before", "退款率÷收入", "--after", "退款率÷GMV",
                    "--target", "metrics.json")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("别忘了同步写回 references", r.stdout)
        cs = memory.read_corrections(self.dir)
        self.assertEqual(len(cs), 1)
        self.assertEqual(cs[0]["type"], "口径")
        self.assertEqual(cs[0]["target"], "metrics.json")

    def test_correct_validates_type(self):
        r = run_cli("correct", self.dir, "--type", "乱写",
                    "--before", "a", "--after", "b")
        self.assertEqual(r.returncode, 1)

    def test_correct_requires_before_after(self):
        r = run_cli("correct", self.dir, "--type", "口径", "--before", "a")
        self.assertEqual(r.returncode, 1)


class TestStatusDistill(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def test_uninitialized_status(self):
        r = run_cli("status", self.dir)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(json.loads(r.stdout)["initialized"])

    def test_distill_counter_flow(self):
        run_cli("init", self.dir)
        for i in range(memory.DISTILL_THRESHOLD):
            run_cli("log", self.dir, "--question", f"问题{i}")
        doc = json.loads(run_cli("status", self.dir).stdout)
        self.assertEqual(doc["pendingDistill"], memory.DISTILL_THRESHOLD)
        self.assertTrue(doc["suggestDistill"])
        run_cli("distilled", self.dir)
        doc = json.loads(run_cli("status", self.dir).stdout)
        self.assertEqual(doc["pendingDistill"], 0)
        self.assertFalse(doc["suggestDistill"])
        self.assertEqual(doc["distilledCount"], memory.DISTILL_THRESHOLD)


class TestClear(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def test_clear_requires_yes(self):
        run_cli("init", self.dir)
        r = run_cli("clear", self.dir)
        self.assertEqual(r.returncode, 1)
        self.assertIn("--yes", r.stderr)

    def test_clear_backs_up_and_reinits(self):
        run_cli("init", self.dir)
        run_cli("log", self.dir, "--question", "将被忘掉的问题")
        r = run_cli("clear", self.dir, "--yes")
        self.assertEqual(r.returncode, 0, r.stderr)
        # 重新初始化后是空流水
        self.assertEqual(memory.read_log(self.dir), [])
        # 备份目录里有旧流水
        backups = [d for d in os.listdir(self.dir) if d.startswith("memory.bak-")]
        self.assertEqual(len(backups), 1)
        with open(os.path.join(self.dir, backups[0], "qa-log.jsonl"), encoding="utf-8") as f:
            self.assertIn("将被忘掉的问题", f.read())


class TestSimilarity(unittest.TestCase):
    def test_similarity_basics(self):
        self.assertEqual(memory.similarity("", "abc"), 0.0)
        self.assertGreater(memory.similarity("华东大区收入", "华东区收入"), 0.5)
        self.assertLess(memory.similarity("华东大区收入", "门店营业时间"), 0.2)


if __name__ == '__main__':
    unittest.main()
