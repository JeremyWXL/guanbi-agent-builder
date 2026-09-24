#!/usr/bin/env python3
"""
卡片批量采样器：对 cards-raw.json 中的数据卡片逐一 preview 采样
用法: python3 sample_cards.py <cards-raw.json> <输出目录>
输出: <输出目录>/<看板名>__<卡片名>.json（原始数据行）+ <输出目录>/_sample_index.json（采样摘要）
"""
import json, subprocess, sys, os, re

SKIP_TYPES = {'SELECTOR', 'TEXT', 'PROGRESS_BAR'}

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

def main():
    cards_file, out_dir = sys.argv[1], sys.argv[2]
    os.makedirs(out_dir, exist_ok=True)
    with open(cards_file, encoding='utf-8') as f:
        pages = json.load(f)
    index = {}
    for page_name, info in pages.items():
        for card in info['cards']:
            if card['type'] in SKIP_TYPES:
                continue
            key = f"{page_name}__{safe_name(card['name'])}"
            print(f"采样: {card['name']} ({card['cdId']}) ...", flush=True)
            data, err = preview(card['cdId'])
            if err:
                index[key] = {"cdId": card["cdId"], "type": card["type"], "error": err}
                print(f"  失败: {err[:80]}")
                continue
            rows = data if isinstance(data, list) else []
            with open(os.path.join(out_dir, f"{key}.json"), 'w', encoding='utf-8') as f:
                json.dump(rows, f, ensure_ascii=False, indent=1)
            cols = list(rows[0].keys()) if rows else []
            index[key] = {
                "cdId": card["cdId"], "type": card["type"],
                "rows": len(rows), "cols": len(cols), "columns": cols[:20],
                "inPool": card.get("inPool", False),
                "filters": card.get("filters", []),
            }
            print(f"  -> {len(rows)} 行 x {len(cols)} 列")
    with open(os.path.join(out_dir, '_sample_index.json'), 'w', encoding='utf-8') as f:
        json.dump(index, f, ensure_ascii=False, indent=1)
    ok = sum(1 for v in index.values() if 'error' not in v)
    print(f"\n完成: {ok}/{len(index)} 张采样成功 -> {out_dir}/_sample_index.json")

if __name__ == '__main__':
    main()
