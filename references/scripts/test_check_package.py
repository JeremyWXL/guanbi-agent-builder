#!/usr/bin/env python3
"""check_package.py 单测：合法交付包通过；本次 review 发现的故障类（cards.json 裁剪、
验收未回填、SKILL.md 缺节、占位符残留、broken 回归基准、dsUsage 丢失）逐项被 ❌ 拦截"""
import json, os, shutil, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "check_package.py")

SCRIPTS_TO_COPY = ["attribute.py", "make_link.py", "memory.py", "check_metrics.py",
                   "check_dims.py", "eval_examples.py", "sample_cards.py", "run_sql.py",
                   "workbench.py", "scope.py", "scope_audit.py", "feedback.py",
                   "check_package.py"]

SKILL_MD = """---
name: agent-test
version: "1.0.0"
description: 测试助手
agent_created: true
---

# 测试 数据分析助手

## 使用方式
x
## 对话体验规范
x
## 记忆系统（memory/）
x
## 前置检查
x
## 执行流程
x
## 数据红线
x
## 维护
x
"""

CARDS_DOC = {
    "_meta": {
        "builderVersion": "4.7.0",
        "biBaseUrl": "https://bi.example.com",
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

EXAMPLES_DOC = {
    "version": 1,
    "scenarios": {
        "问数": [{
            "id": "Q1", "question": "净收入多少？",
            "route": {"pageName": "页一", "cards": ["卡A"]},
            "fetch": {"type": "card", "file": "card-data/页一__卡A.json"},
            "expect": {"values": [41990], "keywords": ["净收入"]},
            "answerPoints": ["x"], "humanConfirmed": True,
        }]
    },
}

SAMPLE_DOC = {"columns": ["指标", "值"], "rows": [["净收入", 41990]]}


def write_json(path, doc):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)


def write_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def make_dashboard_package(root):
    refs = os.path.join(root, "references")
    os.makedirs(refs, exist_ok=True)
    write_text(os.path.join(root, "SKILL.md"), SKILL_MD)
    write_text(os.path.join(root, "workbench.html"), "<html>" + "x" * 11000 + "</html>")
    write_text(os.path.join(root, "memory", "profile.md"), "# 用户画像")
    write_text(os.path.join(root, "memory", "qa-log.jsonl"), "")
    write_text(os.path.join(root, "memory", "corrections.json"), "[]")
    write_json(os.path.join(root, "memory", "_meta.json"), {"memorySchema": 1})
    write_json(os.path.join(refs, "cards.json"), CARDS_DOC)
    write_json(os.path.join(refs, "formulas.json"), {"metrics": [], "conflicts": []})
    write_json(os.path.join(refs, "metrics.json"), {"metrics": [], "rejected": []})
    write_json(os.path.join(refs, "dimensions.json"), {"dimensions": []})
    write_json(os.path.join(refs, "examples.json"), EXAMPLES_DOC)
    write_json(os.path.join(refs, "outputFormat.json"), {})
    write_text(os.path.join(refs, "sql-guide.md"), "# SQL 直查指南")
    write_text(os.path.join(refs, "learningResult.md"), "# 资产目录\n" + "x" * 400)
    write_text(os.path.join(refs, "businessKnowledge.md"), "# 业务口径\n" + "x" * 400)
    write_text(os.path.join(refs, "insightThinking.md"), "# 分析框架\n" + "x" * 400)
    write_json(os.path.join(refs, "card-data", "页一__卡A.json"), SAMPLE_DOC)
    write_json(os.path.join(refs, "card-data", "_sample_index.json"), {})
    for fn in SCRIPTS_TO_COPY:
        shutil.copy(os.path.join(HERE, fn), os.path.join(refs, fn))
    return root


def run(*args):
    return subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True)


class ValidPackageTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        make_dashboard_package(self.dir)

    def test_valid_dashboard_package_passes(self):
        r = run(self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("体检通过", r.stdout)

    def test_json_output(self):
        r = run(self.dir, "--json")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        doc = json.loads(r.stdout)
        self.assertEqual(doc["result"], "pass")
        self.assertEqual(doc["mode"], "dashboard")


class BrokenPackageTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        make_dashboard_package(self.dir)

    def out(self, r):
        return r.stdout + r.stderr

    def test_slim_cards_json_caught(self):
        """cards.json 被裁成纯卡片名列表（字符串条目）"""
        doc = json.loads(json.dumps(CARDS_DOC))
        doc["页一"]["cards"] = ["卡A", "展示渠道"]
        write_json(os.path.join(self.dir, "references", "cards.json"), doc)
        r = run(self.dir)
        self.assertEqual(r.returncode, 1)
        self.assertIn("不是对象", self.out(r))
        self.assertIn("cdIds 为空", self.out(r))  # scope 冒烟同步瘫痪

    def test_dict_shape_cards_json_caught(self):
        """实机故障类：cards.json 被重构成「名字→摘要」字典（cdId/measures 等全丢）"""
        doc = json.loads(json.dumps(CARDS_DOC))
        doc["页一"]["cards"] = {"卡A": {"type": "PIVOT_TABLE", "notes": ""},
                                "展示渠道": {"type": "SELECTOR", "notes": ""}}
        write_json(os.path.join(self.dir, "references", "cards.json"), doc)
        r = run(self.dir)
        self.assertEqual(r.returncode, 1)
        self.assertIn("字典形态", self.out(r))
        self.assertIn("cdIds 为空", self.out(r))

    def test_missing_dsusage_caught(self):
        """dsUsage 丢失 → scope dsIds 空集 → run_sql 全拦截（SQL 直查瘫痪）"""
        doc = json.loads(json.dumps(CARDS_DOC))
        del doc["页一"]["dsUsage"]
        write_json(os.path.join(self.dir, "references", "cards.json"), doc)
        r = run(self.dir)
        self.assertEqual(r.returncode, 1)
        self.assertIn("dsUsage", self.out(r))
        self.assertIn("dsIds 为空", self.out(r))

    def test_examples_not_confirmed_caught(self):
        doc = json.loads(json.dumps(EXAMPLES_DOC))
        doc["scenarios"]["问数"][0]["humanConfirmed"] = False
        write_json(os.path.join(self.dir, "references", "examples.json"), doc)
        r = run(self.dir)
        self.assertEqual(r.returncode, 1)
        self.assertIn("humanConfirmed", self.out(r))

    def test_examples_empty_expect_caught(self):
        doc = json.loads(json.dumps(EXAMPLES_DOC))
        doc["scenarios"]["问数"][0]["expect"] = {"values": [], "keywords": []}
        write_json(os.path.join(self.dir, "references", "examples.json"), doc)
        r = run(self.dir)
        self.assertEqual(r.returncode, 1)
        self.assertIn("数据层断言缺失", self.out(r))

    def test_broken_eval_baseline_caught(self):
        doc = json.loads(json.dumps(EXAMPLES_DOC))
        doc["scenarios"]["问数"][0]["expect"] = {"values": [99999999]}
        write_json(os.path.join(self.dir, "references", "examples.json"), doc)
        r = run(self.dir)
        self.assertEqual(r.returncode, 1)
        self.assertIn("数据层失败", self.out(r))

    def test_skill_md_missing_sections_caught(self):
        write_text(os.path.join(self.dir, "SKILL.md"),
                   "---\nname: x\nagent_created: true\n---\n# 助手\n## 使用方式\nx\n")
        r = run(self.dir)
        self.assertEqual(r.returncode, 1)
        self.assertIn("执行流程", self.out(r))
        self.assertIn("维护", self.out(r))

    def test_skill_md_placeholder_caught(self):
        write_text(os.path.join(self.dir, "SKILL.md"),
                   SKILL_MD.replace("测试 数据分析助手", "{业务场景} 数据分析助手"))
        r = run(self.dir)
        self.assertEqual(r.returncode, 1)
        self.assertIn("占位符", self.out(r))

    def test_missing_memory_file_caught(self):
        os.unlink(os.path.join(self.dir, "memory", "corrections.json"))
        r = run(self.dir)
        self.assertEqual(r.returncode, 1)
        self.assertIn("corrections.json", self.out(r))

    def test_missing_script_caught(self):
        os.unlink(os.path.join(self.dir, "references", "scope.py"))
        r = run(self.dir)
        self.assertEqual(r.returncode, 1)
        self.assertIn("scope.py", self.out(r))

    def test_missing_package_dir(self):
        r = run(os.path.join(self.dir, "不存在的包"))
        self.assertEqual(r.returncode, 1)
        self.assertIn("不存在", self.out(r))


class DatasetModeTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        make_dashboard_package(self.dir)
        refs = os.path.join(self.dir, "references")
        os.unlink(os.path.join(refs, "cards.json"))
        shutil.rmtree(os.path.join(refs, "card-data"))
        os.unlink(os.path.join(refs, "make_link.py"))
        os.unlink(os.path.join(refs, "sample_cards.py"))
        write_json(os.path.join(refs, "datasets.json"), {
            "_meta": {"builderVersion": "4.7.0"},
            "数据集一": {"dsId": "ds1", "columns": []},
        })
        # 直通模式示例走 sql 取数；测试环境无 guancli，用 card 形态夹具规避（结构校验才是本测试目的）
        write_json(os.path.join(refs, "examples.json"), {
            "scenarios": {"问数": [{
                "id": "Q1", "question": "q",
                "fetch": {"type": "card", "file": "样本.json"},
                "expect": {"values": [41990]}, "humanConfirmed": True}]},
        })
        write_json(os.path.join(refs, "样本.json"), SAMPLE_DOC)

    def test_valid_dataset_package_passes(self):
        r = run(self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("数据集直通", r.stdout)


if __name__ == "__main__":
    unittest.main()
