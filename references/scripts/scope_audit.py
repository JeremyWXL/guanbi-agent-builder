#!/usr/bin/env python3
"""
越界取数审计（范围守卫的侦探控制）：扫 qa-log 的 --page/--ds 出处字段，对照 scope 白名单。
实时拦截靠 run_sql.py / sample_cards.py 的白名单脚本；本脚本是事后审计——
防的是"绕过脚本直接调 guancli"，用户问"助手是不是查了没学过的数据？"或定期巡检时运行。
用法:
  python3 scope_audit.py <agent目录> [--json]
  <agent目录> = 交付包路径（读 memory/qa-log.jsonl + references/cards.json 或 datasets.json）
判定:
  --page 不在 scope.pgIds → 越界；--ds 不在 scope.dsIds → 越界
  条目无 --page/--ds 字段（旧流水）→ 计入"无法判定"，不误报
退出码: 0 无越界 / 1 发现越界 / 2 用法或 IO 错误
"""
import json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import scope as scope_mod
except ImportError:
    scope_mod = None  # scope.py 未随包复制：审计无法进行，按"找不到白名单"降级退出

USAGE = __doc__


def audit(agent_dir):
    agent_dir = os.path.abspath(agent_dir)  # 相对路径按 cwd 解析（用户直觉），再拼 scope/流水路径
    scope = None
    if scope_mod is not None:
        scope = scope_mod.load_scope(candidates=[
            os.path.join(agent_dir, "references", "cards.json"),
            os.path.join(agent_dir, "references", "datasets.json"),
            os.path.join(agent_dir, "cards.json"),
            os.path.join(agent_dir, "datasets.json"),
        ])
    log_path = os.path.join(agent_dir, "memory", "qa-log.jsonl")
    if not os.path.exists(log_path):
        print(f"⚠️ 未找到问答流水 {log_path}——先正常使用积累流水后再审计")
        return None, None
    entries = []
    with open(log_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                pass  # 坏行跳过（与 memory.py read_log 的 _badLine 纪律一致）
    if scope is None:
        print(f"⚠️ 找不到 scope 白名单（references/cards.json 或 datasets.json）——无法审计，先完成搭建/升级")
        return entries, None
    violations, unknown = [], 0
    for e in entries:
        page, ds = e.get("page") or "", e.get("ds") or ""
        bad = []
        if page and page not in scope["pgIds"]:
            bad.append(f"page {page}")
        if ds and ds not in scope["dsIds"]:
            bad.append(f"ds {ds}")
        if bad:
            violations.append({"ts": e.get("ts", ""), "question": e.get("question", ""),
                               "page": page, "ds": ds, "reason": "越界 " + "、".join(bad)})
        elif not page and not ds:
            unknown += 1
    return entries, {"scope_source": scope["source"], "violations": violations, "unknown": unknown}


def main():
    args = sys.argv[1:]
    as_json = "--json" in args
    positional = [a for a in args if not a.startswith("-")]
    if len(positional) != 1:
        print(USAGE, file=sys.stderr)
        sys.exit(2)
    agent_dir = positional[0]
    entries, result = audit(agent_dir)
    if entries is None:
        sys.exit(2)
    if result is None:
        sys.exit(2)
    violations, unknown = result["violations"], result["unknown"]
    stats = {"agent": os.path.basename(os.path.normpath(agent_dir)),
             "scope_source": result["scope_source"],
             "total": len(entries), "with_provenance": len(entries) - unknown,
             "violations": violations, "unknown": unknown}
    if as_json:
        print(json.dumps(stats, ensure_ascii=False, indent=1))
        sys.exit(1 if violations else 0)
    print(f"越界取数审计 —— agent「{stats['agent']}」（scope: {stats['scope_source']}）")
    print(f"问答流水 {stats['total']} 条：有出处 {stats['with_provenance']} / 越界 {len(violations)} / 无法判定 {unknown}")
    for v in violations:
        print(f"  ❌ [{v['ts']}] {v['question']}")
        print(f"     {v['reason']}")
    if violations:
        print(f"\n结论: ❌ 发现 {len(violations)} 条越界取数——覆盖范围外的看板/数据集被当答案引用")
        print("      覆盖范围见 scope 来源文件；越界数据应作废重答，并检查是否有裸调 guancli 的绕过路径")
        sys.exit(1)
    print("\n结论: ✅ 未发现越界取数" + (f"（{unknown} 条旧流水无出处字段，无法判定——新版 memory.py log 起有记录）" if unknown else ""))
    sys.exit(0)


if __name__ == '__main__':
    main()
