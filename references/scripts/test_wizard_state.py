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


class WizardStateIncrTest(unittest.TestCase):
    """incr 增量模式：独立状态文件、增量五步、命门约束、与搭建档案互不覆盖"""

    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def state(self):
        with open(os.path.join(self.dir, "wizard-state.json"), encoding="utf-8") as f:
            return json.load(f)

    def incr_state(self):
        with open(os.path.join(self.dir, "wizard-state-incr.json"), encoding="utf-8") as f:
            return json.load(f)

    def test_init_incr_writes_separate_file(self):
        r = run("init", self.dir, "--name", "测试agent", "--mode", "incr")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.dir, "wizard-state.json")))
        state = self.incr_state()
        self.assertEqual(state["mode"], "incr")
        self.assertEqual(state["agentName"], "测试agent")
        self.assertEqual(sorted(state["steps"].keys()), ["1", "2", "4", "7", "8"])
        self.assertIn("增量学习", r.stdout)

    def test_incr_show_displays_incr_step_names(self):
        run("init", self.dir, "--mode", "incr")
        r = run("show", self.dir, "--state", "incr")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("增量模式", r.stdout)
        self.assertIn("增量选看板", r.stdout)
        self.assertIn("交付更新", r.stdout)
        self.assertNotIn("业务认知补充", r.stdout)

    def test_incr_step4_and_7_not_skippable(self):
        run("init", self.dir, "--mode", "incr")
        for step in ("4", "7"):
            r = run("set", self.dir, "--state", "incr", "--step", step, "--status", "skipped")
            self.assertEqual(r.returncode, 3, f"incr 第 {step} 步 skipped 应被拒绝: {r.stdout}")
            self.assertIn("质量命门", r.stderr)

    def test_incr_step3_rejected(self):
        run("init", self.dir, "--mode", "incr")
        r = run("set", self.dir, "--state", "incr", "--step", "3", "--status", "in_progress")
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("不存在", r.stderr)

    def test_incr_does_not_touch_build_state(self):
        run("init", self.dir, "--name", "搭建档案", "--mode", "full")
        build_path = os.path.join(self.dir, "wizard-state.json")
        with open(build_path, encoding="utf-8") as f:
            before = f.read()
        r = run("init", self.dir, "--name", "搭建档案", "--mode", "incr")
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(build_path, encoding="utf-8") as f:
            after = f.read()
        self.assertEqual(before, after)

    def test_incr_next_resumes_from_step2(self):
        run("init", self.dir, "--mode", "incr")
        run("set", self.dir, "--state", "incr", "--step", "1", "--status", "confirmed")
        r = run("next", self.dir, "--state", "incr")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("第 2 步", r.stdout)
        self.assertIn("增量学习", r.stdout)

    def test_incr_completed_message(self):
        run("init", self.dir, "--mode", "incr")
        state = self.incr_state()
        for n in ("1", "2", "4", "7", "8"):
            state["steps"][n]["status"] = "confirmed"
        with open(os.path.join(self.dir, "wizard-state-incr.json"), "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False)
        r = run("next", self.dir, "--state", "incr")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("本轮增量已交付", r.stdout)

    def test_build_next_suggests_incr(self):
        run("init", self.dir, "--mode", "full")
        state = self.state()
        for n in range(1, 9):
            state["steps"][str(n)]["status"] = "confirmed"
        with open(os.path.join(self.dir, "wizard-state.json"), "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False)
        r = run("next", self.dir)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("增量学习", r.stdout)


if __name__ == "__main__":
    unittest.main()
