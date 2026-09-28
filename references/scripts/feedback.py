#!/usr/bin/env python3
"""feedback.py — 问题反馈通道：把用户遇到的 bug / 不符合预期的情况发到本项目 GitHub 仓库或 SkillHub 评论区。

用法:
    python3 references/scripts/feedback.py [工作目录] --title "一句话问题" --description "现象描述"
        [--channel github|skillhub|both] [--dry-run]

- 自动附加环境上下文（builder 版本、搭建进度、平台、guancli 有无），业务数据绝不带入
- GitHub 通道：gh issue create（需 gh 已登录）；SkillHub 通道：skillhub comment post（正文 ≤500 字）
- --dry-run 只打印将发送的标题/正文与命令，不实际发送（给用户预览用）
- 工作目录省略时按当前目录，无 wizard-state 时上下文自动降级为"未知"

隐私红线：description 只能是用户亲口描述的现象 + 发生步骤；禁止夹带看板数值、采样数据、
卡片明细、截图中的数据。脚本只收集环境信息，业务数据泄露只能靠 prompt 层约束。

退出码：0 成功；2 用法/组合失败（如 SkillHub 正文超 500 字）；3 发送失败（CLI 缺失/未登录/网络）。
"""
import argparse
import json
import os
import platform
import shutil
import subprocess
import sys

REPO = "JeremyWXL/guanbi-agent-builder"
SKILLHUB_SLUG = "guanbi-agent-builder"
SKILLHUB_BIN = os.path.expanduser("~/.local/bin/skillhub")
SKILLHUB_LIMIT = 500


class FeedbackError(Exception):
    """可预期失败（CLI 缺失/未登录/正文超限），退出码 2 或 3"""


# ---------- 环境上下文收集 ----------

def find_builder_version():
    """从 SKILL.md frontmatter 读 builder 版本。两种布局：仓库（references/scripts/feedback.py）
    与交付包（references/feedback.py）。"""
    here = os.path.dirname(os.path.abspath(__file__))
    for candidate in (os.path.join(here, "..", "..", "SKILL.md"),
                      os.path.join(here, "..", "SKILL.md")):
        try:
            with open(candidate, encoding="utf-8") as f:
                in_fm = False
                for line in f:
                    if line.strip() == "---":
                        if not in_fm:
                            in_fm = True  # frontmatter 开始
                            continue
                        break  # frontmatter 结束
                    if in_fm and line.startswith("version:"):
                        return line.split(":", 1)[1].strip().strip('"').strip("'")
        except OSError:
            continue
    return None


def _state_summary(path):
    try:
        with open(path, encoding="utf-8") as f:
            st = json.load(f)
    except (OSError, ValueError):
        return None
    step = st.get("currentStep") or st.get("step")
    status = st.get("status")
    mode = st.get("mode")
    updated = st.get("updatedAt")
    parts = []
    if step is not None:
        parts.append(f"第 {step} 步")
    if status:
        parts.append(f"状态 {status}")
    if mode:
        parts.append(f"模式 {mode}")
    if updated:
        parts.append(f"更新于 {updated}")
    return "（" + "，".join(parts) + "）" if parts else None


def collect_context(workdir):
    """只收集环境信息：版本/进度/平台/依赖。绝不读卡片、采样等业务文件。"""
    ctx = {"builderVersion": find_builder_version() or "未知",
           "platform": f"{platform.system()} {platform.release()}",
           "python": platform.python_version(),
           "guancli": "已安装" if shutil.which("guancli") else "未安装"}
    label = {"wizard-state.json": "搭建进度", "wizard-state-incr.json": "增量学习进度"}
    for name in label:
        s = _state_summary(os.path.join(workdir, name))
        if s:
            ctx["progress"] = f"{label[name]}{s}"
            break
    return ctx


def compose_issue(title, description, ctx):
    lines = [f"## 现象", "", description.strip(), "", "## 环境信息（自动收集，不含业务数据）", ""]
    label = {"builderVersion": "builder 版本", "progress": "搭建进度",
             "platform": "平台", "python": "Python", "guancli": "guancli"}
    for k, v in ctx.items():
        lines.append(f"- {label.get(k, k)}：{v}")
    lines += ["", "> 本反馈由搭建向导的 feedback.py 生成，正文不包含业务数据。"]
    return title.strip(), "\n".join(lines)


def compose_comment(title, description, ctx):
    """SkillHub 评论，≤500 字。"""
    text = f"【用户反馈】{title.strip()}\n{description.strip()}\n— builder {ctx.get('builderVersion', '未知')}"
    if ctx.get("progress"):
        text += f" · {ctx['progress']}"
    if len(text) > SKILLHUB_LIMIT:
        raise FeedbackError(
            f"SkillHub 评论超长：{len(text)} 字 > {SKILLHUB_LIMIT} 上限，请精简 description 后重试")
    return text


# ---------- 发送 ----------

def send_github(title, body):
    if not shutil.which("gh"):
        raise FeedbackError("未找到 gh CLI（brew install gh），GitHub 通道不可用")
    r = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True)
    if r.returncode != 0:
        raise FeedbackError("gh 未登录，请先运行：gh auth login")
    r = subprocess.run(["gh", "issue", "create", "--repo", REPO,
                        "--title", title, "--body", body],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise FeedbackError(f"gh issue create 失败：{r.stderr.strip() or r.stdout.strip()}")
    return (r.stdout.strip() or "").splitlines()[-1].strip()  # issue URL


def send_skillhub(comment):
    bin_ = SKILLHUB_BIN if os.path.exists(SKILLHUB_BIN) else shutil.which("skillhub")
    if not bin_:
        raise FeedbackError(f"未找到 skillhub CLI（{SKILLHUB_BIN}），SkillHub 通道不可用")
    r = subprocess.run([bin_, "comment", "post", SKILLHUB_SLUG,
                        "--content", comment, "--json"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise FeedbackError(f"skillhub comment post 失败：{r.stderr.strip() or r.stdout.strip()}")
    try:
        doc = json.loads(r.stdout)
        return doc.get("url") or doc.get("data", {}).get("url") or "已发布"
    except ValueError:
        return "已发布"


def main(argv=None):
    p = argparse.ArgumentParser(description="问题反馈：发送 GitHub issue / SkillHub 评论")
    p.add_argument("workdir", nargs="?", default=".", help="工作目录（收集搭建进度用，默认当前目录）")
    p.add_argument("--title", required=True, help="一句话问题概括")
    p.add_argument("--description", required=True, help="现象描述（用户原话，禁止含业务数据）")
    p.add_argument("--channel", choices=["github", "skillhub", "both"], default="github")
    p.add_argument("--dry-run", action="store_true", help="只打印不发送")
    a = p.parse_args(argv)

    ctx = collect_context(a.workdir)
    try:
        gh_title, gh_body = compose_issue(a.title, a.description, ctx)
        sh_comment = compose_comment(a.title, a.description, ctx) if a.channel in ("skillhub", "both") else None
    except FeedbackError as e:
        print(f"组合失败：{e}", file=sys.stderr)
        return 2

    if a.dry_run:
        print("=== GitHub issue ===")
        print(f"标题：{gh_title}\n\n{gh_body}")
        if sh_comment:
            print("\n=== SkillHub 评论 ===")
            print(sh_comment)
        print("\n（dry-run，未发送）")
        return 0

    try:
        if a.channel in ("github", "both"):
            url = send_github(gh_title, gh_body)
            print(f"GitHub issue 已创建：{url}")
        if sh_comment:
            r = send_skillhub(sh_comment)
            print(f"SkillHub 评论已发布：{r}")
    except FeedbackError as e:
        print(f"发送失败：{e}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
