#!/usr/bin/env python3
"""wizard_state.py 单测：--mode 字段、lite 轨道约束与旧档案兼容"""
import json, os, subprocess, sys, tempfile, unittest

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wizard_state.py")


def run(*args):
    return subprocess.run([sys.executable, SCRIPT, *args],
                          capture_output=True, text=True)


class WizardStateModeTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def state(self):
        with open(os.path.join(self.dir, "wizard-state.json"), encoding="utf-8") as f:
            return json.load(f)

    def test_init_default_full(self):
        r = run("init", self.dir)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.state()["mode"], "full")

    def test_init_lite(self):
        r = run("init", self.dir, "--mode", "lite")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.state()["mode"], "lite")
        self.assertIn("快速模式", r.stdout)

    def test_show_displays_mode(self):
        run("init", self.dir, "--mode", "lite", "--name", "测试agent")
        r = run("show", self.dir)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("快速模式", r.stdout)

    def test_lite_step3_skippable(self):
        run("init", self.dir, "--mode", "lite")
        r = run("set", self.dir, "--step", "3", "--status", "skipped")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_lite_step4_and_7_not_skippable(self):
        run("init", self.dir, "--mode", "lite")
        for step in ("4", "7"):
            r = run("set", self.dir, "--step", step, "--status", "skipped")
            self.assertEqual(r.returncode, 3, f"第 {step} 步 skipped 应被拒绝: {r.stdout}")
            self.assertIn("质量命门", r.stderr)

    def test_legacy_state_without_mode_treated_as_full(self):
        # 旧档案无 mode 字段：show/next 不崩溃，按完整模式处理
        legacy = {
            "version": 1, "builderVersion": "4.2.0", "agentName": "旧档案",
            "createdAt": "2026-09-01T10:00:00+08:00",
            "updatedAt": "2026-09-01T10:00:00+08:00",
            "currentStep": 2,
            "steps": {str(n): {"status": "pending"} for n in range(1, 9)},
        }
        legacy["steps"]["1"]["status"] = "confirmed"
        with open(os.path.join(self.dir, "wizard-state.json"), "w", encoding="utf-8") as f:
            json.dump(legacy, f, ensure_ascii=False)
        r = run("show", self.dir)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("完整模式", r.stdout)
        r = run("next", self.dir)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("第 2 步", r.stdout)

    def test_next_lite_completed_suggests_deepening(self):
        run("init", self.dir, "--mode", "lite")
        state = self.state()
        for n in range(1, 9):
            state["steps"][str(n)]["status"] = "confirmed"
        with open(os.path.join(self.dir, "wizard-state.json"), "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False)
        r = run("next", self.dir)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("深化", r.stdout)


if __name__ == "__main__":
    unittest.main()
