#!/usr/bin/env python3
"""
preflight.py 单测：--json 模式 stdout 必须是纯 JSON（人类可读行不混排）、
人类模式照常打印、finish() 退出码逻辑、看板诊断断点摘要（不影响退出码）。
运行: python3 -m unittest discover -s references/scripts -p 'test_*.py' -v
不触网：只测 check()/finish()/断点检测输出纪律，不跑 main()（main 依赖 guancli 环境）。
"""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import preflight


def run_checks(json_mode, checks):
    """重置模块状态，跑一串 check 后 finish，返回 (exit_code, stdout)"""
    preflight.results.clear()
    preflight._JSON_MODE = json_mode
    buf = io.StringIO()
    code = None
    with contextlib.redirect_stdout(buf):
        for name, ok, hard in checks:
            preflight.check(name, ok, hard, f"{name} 详情", f"{name} 提示")
        try:
            preflight.finish(json_mode, 0)
        except SystemExit as e:
            code = e.code
    return code, buf.getvalue()


class TestJsonMode(unittest.TestCase):
    def test_stdout_is_pure_json(self):
        code, out = run_checks(True, [("安装", True, True), ("认证", True, True)])
        self.assertEqual(code, 0)
        doc = json.loads(out)  # 混排人类可读行时这里会直接抛 JSONDecodeError
        self.assertTrue(doc["ok"])
        self.assertEqual(len(doc["checks"]), 2)
        self.assertEqual(doc["checks"][0]["check"], "安装")

    def test_json_mode_hard_fail_exit1(self):
        code, out = run_checks(True, [("安装", False, True)])
        self.assertEqual(code, 1)
        doc = json.loads(out)
        self.assertFalse(doc["ok"])
        self.assertFalse(doc["checks"][0]["ok"])

    def test_json_mode_soft_fail_keeps_ok(self):
        code, out = run_checks(True, [("版本", False, False)])
        self.assertEqual(code, 0)  # 非 hard 失败不影响退出码
        self.assertTrue(json.loads(out)["ok"])


class TestHumanMode(unittest.TestCase):
    def test_human_lines_printed(self):
        code, out = run_checks(False, [("安装", True, True), ("认证", False, True)])
        self.assertEqual(code, 1)
        self.assertIn("✅ 安装: 安装 详情", out)
        self.assertIn("❌ 认证: 认证 详情 → 认证 提示", out)
        self.assertIn("存在必须修复的问题", out)

    def test_human_pass_summary(self):
        code, out = run_checks(False, [("安装", True, True)])
        self.assertEqual(code, 0)
        self.assertIn("前置检查通过", out)


class TestAuditResume(unittest.TestCase):
    """看板诊断断点摘要（wizard-state-audit.json）：信息性检查，不影响退出码"""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "wizard-state-audit.json")

    def write_state(self, steps, name="月度经营分析"):
        doc = {"mode": "audit", "agentName": name, "steps": steps}
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False)

    def run_audit(self, json_mode=False):
        preflight.results.clear()
        preflight._JSON_MODE = json_mode
        buf = io.StringIO()
        code = None
        with contextlib.redirect_stdout(buf):
            preflight.check_audit_resume(self.dir)
            try:
                preflight.finish(json_mode, 0)
            except SystemExit as e:
                code = e.code
        return code, buf.getvalue()

    def test_audit_resume_prints_summary_and_keeps_exit_code(self):
        self.write_state({"1": {"status": "confirmed"}, "2": {"status": "in_progress"},
                          "3": {"status": "pending"}, "4": {"status": "pending"}})
        code, out = self.run_audit()
        self.assertEqual(code, 0)
        self.assertIn("看板诊断进行到第 2 步【学习与结构体检】", out)
        self.assertIn("进行中", out)
        self.assertIn("月度经营分析", out)
        self.assertFalse(any(r["hard"] for r in preflight.results))

    def test_audit_completed_summary(self):
        self.write_state({str(n): {"status": "confirmed"} for n in range(1, 5)})
        code, out = self.run_audit()
        self.assertEqual(code, 0)
        self.assertIn("四步已完成", out)
        self.assertIn("诊断报告已生成", out)
        self.assertFalse(any(r["hard"] for r in preflight.results))

    def test_json_mode_keeps_summary_in_pure_json(self):
        self.write_state({"1": {"status": "confirming"}, "2": {"status": "pending"},
                          "3": {"status": "pending"}, "4": {"status": "pending"}})
        code, out = self.run_audit(json_mode=True)
        self.assertEqual(code, 0)
        doc = json.loads(out)
        self.assertTrue(doc["ok"])
        self.assertTrue(any("看板诊断进行到第 1 步" in c["detail"] for c in doc["checks"]))

    def test_no_audit_state_is_silent(self):
        code, out = self.run_audit()
        self.assertEqual(code, 0)
        self.assertNotIn("看板诊断", out)
        self.assertEqual(preflight.results, [])

    def test_corrupted_state_does_not_crash(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("{not json")
        code, out = self.run_audit()
        self.assertEqual(code, 0)
        self.assertIn("损坏", out)
        self.assertFalse(any(r["hard"] for r in preflight.results))


if __name__ == '__main__':
    unittest.main()
