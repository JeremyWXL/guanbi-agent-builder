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
                                                           # 在白名单内 exit 0，越界 exit 3，scope 缺失降级 exit 0
校验规则（违反即 exit 3，不调用 guancli）:
  范围守卫：metricId 必须在白名单内（从同目录 metrics.json 的 governedRef.metricId 派生）。
  降级哲学（与 run_sql.py 一致）：找不到 scope 档案、metrics.json 不存在、
  或档案里没有任何 governedRef（多数指标没有引用，正常）时跳过校验不阻断独立使用，
  但会在 stderr 提示"未校验"。
"""
import os, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import scope as scope_mod
except ImportError:
    scope_mod = None  # scope.py 未随包复制时降级跳过白名单校验，不阻断指标直查主功能

# 与 SKILL.md frontmatter 的 version 保持同步
BUILDER_VERSION = "4.8.1"


def scope_check(metric_id):
    """白名单校验：在白名单内返回 None；越界返回错误信息；scope 缺失/无 governedRef 返回 None（降级）"""
    if scope_mod is None:
        print("提示: scope.py 未随包复制，跳过指标白名单校验（降级放行）", file=sys.stderr)
        return None
    scope = scope_mod.load_scope()
    if scope is None:
        print("提示: 未找到范围档案（cards.json/datasets.json），跳过指标白名单校验（降级放行）",
              file=sys.stderr)
        return None
    ids = scope.get("metricIds") or set()
    if not ids:
        print("提示: metrics.json 中没有指标中心引用（governedRef），白名单为空——"
              "降级放行（未校验）。如需引用指标中心口径，回到搭建向导做指标中心对齐。",
              file=sys.stderr)
        return None
    if metric_id not in ids:
        return (f"指标 {metric_id} 不在本助手已确认的指标中心口径白名单内（脚本层拦截）\n"
                "白名单见 references/metrics.json 各条目的 governedRef；如需接入新指标，"
                "回到搭建向导做「增量学习」或指标中心对齐。")
    return None


def main():
    args = sys.argv[1:]
    # --check-scope <metricId>：只验白名单不调 guancli（check_package 功能冒烟用）
    if "--check-scope" in args:
        i = args.index("--check-scope")
        if i + 1 >= len(args):
            sys.exit("用法: python3 run_metric.py --check-scope <metricId>")
        err = scope_check(args[i + 1])
        if err:
            print(f"❌ {err}", file=sys.stderr)
            sys.exit(3)
        print(f"✅ 指标 {args[i + 1]} 在白名单内（或 scope 缺失降级放行）")
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
    err = scope_check(metric_id)
    if err:
        print(f"❌ {err}", file=sys.stderr)
        sys.exit(3)
    r = subprocess.run(["guancli", "metric", "query", metric_id] + passthrough,
                       timeout=180)
    sys.exit(r.returncode)


if __name__ == '__main__':
    main()
