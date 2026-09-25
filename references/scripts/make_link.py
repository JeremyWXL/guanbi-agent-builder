#!/usr/bin/env python3
"""
筛选直达链接生成器：把筛选条件拼进 BI 看板 URL——用户点开就是筛好条件的视图
用法: python3 make_link.py <工作目录> <看板名> --filter "字段=值" [--filter ...] [--anchor 卡片名]
  python3 make_link.py <工作目录> --list <看板名>     # 列出该看板可用的筛选器（字段名 → 可带值）
原理: 观远 BI 页面 URL 原生支持查询参数筛选（官方文档"页面URL添加条件参数"，已实机验证）：
  {biBaseUrl}/page/{pgId}?<筛选器ID>=<值>      多值重复传参: ?id=值1&id=值2
  树状筛选器带路径: id=["浙江","杭州"]；&anchor=<cdId> 定位到具体卡片
  筛选器 ID = 筛选栏里筛选器卡片的 cdId（= 编辑 UI"复制筛选器ID"的"线上 ID"），
  学习时已由 parse_page.py 收割进 cards-raw.json（inFilterBar / linkedCardCount /
  defaultValueType 等筛选交互字段），cards.json 需保留
候选规则（实机验证结论）:
  - 只认筛选栏成员（inFilterBar）：页面可能存在不在筛选栏的同名筛选器，其 cdId 拼进 URL 无效
  - 只认有联动的（linkedCardCount > 0）：无联动筛选器只改 UI 不改数据
  - 筛选栏含 FIRST_PICK 默认值筛选器的页面：首屏取数可能不携带 URL 筛选（前端在
    first-pick 异步解析前发出空 filters 请求且不重查），生成链接时告警
铁律: 筛选值必须来自实际数据（列画像枚举值/取数结果），禁止编造；字段没有对应页面筛选器时
  明确报错并列出可用筛选器，禁止静默忽略（静默忽略 = 用户点开看到未筛选的全量，比不给链接更糟）
"""
import json, os, sys
from urllib.parse import quote


def load_pages(workdir):
    """读 cards-raw.json（搭建期）或 cards.json（交付包），统一为 {看板名: {pgId, cards: [...]}}"""
    for fn in ("cards-raw.json", "cards.json"):
        fp = os.path.join(workdir, fn)
        if not os.path.exists(fp):
            continue
        with open(fp, encoding="utf-8") as f:
            doc = json.load(f)
        pages = {k: v for k, v in doc.items()
                 if not k.startswith("_") and k != "meta" and isinstance(v, dict) and "pgId" in v}
        out = {}
        for name, info in pages.items():
            cards = info.get("cards") or []
            if isinstance(cards, dict):  # cards.json 字典形态 → 列表
                cards = [dict(v, name=k) if isinstance(v, dict) else {"name": str(v)}
                         for k, v in cards.items()]
            out[name] = {"pgId": info.get("pgId") or info.get("pageId", ""), "cards": cards}
        if out:
            return out, (doc.get("_meta") or doc.get("meta") or {})
    sys.exit(f"{workdir} 下找不到 cards-raw.json / cards.json")


def selectors_of(page):
    """看板的筛选器清单：[(name, cdId, field, usable, note)]。usable=False 的只用于展示，不作候选"""
    sels = []
    for c in page["cards"]:
        if not isinstance(c, dict):
            continue
        if c.get("type") == "SELECTOR" or c.get("cdType") == "SELECTOR":
            fields = c.get("filters") or []
            field = fields[0] if fields else ""
            if not field:  # 兼容 filterDetails 形态
                fd = (c.get("filterDetails") or [{}])[0]
                field = fd.get("field", "")
            in_bar = c.get("inFilterBar")       # 旧版收割没有这些字段 → None，按可用处理
            linked = c.get("linkedCardCount")
            if in_bar is False:
                sels.append((c.get("name", "").strip(), c.get("cdId", ""), field, False, "不在筛选栏"))
            elif linked == 0:
                sels.append((c.get("name", "").strip(), c.get("cdId", ""), field, False, "无联动卡片，只改 UI 不改数据"))
            else:
                sels.append((c.get("name", "").strip(), c.get("cdId", ""), field, True, ""))
    return [s for s in sels if s[1]]


def first_pick_warning(page, sels):
    """筛选栏含 FIRST_PICK 默认值筛选器 → URL 筛选可能只进 UI 不进数据层（实机验证结论）"""
    bar_ids = {s[1] for s in sels}
    fp = [c.get("name", "") for c in page["cards"]
          if isinstance(c, dict) and c.get("cdId") in bar_ids
          and c.get("defaultValueType") == "FIRST_PICK"]
    if fp:
        return (f"⚠️ 该看板筛选栏含「首选项」默认值筛选器（{'、'.join(fp)}），"
                f"此类页面首屏取数可能不携带 URL 筛选（数据仍是全量）。"
                f"请实机打开链接确认数据已过滤；若未过滤，此看板暂不适合直达链接")
    return ""


def main():
    args = sys.argv[1:]
    if len(args) < 2:
        sys.exit(__doc__)
    workdir = args[0]
    filters, anchor = [], None
    rest = []
    i = 1
    while i < len(args):
        if args[i] == "--filter":
            filters.append(args[i + 1]); i += 2
        elif args[i] == "--anchor":
            anchor = args[i + 1]; i += 2
        elif args[i] == "--list":
            rest.append(("list", args[i + 1])); i += 2
        else:
            rest.append(("page", args[i])); i += 1
    pages, meta = load_pages(workdir)

    if rest and rest[0][0] == "list":
        name = rest[0][1]
        page = pages.get(name) or next((v for k, v in pages.items() if name in k), None)
        if not page:
            sys.exit(f"找不到看板「{name}」，已有看板：{'、'.join(pages)}")
        sels = selectors_of(page)
        print(f"《{name}》可用筛选器：")
        for nm, cdid, field, usable, note in sels:
            if usable:
                print(f"  {field or nm}（筛选器「{nm}」）")
        unusable = [s for s in sels if not s[3]]
        for nm, cdid, field, usable, note in unusable:
            print(f"  ✗ {field or nm}（筛选器「{nm}」——{note}，不可用于直达链接）")
        warn = first_pick_warning(page, sels)
        if warn:
            print(warn, file=sys.stderr)
        return

    page_name = rest[0][1] if rest else ""
    page = pages.get(page_name) or next((v for k, v in pages.items() if page_name and page_name in k), None)
    if not page:
        sys.exit(f"找不到看板「{page_name}」，已有看板：{'、'.join(pages)}")
    if not page["pgId"]:
        sys.exit(f"《{page_name}》没有记录 pageId，无法生成链接")

    sels = selectors_of(page)
    usable = [s for s in sels if s[3]]
    params = []
    for f in filters:
        if "=" not in f:
            sys.exit(f"筛选格式应为「字段=值」: {f}")
        field, value = f.split("=", 1)
        field, value = field.strip(), value.strip()
        hit = next((s for s in usable if s[2] == field or s[0] == field), None)
        if not hit:
            avail = "、".join(s[2] or s[0] for s in usable) or "（无）"
            sys.exit(f"❌ 字段「{field}」在《{page_name}》没有对应的页面筛选器，带不进去。"
                     f"可用筛选器：{avail}——请改用这些字段，或不给链接（禁止静默忽略）")
        for v in value.split(","):  # 多值：重复传参
            params.append(f"{quote(hit[1])}={quote(v.strip())}")
    if anchor:
        card = next((c for c in page["cards"]
                     if isinstance(c, dict) and (c.get("name") or "") == anchor), None)
        if not card or not card.get("cdId"):
            sys.exit(f"找不到卡片「{anchor}」的 cdId")
        params.append(f"anchor={quote(card['cdId'])}")

    base = (meta.get("biBaseUrl") or "").rstrip("/")
    if not base:
        import re, subprocess
        r = subprocess.run(["guancli", "auth", "status"], capture_output=True, text=True, timeout=30)
        m = re.search(r'^URL:\s*(\S+)', r.stdout, re.M)
        base = m.group(1).rstrip("/") if m else ""
        if not base:
            sys.exit("拿不到 BI 地址（cards.json._meta.biBaseUrl 缺失且 guancli 不可用）")
    warn = first_pick_warning(page, selectors_of(page))
    if warn:
        print(warn, file=sys.stderr)
    print(f"{base}/page/{page['pgId']}?{'&'.join(params)}")


if __name__ == "__main__":
    main()
