#!/usr/bin/env python3
"""wizard_state.py 单测：--mode 字段、lite/incr/audit 轨道约束、产物门与旧档案兼容"""
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


class WizardStateConfirmGateTest(unittest.TestCase):
    """confirm 第 7/8 步的产物校验：质量命门看产物不看口头申报"""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        run("init", self.dir)

    def write_examples(self, confirmed=True):
        doc = {"scenarios": {"问数": [{
            "id": "Q1", "question": "q",
            "fetch": {"type": "card", "file": "card-data/x.json"},
            "expect": {"values": [1]}, "humanConfirmed": confirmed}]}}
        with open(os.path.join(self.dir, "examples.json"), "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False)

    def test_confirm_step7_requires_examples(self):
        r = run("confirm", self.dir, "--step", "7")
        self.assertEqual(r.returncode, 3)
        self.assertIn("examples.json", r.stderr)

    def test_confirm_step7_rejects_unconfirmed(self):
        """验收未回填（实机 review 故障类）→ confirm 第 7 步被拦"""
        self.write_examples(confirmed=False)
        r = run("confirm", self.dir, "--step", "7")
        self.assertEqual(r.returncode, 3)
        self.assertIn("未验收确认", r.stderr)

    def test_confirm_step7_passes_with_evidence(self):
        self.write_examples(confirmed=True)
        r = run("confirm", self.dir, "--step", "7")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_confirm_step8_requires_package_check(self):
        r = run("confirm", self.dir, "--step", "8")
        self.assertEqual(r.returncode, 3)
        self.assertIn("build_package", r.stderr)

    def test_confirm_step8_rejects_failed_check(self):
        with open(os.path.join(self.dir, "package-check.json"), "w", encoding="utf-8") as f:
            json.dump({"package": self.dir, "result": "fail", "errors": ["x"]}, f)
        r = run("confirm", self.dir, "--step", "8")
        self.assertEqual(r.returncode, 3)
        self.assertIn("未通过", r.stderr)

    def test_confirm_step8_passes_with_passed_check(self):
        with open(os.path.join(self.dir, "package-check.json"), "w", encoding="utf-8") as f:
            json.dump({"package": self.dir, "result": "pass", "errors": []}, f)
        r = run("confirm", self.dir, "--step", "8")
        self.assertEqual(r.returncode, 0, r.stderr)


class WizardStateAuditTest(unittest.TestCase):
    """audit 看板诊断模式：独立状态文件、四步、全步禁跳过、产物门、话术不串台"""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.audit_path = os.path.join(self.dir, "wizard-state-audit.json")

    def audit_state(self):
        with open(self.audit_path, encoding="utf-8") as f:
            return json.load(f)

    def write_audit_state(self, state):
        with open(self.audit_path, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False)

    def write_file(self, name, content=""):
        with open(os.path.join(self.dir, name), "w", encoding="utf-8") as f:
            f.write(content)

    def confirm_prior_steps(self, step):
        state = self.audit_state()
        for n in range(1, step):
            state["steps"][str(n)]["status"] = "confirmed"
        self.write_audit_state(state)

    def write_valid_audit_pair(self):
        """写一对能通过 insight_audit_report.py --check 的最小体检/建议产物。"""
        audit = {
            "meta": {"builtAt": "2026-10-22 10:00", "pageCount": 1,
                     "maxPages": 10, "officialMaxPages": 10},
            "pages": [{"pgId": "pg1", "name": "经营总览"}],
            "findings": [{"id": "F-001", "rule": "R-02", "level": "P0",
                          "requirement": "每张仪表板必须配置联动筛选器",
                          "source": "官方文档·新建智能体"}],
            "cross": {"overlaps": [], "sharedLinkageDims": [], "conflicts": []},
            "portfolio": {"score": 60, "grade": "需改造", "overall": 60},
        }
        advice = {
            "auditBuiltAt": "2026-10-22 10:00",
            "scenario": "月度经营分析",
            "businessScope": "连锁零售月度经营分析",
            "mode": {"primary": "一张宽表", "alternatives": [], "reason": "单页即可覆盖"},
            "targetArchitecture": [
                {"layer": "总览", "pages": ["pg1"], "purpose": "判断整体是否异常"}
            ],
            "pageActions": [
                {"pgId": "pg1", "name": "经营总览", "verdict": "保留", "priority": "P0",
                 "actions": ["补区域联动筛选器"], "evidence": ["F-001"],
                 "expectedEffect": "Agent 能按区域传参"}
            ],
            "cardReuse": [],
            "crossPageActions": [
                {"type": "补筛选器", "pages": ["pg1"], "priority": "P0",
                 "action": "补区域联动筛选器", "evidence": ["F-001"]}
            ],
            "configHandoff": {
                "linkageFilters": [{"pgId": "pg1", "name": "区域", "field": "区域", "cdId": "planned-region"}],
                "businessScope": "连锁零售月度经营分析",
                "agentType": "探索型",
                "defaultThinking": "先看总览，再按区域拆解",
                "stepPlan": [],
                "exploratoryRules": ["先总览再拆解", "异常区域才下钻"],
                "reportFramework": [],
                "questionExamples": [],
                "outputRequirements": "带数据范围与口径",
                "businessKnowledgeGaps": [],
                "expertRoles": [],
            },
            "roadmap": [],
            "openQuestions": [],
        }
        self.write_file("insight-audit.json", json.dumps(audit, ensure_ascii=False))
        self.write_file("insight-advice.json", json.dumps(advice, ensure_ascii=False))

    def test_init_audit_writes_separate_four_step_file(self):
        r = run("init", self.dir, "--mode", "audit", "--name", "月度经营分析")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.dir, "wizard-state.json")))
        state = self.audit_state()
        self.assertEqual(state["mode"], "audit")
        self.assertEqual(sorted(state["steps"].keys()), ["1", "2", "3", "4"])
        self.assertEqual({s["status"] for s in state["steps"].values()}, {"pending"})
        self.assertIn("看板诊断（四步）", r.stdout)

    def test_init_audit_duplicate_rejected(self):
        run("init", self.dir, "--mode", "audit")
        r = run("init", self.dir, "--mode", "audit")
        self.assertEqual(r.returncode, 1)
        self.assertIn("已存在", r.stderr)

    def test_audit_show_uses_four_steps_without_eight_step_wording(self):
        run("init", self.dir, "--mode", "audit", "--name", "月度经营分析")
        r = run("show", self.dir, "--state", "audit")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("看板诊断模式", r.stdout)
        self.assertIn("选定看板与场景", r.stdout)
        self.assertIn("报告输出", r.stdout)
        self.assertNotIn("八步", r.stdout)
        self.assertNotIn("搭建进度", r.stdout)
        self.assertNotIn("业务认知补充", r.stdout)

    def test_audit_next_resumes_from_first_step(self):
        run("init", self.dir, "--mode", "audit")
        r = run("next", self.dir, "--state", "audit")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("第 1 步", r.stdout)
        self.assertIn("选定看板与场景", r.stdout)
        self.assertIn("看板诊断", r.stdout)
        self.assertNotIn("八步", r.stdout)

    def test_audit_next_completed_message(self):
        run("init", self.dir, "--mode", "audit")
        state = self.audit_state()
        for n in ("1", "2", "3", "4"):
            state["steps"][n]["status"] = "confirmed"
        self.write_audit_state(state)
        r = run("next", self.dir, "--state", "audit")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("诊断报告已生成", r.stdout)
        self.assertNotIn("八步", r.stdout)
        self.assertNotIn("搭建已交付", r.stdout)

    def test_audit_all_four_steps_not_skippable(self):
        run("init", self.dir, "--mode", "audit")
        for step in ("1", "2", "3", "4"):
            r = run("set", self.dir, "--state", "audit", "--step", step, "--status", "skipped")
            self.assertEqual(r.returncode, 3,
                             f"audit 第 {step} 步 skipped 应被拒绝: {r.stdout}{r.stderr}")
            self.assertIn("不允许跳过", r.stderr)

    def test_build_step3_still_skippable(self):
        """build 侧既有行为不回归：第 3 步仍可 skipped"""
        run("init", self.dir)
        r = run("set", self.dir, "--step", "3", "--status", "skipped")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_audit_confirm_step1_has_no_artifact_gate(self):
        run("init", self.dir, "--mode", "audit")
        r = run("confirm", self.dir, "--state", "audit", "--step", "1")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_audit_confirm_step2_requires_insight_audit(self):
        run("init", self.dir, "--mode", "audit")
        self.confirm_prior_steps(2)
        r = run("confirm", self.dir, "--state", "audit", "--step", "2")
        self.assertEqual(r.returncode, 3)
        self.assertIn("insight-audit.json", r.stderr)
        self.assertIn("audit_insight_pages.py", r.stderr)
        self.write_file("insight-audit.json", "{}")
        r = run("confirm", self.dir, "--state", "audit", "--step", "2")
        self.assertEqual(r.returncode, 3)
        self.write_valid_audit_pair()
        r = run("confirm", self.dir, "--state", "audit", "--step", "2")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_audit_confirm_rejects_out_of_order_step(self):
        run("init", self.dir, "--mode", "audit")
        r = run("confirm", self.dir, "--state", "audit", "--step", "4")
        self.assertEqual(r.returncode, 3)
        self.assertIn("前序", r.stderr)

    def test_audit_confirm_step3_requires_valid_advice(self):
        run("init", self.dir, "--mode", "audit")
        self.confirm_prior_steps(3)
        r = run("confirm", self.dir, "--state", "audit", "--step", "3")
        self.assertEqual(r.returncode, 3)
        self.assertIn("insight-advice.json", r.stderr)
        self.assertIn("--seed-advice", r.stderr)
        # 只有文件存在还不够：结构不完整必须被 --check 拦住
        self.write_file("insight-advice.json", "{}")
        r = run("confirm", self.dir, "--state", "audit", "--step", "3")
        self.assertEqual(r.returncode, 3)
        self.assertIn("校验未通过", r.stderr)
        self.write_valid_audit_pair()
        r = run("confirm", self.dir, "--state", "audit", "--step", "3")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_audit_confirm_step4_requires_both_reports(self):
        run("init", self.dir, "--mode", "audit")
        self.confirm_prior_steps(4)
        r = run("confirm", self.dir, "--state", "audit", "--step", "4")
        self.assertEqual(r.returncode, 3)
        self.assertIn("insight_audit_report.py", r.stderr)
        self.write_valid_audit_pair()
        self.write_file("insight-audit.md", "# 报告")
        self.write_file("insight-audit.html", "<html></html>")
        r = run("confirm", self.dir, "--state", "audit", "--step", "4")
        self.assertEqual(r.returncode, 3)
        reporter = os.path.join(os.path.dirname(__file__), "insight_audit_report.py")
        rendered = subprocess.run([sys.executable, reporter, self.dir], capture_output=True, text=True)
        self.assertEqual(rendered.returncode, 0, rendered.stderr)
        r = run("confirm", self.dir, "--state", "audit", "--step", "4")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_audit_confirm_step4_rejects_stale_report(self):
        """建议改过之后必须重新渲染报告，旧报告不能拿来确认。"""
        run("init", self.dir, "--mode", "audit")
        self.confirm_prior_steps(4)
        self.write_valid_audit_pair()
        self.write_file("insight-audit.md", "# 报告")
        self.write_file("insight-audit.html", "<html></html>")
        for name in ("insight-audit.md", "insight-audit.html"):
            os.utime(os.path.join(self.dir, name), (1000, 1000))
        r = run("confirm", self.dir, "--state", "audit", "--step", "4")
        self.assertEqual(r.returncode, 3)
        self.assertIn("不一致或内容不完整", r.stderr)

    def test_audit_does_not_touch_build_state(self):
        run("init", self.dir, "--name", "搭建档案", "--mode", "full")
        build_path = os.path.join(self.dir, "wizard-state.json")
        with open(build_path, encoding="utf-8") as f:
            before = f.read()
        r = run("init", self.dir, "--name", "诊断对象", "--mode", "audit")
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(build_path, encoding="utf-8") as f:
            after = f.read()
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
