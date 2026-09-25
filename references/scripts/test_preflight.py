#!/usr/bin/env python3
"""
preflight.py 最小单测：--json 模式 stdout 必须是纯 JSON（人类可读行不混排）、
人类模式照常打印、finish() 退出码逻辑。
运行: python3 -m unittest discover -s references/scripts -p 'test_*.py' -v
不触网：只测 check()/finish() 输出纪律，不跑 main()（main 依赖 guancli 环境）。
"""
import contextlib
import io
import json
import os
import sys
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


if __name__ == '__main__':
    unittest.main()
