#!/usr/bin/env python3
"""模板-CLI 一致性：agent-SKILL.md 模板里 documented 的命令必须与脚本真实接口一致——
CLI 用法漂移（凭记忆写错 flag / 漏必填参数）在此被拦截，单一事实源是脚本源码本身。
校验项:
  1. 模板引用的每个 references/X.py 都真实存在
  2. 模板命令行里的每个 --flag 都出现在对应脚本的源码中（防止文档写出不存在的参数）
  3. 关键命令的必填参数在模板命令行里齐全（防止漏 --question 这类"照着做必报错"的漂移）
  4. 模板占位符不超出已知集合（新增占位符必须同步 render_agent_skill.py）
"""
import os, re, sys, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, "..", "templates", "agent-SKILL.md")

KNOWN_PLACEHOLDERS = {
    "{场景名}", "{业务场景}", "{看板清单}", "{典型问题关键词列表}", "{日期}",
    "{典型问题1}", "{典型问题2}", "{典型问题3}", "{典型问题4}",
}
# 关键命令的必填参数（事实源：各脚本 docstring 用法行与参数解析代码）
MANDATORY = {
    ("memory.py", "log"): ["--question"],
    ("memory.py", "correct"): ["--type", "--before", "--after", "--target"],
    ("feedback.py", None): ["--title", "--description"],
}


def template_lines():
    with open(TEMPLATE, encoding="utf-8") as f:
        return f.read().splitlines()


class TemplateCliConsistencyTest(unittest.TestCase):
    def setUp(self):
        self.lines = template_lines()

    def test_referenced_scripts_exist(self):
        refs = set()
        for ln in self.lines:
            refs.update(re.findall(r"references/([a-z_]+\.py)", ln))
        self.assertTrue(refs, "模板未引用任何脚本——模板结构可能已漂移")
        for fn in sorted(refs):
            self.assertTrue(os.path.isfile(os.path.join(HERE, fn)),
                            f"模板引用了不存在的脚本 references/{fn}")

    def test_documented_flags_exist_in_script_source(self):
        source_cache = {}
        for ln in self.lines:
            for m in re.finditer(r"python3\s+references/([a-z_]+\.py)\b([^\n`]*)", ln):
                fn, rest = m.group(1), m.group(2)
                path = os.path.join(HERE, fn)
                if not os.path.isfile(path):
                    continue  # 由 test_referenced_scripts_exist 报告
                if fn not in source_cache:
                    with open(path, encoding="utf-8") as f:
                        source_cache[fn] = f.read()
                for flag in re.findall(r"--[a-zA-Z][\w-]*", rest):
                    self.assertIn(flag, source_cache[fn],
                                  f"模板为 {fn} 文档化了源码中不存在的参数 {flag}: {ln.strip()[:80]}")

    def test_mandatory_flags_present_in_template_commands(self):
        for (fn, sub), flags in MANDATORY.items():
            hit = False
            for ln in self.lines:
                if fn not in ln:
                    continue
                if sub and not re.search(re.escape(fn) + r"\s+" + re.escape(sub) + r"\b", ln):
                    continue
                hit = True
                for flag in flags:
                    self.assertIn(flag, ln,
                                  f"模板里 {fn} {sub or ''} 命令缺少必填参数 {flag}: {ln.strip()[:80]}")
            self.assertTrue(hit, f"模板中找不到 {fn} {sub or ''} 的命令示例——"
                                 "交付助手将不知道这个关键入口")

    def test_placeholders_within_known_set(self):
        with open(TEMPLATE, encoding="utf-8") as f:
            text = f.read()
        found = set(re.findall(r"\{[^{}\n]{1,30}\}", text))
        unknown = found - KNOWN_PLACEHOLDERS
        self.assertFalse(unknown,
                         f"模板出现未知占位符 {unknown}——需同步 render_agent_skill.py 的填充表与本测试")


if __name__ == "__main__":
    unittest.main()
