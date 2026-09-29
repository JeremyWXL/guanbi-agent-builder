#!/usr/bin/env python3
"""
卡片批量采样器：对 cards-raw.json 中的数据卡片逐一 preview 采样
用法: python3 sample_cards.py <cards-raw.json> <输出目录> [--max-rows N] [--only-cdIds <文件>] [--prune-keys <文件>] [--scope <cards.json>]
  --only-cdIds  增量学习用：只采样文件里列出的 cdId（每行一个或 JSON 列表），其余卡片跳过——
                 未变的卡片沿用旧采样，不重复消耗取数
  --prune-keys  增量学习用：删除输出目录里列出的采样文件（key 列表，不含 .json 后缀）——
                 被删/改名卡片的旧采样文件是孤儿，防止陈旧数据被误当现状引用
  --scope       范围守卫：待采卡片的 cdId 必须 ∈ 指定 cards.json 的白名单，越界整批拒绝（exit 2）
输出:
  <输出目录>/<看板名>__<卡片名>__<cdId>.json（数据行，超过 --max-rows 截断并标注）
  <输出目录>/_sample_index.json（采样摘要 + 列画像 profiling）
说明:
  - 自动跳过 "_meta" 等非看板键
  - 文件名以 cdId 结尾：卡片名经非法字符归一化/截断后可能碰撞（如「收入/本月」与「收入:本月」），
    cdId 保证唯一；同一 key 仍重复出现（同 cdId 被列两次）即整批拒绝（exit 2），禁止静默覆盖
  - 默认最多落盘 200 行/卡（防止大卡片撑爆上下文）；原始行数记入 _sample_index.json
  - profiling：每列推断类型（number/text/date）、数值列给 min/max、
    低基数文本列给枚举值（防取值幻觉，供筛选器取值参考）
"""
import json, subprocess, sys, os, re
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import scope as scope_mod
except ImportError:
    scope_mod = None  # scope.py 未随包复制时降级：--scope 白名单校验不可用，采样主功能不受影响

SKIP_TYPES = {'SELECTOR', 'TEXT', 'PROGRESS_BAR', 'PICTURE', 'LAYOUT'}
DEFAULT_MAX_ROWS = 200
ENUM_LIMIT = 8       # 枚举值最多列几个
ENUM_CARD_MAX = 20   # 唯一值超过该数不视为枚举列
PROFILE_ROWS = 200   # profiling 最多扫描的行数


def safe_name(s):
    return re.sub(r'[\\/:*?"<>|\s]+', '_', s)[:60]


def preview(cd_id):
    r = subprocess.run(["guancli", "card", "preview", cd_id, "-f", "json"],
                       capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        return None, r.stderr[:300]
    try:
        d = json.loads(r.stdout)
        if isinstance(d, dict):
            d = d.get("response", d)
        return d, None
    except json.JSONDecodeError:
        return None, "非 JSON 输出"


def to_num(v):
    if v is None or v == '':
        return None
    try:
        return float(str(v).replace(',', '').replace('%', ''))
    except ValueError:
        return None


def looks_date(v):
    return isinstance(v, str) and re.match(r'^\d{4}[-/]\d{1,2}([-/]\d{1,2})?', v.strip()) is not None


def profile(rows):
    """列画像：类型 / min-max / 枚举值。只扫前 PROFILE_ROWS 行。"""
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


def main():
    args = sys.argv[1:]
    max_rows = DEFAULT_MAX_ROWS
    if "--max-rows" in args:
        i = args.index("--max-rows")
        max_rows = int(args[i + 1])
        args = args[:i] + args[i + 2:]
    only_ids, prune_keys = None, []
    scope_path = None
    for flag, dest in (("--only-cdIds", "only"), ("--prune-keys", "prune"), ("--scope", "scope")):
        if flag in args:
            i = args.index(flag)
            path = args[i + 1]
            args = args[:i] + args[i + 2:]
            if dest == "scope":
                scope_path = path
            else:
                with open(path, encoding='utf-8') as f:
                    content = f.read().strip()
                try:
                    values = json.loads(content)
                except json.JSONDecodeError:
                    values = [ln.strip() for ln in content.splitlines() if ln.strip()]
                if dest == "only":
                    only_ids = set(values)
                else:
                    prune_keys = list(values)
    cards_file, out_dir = args[0], args[1]
    os.makedirs(out_dir, exist_ok=True)
    # 范围守卫：--scope 时所有待采卡片的 cdId 必须 ∈ 白名单，越界整批拒绝（exit 2 哨兵）
    scope = None
    if scope_path:
        if scope_mod is not None:
            scope = scope_mod.load_scope(candidates=[scope_path])
        else:
            sys.exit("❌ --scope 要求白名单校验，但 scope.py 缺失——请把 scope.py 复制进 references/ 后重试（exit 2）")
    with open(cards_file, encoding='utf-8') as f:
        pages = json.load(f)
    if scope is not None:
        out_of_scope = sorted({c["cdId"] for info in pages.values()
                               if isinstance(info, dict)
                               for c in (info.get("cards") or [])
                               if isinstance(c, dict) and c.get("cdId") and c["cdId"] not in scope["cdIds"]})
        if out_of_scope:
            print(f"❌ 范围守卫：{len(out_of_scope)} 张卡片不在助手覆盖范围，整批拒绝采样", file=sys.stderr)
            print(f"   越界 cdId: {', '.join(out_of_scope[:10])}" + ("…" if len(out_of_scope) > 10 else ""),
                  file=sys.stderr)
            print("   覆盖范围见 scope 来源 cards.json；如需接入新卡片，回到搭建向导说「增量学习」。",
                  file=sys.stderr)
            sys.exit(2)
        print(f"✅ 范围守卫：全部卡片在覆盖范围内（{len(scope['cdIds'])} 个 cdId 白名单）")
    # 孤儿采样清理：被删/改名卡片的旧 key（增量学习合并后调用）
    for key in prune_keys:
        path = os.path.join(out_dir, f"{key}.json")
        if os.path.exists(path):
            os.unlink(path)
            print(f"  清理孤儿采样: {key}.json")
    with open(cards_file, encoding='utf-8') as f:
        pages = json.load(f)
    # 先展开待采清单并校验文件键唯一：key 含 cdId，重复 = 同一卡片被列两次——
    # 冲突即整批拒绝（exit 2），禁止部分采样后才发现覆盖
    tasks, seen_keys = [], {}
    for page_name, info in pages.items():
        if page_name.startswith('_') or not isinstance(info, dict) or 'cards' not in info:
            continue  # 跳过 _meta 等元数据键
        for card in info['cards']:
            if card['type'] in SKIP_TYPES:
                continue
            if only_ids is not None and card['cdId'] not in only_ids:
                continue  # 增量模式：未变的卡片不重复采样
            key = f"{page_name}__{safe_name(card['name'])}__{card['cdId']}"
            if key in seen_keys:
                print(f"❌ 采样文件键冲突: {key}（同一 cdId 出现多次）——整批拒绝，请检查输入的 cards 清单",
                      file=sys.stderr)
                sys.exit(2)
            seen_keys[key] = card['cdId']
            tasks.append((key, card))
    index = {}
    for key, card in tasks:
        print(f"采样: {card['name']} ({card['cdId']}) ...", flush=True)
        data, err = preview(card['cdId'])
        if err:
            index[key] = {"cdId": card["cdId"], "type": card["type"], "error": err}
            print(f"  失败: {err[:80]}")
            continue
        rows = data if isinstance(data, list) else []
        total_rows = len(rows)
        truncated = total_rows > max_rows
        if truncated:
            rows = rows[:max_rows]
        payload = {"_truncated": True, "_totalRows": total_rows, "rows": rows} if truncated else rows
        with open(os.path.join(out_dir, f"{key}.json"), 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=1)
        cols = list(rows[0].keys()) if rows else []
        index[key] = {
            "cdId": card["cdId"], "type": card["type"],
            "rows": total_rows, "sampledRows": len(rows), "truncated": truncated,
            "cols": len(cols), "columns": cols[:20],
            "inPool": card.get("inPool", False),
            "dsId": card.get("dsId", ""),
            "filters": card.get("filters", []),
            "profile": profile(rows),
        }
        print(f"  -> {total_rows} 行 x {len(cols)} 列" + (f"（截断采样 {max_rows} 行）" if truncated else ""))
    with open(os.path.join(out_dir, '_sample_index.json'), 'w', encoding='utf-8') as f:
        json.dump(index, f, ensure_ascii=False, indent=1)
    ok = sum(1 for v in index.values() if 'error' not in v)
    print(f"\n完成: {ok}/{len(index)} 张采样成功 -> {out_dir}/_sample_index.json")


if __name__ == '__main__':
    main()
