#!/usr/bin/env python3
"""build_package.py 单测：端到端机械组装（cards.json 与 cards-raw 字节一致=零裁剪）、
验收证据不足拒绝交付、双闸门拦截、--force 语义、memory 重建保留"""
import json, os, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "build_package.py")

CARDS_RAW = {
    "_meta": {
        "builderVersion": "4.7.0", "biBaseUrl": "https://bi.example.com",
        "dsFormulas": {"ds1": []},
        "pages": {"p1": {"title": "页一", "mtime": "x", "cardCount": 2, "cardHash": "h",
                         "cards": [{"cdId": "c1", "name": "卡A"}, {"cdId": "s1", "name": "展示渠道"}]}},
    },
    "页一": {
        "pgId": "p1",
        "dsUsage": {"ds1": {"cards": 1, "filteredCards": 0}},
        "cards": [
            {"name": "卡A", "cdId": "c1", "type": "TABLE", "dsId": "ds1",
             "measures": [{"name": "净收入", "formula": "sum([实际数])"}],
             "dims": ["展示渠道"], "filtered": False, "filterDetails": []},
            {"name": "展示渠道", "cdId": "s1", "type": "SELECTOR",
             "inFilterBar": True, "linkedCardCount": 2, "filters": ["展示渠道"]},
        ],
    },
}

SAMPLE = {"columns": ["指标", "值"], "rows": [["净收入", 41990]]}

MANIFEST = {"slug": "test-agent", "scenario": "测试经营分析",
            "keywords": "收入、达成率"}


def write_json(d, rel, doc):
    fp = os.path.join(d, rel)
    os.makedirs(os.path.dirname(fp), exist_ok=True)
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)


def write_text(d, rel, text):
    fp = os.path.join(d, rel)
    os.makedirs(os.path.dirname(fp), exist_ok=True)
    with open(fp, "w", encoding="utf-8") as f:
        f.write(text)


def make_workdir(d, confirmed=True):
    write_json(d, "cards-raw.json", CARDS_RAW)
    write_json(d, "card-data/页一__卡A.json", SAMPLE)
    write_json(d, "card-data/_sample_index.json", {})
    write_json(d, "formulas.json", {"metrics": [], "conflicts": []})
    write_json(d, "metrics.json", {"metrics": [], "rejected": []})
    write_json(d, "dimensions.json", {"dimensions": []})
    write_json(d, "outputFormat.json", {})
    for fn, t in (("learningResult.md", "# 资产目录"), ("businessKnowledge.md", "# 业务口径"),
                  ("insightThinking.md", "# 分析框架")):
        write_text(d, fn, t + "\n" + "x" * 400)
    scenarios = {}
    for i, sname in enumerate(("问数", "归因", "异常", "洞察")):
        scenarios[sname] = [{
            "id": f"Q{i+1}", "question": f"问题{i+1}",
            "fetch": {"type": "card", "file": "card-data/页一__卡A.json"},
            "expect": {"values": [41990], "keywords": ["净收入"]},
            "answerPoints": ["x"], "humanConfirmed": confirmed,
        }]
    write_json(d, "examples.json", {"scenarios": scenarios})
    write_json(d, "agent-manifest.json", MANIFEST)


class BuildPackageTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.workdir = os.path.join(self.dir, "work")
        self.pkg = os.path.join(self.dir, "skills", "agent-test-agent")
        os.makedirs(self.workdir)

    def build(self, *extra):
        return subprocess.run([sys.executable, SCRIPT, self.workdir,
                               "--package", self.pkg, *extra],
                              capture_output=True, text=True)

    def test_end_to_end_assembly(self):
        make_workdir(self.workdir)
        r = self.build()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        # cards.json 与 cards-raw.json 字节一致——零裁剪的硬证据
        with open(os.path.join(self.workdir, "cards-raw.json"), encoding="utf-8") as f:
            raw_text = f.read()
        with open(os.path.join(self.pkg, "references", "cards.json"), encoding="utf-8") as f:
            self.assertEqual(f.read(), raw_text)
        # SKILL.md 模板渲染：章节齐全、占位符清零、自动带入看板清单与典型问题
        with open(os.path.join(self.pkg, "SKILL.md"), encoding="utf-8") as f:
            skill = f.read()
        for sec in ("## 使用方式", "## 执行流程", "## 维护", "## 记忆系统"):
            self.assertIn(sec, skill)
        self.assertNotIn("{", skill)
        self.assertIn("页一", skill)
        self.assertIn("问题1", skill)
        # memory 初始化 + workbench.html + 体检凭证
        self.assertTrue(os.path.isfile(os.path.join(self.pkg, "memory", "_meta.json")))
        self.assertGreater(os.path.getsize(os.path.join(self.pkg, "workbench.html")), 10 * 1024)
        with open(os.path.join(self.workdir, "package-check.json"), encoding="utf-8") as f:
            record = json.load(f)
        self.assertEqual(record["result"], "pass", record["errors"])
        # 脚本复制齐全
        for fn in ("run_sql.py", "scope.py", "check_package.py", "eval_examples.py", "feedback.py"):
            self.assertTrue(os.path.isfile(os.path.join(self.pkg, "references", fn)), fn)

    def test_unconfirmed_examples_rejected(self):
        """验收未回填（本次 review 故障类）→ 前置校验 exit 2，禁止交付"""
        make_workdir(self.workdir, confirmed=False)
        r = self.build()
        self.assertEqual(r.returncode, 2)
        self.assertIn("humanConfirmed", r.stderr)

    def test_gate_failure_rejected(self):
        make_workdir(self.workdir)
        write_json(self.workdir, "metrics.json",
                   {"metrics": [{"name": "退款率", "pending": True}], "rejected": []})
        r = self.build()
        self.assertEqual(r.returncode, 2)
        self.assertIn("check_metrics", r.stderr)

    def test_existing_package_requires_force(self):
        make_workdir(self.workdir)
        os.makedirs(self.pkg)
        write_text(self.pkg, "占位.txt", "x")
        r = self.build()
        self.assertEqual(r.returncode, 2)
        self.assertIn("--force", r.stderr)

    def test_rebuild_with_force_preserves_memory(self):
        """重建（--force）只换 references/ 与 SKILL.md——memory/ 用户资产永不覆盖"""
        make_workdir(self.workdir)
        r = self.build()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        marker = '{"q": "历史问答"}\n'
        write_text(self.pkg, "memory/qa-log.jsonl", marker)
        r = self.build("--force")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        with open(os.path.join(self.pkg, "memory", "qa-log.jsonl"), encoding="utf-8") as f:
            self.assertEqual(f.read(), marker)

    def test_missing_manifest_rejected(self):
        make_workdir(self.workdir)
        os.unlink(os.path.join(self.workdir, "agent-manifest.json"))
        r = self.build()
        self.assertEqual(r.returncode, 2)
        self.assertIn("manifest", r.stderr)


if __name__ == "__main__":
    unittest.main()
