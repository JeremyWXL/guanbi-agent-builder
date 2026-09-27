#!/usr/bin/env python3
"""
增量学习合并器：把新看板/改版看板的最新解析合并进交付包 cards.json（slim 形态）
用法: python3 merge_cards.py <工作目录> --package <交付包路径> --pages <新看板ID...> [--remove-pages <pgId...>] [--workers 4]
  --pages：新看板（加入）或已学看板（改版重学）的 pageId；结构未变的页不重学不重采样
  --remove-pages：整页移除的 pageId
输入: <交付包>/references/cards.json（只读；先备份到 <工作目录>/cards.json.bak-incr-<时间戳>）
输出: <工作目录>/cards-merged.json（新 slim cards.json）
      <工作目录>/incr-report.json（diff 详情 + 受影响清单，供后续脚本与用户确认）
合并规则:
  - 新页直接加入（与已学看板同名则拒绝，exit 1——cards.json 以看板名为键，同名会互相覆盖）；
    旧页比对卡片结构指纹（cardHash，与 parse_page.py / workbench.py 一致），
    未变且未改名的页原样保留；变了的页 cards 列表整体替换，报告具体增删/改名；
    页面改名即使卡片未变也走变更路径（采样 key 是"页面名__卡片名"，改名即孤儿，需换键重采）
  - 被删卡片不引入 tombstone 标记：其口径引用由 check_metrics 闸门与 eval_examples 回归兜底，
    受影响清单（affectedExamples/affectedMetrics）进报告请用户确认
  - _meta.pages 逐页更新 {title, mtime, cardHash, cards}；dsFormulas 取并集；
    新增 _meta.incrLog 变更履历与 lastIncrAt
哨兵: 任一看板解析出 0 张卡片即整体报错退出（exit 2），禁止带着空资产继续
退出码: 0 成功 / 1 参数或 IO 错误 / 2 解析哨兵
"""
import argparse, json, os, shutil, sys
from datetime import datetime
from hashlib import sha1

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import parse_page
from sample_cards import safe_name

BUILDER_VERSION = "4.5.0"  # 与 parse_page.py 同步；合并不改版本号（交付更新时统一升）


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def structure_hash(cards):
    """卡片结构指纹：cdId+名称排序后取 hash。与 parse_page.py / workbench.py 的实现必须保持一致。"""
    items = sorted((c.get("cdId", ""), (c.get("name") or "").strip()) for c in cards)
    return sha1(json.dumps(items, ensure_ascii=False).encode("utf-8")).hexdigest()[:12]


def diff_cards(learned, current):
    """对比学习时与当前的卡片清单，报出具体增删/改名。与 workbench.py _diff_cards 同构。"""
    old = {c.get("cdId"): (c.get("name") or "").strip() for c in learned or []}
    new = {c.get("cdId"): (c.get("name") or "").strip() for c in current or []}
    added = [n for cid, n in new.items() if cid not in old]
    removed = [n for cid, n in old.items() if cid not in new]
    renamed = [f"{old[cid]}→{new[cid]}" for cid in old.keys() & new.keys() if old[cid] != new[cid]]
    return {"added": added, "removed": removed, "renamed": renamed}


def slim_card(card):
    """交付 slim 形态：数据卡保留语义字段；筛选器卡另保留直达链接/降级判断原料。
    filterDetails 原样带入（隐藏筛选上下文，check_formulas 口径字典 scope 的原料）。"""
    out = {
        "name": card.get("name"),
        "cdId": card.get("cdId"),
        "type": card.get("type"),
        "dsId": card.get("dsId", ""),
        "dims": card.get("dims") or [],
        "measures": card.get("measures") or [],
        "filters": card.get("filters") or [],
        "filterDetails": card.get("filterDetails") or [],
        "unitHints": card.get("unitHints") or {},
    }
    if card.get("type") in ("SELECTOR", "TEXT"):
        for k in ("inFilterBar", "linkedCardCount", "defaultValueType", "multiSelect", "selectorType"):
            if k in card:
                out[k] = card[k]
    else:
        out["filtered"] = bool(card.get("filtered"))
    return out


def page_entry(title, pg_id, info):
    """新页/变更页的交付条目"""
    return {
        "title": title,
        "pgId": pg_id,
        "dsUsage": info.get("dsUsage") or {},
        "cards": [slim_card(c) for c in info["cards"]],
    }


def meta_page(title, info):
    """_meta.pages 条目：学习时点快照（体检对比与增量 diff 的基准）"""
    return {
        "title": title,
        "mtime": info.get("mtime", ""),
        "cardCount": len(info["cards"]),
        "cardHash": structure_hash(info["cards"]),
        "cards": [{"cdId": c["cdId"], "name": c["name"]} for c in info["cards"]],
    }


def main(args=None):
    if args is None:
        ap = argparse.ArgumentParser(
            prog="merge_cards.py",
            description="增量学习合并器：新看板/改版看板解析合并进交付包 cards.json")
        ap.add_argument("workdir", help="增量会话工作目录（输出 cards-merged.json / incr-report.json）")
        ap.add_argument("--package", required=True, help="交付包路径（读 references/cards.json，只读）")
        ap.add_argument("--pages", nargs="+", default=[], metavar="PAGE_ID",
                        help="新看板或改版重学的 pageId（结构未变的页自动跳过）")
        ap.add_argument("--remove-pages", nargs="+", default=[], metavar="PG_ID",
                        help="整页移除的 pageId")
        ap.add_argument("--workers", type=int, default=4, help="数据集公式收割并发数")
        args = ap.parse_args()
        if not args.pages and not args.remove_pages:
            ap.error("--pages 与 --remove-pages 至少给一个")

    os.makedirs(args.workdir, exist_ok=True)
    cards_path = os.path.join(args.package, "references", "cards.json")
    if not os.path.exists(cards_path):
        sys.exit(f"❌ 找不到 {cards_path}——交付包缺少 references/cards.json")
    with open(cards_path, encoding="utf-8") as f:
        doc = json.load(f)
    meta = doc.get("_meta") or {}
    learned_pages = meta.get("pages") or {}

    # 备份交付包 cards.json（项目 .bak 惯例，改出问题可回滚）
    bak = os.path.join(args.workdir, f"cards.json.bak-incr-{datetime.now().strftime('%Y%m%d-%H%M%S')}")
    shutil.copy2(cards_path, bak)

    # 解析 --pages（新页 + 改版重学页）；任一看板 0 卡片 → 哨兵 exit 2
    fresh, failed = {}, []
    for pid in args.pages:
        info = parse_page.parse_page(pid)
        if info.get("error"):
            failed.append((pid, info["error"]))
        elif not info.get("cards"):
            failed.append((pid, "解析出 0 张卡片（空看板/总览页）"))
        else:
            fresh[pid] = info
    if failed:
        for pid, err in failed:
            print(f"❌ 看板 {pid}: {err}", file=sys.stderr)
        sys.exit(2)

    merged = {k: v for k, v in doc.items() if k != "_meta"}
    new_meta_pages = dict(learned_pages)
    added_pages, changed_pages, unchanged_pages, removed_pages = [], [], [], []
    renamed_pages = []                    # {pgId, old, new}：页面改名（卡片可能未变，但采样 key 含页面名，需换键重采）
    removed_cards, renamed_cards = [], []   # {pgId, page, name/old/new, cdId}
    resample, touched_ds = set(), set()

    for pid, info in fresh.items():
        title = info["title"]
        if pid not in learned_pages:
            existing = merged.get(title)
            if isinstance(existing, dict) and existing.get("pgId") and existing["pgId"] != pid:
                print(f"❌ 新看板《{title}》与已学看板（pgId={existing['pgId']}）同名——"
                      f"cards.json 以看板名为键，同名会互相覆盖；请先在 BI 中改名区分后再增量学习",
                      file=sys.stderr)
                sys.exit(1)
            merged[title] = page_entry(title, pid, info)
            new_meta_pages[pid] = meta_page(title, info)
            added_pages.append({"pgId": pid, "title": title, "cardCount": len(info["cards"])})
            resample.update(c["cdId"] for c in info["cards"])
            touched_ds.update(info.get("dsIds") or [])
            print(f"  ＋ 新增页面《{title}》{len(info['cards'])} 张卡片")
            continue
        old_info = learned_pages[pid]
        old_title = old_info.get("title", title)
        # 结构未变且页面未改名才跳过；改名要走变更路径换键（采样 key 是"页面名__卡片名"，改名即孤儿）
        if (old_info.get("cardHash") and structure_hash(info["cards"]) == old_info["cardHash"]
                and old_title == title):
            unchanged_pages.append({"pgId": pid, "title": old_title})
            if info.get("mtime") and info["mtime"] != old_info.get("mtime"):
                new_meta_pages[pid] = dict(old_info, mtime=info["mtime"])  # 结构未变，仅刷 mtime 供体检参考
            print(f"  ＝ 《{old_title}》卡片清单未变，跳过重学")
            continue
        # 结构变了或页面改名：diff + 整体替换
        ch = diff_cards(old_info.get("cards"), info["cards"])
        if old_title != title:
            merged.pop(old_title, None)  # 页面改名：旧标题键移除
            renamed_pages.append({"pgId": pid, "old": old_title, "new": title})
        merged[title] = page_entry(title, pid, info)
        new_meta_pages[pid] = meta_page(title, info)
        changed_pages.append({"pgId": pid, "title": title,
                              **({"renamedFrom": old_title} if old_title != title else {}), **ch})
        resample.update(c["cdId"] for c in info["cards"])
        touched_ds.update(info.get("dsIds") or [])
        old_names = {c["cdId"]: c["name"] for c in old_info.get("cards") or []}
        new_names = {c["cdId"]: c["name"] for c in info["cards"]}
        for cid, name in old_names.items():
            if cid not in new_names:
                removed_cards.append({"pgId": pid, "page": old_title, "name": name, "cdId": cid})
            elif new_names[cid] != name:
                renamed_cards.append({"pgId": pid, "page": old_title, "old": name, "new": new_names[cid], "cdId": cid})
        rename_note = f"；页面改名《{old_title}》→《{title}》" if old_title != title else ""
        print(f"  ✎ 《{old_title}》卡片变更：+{len(ch['added'])} / -{len(ch['removed'])} / 改名 {len(ch['renamed'])}{rename_note}")

    # 整页移除
    for pid in args.remove_pages:
        info = learned_pages.get(pid)
        if not info:
            print(f"  ⚠️ 看板 {pid} 不在已学清单中，跳过移除", file=sys.stderr)
            continue
        title = info.get("title", pid)
        merged.pop(title, None)
        new_meta_pages.pop(pid, None)
        names = [c.get("name", c.get("cdId")) for c in info.get("cards") or []]
        removed_pages.append({"pgId": pid, "title": title, "cardCount": info.get("cardCount", 0), "cards": names})
        for c in info.get("cards") or []:
            removed_cards.append({"pgId": pid, "page": title, "name": c.get("name", ""), "cdId": c.get("cdId", "")})
        print(f"  － 移除页面《{title}》{info.get('cardCount', 0)} 张卡片")

    # 采样文件 key（页面名__卡片名）：被删/改名卡片的旧 key 需清理（重命名即孤儿）；
    # 页面改名时旧页面名下全部采样 key 同样成为孤儿
    prune_keys = [f"{c['page']}__{safe_name(c['name'])}" for c in removed_cards]
    prune_keys += [f"{r['page']}__{safe_name(r['old'])}" for r in renamed_cards]
    for rp in renamed_pages:
        for c in (learned_pages.get(rp["pgId"]) or {}).get("cards") or []:
            prune_keys.append(f"{rp['old']}__{safe_name(c.get('name') or c.get('cdId', ''))}")

    # 数据集增删（dsUsage 并集）
    old_ds = set()
    for k, v in doc.items():
        if k.startswith("_") or not isinstance(v, dict):
            continue
        old_ds.update((v.get("dsUsage") or {}).keys())
    new_ds = set()
    for k, v in merged.items():
        if k.startswith("_") or not isinstance(v, dict):
            continue
        new_ds.update((v.get("dsUsage") or {}).keys())
    ds_added, ds_lost = sorted(new_ds - old_ds), sorted(old_ds - new_ds)

    # _meta：pages 更新；dsFormulas 取并集（新解析覆盖旧 error 条目，好条目不被 error 覆盖）
    meta["pages"] = new_meta_pages
    if touched_ds:
        merged_formulas = parse_page.fetch_ds_formulas(sorted(touched_ds), args.workers)
        old_formulas = meta.get("dsFormulas") or {}
        for ds_id, info in merged_formulas.items():
            if ds_id not in old_formulas or "error" not in info:
                old_formulas[ds_id] = info
        meta["dsFormulas"] = old_formulas
    meta["incrLog"] = (meta.get("incrLog") or []) + [{
        "at": now_str(),
        "addedPages": [p["pgId"] for p in added_pages],
        "changedPages": [p["pgId"] for p in changed_pages],
        "removedPages": [p["pgId"] for p in removed_pages],
        "renamedPages": renamed_pages,
        "removedCards": removed_cards,
    }]
    meta["lastIncrAt"] = now_str()
    merged["_meta"] = meta

    # 受影响示例：route 指向被删/改名卡片或已移除看板的 examples.json 条目
    removed_pgids = {p["pgId"] for p in removed_pages}
    renamed_old = {(r["page"], r["old"]) for r in renamed_cards}
    affected_examples = []
    ex_path = os.path.join(args.package, "references", "examples.json")
    if os.path.exists(ex_path):
        with open(ex_path, encoding="utf-8") as f:
            ex_doc = json.load(f)
        prune_set = set(prune_keys)
        for sname, exs in (ex_doc.get("scenarios") or {}).items():
            for ex in exs or []:
                route = ex.get("route") or {}
                reason = None
                if route.get("pageId") in removed_pgids:
                    reason = "看板已移除"
                elif any((route.get("pageName"), cn) in renamed_old for cn in route.get("cards") or []):
                    reason = "卡片已删除/改名"
                else:
                    fetch_file = (ex.get("fetch") or {}).get("file") or ""
                    key = os.path.basename(fetch_file).rsplit(".", 1)[0]
                    if key in prune_set:
                        reason = "采样文件已删除"
                if reason:
                    affected_examples.append({"scenario": sname, "id": ex.get("id"),
                                              "question": ex.get("question"), "reason": reason})

    # 受影响指标：formulas.json sources 引用被删/改名卡片的指标（工作目录优先，回退交付包）
    affected_metrics = []
    f_path = os.path.join(args.workdir, "formulas.json")
    if not os.path.exists(f_path):
        f_path = os.path.join(args.package, "references", "formulas.json")
    if os.path.exists(f_path):
        with open(f_path, encoding="utf-8") as f:
            f_doc = json.load(f)
        patterns = {(c["page"], c["name"]) for c in removed_cards}
        patterns |= {(r["page"], r["old"]) for r in renamed_cards}
        for m in f_doc.get("metrics") or []:
            srcs = m.get("sources") or []
            if any((s.get("page"), s.get("card")) in patterns for s in srcs):
                affected_metrics.append(m.get("name"))
        affected_metrics = sorted(set(affected_metrics))

    # 落盘
    out_cards = os.path.join(args.workdir, "cards-merged.json")
    with open(out_cards, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=1)
    report = {
        "at": now_str(),
        "package": os.path.abspath(args.package),
        "backup": bak,
        "addedPages": added_pages,
        "changedPages": changed_pages,
        "unchangedPages": unchanged_pages,
        "removedPages": removed_pages,
        "renamedPages": renamed_pages,
        "datasets": {"added": ds_added, "lost": ds_lost},
        "resampleCdIds": sorted(resample),
        "pruneSampleKeys": sorted(set(prune_keys)),
        "affectedExamples": affected_examples,
        "affectedMetrics": affected_metrics,
    }
    out_report = os.path.join(args.workdir, "incr-report.json")
    with open(out_report, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)

    print(f"\n已写入 {out_cards}")
    print(f"已写入 {out_report}")
    print(f"交付包原 cards.json 备份: {bak}")
    if ds_lost:
        print(f"⚠️ 数据集消失（SQL 直查能力可能变化，验收时探活）: {', '.join(ds_lost)}")
    if affected_examples:
        print(f"⚠️ {len(affected_examples)} 个已验收示例受影响，需用户确认（见报告 affectedExamples）")
    if affected_metrics:
        print(f"⚠️ {len(affected_metrics)} 个指标口径来源受影响: {', '.join(affected_metrics[:10])}")


if __name__ == '__main__':
    main()
