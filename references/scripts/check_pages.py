#!/usr/bin/env python3
"""
看板适检器 + agent-ready 评分：在用户勾选看板后、资产学习前，判断每张看板适不适合组装进 data agent
用法:
  python3 check_pages.py <pageId> [pageId2 ...]              # 控制台报告
  python3 check_pages.py <pageId> ... -o <目录>              # 同时写 <目录>/page-check.json
  python3 check_pages.py <pageId> ... --stale-days 60        # 数据停更阈值（默认 90 天）
  python3 check_pages.py <pageId> ... --workers 6            # 并发数（默认 4）
  python3 check_pages.py <pageId> ... --skip-governed        # 不查指标中心（少一层信号，更快）
判定分两层:
  适检三档（硬门槛 + 风险信号）:
    ✅ 适合   —— 无风险信号
    ⚠️ 有风险 —— 能用但有坑（重名卡多/数据停更/一次性快照/卡片过少/名称疑似演示备份）
    ⛔ 不可用 —— 取不到/非普通仪表板/0 数据卡/数据集全部不可读（不评分）
  agent-ready 评分（0–100，看板作为知识源的质量，设计推演见 references/dashboard-knowledge-rationale.md 第一节）:
    口径一致性(40)  同名指标多种算法 = 口径混乱，是有毒信号 → 进红线清单，必须先治理
    权威标注率(25)  指标中心（metric by-dataset）已发布指标名命中看板指标名的比例
    数据集复用率(20) 数据集被多张数据卡共用的卡片占比（复用高 = ETL 成果与权限免费继承）
    粒度覆盖度(15)  数据集维度字段被卡片行维度/筛选器用到的比例（覆盖低 = 能力边界，不是毒）
    ≥75 高 / 45–74 中 / <45 低；有口径冲突最高只到「中」。指标中心查不到时该维度权重按比例重分摊。
    低分不拦路：建议先在 BI 里治理（标注权威口径/统一同名指标算法）再进挖掘向导；
    坚持继续也可以，红线项会在第 4 步口径确认逐条裁决。
调用预算: 每张看板一次 page get --raw（并发）；每个数据集一次 metric by-dataset（--skip-governed 可省）。
"""
import json, re, subprocess, sys, os
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

RISKY_NAME = re.compile(r'演示|验证|测试|副本|备份|临时|样例|勿动|废弃|demo|test', re.I)
# 绝对时间锁定：卡名里写死具体年/月（"8月出杯""2026年8月"）；排除 月度/月趋势/月均等通用词
TIME_LOCK = re.compile(r'(20\d{2}\s*年\s*\d{1,2}\s*月|20\d{2}[-/]\d{1,2}|\d{1,2}\s*月(?!\s*[度趋均累份]))')
DATE_HINT = re.compile(r'日期|时间|年月|月份|账期|周')
DATA_TYPES = ('CHART', 'DRILL')
# 口径一致性得分表：0 冲突满分，1 个 0.4，2 个 0.1，≥3 个 0——口径混乱是有毒信号，重罚
CONSISTENCY_TABLE = {0: 1.0, 1: 0.4, 2: 0.1}
WEIGHTS = {"consistency": 40, "governed": 25, "reuse": 20, "grain": 15}


def fetch_raw(page_id, timeout=60):
    r = subprocess.run(["guancli", "page", "get", page_id, "--raw"],
                       capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        m = re.search(r'message=([^,}]+)', r.stderr or r.stdout)
        return None, (m.group(1) if m else (r.stderr or r.stdout)[:120])
    try:
        return json.loads(r.stdout).get("data"), None
    except json.JSONDecodeError:
        return None, "返回数据格式异常"


def _zone_data(card):
    return (((card.get("content") or {}).get("meta") or {}).get("chartMain") or {}).get("zoneData") or {}


def _fd_name_map(data):
    """dsInfos[].columns → {fdId: 字段名}（与 parse_page.py 同口径）"""
    m = {}
    for ds in data.get("dsInfos") or []:
        for col in ds.get("columns") or []:
            if col.get("fdId") and col.get("name"):
                m[col["fdId"]] = col["name"]
    return m


def normalize_formula(formula):
    """公式归一化：与 check_formulas.normalize 必须保持一致"""
    parts = re.split(r'(\[[^\]]*\])', formula or '')
    return ''.join(p if p.startswith('[') else re.sub(r'\s+', '', p).lower() for p in parts)


def page_measures(data):
    """页面级度量收割（check_formulas 轻量版）：评分专用，不做 ds get，只看卡片层"""
    out = []
    for c in data.get("cards") or []:
        if not isinstance(c, dict) or c.get("cdType") not in DATA_TYPES:
            continue
        for m in _zone_data(c).get("metric") or []:
            if not isinstance(m, dict):
                continue
            out.append({
                "display": (m.get("alias") or m.get("name") or "?"),
                "name": m.get("name") or "",
                "alias": m.get("alias") or "",
                "formula": m.get("formula") or "",
                "aggrType": m.get("aggrType") or "",
                "advType": (m.get("advCalc") or {}).get("advType") or "",
            })
    return out


def find_conflicts(measures):
    """同名指标多种算法 → [{"name", "variants"}]。与 check_formulas 同口径：
    别名≠本名的展示层派生条目不参与；纯物理字段聚合方式差异降级不算冲突。"""
    groups = {}
    for m in measures:
        if m["alias"] and m["alias"] != m["name"]:
            continue  # 展示层派生（同比/占比等）：真实身份是基数字段
        key = normalize_formula(m["formula"]) if m["formula"] else f"__field__{m['name']}:{m['aggrType']}"
        groups.setdefault(m["display"], {}).setdefault(key, m)
    conflicts = []
    for name, variants in sorted(groups.items()):
        if len(variants) > 1 and any(not k.startswith("__field__") for k in variants):
            conflicts.append({"name": name, "variants": [
                re.sub(r'\s+', ' ', v["formula"]).strip() or f"物理字段 {v['name']}（{v['aggrType']}）"
                for v in variants.values()]})
    return conflicts


def reuse_rate(data):
    """数据集复用率：数据集被 ≥2 张数据卡共用的卡片占比。无 dsId 信息返回 None（权重重分摊）"""
    ds_ids = [(c.get("content") or {}).get("dsId") for c in data.get("cards") or []
              if isinstance(c, dict) and c.get("cdType") in DATA_TYPES]
    ds_ids = [d for d in ds_ids if d]
    if not ds_ids:
        return None
    cnt = Counter(ds_ids)
    return sum(n for n in cnt.values() if n > 1) / len(ds_ids)


def grain_coverage(data):
    """粒度覆盖度：数据集维度字段（metaType=DIM）被卡片行维度/筛选/筛选器用到的比例。
    数据集没有维度字段时返回 None（权重重分摊）"""
    available = set()
    for ds in data.get("dsInfos") or []:
        for col in ds.get("columns") or []:
            if col.get("metaType") == "DIM" and col.get("name"):
                available.add(col["name"])
    if not available:
        return None
    fd_names = _fd_name_map(data)
    used = set()
    for c in data.get("cards") or []:
        if not isinstance(c, dict):
            continue
        if c.get("cdType") in ("SELECTOR", "TREE_SELECTOR"):
            fname = (((c.get("content") or {}).get("source") or {}).get("field") or {}).get("name")
            if fname:
                used.add(fname)
            continue
        if c.get("cdType") not in DATA_TYPES:
            continue
        for d in _zone_data(c).get("row") or []:
            if isinstance(d, dict) and d.get("name"):
                used.add(d["name"])
        for f in _zone_data(c).get("filters") or []:
            if isinstance(f, dict) and f.get("fdId"):
                used.add(fd_names.get(f["fdId"], f["fdId"]))
    return len(used & available) / len(available)


def governed_rate(measures, governed_names):
    """权威标注率：看板指标名命中指标中心已发布指标名的比例 → (rate, [命中名])"""
    distinct = {m["display"] for m in measures if m["display"] != "?"}
    if not distinct:
        return None, []
    hit = sorted(distinct & governed_names)
    return len(hit) / len(distinct), hit


def agent_ready(data, governed_names=None):
    """单页 agent-ready 评分（纯函数）。
    governed_names: 指标中心已发布指标名集合；None = 未查询/查询失败（该维度权重按比例重分摊）"""
    measures = page_measures(data)
    conflicts = find_conflicts(measures)
    reuse = reuse_rate(data)
    grain = grain_coverage(data)

    parts = {"consistency": CONSISTENCY_TABLE.get(len(conflicts), 0.0)}
    if governed_names is not None:
        g_rate, g_hit = governed_rate(measures, governed_names)
        if g_rate is not None:
            parts["governed"] = g_rate
    else:
        g_rate, g_hit = None, []
    if reuse is not None:
        parts["reuse"] = reuse
    if grain is not None:
        parts["grain"] = grain

    total_w = sum(WEIGHTS[k] for k in parts)
    score = round(sum(WEIGHTS[k] * v for k, v in parts.items()) / total_w * 100)
    grade = "高" if score >= 75 else ("中" if score >= 45 else "低")
    red_lines, boundaries = [], []
    if conflicts:
        grade = "中" if grade == "高" else grade  # 口径混乱有毒：有冲突最高只到「中」
        red_lines = [f"「{c['name']}」有 {len(c['variants'])} 种算法（{' / '.join(c['variants'][:2])}）"
                     f"——口径混乱是有毒信号，必须先统一（建议先在 BI 里治理，至少第 4 步逐条裁决）"
                     for c in conflicts]
    if grain is not None and grain < 0.3:
        boundaries.append(f"维度切面只用到 {grain:.0%}——属覆盖不足（只压上限、没有毒），"
                          f"搭建后在能力边界里标注「能答的问题面偏窄」即可")
    if g_rate == 0.0:
        boundaries.append("指标中心没有已发布的权威口径命中本看板指标——"
                          "口径治理全部压到第 4 步确认，建议在 BI 里逐步补标注")
    return {
        "score": score, "grade": grade,
        "dims": {"conflicts": len(conflicts),
                 "governedRate": g_rate, "reuseRate": reuse, "grainCoverage": grain,
                 "governed": "ok" if governed_names is not None else "unavailable"},
        "conflictNames": [c["name"] for c in conflicts],
        "governedHits": g_hit,
        "redLines": red_lines,
        "boundaries": boundaries,
    }


def fetch_governed(ds_ids, workers=4):
    """指标中心已发布指标名（按数据集，一次调用/数据集）。单个失败不阻断：该数据集记为空集合"""
    def fetch(ds_id):
        try:
            r = subprocess.run(["guancli", "metric", "by-dataset", ds_id, "--raw"],
                               capture_output=True, text=True, timeout=60)
            if r.returncode != 0:
                return ds_id, None
            payload = json.loads(r.stdout)
        except (json.JSONDecodeError, subprocess.TimeoutExpired):
            return ds_id, None
        return ds_id, {(m.get("Detail") or {}).get("name")
                       for m in payload.get("Metrics") or []
                       if (m.get("Detail") or {}).get("status") == "PUBLISHED"
                       and (m.get("Detail") or {}).get("name")}

    result = {}
    if not ds_ids:
        return result
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(fetch, d): d for d in ds_ids}
        for fut in as_completed(futs):
            ds_id, names = fut.result()
            if names is not None:
                result[ds_id] = names
    return result


def _max_utime(data):
    """数据集最近更新时间：取 dsInfos 里最新的 utime（页面内嵌快照，快检够用）"""
    latest = ""
    for ds in data.get("dsInfos") or []:
        u = (ds or {}).get("utime") or ""
        if u > latest:
            latest = u
    if not latest:
        for c in data.get("cards") or []:
            u = (((c.get("content") or {}).get("dsInfo") or {}).get("utime")) or ""
            if u > latest:
                latest = u
    return latest[:10]


def evaluate(page_id, data, err, stale_days, governed=None):
    """评估单页：data/err 来自 fetch_raw；governed 为 {dsId: 指标名集合}，None 表示未查指标中心"""
    if err:
        return {"pgId": page_id, "verdict": "⛔", "name": page_id,
                "reasons": [f"看板内容取不到（{err}）——移动端轻应用/报告推送/填报页或无权限，无法学习"],
                "signals": {}}
    name = (data.get("name") or page_id).strip()
    pg_type = data.get("pgType") or "PAGE"
    cards = [c for c in data.get("cards") or [] if isinstance(c, dict)]
    data_cards = [c for c in cards if c.get("cdType") in DATA_TYPES]
    selectors = [c for c in cards if c.get("cdType") in ("SELECTOR", "TREE_SELECTOR")]
    signals, reasons, notes = {}, [], []

    # ── 硬门槛 ──
    if pg_type != "PAGE":
        kind = {"LARGE_SCREEN": "数据大屏", "OVERVIEW": "导航概览页"}.get(pg_type, pg_type)
        return {"pgId": page_id, "verdict": "⛔", "name": name,
                "reasons": [f"页面类型是「{kind}」不是普通仪表板——为视觉排版/导航设计，学不出可问数的资产"],
                "signals": {"pgType": pg_type}}
    if not data_cards:
        return {"pgId": page_id, "verdict": "⛔", "name": name,
                "reasons": ["没有任何数据卡片（纯文本/图片/导航页），无资产可学"],
                "signals": {"pgType": pg_type, "dataCards": 0}}
    unreadable = [c for c in data_cards if c.get("isDsReadable") is False]
    if unreadable and len(unreadable) == len(data_cards):
        return {"pgId": page_id, "verdict": "⛔", "name": name,
                "reasons": ["全部数据卡片的数据集都不可读（无数据集权限）"],
                "signals": {"dataCards": len(data_cards)}}

    # ── 质量信号 ──
    signals["pgType"] = pg_type
    signals["dataCards"] = len(data_cards)
    if RISKY_NAME.search(name):
        reasons.append(f"看板名「{name}」疑似演示/验证/备份页，建议确认是否正式生产看板")
    names = [(c.get("name") or "") for c in data_cards if c.get("name")]
    dups = {k: v for k, v in Counter(names).items() if v > 1}
    if names and (len(dups) >= 2 or sum(dups.values()) / len(names) > 0.1):
        signals["dupNames"] = dict(list(dups.items())[:5])
        reasons.append(f"数据卡重名 {sum(dups.values()) - len(dups)} 张（如「{'」「'.join(list(dups)[:3])}」各出现多次）"
                       f"——助手按名找卡会歧义，学习时需以下级维度/筛选条件消歧")
    if len(data_cards) < 5:
        reasons.append(f"只有 {len(data_cards)} 张数据卡，覆盖的问题面偏窄，建议搭配同主题看板")
    if unreadable:
        reasons.append(f"{len(unreadable)} 张卡的数据集不可读，这些卡学习不到")
    latest = _max_utime(data)
    if latest:
        signals["dataUtime"] = latest
        try:
            age = (datetime.now() - datetime.strptime(latest, "%Y-%m-%d")).days
            if age > stale_days:
                reasons.append(f"数据停在 {latest}（{age} 天未更新）——助手会天天答旧数，确认是否仍在维护")
        except ValueError:
            pass
    locked = [n for n in names if TIME_LOCK.search(n)]
    has_date_sel = any(DATE_HINT.search(str(((c.get("content") or {}).get("source") or {}).get("field") or {}))
                       or DATE_HINT.search(c.get("name") or "") for c in selectors)
    if names and len(locked) / len(names) >= 0.5 and not has_date_sel:
        signals["timeLocked"] = len(locked)
        reasons.append(f"{len(locked)}/{len(names)} 张卡名锁死固定期间（如「{locked[0]}」）且页面无时间筛选器"
                       f"——疑似一次性报告快照，只能回答那个期间的问题")
    # ── 加分项（不构成警告）──
    if any((c.get("content") or {}).get("hasDrill") or c.get("cdType") == "DRILL" for c in data_cards):
        notes.append("自带下钻路径，天然支撑归因场景")
    text_cards = [c for c in cards if c.get("cdType") == "TEXT"]
    if any(len(str((c.get("content") or {}).get("text") or (c.get("content") or {}).get("html") or "")) > 80
           for c in text_cards):
        notes.append("文本卡内含说明文字，可能沉淀了分析逻辑/口径")

    verdict = "⚠️" if reasons else "✅"
    result = {"pgId": page_id, "verdict": verdict, "name": name,
              "reasons": reasons, "notes": notes, "signals": signals}

    # ── agent-ready 评分（知识源质量，⛔ 看板不到这里）──
    if governed is None:
        result["agentReady"] = agent_ready(data, None)
    else:
        page_ds = {ds.get("dsId") for ds in data.get("dsInfos") or [] if ds.get("dsId")}
        if page_ds and not any(d in governed for d in page_ds):
            result["agentReady"] = agent_ready(data, None)  # 指标中心全部查询失败：权重重分摊
        else:
            names = set().union(*(governed.get(d, set()) for d in page_ds)) if page_ds else set()
            result["agentReady"] = agent_ready(data, names)
    return result


def main():
    args = sys.argv[1:]
    out, stale_days, workers = None, 90, 4
    skip_governed = '--skip-governed' in args
    args = [a for a in args if a != '--skip-governed']
    page_ids = []
    i = 0
    while i < len(args):
        if args[i] == '-o':
            out = args[i + 1]; i += 2
        elif args[i] == '--stale-days':
            stale_days = int(args[i + 1]); i += 2
        elif args[i] == '--workers':
            workers = int(args[i + 1]); i += 2
        else:
            page_ids.append(args[i]); i += 1
    if not page_ids:
        sys.exit("用法: python3 check_pages.py <pageId> [pageId2 ...] [-o 目录] [--stale-days 90] [--workers 4] [--skip-governed]")

    # 阶段一：并发取看板（每张一次 page get --raw）
    raws = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(fetch_raw, pid): pid for pid in page_ids}
        for fut in as_completed(futs):
            pid = futs[fut]
            raws[pid] = fut.result()
            print(f"  适检完成: {pid}", file=sys.stderr)

    # 阶段二：查指标中心权威口径（每个数据集一次，--skip-governed 跳过）
    governed = None
    if not skip_governed:
        ds_ids = sorted({ds.get("dsId") for data, err in raws.values() if data
                         for ds in data.get("dsInfos") or [] if ds.get("dsId")})
        governed = fetch_governed(ds_ids, workers)
        print(f"  指标中心: {len(governed)}/{len(ds_ids)} 个数据集查询成功"
              f"（已发布权威口径 {sum(len(v) for v in governed.values())} 个）", file=sys.stderr)

    results = {pid: evaluate(pid, *raws[pid], stale_days, governed) for pid in page_ids}

    n_ok = sum(1 for r in results.values() if r["verdict"] == "✅")
    n_warn = sum(1 for r in results.values() if r["verdict"] == "⚠️")
    n_bad = sum(1 for r in results.values() if r["verdict"] == "⛔")
    print(f"\n看板适检报告（{len(results)} 张：✅{n_ok} ⚠️{n_warn} ⛔{n_bad}）")
    print("=" * 60)
    for pid in page_ids:  # 按用户勾选顺序输出
        r = results[pid]
        ar = r.get("agentReady")
        score_txt = f"　agent-ready {ar['score']}/100（{ar['grade']}）" if ar else ""
        print(f"{r['verdict']} 《{r['name']}》{score_txt}")
        for reason in r.get("reasons") or []:
            print(f"    - {reason}")
        for note in r.get("notes") or []:
            print(f"    + {note}")
        if ar:
            dims = ar["dims"]
            def pct(v): return "—" if v is None else f"{v:.0%}"
            print(f"    评分: 口径冲突 {dims['conflicts']} 处 · 权威标注 {pct(dims['governedRate'])}"
                  f" · 数据集复用 {pct(dims['reuseRate'])} · 粒度覆盖 {pct(dims['grainCoverage'])}"
                  + ("" if dims["governed"] == "ok" else "（未查指标中心）"))
            for line in ar.get("redLines") or []:
                print(f"    🔴 {line}")
            for line in ar.get("boundaries") or []:
                print(f"    🔷 {line}")
    if n_bad or n_warn:
        print("\n建议：⛔ 的看板请换普通仪表板；⚠️ 的看板可保留，但上述风险会在后续步骤中跟踪处理")
    graded = [r["agentReady"] for r in results.values() if r.get("agentReady")]
    if any(g["grade"] == "低" or g["redLines"] for g in graded):
        print("\n治理建议：评分「低」或带 🔴 红线的看板是信噪比偏差的知识源——建议先在 BI 里治理"
              "（统一同名指标算法、在指标中心标注权威口径）再搭建；坚持继续也可以，红线项会在第 4 步口径确认逐条裁决")
    if out:
        os.makedirs(out, exist_ok=True)
        fp = os.path.join(out, "page-check.json")
        with open(fp, "w", encoding="utf-8") as f:
            json.dump({"builtAt": datetime.now().strftime("%Y-%m-%d %H:%M"),
                       "staleDays": stale_days,
                       "pages": [results[pid] for pid in page_ids]}, f, ensure_ascii=False, indent=1)
        print(f"\n已写入 {fp}", file=sys.stderr)


if __name__ == '__main__':
    main()
