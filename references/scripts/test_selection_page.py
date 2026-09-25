#!/usr/bin/env python3
"""selection_page.py 的最小单测：渲染内容、HTML 转义、缺输入文件报错"""
import json, os, subprocess, sys, tempfile, unittest

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "selection_page.py")

CHECK_DOC = {
    "builtAt": "2026-09-25 15:00",
    "staleDays": 90,
    "pages": [
        {"pgId": "p1", "verdict": "✅", "name": "经营<驾驶舱>", "reasons": [],
         "notes": ["自带下钻路径"], "signals": {}},
        {"pgId": "p2", "verdict": "⛔", "name": "大屏", "reasons": ["页面类型是「数据大屏」"],
         "signals": {"pgType": "LARGE_SCREEN"}},
    ],
}


class TestSelectionPage(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        with open(os.path.join(self.dir, "page-check.json"), "w", encoding="utf-8") as f:
            json.dump(CHECK_DOC, f, ensure_ascii=False)

    def run_script(self, *extra):
        return subprocess.run([sys.executable, SCRIPT, self.dir, *extra],
                              capture_output=True, text=True, timeout=30)

    def test_render_happy_path(self):
        r = self.run_script("--scope", "只看国内")
        self.assertEqual(r.returncode, 0, r.stderr)
        out = os.path.join(self.dir, "selection.html")
        self.assertTrue(os.path.exists(out))
        with open(out, encoding="utf-8") as f:
            body = f.read()
        self.assertIn("只看国内", body)
        self.assertIn("适合", body)
        self.assertIn("不可用", body)
        self.assertIn("页面类型是「数据大屏」", body)

    def test_html_escaping(self):
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(os.path.join(self.dir, "selection.html"), encoding="utf-8") as f:
            body = f.read()
        self.assertIn("经营&lt;驾驶舱&gt;", body)
        self.assertNotIn("经营<驾驶舱>", body)

    def test_missing_page_check_exits(self):
        os.remove(os.path.join(self.dir, "page-check.json"))
        r = self.run_script()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("page-check.json", r.stderr)


if __name__ == "__main__":
    unittest.main()
