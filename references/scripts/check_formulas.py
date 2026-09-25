#!/usr/bin/env python3
"""
指标公式分析器：把 parse_page.py 收割的公式变成问数 agent 的口径资产
用法: python3 check_formulas.py <工作目录> [--seed-metrics]
                          # 读 cards-raw.json → 写 formulas.json + 控制台报告
                          # --seed-metrics：额外写 metrics-seed.json（metrics.json 的起草种子，第 4 步逐条确认的素材）
做的事:
  1. 汇总全部卡片/数据集的公式字段，按指标名归组
  2. 同名指标公式比对 → 口径冲突清单（如"退款率"在不同卡片分母不同）——第 4 步必须请用户裁决
  3. 按公式结构分类"换维度聚合安全性"：
     - FREE        纯 sum 可加 / sum/sum 比率型 → 换维度安全（分子分母分别求和再相除）
     - DISTINCT    含 count(distinct) → 必须从明细现算，禁止把分组结果再加总/平均
     - NONADDITIVE 含 max/min 聚合 → 换维度语义会变，必须从明细现算
     - AVG         含 avg → 禁止对分组均值再平均，必须 sum/count 现算
     - ROW_LOGIC   含 case when 行级条件 → SQL 可复写，但语义绑定行粒度
     - TIME_MACRO  含 current_date/date_trunc 等 → 结果与"今天"绑定
  4. 生成口径候选条目（candidateRules），供第 4 步业务口径确认直接使用
输出: <工作目录>/formulas.json
"""
import json, re, sys, os
from collections import defaultdict
from datetime import datetime

RULES = [  # (优先级, 类别, 正则, 中文说明)
    (0, "CONSTANT", re.compile(r'^\s*[\d.,\s]+\s*$'),
     "硬编码常量：疑似演示/大屏专属（如写死的目标值、调整系数），禁止当业务口径"),
    (1, "DISTINCT", re.compile(r'count\s*\(\s*distinct', re.I),
     "含 COUNT DISTINCT：换维度必须从明细现算；禁止把各分组结果相加或平均"),
    (2, "AVG", re.compile(r'\bavg\s*\(', re.I),
     "含 AVG：禁止对分组均值再平均，换维度必须 sum/count 现算"),
    (3, "NONADDITIVE", re.compile(r'\b(max|min|median|percentile|stddev)\s*\(', re.I),
     "含 MAX/MIN 等非加聚合：换维度后语义会变，必须从明细现算"),
    (4, "TIME_MACRO", re.compile(r'current_date|current_timestamp|date_trunc|dayofmonth|last_day|now\s*\(', re.I),
     "含时间宏/日期函数：结果与「今天」绑定，SQL 复写时需显式日期"),
    (5, "ROW_LOGIC", re.compile(r'\bcase\s+when\b', re.I),
     "含行级条件逻辑：SQL 可复写，但语义绑定数据集行粒度"),
]
RATIO_OF_SUM = re.compile(
    r'^\s*sum\s*\([^()]*\)\s*/\s*(sum|count\s*\(\s*distinct)\s*\([^()]*\)\s*$', re.I)
PURE_SUM = re.compile(r'^\s*sum\s*\([^()]*\)\s*$', re.I)


def normalize(formula):
    """公式归一化：去空白、方括号外转小写（函名字段大小写不敏感，字段名保留原样）"""
    parts = re.split(r'(\[[^\]]*\])', formula or '')
    return ''.join(p if p.startswith('[') else re.sub(r'\s+', '', p).lower() for p in parts)


def classify(formula, aggr_type=""):
    """返回 (类别, 说明)。无公式时按物理字段的聚合方式分类。"""
    f = (formula or "").strip()
    if f:
        for _, cls, pat, desc in RULES:
            if pat.search(f):
                return cls, desc
        if RATIO_OF_SUM.match(f):
            return "FREE", "sum/sum 比率型：换维度安全（分子分母分别求和再相除）；禁止 AVG(明细比率)"
        if PURE_SUM.match(f):
            return "FREE", "纯求和：换维度安全"
        return "FREE", "公式仅含可加聚合：换维度安全（SQL 内联公式现算）"
    ag = (aggr_type or "").upper().replace(" ", "")
    if ag in ("SUM", ""):
        return "FREE", "物理可加字段（SUM）" if ag else ""
    if ag in ("AVG",):
        return "AVG", "物理字段按 AVG 聚合：禁止对分组均值再平均"
    if ag in ("COUNTDISTINCT", "DISTINCT", "DCOUNT"):
        return "DISTINCT", "物理字段按 COUNT DISTINCT 聚合：必须从明细现算"
    if ag in ("MAX", "MIN"):
        return "NONADDITIVE", f"物理字段按 {ag} 聚合：换维度语义会变"
    return "FREE", ""


def main():
    argv = [a for a in sys.argv[1:] if a != "--seed-metrics"]
    seed = len(argv) != len(sys.argv) - 1
    workdir = argv[0] if argv else "."
    src = os.path.join(workdir, "cards-raw.json")
    if not os.path.exists(src):
        sys.exit(f"找不到 {src}——先运行 parse_page.py")
    raw = json.load(open(src, encoding="utf-8"))
    ds_formulas = (raw.get("_meta") or {}).get("dsFormulas") or {}
    # fdId → 数据集计算字段公式（卡片按 fdId 引用时补全）
    fd_vc = {}
    for ds_id, info in ds_formulas.items():
        for vc in info.get("virtualColumns") or []:
            if vc.get("fdId") and vc.get("formula"):
                fd_vc[vc["fdId"]] = vc

    # 汇总：display_name → [{formula, aggrType, advType, source, page, card, dims, scope}]
    groups = defaultdict(list)
    n_card_formula = 0
    for page_name, page in raw.items():
        if page_name == "_meta" or not isinstance(page, dict):
            continue
        for card in page.get("cards") or []:
            scope = [f"{f['field']} {f['filterType']} {f['filterValue']}"
                     for f in (card.get("filterDetails") or []) if f.get("filterValue")]
            for m in card.get("measures") or []:
                formula = m.get("formula") or (fd_vc.get(m.get("fdId")) or {}).get("formula", "")
                if m.get("fdId") in fd_vc and not m.get("formula"):
                    src_tag = "dataset"
                else:
                    src_tag = "card"
                if m.get("formula"):
                    n_card_formula += 1
                groups[m.get("alias") or m.get("name") or "?"].append({
                    "baseField": m.get("name") or "",
                    "alias": m.get("alias") or "",
                    "formula": formula,
                    "aggrType": m.get("aggrType", ""),
                    "advType": m.get("advType", ""),
                    "advParams": m.get("advParams"),
                    "source": src_tag,
                    "page": page_name,
                    "card": card.get("name", ""),
                    "dims": card.get("dims") or [],
                    "scope": scope,
                })

    # 数据集计算字段中未被任何卡片引用的，也收录为口径候选（标注未引用）
    used_fds = {e["formula"] for g in groups.values() for e in g}
    n_ds_only = 0
    for ds_id, info in ds_formulas.items():
        for vc in info.get("virtualColumns") or []:
            if vc.get("formula") and vc["formula"] not in used_fds:
                groups[vc["name"]].append({
                    "baseField": vc["name"], "formula": vc["formula"],
                    "aggrType": vc.get("aggrType", ""), "advType": "", "advParams": None,
                    "source": "dataset-unused", "page": "", "card": "",
                    "dsName": info.get("dsName", ds_id),
                    "dims": [], "scope": [],
                })
                n_ds_only += 1

    metrics, conflicts, candidate_rules = [], [], []
    cls_counts = defaultdict(int)
    for name, entries in sorted(groups.items()):
        # 展示层派生条目（别名 ≠ 本名：如"年同比""占比""同期收入"）不参与口径冲突判定——
        # 它们是同一计算方式作用于不同基数字段的正常复用，真实身份是基数字段而非别名
        adv_idx = {i for i, e in enumerate(entries)
                   if e.get("alias") and e["alias"] != e.get("baseField")}
        adv_entries = [e for i, e in enumerate(entries) if i in adv_idx]
        plain = [e for i, e in enumerate(entries) if i not in adv_idx]
        if not plain:
            # 纯展示层组（如各卡的"年同比"）：只登记，不参与分类与冲突判定
            metrics.append({
                "name": name, "classification": "PRESENTATION",
                "classificationNote": "展示层高级计算（同比/环比/占比），SQL 复写需按 advParams 现算",
                "consensus": True, "occurrences": len(entries),
                "advCalcs": sorted({f"{e['alias']}（基数: {e['baseField']}）"
                                    for e in adv_entries}),
                "sources": [],
            })
            continue
        variants = {}
        for e in plain:
            key = normalize(e["formula"]) if e["formula"] else f"__field__{e['baseField']}:{e['aggrType']}"
            variants.setdefault(key, []).append(e)
        representative = plain[0]
        cls, cls_desc = classify(representative["formula"], representative.get("aggrType", ""))
        if cls:
            cls_counts[cls] += 1
        entry = {
            "name": name,
            "classification": cls,
            "classificationNote": cls_desc,
            "consensus": len(variants) == 1,
            "occurrences": len(entries),
            "sources": [{"page": e["page"], "card": e["card"], "dims": e["dims"], "scope": e["scope"]}
                        for e in plain[:5]],
        }
        if adv_entries:
            entry["advCalcs"] = sorted({f"{e['alias']}（基数: {e['baseField']}）"
                                        for e in adv_entries})
        if len(variants) == 1:
            e = representative
            if e["formula"]:
                entry["formula"] = e["formula"]
            else:
                entry["baseField"] = e["baseField"]
                entry["aggrType"] = e.get("aggrType", "")
            if e.get("advType"):
                entry["advType"] = e["advType"]
                entry["advParams"] = e.get("advParams")
            if e["formula"] and cls != "CONSTANT" and not (e.get("advType") and e.get("alias")):
                src = f"《{e['page']}》{e['card']}" if e["page"] else f"数据集《{e.get('dsName','')}》"
                scope_txt = f"；口径上下文：{'；'.join(e['scope'])}" if e["scope"] else ""
                one_line = re.sub(r'\s+', ' ', e['formula']).strip()
                candidate_rules.append(f"{name} = {one_line}（来源：{src} 等 "
                                       f"{len(entries)} 处{scope_txt}）")
        else:
            def src_of(e):
                return f"《{e['page']}》{e['card']}" if e["page"] else f"数据集《{e.get('dsName','')}》"
            def variant_text(v0):
                if v0["formula"]:
                    return re.sub(r'\s+', ' ', v0["formula"]).strip()
                ag = f"（{v0['aggrType']}）" if v0.get("aggrType") else ""
                return f"物理字段 {v0['baseField']}{ag}"
            entry["variants"] = [
                {"formula": variant_text(v[0]),
                 "sources": [src_of(e) for e in v[:3]]}
                for v in variants.values()
            ]
            # 纯物理字段的聚合方式差异（如同一"日期"字段 MIN/MAX 分作起止）降级为提示，不占冲突裁决
            if all(not v[0]["formula"] for v in variants.values()):
                entry["fieldNote"] = "同名字段不同聚合方式，属正常使用差异"
            else:
                conflicts.append({"name": name, "variants": entry["variants"]})
        metrics.append(entry)

    out = {
        "_meta": {
            "builtAt": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "uniqueMetrics": len(metrics),
            "cardFormulas": n_card_formula,
            "datasetOnlyFormulas": n_ds_only,
            "conflicts": len(conflicts),
            "classification": dict(cls_counts),
        },
        "metrics": metrics,
        "conflicts": conflicts,
        "candidateRules": sorted(set(candidate_rules)),
    }
    fp = os.path.join(workdir, "formulas.json")
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    # 控制台报告
    print(f"\n指标公式分析报告")
    print("=" * 60)
    print(f"唯一指标 {len(metrics)} 个（卡片级公式 {n_card_formula} 处，数据集级补充 {n_ds_only} 个）")
    cls_label = {"FREE": "✅ 自由重聚合", "DISTINCT": "⚠️ 需明细现算(去重)",
                 "AVG": "⚠️ 需明细现算(均值)", "NONADDITIVE": "⚠️ 需明细现算(最值)",
                 "ROW_LOGIC": "ℹ️ 行级逻辑", "TIME_MACRO": "ℹ️ 时间宏",
                 "CONSTANT": "🚫 硬编码常量"}
    for cls, n in sorted(cls_counts.items()):
        print(f"  {cls_label.get(cls, cls)}: {n} 个")
    if conflicts:
        print(f"\n🔴 同名口径冲突 {len(conflicts)} 处（第 4 步必须请用户裁决）:")
        for c in conflicts:
            print(f"  「{c['name']}」:")
            for v in c["variants"]:
                print(f"    - {v['formula']}   （{'、'.join(v['sources'][:2])}）")
    else:
        print("\n✅ 无同名口径冲突")
    print(f"\n已生成口径候选 {len(out['candidateRules'])} 条 → {fp}")

    if seed:
        # metrics.json 起草种子：共识指标直接成稿，冲突指标标 pending 待第 4 步裁决
        seed_metrics = []
        for m in metrics:
            if m["classification"] in ("PRESENTATION", "CONSTANT"):
                continue
            e = {"name": m["name"], "safety": m["classification"],
                 "synonyms": [], "exampleQuestions": []}
            dims = sorted({d for s in m.get("sources", []) for d in (s.get("dims") or [])})
            if dims:
                e["dims"] = dims
            srcs = m.get("sources") or []
            e["source"] = "dataset" if any(not s.get("page") for s in srcs) else "card"
            if not m["consensus"]:
                e["pending"] = True  # 口径冲突：第 4 步用户裁决后填 formula 并删除本标记
                e["variants"] = m.get("variants", [])
            elif m.get("formula"):
                e["formula"] = re.sub(r'\s+', ' ', m["formula"]).strip()
            else:
                e["baseField"] = m.get("baseField", m["name"])
                if m.get("aggrType"):
                    e["aggrType"] = m["aggrType"]
            seed_metrics.append(e)
        seed_out = {"version": 1,
                    "_readme": ["metrics.json 起草种子（check_formulas.py --seed-metrics 生成）："
                                "共识指标已预填公式与 safety；pending=true 的是口径冲突，"
                                "第 4 步请用户裁决后填 formula、删除 pending 与 variants；"
                                "全部确认后另存为 metrics.json 并跑 check_metrics.py 校验"],
                    "metrics": seed_metrics, "rejected": []}
        sp = os.path.join(workdir, "metrics-seed.json")
        with open(sp, "w", encoding="utf-8") as f:
            json.dump(seed_out, f, ensure_ascii=False, indent=1)
        n_pending = sum(1 for e in seed_metrics if e.get("pending"))
        print(f"已生成指标种子 {len(seed_metrics)} 条（含 {n_pending} 条待裁决冲突）→ {sp}")


if __name__ == '__main__':
    main()
