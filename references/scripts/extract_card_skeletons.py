#!/usr/bin/env python3
"""
把 cards-raw.json 里选中的源卡抽成 createCard() 骨架，供 guanvis init 的新工程重建。

用法:
  python3 extract_card_skeletons.py <工作目录或 cards-raw.json> \
      --cdIds <cdId1,cdId2,...> -o <输出目录> [--dataset-alias DS] [--page <看板名>]

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
import json
import os
import random
import re
import string
import sys
from datetime import datetime

KNOWN_CHART_TYPES = {
    "BASIC_BAR", "BASIC_COLUMN", "BASIC_LINE", "PIE", "PIVOT_TABLE",
    "DETAIL_TABLE", "KPI_CARD", "BASIC_MAP", "WORLD_MAP", "POINT_MAP",
    "BUBBLE_MAP", "GROUPED_COLUMN", "STACKED_COLUMN", "STACKED_AREA",
    "LINE", "PARETO", "SINGLE_VALUE", "DATA_GRID", "GROUPED_TABLE",
    "STACKED_SPLIT_COLUMN", "MULTI_LINE", "TABLE",
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
        return "TABLE", f"原卡类型 {ctype or '未知'} 不是可直接重建的图表，先按 TABLE 占位，人工确认"
    return "TABLE", f"原卡类型 {ctype} 未在已知图表类型清单内，先按 TABLE 占位，人工确认"


def measure_lines(card, alias):
    lines = []
    todos = []
    for m in card.get("measures") or []:
        if not isinstance(m, dict):
            continue
        name = m.get("name") or m.get("alias") or ""
        alias_name = m.get("alias") or ""
        formula = m.get("formula") or ""
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
                f"    .addMetric(f({js_str(name)}, {{ aggrType: AggrType.{aggr} }}))")
        else:
            todos.append(f"度量「{alias_name or name}」聚合方式未识别（{m.get('aggrType') or '空'}）")
            lines.append(
                f"    // TODO 度量 {js_str(alias_name or name)}：原聚合方式 {m.get('aggrType') or '未识别'}")
            lines.append(f"    .addMetric(f({js_str(name)}))")
    return lines, todos


def skeleton_for(card, alias):
    page = card.get("_pageName") or ""
    name = card.get("name") or card.get("cdId")
    ctype, type_note = chart_type_for(card)
    dims = [str(d) for d in card.get("dims") or [] if d]
    filters = [str(f) for f in card.get("filters") or [] if f]
    dynamic = [str(p.get("name") or "") for p in card.get("dynamicParams") or []
               if isinstance(p, dict) and p.get("name")]
    measures, todos = measure_lines(card, alias)
    lines = [
        f"// 源看板：{page}",
        f"// 源卡片：{name} ({card.get('cdId')})",
        f"// 原图表类型：{card.get('type') or '未知'}；数据集：{card.get('dsId') or '未知'}",
        f"// 必读：骨架只覆盖类型/数据集/维度/度量/描述；格式、排序、图例、标签、",
        f"// 计算字段、筛选器联动必须按源卡补齐，发布前逐项核对。",
    ]
    if type_note:
        lines.append(f"// TODO 图表类型：{type_note}")
    if filters:
        lines.append(f"// 原卡筛选：{'、'.join(filters)}（按需在页面筛选器中承接）")
    if dynamic:
        lines.append(f"// 原卡动态参数：{'、'.join(dynamic)}（按需在 createCard 中传参）")
    for todo in todos:
        lines.append(f"// TODO：{todo}")
    lines.append("")
    card_id = new_card_id()
    lines.append(f"var card = createCard(ChartType.{ctype}, {js_str(name)})")
    lines.append(f"    // 新 ID 由抽取器生成；需要替换时运行 guanvis genid 后改 setId")
    lines.append(f"    .setId({js_str(card_id)})")
    lines.append(f"    .bindDataset({alias})")
    for dim in dims:
        lines.append(f"    .addRow(f({js_str(dim)}))")
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
        "# 1) 目标工程（把 <目标dsId> 换成新看板要用的数据集）",
        "guanvis init <目标dsId> -d ./dst",
        "",
        "# 2) 复制骨架并补齐 TODO",
        "cp card-skeletons/*.js ./dst/",
        "",
        "# 3) 新资源 ID（按需）",
        "guanvis genid",
        "",
        "# 4) 本地验证 → dry-run → 发布",
        "guanvis preview ./dst",
        "guanvis diff ./dst",
        "guanvis publish ./dst --dry-run",
        "guanvis publish ./dst",
        "```",
        "",
        "> 目标 dsId 必须与源卡 dsId 一致，或目标数据集暴露同名字段。`guanvis init` 显示 0 fields 时，"
        "先用有数据集权限的账号重试；否则骨架里的 `f(\"...\")` 会报 field not found。",
        "",
        "## 逐卡核对",
        "",
    ]
    for i, item in enumerate(selected, 1):
        card = item["card"]
        lines.extend([
            f"### {i}. {card.get('name') or card.get('cdId')}（{item['skeleton'].split('/')[-1]}）",
            "",
            f"- 源看板：{card.get('_pageName') or ''}",
            f"- 源 cdId：{card.get('cdId') or ''}",
            f"- 图表类型：{card.get('type') or '未知'}",
            f"- 数据集：`{card.get('dsId') or '未知'}`",
            f"- 维度：{'、'.join(card.get('dims') or []) or '无'}",
            f"- 度量：{'、'.join((m.get('alias') or m.get('name') or '') for m in card.get('measures') or []) or '无'}",
        ])
        if item["todos"]:
            lines.append("- 待人工确认：")
            for todo in item["todos"]:
                lines.append(f"  - {todo}")
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

    source, pages = read_cards(src)
    if page_filter:
        pages = [(n, p) for n, p in pages if n == page_filter]
        if not pages:
            die(f"未找到看板：{page_filter}")
    index = card_index(pages)
    missing = [x for x in cd_ids if x not in index]
    if missing:
        die(f"以下 cdId 不在选中看板里：{','.join(missing)}")

    os.makedirs(os.path.join(out_dir, "card-skeletons"), exist_ok=True)
    selected = []
    for order, cd_id in enumerate(cd_ids, 1):
        card = index[cd_id]
        text, todos = skeleton_for(card, alias)
        filename = f"card_{order:02d}_{safe_name(card)}.js"
        path = os.path.join(out_dir, "card-skeletons", filename)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        selected.append({"card": card, "skeleton": path, "todos": todos,
                         "chartType": chart_type_for(card)[0]})

    meta = {"builtAt": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "source": os.path.abspath(source), "datasetAlias": alias,
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
    for item in selected:
        print(f"   - {item['card'].get('name')} ({item['card'].get('cdId')}) → {os.path.basename(item['skeleton'])}")


if __name__ == "__main__":
    main()
