#!/usr/bin/env python3
"""insight_audit_report.py 的单测：draft 渲染、建议校验（引用完整性/阻断覆盖/体检版本/联动筛选器）、
合法报告渲染、HTML 转义、--check 不写文件。"""
import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "insight_audit_report.py")

AUDIT = {
    "meta": {
        "builtAt": "2026-10-22 10:00",
        "builderVersion": "4.10.0",
        "scenario": "华东单店业绩下滑归因",
        "pageCount": 2,
        "maxPages": 10,
        "biBaseUrl": "https://bi.example.com",
        "inputs": {"pageCheck": True, "formulas": True, "samples": False},
    },
    "pages": [
        {
            "pgId": "pgA",
            "name": "经营总览",
            "verdict": "blocker",
            "facts": {"dataCards": 12, "selectors": 5, "linkageSelectors": 0,
                      "tableCards": 0, "maxRawRows": None, "mtime": "2026-10-01"},
            "scores": {"focus": 12, "metrics": 16, "linkage": 0, "layers": 12, "context": 8, "ops": 8},
            "total": 56,
            "grade": "需改造",
            "findings": ["F-001", "F-003"],
        },
        {
            "pgId": "pgB",
            "name": "单店明细<script>alert(1)</script>",
            "verdict": "warn",
            "facts": {
                "dataCards": 22,
                "selectors": 3,
                "linkageSelectorIds": ["cd-9"],
                "cards": [
                    {"cdId": "cd-9", "name": "区域", "inFilterBar": True, "linkedCardCount": 3},
                    {"cdId": "cd-8", "name": "隐藏筛选", "inFilterBar": False, "linkedCardCount": 3},
                    {"cdId": "cd-7", "name": "无人关联", "inFilterBar": True, "linkedCardCount": 0},
                ],
                "maxRawRows": 12000,
                "mtime": "2026-09-20",
            },
            "scores": {"focus": 8, "metrics": 12, "linkage": 25, "layers": 12, "context": 0, "ops": 8},
            "total": 65,
            "grade": "小改后配置",
            "findings": ["F-002", "F-004"],
        },
    ],
    "cross": {
        "overlaps": [],
        "sharedLinkageDims": [{"field": "区域", "pages": ["pgB"]}],
        "conflicts": [],
        "layers": {"overview": ["pgA"], "mid": [], "detail": ["pgB"]},
    },
    "findings": [
        {"id": "F-001", "rule": "R-02", "level": "blocker", "scope": "page:pgA",
         "evidence": "筛选栏内无联动筛选器（5 个筛选器均 linkedCardCount=0）",
         "requirement": "每张仪表板必须选联动筛选器",
         "source": "官方文档·新建智能体",
         "action": "在页面筛选栏配置至少一个联动筛选器（区域/门店/品类）"},
        {"id": "F-002", "rule": "R-06", "level": "p1", "scope": "page:pgB",
         "evidence": "单页 22 张数据卡，超过 20 张",
         "requirement": "单页数据卡不超过 20 张",
         "source": "规则 R-06",
         "action": "拆分页面或移出低价值卡片"},
        {"id": "F-003", "rule": "R-05", "level": "p0", "scope": "page:pgA",
         "evidence": "「销售额」在两张卡片中公式不一致",
         "requirement": "指标口径由看板固化",
         "source": "官方文档·业务知识",
         "action": "统一到同一数据源与同一公式"},
        {"id": "F-004", "rule": "R-10", "level": "p2", "scope": "page:pgB",
         "evidence": "卡片名「图1」「副本-区域」不可读",
         "requirement": "卡片标题能被 Agent 理解",
         "source": "规则 R-10",
         "action": "改名为「指标 + 维度 + 口径」"},
    ],
    "portfolio": {"score": 60, "grade": "需改造", "overall": 61},
    "recommendedMode": {"primary": "多层下钻", "alternatives": ["主从Agent"], "reason": "存在总览与明细两层"},
}


def advice_doc():
    return {
        "auditBuiltAt": "2026-10-22 10:00",
        "scenario": "华东单店业绩下滑归因",
        "businessScope": "连锁零售单店经营异常定位与归因",
        "mode": {"primary": "多层下钻", "alternatives": ["主从Agent"],
                 "reason": "pgA 是总览层、pgB 是明细层，缺门店粒度承接"},
        "targetArchitecture": [
            {"layer": "总览", "pages": ["pgA"], "purpose": "判断整体是否异常",
             "linkageFilters": [], "newPage": False},
            {"layer": "明细", "pages": ["NEW"], "purpose": "把结论落到门店",
             "linkageFilters": [], "newPage": True},
        ],
        "pageActions": [
            {"pgId": "pgA", "name": "经营总览", "verdict": "改造", "priority": "P0",
             "actions": ["补区域联动筛选器", "统一销售额公式"],
             "evidence": ["F-001", "F-003"], "expectedEffect": "Agent 能按区域传参并读到唯一口径"},
            {"pgId": "pgB", "name": "单店明细", "verdict": "保留", "priority": "P2",
             "actions": ["清理不可读卡名"], "evidence": ["F-004"],
             "expectedEffect": "减少命名歧义"},
            {"pgId": "NEW", "name": "单店异常明细页", "verdict": "新建", "priority": "P1",
             "actions": ["新建门店粒度明细页，含区域/门店筛选器与销售额、客流两列"],
             "evidence": ["F-002"], "expectedEffect": "结论可落到具体门店"},
        ],
        "cardReuse": [
            {"sourcePgId": "pgA", "target": "NEW", "targetName": "经营总览_洞察版",
             "method": "rebuild", "keepCards": [], "dropCards": ["装饰卡"],
             "rebuildCards": ["销售额趋势"], "reason": "只重建核心趋势卡，拆掉装饰卡", "commands": []},
        ],
        "crossPageActions": [
            {"type": "补筛选器", "pages": ["pgA", "pgB"], "priority": "P0",
             "action": "两页统一区域联动筛选器并保持字段名一致", "evidence": ["F-001"]},
        ],
        "configHandoff": {
            "linkageFilters": [
                {"pgId": "pgB", "name": "区域", "field": "区域", "cdId": "cd-9"},
            ],
            "businessScope": "连锁零售单店经营异常定位与归因",
            "agentType": "报告型",
            "defaultThinking": "Step 1 总览定位 → Step 2 区域拆解 → Step 3 门店下钻 → Step 4 归因建议",
            "stepPlan": [
                {"step": 1, "goal": "判断整体是否异常", "dashboards": ["pgA"],
                 "coreQuestions": ["哪些核心指标偏离？", "偏离幅度多大？"],
                 "cards": ["销售额趋势"], "filters": ["时间"],
                 "output": "一句话定调 + 核心指标偏离清单",
                 "nextIf": "存在明显偏离则进入 Step 2", "stopIf": "无显著偏离则输出结论并结束"},
                {"step": 2, "goal": "定位异常区域并下钻到门店", "dashboards": ["pgB"],
                 "coreQuestions": ["哪个区域贡献最大？", "哪些门店需要处理？"],
                 "cards": ["门店销售额"], "filters": ["时间", "区域"],
                 "output": "异常区域与门店清单（带贡献额）",
                 "nextIf": "需要归因则进入 Step 3", "stopIf": "已能给出建议则结束"},
            ],
            "exploratoryRules": ["先总览再下钻，允许回退", "筛选参数必须来自看板已声明筛选器"],
            "reportFramework": ["1. 结论摘要", "2. 核心指标", "3. 异常清单", "4. 原因与建议"],
            "questionExamples": [
                "出一份 2026 年 9 月华东区域单店经营诊断报告。",
                "对比 9 月和 8 月，找出下滑最严重的 20 家门店并给出原因。",
                "本周经营例会：输出需要重点讨论的 5 个门店问题。",
            ],
            "outputRequirements": "结论必须带数据范围与口径，建议绑定到具体门店",
            "businessKnowledgeGaps": ["异常阈值由业务定义", "责任部门映射缺失"],
            "expertRoles": [{"name": "门店经营专家", "scope": "门店经营",
                             "reason": "涉及门店与商品两个域"}],
        },
        "roadmap": [
            {"phase": "P0", "items": ["补区域联动筛选器", "统一销售额公式"], "effort": "约 1-2 人天"},
            {"phase": "P1", "items": ["新建门店明细页"], "effort": "约 3-5 人天"},
        ],
        "openQuestions": ["业绩下滑的异常阈值是多少？", "责任部门如何映射到区域？"],
    }


class ReportTestBase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def write_audit(self, doc=None):
        with open(os.path.join(self.dir, "insight-audit.json"), "w", encoding="utf-8") as f:
            json.dump(AUDIT if doc is None else doc, f, ensure_ascii=False)

    def write_advice(self, doc=None):
        with open(os.path.join(self.dir, "insight-advice.json"), "w", encoding="utf-8") as f:
            json.dump(advice_doc() if doc is None else doc, f, ensure_ascii=False)

    def run_script(self, *extra):
        return subprocess.run([sys.executable, SCRIPT, self.dir, *extra],
                              capture_output=True, text=True, timeout=60)

    def read(self, name):
        with open(os.path.join(self.dir, name), encoding="utf-8") as f:
            return f.read()


class TestDraft(ReportTestBase):
    def test_draft_renders_without_advice(self):
        self.write_audit()
        r = self.run_script("--draft")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("DRAFT_HTML=", r.stdout)
        md = self.read("insight-audit-draft.md")
        html = self.read("insight-audit-draft.html")
        self.assertIn("结构体检草稿", md)
        self.assertIn("尚未生成整合建议", md)
        self.assertIn("尚未生成整合建议", html)
        self.assertIn("体检总表", html)
        self.assertIn("F-001", html)
        self.assertIn("R-02", md)
        self.assertIn("> 结论：", md)
        self.assertFalse(os.path.exists(os.path.join(self.dir, "insight-audit.html")))

    def test_missing_audit_exits_2(self):
        r = self.run_script("--draft")
        self.assertEqual(r.returncode, 2)
        self.assertIn("insight-audit.json", r.stderr)

    def test_broken_audit_exits_2(self):
        with open(os.path.join(self.dir, "insight-audit.json"), "w", encoding="utf-8") as f:
            f.write("{not json")
        r = self.run_script("--draft")
        self.assertEqual(r.returncode, 2)
        self.assertIn("无法解析", r.stderr)


class TestValidation(ReportTestBase):
    def setUp(self):
        super().setUp()
        self.write_audit()

    def check(self, doc):
        self.write_advice(doc)
        return self.run_script("--check")

    def test_valid_advice_passes(self):
        r = self.check(advice_doc())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("建议校验通过", r.stdout)

    def test_report_type_requires_step_plan(self):
        doc = advice_doc()
        doc["configHandoff"]["stepPlan"] = []
        r = self.check(doc)
        self.assertEqual(r.returncode, 2)
        self.assertIn("至少 2 步", r.stderr)

    def test_report_type_requires_framework(self):
        doc = advice_doc()
        doc["configHandoff"]["reportFramework"] = []
        r = self.check(doc)
        self.assertEqual(r.returncode, 2)
        self.assertIn("至少 3 章", r.stderr)

    def test_report_type_requires_question_examples(self):
        doc = advice_doc()
        doc["configHandoff"]["questionExamples"] = []
        r = self.check(doc)
        self.assertEqual(r.returncode, 2)
        self.assertIn("至少 3 个", r.stderr)

    def test_card_reuse_required_for_restructure(self):
        doc = advice_doc()
        doc["cardReuse"] = []
        r = self.check(doc)
        self.assertEqual(r.returncode, 2)
        self.assertIn("cardReuse 为空", r.stderr)

    def test_card_reuse_rejects_page_save_as(self):
        doc = advice_doc()
        doc["cardReuse"][0]["method"] = "page_save_as"
        r = self.check(doc)
        self.assertEqual(r.returncode, 2)
        self.assertIn("不在 rebuild/keep 内", r.stderr)

    def test_card_reuse_rebuild_requires_cards(self):
        doc = advice_doc()
        doc["cardReuse"][0]["rebuildCards"] = []
        doc["cardReuse"][0]["keepCards"] = ["旧卡"]
        r = self.check(doc)
        self.assertEqual(r.returncode, 2)
        self.assertIn("必须写 rebuildCards", r.stderr)

    def test_card_reuse_keep_requires_cards(self):
        doc = advice_doc()
        doc["cardReuse"][0]["method"] = "keep"
        doc["cardReuse"][0]["keepCards"] = []
        r = self.check(doc)
        self.assertEqual(r.returncode, 2)
        self.assertIn("必须写 keepCards", r.stderr)

    def test_exploratory_requires_rules(self):
        doc = advice_doc()
        doc["configHandoff"]["agentType"] = "探索型"
        doc["configHandoff"]["exploratoryRules"] = []
        r = self.check(doc)
        self.assertEqual(r.returncode, 2)
        self.assertIn("exploratoryRules 至少 2 条", r.stderr)

    def test_mixed_requires_both_tracks(self):
        doc = advice_doc()
        doc["configHandoff"]["agentType"] = "混合型"
        doc["configHandoff"]["stepPlan"] = []
        doc["configHandoff"]["exploratoryRules"] = []
        doc["configHandoff"]["reportFramework"] = []
        doc["configHandoff"]["questionExamples"] = []
        r = self.check(doc)
        self.assertEqual(r.returncode, 2)
        self.assertIn("混合型", r.stderr)
        self.assertIn("stepPlan", r.stderr)
        self.assertIn("reportFramework", r.stderr)

    def test_step_plan_unknown_dashboard_exits_2(self):
        doc = advice_doc()
        doc["configHandoff"]["stepPlan"][0]["dashboards"] = ["pgZ"]
        r = self.check(doc)
        self.assertEqual(r.returncode, 2)
        self.assertIn("pgZ", r.stderr)

    def test_step_plan_missing_next_if_exits_2(self):
        doc = advice_doc()
        doc["configHandoff"]["stepPlan"][0]["nextIf"] = ""
        r = self.check(doc)
        self.assertEqual(r.returncode, 2)
        self.assertIn("nextIf", r.stderr)

    def test_unknown_pgid_exits_2(self):
        doc = advice_doc()
        doc["pageActions"][0]["pgId"] = "pgZ"
        r = self.check(doc)
        self.assertEqual(r.returncode, 2)
        self.assertIn("pgZ", r.stderr)

    def test_unknown_finding_exits_2(self):
        doc = advice_doc()
        doc["crossPageActions"][0]["evidence"] = ["F-999"]
        r = self.check(doc)
        self.assertEqual(r.returncode, 2)
        self.assertIn("F-999", r.stderr)

    def test_blocker_without_p0_exits_2(self):
        doc = advice_doc()
        for action in doc["pageActions"]:
            action["priority"] = "P1"
        for action in doc["crossPageActions"]:
            action["priority"] = "P1"
        r = self.check(doc)
        self.assertEqual(r.returncode, 2)
        self.assertIn("F-001", r.stderr)
        self.assertIn("阻断", r.stderr)

    def test_audit_built_at_mismatch_exits_2(self):
        doc = advice_doc()
        doc["auditBuiltAt"] = "2026-10-21 09:00"
        r = self.check(doc)
        self.assertEqual(r.returncode, 2)
        self.assertIn("auditBuiltAt", r.stderr)

    def test_invalid_linkage_cd_id_exits_2(self):
        doc = advice_doc()
        doc["configHandoff"]["linkageFilters"][0]["cdId"] = "cd-8"
        r = self.check(doc)
        self.assertEqual(r.returncode, 2)
        self.assertIn("cd-8", r.stderr)

    def test_linkage_not_in_filter_bar_rejected(self):
        # cd-7 在筛选栏内但 linkedCardCount=0，不能当联动筛选器
        doc = advice_doc()
        doc["configHandoff"]["linkageFilters"][0]["cdId"] = "cd-7"
        r = self.check(doc)
        self.assertEqual(r.returncode, 2)
        self.assertIn("cd-7", r.stderr)

    def test_invalid_mode_exits_2(self):
        doc = advice_doc()
        doc["mode"]["primary"] = "随便看看"
        r = self.check(doc)
        self.assertEqual(r.returncode, 2)
        self.assertIn("五模式", r.stderr)

    def test_missing_required_key_exits_2(self):
        doc = advice_doc()
        del doc["openQuestions"]
        r = self.check(doc)
        self.assertEqual(r.returncode, 2)
        self.assertIn("openQuestions", r.stderr)

    def test_placeholder_advice_rejected(self):
        doc = advice_doc()
        doc["businessScope"] = "<对象 + 场景 + 决策，一句话>"
        r = self.check(doc)
        self.assertEqual(r.returncode, 2)
        self.assertIn("占位符", r.stderr)

    def test_new_page_requires_name_and_actions(self):
        doc = advice_doc()
        doc["pageActions"][2]["actions"] = []
        doc["pageActions"][2]["expectedEffect"] = ""
        r = self.check(doc)
        self.assertEqual(r.returncode, 2)
        self.assertIn("expectedEffect", r.stderr)
        self.assertIn("actions", r.stderr)

    def test_new_page_must_appear_in_architecture(self):
        doc = advice_doc()
        doc["targetArchitecture"] = [doc["targetArchitecture"][0]]
        r = self.check(doc)
        self.assertEqual(r.returncode, 2)
        self.assertIn("NEW", r.stderr)

    def test_long_business_scope_only_warns(self):
        doc = advice_doc()
        doc["businessScope"] = "经营分析" * 80
        r = self.check(doc)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("300", r.stdout)

    def test_linkage_cd_id_unverifiable_only_warns(self):
        # 真实体检产物常只保留数量、不留 cdId：此时降级为提醒，不阻断
        audit = copy.deepcopy(AUDIT)
        audit["pages"][1]["facts"] = {"dataCards": 22, "selectors": 3, "linkageSelectors": 4}
        self.write_audit(audit)
        r = self.check(advice_doc())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("跳过 cdId 机械校验", r.stdout)

    def test_linkage_cd_id_rejected_when_page_has_none(self):
        audit = copy.deepcopy(AUDIT)
        audit["pages"][1]["facts"] = {"dataCards": 22, "selectors": 3, "linkageSelectors": 0}
        self.write_audit(audit)
        r = self.check(advice_doc())
        self.assertEqual(r.returncode, 2)
        self.assertIn("没有联动筛选器", r.stderr)

    def test_all_errors_reported_together(self):
        doc = advice_doc()
        doc["auditBuiltAt"] = "2020-01-01 00:00"
        doc["pageActions"][0]["pgId"] = "pgZ"
        doc["pageActions"][1]["evidence"] = ["F-404"]
        r = self.check(doc)
        self.assertEqual(r.returncode, 2)
        self.assertIn("4 个错误", r.stderr)
        self.assertIn("pgZ", r.stderr)
        self.assertIn("F-404", r.stderr)
        self.assertIn("auditBuiltAt", r.stderr)
        self.assertIn("没有逐页动作", r.stderr)


class TestReport(ReportTestBase):
    def setUp(self):
        super().setUp()
        self.write_audit()

    def test_valid_advice_renders_md_and_html(self):
        self.write_advice()
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        md = self.read("insight-audit.md")
        html = self.read("insight-audit.html")
        for name, body in (("md", md), ("html", html)):
            for section in ("结论摘要", "目标场景", "体检总表", "关键发现", "整合建议",
                            "逐页调整清单", "配置衔接", "落地路线图", "待确认问题", "看板与卡片清单"):
                self.assertIn(section, body, "{} 缺章节 {}".format(name, section))
            self.assertIn("多层下钻", body)
            self.assertIn("F-001", body)
            self.assertIn("R-02", body)
            self.assertIn("单店异常明细页", body)
            self.assertIn("约 1-2 人天", body)

        self.assertIn("61/100", md)
        self.assertIn("https://bi.example.com/page/pgA", md)
        self.assertIn("https://bi.example.com/page/pgA", html)
        self.assertIn("<!DOCTYPE html>", html)
        self.assertNotIn("尚未生成整合建议", html)

    def test_html_escapes_page_name(self):
        self.write_advice()
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        html = self.read("insight-audit.html")
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
        self.assertNotIn("<script>alert(1)</script>", html)

    def test_html_escapes_advice_text(self):
        doc = advice_doc()
        doc["openQuestions"] = ["阈值是不是 <5% ？<img src=x onerror=alert(1)>"]
        self.write_advice(doc)
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        html = self.read("insight-audit.html")
        self.assertIn("&lt;img src=x onerror=alert(1)&gt;", html)
        self.assertNotIn("<img src=x", html)

    def test_uppercase_levels_supported(self):
        # 体检器把级别写成 P0/P1/P2（大写），渲染与校验都必须兼容
        audit = copy.deepcopy(AUDIT)
        audit["meta"]["builtAt"] = "2026-10-22 10:00"
        for finding in audit["findings"]:
            finding["level"] = finding["level"].upper()
        self.write_audit(audit)
        self.write_advice()
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        html = self.read("insight-audit.html")
        md = self.read("insight-audit.md")
        self.assertIn("P0（", html)
        self.assertIn("### P0", md)
        self.assertIn("阻断项", html)

    def test_check_writes_no_files(self):
        self.write_advice()
        before = set(os.listdir(self.dir))
        r = self.run_script("--check")
        self.assertEqual(r.returncode, 0, r.stderr)
        after = set(os.listdir(self.dir))
        self.assertEqual(before, after)
        self.assertFalse(os.path.exists(os.path.join(self.dir, "insight-audit.html")))
        self.assertFalse(os.path.exists(os.path.join(self.dir, "insight-audit.md")))

    def test_custom_advice_path(self):
        other = os.path.join(self.dir, "my-advice.json")
        with open(other, "w", encoding="utf-8") as f:
            json.dump(advice_doc(), f, ensure_ascii=False)
        r = self.run_script("--advice", other)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.exists(os.path.join(self.dir, "insight-audit.html")))

    def test_invalid_advice_writes_no_report(self):
        doc = advice_doc()
        doc["auditBuiltAt"] = "2000-01-01 00:00"
        self.write_advice(doc)
        r = self.run_script()
        self.assertEqual(r.returncode, 2)
        self.assertFalse(os.path.exists(os.path.join(self.dir, "insight-audit.html")))
        self.assertFalse(os.path.exists(os.path.join(self.dir, "insight-audit.md")))

    def test_missing_advice_exits_2(self):
        r = self.run_script()
        self.assertEqual(r.returncode, 2)
        self.assertIn("insight-advice.json", r.stderr)


class TestTolerantAudit(unittest.TestCase):
    """体检 JSON 缺 facts/scores/inputs 时不应 KeyError。"""

    def test_minimal_audit_draft(self):
        workdir = tempfile.mkdtemp()
        doc = {
            "meta": {"builtAt": "2026-10-22 10:00", "pageCount": 1},
            "pages": [{"pgId": "p1", "name": "总览"}],
            "findings": [{"id": "F-001", "level": "blocker"}],
        }
        with open(os.path.join(workdir, "insight-audit.json"), "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False)
        r = subprocess.run([sys.executable, SCRIPT, workdir, "--draft"],
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(os.path.join(workdir, "insight-audit-draft.html"), encoding="utf-8") as f:
            body = f.read()
        self.assertIn("总览", body)
        self.assertIn("F-001", body)


if __name__ == "__main__":
    unittest.main()
