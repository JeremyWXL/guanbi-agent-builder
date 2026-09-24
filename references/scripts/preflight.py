#!/usr/bin/env python3
"""
前置检查（第 0 步）：一键确认搭建环境就绪
用法: python3 preflight.py [--json]
检查项:
  1. guancli 可执行文件存在
  2. guancli 版本可读取（脚本对其输出格式有隐式依赖，版本异常时给出提醒）
  3. 认证状态有效（guancli auth status）
  4. 活探针：page tree --raw 可解析为 JSON；随机取一张看板验证 page get --raw 结构
退出码: 0 全部通过 / 1 存在硬失败（认证缺失、CLI 不存在等，必须修复后才能继续）
"""
import json, re, subprocess, sys, shutil


def run(args, timeout=120):
    try:
        r = subprocess.run(["guancli"] + args, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"


results = []

def check(name, ok, hard, detail="", hint=""):
    results.append({"check": name, "ok": ok, "hard": hard, "detail": detail, "hint": hint})
    icon = "✅" if ok else ("❌" if hard else "⚠️")
    print(f"{icon} {name}: {detail}" + (f" → {hint}" if not ok and hint else ""))


def find_first_page(node):
    if isinstance(node, dict):
        if node.get("isPage") and node.get("id"):
            return node["id"], node.get("name", "")
        for c in node.get("contents") or []:
            r = find_first_page(c)
            if r:
                return r
    elif isinstance(node, list):
        for c in node:
            r = find_first_page(c)
            if r:
                return r
    return None


def main():
    as_json = "--json" in sys.argv

    # 1. guancli 存在
    if not shutil.which("guancli"):
        check("guancli 安装", False, True, "未找到 guancli 可执行文件",
              "请先安装 guancli 并登录（guancli auth login）")
        finish(as_json, 1)
    check("guancli 安装", True, True, shutil.which("guancli"))

    # 2. 版本
    code, out, err = run(["version"], timeout=30)
    ver = out.strip().splitlines()[0] if code == 0 and out.strip() else ""
    if ver:
        check("guancli 版本", True, False, ver)
    else:
        check("guancli 版本", False, False, f"无法读取版本（{err[:100] or out[:100]}）",
              "v2.5 脚本基于 guancli 1.x 的 --raw JSON 输出开发，旧版可能不兼容")

    # 3. 认证
    code, out, err = run(["auth", "status"], timeout=30)
    authed = code == 0 and ("有效" in out or re.search(r"uIdToken", out))
    env_m = re.search(r'^环境:\s*(\S+)', out, re.M)
    url_m = re.search(r'^URL:\s*(\S+)', out, re.M)
    if authed:
        check("BI 认证", True, True,
              f"已连接（环境 {env_m.group(1) if env_m else '?'}，{url_m.group(1) if url_m else '?'}）")
    else:
        check("BI 认证", False, True, "未认证或令牌失效",
              "请执行 guancli auth login（或 guancli auth use <环境名>）后重试")
        finish(as_json, 1)

    # 4. 活探针：page tree --raw
    code, out, err = run(["page", "tree", "--raw"])
    tree, probe_page = None, None
    if code == 0:
        try:
            tree = json.loads(out).get("response")
            probe_page = find_first_page(tree)
        except (json.JSONDecodeError, AttributeError):
            pass
    if tree is None:
        check("看板树探针", False, True, f"page tree --raw 输出不可解析（{(err or out)[:120]}）",
              "guancli 输出格式可能已变更，请升级 guancli 或检查脚本兼容性")
        finish(as_json, 1)
    check("看板树探针", True, True, "page tree --raw JSON 结构正常")

    # 5. 活探针：page get --raw 结构（parse_page.py 的主解析路径依赖它）
    if not probe_page:
        check("看板详情探针", True, False, "当前账号没有任何看板，跳过结构探针")
    else:
        pid, pname = probe_page
        code, out, err = run(["page", "get", pid, "--raw"])
        ok = False
        if code == 0:
            try:
                data = json.loads(out).get("data")
                ok = isinstance(data, dict) and isinstance(data.get("cards"), list)
            except json.JSONDecodeError:
                pass
        if ok:
            check("看板详情探针", True, False, f"page get --raw 结构正常（探针看板《{pname}》）")
        else:
            check("看板详情探针", False, False,
                  f"page get --raw 结构异常（{(err or out)[:120]}）",
                  "parse_page.py 将回退文本解析；若大量看板解析失败请检查 guancli 版本")

    finish(as_json, 0)


def finish(as_json, base_code):
    hard_fail = any(not r["ok"] and r["hard"] for r in results)
    code = 1 if hard_fail else base_code
    if as_json:
        print(json.dumps({"ok": code == 0, "checks": results}, ensure_ascii=False, indent=1))
    if code == 0:
        print("\n前置检查通过，可以开始搭建。")
    else:
        print("\n存在必须修复的问题，修复后重新运行 preflight.py。")
    sys.exit(code)


if __name__ == '__main__':
    main()
