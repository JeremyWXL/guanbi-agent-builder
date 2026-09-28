#!/usr/bin/env python3
"""feedback.py 单测：版本提取（仓库/交付包两种布局）、上下文收集、正文组合、
SkillHub 500 字上限、dry-run 不发送、CLI 缺失/未登录的失败路径（mock subprocess）"""
import json, os, sys, tempfile, unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import feedback

SKILL_MD = """---
name: guanbi-agent-builder
version: "4.6.0"
---
# body
"""


def make_layout(skills_subdir=True, with_state=None):
    """仓库布局：root/SKILL.md + root/references/scripts/feedback.py"""
    d = tempfile.mkdtemp()
    os.makedirs(os.path.join(d, "references", "scripts"))
    with open(os.path.join(d, "SKILL.md"), "w", encoding="utf-8") as f:
        f.write(SKILL_MD)
    if with_state:
        with open(os.path.join(d, "wizard-state.json"), "w", encoding="utf-8") as f:
            json.dump(with_state, f, ensure_ascii=False)
    return d


def patch_at(dirpath):
    """把 feedback.__file__ 补丁到 dirpath/feedback.py（dirpath 须真实存在，
    否则路径里 .. 段解析不到 SKILL.md）"""
    return mock.patch.object(feedback, "__file__", os.path.join(dirpath, "feedback.py"))


class VersionTest(unittest.TestCase):
    def test_repo_layout_version(self):
        with patch_at(os.path.join(make_layout(), "references", "scripts")):
            self.assertEqual(feedback.find_builder_version(), "4.6.0")

    def test_package_layout_version(self):
        # 交付包布局：feedback.py 在 references/ 下，SKILL.md 在包根（第二候选命中）
        pkg = tempfile.mkdtemp()
        os.makedirs(os.path.join(pkg, "references"))
        with open(os.path.join(pkg, "SKILL.md"), "w", encoding="utf-8") as f:
            f.write(SKILL_MD)
        with patch_at(os.path.join(pkg, "references")):  # 包布局：候选 ../SKILL.md 命中包根
            self.assertEqual(feedback.find_builder_version(), "4.6.0")


class ContextTest(unittest.TestCase):
    def test_collect_with_state(self):
        d = make_layout(with_state={"currentStep": 4, "status": "confirming",
                                    "mode": "lite", "updatedAt": "2026-09-28 10:00"})
        with patch_at(os.path.join(d, "references", "scripts")):
            ctx = feedback.collect_context(d)
        self.assertEqual(ctx["builderVersion"], "4.6.0")
        self.assertIn("第 4 步", ctx["progress"])
        self.assertIn("模式 lite", ctx["progress"])

    def test_collect_without_state_graceful(self):
        d = make_layout()
        with patch_at(os.path.join(d, "references", "scripts")):
            ctx = feedback.collect_context(d)
        self.assertNotIn("progress", ctx)


class ComposeTest(unittest.TestCase):
    def setUp(self):
        self.ctx = {"builderVersion": "4.6.0", "platform": "Darwin 24.0",
                    "python": "3.9.6", "guancli": "已安装",
                    "progress": "搭建进度（第 4 步，状态 confirming，模式 full，更新于 t）"}

    def test_issue_body_has_context_and_no_data_files(self):
        title, body = feedback.compose_issue("口径确认页报错", "用户说点确认没反应", self.ctx)
        self.assertEqual(title, "口径确认页报错")
        self.assertIn("builder 版本：4.6.0", body)
        self.assertIn("搭建进度", body)
        self.assertIn("不含业务数据", body)

    def test_comment_within_limit(self):
        text = feedback.compose_comment("标题", "描述一句话", self.ctx)
        self.assertLessEqual(len(text), feedback.SKILLHUB_LIMIT)
        self.assertIn("【用户反馈】标题", text)

    def test_comment_over_limit_rejected(self):
        with self.assertRaises(feedback.FeedbackError):
            feedback.compose_comment("标题", "长" * 600, self.ctx)


class SendTest(unittest.TestCase):
    def test_github_missing_gh(self):
        with mock.patch.object(feedback.shutil, "which", return_value=None):
            with self.assertRaises(feedback.FeedbackError):
                feedback.send_github("t", "b")

    def test_github_not_logged_in(self):
        with mock.patch.object(feedback.shutil, "which", return_value="/usr/bin/gh"), \
             mock.patch.object(feedback.subprocess, "run",
                               return_value=mock.Mock(returncode=1)) as m:
            with self.assertRaises(feedback.FeedbackError):
                feedback.send_github("t", "b")
        self.assertEqual(m.call_args[0][0][:3], ["gh", "auth", "status"])

    def test_github_success_uses_repo(self):
        ok = mock.Mock(returncode=0, stdout="https://github.com/x/y/issues/9\n", stderr="")
        with mock.patch.object(feedback.shutil, "which", return_value="/usr/bin/gh"), \
             mock.patch.object(feedback.subprocess, "run", return_value=ok) as m:
            url = feedback.send_github("标题", "正文")
        self.assertEqual(url, "https://github.com/x/y/issues/9")
        args = m.call_args[0][0]
        self.assertIn("--repo", args)
        self.assertIn(feedback.REPO, args)

    def test_skillhub_missing_cli(self):
        with mock.patch.object(feedback.os.path, "exists", return_value=False), \
             mock.patch.object(feedback.shutil, "which", return_value=None):
            with self.assertRaises(feedback.FeedbackError):
                feedback.send_skillhub("c")

    def test_dry_run_sends_nothing(self):
        d = make_layout()
        with patch_at(os.path.join(d, "references", "scripts")), \
             mock.patch.object(feedback.subprocess, "run") as m, \
             mock.patch("sys.stdout"):  # 静默 dry-run 输出
            rc = feedback.main([d, "--title", "t", "--description", "d", "--dry-run"])
        self.assertEqual(rc, 0)
        m.assert_not_called()

    def test_main_overlong_skillhub_exit_2(self):
        d = make_layout()
        with patch_at(os.path.join(d, "references", "scripts")), mock.patch("sys.stderr"):
            rc = feedback.main([d, "--title", "t", "--description", "长" * 600,
                                "--channel", "skillhub"])
        self.assertEqual(rc, 2)

    def test_main_send_failure_exit_3(self):
        d = make_layout()
        with patch_at(os.path.join(d, "references", "scripts")), \
             mock.patch.object(feedback.shutil, "which", return_value=None), \
             mock.patch("sys.stderr"):
            rc = feedback.main([d, "--title", "t", "--description", "d"])
        self.assertEqual(rc, 3)


if __name__ == "__main__":
    unittest.main()
