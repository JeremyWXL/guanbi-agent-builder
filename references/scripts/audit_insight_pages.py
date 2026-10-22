#!/usr/bin/env python3
"""
洞察Agent 看板就绪诊断器：把 parse_page.py / check_pages.py / check_formulas.py / sample_cards.py
的产物，按 references/insight-agent-readiness.md 的规则做机械体检，输出可复算的结构诊断
用法:
  python3 audit_insight_pages.py <工作目录> [--scenario TEXT] [--max-pages N] [--out PATH] [--seed-advice]
输入（只读，不调用 guancli）:
  <工作目录>/cards-raw.json              必需（parse_page.py 产出）；缺失/损坏 → exit 2
  <工作目录>/page-check.json             可选（适检结论 / agent-ready / dataUtime 停更信号）
  <工作目录>/formulas.json               可选（同名指标冲突 / PARAM_DEPENDENT 公式）
  <工作目录>/card-data/_sample_index.json 可选（明细表原始行数；缺失则行数“未实测”）
输出:
  <工作目录>/insight-audit.json           体检结果（页级六维 + 组合级 + 逐条有证据的发现）
  <工作目录>/insight-advice.seed.json     --seed-advice 时写建议底稿（字段对齐 references/templates/insight-advice.json）

规则口径（references/insight-agent-readiness.md）:
  R-01 数据范围 >max-pages（默认 10）→ blocker；R-02 筛选栏内无联动筛选器 → blocker，
        linkedCardCount>0 但不在筛选栏只告警（P2，不算通过）；
  R-05 同名指标公式冲突 → P0；R-06 单页数据卡 >20 → P0、13–20 / <5 → P1、
        明细表（type=TABLE）原始行数 >10000 → P0、未采样 → P2“未实测”；
  R-08 参数化指标（PARAM_DEPENDENT）无参数筛选器 → P0；
  R-09 无时间筛选器/时间参数 → P0；R-10 卡名空/纯编号/重名/副本测试/时间锁死 → P1/P2；
  R-11 关键维度有维度无筛选器 → P1，完全无公共业务维度筛选器 → P0；
  R-12 下钻卡/层级维度无筛选承接、跨页缺明细层/总览层、所有页层级混在一起 → P1；
  R-13 跨页无共享联动维度 → P0，只有时间维度 → P1；
  R-07 跨页同数据集+同指标+同维度的重复卡片 → 合并建议（占比 >30% P0，10–30% P1）；
  R-16 数据停更 >90 天 → P1。
环境前提（R-03）CLI 无法验证：不作为 finding，meta.environmentCheck 固定 "unverified"。

评分（insight-agent-readiness.md §4）:
  页级六维 focus 15 / metrics 20 / linkage 25 / layers 20 / context 10 / ops 10；
  组合级 25 / 20 / 20 / 15 / 10 / 10；总分 = 页级均分 × 0.6 + 组合级 × 0.4。
  ⛔ 不可用页（0 数据卡 / page-check 判 ⛔）不进入页级均分，页对象带 unavailable=true。
  阻断收敛：任一页 blocker 级 R-02、或任一 P0 → 总分封顶 64（需改造）；页数 >max-pages 或可用页为 0 → 封顶 49。

meta 额外字段供报告使用：officialMaxPages（官方上限 10）、environmentCheck、skippedRules
（缺/损坏的输入导致未判定的规则）。判定确定性：除 meta.builtAt 与按当天计算的停更天数外，
同一输入重复运行输出一致。
"""
import json
import os
import re
import sys
from datetime import date, datetime

BUILDER_VERSION = "4.10.0"  # 发布时与 SKILL.md frontmatter version 同步
DEFAULT_MAX_PAGES = 10
STALE_DAYS = 90

SELECTOR_TYPES = ("SELECTOR", "TREE_SELECTOR")
NON_DATA_TYPES = ("SELECTOR", "TREE_SELECTOR", "TEXT", "PICTURE", "PROGRESS_BAR", "LAYOUT")
TABLE_TYPES = ("TABLE",)
LAYER_TABLE_TYPES = ("TABLE", "PIVOT_TABLE")

TIME_HINT = re.compile(r'时间|日期|年月|月份|账期|月度|周$|周次|月$|月[份度]')
RISKY_NAME = re.compile(r'副本|测试|临时|未命名|备份|勿动|废弃|demo|test', re.I)
NUMBERED_NAME = re.compile(r'^(?:图|图表|卡片|表|图\s*\d+|chart|card|sheet|page)?\s*[-_#]?\s*\d+$', re.I)
# 与 check_pages.TIME_LOCK 同口径：卡名写死具体年月（排除“月度/月趋势/月均”等通用词）
TIME_LOCK = re.compile(r'(20\d{2}\s*年\s*\d{1,2}\s*月|20\d{2}[-/]\d{1,2}|\d{1,2}\s*月(?!\s*[度趋均累份]))')
OBJECT_HINT = re.compile(r'门店|店铺|店编码|店名|商品|产品|SKU|sku|订单|客户|经销|加盟')
DYNAMIC_PARAM = re.compile(r'DYNAMIC_PARAMS\s*\.\s*([^\[\]]+)')
AVG_CALL = re.compile(r'\bavg\s*\(', re.I)
RATIO_NAME = re.compile(r'率|占比|比$|均价')

# 关键维度分组：按顺序首次命中即归属（“产品一级分类名称”归“品类”而不是“产品”）
KEY_DIM_GROUPS = [
    ("区域", re.compile(r'区域|大区|片区|地区')),
    ("省份", re.compile(r'省份|省区|省$|^省')),
    ("城市", re.compile(r'城市|市$')),
    ("县区", re.compile(r'县区|区县|县$')),
    ("门店", re.compile(r'门店|店铺|店编码|店名|店$')),
    ("品类", re.compile(r'品类|分类|类别')),
    ("渠道", re.compile(r'渠道')),
    ("产品", re.compile(r'产品|商品|SKU|sku|品名|款号')),
    ("客户", re.compile(r'客户')),
    ("加盟商", re.compile(r'加盟商|经销商|加盟')),
]
HIERARCHY_GROUPS = ("区域", "省份", "城市", "县区", "门店")
LAYER_KEYS = ("overview", "mid", "detail")

STAGE_PATTERNS = [
    ("开发", re.compile(r'开发|企划|设计')),
    ("采购", re.compile(r'采购|进货|供应链')),
    ("销售", re.compile(r'销售|营收|营业额|出货')),
    ("库存", re.compile(r'库存|存货|周转')),
    ("履约", re.compile(r'履约|发货|配送|物流')),
    ("售后", re.compile(r'售后|退款|退货|客诉')),
]

RULES = {
    "R-01": {"requirement": "一个洞察Agent 的数据范围最多选择 10 张仪表板",
             "source": "官方文档·新建智能体"},
    "R-02": {"requirement": "每张仪表板必须配置筛选栏内的联动筛选器，供跨页动态传参",
             "source": "官方文档·新建智能体"},
    "R-05": {"requirement": "同名指标口径必须由看板固化且一致，Agent 不自创口径",
             "source": "官方文档·业务知识 / 项目方法论·指标口径"},
    "R-06": {"requirement": "单页卡片数与明细行数必须控制在 Agent 可稳定读取的范围",
             "source": "官方文档·分析思路 / 项目方法论·看板设计检查表"},
    "R-07": {"requirement": "一张看板只解决一个清晰问题，跨页重复卡片应合并",
             "source": "项目方法论·看板设计检查表"},
    "R-08": {"requirement": "指标应在 BI/数据集层算好；参数化指标必须有可用的参数入口",
             "source": "项目方法论·看板设计检查表"},
    "R-09": {"requirement": "每张看板必须有明确时间范围或时间参数",
             "source": "项目方法论·看板设计检查表"},
    "R-10": {"requirement": "卡片标题必须能被 Agent 独立理解，不依赖人工补充",
             "source": "项目方法论·看板设计检查表"},
    "R-11": {"requirement": "下钻/关键维度字段必须有筛选器承接，且存在公共业务维度筛选器",
             "source": "项目方法论·Agent 看板设计检查表"},
    "R-12": {"requirement": "看板应形成总览→定位→明细的分层结构，每层有筛选器承接",
             "source": "项目方法论·Agent 看板设计检查表"},
    "R-13": {"requirement": "跨页联动必须至少共享一个非时间维度",
             "source": "官方文档·新建智能体 / 项目方法论·落地实施 SOP"},
    "R-16": {"requirement": "看板数据必须持续更新，停更页不能作为 Agent 的知识源",
             "source": "项目方法论·落地实施 SOP"},
}


# ───────────────────────────── 基础工具 ─────────────────────────────

def json_load(path):
    """返回 (data, err)；err 区分 missing（不存在）与 invalid（损坏/非 JSON）"""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f), None
    except FileNotFoundError:
        return None, "missing"
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        return None, "invalid"


def preview(items, n=3):
    items = [str(i) for i in items if str(i)]
    if not items:
        return ""
    return "、".join(items[:n]) + ("…" if len(items) > n else "")


def selector_field(card):
    """筛选器对应字段名：filterDetails[0].field（parse_page 已把 fdId 翻译成名称）"""
    for detail in card.get("filterDetails") or []:
        field = (detail or {}).get("field")
        if field:
            return str(field)
    return ""


def selector_label(card):
    return selector_field(card) or (card.get("name") or "").strip()


def is_time_selector(card):
    stype = (card.get("selectorType") or "").upper()
    if stype in ("TIME_MACRO", "CALENDAR", "DATE"):
        return True
    return bool(TIME_HINT.search(selector_field(card) or "") or
                TIME_HINT.search(card.get("name") or ""))


def dim_group(field):
    """关键维度分组；时间维度/非关键维度返回 None"""
    field = field or ""
    for label, pat in KEY_DIM_GROUPS:
        if pat.search(field):
            return label
    return None


def measure_names(card):
    out = set()
    for m in card.get("measures") or []:
        name = (m.get("name") or m.get("alias") or "").strip()
        if name:
            out.add(name)
    return out


def card_dims(card):
    return {d for d in card.get("dims") or [] if d}


def page_cards(page):
    cards = page.get("cards")
    if not isinstance(cards, list):
        return []
    return [c for c in cards if isinstance(c, dict)]


def data_cards_of(cards):
    return [c for c in cards if c.get("type") not in NON_DATA_TYPES]


def iter_pages(cards_raw):
    for name, page in cards_raw.items():
        if name.startswith("_") or not isinstance(page, dict) or "cards" not in page:
            continue
        yield name, page


def parse_date(text):
    m = re.match(r'(\d{4})[-/](\d{1,2})[-/](\d{1,2})', (text or "").strip())
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def grade_for(score):
    if score >= 80:
        return "可直接配置"
    if score >= 65:
        return "小改后配置"
    if score >= 50:
        return "需改造"
    return "不建议直接配置"


def make_finding(rule, level, scope, evidence, action, pages):
    meta = RULES[rule]
    return {"id": None, "rule": rule, "level": level, "scope": scope,
            "evidence": evidence, "requirement": meta["requirement"],
            "source": meta["source"], "action": action, "_pages": list(pages)}


# ───────────────────────────── 输入派生 ─────────────────────────────

def conflict_records(formulas):
    """formulas.json 的 conflicts → [{metric, pages, cards, detail}]（跨卡/跨页都保留）"""
    records = []
    for conflict in (formulas or {}).get("conflicts") or []:
        if not isinstance(conflict, dict):
            continue
        pages, cards = [], []
        for variant in conflict.get("variants") or []:
            for source in (variant or {}).get("sources") or []:
                m = re.match(r'《(.+?)》\s*(.*)$', str(source))
                if not m:
                    continue
                page_name, card_name = m.group(1), m.group(2)
                if page_name not in pages:
                    pages.append(page_name)
                if page_name:
                    cards.append((page_name, card_name))
        variants = []
        for variant in (conflict.get("variants") or [])[:4]:
            formula = re.sub(r'\s+', ' ', str((variant or {}).get("formula") or "")).strip()
            sources = "、".join((variant or {}).get("sources") or [])
            variants.append(f"{formula}（{sources}）")
        detail = "；".join(variants)
        records.append({"metric": conflict.get("name") or "?",
                        "pages": pages, "cards": cards, "detail": detail})
    return records


def param_dependency_records(formulas):
    """PARAM_DEPENDENT 指标 → [{metric, params, pages, cards, formula}]"""
    records = []
    for metric in (formulas or {}).get("metrics") or []:
        if not isinstance(metric, dict) or metric.get("classification") != "PARAM_DEPENDENT":
            continue
        formula = metric.get("formula") or ""
        params = sorted({p.strip() for p in DYNAMIC_PARAM.findall(formula) if p.strip()})
        pages, cards = [], []
        for source in metric.get("sources") or []:
            page_name = (source or {}).get("page") or ""
            if not page_name:
                continue
            if page_name not in pages:
                pages.append(page_name)
            cards.append((page_name, (source or {}).get("card") or ""))
        records.append({"metric": metric.get("name") or "?",
                        "params": params, "pages": pages, "cards": cards,
                        "formula": formula})
    return records


def sample_maps(samples):
    """_sample_index.json → (cdId → rows, 是否可用)"""
    rows_by_cd = {}
    if not isinstance(samples, dict):
        return rows_by_cd, False
    for key, entry in samples.items():
        if not isinstance(entry, dict):
            continue
        cd_id = entry.get("cdId") or key.split("__")[-1].replace(".json", "")
        if "error" in entry or not cd_id:
            continue
        rows = entry.get("rows")
        if isinstance(rows, int):
            rows_by_cd[cd_id] = rows
    return rows_by_cd, bool(samples)


def param_served(param, has_param_selector, has_time):
    if TIME_HINT.search(param or ""):
        return has_time
    return has_param_selector


# ───────────────────────────── 页级体检 ─────────────────────────────

def infer_layer_profile(data_cards):
    """返回 (层级集合, 各层卡片计数, 主层级)。

    一张大页可能同时含总览/定位/明细卡；组合级“层级完整”必须看**不同页面**的主层级，
    否则一张 40 卡的大页会把三层都占满，掩盖“该拆页”的问题。
    """
    counts = {"overview": 0, "mid": 0, "detail": 0}
    for card in data_cards:
        dims = [d for d in card.get("dims") or [] if d]
        ctype = card.get("type") or ""
        hit = set()
        if ctype in ("KPI_CARD", "SINGLE_VALUE") or not dims:
            hit.add("overview")
        if ctype in LAYER_TABLE_TYPES and (len(dims) >= 2 or any(OBJECT_HINT.search(d) for d in dims)):
            hit.add("detail")
        elif any(OBJECT_HINT.search(d) for d in dims):
            hit.add("detail")
        if any(dim_group(d) for d in dims):
            hit.add("mid")
        for layer in hit:
            counts[layer] += 1
    if not any(counts.values()):
        return set(), counts, "mid"
    # 平票时优先 detail → mid → overview：大页里明细最稀缺，也最能说明页面重心
    priority = {"detail": 3, "mid": 2, "overview": 1}
    dominant = max(counts, key=lambda k: (counts[k], priority[k]))
    layers = {k for k, v in counts.items() if v}
    return layers, counts, dominant


def audit_page(name, page, check_page, conflicts, deps, rows_by_cd, samples_available):
    cards = page_cards(page)
    data_cards = data_cards_of(cards)
    selectors = [c for c in cards if c.get("type") in SELECTOR_TYPES]
    tables = [c for c in data_cards if c.get("type") in TABLE_TYPES]
    linkage = [s for s in selectors
               if s.get("inFilterBar") and (s.get("linkedCardCount") or 0) > 0]
    hidden = [s for s in selectors
              if not s.get("inFilterBar") and (s.get("linkedCardCount") or 0) > 0]
    param_selectors = [s for s in selectors if (s.get("selectorType") or "").upper() == "PARAMETER"]
    time_selectors = [s for s in selectors if is_time_selector(s)]
    text_cards = [c for c in cards if c.get("type") == "TEXT"]
    time_params = [(c.get("name") or c.get("cdId") or "", p.get("name") or "")
                   for c in data_cards for p in (c.get("dynamicParams") or [])
                   if TIME_HINT.search(p.get("name") or "")]

    has_time = bool(time_selectors or time_params)
    business_selectors = [s for s in selectors if dim_group(selector_label(s))]
    business_linkage = [s for s in linkage if dim_group(selector_label(s))]
    param_labels = [selector_label(s) or (s.get("cdId") or "") for s in param_selectors]

    selector_groups = {dim_group(selector_label(s)) for s in selectors} - {None}
    selector_groups |= {dim_group(s.get("name") or "") for s in selectors} - {None}
    present_groups, dim_evidence = {}, {}
    for card in data_cards:
        for dim in card.get("dims") or []:
            group = dim_group(dim)
            if not group:
                continue
            present_groups[group] = present_groups.get(group, 0) + 1
            dim_evidence.setdefault(group, []).append(
                f"「{card.get('name')}」.{dim}({card.get('cdId')})")
    page_layers, layer_counts, dominant_layer = infer_layer_profile(data_cards)
    hier_groups = [g for g in HIERARCHY_GROUPS if g in present_groups]
    drill_cards = [c for c in data_cards if c.get("type") == "DRILL"]

    findings = []

    def add(rule, level, evidence, action, scope=None):
        findings.append(make_finding(rule, level, scope or f"page:{name}",
                                     evidence, action, [name]))

    # ⛔ 不可用页：0 数据卡，或 page-check 判 ⛔（取不到/大屏/导航页/数据集全部不可读且探针失败）
    reasons = " ".join(str(r) for r in (check_page or {}).get("reasons") or [])
    unavailable = (not data_cards) or ((check_page or {}).get("verdict") == "⛔")
    facts = {
        "dataCards": len(data_cards),
        "selectors": len(selectors),
        "linkageSelectors": len(linkage),
        "linkageSelectorIds": [s.get("cdId") or "" for s in linkage if s.get("cdId")],
        "linkageSelectorDetails": [
            {"cdId": s.get("cdId") or "", "name": s.get("name") or "",
             "field": selector_field(s), "linkedCardCount": s.get("linkedCardCount") or 0}
            for s in linkage
        ],
        "tableCards": len(tables),
        "maxRawRows": None,
        "mtime": page.get("mtime") or "",
        "layerCounts": layer_counts,
        "dominantLayer": dominant_layer,
    }
    for table in tables:
        rows = rows_by_cd.get(table.get("cdId") or "")
        if isinstance(rows, int) and (facts["maxRawRows"] is None or rows > facts["maxRawRows"]):
            facts["maxRawRows"] = rows

    if unavailable:
        if data_cards:
            evidence = (f"page-check 判定页面「{name}」不可用（{reasons or '无原因明细'}），"
                        f"虽有 {len(data_cards)} 张数据卡，也不进入页级均分")
        else:
            reason = f"：{reasons}" if reasons else ""
            evidence = f"页面「{name}」没有可读的数据卡（{len(cards)} 张卡片中数据卡 0 张）{reason}"
        add("R-06", "blocker", evidence,
            "从数据范围移出该页，换用取数正常的普通仪表板",
            scope=f"page:{name}")
        return {"name": name, "pgId": page.get("pgId") or "",
                "available": False, "facts": facts,
                "scores": {k: 0 for k in ("focus", "metrics", "linkage", "layers", "context", "ops")},
                "total": 0, "grade": grade_for(0), "verdict": "blocker",
                "data_cards": data_cards, "selectors": selectors, "linkage": linkage,
                "selector_groups": selector_groups, "present_groups": present_groups,
                "page_layers": page_layers, "hier_groups": hier_groups,
                "time_locked": False, "stale": False, "hidden_only": False,
                "findings": findings}

    # ── R-02 联动筛选器（硬要求）──
    if not linkage:
        if hidden:
            hidden_desc = preview([f"{selector_label(s)}({s.get('cdId')})" for s in hidden])
            add("R-02", "P2",
                f"筛选栏内无联动筛选器；{len(hidden)} 个筛选器 linkedCardCount>0 但 inFilterBar=false"
                f"（{hidden_desc}）——只能算候选，"
                f"需在 BI 里确认洞察Agent 能否选中",
                "把这些筛选器移入筛选栏，或在 BI 中确认可被洞察Agent 选中后重新体检")
        else:
            add("R-02", "blocker",
                f"筛选栏内无联动筛选器（共 {len(selectors)} 个筛选器，0 个同时满足 inFilterBar=true 且 "
                f"linkedCardCount>0）" if selectors else "页面没有任何筛选器",
                "在页面筛选栏配置至少一个联动筛选器（区域/门店/品类），优先选跨页共用的业务维度字段")
    elif not business_linkage and not time_selectors:
        add("R-02", "P1",
            f"页面有 {len(linkage)} 个联动筛选器，但没有业务维度/时间类联动筛选器"
            f"（{preview([selector_label(s) for s in linkage])}）——跨页只能传参数，不能定位对象",
            "补一个区域/门店/品类等业务维度联动筛选器；参数筛选器解决不了跨页对象定位")

    # ── R-09 时间范围 ──
    if not has_time:
        add("R-09", "P0",
            f"页面 {len(selectors)} 个筛选器均非时间类，{len(data_cards)} 张数据卡未声明时间类参数"
            f"（筛选器：{preview([selector_label(s) for s in selectors]) or '无'}）",
            "补时间筛选器或时间宏参数，并把默认范围收窄到 Agent 可稳定读取的期间")

    # ── R-06 上下文可控：卡片数 / 明细行数 / 采样 ──
    n = len(data_cards)
    if n > 20:
        add("R-06", "P0",
            f"页面共 {n} 张数据卡，超过 20 张的 Agent 稳定读取上限"
            f"（KPI/图表/明细混合：{preview([c.get('name') for c in data_cards], 5)}）",
            "拆分为总览/定位/明细页，或用筛选器收敛默认范围，单页保留最贴近问题链路的卡片")
    elif 13 <= n <= 20:
        add("R-06", "P1", f"页面共 {n} 张数据卡（13–20 张），接近上下文上限",
            "按主题拆分或移出与目标问题无关的卡片")
    elif n < 5:
        add("R-06", "P1", f"页面仅 {n} 张数据卡（<5），覆盖的问题面偏窄",
            "补充关键指标/维度卡片，或与同主题看板合并")

    for table in tables:
        rows = rows_by_cd.get(table.get("cdId") or "")
        if isinstance(rows, int) and rows > 10000:
            add("R-06", "P0",
                f"明细表「{table.get('name')}」（{table.get('cdId')}）原始 {rows} 行，超过 1 万行上限",
                "把明细聚合到日/商品/门店粒度，或增加中间层并限制默认时间范围")

    missing_samples = [t for t in tables if rows_by_cd.get(t.get("cdId") or "") is None]
    if not samples_available:
        add("R-06", "P2",
            f"无 card-data/_sample_index.json，{n} 张数据卡的行数未实测"
            + (f"（含 {len(tables)} 张明细表）" if tables else ""),
            "运行 sample_cards.py 采样后再复检，上下文风险不能默认通过")
    elif missing_samples:
        missing_desc = preview([f"{t.get('name')}({t.get('cdId')})" for t in missing_samples])
        add("R-06", "P2",
            f"样例索引存在但缺 {len(missing_samples)} 张明细表的行数（"
            f"{missing_desc}），未实测",
            "重新采样这几张明细表；未实测前不把行数当通过")

    # ── R-05 口径冲突（页面级扣分；finding 由跨页分析统一生成）──
    page_conflicts = [c for c in conflicts if name in c["pages"]]

    # ── R-08 参数化指标承接 ──
    param_hits = []
    for dep in deps:
        if name not in dep["pages"]:
            continue
        missing = [p for p in dep["params"] if not param_served(p, bool(param_selectors), has_time)]
        if missing:
            card_name = next((c for pg, c in dep["cards"] if pg == name), "")
            param_hits.append(dep)
            add("R-08", "P0",
                f"参数化指标「{dep['metric']}」（卡片「{card_name}」）依赖全局参数 "
                f"{preview(missing)}，页面没有可设置该参数的筛选器"
                f"（{len(param_selectors)} 个参数筛选器、{len(time_selectors)} 个时间筛选器）",
                "在页面加参数筛选器/时间筛选器承接该参数，或把参数固化成一版固定口径的指标卡")
    if param_hits and param_selectors and not [s for s in param_selectors if s.get("inFilterBar")]:
        add("R-08", "P2",
            f"{len(param_selectors)} 个参数筛选器（{preview(param_labels)}）均不在筛选栏"
            f"（inFilterBar=false）——需在 BI 确认洞察Agent 能否设置参数",
            "把参数筛选器移入筛选栏，或改为时间/维度筛选器承接")

    # ── 比率公式风险（R-08 的机械信号）──
    ratio_risks = []
    for card in data_cards:
        for m in card.get("measures") or []:
            formula = m.get("formula") or ""
            label = m.get("alias") or m.get("name") or ""
            if "/" in formula and AVG_CALL.search(formula):
                ratio_risks.append((card.get("name"), label,
                                    re.sub(r'\s+', ' ', formula).strip()))
            elif (m.get("aggrType") or "").upper() == "AVG" and RATIO_NAME.search(label):
                ratio_risks.append((card.get("name"), label,
                                    f"物理字段 {m.get('name') or label} 按 AVG 聚合"))
    if ratio_risks:
        card_name, label, formula = ratio_risks[0]
        add("R-08", "P1",
            f"比率指标「{label}」在卡片「{card_name}」用 AVG(明细比率)/均值聚合（{formula}）",
            "改为分子分母分别求和再相除，指标在数据集/看板层算好再给 Agent")

    # ── R-11 关键维度承接 ──
    missing_groups = [g for g in sorted(present_groups) if g not in selector_groups]
    for group in missing_groups:
        add("R-11", "P1",
            f"卡片维度含「{group}」但页面无对应筛选器（证据：{preview(dim_evidence.get(group), 3)}）",
            f"补「{group}」筛选器，字段名与卡片维度字段保持一致")
    if not business_selectors:
        add("R-11", "P0",
            f"页面没有公共业务维度筛选器（{len(selectors)} 个筛选器："
            f"{preview([selector_label(s) for s in selectors]) or '无'}），"
            f"下钻只能从全量数据里猜筛选条件",
            "至少配置一个业务维度联动筛选器（区域/门店/品类/渠道）")

    # ── R-12 下钻承接与分层 ──
    if (drill_cards or len(hier_groups) >= 2) and not (set(hier_groups) & selector_groups):
        evidence = (f"下钻卡 {preview([c.get('name') for c in drill_cards])}；" if drill_cards else "")
        evidence += (f"层级维度 {preview(hier_groups)} 存在，但页面无对应层级筛选器"
                     f"（筛选器字段：{preview([selector_label(s) for s in selectors]) or '无'}）")
        add("R-12", "P1", evidence, "为每一层下钻字段补筛选器，层间用同一字段名传参")

    # ── R-10 卡名可理解 ──
    names = [(c.get("name") or "").strip() for c in data_cards]
    empty_names = [c for c in data_cards
                   if not (c.get("name") or "").strip()
                   or (c.get("name") or "").strip() == (c.get("cdId") or "")
                   or NUMBERED_NAME.match((c.get("name") or "").strip())]
    dup_names = sorted({nm for nm in names if names.count(nm) > 1 and nm})
    risky_names = [nm for nm in names if nm and RISKY_NAME.search(nm)]
    locked_names = [nm for nm in names if nm and TIME_LOCK.search(nm)]
    if empty_names:
        empty_desc = preview([f"{(c.get('name') or '空')}({c.get('cdId')})" for c in empty_names])
        add("R-10", "P1",
            f"{len(empty_names)} 张数据卡名为空/纯编号（"
            f"{empty_desc}），Agent 无法按名理解",
            "改成「指标 + 维度 + 口径」的可读名称，例如「各区域单店日均销售额（月累计）」")
    if dup_names:
        add("R-10", "P1",
            f"{len(dup_names)} 组数据卡重名（{preview(dup_names)}），按名找卡会歧义",
            "用维度/口径后缀消歧，重名卡只保留一张或改名")
    if risky_names:
        add("R-10", "P1",
            f"{len(risky_names)} 张卡名含副本/测试/临时/未命名等字样（{preview(risky_names)}）",
            "清理副本与测试卡，避免 Agent 误选非生产卡片")
    if locked_names:
        add("R-10", "P2",
            f"{len(locked_names)} 张卡名锁定固定期间（{preview(locked_names)}）"
            f"，另有 {len(time_selectors)} 个时间筛选器",
            "卡名去掉固定年月，期间交给时间筛选器控制")

    # ── R-07 页面说明 ──
    if not text_cards:
        add("R-07", "P2", f"页面 {len(cards)} 张卡片中没有文本卡/说明卡",
            "补一张文本卡写清「这张看板回答什么问题、何时调用、口径说明」")

    # ── R-16 数据停更 ──
    latest = ((check_page or {}).get("signals") or {}).get("dataUtime") or \
        (page.get("mtime") or "")[:10]
    stale = False
    latest_date = parse_date(latest)
    if latest_date:
        age = (date.today() - latest_date).days
        if age > STALE_DAYS:
            stale = True
            add("R-16", "P1",
                f"数据停在 {latest_date.isoformat()}（{age} 天未更新），超过 {STALE_DAYS} 天阈值",
                "确认看板是否仍在维护；停更页移出数据范围，或恢复数据更新后再接入")

    # ── 评分：六维 ──
    focus = 15
    if n > 20:
        focus -= 5
    elif n < 5 or 13 <= n <= 20:
        focus -= 2
    if dup_names:
        focus -= 2
    if empty_names:
        focus -= 2
    if risky_names or locked_names:
        focus -= 2
    if not text_cards:
        focus -= 2
    focus = max(0, focus)

    metrics = 20
    metrics -= 4 * min(3, len(page_conflicts))
    if ratio_risks:
        metrics -= 4
    if param_hits:
        metrics -= 4
    metrics = max(0, metrics)

    hidden_only = bool(hidden) and not linkage
    if not linkage:
        linkage_score = 8 if hidden else 0
    else:
        linkage_score = 25
        if not has_time:
            linkage_score -= 7
        if present_groups:
            coverage = len(set(present_groups) & selector_groups) / len(present_groups)
            if coverage < 1:
                linkage_score -= int(round(10 * (1 - coverage)))
        if not business_linkage:
            linkage_score = min(linkage_score, 10)
    linkage_score = max(0, linkage_score)

    layers_score = 20
    if not (drill_cards or len(hier_groups) >= 2):
        layers_score -= 8
    if "detail" not in page_layers:
        layers_score -= 6
    if (drill_cards or len(hier_groups) >= 2) and not (set(hier_groups) & selector_groups):
        layers_score -= 6
    layers_score = max(0, layers_score)

    context = 10
    over_limit_rows = any(isinstance(rows_by_cd.get(t.get("cdId") or ""), int)
                          and rows_by_cd[t.get("cdId")] > 10000 for t in tables)
    if over_limit_rows:
        context = 0
    else:
        if (not samples_available) or missing_samples:
            context -= 3
        if n > 20:
            context -= 3
        if dup_names:
            context -= 2
        context = max(0, context)

    ops = 10
    if stale:
        ops -= 3
    if locked_names:
        ops -= 3
    if hidden_only:
        ops -= 2
    ops = max(0, ops)

    scores = {"focus": focus, "metrics": metrics, "linkage": linkage_score,
              "layers": layers_score, "context": context, "ops": ops}
    raw_total = sum(scores.values())
    has_p0 = any(f["level"] == "P0" for f in findings)
    has_blocker = any(f["level"] == "blocker" for f in findings)
    # 页级 P0（口径冲突/上下文超限/参数无承接）或阻断 → 不允许显示“可直接配置”。
    # 分数仍保留原始值供排查，展示分收敛到 64（需改造档），避免“91 分但 3 个 P0”的自相矛盾。
    total = min(raw_total, 64) if (has_p0 or has_blocker) else raw_total
    verdict = "blocker" if has_blocker else ("warn" if findings else "ok")

    return {"name": name, "pgId": page.get("pgId") or "",
            "available": True, "facts": facts, "scores": scores,
            "total": total, "rawTotal": raw_total, "hasP0": has_p0,
            "grade": grade_for(total), "verdict": verdict,
            "data_cards": data_cards, "selectors": selectors, "linkage": linkage,
            "selector_groups": selector_groups, "present_groups": present_groups,
            "page_layers": page_layers, "layer_counts": layer_counts,
            "dominant_layer": dominant_layer, "hier_groups": hier_groups,
            "time_locked": bool(locked_names), "stale": stale, "hidden_only": hidden_only,
            "findings": findings}


# ───────────────────────────── 跨页体检 ─────────────────────────────

def find_overlaps(ctxs):
    """跨页重复卡：dsId 相同 + 度量名交集 ≥2 + 维度交集 ≥1"""
    overlaps = []
    involved = set()
    pair_count = 0
    for i, a in enumerate(ctxs):
        for b in ctxs[i + 1:]:
            grouped = {}
            for ca in a["data_cards"]:
                ds_id = ca.get("dsId") or ""
                if not ds_id:
                    continue
                for cb in b["data_cards"]:
                    if (cb.get("dsId") or "") != ds_id:
                        continue
                    shared_m = measure_names(ca) & measure_names(cb)
                    shared_d = card_dims(ca) & card_dims(cb)
                    if len(shared_m) < 2 or not shared_d:
                        continue
                    grouped.setdefault(ds_id, []).append({
                        "a": ca, "b": cb,
                        "measures": sorted(shared_m), "dims": sorted(shared_d)})
            for ds_id, pairs in grouped.items():
                pair_count += len(pairs)
                involved.update(p["a"].get("cdId") for p in pairs if p["a"].get("cdId"))
                involved.update(p["b"].get("cdId") for p in pairs if p["b"].get("cdId"))
                shown = pairs[:5]  # 每数据集最多列 5 对；重叠占比按全部命中卡计算
                overlaps.append({
                    "pages": [a["name"], b["name"]],
                    "cards": [f"{p['a'].get('name')}({p['a'].get('cdId')}) ↔ "
                              f"{p['b'].get('name')}({p['b'].get('cdId')})" for p in shown],
                    "reason": f"同数据集 {ds_id} + 共同指标 {preview(shown[0]['measures'], 3)}"
                              f" + 共同维度 {preview(shown[0]['dims'], 3)}"
                              f"；命中 {len(pairs)} 对卡片",
                })
    total_cards = sum(len(c["data_cards"]) for c in ctxs)
    ratio = (len(involved) / total_cards) if total_cards else 0.0
    return overlaps, involved, ratio, pair_count


def shared_linkage_dims(ctxs):
    """各页「筛选栏内联动筛选器」字段名交集 → [{field, pages}]"""
    field_pages = {}
    for ctx in ctxs:
        for sel in ctx["linkage"]:
            field = selector_label(sel)
            if not field:
                continue
            pages = field_pages.setdefault(field, [])
            if ctx["name"] not in pages:
                pages.append(ctx["name"])
    shared = [{"field": field, "pages": pages}
              for field, pages in field_pages.items() if len(pages) >= 2]
    # 非时间维度优先、页数多优先，字段名兜底排序 → 输出稳定
    shared.sort(key=lambda x: (bool(TIME_HINT.search(x["field"])), -len(x["pages"]), x["field"]))
    return shared


def cross_analysis(ctxs, conflicts, max_pages):
    """跨页发现 + 组合级指标；返回 (cross, refs, portfolio_score, findings)"""
    findings = []

    def add(rule, level, scope, evidence, action, pages):
        f = make_finding(rule, level, scope, evidence, action, pages)
        findings.append(f)
        return f

    available = [c for c in ctxs if c["available"]]
    page_names = [c["name"] for c in ctxs]
    refs = {"overlaps": [], "conflicts": [], "shared": None, "layers": [], "budget": None}

    # R-01 页数预算
    budget_ok = len(page_names) <= max_pages
    if not budget_ok:
        refs["budget"] = add(
            "R-01", "blocker", "portfolio",
            f"数据范围共 {len(page_names)} 张看板（{preview(page_names, 5)}），"
            f"超过本次预算 {max_pages} 张（官方上限 {DEFAULT_MAX_PAGES} 张）",
            f"按目标业务问题取舍到 ≤{max_pages} 张；其余拆成第二个智能体或先移出数据范围",
            page_names)

    # 跨页口径冲突（R-05）
    cross_conflicts = []
    for record in conflicts:
        pages = [p for p in record["pages"] if p in page_names]
        if len(pages) >= 2:
            cross_conflicts.append({"metric": record["metric"], "pages": pages,
                                    "detail": record["detail"]})
            refs["conflicts"].append(add(
                "R-05", "P0", "cross",
                f"指标「{record['metric']}」在 {len(pages)} 张看板（{preview(pages)}）公式不一致："
                f"{record['detail']}",
                "先确认是否同一指标：不同指标请改名消歧（如「老品占比/新品占比」）；"
                "同一指标请统一数据源与公式，业务拍板后固化，禁止让 Agent 二选一",
                pages))
        elif len(pages) == 1:
            page_name = pages[0]
            refs["conflicts"].append(add(
                "R-05", "P0", f"page:{page_name}",
                f"指标「{record['metric']}」在同页多张卡片公式不一致：{record['detail']}",
                "先确认是否同一指标：不同指标改名消歧；同一指标统一公式——"
                "同名不同口径会让 Agent 给出互相矛盾的结论",
                pages))
        elif record["pages"]:
            # formulas.json 的来源看板不在本次范围（旧产物/换了看板集）：不静默丢弃
            refs["conflicts"].append(add(
                "R-05", "P0", "portfolio",
                f"指标「{record['metric']}」存在公式冲突，但来源看板不在本次数据范围"
                f"（{preview(record['pages'])}）：{record['detail']}",
                "确认 formulas.json 是否基于本次看板重新生成；如相关则统一口径后再体检",
                page_names))

    # R-13 共享联动维度
    shared = shared_linkage_dims(available)
    shared_non_time = [s for s in shared if not TIME_HINT.search(s["field"])]
    if len(available) >= 2:
        if not shared:
            page_fields = [f"{c['name']}={preview([selector_label(s) for s in c['linkage']], 3)}"
                           for c in available]
            refs["shared"] = add(
                "R-13", "P0", "cross",
                f"{len(available)} 张看板的筛选栏联动字段无交集"
                f"（各页字段：{preview(page_fields, 3)}）",
                "统一公共维度命名（区域/省份/城市/门店编码/品类），每页配置同一字段的联动筛选器",
                [c["name"] for c in available])
        elif not shared_non_time:
            refs["shared"] = add(
                "R-13", "P1", "cross",
                f"跨页只有时间维度共享（{preview([s['field'] for s in shared])}）——时间只能限定范围，不能定位对象",
                "补一个跨页共用的业务维度联动筛选器（区域/门店/品类），用于主从传参",
                [c["name"] for c in available])

    # R-07 跨页重复卡
    overlaps, involved, ratio, pair_count = find_overlaps(available)
    if overlaps:
        pairs = pair_count
        if ratio > 0.30:
            level = "P0"
        elif ratio >= 0.10:
            level = "P1"
        else:
            level = "P2"
        pages = sorted({p for o in overlaps for p in o["pages"]})
        detail = "；".join(f"{o['pages'][0]}「{o['cards'][0]}」" if o["cards"] else ""
                          for o in overlaps[:3])
        f = add("R-07", level, "cross",
                f"跨页疑似重复卡片 {pairs} 对（涉及 {len(involved)} 张卡，占数据卡 {ratio:.0%}）："
                f"{detail}（{overlaps[0]['reason']}；按结构相似判定，需人工确认是否真重复）",
                "人工确认后：确属重复则保留一页、另一页改为联动引用或删除；"
                "只是同数据集不同视角则保留并改名消歧",
                pages)
        refs["overlaps"].append(f)

    # 层级完整性：既看三层是否都存在，也看是否被拆到不同页面。
    # 一张 40 卡大页同时含总览/定位/明细，不等于“三层齐全”，而是“层级混在一页”。
    layers_map = {k: [c["name"] for c in available if k in c["page_layers"]]
                  for k in LAYER_KEYS}
    covered = sum(1 for k in LAYER_KEYS if layers_map[k])
    mixed_pages = [c["name"] for c in available if len(c["page_layers"]) > 1]
    single_layer_pages = [c["name"] for c in available if len(c["page_layers"]) == 1]
    if available:
        if not layers_map["detail"]:
            refs["layers"].append(add(
                "R-12", "P1", "portfolio",
                f"所有看板都停留在总览/定位层，缺明细层（总览页：{preview(layers_map['overview']) or '无'}；"
                f"定位页：{preview(layers_map['mid']) or '无'}）",
                "补明细页/对象清单（门店/商品/订单粒度），用对象 ID 串联各层",
                [c["name"] for c in available]))
        if not layers_map["overview"]:
            layer_desc = [f"{c['name']}={preview(sorted(c['page_layers']))}" for c in available]
            refs["layers"].append(add(
                "R-12", "P1", "portfolio",
                f"没有总览层（各页推断层级：{preview(layer_desc, 3)}）",
                "补总览页，先判断整体是否异常，再逐层定位",
                [c["name"] for c in available]))
        if len(available) >= 2 and len(mixed_pages) == len(available) and covered >= 2:
            layer_desc = [f"{c['name']}={preview(sorted(c['page_layers']))}" for c in available]
            refs["layers"].append(add(
                "R-12", "P1", "portfolio",
                f"{len(mixed_pages)} 张看板都同时承载多个层级（{preview(layer_desc, 3)}）——"
                f"层级混在一页，Agent 难以判断该先看哪一层",
                "按总览 → 定位 → 明细拆页；每页只承载该层问题，层间用筛选器传参",
                mixed_pages))

    # ── 组合级评分 ──
    n_avail = len(available) or 1
    linkage_ready = int(round(25 * sum(1 for c in available if c["linkage"]) / n_avail))
    if len(available) < 2:
        shared_score = 20
    elif shared_non_time:
        shared_score = 20
    elif shared:
        shared_score = 10
    else:
        shared_score = 0
    consistency = max(0, 20 - 5 * len(cross_conflicts))
    if ratio > 0.30:
        redundancy = 5
    elif ratio >= 0.10:
        redundancy = 10
    else:
        redundancy = 15
    if covered == 3:
        layers_score = 10 if len(single_layer_pages) >= 3 else 5
    else:
        layers_score = {2: 5, 1: 2, 0: 0}[covered]
    budget_score = 10 if budget_ok else 0
    portfolio_score = linkage_ready + shared_score + consistency + redundancy + layers_score + budget_score

    cross = {"overlaps": overlaps, "sharedLinkageDims": shared,
             "conflicts": cross_conflicts, "layers": layers_map,
             "mixedPages": mixed_pages}
    return cross, refs, portfolio_score, findings


# ───────────────────────────── 推荐模式 ─────────────────────────────

def object_cardinality(samples):
    """样例列画像里对象类文本列的最大 distinct（SKU/门店/客户）"""
    best = 0
    if not isinstance(samples, dict):
        return best
    for entry in samples.values():
        if not isinstance(entry, dict):
            continue
        for column, profile in (entry.get("profile") or {}).items():
            if not isinstance(profile, dict) or profile.get("type") != "text":
                continue
            if OBJECT_HINT.search(column or ""):
                best = max(best, int(profile.get("distinct") or 0))
    return best


def recommend_mode(ctxs, cross, samples, page_count):
    available = [c for c in ctxs if c["available"]]
    total_cards = sum(len(c["data_cards"]) for c in available)
    hier = set()
    for c in available:
        hier.update(c["hier_groups"])
    hier_levels = [g for g in HIERARCHY_GROUPS if g in hier]
    stages = set()
    corpus = [c["name"] for c in available] + \
             [card.get("name") or "" for c in available for card in c["data_cards"]]
    for label, pat in STAGE_PATTERNS:
        if any(pat.search(text) for text in corpus):
            stages.add(label)
    objects = object_cardinality(samples)
    non_time_shared = [s for s in cross["sharedLinkageDims"] if not TIME_HINT.search(s["field"])]

    signals = {
        "一张宽表": page_count <= 2 and total_cards <= 40 and len(hier_levels) < 2,
        "多层下钻": len(hier_levels) >= 2,
        "主从Agent": page_count >= 3,
        "批量分治": objects >= 200,
        "链路复盘": len(stages) >= 2 and page_count >= 2,
    }
    order = ["一张宽表", "多层下钻", "主从Agent", "批量分治", "链路复盘"]
    primary = next((m for m in order if signals[m]), "主从Agent" if page_count >= 2 else "一张宽表")

    alternatives = [m for m in order if m != primary and signals[m]][:2]
    if not alternatives:
        alternatives = ["主从Agent"] if page_count >= 2 else ["一张宽表"]
        alternatives = [m for m in alternatives if m != primary] or ["一张宽表"]

    parts = [f"共 {page_count} 张看板 / {total_cards} 张数据卡"]
    if hier_levels:
        parts.append(f"卡片维度覆盖 {'/'.join(hier_levels)} 层级")
    if non_time_shared:
        parts.append(f"跨页共享 {preview([s['field'] for s in non_time_shared], 3)} 联动字段")
    if objects:
        parts.append(f"对象类字段最大基数约 {objects}")
    if stages:
        parts.append(f"标注到的业务阶段：{preview(sorted(stages))}")
    tail = {
        "链路复盘": "按阶段拆页、用对象 ID 串联，才能回答从开发到售后的全过程问题",
        "批量分治": "单对象分析稳定但对象成百上千，必须定义分批/遍历/汇总",
        "多层下钻": "需要集团/区域/门店逐层定位，按总览→定位→明细传参最稳定",
        "主从Agent": "跨看板整合结论，主Agent 规划、子Agent 单页分析更合适",
        "一张宽表": "页数与对象都少，链路可一次读完，单页宽表最省配置",
    }[primary]
    reason = "；".join(parts) + f"——{tail}"
    return {"primary": primary, "alternatives": alternatives, "reason": reason}


# ───────────────────────────── 建议底稿 ─────────────────────────────

def _page_verdict_candidate(ctx, overlap_pages):
    if not ctx["available"] or ctx["stale"]:
        return "移出"
    if ctx["facts"]["dataCards"] > 20:
        return "拆分"
    if ctx["name"] in overlap_pages:
        return "合并"
    if ctx["findings"]:
        return "改造"
    return "保留"


def _priority_of(level):
    return "P0" if level in ("blocker", "P0") else ("P1" if level == "P1" else "P2")


def build_seed(audit, ctxs, refs, mode, overlap_pages):
    page_actions = []
    for ctx in ctxs:
        page_findings = sorted([f for f in audit["findings"] if ctx["name"] in f["_pages"]],
                               key=lambda f: (_priority_of(f["level"]), f["id"]))
        priority = "P2"
        for f in page_findings:
            if f["level"] in ("blocker", "P0"):
                priority = "P0"
                break
            if f["level"] == "P1":
                priority = "P1"
        actions = []
        for f in page_findings:
            if f["action"] not in actions:
                actions.append(f["action"])
        page_actions.append({
            "pgId": ctx["pgId"],
            "name": ctx["name"],
            "verdict": _page_verdict_candidate(ctx, overlap_pages),
            "priority": priority,
            "actions": actions[:4],
            "evidence": [f["id"] for f in page_findings],
            "expectedEffect": "",
        })

    # 建议文件统一用 pgId 引用看板（报告校验按 pgId 核对），这里把内部页面名映射成 id
    name_to_id = {ctx["name"]: ctx["pgId"] for ctx in ctxs}

    def page_ids_of(finding):
        return [name_to_id.get(n, n) for n in finding["_pages"]]

    cross_actions = []
    for f in refs["overlaps"]:
        cross_actions.append({"type": "合并", "pages": page_ids_of(f),
                              "priority": _priority_of(f["level"]),
                              "action": f["action"], "evidence": [f["id"]]})
    for f in refs["conflicts"]:
        if f["scope"].startswith("page:"):
            continue
        cross_actions.append({"type": "统一口径", "pages": page_ids_of(f),
                              "priority": _priority_of(f["level"]), "action": f["action"],
                              "evidence": [f["id"]]})
    if refs["shared"]:
        f = refs["shared"]
        cross_actions.append({"type": "补筛选器", "pages": page_ids_of(f),
                              "priority": _priority_of(f["level"]),
                              "action": f["action"], "evidence": [f["id"]]})
    for f in refs["layers"]:
        cross_actions.append({"type": "补层", "pages": page_ids_of(f),
                              "priority": _priority_of(f["level"]),
                              "action": f["action"], "evidence": [f["id"]]})
    if refs["budget"]:
        f = refs["budget"]
        cross_actions.append({"type": "移出", "pages": page_ids_of(f),
                              "priority": _priority_of(f["level"]),
                              "action": f["action"], "evidence": [f["id"]]})

    linkage_filters = []
    for ctx in ctxs:
        for sel in sorted(ctx["linkage"], key=lambda s: (selector_label(s), s.get("cdId") or "")):
            linkage_filters.append({"pgId": ctx["pgId"], "name": sel.get("name") or "",
                                    "field": selector_label(sel),
                                    "cdId": sel.get("cdId") or ""})

    business_gaps = []
    if any(f["rule"] == "R-16" for f in audit["findings"]):
        business_gaps.append("看板数据更新频率与责任部门")
    if any(f["rule"] == "R-10" for f in audit["findings"]):
        business_gaps.append("卡片名称对应的指标口径与业务含义")

    return {
        "_help": "体检器生成的建议底稿：pgId/verdict/priority/evidence 与联动筛选器已按结构候选填好，"
                 "业务判断（scenario/businessScope/targetArchitecture/expectedEffect/roadmap/openQuestions）"
                 "由 AI 与用户确认后补全，再另存为 insight-advice.json。",
        "auditBuiltAt": audit["meta"]["builtAt"],
        "scenario": audit["meta"]["scenario"],
        "businessScope": "",
        "mode": dict(mode),
        "targetArchitecture": [],
        "pageActions": page_actions,
        "crossPageActions": cross_actions,
        "configHandoff": {
            "linkageFilters": linkage_filters,
            "businessScope": "",
            "defaultThinking": "",
            "outputRequirements": "",
            "businessKnowledgeGaps": business_gaps,
            "expertRoles": [],
        },
        "roadmap": [],
        "openQuestions": [],
    }


# ───────────────────────────── 主流程 ─────────────────────────────

USAGE = ("用法: python3 audit_insight_pages.py <工作目录> [--scenario TEXT] [--max-pages N] "
         "[--out PATH] [--seed-advice]")


def fail(message, code=2):
    print(f"❌ {message}", file=sys.stderr)
    sys.exit(code)


def parse_args(argv):
    workdir, scenario, out = None, "", None
    max_pages = DEFAULT_MAX_PAGES
    seed = False
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--scenario":
            if i + 1 >= len(argv):
                fail(f"--scenario 缺少取值\n{USAGE}")
            scenario = argv[i + 1]
            i += 2
        elif arg == "--max-pages":
            if i + 1 >= len(argv):
                fail(f"--max-pages 缺少取值\n{USAGE}")
            try:
                max_pages = int(argv[i + 1])
            except ValueError:
                fail(f"--max-pages 需要整数，收到 {argv[i + 1]!r}\n{USAGE}")
            if max_pages < 1:
                fail(f"--max-pages 必须 ≥1，收到 {max_pages}\n{USAGE}")
            i += 2
        elif arg == "--out":
            if i + 1 >= len(argv):
                fail(f"--out 缺少取值\n{USAGE}")
            out = argv[i + 1]
            i += 2
        elif arg == "--seed-advice":
            seed = True
            i += 1
        elif arg in ("-h", "--help"):
            print(USAGE)
            sys.exit(0)
        elif arg.startswith("-"):
            fail(f"未知参数 {arg}\n{USAGE}")
        else:
            if workdir is not None:
                fail(f"只能指定一个工作目录，收到 {workdir!r} 与 {arg!r}\n{USAGE}")
            workdir = arg
            i += 1
    if not workdir:
        fail(f"缺少工作目录\n{USAGE}")
    return workdir, scenario, max_pages, out, seed


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    workdir, scenario, max_pages, out, seed = parse_args(argv)
    if not os.path.isdir(workdir):
        fail(f"工作目录不存在: {workdir}")

    cards_path = os.path.join(workdir, "cards-raw.json")
    cards_raw, err = json_load(cards_path)
    if err == "missing":
        fail(f"找不到 {cards_path}——先运行 parse_page.py 生成 cards-raw.json，"
             f"洞察Agent 诊断必须从看板结构解析开始")
    if err == "invalid":
        fail(f"{cards_path} 无法解析（内容损坏或非 JSON）——重跑 parse_page.py，"
             f"禁止在残缺数据上出诊断")
    if not isinstance(cards_raw, dict):
        fail(f"{cards_path} 结构不符（应为 {{看板名: {{...}}}} 对象）——重跑 parse_page.py")

    page_check, page_check_err = json_load(os.path.join(workdir, "page-check.json"))
    formulas, formulas_err = json_load(os.path.join(workdir, "formulas.json"))
    samples, samples_err = json_load(os.path.join(workdir, "card-data", "_sample_index.json"))
    if not isinstance(page_check, dict):
        page_check = None
    if not isinstance(formulas, dict):
        formulas = None
    if not isinstance(samples, dict):
        samples = None
    check_map = {p.get("pgId"): p for p in (page_check or {}).get("pages") or []
                 if isinstance(p, dict) and p.get("pgId")}
    conflicts = conflict_records(formulas)
    deps = param_dependency_records(formulas)
    rows_by_cd, samples_available = sample_maps(samples)

    pages_raw = list(iter_pages(cards_raw))
    if not pages_raw:
        fail(f"{cards_path} 中没有可诊断的看板（只有 _meta 或空对象）——先运行 parse_page.py")

    ctxs = []
    for name, page in pages_raw:
        ctxs.append(audit_page(name, page, check_map.get(page.get("pgId")),
                               conflicts, deps, rows_by_cd, samples_available))

    page_names = [c["name"] for c in ctxs]
    cross, refs, portfolio_score, cross_findings = cross_analysis(
        ctxs, conflicts, max_pages)

    all_findings = []
    for ctx in ctxs:
        all_findings.extend(ctx["findings"])
    all_findings.extend(cross_findings)
    for index, finding in enumerate(all_findings, 1):
        finding["id"] = f"F-{index:03d}"

    available = [c for c in ctxs if c["available"]]
    page_mean = int(round(sum(c["total"] for c in available) / len(available))) if available else 0
    raw_overall = int(round(page_mean * 0.6 + portfolio_score * 0.4))
    overall = raw_overall
    if refs["budget"] or not available:
        overall = min(overall, 49)
    if any(f["level"] == "P0" for f in all_findings):
        overall = min(overall, 64)
    if any(f["rule"] == "R-02" and f["level"] == "blocker" for f in all_findings):
        overall = min(overall, 64)
    grade = grade_for(overall)

    skipped = []
    if formulas is None:
        reason = "损坏，已忽略" if formulas_err == "invalid" else "缺失"
        skipped.append(f"R-05 口径冲突 / R-08 参数化（formulas.json {reason}）")
    if not samples_available:
        reason = "损坏，已忽略" if samples_err == "invalid" else "缺失"
        skipped.append(f"R-06 明细行数（card-data/_sample_index.json {reason}，未实测）")
    if page_check_err == "invalid":
        skipped.append("page-check.json 损坏，停更信号退化为页面 mtime")

    pages_out = []
    for ctx in ctxs:
        page_ids = [f["id"] for f in all_findings if ctx["name"] in f["_pages"]]
        entry = {
            "pgId": ctx["pgId"],
            "name": ctx["name"],
            "verdict": ctx["verdict"],
            "facts": ctx["facts"],
            "scores": ctx["scores"],
            "total": ctx["total"],
            "rawTotal": ctx.get("rawTotal", ctx["total"]),
            "hasP0": ctx.get("hasP0", False),
            "grade": ctx["grade"],
            "findings": page_ids,
        }
        if not ctx["available"]:
            entry["unavailable"] = True
        pages_out.append(entry)

    meta = {
        "builtAt": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "builderVersion": BUILDER_VERSION,
        "scenario": scenario,
        "pageCount": len(page_names),
        "maxPages": max_pages,
        "inputs": {"pageCheck": isinstance(page_check, dict),
                   "formulas": isinstance(formulas, dict),
                   "samples": samples_available},
        "biBaseUrl": (cards_raw.get("_meta") or {}).get("biBaseUrl", ""),
        "officialMaxPages": DEFAULT_MAX_PAGES,
        "environmentCheck": "unverified",
        "skippedRules": skipped,
    }

    audit = {
        "meta": meta,
        "pages": pages_out,
        "cross": cross,
        "findings": all_findings,
        "portfolio": {"score": portfolio_score, "grade": grade,
                      "overall": overall, "rawOverall": raw_overall},
        "recommendedMode": recommend_mode(ctxs, cross, samples, len(page_names)),
    }
    seed_doc = None
    if seed:
        overlap_pages = {p for o in cross["overlaps"] for p in o["pages"]}
        seed_doc = build_seed(audit, ctxs, refs, audit["recommendedMode"], overlap_pages)
    for finding in audit["findings"]:
        finding.pop("_pages", None)

    out_path = out or os.path.join(workdir, "insight-audit.json")
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(audit, f, ensure_ascii=False, indent=1)

    seed_path = None
    if seed_doc is not None:
        seed_path = os.path.join(workdir, "insight-advice.seed.json")
        with open(seed_path, "w", encoding="utf-8") as f:
            json.dump(seed_doc, f, ensure_ascii=False, indent=1)

    blockers = [f for f in audit["findings"] if f["level"] == "blocker"]
    counts = {lvl: sum(1 for f in audit["findings"] if f["level"] == lvl)
              for lvl in ("P0", "P1", "P2")}
    print("洞察Agent 看板就绪诊断完成")
    print(f"  看板 {len(page_names)} 张（可用 {len(available)}）· 总分 {overall}/100（{grade}）"
          f" · 阻断 {len(blockers)} 项 · P0 {counts['P0']} / P1 {counts['P1']} / P2 {counts['P2']}")
    for page in pages_out:
        mark = {"blocker": "⛔", "warn": "⚠️", "ok": "✅"}.get(page["verdict"], "•")
        print(f"  {mark} 《{page['name']}》{page['total']} 分（{page['grade']}）"
              f"· 数据卡 {page['facts']['dataCards']} · 联动筛选器 {page['facts']['linkageSelectors']}")
    print(f"  推荐模式：{audit['recommendedMode']['primary']}"
          f"（备选：{'、'.join(audit['recommendedMode']['alternatives']) or '无'}）")
    if max_pages != DEFAULT_MAX_PAGES:
        print(f"  ⚠️ --max-pages 已调为 {max_pages}；官方上限为 {DEFAULT_MAX_PAGES} 张，报告需说明取舍理由")
    print(f"  已写入 {out_path}")
    if seed_path:
        print(f"  已写入 {seed_path}")
    return 0


if __name__ == "__main__":
    main()
