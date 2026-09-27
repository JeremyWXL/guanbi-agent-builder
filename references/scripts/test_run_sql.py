#!/usr/bin/env python3
"""run_sql.py 单测：范围守卫 dsId 白名单（越界 exit 3 且不调 guancli）+ 只读校验回归"""
import json, os, sys, tempfile, unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run_sql
import scope


def write_json(workdir, name, doc):
    with open(os.path.join(workdir, name), "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)


def make_cards_doc():
    return {
        "_meta": {"pages": {"p1": {"title": "页一", "mtime": "x", "cardCount": 1,
                                   "cardHash": "h", "cards": [{"cdId": "c1", "name": "卡A"}]}}},
        "页一": {"title": "页一", "pgId": "p1", "dsUsage": {"ds1": {"cards": 1, "filteredCards": 0}},
                 "cards": [{"name": "卡A", "cdId": "c1", "type": "TABLE", "dsId": "ds1"}]},
    }


class ScopeGuardTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        write_json(self.dir, "cards.json", make_cards_doc())

    def run_sql(self, ds_id, sql="SELECT 1", scope_obj=None):
        argv = sys.argv
        sys.argv = ["run_sql.py", ds_id, sql]
        with mock.patch.object(run_sql.subprocess, "run") as m_run, \
             mock.patch.object(run_sql.scope_mod, "load_scope", return_value=scope_obj):
            m_run.return_value.returncode = 0
            try:
                run_sql.main()
            except SystemExit as e:
                sys.argv = argv
                return e.code, m_run
            sys.argv = argv
            return 0, m_run

    def test_out_of_scope_ds_rejected_without_calling_guancli(self):
        scope_obj = scope.load_scope(candidates=[os.path.join(self.dir, "cards.json")])
        code, m_run = self.run_sql("ds_evil", scope_obj=scope_obj)
        self.assertEqual(code, 3)
        m_run.assert_not_called()  # 越界拦截在调 guancli 之前

    def test_in_scope_ds_passes_to_guancli(self):
        scope_obj = scope.load_scope(candidates=[os.path.join(self.dir, "cards.json")])
        code, m_run = self.run_sql("ds1", scope_obj=scope_obj)
        self.assertEqual(code, 0)
        m_run.assert_called_once()  # 白名单内正常透传

    def test_scope_missing_skips_check(self):
        # 无 cards.json：优雅降级，不阻断独立使用
        code, m_run = self.run_sql("ds_whatever", scope_obj=None)
        self.assertEqual(code, 0)
        m_run.assert_called_once()


class ReadOnlyValidationTest(unittest.TestCase):
    def test_select_ok(self):
        self.assertIsNone(run_sql.validate("SELECT COUNT(*) FROM `ds`"))

    def test_write_blocked(self):
        self.assertIn("DROP", run_sql.validate("DROP TABLE x"))

    def test_multi_statement_blocked(self):
        self.assertIn("多语句", run_sql.validate("SELECT 1; SELECT 2"))

    def test_insert_blocked(self):
        self.assertIn("INSERT", run_sql.validate("INSERT INTO t VALUES (1)"))


if __name__ == "__main__":
    unittest.main()
