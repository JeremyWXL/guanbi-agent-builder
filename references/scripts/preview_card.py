#!/usr/bin/env python3
"""单卡取数：guancli card preview 的范围与参数白名单包装。

用法: python3 preview_card.py <cdId> [--dynamic-param "名称=值"]... [--no-scope]
默认从包内 cards.json 校验 cdId；独立调试必须显式传 --no-scope。
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import scope as scope_mod
except ImportError:
    scope_mod = None


def fail(message, code=3):
    print(f"❌ {message}", file=sys.stderr)
    sys.exit(code)


def main():
    args = sys.argv[1:]
    allow_no_scope = "--no-scope" in args
    args = [arg for arg in args if arg != "--no-scope"]
    scope_path = None
    if "--scope" in args:
        i = args.index("--scope")
        if i + 1 >= len(args):
            fail("--scope 需要 cards.json/cards-raw.json 路径", 2)
        scope_path = args[i + 1]
        args = args[:i] + args[i + 2:]
    if not args:
        fail("用法: preview_card.py <cdId> [--dynamic-param 名称=值]... [--scope 路径] [--no-scope]", 2)
    cd_id = args[0]
    scope = scope_mod.load_scope(candidates=[scope_path] if scope_path else None) if scope_mod is not None else None
    if scope is None:
        if not allow_no_scope:
            fail("找不到范围档案，已拒绝取数；独立调试请显式加 --no-scope")
    elif cd_id not in scope["cdIds"]:
        fail(f"卡片 {cd_id} 不在本助手覆盖范围；请先增量学习该看板")

    passthrough = []
    i = 1
    while i < len(args):
        if args[i] != "--dynamic-param" or i + 1 >= len(args):
            fail("只支持 --dynamic-param 名称=值（可多次指定）", 2)
        assignment = args[i + 1]
        name, sep, value = assignment.partition("=")
        if not sep or not name.strip() or not value.strip():
            fail(f"动态参数格式错误: {assignment}", 2)
        if scope is not None:
            card = (scope.get("cardsById") or {}).get(cd_id) or {}
            declared = {p.get("name") for p in card.get("dynamicParams") or []
                        if isinstance(p, dict)}
            if name.strip() not in declared:
                fail(f"参数 {name.strip()} 未在卡片 {cd_id} 的 dynamicParams 中声明")
        passthrough.extend(["--dynamic-param", assignment])
        i += 2

    command = ["guancli", "card", "preview", cd_id, "-f", "json"] + passthrough
    try:
        result = subprocess.run(command, timeout=180)
    except (OSError, subprocess.TimeoutExpired) as exc:
        fail(f"card preview 执行失败: {exc}", 2)
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
