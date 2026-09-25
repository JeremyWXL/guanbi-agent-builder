#!/usr/bin/env python3
"""
指标口径档案校验器：metrics.json（机器可读口径，第 4 步确认产物）的质量闸门
用法: python3 check_metrics.py <工作目录>     # 读 metrics.json，对照 formulas.json / cards-raw.json 校验
校验项（❌ 错误未清零退出码 1，禁止进入第 5 步；⚠️ 警告不阻断但必须在确认点告知用户）:
  结构: name 必填且唯一；formula 与 baseField 至少其一；dims/synonyms/exampleQuestions 必须是数组
  同义词: synonyms 禁止与其他指标的 name/synonyms 撞车（撞车 = 问数路由歧义）
  冲突裁决: formulas.json 的 conflicts 必须在 metrics（裁决收录）或 rejected（裁决弃用）中有着落
  一致性: metrics.json 公式与 formulas.json 已知变体比对，都不匹配时 ⚠️（可能是用户新口径，需确认来源）
          safety 分类与 formulas.json 不一致时 ⚠️
  覆盖: formulas.json 的共识指标未收编（既不在 metrics 也不在 rejected）时 ⚠️ 列出，防漏确认
  维度: dims 未在任何卡片出现时 ⚠️（SQL 独有维度可忽略）
参照: formulas.json 缺失时只做结构+同义词校验；cards-raw.json 缺失时跳过维度校验
"""
import json, re, sys, os

SAFETY_KNOWN = {"FREE", "DISTINCT", "AVG", "NONADDITIVE", "ROW_LOGIC", "TIME_MACRO"}


def normalize(formula):
    """公式归一化（与 check_formulas.py 的实现保持一致）。"""
    parts = re.split(r'(\[[^\]]*\])', formula or '')
    return ''.join(p if p.startswith('[') else re.sub(r'\s+', '', p).lower() for p in parts)


def load(workdir, fn):
    fp = os.path.join(workdir, fn)
    if not os.path.exists(fp):
        return None
    with open(fp, encoding="utf-8") as f:
        return json.load(f)


def main():
    workdir = sys.argv[1] if len(sys.argv) > 1 else "."
    doc = load(workdir, "metrics.json")
    if doc is None:
        sys.exit(f"找不到 {workdir}/metrics.json——第 4 步口径确认后由 metrics-seed.json 转写生成")
    errors, warns = [], []

    metrics = doc.get("metrics")
    if not isinstance(metrics, list):
        sys.exit("metrics.json 结构错误：顶层 metrics 必须是数组")
    rejected = doc.get("rejected") or []
    rejected_names = {r.get("name") for r in rejected if isinstance(r, dict)}

    # ---- 结构校验 ----
    seen = {}
    for i, m in enumerate(metrics):
        tag = f"metrics[{i}]「{m.get('name', '?')}」"
        if not isinstance(m, dict) or not (m.get("name") or "").strip():
            errors.append(f"{tag}: name 必填且非空")
            continue
        name = m["name"].strip()
        if name in seen:
            errors.append(f"{tag}: 与 metrics[{seen[name]}] 重名——name 必须唯一")
        seen[name] = i
        if not (m.get("formula") or "").strip() and not (m.get("baseField") or "").strip():
            errors.append(f"{tag}: formula 与 baseField 至少填一个")
        for k in ("dims", "synonyms", "exampleQuestions"):
            if k in m and not isinstance(m[k], list):
                errors.append(f"{tag}: {k} 必须是数组")
        if m.get("safety") and m["safety"] not in SAFETY_KNOWN:
            warns.append(f"{tag}: safety「{m['safety']}」不是已知分类（{'/'.join(sorted(SAFETY_KNOWN))}）")
        if m.get("pending"):
            errors.append(f"{tag}: 仍带 pending 标记——冲突裁决后请填 formula 并删除 pending/variants")

    # ---- 同义词撞车 ----
    owners = {name: name for name in seen}  # 词 → 占用者
    for m in metrics:
        name = (m.get("name") or "").strip()
        for syn in m.get("synonyms") or []:
            syn = (syn or "").strip()
            if not syn:
                continue
            if syn == name:
                warns.append(f"「{name}」: 同义词与本名相同（{syn}），无信息增量")
            elif syn in owners and owners[syn] != name:
                errors.append(f"「{name}」的同义词「{syn}」与「{owners[syn]}」撞车——问数路由会歧义，必须改名或删除")
            else:
                owners[syn] = name

    # ---- 对照 formulas.json ----
    fm = load(workdir, "formulas.json")
    if fm:
        by_name = {e.get("name"): e for e in fm.get("metrics") or []}
        # 冲突必须有着落
        for c in fm.get("conflicts") or []:
            n = c.get("name")
            if n not in seen and n not in rejected_names:
                errors.append(f"口径冲突「{n}」未裁决：metrics.json 的 metrics（收录）与 rejected（弃用）都没有它")
        # 公式一致性 + safety 一致性
        for m in metrics:
            name = (m.get("name") or "").strip()
            ref = by_name.get(name)
            if not ref:
                warns.append(f"「{name}」在 formulas.json 中不存在——若是用户口述口径请确认 source=user")
                continue
            f = (m.get("formula") or "").strip()
            if f and ref.get("consensus") is False:
                known = {normalize(v.get("formula")) for v in ref.get("variants") or [] if v.get("formula")}
                if known and normalize(f) not in known:
                    warns.append(f"「{name}」的裁决公式与看板已知变体都不一致——请确认这是用户明确裁定的新口径")
            if m.get("safety") and ref.get("classification") and \
               ref["classification"] not in ("PRESENTATION",) and m["safety"] != ref["classification"]:
                warns.append(f"「{name}」safety={m['safety']} 与看板分类 {ref['classification']} 不一致")
        # 候选覆盖
        uncovered = [e["name"] for e in fm.get("metrics") or []
                     if e.get("name") and e["name"] not in seen and e["name"] not in rejected_names
                     and (e.get("formula") or e.get("baseField"))
                     and e.get("classification") not in ("PRESENTATION", "CONSTANT")]
        if uncovered:
            warns.append(f"{len(uncovered)} 个看板共识指标未收编（确认过但没收进 metrics/rejected）："
                         f"{'、'.join(uncovered[:10])}{'…' if len(uncovered) > 10 else ''}")
    else:
        warns.append("formulas.json 缺失：跳过冲突裁决/一致性/覆盖校验（第 2 步先跑 check_formulas.py）")

    # ---- 维度校验 ----
    raw = load(workdir, "cards-raw.json")
    if raw:
        known_dims = {d for k, v in raw.items() if k != "_meta" and isinstance(v, dict)
                      for c in v.get("cards") or [] for d in c.get("dims") or []}
        for m in metrics:
            for d in m.get("dims") or []:
                if d not in known_dims:
                    warns.append(f"「{m.get('name')}」的维度「{d}」未在任何卡片出现（SQL 独有维度可忽略）")

    # ---- 报告 ----
    print(f"\n指标口径档案校验（{workdir}/metrics.json）")
    print("=" * 60)
    print(f"已确认指标 {len(metrics)} 个，弃用候选 {len(rejected)} 个")
    for e in errors:
        print(f"  ❌ {e}")
    for w in warns:
        print(f"  ⚠️  {w}")
    if errors:
        print(f"\n{len(errors)} 个错误未清零——禁止进入第 5 步")
        sys.exit(1)
    print("\n✅ 校验通过" + (f"（{len(warns)} 条警告需在确认点告知用户）" if warns else ""))


if __name__ == '__main__':
    main()
