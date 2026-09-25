#!/usr/bin/env python3
"""
维度档案校验器：dimensions.json（机器可读维度档案，第 4 步确认产物）的质量闸门
用法: python3 check_dims.py <工作目录>              # 读 dimensions.json 校验
      python3 check_dims.py <工作目录> --seed-dims  # 从 cards-raw.json + 采样列画像 + metrics.json 生成 dimensions-seed.json
校验项（❌ 错误未清零退出码 1，禁止进入第 5 步；⚠️ 警告不阻断但必须在确认点告知用户）:
  结构: name 必填且唯一；synonyms/values 必须是数组；valueAliases 必须是对象，且目标值必须已收录在 values 中
  同义词: 维度之间 name/synonyms 禁止撞车；与 metrics.json 指标的 name/synonyms 撞车同为 ❌
          （"门店"既是维度叫法又是指标名 = 问数路由歧义）
  取值: 同一成员值出现在多个维度 → ⚠️ 列出"值 → 维度"映射（交付助手命中时必须选项式消歧）
        同维度内两个值归一化后相同或互为包含 → ⚠️ 建议收编进 valueAliases（"华东区"→"华东"）
  覆盖: metrics.json 的 dims 未在 dimensions.json 收编 → ⚠️；档案维度未在任何卡片/筛选器出现 → ⚠️；
        维度未收录成员值（values 为空）→ ⚠️（取值匹配将无候选可给）
参照: metrics.json 缺失时跳过跨档案撞车与 dims 覆盖校验；cards-raw.json 缺失时跳过卡片覆盖校验；
      card-data/_sample_index.json 缺失时种子不带枚举值
"""
import json, os, sys, unicodedata

VALUE_CAP = 60        # 单维度种子最多收录成员值个数
SIM_MIN_LEN = 2       # 参与"互为包含"相似判定的较短值最小长度（防单字误报）


def norm(s):
    """取值归一化：全半角统一 + 去空白 + 小写。用于相似值检测，不改写原始值。"""
    return "".join(unicodedata.normalize("NFKC", str(s)).split()).lower()


def load(workdir, fn):
    fp = os.path.join(workdir, fn)
    if not os.path.exists(fp):
        return None
    with open(fp, encoding="utf-8") as f:
        return json.load(f)


def card_dims(raw):
    """cards-raw.json 中出现的全部维度名：数据卡片行维度 + 筛选器关联字段。"""
    known = set()
    for k, v in (raw or {}).items():
        if k.startswith("_") or not isinstance(v, dict):
            continue
        for c in v.get("cards") or []:
            for d in c.get("dims") or []:
                known.add(d)
            for fd in c.get("filterDetails") or []:
                if fd.get("field"):
                    known.add(fd["field"])
    return known


def metric_words(doc):
    """metrics.json 的全部指标用词（name + synonyms）——维度叫法与之撞车即路由歧义。"""
    words = {}
    for m in (doc or {}).get("metrics") or []:
        name = (m.get("name") or "").strip()
        if name:
            words.setdefault(name, name)
        for syn in m.get("synonyms") or []:
            syn = (syn or "").strip()
            if syn:
                words.setdefault(syn, name)
    return words


def seed(workdir):
    raw = load(workdir, "cards-raw.json")
    if raw is None:
        sys.exit(f"找不到 {workdir}/cards-raw.json——先跑第 2 步 parse_page.py 学习看板")
    names = set(card_dims(raw))
    mdoc = load(workdir, "metrics.json") or load(workdir, "metrics-seed.json")
    for m in (mdoc or {}).get("metrics") or []:
        names.update(m.get("dims") or [])
    if not names:
        sys.exit("cards-raw.json / metrics 里没有任何维度可收割——请先完成第 2 步资产学习")

    # 成员值：从采样列画像收割枚举值（列名 == 维度名 且被判定为枚举列）
    values = {n: [] for n in names}
    idx = load(workdir, os.path.join("card-data", "_sample_index.json")) or {}
    for entry in idx.values():
        for col, p in (entry.get("profile") or {}).items():
            if col in values and isinstance(p, dict):
                for v in p.get("enum") or []:
                    if v not in values[col] and len(values[col]) < VALUE_CAP:
                        values[col].append(v)

    # 易混维度建议：名称互为包含（如"大区"与"销售大区"）——第 4 步请用户确认叫法分工
    ordered = sorted(names)
    similar = {n: [] for n in ordered}
    for i, a in enumerate(ordered):
        for b in ordered[i + 1:]:
            if a != b and (a in b or b in a):
                similar[a].append(b)
                similar[b].append(a)

    dims = []
    for n in ordered:
        e = {"name": n, "field": n, "synonyms": [], "values": values[n],
             "valueAliases": {}, "source": "card"}
        if similar[n]:
            e["similarTo"] = sorted(similar[n])
        dims.append(e)
    out = {"version": 1,
           "_readme": ["dimensions.json 起草种子（check_dims.py --seed-dims 生成）："
                       "维度名来自卡片行维度/筛选器字段/指标 dims；values 来自采样列画像枚举值（截断采样可能不全）；"
                       "similarTo 是按名称包含关系自动建议的易混维度，第 4 步请用户确认叫法分工；"
                       "全部确认后另存为 dimensions.json 并跑 check_dims.py 校验"],
           "dimensions": dims}
    sp = os.path.join(workdir, "dimensions-seed.json")
    with open(sp, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    n_vals = sum(1 for d in dims if d["values"])
    n_sim = sum(1 for d in dims if d.get("similarTo"))
    print(f"已生成维度种子 {len(dims)} 个（{n_vals} 个带成员值，{n_sim} 个有易混维度建议）→ {sp}")


def main():
    argv = [a for a in sys.argv[1:] if a != "--seed-dims"]
    workdir = argv[0] if argv else "."
    if len(argv) != len(sys.argv) - 1:
        seed(workdir)
        return

    doc = load(workdir, "dimensions.json")
    if doc is None:
        sys.exit(f"找不到 {workdir}/dimensions.json——第 4 步口径确认后由 dimensions-seed.json 转写生成")
    errors, warns = [], []

    dims = doc.get("dimensions")
    if not isinstance(dims, list):
        sys.exit("dimensions.json 结构错误：顶层 dimensions 必须是数组")

    # ---- 结构校验 ----
    seen = {}
    for i, d in enumerate(dims):
        tag = f"dimensions[{i}]「{(d or {}).get('name', '?')}」"
        if not isinstance(d, dict) or not (d.get("name") or "").strip():
            errors.append(f"{tag}: name 必填且非空")
            continue
        name = d["name"].strip()
        if name in seen:
            errors.append(f"{tag}: 与 dimensions[{seen[name]}] 重名——name 必须唯一")
        seen[name] = i
        for k in ("synonyms", "values", "similarTo"):
            if k in d and not isinstance(d[k], list):
                errors.append(f"{tag}: {k} 必须是数组")
        va = d.get("valueAliases")
        if va is not None and not isinstance(va, dict):
            errors.append(f"{tag}: valueAliases 必须是对象（别名 → 标准成员值）")
        elif isinstance(va, dict):
            values = d.get("values") or []
            for alias, target in va.items():
                if norm(alias) == norm(target):
                    warns.append(f"「{name}」的值别名「{alias}」与目标值相同，无信息增量")
                elif values and target not in values:
                    errors.append(f"「{name}」的值别名「{alias}」指向「{target}」，但 values 未收录该值——先补进 values")
        if not d.get("values"):
            warns.append(f"「{name}」未收录成员值（values 为空）——取值匹配将无候选可给，建议从采样枚举或取数结果补充")

    # ---- 同义词撞车（维度之间 + 与指标档案）----
    owners = {name: name for name in seen}  # 词 → 占用维度
    for d in dims:
        name = (d.get("name") or "").strip()
        for syn in d.get("synonyms") or []:
            syn = (syn or "").strip()
            if not syn:
                continue
            if syn == name:
                warns.append(f"「{name}」: 同义词与本名相同（{syn}），无信息增量")
            elif syn in owners and owners[syn] != name:
                errors.append(f"「{name}」的同义词「{syn}」与维度「{owners[syn]}」撞车——用户说这个词时无法确定指哪个维度，必须改名或删除")
            else:
                owners[syn] = name
    mdoc = load(workdir, "metrics.json")
    if mdoc:
        mwords = metric_words(mdoc)
        for word, owner in owners.items():
            if word in mwords:
                errors.append(f"维度用词「{word}」（维度「{owner}」）与指标「{mwords[word]}」撞车——问数路由歧义，维度侧必须换叫法")
        # 指标 dims 覆盖
        for m in mdoc.get("metrics") or []:
            for dd in m.get("dims") or []:
                if dd not in seen:
                    warns.append(f"指标「{m.get('name')}」的维度「{dd}」未在 dimensions.json 收编")

    # ---- 取值校验：跨维度重叠 + 同维度相似 ----
    value_home = {}  # 值 → [维度...]
    for d in dims:
        for v in d.get("values") or []:
            value_home.setdefault(str(v), set()).add((d.get("name") or "").strip())
    shared = {v: sorted(hs) for v, hs in value_home.items() if len(hs) > 1}
    if shared:
        warns.append(f"{len(shared)} 个成员值跨维度重叠——交付助手命中时必须选项式消歧：")
        for v, hs in sorted(shared.items()):
            warns.append(f"    「{v}」同时属于：{'、'.join(hs)}")
    for d in dims:
        name = (d.get("name") or "").strip()
        vals = [str(v) for v in d.get("values") or []]
        aliased = set((d.get("valueAliases") or {}).keys())
        for i, a in enumerate(vals):
            for b in vals[i + 1:]:
                na, nb = norm(a), norm(b)
                if not na or not nb or na == nb and a == b:
                    continue
                if na == nb:
                    warns.append(f"「{name}」的值「{a}」与「{b}」归一化后相同——建议保留一个，另一个收进 valueAliases")
                elif len(min(na, nb, key=len)) >= SIM_MIN_LEN and (na in nb or nb in na) \
                        and a not in aliased and b not in aliased:
                    warns.append(f"「{name}」的值「{a}」与「{b}」互为包含——若用户常混用，建议收进 valueAliases")

    # ---- 卡片覆盖 ----
    raw = load(workdir, "cards-raw.json")
    if raw:
        known = card_dims(raw)
        for d in dims:
            name = (d.get("name") or "").strip()
            if name and name not in known:
                warns.append(f"维度「{name}」未在任何卡片/筛选器出现（SQL 独有维度可忽略）")

    # ---- 报告 ----
    print(f"\n维度档案校验（{workdir}/dimensions.json）")
    print("=" * 60)
    print(f"已确认维度 {len(dims)} 个，成员值共 {sum(len(d.get('values') or []) for d in dims)} 个")
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
