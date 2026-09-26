#!/usr/bin/env python3
"""
数据集直学器（数据集冷启动路径）：没有合适看板时，第 2 步资产学习的替代动作
用法: python3 learn_dataset.py <dsId> [dsId2 ...] -o <工作目录> [--workers 4] [--max-rows 200]
输出: <工作目录>/datasets-raw.json
  {数据集名: {dsId, mtime, rowCount,
              columns: [{name, fdId, metaType, fdType, aggrType?, calcType?, formula?}],
              sample: {rows, sampledRows, truncated, profile}},
   "_meta": {builtAt, builderVersion, biBaseUrl, mode: "dataset",
             dsFormulas: {dsId: {dsName, virtualColumns}}}}
  _meta.dsFormulas 与 cards-raw.json 同构——check_formulas.py 回退读它时无需特判；
  sample.profile 列画像与 sample_cards.py 同构（枚举值是 check_dims.py 种子的成员值来源）
产物定位（与看板路径的诚实差异）:
  有：字段清单 / 数据集计算字段口径 / 列画像枚举值 → metrics/dimensions 档案与 SQL 直查照走
  没有：卡片、筛选器、看板语义（分析路径与问题空间）→ 交付的是"数据探索型"助手，
       能答"数据里有什么"，答不了"业务上该看什么"（能力边界必须写进交付助手自我介绍）
哨兵: 全部数据集获取失败 → exit 2（禁止静默产出空资产）；单个失败跳过并警告
"""
import json, re, subprocess, sys, os
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

BUILDER_VERSION = "4.1.1"  # 发布时与 SKILL.md frontmatter version 同步（同 parse_page.py/workbench.py）
DEFAULT_MAX_ROWS = 200
ENUM_LIMIT = 8       # 与 sample_cards.py 保持一致
ENUM_CARD_MAX = 20
PROFILE_ROWS = 200


def run_guancli(args, timeout=120):
    r = subprocess.run(["guancli"] + args, capture_output=True, text=True, timeout=timeout)
    return r.returncode, r.stdout, r.stderr


def bi_base_url():
    code, out, _ = run_guancli(["auth", "status"], timeout=30)
    m = re.search(r'^URL:\s*(\S+)', out, re.M)
    return m.group(1).rstrip('/') if m else ""


def fetch_ds(ds_id):
    """ds get --raw --brief → (data, err)。轻量且含 columns + virtualColumns"""
    code, out, err = run_guancli(["ds", "get", ds_id, "--raw", "--brief"], timeout=60)
    if code != 0:
        return None, (err or out)[:150]
    try:
        raw = json.loads(out)
    except json.JSONDecodeError:
        return None, "RAW_NOT_JSON"
    data = raw.get("data") or raw
    if not isinstance(data, dict) or "columns" not in data:
        return None, "RAW_SCHEMA_MISMATCH"
    return data, None


def preview_ds(ds_id, max_rows):
    """ds preview -f json → (rows, err)。失败不阻断（降级为无画像，字段清单仍在）"""
    code, out, err = run_guancli(["ds", "preview", ds_id, "-f", "json"], timeout=120)
    if code != 0:
        return None, (err or out)[:150]
    try:
        rows = json.loads(out)
    except json.JSONDecodeError:
        return None, "非 JSON 输出"
    if isinstance(rows, dict):
        rows = rows.get("response") or rows.get("data") or []
    return (rows if isinstance(rows, list) else [])[:max_rows], None


def extract_columns(data):
    """物理列 + 计算字段（virtualColumns）合并去重：计算字段补 calcType/formula/aggrType"""
    cols = {}
    for c in data.get("columns") or []:
        if isinstance(c, dict) and c.get("name") and c.get("fdId"):
            cols[c["fdId"]] = {
                "name": c["name"], "fdId": c["fdId"],
                "metaType": c.get("metaType") or "",
                "fdType": c.get("fdType") or c.get("baseFdType") or "",
            }
    for vc in data.get("virtualColumns") or []:
        if not isinstance(vc, dict) or not vc.get("name"):
            continue
        fd_id = vc.get("fdId") or f"vc-{vc['name']}"
        entry = cols.get(fd_id) or {
            "name": vc["name"], "fdId": fd_id,
            "metaType": vc.get("metaType") or "METRIC",
            "fdType": vc.get("fdType") or "",
        }
        if vc.get("calculationType"):
            entry["calcType"] = vc["calculationType"]
        if vc.get("formula"):
            entry["formula"] = vc["formula"]
        if vc.get("aggrType"):
            entry["aggrType"] = vc["aggrType"]
        cols[fd_id] = entry
    return list(cols.values())


def to_num(v):
    """与 sample_cards.py 的列画像实现必须保持一致"""
    if v is None or v == '':
        return None
    try:
        return float(str(v).replace(',', '').replace('%', ''))
    except ValueError:
        return None


def looks_date(v):
    return isinstance(v, str) and re.match(r'^\d{4}[-/]\d{1,2}([-/]\d{1,2})?', v.strip()) is not None


def profile(rows):
    """列画像：类型 / min-max / 枚举值。与 sample_cards.py 的实现必须保持一致"""
    if not rows:
        return {}
    sample = rows[:PROFILE_ROWS]
    cols = list(rows[0].keys())[:30]
    out = {}
    for c in cols:
        vals = [r.get(c) for r in sample if r.get(c) not in (None, '')]
        if not vals:
            out[c] = {"type": "empty"}
            continue
        nums = [to_num(v) for v in vals]
        n_num = sum(1 for x in nums if x is not None)
        if n_num >= len(vals) * 0.9:
            real_nums = [x for x in nums if x is not None]
            out[c] = {"type": "number", "min": min(real_nums), "max": max(real_nums)}
        elif sum(1 for v in vals if looks_date(v)) >= len(vals) * 0.9:
            out[c] = {"type": "date", "min": str(min(vals)), "max": str(max(vals))}
        else:
            uniq = Counter(str(v) for v in vals)
            p = {"type": "text", "distinct": len(uniq)}
            if len(uniq) <= ENUM_CARD_MAX:
                p["enum"] = [v for v, _ in uniq.most_common(ENUM_LIMIT)]
            out[c] = p
    return out


def build_entry(ds_id, data, rows, max_rows):
    """单数据集的 datasets-raw 条目（纯函数，便于单测）"""
    columns = extract_columns(data)
    entry = {
        "dsId": ds_id,
        "mtime": (data.get("utime") or "")[:19],
        "rowCount": data.get("rowCount"),
        "columns": columns,
    }
    if rows is not None:
        entry["sample"] = {
            "rows": data.get("rowCount") or len(rows),
            "sampledRows": len(rows),
            "truncated": bool(data.get("rowCount") and data["rowCount"] > len(rows)) or len(rows) >= max_rows,
            "profile": profile(rows),
        }
    return entry


def learn_one(ds_id, max_rows):
    data, err = fetch_ds(ds_id)
    if err:
        return ds_id, {"error": f"ds get 失败: {err}"}
    rows, perr = preview_ds(ds_id, max_rows)
    name = (data.get("name") or ds_id).strip()
    entry = build_entry(ds_id, data, rows, max_rows)
    if perr:
        entry["sampleError"] = perr
    entry["_name"] = name
    # 与 cards-raw._meta.dsFormulas 同构：check_formulas.py 回退读 datasets-raw 时直接可用
    vcs = [{"fdId": vc.get("fdId", ""), "name": vc["name"],
            "formula": vc.get("formula", ""),
            "calcType": vc.get("calculationType", ""),
            "aggrType": vc.get("aggrType", "")}
           for vc in data.get("virtualColumns") or [] if isinstance(vc, dict) and vc.get("name")]
    return ds_id, {"name": name, "entry": entry, "virtualColumns": vcs}


def main():
    args = sys.argv[1:]
    out, workers, max_rows = '.', 4, DEFAULT_MAX_ROWS
    ds_ids = []
    i = 0
    while i < len(args):
        if args[i] == '-o':
            out = args[i + 1]; i += 2
        elif args[i] == '--workers':
            workers = int(args[i + 1]); i += 2
        elif args[i] == '--max-rows':
            max_rows = int(args[i + 1]); i += 2
        else:
            ds_ids.append(args[i]); i += 1
    if not ds_ids:
        sys.exit("用法: python3 learn_dataset.py <dsId> [dsId2 ...] -o <工作目录> [--workers 4] [--max-rows 200]")
    os.makedirs(out, exist_ok=True)

    learned, failed, ds_formulas = {}, [], {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(learn_one, d, max_rows): d for d in ds_ids}
        for fut in as_completed(futs):
            ds_id = futs[fut]
            r = fut.result()[1]
            if "error" in r:
                print(f"  失败: {ds_id}: {r['error']}")
                failed.append(ds_id)
                continue
            entry = r["entry"]
            n_dim = sum(1 for c in entry["columns"] if c.get("metaType") == "DIM")
            n_vc = len(r["virtualColumns"])
            sample = entry.get("sample") or {}
            print(f"  {r['name']}: {len(entry['columns'])} 列（维度 {n_dim} / 指标 {len(entry['columns']) - n_dim}，"
                  f"计算字段 {n_vc}）" + (f"，采样 {sample.get('sampledRows')} 行" if sample else "，采样失败（已降级）"))
            entry.pop("_name", None)
            learned[r["name"]] = entry
            ds_formulas[ds_id] = {"dsName": r["name"], "virtualColumns": r["virtualColumns"]}
    if not learned:
        sys.exit(f"学习失败: 全部 {len(failed)} 个数据集获取失败（{', '.join(failed)}）——"
                 f"检查数据集权限与 guancli 环境后再试")

    result = dict(learned)
    result["_meta"] = {
        "builtAt": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "builderVersion": BUILDER_VERSION,
        "biBaseUrl": bi_base_url(),
        "mode": "dataset",
        "dsFormulas": ds_formulas,
    }
    out_file = os.path.join(out, 'datasets-raw.json')
    with open(out_file, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    print(f"\n已写入 {out_file}（{len(learned)} 个数据集）")
    print("定位提醒：数据集直通产出的是「数据探索型」助手——能答「数据里有什么」，"
          "答不了「业务上该看什么」；能力边界必须写进交付助手的自我介绍（第 8 步模板变体）")
    if failed:
        print(f"⚠️ {len(failed)} 个数据集获取失败已跳过: {', '.join(failed)}")


if __name__ == '__main__':
    main()
