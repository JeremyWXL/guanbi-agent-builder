#!/usr/bin/env python3
"""
把 cards-raw.json 里选中的源卡抽成 createCard() 骨架，供 guanvis init 的新工程重建。

用法:
  python3 extract_card_skeletons.py <工作目录或 cards-raw.json> \
      --cdIds <cdId1,cdId2,...> -o <输出目录> [--dataset-alias DS] [--page <看板名>]

  --dataset-alias 单数据集写一个变量名（默认 DS）；选中卡片来自多个数据集时，
  写与数据集数量一致的逗号分隔变量名（如 DS1,DS2），缺省自动按 DS1…DSn 命名。

输入:
  cards-raw.json（parse_page.py 产出）或包含它的工作目录
输出:
  <输出目录>/card-reuse.json                     选中卡的结构与人工核对项
  <输出目录>/card-skeletons/card_XX_<cdId>.js    每张卡的 createCard() 骨架
  <输出目录>/card-reuse-checklist.md             重建步骤与逐卡核对清单

边界:
  - 只读，不调用 guanvis，不发布；
  - 骨架只覆盖图表类型/数据集/维度/度量/描述；格式、排序、图例、标签、
    计算字段、筛选器联动必须人工按源卡补齐；
  - checkout 的 card_*.js 是 attachCard，不要复制到新工程；本脚本从
    cards-raw.json 抽取 createCard 骨架。
"""
import glob
import json
import os
import random
import re
import string
import sys
from datetime import datetime

KNOWN_CHART_TYPES = {
    "BASIC_BAR", "BASIC_COLUMN", "BASIC_LINE", "PIE", "PIVOT_TABLE",
    "DETAIL_TABLE", "SCROLL_TABLE", "KPI_CARD", "BASIC_MAP", "WORLD_MAP", "POINT_MAP",
    "BUBBLE_MAP", "GROUPED_COLUMN", "STACKED_COLUMN", "STACKED_AREA",
    "LINE", "PARETO", "SINGLE_VALUE", "DATA_GRID", "GROUPED_TABLE",
    "STACKED_SPLIT_COLUMN", "MULTI_LINE",
}
NON_CHART_TYPES = {
    "TEXT", "PICTURE", "SELECTOR", "TREE_SELECTOR", "LAYOUT",
    "PROGRESS_BAR", "CHART", "DRILL", "COMPLEX_REPORT", "REPORT_FORM",
    "PLUGIN", "PLUGIN_LITE",
}
AGGR_TYPES = {
    "SUM": "SUM", "COUNT": "COUNT", "COUNT_DISTINCT": "COUNT_DISTINCT",
    "COUNTD": "COUNT_DISTINCT", "MAX": "MAX", "MIN": "MIN", "AVG": "AVG",
}


def die(message, code=2):
    print(f"❌ {message}", file=sys.stderr)
    sys.exit(code)


def js_str(value):
    return json.dumps(str(value or ""), ensure_ascii=False)


def one_line(value):
    """把公式/卡名压成单行——多行内容直接拼进 // 注释会截断注释并生成语法错误的 JS。"""
    return re.sub(r"\s+", " ", str(value or "")).strip()


def new_card_id():
    """生成 24 位卡片 ID（首字符字母），与 guanvis genid 的形态一致；发布前可替换。"""
    alphabet = string.ascii_lowercase + string.digits
    return random.choice(string.ascii_lowercase) + "".join(
        random.choice(alphabet) for _ in range(23))


def read_cards(path):
    if os.path.isdir(path):
        path = os.path.join(path, "cards-raw.json")
    if not os.path.isfile(path):
        die(f"未找到 {path}——先运行 parse_page.py 生成 cards-raw.json")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        die(f"{path} 解析失败：{e}")
    if not isinstance(data, dict):
        die(f"{path} 结构异常：顶层应为对象")
    pages = []
    for page_name, page in data.items():
        if str(page_name).startswith("_") or not isinstance(page, dict):
            continue
        pages.append((page_name, page))
    if not pages:
        die(f"{path} 中没有看板")
    return path, pages


def card_index(pages):
    index = {}
    for page_name, page in pages:
        for card in page.get("cards") or []:
            if not isinstance(card, dict) or not card.get("cdId"):
                continue
            item = dict(card)
            item["_pageName"] = page_name
            item["_pgId"] = page.get("pgId", "")
            index[card["cdId"]] = item
    return index


def chart_type_for(card):
    ctype = str(card.get("type") or "").upper()
    if ctype in KNOWN_CHART_TYPES:
        return ctype, ""
    if ctype in NON_CHART_TYPES or not ctype:
        return "DETAIL_TABLE", f"原卡类型 {ctype or '未知'} 不是可直接重建的图表，先按 DETAIL_TABLE 占位，人工确认"
    return "DETAIL_TABLE", f"原卡类型 {ctype} 未在已知图表类型清单内，先按 DETAIL_TABLE 占位，人工确认"


def measure_lines(card, field_ref):
    lines = []
    todos = []
    for m in card.get("measures") or []:
        if not isinstance(m, dict):
            continue
        name = one_line(m.get("name") or m.get("alias") or "")
        alias_name = one_line(m.get("alias") or "")
        formula = one_line(m.get("formula") or "")
        if not name:
            continue
        if formula:
            todos.append(f"计算字段「{alias_name or name}」原公式：{formula}")
            lines.append(f"    // TODO 计算字段 {js_str(alias_name or name)}：{formula}")
            lines.append(f"    // 请在 createCard 中重建该计算字段后，再 addMetric。")
            continue
        aggr = AGGR_TYPES.get(str(m.get("aggrType") or "").upper())
        if aggr:
            lines.append(
                f"    .addMetric({field_ref(name)}, {{ aggrType: AggrType.{aggr} }})")
        else:
            todos.append(f"度量「{alias_name or name}」聚合方式未识别（{m.get('aggrType') or '空'}）")
            lines.append(
                f"    // TODO 度量 {js_str(alias_name or name)}：原聚合方式 "
                f"{one_line(m.get('aggrType')) or '未识别'}")
            lines.append(f"    .addMetric({field_ref(name)})")
    return lines, todos


def skeleton_for(card, alias, alias_note="", multi=False):
    page = one_line(card.get("_pageName"))
    name = one_line(card.get("name") or card.get("cdId"))
    ctype, type_note = chart_type_for(card)
    dims = [one_line(d) for d in card.get("dims") or [] if d]
    filters = [one_line(f) for f in card.get("filters") or [] if f]
    dynamic = [one_line(p.get("name")) for p in card.get("dynamicParams") or []
               if isinstance(p, dict) and p.get("name")]
    qualified = multi or alias != "DS"

    def field_ref(field_name):
        return (f"field({alias}, {js_str(field_name)})" if qualified
                else f"f({js_str(field_name)})")

    measures, todos = measure_lines(card, field_ref)
    if ctype in ("BASIC_MAP", "WORLD_MAP", "POINT_MAP", "BUBBLE_MAP") \
            and not (card.get("measures") or []):
        todos.append("地图类卡片缺少 colorBy/位置编码，必须按源卡补齐着色指标或经纬度")
    lines = [
        f"// 源看板：{page}",
        f"// 源卡片：{name} ({card.get('cdId')})",
        f"// 原图表类型：{one_line(card.get('type')) or '未知'}；"
        f"数据集：{one_line(card.get('dsId')) or '未知'}",
        f"// 数据集绑定：{alias}" + (f"（{alias_note}）" if alias_note else ""),
        f"// 必读：骨架只覆盖类型/数据集/维度/度量/描述；格式、排序、图例、标签、",
        f"// 计算字段、筛选器联动必须按源卡补齐，发布前逐项核对。",
    ]
    if type_note:
        lines.append(f"// TODO 图表类型：{one_line(type_note)}")
    if filters:
        lines.append(f"// 原卡筛选：{'、'.join(filters)}（按需在页面筛选器中承接）")
    if dynamic:
        lines.append(f"// 原卡动态参数：{'、'.join(dynamic)}（按需在 createCard 中传参）")
    for todo in todos:
        lines.append(f"// TODO：{one_line(todo)}")
    lines.append("")
    card_id = new_card_id()
    lines.append(f"var card = createCard(ChartType.{ctype}, {js_str(name)})")
    lines.append(f"    // 新 ID 由抽取器生成；需要替换时运行 guanvis genid 后改 setId")
    lines.append(f"    .setId({js_str(card_id)})")
    lines.append(f"    .bindDataset({alias})")
    for dim in dims:
        lines.append(f"    .addRow({field_ref(dim)})")
    lines.extend(measures)
    lines.append(f"    .setDescription({js_str(f'从《{page}》复用：{name}')});")
    lines.append("registerCard(card.build());")
    lines.append("")
    return "\n".join(lines), todos


def safe_name(card):
    raw = f"{card.get('name') or ''}_{card.get('cdId') or ''}"
    raw = re.sub(r"[^\w\u4e00-\u9fff.-]+", "_", raw).strip("_")
    return raw[:80] or card.get("cdId", "card")


def write_checklist(out_dir, source, selected, meta):
    lines = [
        "# 卡片复用与重建清单",
        "",
        f"> 来源：`{source}`",
        f"> 生成于：{meta['builtAt']}",
        f"> 选中卡片：{len(selected)} 张",
        "",
        "## 重建步骤",
        "",
        "```bash",
        "# 1) 目标工程（按下方数据集别名表准备目标数据集）",
        meta["initCommand"],
        "",
        "# 2) 复制骨架并补齐 TODO",
        "cp card-skeletons/*.js ./dst/",
        "",
        "# 3) 新资源 ID（按需）",
        "guanvis genid",
        "",
        "# 4) 本地验证 → dry-run → 用户确认后发布",
        "guanvis preview ./dst",
        "guanvis diff ./dst",
        "guanvis publish ./dst --dry-run",
        "# 确认无误、用户同意后再执行：guanvis publish ./dst",
        "```",
        "",
    ]
    alias_map = meta.get("datasetAliases") or {}
    if len(alias_map) > 1:
        lines.extend([
            "## 数据集与别名",
            "",
            "| 源数据集 dsId | 目标变量别名 |",
            "|---|---|",
        ])
        for ds_id, alias in alias_map.items():
            lines.append(f"| `{ds_id}` | `{alias}` |")
        lines.extend([
            "",
            "> 多个数据集必须按上表顺序执行 `guanvis init ... --alias "
            + ",".join(alias_map.values()) + "`；别名与骨架里的 `.bindDataset(...)` 一一对应。",
            "",
        ])
    lines.extend([
        "> 目标 dsId 必须与源卡 dsId 一致，或目标数据集暴露同名字段。`guanvis init` 显示 0 fields 时，"
        "先用有数据集权限的账号重试；否则骨架里的 `f(\"...\")` 会报 field not found。",
        "",
        "## 逐卡核对",
        "",
    ])
    for i, item in enumerate(selected, 1):
        card = item["card"]
        lines.extend([
            f"### {i}. {one_line(card.get('name') or card.get('cdId'))}"
            f"（{item['skeleton'].split('/')[-1]}）",
            "",
            f"- 源看板：{one_line(card.get('_pageName'))}",
            f"- 源 cdId：{card.get('cdId') or ''}",
            f"- 图表类型：{one_line(card.get('type')) or '未知'}",
            f"- 数据集：`{one_line(card.get('dsId')) or '未知'}`"
            f"（变量 `{item.get('alias') or 'DS'}`）",
            f"- 维度：{'、'.join(one_line(d) for d in card.get('dims') or []) or '无'}",
            f"- 度量：{'、'.join(one_line(m.get('alias') or m.get('name') or '') for m in card.get('measures') or []) or '无'}",
        ])
        if item["todos"]:
            lines.append("- 待人工确认：")
            for todo in item["todos"]:
                lines.append(f"  - {one_line(todo)}")
        else:
            lines.append("- 待人工确认：格式、排序、图例、标签、筛选器联动、描述")
        lines.extend([
            "- [ ] 图表类型与源卡一致",
            "- [ ] 字段/维度/聚合与源卡一致",
            "- [ ] 计算字段/公式结果与源卡一致",
            "- [ ] 格式/排序/图例/标签/颜色一致",
            "- [ ] 筛选器联动已承接",
            "- [ ] 描述已填写",
            "",
        ])
    with open(os.path.join(out_dir, "card-reuse-checklist.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return
    src = args[0]
    cd_ids = []
    out_dir = "card-reuse"
    alias = "DS"
    alias_given = False
    page_filter = ""
    i = 1
    while i < len(args):
        arg = args[i]
        if arg == "--cdIds":
            if i + 1 >= len(args):
                die("--cdIds 需要逗号分隔的 cdId")
            cd_ids = [x.strip() for x in args[i + 1].split(",") if x.strip()]
            i += 2
        elif arg == "-o" or arg == "--out":
            if i + 1 >= len(args):
                die("--out 需要目录")
            out_dir = args[i + 1]
            i += 2
        elif arg == "--dataset-alias":
            if i + 1 >= len(args):
                die("--dataset-alias 需要变量名")
            alias = args[i + 1]
            alias_given = True
            i += 2
        elif arg == "--page":
            if i + 1 >= len(args):
                die("--page 需要看板名")
            page_filter = args[i + 1]
            i += 2
        else:
            die(f"未知参数：{arg}")
    if not cd_ids:
        die("必须用 --cdIds 指定要复用的卡片（逗号分隔）")
    deduped, seen = [], set()
    for cd_id in cd_ids:
        if cd_id in seen:
            print(f"⚠️ 重复 cdId 已去重：{cd_id}", file=sys.stderr)
            continue
        seen.add(cd_id)
        deduped.append(cd_id)
    cd_ids = deduped

    source, pages = read_cards(src)
    if page_filter:
        pages = [(n, p) for n, p in pages if n == page_filter]
        if not pages:
            die(f"未找到看板：{page_filter}")
    index = card_index(pages)
    missing = [x for x in cd_ids if x not in index]
    if missing:
        die(f"以下 cdId 不在选中看板里：{','.join(missing)}")

    # 数据集 → 别名：单数据集沿用 --dataset-alias（默认 DS）；多数据集必须一卡一绑定，
    # 否则所有骨架都 bindDataset(DS) 会把卡静默建到错误的数据集上。
    selected_cards = [index[x] for x in cd_ids]
    missing_ds = [c.get("cdId") for c in selected_cards if not one_line(c.get("dsId"))]
    if missing_ds:
        die(f"以下卡片缺少 dsId，无法确定字段归属：{','.join(missing_ds)}")
    ds_ids = []
    for card in selected_cards:
        ds_id = one_line(card.get("dsId"))
        if ds_id not in ds_ids:
            ds_ids.append(ds_id)
    explicit = [x.strip() for x in alias.split(",") if x.strip()] if alias_given else []
    if len(set(explicit)) != len(explicit):
        die("--dataset-alias 不能重复")
    for name in explicit:
        if not re.match(r"^[A-Za-z_$][A-Za-z0-9_$]*$", name):
            die(f"非法 JS 数据集变量名：{name}")
    if len(ds_ids) > 1:
        if explicit and len(explicit) != len(ds_ids):
            die(f"选中卡片来自 {len(ds_ids)} 个数据集（{'、'.join(ds_ids)}），"
                f"--dataset-alias 需要 {len(ds_ids)} 个逗号分隔的变量名，"
                f"收到 {len(explicit)} 个：{','.join(explicit)}")
        aliases = explicit or [f"DS{i}" for i in range(1, len(ds_ids) + 1)]
    else:
        if len(explicit) > 1:
            die(f"选中卡片只来自 {len(ds_ids) or 0} 个数据集，--dataset-alias 只应给 1 个变量名，"
                f"收到 {len(explicit)} 个：{','.join(explicit)}")
        aliases = explicit or ["DS"]
    alias_map = dict(zip(ds_ids, aliases))
    fallback_alias = aliases[0]
    multi = len(ds_ids) > 1
    init_targets = " ".join(ds_ids) if ds_ids else "<目标dsId>"
    init_command = f"guanvis init {init_targets} -d ./dst"
    if multi:
        init_command += f" --alias {','.join(aliases)}"

    skel_dir = os.path.join(out_dir, "card-skeletons")
    os.makedirs(skel_dir, exist_ok=True)
    # 重跑时先清掉上一轮的骨架：否则已从选择中移除的卡会被 cp *.js 一起带进新工程。
    for stale in glob.glob(os.path.join(skel_dir, "card_*.js")):
        os.remove(stale)

    selected = []
    for order, cd_id in enumerate(cd_ids, 1):
        card = index[cd_id]
        card_alias = alias_map.get(one_line(card.get("dsId")), fallback_alias)
        alias_note = ""
        if multi:
            alias_note = (f"数据集 {one_line(card.get('dsId')) or '未知'} → {card_alias}；"
                          f"多数据集 init 需 --alias {','.join(aliases)}")
        text, todos = skeleton_for(card, card_alias, alias_note, multi=multi)
        filename = f"card_{order:02d}_{safe_name(card)}.js"
        path = os.path.join(skel_dir, filename)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        selected.append({"card": card, "skeleton": path, "todos": todos,
                         "alias": card_alias, "chartType": chart_type_for(card)[0]})

    meta = {"builtAt": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "source": os.path.abspath(source), "datasetAlias": fallback_alias,
            "datasetIds": ds_ids, "datasetAliases": alias_map,
            "multiDataset": multi, "initCommand": init_command,
            "count": len(selected)}
    doc = {
        "meta": meta,
        "cards": [
            {
                "sourcePage": item["card"].get("_pageName"),
                "sourcePgId": item["card"].get("_pgId"),
                "cdId": item["card"].get("cdId"),
                "name": item["card"].get("name"),
                "chartType": item["chartType"],
                "originalType": item["card"].get("type"),
                "dsId": item["card"].get("dsId"),
                "dims": item["card"].get("dims") or [],
                "measures": item["card"].get("measures") or [],
                "filters": item["card"].get("filters") or [],
                "dynamicParams": item["card"].get("dynamicParams") or [],
                "skeleton": os.path.abspath(item["skeleton"]),
                "todos": item["todos"],
            }
            for item in selected
        ],
    }
    with open(os.path.join(out_dir, "card-reuse.json"), "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    write_checklist(out_dir, source, selected, meta)

    print(f"✅ 已抽取 {len(selected)} 张卡片骨架 → {os.path.abspath(out_dir)}")
    print(f"   card-reuse.json / card-skeletons/ / card-reuse-checklist.md")
    if multi:
        print("   数据集别名：" + "；".join(f"{ds} → {al}" for ds, al in alias_map.items()))
        print(f"   init 命令：{init_command}")
    for item in selected:
        print(f"   - {item['card'].get('name')} ({item['card'].get('cdId')}) "
              f"→ {os.path.basename(item['skeleton'])} [bindDataset({item['alias']})]")


if __name__ == "__main__":
    main()
