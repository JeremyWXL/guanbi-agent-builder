#!/usr/bin/env python3
"""
看板结构解析器：guancli page get --raw（JSON 主解析）→ 卡片清单
主路径解析原始 JSON，名称/ID/类型天然配对，不受文本格式变动影响；
--raw 不可用或结构不符时回退文本解析（兼容旧版 guancli），仍按 Card 块内联 **ID:** 解析。
用法: python3 parse_page.py <pageId> [pageId2 ...] -o <输出目录> [--skip-ds-formulas] [--workers 4]
输出: <输出目录>/cards-raw.json
  {看板名: {pgId, mtime, dsIds, cards: [{name, cdId, type, inPool, dsId, filters, filterDetails, unitHints,
                                        dims, measures}]},
   "_meta": {builtAt, builderVersion, biBaseUrl, parser,
             pages: {pgId: {title, mtime, cardCount, cardHash, cards: [{cdId, name}]}},
             dsFormulas: {dsId: {dsName, virtualColumns}}}}
  pages[].cardHash/cards 是学习时点的卡片结构指纹：交付后体检对比 hash+mtime 双信号，
  能具体报出"新增/删除了哪些卡片"（workbench.py --check）。
公式收割（data agent 口径字典的原料）:
  - 每张数据卡的 measures: 字段名/别名/聚合方式/计算公式/高级计算(同比占比)/fdId
  - dims: 卡片的行维度（指标的当前粒度，判断"换维度是否安全"的依据）
  - _meta.dsFormulas: 各数据集的计算字段（virtualColumns）公式原文，
    供卡片按 fdId 引用数据集计算字段时补全；--skip-ds-formulas 可关闭
哨兵: 任何看板解析出 0 张卡片即整体报错退出（exit 2），禁止静默产出空资产。
"""
import json, re, subprocess, sys, os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from hashlib import sha1

BUILDER_VERSION = "3.1.0"  # 发布时与 SKILL.md frontmatter version 同步；写入 _meta 供交付后升级提示

TEXT_ONLY_KEYS = ("页面标题:", "# Card ")  # 文本输出的特征，用于判断 --raw 是否被忽略


def run_guancli(args, timeout=120):
    r = subprocess.run(["guancli"] + args, capture_output=True, text=True, timeout=timeout)
    return r.returncode, r.stdout, r.stderr


def bi_base_url():
    code, out, _ = run_guancli(["auth", "status"], timeout=30)
    m = re.search(r'^URL:\s*(\S+)', out, re.M)
    return m.group(1).rstrip('/') if m else ""


def _structure_hash(cards):
    """卡片结构指纹：cdId+名称排序后取 hash。与 workbench.py 的实现必须保持一致。"""
    items = sorted((c.get("cdId", ""), (c.get("name") or "").strip()) for c in cards)
    return sha1(json.dumps(items, ensure_ascii=False).encode("utf-8")).hexdigest()[:12]


def _fd_name_map(data):
    """dsInfos[].columns → {fdId: 字段名}，用于把筛选器 fdId 翻译成可读名称"""
    m = {}
    for ds in data.get("dsInfos") or []:
        for col in ds.get("columns") or []:
            if col.get("fdId") and col.get("name"):
                m[col["fdId"]] = col["name"]
    return m


def _unit_hints(card):
    """从 zoneData.metric[].fieldFormat.numberFormat 提取单位线索（万/千/divideDataBy）"""
    hints = {}
    for metric in _zone_data(card).get("metric") or []:
        if not isinstance(metric, dict):
            continue
        nf = ((metric.get("fieldFormat") or {}).get("numberFormat") or {})
        prefix, div = nf.get("prefixUnit"), nf.get("divideDataBy")
        if not prefix and not div:
            continue
        fname = (metric.get("field") or {}).get("name") or metric.get("name") or ""
        hint = {}
        if prefix:
            hint["prefixUnit"] = prefix
        if isinstance(div, (int, float)) and div != 1:
            hint["divideDataBy"] = div
        if fname and hint:
            hints[fname] = hint
    return hints


def _zone_data(card):
    return (((card.get("content") or {}).get("meta") or {}).get("chartMain") or {}).get("zoneData") or {}


def _card_dims(card):
    """行维度名列表：指标的当前粒度（判断"换维度聚合是否安全"的基准）"""
    dims = []
    for d in _zone_data(card).get("row") or []:
        if isinstance(d, dict) and d.get("name"):
            dims.append(d["name"])
    return dims


def _card_measures(card):
    """收割度量字段：名称/别名/聚合方式/计算公式/高级计算/fdId——口径字典的原料"""
    measures = []
    for m in _zone_data(card).get("metric") or []:
        if not isinstance(m, dict):
            continue
        adv = (m.get("advCalc") or {}).get("advType")
        entry = {
            "name": m.get("name") or "",
            "alias": m.get("alias") or "",
            "fdId": m.get("fdId") or "",
            "dsId": m.get("dsId") or "",
        }
        if m.get("aggrType"):
            entry["aggrType"] = m["aggrType"]
        if m.get("calculationType") and m["calculationType"] != "normal":
            entry["calcType"] = m["calculationType"]
        if m.get("formula"):
            entry["formula"] = m["formula"]
        if adv:
            entry["advType"] = adv
            av = (m.get("advCalc") or {}).get("advValue") or {}
            if adv == "COMPARATIVE":
                entry["advParams"] = {k: av.get(k) for k in
                                      ("granularity", "offset", "offsetType", "valueType") if av.get(k) is not None}
        # 无公式的物理字段不记（没有信息增量），有公式/高级计算/聚合方式的才进字典
        if len(entry) > 4:
            measures.append(entry)
    return measures


def _card_filters(card, fd_names):
    """CHART 卡片的过滤器：fdId 翻译为名称，保留过滤类型与值（理解卡片语义的关键）"""
    details = []
    for f in _zone_data(card).get("filters") or []:
        if not isinstance(f, dict):
            continue
        fd_id = f.get("fdId", "")
        details.append({
            "field": fd_names.get(fd_id, fd_id),
            "filterType": f.get("filterType", ""),
            "filterValue": f.get("filterValue"),
            "level": f.get("filterLevel", ""),
        })
    return details


def fetch_ds_formulas(ds_ids, workers=4):
    """收割数据集计算字段（virtualColumns）公式。ds get --raw --brief 轻量且含 virtualColumns；
    单个失败不阻断整体（降级为只有卡片级公式）。"""
    def fetch(ds_id):
        code, out, err = run_guancli(["ds", "get", ds_id, "--raw", "--brief"], timeout=60)
        if code != 0:
            return ds_id, {"error": (err or out)[:150]}
        try:
            raw = json.loads(out)
        except json.JSONDecodeError:
            return ds_id, {"error": "RAW_NOT_JSON"}
        data = raw.get("data") or raw
        vcs = []
        for vc in data.get("virtualColumns") or []:
            if isinstance(vc, dict) and vc.get("name"):
                vcs.append({"fdId": vc.get("fdId", ""), "name": vc["name"],
                            "formula": vc.get("formula", ""),
                            "calcType": vc.get("calculationType", ""),
                            "aggrType": vc.get("aggrType", "")})
        return ds_id, {"dsName": data.get("name", ""), "virtualColumns": vcs}

    result = {}
    if not ds_ids:
        return result
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(fetch, d): d for d in ds_ids}
        for fut in as_completed(futs):
            ds_id, info = fut.result()
            result[ds_id] = info
            note = f"{len(info.get('virtualColumns', []))} 个计算字段" if "error" not in info else "获取失败(已跳过)"
            print(f"  数据集公式收割 {ds_id}: {note}", flush=True)
    return result


def parse_page_raw(page_id):
    """主路径：guancli page get --raw → 结构化 JSON 解析。失败返回 {'error': ...}"""
    code, out, err = run_guancli(["page", "get", page_id, "--raw"])
    if code != 0:
        return {"error": f"guancli page get --raw 失败: {err[:300]}", "pgId": page_id}
    try:
        raw = json.loads(out)
    except json.JSONDecodeError:
        return {"error": "RAW_NOT_JSON", "pgId": page_id}
    data = raw.get("data")
    if not isinstance(data, dict) or "cards" not in data:
        return {"error": "RAW_SCHEMA_MISMATCH", "pgId": page_id}

    fd_names = _fd_name_map(data)
    backlog = set((data.get("meta") or {}).get("backlogLayout") or [])
    ds_ids = sorted({ds["dsId"] for ds in data.get("dsInfos") or [] if ds.get("dsId")})
    cards = []
    for c in data.get("cards") or []:
        if not isinstance(c, dict) or not c.get("cdId"):
            continue
        content = c.get("content") or {}
        cd_type = content.get("chartType") or c.get("cdType") or "UNKNOWN"
        if c.get("cdType") == "SELECTOR":
            src = content.get("source") or {}
            field_name = (src.get("field") or {}).get("name", "")
            filters = [field_name] if field_name else []
            filter_details = [{"field": field_name, "selectorType": src.get("selectorType", ""),
                               "multiSelect": src.get("multiSelect")}] if field_name else []
        else:
            filter_details = _card_filters(c, fd_names)
            filters = [d["field"] for d in filter_details]
        cards.append({
            "name": (c.get("name") or "").strip() or c["cdId"],
            "cdId": c["cdId"],
            "type": cd_type,
            "inPool": c["cdId"] in backlog,
            "dsId": content.get("dsId", ""),
            "filters": filters,
            "filterDetails": filter_details,
            "unitHints": _unit_hints(c),
            "dims": _card_dims(c),
            "measures": _card_measures(c),
        })
    return {
        "title": (data.get("name") or page_id).strip(),
        "pgId": page_id,
        "mtime": data.get("utime", ""),
        "dsIds": ds_ids,
        "cards": cards,
        "_rawCardCount": len(data.get("cards") or []),
    }


def parse_page_text(page_id):
    """回退路径：解析文本输出。按 Card 块内联 **ID:** 配对，禁止跨块顺序配对。"""
    code, text, err = run_guancli(["page", "get", page_id])
    if code != 0:
        return {"error": err[:300], "pgId": page_id}
    m = re.search(r'^页面标题: (.+)$', text, re.M)
    title = m.group(1).strip() if m else page_id
    mm = re.search(r'^更新时间: (.+)$', text, re.M)
    mtime = mm.group(1).strip() if mm else ""
    cards = []
    blocks = re.split(r'(?=^# Card )', text, flags=re.M)
    for b in blocks:
        m1 = re.match(r'# Card \d+(?:\s*\[[^\]]*\])?:[ \t]*([^\n]*)', b)
        m2 = re.search(r'\*\*ID:\*\* (\w+)', b)
        m3 = re.search(r'\*\*Type:\*\* (\w+)', b)
        if not (m1 and m2):
            continue
        filters = re.findall(r'- 筛选器名称: (.+)', b)
        header = b.split('\n')[0]
        cards.append({
            "name": m1.group(1).strip() or m2.group(1),
            "cdId": m2.group(1),
            "type": m3.group(1) if m3 else "UNKNOWN",
            "inPool": "[卡片池]" in header,
            "dsId": "",
            "filters": [f.strip() for f in filters],
            "filterDetails": [],
            "unitHints": {},
            "dims": [],
            "measures": [],
        })
    return {"title": title, "pgId": page_id, "mtime": mtime, "dsIds": [], "cards": cards,
            "_parser": "text-fallback"}


def parse_page(page_id):
    info = parse_page_raw(page_id)
    if info.get("error") in ("RAW_NOT_JSON", "RAW_SCHEMA_MISMATCH"):
        print(f"  警告: --raw 解析不可用（{info['error']}），回退文本解析", flush=True)
        info = parse_page_text(page_id)
    return info


def main():
    args = sys.argv[1:]
    out = '.'
    skip_ds = '--skip-ds-formulas' in args
    workers = 4
    page_ids = []
    i = 0
    while i < len(args):
        if args[i] == '-o':
            out = args[i + 1]
            i += 2
        elif args[i] == '--skip-ds-formulas':
            i += 1
        elif args[i] == '--workers':
            workers = int(args[i + 1])
            i += 2
        else:
            page_ids.append(args[i])
            i += 1
    if not page_ids:
        sys.exit("用法: python3 parse_page.py <pageId> [pageId2 ...] -o <输出目录> [--skip-ds-formulas] [--workers 4]")
    os.makedirs(out, exist_ok=True)

    # 并发解析各看板（保持用户勾选顺序输出）
    parsed = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(parse_page, pid): pid for pid in page_ids}
        for fut in as_completed(futs):
            pid = futs[fut]
            print(f"解析看板 {pid} ...", flush=True)
            parsed[pid] = fut.result()

    result = {}
    failed, empty = [], []
    parsers = set()
    for pid in page_ids:
        info = parsed[pid]
        if "error" in info and info["error"] not in ("RAW_NOT_JSON", "RAW_SCHEMA_MISMATCH"):
            print(f"  失败: {info['error']}")
            failed.append(pid)
            continue
        parsers.add(info.pop("_parser", "raw"))
        raw_count = info.pop("_rawCardCount", None)
        if raw_count is not None and len(info["cards"]) < raw_count:
            # JSON 里明明有卡片却一张都没解析出来 = 输出结构已变更
            print(f"  ❌ 哨兵: 原始数据含 {raw_count} 张卡片但解析出 {len(info['cards'])} 张——"
                  f"guancli 输出结构可能已变更，禁止继续")
            empty.append(pid)
            continue
        if not info["cards"]:
            print(f"  ⚠️ {info['title']}: 该看板没有任何卡片（空看板/总览页），已跳过")
            continue
        n_data = sum(1 for c in info['cards'] if c['type'] not in ('SELECTOR', 'TEXT'))
        n_pool = sum(1 for c in info['cards'] if c['inPool'])
        n_formula = sum(1 for c in info['cards'] for m in c.get('measures', []) if m.get('formula'))
        print(f"  {info['title']}: {len(info['cards'])} 张卡片"
              f"（数据卡 {n_data}，筛选器/文本 {len(info['cards'])-n_data}，卡片池 {n_pool}，"
              f"公式字段 {n_formula}）")
        result[info['title']] = info
    if empty:
        sys.exit(f"解析失败: {len(empty)} 个看板解析异常（{', '.join(empty)}）。"
                 f"请检查 guancli 版本兼容性后再试")
    if not result:
        sys.exit(f"解析失败: 全部 {len(failed)} 个看板获取失败（{', '.join(failed)}）")

    # 数据集计算字段公式收割（卡片按 fdId 引用数据集计算字段时补全口径）
    ds_formulas = {}
    if not skip_ds:
        all_ds = sorted({d for v in result.values() if isinstance(v, dict)
                         for d in (v.get("dsIds") or [])})
        ds_formulas = fetch_ds_formulas(all_ds, workers)

    # 学习时点元数据：供交付后体检（看板是否在 agent 学习后被改过、改了什么、脚本可否升级）
    result["_meta"] = {
        "builtAt": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "builderVersion": BUILDER_VERSION,
        "biBaseUrl": bi_base_url(),
        "parser": "+".join(sorted(parsers)),
        "pages": {v["pgId"]: {"title": k, "mtime": v.get("mtime", ""),
                              "cardCount": len(v["cards"]),
                              "cardHash": _structure_hash(v["cards"]),
                              "cards": [{"cdId": c["cdId"], "name": c["name"]} for c in v["cards"]]}
                  for k, v in result.items() if isinstance(v, dict) and "pgId" in v},
        "dsFormulas": ds_formulas,
    }
    out_file = os.path.join(out, 'cards-raw.json')
    with open(out_file, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    print(f"\n已写入 {out_file}")
    if failed:
        print(f"⚠️ {len(failed)} 个看板获取失败已跳过: {', '.join(failed)}")


if __name__ == '__main__':
    main()
