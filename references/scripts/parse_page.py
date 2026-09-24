#!/usr/bin/env python3
"""
看板结构解析器：guancli page get → 卡片清单（名称/ID/类型/筛选器）
关键：按 Card 块内联的 **ID:** 解析，禁止跨块顺序配对（brief 输出中 SELECTOR 交错会错位）
用法: python3 parse_page.py <pageId> [pageId2 ...] -o <输出目录>
输出: <输出目录>/cards-raw.json  （{看板名: {pgId, cards: [{name, cdId, type, filters}]}}）
"""
import json, re, subprocess, sys, os

def parse_page(page_id):
    r = subprocess.run(["guancli", "page", "get", page_id],
                       capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        return {"error": r.stderr[:300], "pgId": page_id}
    text = r.stdout
    m = re.search(r'^页面标题: (.+)$', text, re.M)
    title = m.group(1).strip() if m else page_id
    mm = re.search(r'^更新时间: (.+)$', text, re.M)
    mtime = mm.group(1).strip() if mm else ""
    cards = []
    # 按 Card 块切分，名称与 ID 必须取自同一块内
    blocks = re.split(r'(?=^# Card )', text, flags=re.M)
    for b in blocks:
        m1 = re.match(r'# Card \d+(?:\s*\[卡片池\])?: (.+)', b)
        m2 = re.search(r'\*\*ID:\*\* (\w+)', b)
        m3 = re.search(r'\*\*Type:\*\* (\w+)', b)
        if not (m1 and m2):
            continue
        name = m1.group(1).strip()
        filters = re.findall(r'- 筛选器名称: (.+)', b)
        cards.append({
            "name": name,
            "cdId": m2.group(1),
            "type": m3.group(1) if m3 else "UNKNOWN",
            "inPool": "[卡片池]" in b.split('\n')[0],
            "filters": [f.strip() for f in filters],
        })
    return {"title": title, "pgId": page_id, "mtime": mtime, "cards": cards}

def bi_base_url():
    r = subprocess.run(["guancli", "auth", "status"],
                       capture_output=True, text=True, timeout=30)
    m = re.search(r'^URL:\s*(\S+)', r.stdout, re.M)
    return m.group(1).rstrip('/') if m else ""

def main():
    args = sys.argv[1:]
    out = '.'
    page_ids = []
    i = 0
    while i < len(args):
        if args[i] == '-o':
            out = args[i + 1]
            i += 2
        else:
            page_ids.append(args[i])
            i += 1
    os.makedirs(out, exist_ok=True)
    result = {}
    for pid in page_ids:
        print(f"解析看板 {pid} ...", flush=True)
        info = parse_page(pid)
        if "error" in info:
            print(f"  失败: {info['error']}")
            continue
        n_data = sum(1 for c in info['cards'] if c['type'] not in ('SELECTOR', 'TEXT'))
        print(f"  {info['title']}: {len(info['cards'])} 张卡片（数据卡 {n_data}，筛选器/文本 {len(info['cards'])-n_data}）")
        result[info['title']] = info
    # 学习时点元数据：供交付后体检（看板是否在 agent 学习后被改过）
    result["_meta"] = {
        "builtAt": __import__('datetime').datetime.now().strftime("%Y-%m-%d %H:%M"),
        "biBaseUrl": bi_base_url(),
        "pages": {v["pgId"]: {"title": k, "mtime": v.get("mtime", "")}
                  for k, v in result.items() if isinstance(v, dict) and "pgId" in v},
    }
    out_file = os.path.join(out, 'cards-raw.json')
    with open(out_file, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    print(f"\n已写入 {out_file}")

if __name__ == '__main__':
    main()
