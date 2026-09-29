#!/usr/bin/env python3
"""run_metric.py 单测：指标中心 governedRef 白名单（越界 exit 3 且不调 guancli）+
scope 缺失/无 governedRef 降级 + --check-scope dry 校验 + 查询参数透传"""
import json, os, sys, tempfile, unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run_metric
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
        write_json(self.dir, "metrics.json", {"metrics": [
            {"name": "净收入", "formula": "sum([实际数])",
             "governedRef": {"metricId": "m100", "name": "净收入", "status": "PUBLISHED"}},
            {"name": "毛利率", "formula": "sum([毛利])/sum([收入])"},  # 无 governedRef，正常
        ], "rejected": []})

    def load_scope(self):
        return scope.load_scope(candidates=[os.path.join(self.dir, "cards.json")])

    def run_metric(self, argv_extra, scope_obj="__default__"):
        argv = sys.argv
        sys.argv = ["run_metric.py"] + argv_extra
        if scope_obj == "__default__":
            scope_obj = self.load_scope()
        with mock.patch.object(run_metric.subprocess, "run") as m_run, \
             mock.patch.object(run_metric.scope_mod, "load_scope", return_value=scope_obj):
            m_run.return_value.returncode = 0
            try:
                run_metric.main()
            except SystemExit as e:
                sys.argv = argv
                return e.code, m_run
            sys.argv = argv
            return 0, m_run

    def test_whitelisted_metric_passes_to_guancli(self):
        code, m_run = self.run_metric(["m100"])
        self.assertEqual(code, 0)
        m_run.assert_called_once()
        cmd = m_run.call_args[0][0]
        self.assertEqual(cmd[:4], ["guancli", "metric", "query", "m100"])

    def test_out_of_scope_metric_rejected_without_calling_guancli(self):
        code, m_run = self.run_metric(["m_evil"])
        self.assertEqual(code, 3)
        m_run.assert_not_called()  # 越界拦截在调 guancli 之前

    def test_scope_missing_degrades(self):
        # 无范围档案：优雅降级放行，不阻断独立使用
        code, m_run = self.run_metric(["m_whatever"], scope_obj=None)
        self.assertEqual(code, 0)
        m_run.assert_called_once()

    def test_no_governed_ref_degrades(self):
        # metrics.json 存在但无任何 governedRef：白名单为空 = 降级放行（多数指标没有引用，正常）
        d = tempfile.mkdtemp()
        write_json(d, "cards.json", make_cards_doc())
        write_json(d, "metrics.json", {"metrics": [{"name": "净收入", "formula": "sum([实际数])"}]})
        scope_obj = scope.load_scope(candidates=[os.path.join(d, "cards.json")])
        code, m_run = self.run_metric(["m_whatever"], scope_obj=scope_obj)
        self.assertEqual(code, 0)
        m_run.assert_called_once()

    def test_passthrough_args_forwarded(self):
        code, m_run = self.run_metric(["m100", "--", "--dim", "月份", "--filter", "区域=华东"])
        self.assertEqual(code, 0)
        cmd = m_run.call_args[0][0]
        self.assertEqual(cmd, ["guancli", "metric", "query", "m100",
                               "--dim", "月份", "--filter", "区域=华东"])

    def test_usage_error_exit(self):
        code, _ = self.run_metric([])
        self.assertNotEqual(code, 0)


class CheckScopeTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        write_json(self.dir, "cards.json", make_cards_doc())
        write_json(self.dir, "metrics.json", {"metrics": [
            {"name": "净收入", "formula": "sum([实际数])",
             "governedRef": {"metricId": "m100", "name": "净收入", "status": "PUBLISHED"}},
        ]})

    def run_check_scope(self, metric_id, scope_obj="__default__"):
        argv = sys.argv
        sys.argv = ["run_metric.py", "--check-scope", metric_id]
        if scope_obj == "__default__":
            scope_obj = scope.load_scope(candidates=[os.path.join(self.dir, "cards.json")])
        with mock.patch.object(run_metric.subprocess, "run") as m_run, \
             mock.patch.object(run_metric.scope_mod, "load_scope", return_value=scope_obj):
            try:
                run_metric.main()
            except SystemExit as e:
                sys.argv = argv
                return e.code, m_run
            sys.argv = argv
            return 0, m_run

    def test_in_scope_exit0_no_guancli(self):
        code, m_run = self.run_check_scope("m100")
        self.assertEqual(code, 0)
        m_run.assert_not_called()  # dry 模式不调 guancli

    def test_out_of_scope_exit3(self):
        code, m_run = self.run_check_scope("m_evil")
        self.assertEqual(code, 3)
        m_run.assert_not_called()

    def test_missing_scope_degrades_exit0(self):
        code, m_run = self.run_check_scope("m_whatever", scope_obj=None)
        self.assertEqual(code, 0)
        m_run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
