#!/usr/bin/env python3
"""render_agent_skill.py 单测：占位符填零、看板/直通模式变体节、SQL 不可用替换、
lite 标注、extraRedLines 追加、缺字段与残留占位符拦截"""
import json, os, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "render_agent_skill.py")


def make_manifest(**over):
    m = {
        "slug": "yecai-finance",
        "scenario": "业财经营分析",
        "keywords": "收入/毛利/费用、达成率、归因",
        "dashboards": "管报洞察分析_收入》《集团管理报表_26年",
        "typicalQuestions": ["集团净收入多少？", "利润为什么没达标？",
                             "哪些渠道费用失控？", "出一份月度经营分析"],
    }
    m.update(over)
    return m


class RenderTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.mp = os.path.join(self.dir, "manifest.json")

    def render(self, manifest):
        with open(self.mp, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False)
        return subprocess.run([sys.executable, SCRIPT, "--manifest", self.mp],
                              capture_output=True, text=True)

    def test_dashboard_mode_renders_clean(self):
        r = self.render(make_manifest())
        self.assertEqual(r.returncode, 0, r.stderr)
        text = r.stdout
        self.assertNotIn("{", text)  # 占位符清零
        self.assertNotIn("数据探索型变体", text)  # 看板模式删除变体节
        for sec in ("## 使用方式", "## 对话体验规范", "## 记忆系统", "## 前置检查",
                    "## 执行流程", "## 数据红线", "## 维护"):
            self.assertIn(sec, text)
        self.assertIn("agent-yecai-finance", text)
        self.assertIn("业财经营分析", text)
        self.assertIn("集团净收入多少？", text)

    def test_dataset_mode_keeps_variant_and_fills_count(self):
        r = self.render(make_manifest(mode="dataset", datasetCount=5,
                                      dashboards="fact_sales_daily"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("数据探索型变体", r.stdout)
        self.assertIn("数据来自 5 个数据集", r.stdout)

    def test_dataset_mode_no_dangling_dashboard_refs(self):
        """直通模式产物不得引用不随包分发的看板模式资产（悬空引用渲染期拦截）"""
        r = self.render(make_manifest(mode="dataset", datasetCount=1,
                                      dashboards="fact_sales_daily"))
        self.assertEqual(r.returncode, 0, r.stderr)
        for ref in ("cards.json", "card-data", "sample_cards", "make_link"):
            self.assertNotIn(ref, r.stdout)
        self.assertNotIn("**看板直达链接**", r.stdout)  # 整节裁掉（变体节"没有看板直达链接"是能力边界声明，保留）
        # 取数主路径：datasets.json 路由 + run_metric 优先 + run_sql
        self.assertIn("references/datasets.json", r.stdout)
        self.assertIn("run_metric.py <metricId>", r.stdout)
        self.assertIn("governedRef", r.stdout)
        # 直通版数据出身行
        self.assertIn("来源：数据集名 · run_sql/run_metric 直查", r.stdout)
        self.assertNotIn("来源：《看板名》卡片名", r.stdout)

    def test_dataset_mode_description_and_self_intro_fixed(self):
        """description 写数据集而非看板；场景名以「数据探索」结尾时自我介绍不重复"""
        r = self.render(make_manifest(mode="dataset", datasetCount=1,
                                      scenario="门店日销数据探索",
                                      dashboards="fact_sales_daily"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("以观远 BI 数据集《fact_sales_daily》为数据来源", r.stdout)
        self.assertNotIn("以观远 BI 看板《", r.stdout)
        self.assertIn("数据来自《fact_sales_daily》", r.stdout)
        self.assertNotIn("数据探索数据探索", r.stdout)
        self.assertIn("我是您的门店日销数据探索助手", r.stdout)

    def test_dataset_mode_sql_unavailable_uses_dataset_note(self):
        r = self.render(make_manifest(mode="dataset", datasetCount=1,
                                      dashboards="fact_sales_daily", sqlAvailable=False))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("SQL 直查当前不可用", r.stdout)
        self.assertIn("取数以已验收示例的缓存结论为准", r.stdout)
        self.assertNotIn("💡 **SQL 直查即主路径**", r.stdout)

    def test_sql_unavailable_replaces_note(self):
        r = self.render(make_manifest(sqlAvailable=False))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("SQL 直查当前不可用", r.stdout)
        self.assertNotIn("💡 **SQL 直查触发条件**", r.stdout)

    def test_lite_and_build_note_annotated(self):
        r = self.render(make_manifest(lite=True, buildNote="10 条冲突已逐条裁决"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("快速模式", r.stdout)
        self.assertIn("10 条冲突已逐条裁决", r.stdout)

    def test_extra_red_lines_appended(self):
        r = self.render(make_manifest(extraRedLines=["3.5 预算口径达成率失真，用百分点偏差"]))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("- 3.5 预算口径达成率失真，用百分点偏差\n\n## 维护", r.stdout)

    def test_missing_required_key_rejected(self):
        m = make_manifest()
        del m["scenario"]
        r = self.render(m)
        self.assertEqual(r.returncode, 2)
        self.assertIn("scenario", r.stderr)

    def test_typical_questions_must_be_four(self):
        r = self.render(make_manifest(typicalQuestions=["只有一题"]))
        self.assertEqual(r.returncode, 2)
        self.assertIn("typicalQuestions", r.stderr)


if __name__ == "__main__":
    unittest.main()
