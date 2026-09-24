#!/usr/bin/env python3
"""
看板适检器：在用户勾选看板后、资产学习前，快速判断每张看板适不适合组装进 data agent
用法:
  python3 check_pages.py <pageId> [pageId2 ...]              # 控制台报告
  python3 check_pages.py <pageId> ... -o <目录>              # 同时写 <目录>/page-check.json
  python3 check_pages.py <pageId> ... --stale-days 60        # 数据停更阈值（默认 90 天）
  python3 check_pages.py <pageId> ... --workers 6            # 并发数（默认 4）
判定分三档:
  ✅ 适合   —— 无风险信号
  ⚠️ 有风险 —— 能用但有坑（重名卡多/数据停更/一次性快照/卡片过少/名称疑似演示备份）
  ⛔ 不可用 —— 取不到/非普通仪表板/0 数据卡/数据集全部不可读
设计原则: 每张看板只调一次 page get --raw，并发执行；不做 card preview / ds get（那是第 2 步的事）。
"""
import json, re, subprocess, sys, os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

RISKY_NAME = re.compile(r'演示|验证|测试|副本|备份|临时|样例|勿动|废弃|demo|test', re.I)
# 绝对时间锁定：卡名里写死具体年/月（"8月出杯""2026年8月"）；排除 月度/月趋势/月均等通用词
TIME_LOCK = re.compile(r'(20\d{2}\s*年\s*\d{1,2}\s*月|20\d{2}[-/]\d{1,2}|\d{1,2}\s*月(?!\s*[度趋均累份]))')
DATE_HINT = re.compile(r'日期|时间|年月|月份|账期|周')
DATA_TYPES = ('CHART', 'DRILL')


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


def check_one(page_id, stale_days):
    data, err = fetch_raw(page_id)
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
    from collections import Counter
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
    return {"pgId": page_id, "verdict": verdict, "name": name,
            "reasons": reasons, "notes": notes, "signals": signals}


def main():
    args = sys.argv[1:]
    out, stale_days, workers = None, 90, 4
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
        sys.exit("用法: python3 check_pages.py <pageId> [pageId2 ...] [-o 目录] [--stale-days 90] [--workers 4]")

    results = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(check_one, pid, stale_days): pid for pid in page_ids}
        for fut in as_completed(futs):
            r = fut.result()
            results[r["pgId"]] = r
            print(f"  适检完成: {r['name']}", file=sys.stderr)

    n_ok = sum(1 for r in results.values() if r["verdict"] == "✅")
    n_warn = sum(1 for r in results.values() if r["verdict"] == "⚠️")
    n_bad = sum(1 for r in results.values() if r["verdict"] == "⛔")
    print(f"\n看板适检报告（{len(results)} 张：✅{n_ok} ⚠️{n_warn} ⛔{n_bad}）")
    print("=" * 60)
    for pid in page_ids:  # 按用户勾选顺序输出
        r = results[pid]
        print(f"{r['verdict']} 《{r['name']}》")
        for reason in r.get("reasons") or []:
            print(f"    - {reason}")
        for note in r.get("notes") or []:
            print(f"    + {note}")
    if n_bad or n_warn:
        print("\n建议：⛔ 的看板请换普通仪表板；⚠️ 的看板可保留，但上述风险会在后续步骤中跟踪处理")
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
