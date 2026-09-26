#!/usr/bin/env python3
"""
基线版本对比：读取两份 tests/baselines/v<版本>.json（agent-tester 的机器可读基线孪生），
生成"与上版基线的差异"报告——代替人工逐行比对两份 markdown。
用法:
  python3 diff_baselines.py <旧基线.json> <新基线.json>
输出（stdout，markdown）:
  - L0/L1/L2 三层结果变化（L2 总分涨跌、等级、红线数、逐题得分对比）
  - 旧版遗留问题的处置情况（按 title 匹配：已修复 / 仍未解决 / 跟踪中）
  - 新版新增问题清单
  - 回归焦点建议（未解决问题 + 新增问题 + 得分下降的考题）
基线 JSON 字段约定见 v3.7.0.json；issue.status 取值：open / fixed / tracking。
退出码: 0 正常；1 用法/文件错误
"""
import json
import sys


def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        sys.exit(f"❌ 无法读取基线 {path}: {e}")


def fmt_delta(d):
    if d > 0:
        return f"▲{d}"
    if d < 0:
        return f"▼{abs(d)}"
    return "＝0"


def main():
    if len(sys.argv) != 3:
        sys.exit("用法: python3 diff_baselines.py <旧基线.json> <新基线.json>")
    old, new = load(sys.argv[1]), load(sys.argv[2])

    print(f"# 基线对比：v{old.get('version', '?')} → v{new.get('version', '?')}\n")
    print(f"- 旧版：{old.get('date', '?')} ｜ tester v{old.get('testerVersion', '?')} ｜ {old.get('environment', '?')}")
    print(f"- 新版：{new.get('date', '?')} ｜ tester v{new.get('testerVersion', '?')} ｜ {new.get('environment', '?')}")

    # L0 / 单测
    lo, ln = old.get("l0", {}), new.get("l0", {})
    print("\n## L0 脚本层\n")
    print(f"- 检查点：{lo.get('passed', '?')}/{lo.get('total', '?')} → {ln.get('passed', '?')}/{ln.get('total', '?')}")
    if "unitTests" in old or "unitTests" in new:
        print(f"- 单测：{old.get('unitTests', '?')} → {new.get('unitTests', '?')} 例（{fmt_delta(new.get('unitTests', 0) - old.get('unitTests', 0))}）")

    # L1
    print("\n## L1 八步向导 E2E\n")
    print(f"- 结论：{old.get('l1', {}).get('status', '?')} → {new.get('l1', {}).get('status', '?')}")
    if new.get("l1", {}).get("notes"):
        print(f"- 新版说明：{new['l1']['notes']}")

    # L2
    o2, n2 = old.get("l2", {}), new.get("l2", {})
    print("\n## L2 交付 agent 回答质量\n")
    dropped_questions = []
    if "score" in o2 and "score" in n2 and o2["score"] is not None and n2["score"] is not None:
        print(f"- 总分：{o2['score']} → {n2['score']}（{fmt_delta(n2['score'] - o2['score'])}）｜ "
              f"等级 {o2.get('grade', '?')} → {n2.get('grade', '?')} ｜ "
              f"红线 {o2.get('redlines', '?')} → {n2.get('redlines', '?')}")
    elif n2.get("note"):
        print(f"- 本次未测评：{n2['note']}")
    oq = {q.get("id"): q for q in o2.get("questions", [])}
    nq = {q.get("id"): q for q in n2.get("questions", [])}
    if nq:
        print("\n| 考题 | 旧版 | 新版 | 变化 |")
        print("|------|------|------|------|")
        for qid, q in nq.items():
            o_score = oq.get(qid, {}).get("score")
            if o_score is None:
                print(f"| {qid} {q.get('topic', '')} | —（新题） | {q.get('score', '?')} | — |")
            else:
                d = q.get("score", 0) - o_score
                mark = " ⚠️" if d < 0 else ""
                print(f"| {qid} {q.get('topic', '')} | {o_score} | {q.get('score', '?')} | {fmt_delta(d)}{mark} |")
                if d < 0:
                    dropped_questions.append(f"{qid} {q.get('topic', '')}（{o_score}→{q.get('score')}）")
        for qid in oq:
            if qid not in nq:
                print(f"| {qid} {oq[qid].get('topic', '')} | {oq[qid].get('score', '?')} | —（本版未考） | — |")

    # 问题清单对比（按 title 匹配）
    o_issues = {i.get("title", ""): i for i in old.get("issues", [])}
    n_issues = {i.get("title", ""): i for i in new.get("issues", [])}
    carried_open = [t for t, i in o_issues.items()
                    if i.get("status") in ("open", "tracking")
                    and n_issues.get(t, {}).get("status") in ("open", "tracking", None)]
    fixed = [t for t, i in o_issues.items()
             if i.get("status") in ("open", "tracking")
             and n_issues.get(t, {}).get("status") == "fixed"]
    added = [i for t, i in n_issues.items() if t not in o_issues]

    print("\n## 问题清单变化\n")
    if fixed:
        print("**✅ 旧版问题已修复：**")
        for t in fixed:
            print(f"- [{n_issues[t].get('severity', '?')}] {t}（修复于 v{n_issues[t].get('fixedIn', '?')}）")
    if carried_open:
        print("**⚠️ 旧版问题仍未解决：**")
        for t in carried_open:
            print(f"- [{n_issues.get(t, o_issues[t]).get('severity', '?')}] {t}")
    if added:
        print("**🆕 新版新增问题：**")
        for i in added:
            print(f"- [{i.get('severity', '?')}] {i.get('title', '')}（{i.get('status', 'open')}）")
    if not (fixed or carried_open or added):
        print("两版问题清单无变化。")

    # 回归焦点建议
    print("\n## 回归焦点建议\n")
    focus = []
    focus.extend(f"未解决问题：{t}" for t in carried_open)
    focus.extend(f"新增问题：{i.get('title', '')}" for i in added
                 if i.get("severity") in ("P0", "P1"))
    focus.extend(f"得分下降考题：{q}" for q in dropped_questions)
    if focus:
        for f in focus:
            print(f"- {f}")
    else:
        print("- 无特别焦点；按常规三层流程回归即可")


if __name__ == "__main__":
    main()
