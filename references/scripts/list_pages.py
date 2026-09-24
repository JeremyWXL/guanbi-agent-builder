#!/usr/bin/env python3
"""
看板清单器：guancli page tree → 简洁的目录/仪表板 JSON 清单
供第 1 步"勾选式选看板"使用：只返回当前登录态有权限访问的节点
用法:
  python3 list_pages.py                       # 全部仪表板（扁平列表，含完整路径）
  python3 list_pages.py --dirs                # 目录清单（含每个目录下的仪表板数）
  python3 list_pages.py --dir 根目录/销售分析  # 只看某目录下（含子目录）的仪表板
  python3 list_pages.py --keyword 毛利         # 按名称/路径过滤
  python3 list_pages.py --limit 20            # 限制条数（默认 50）
输出: JSON 数组 [{id, name, path, type, mtime}]；--dirs 时 [{id, name, path, pageCount}]
"""
import json, subprocess, sys


def fetch_tree():
    err = None
    for _ in range(2):
        r = subprocess.run(["guancli", "page", "tree", "--raw"],
                           capture_output=True, text=True, timeout=120)
        if r.returncode == 0:
            try:
                return json.loads(r.stdout)["response"]
            except json.JSONDecodeError:
                err = f"guancli 输出非 JSON: {r.stdout[:300]}"
        else:
            err = f"guancli page tree 失败: {r.stderr[:300]}"
    sys.exit(err)


def flatten(node, path=""):
    """嵌套树 → 扁平列表。目录的 pageCount 统计其全部后代仪表板。"""
    here = f"{path}/{node['name']}" if path else node["name"]
    entries = []
    count = 0
    if node.get("isPage"):
        entries.append({
            "id": node["id"],
            "name": node["name"],
            "path": here,
            "type": "page",
            "mtime": (node.get("ctime") or "")[:10],
        })
        count = 1
    for child in node.get("contents") or []:
        sub, sub_count = flatten(child, here)
        entries.extend(sub)
        count += sub_count
    if not node.get("isPage") and path or node.get("parentDirId"):
        if not node.get("isPage"):
            entries.insert(0, {
                "id": node["id"],
                "name": node["name"],
                "path": here,
                "type": "dir",
                "pageCount": count,
            })
    return entries, count


def main():
    args = sys.argv[1:]
    dirs_only = "--dirs" in args
    dir_prefix, keyword, limit = None, None, 50
    i = 0
    while i < len(args):
        if args[i] == "--dir":
            dir_prefix = args[i + 1]; i += 2
        elif args[i] == "--keyword":
            keyword = args[i + 1]; i += 2
        elif args[i] == "--limit":
            limit = int(args[i + 1]); i += 2
        else:
            i += 1

    entries, _ = flatten(fetch_tree())
    if dirs_only:
        out = [e for e in entries if e["type"] == "dir"]
        for e in out:
            e.pop("type", None)
    else:
        out = [e for e in entries if e["type"] == "page"]
    if dir_prefix:
        p = dir_prefix.rstrip("/")
        out = [e for e in out if e["path"] == p or e["path"].startswith(p + "/")]
    if keyword:
        out = [e for e in out if keyword in e["name"] or keyword in e["path"]]
    out = out[:limit]
    print(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"-- 共 {len(out)} 条" + (f"（已截断，可用 --limit 调整）" if len(out) == limit else ""),
          file=sys.stderr)


if __name__ == "__main__":
    main()
