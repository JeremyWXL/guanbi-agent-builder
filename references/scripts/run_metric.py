#!/usr/bin/env python3
"""
指标中心直查执行器：guancli metric query 的安全包装层
指标中心取数一律走本脚本，禁止裸调 guancli metric query——
prompt 红线靠自觉，本脚本提供脚本层强制：指标必须在本包口径档案的
指标中心引用白名单内（metrics.json 各条目的 governedRef.metricId，越界 exit 3 拦截）。
用法:
  python3 run_metric.py <metricId>                         # 平台直查（权威口径 + 平台侧计算）
  python3 run_metric.py <metricId> -- <透传参数...>         # -- 之后的参数原样透传给
                                                           # guancli metric query（如 --dim/--filter）
  python3 run_metric.py --check-scope <metricId>           # 只验白名单不查询（体检/冒烟用）：
                                                           # 在白名单内 exit 0，越界或 scope 缺失 exit 3
校验规则（违反即 exit 3，不调用 guancli）:
  范围守卫：metricId 必须在白名单内（从同目录 metrics.json 的 governedRef.metricId 派生）。
  默认 fail closed：找不到 scope、metrics.json 损坏或没有 governedRef 都拒绝直查；
  仅独立调试可显式传 --no-scope 跳过校验。
"""
import os, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import scope as scope_mod
except ImportError:
    scope_mod = None  # 缺失时 scope_check 默认拒绝；独立调试须显式 --no-scope

# 与 SKILL.md frontmatter 的 version 保持同步
BUILDER_VERSION = "4.12.1"


def scope_check(metric_id, allow_no_scope=False):
    """交付包默认 fail closed；只有显式 --no-scope 才允许独立调试绕过。"""
    if allow_no_scope:
        print("⚠️ 已显式指定 --no-scope：本次不校验指标白名单", file=sys.stderr)
        return None
    if scope_mod is None:
        return "scope.py 缺失，无法校验指标白名单；请恢复脚本或显式使用 --no-scope"
    scope = scope_mod.load_scope()
    if scope is None:
        return "未找到范围档案，已拒绝取数；独立调试请显式使用 --no-scope"
    if not scope.get("metricsValid", True):
        return "metrics.json 损坏，无法确认指标白名单；请先修复口径档案"
    ids = scope.get("metricIds") or set()
    if not ids:
        return ("metrics.json 没有已确认的 governedRef，指标白名单为空，已拒绝直查；"
                "请先完成指标中心对齐")
    if metric_id not in ids:
        return (f"指标 {metric_id} 不在本助手已确认的指标中心口径白名单内（脚本层拦截）\n"
                "白名单见 references/metrics.json 各条目的 governedRef；如需接入新指标，"
                "回到搭建向导做「增量学习」或指标中心对齐。")
    return None


def main():
    args = sys.argv[1:]
    allow_no_scope = "--no-scope" in args
    args = [arg for arg in args if arg != "--no-scope"]
    # --check-scope <metricId>：只验白名单不调 guancli（check_package 功能冒烟用）
    if "--check-scope" in args:
        i = args.index("--check-scope")
        if i + 1 >= len(args):
            sys.exit("用法: python3 run_metric.py --check-scope <metricId>")
        err = scope_check(args[i + 1])
        if err:
            print(f"❌ {err}", file=sys.stderr)
            sys.exit(3)
        print(f"✅ 指标 {args[i + 1]} 在白名单内")
        sys.exit(0)
    passthrough = []
    if "--" in args:
        i = args.index("--")
        passthrough = args[i + 1:]
        args = args[:i]
    if len(args) != 1:
        sys.exit("用法: python3 run_metric.py <metricId> [-- <guancli metric query 透传参数>]")
    metric_id = args[0]
    # 范围守卫：白名单外的指标禁止取数（口径未经确认的指标禁止当答案）
    err = scope_check(metric_id, allow_no_scope=allow_no_scope)
    if err:
        print(f"❌ {err}", file=sys.stderr)
        sys.exit(3)
    r = subprocess.run(["guancli", "metric", "query", metric_id] + passthrough,
                       timeout=180)
    sys.exit(r.returncode)


if __name__ == '__main__':
    main()
