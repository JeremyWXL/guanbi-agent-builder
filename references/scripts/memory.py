#!/usr/bin/env python3
"""
记忆系统：交付 agent 的长期记忆，形成每个用户独特的上下文。
memory/ 属于用户资产区——builder/脚本升级只替换 references/ 与 SKILL.md，永不写入 memory/。

目录布局（agent目录 = 交付包根目录；传入 references 目录时自动取其父目录）:
  memory/profile.md       用户画像（人读：角色/关注重点/决策习惯/偏好），蒸馏更新，可手改
  memory/qa-log.jsonl     问答流水（append-only 只增不改）
  memory/corrections.json 纠错台账（before→after 历史，references 档案是"现在"，这里是"演变"）
  memory/_meta.json       memorySchema 版本 + 蒸馏计数

用法:
  python3 memory.py init <agent目录>                 初始化 memory/（幂等：已存在的文件不覆盖）
  python3 memory.py log <agent目录> --question "用户原话" [--route "《看板》/卡片"]
      [--fetch card|sql] [--choice "华东=销售大区"] [--note "一句话结论"] [--correction]
  python3 memory.py recall <agent目录> "问题" [--top 3] [--json]   相似历史检索
  python3 memory.py correct <agent目录> --type 口径|维度|取值|其他
      --before "原理解" --after "纠正后" --target metrics.json [--question "触发的问题"]
  python3 memory.py status <agent目录>                 统计 + 蒸馏建议（JSON 输出）
  python3 memory.py distilled <agent目录>              蒸馏完成后重置计数
  python3 memory.py clear <agent目录> --yes            一键清空（先整体备份 memory.bak-<时间戳>/）

读取纪律（写进交付 agent 的 SKILL.md）:
  - 回答前先 recall：命中相似历史则复用路由/消歧结论并向用户声明；标 ⚠️ 的条目
    此后发生过纠错，禁止沿用旧口径，以 references 最新档案为准
  - 画像参与消歧默认值：profile.md 里的用户偏好优先于档案默认（仍需声明）
退出码: 0 正常；1 用法错误；2 数据错误
"""
import json
import os
import re
import shutil
import sys
from datetime import datetime

MEMORY_SCHEMA = 1
DISTILL_THRESHOLD = 20  # 自上次蒸馏起新增流水达到此数即建议蒸馏
RECALL_THRESHOLD = 0.30  # 二分相似度达到此值视为"相似历史"
CORRECTION_TYPES = ("口径", "维度", "取值", "其他")

PROFILE_TEMPLATE = """# 用户画像（记忆）

> 助手在使用中逐步沉淀，经蒸馏更新；可手动编辑。
> 本文件属于用户资产：脚本升级只替换 references/ 与 SKILL.md，不会覆盖本文件。

## 角色与职责
（待沉淀：用户的岗位、负责的业务范围）

## 关注重点
（待沉淀：最常问的指标、看板、维度）

## 决策习惯
（待沉淀：惯用的归因拆法、对比基准、关注的时间粒度）

## 偏好
（待沉淀：输出形式、单位习惯、消歧默认选择）

## 蒸馏记录
- （尚未蒸馏）
"""


def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def memory_dir(agent_dir):
    """agent目录 → memory/ 路径。容忍传入 references 目录（取其父目录）。"""
    d = os.path.abspath(agent_dir)
    if os.path.basename(d) == "references":
        d = os.path.dirname(d)
    return os.path.join(d, "memory")


def paths(agent_dir):
    md = memory_dir(agent_dir)
    return {
        "dir": md,
        "profile": os.path.join(md, "profile.md"),
        "log": os.path.join(md, "qa-log.jsonl"),
        "corrections": os.path.join(md, "corrections.json"),
        "meta": os.path.join(md, "_meta.json"),
    }


def _write_if_absent(path, content):
    if os.path.exists(path):
        return False
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return True


def cmd_init(agent_dir, quiet=False):
    p = paths(agent_dir)
    os.makedirs(p["dir"], exist_ok=True)
    created, kept = [], []
    for key, content in (
        ("profile", PROFILE_TEMPLATE),
        ("log", ""),
        ("corrections", json.dumps({"corrections": []}, ensure_ascii=False, indent=1) + "\n"),
        ("meta", json.dumps({"memorySchema": MEMORY_SCHEMA, "createdAt": now_iso(),
                             "distilledCount": 0}, ensure_ascii=False, indent=1) + "\n"),
    ):
        (created if _write_if_absent(p[key], content) else kept).append(os.path.basename(p[key]))
    if not quiet:
        if created:
            print(f"✅ 记忆已初始化（{p['dir']}）：新建 {'、'.join(created)}")
        if kept:
            print(f"ℹ️ 已存在未覆盖：{'、'.join(kept)}——memory/ 是用户资产，init 永不覆盖")
    return p


def ensure_init(agent_dir):
    """log/correct 等写入动作前兜底初始化，保证记忆永不因目录缺失而写入失败。"""
    return cmd_init(agent_dir, quiet=True)


def read_log(agent_dir):
    """读 qa-log.jsonl，容忍个别坏行（跳过并在结果里标记）。返回 [entry]。"""
    p = paths(agent_dir)
    entries = []
    if not os.path.isfile(p["log"]):
        return entries
    with open(p["log"], encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                entries.append({"_badLine": i, "question": line[:60]})
    return entries


def read_corrections(agent_dir):
    p = paths(agent_dir)
    if not os.path.isfile(p["corrections"]):
        return []
    try:
        with open(p["corrections"], encoding="utf-8") as f:
            return (json.load(f).get("corrections") or [])
    except (json.JSONDecodeError, OSError):
        return []


def read_meta(agent_dir):
    p = paths(agent_dir)
    try:
        with open(p["meta"], encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"memorySchema": MEMORY_SCHEMA, "distilledCount": 0}


def write_meta(agent_dir, meta):
    p = paths(agent_dir)
    with open(p["meta"], "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
        f.write("\n")


# ---------- 相似度（字符二分 Dice，中文无需分词） ----------

def bigrams(s):
    s = re.sub(r"\s+", "", str(s or ""))
    if len(s) < 2:
        return {s} if s else set()
    return {s[i:i + 2] for i in range(len(s) - 1)}


def similarity(a, b):
    A, B = bigrams(a), bigrams(b)
    if not A or not B:
        return 0.0
    return 2 * len(A & B) / (len(A) + len(B))


# ---------- 子命令 ----------

def cmd_log(agent_dir, opts):
    question = opts.get("question")
    if not question:
        sys.exit("用法错误: log 需要 --question \"用户原话\"")
    p = ensure_init(agent_dir)
    choices = {}
    for c in opts.get("choice") or []:
        if "=" not in c:
            sys.exit(f"用法错误: --choice 格式应为「取值=标准维度/标准值」: {c}")
        k, v = c.split("=", 1)
        choices[k.strip()] = v.strip()
    entry = {
        "ts": now_iso(),
        "question": question,
        "route": opts.get("route") or "",
        "fetch": opts.get("fetch") or "",
        "choices": choices,
        "note": opts.get("note") or "",
        "correction": bool(opts.get("correction")),
    }
    with open(p["log"], "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    print(f"✅ 已记入问答流水（第 {len(read_log(agent_dir))} 条）")


def cmd_recall(agent_dir, query, top=3, as_json=False):
    if not query:
        sys.exit("用法错误: recall 需要一个问题文本")
    entries = [e for e in read_log(agent_dir) if "_badLine" not in e]
    corrections = read_corrections(agent_dir)
    scored = []
    for e in entries:
        s = similarity(query, e.get("question", ""))
        if s >= RECALL_THRESHOLD:
            scored.append((s, e))
    scored.sort(key=lambda x: x[0], reverse=True)
    hits = []
    for s, e in scored[:top]:
        # 纠错失效标注：该问答与此后某次纠错高度相关 → 旧结论禁止沿用
        stale_by = None
        for c in corrections:
            ref = " ".join(x for x in (c.get("question"), c.get("before")) if x)
            if ref and similarity(e.get("question", ""), ref) >= RECALL_THRESHOLD \
                    and c.get("ts", "") >= e.get("ts", ""):
                stale_by = c
                break
        hits.append({
            "similarity": round(s, 3),
            "ts": e.get("ts", ""),
            "question": e.get("question", ""),
            "route": e.get("route", ""),
            "choices": e.get("choices") or {},
            "note": e.get("note", ""),
            "stale": stale_by is not None,
            "staleReason": (f"此后有{stale_by.get('type', '')}纠错：{stale_by.get('before', '')} → "
                            f"{stale_by.get('after', '')}（以 references 最新档案为准）") if stale_by else "",
        })
    if as_json:
        print(json.dumps({"query": query, "threshold": RECALL_THRESHOLD,
                          "hits": hits}, ensure_ascii=False, indent=1))
        return
    if not hits:
        print(f"未找到相似历史问题（阈值 {RECALL_THRESHOLD}）——按正常流程回答即可")
        return
    print(f"找到 {len(hits)} 条相似历史（相似度 ≥ {RECALL_THRESHOLD}）：")
    for h in hits:
        print(f"  {'⚠️' if h['stale'] else '•'} [{h['similarity']:.2f}] {h['ts'][:16]} 「{h['question']}」")
        if h["route"]:
            print(f"      当时路由: {h['route']}")
        if h["choices"]:
            print(f"      消歧结论: " + "、".join(f"{k}={v}" for k, v in h["choices"].items()))
        if h["note"]:
            print(f"      结论: {h['note']}")
        if h["stale"]:
            print(f"      ⚠️ {h['staleReason']}")
    print("命中则复用路由与消歧结论并向用户声明（\"上次按 XX 答过，这次沿用\"）；⚠️ 条目禁止沿用旧口径")


def cmd_correct(agent_dir, opts):
    ctype = opts.get("type")
    if ctype not in CORRECTION_TYPES:
        sys.exit(f"用法错误: --type 须为 {'/'.join(CORRECTION_TYPES)}")
    before, after = opts.get("before"), opts.get("after")
    if not before or not after:
        sys.exit("用法错误: correct 需要 --before 与 --after")
    p = ensure_init(agent_dir)
    corrections = read_corrections(agent_dir)
    corrections.append({
        "ts": now_iso(),
        "type": ctype,
        "question": opts.get("question") or "",
        "before": before,
        "after": after,
        "target": opts.get("target") or "",
    })
    with open(p["corrections"], "w", encoding="utf-8") as f:
        json.dump({"corrections": corrections}, f, ensure_ascii=False, indent=1)
        f.write("\n")
    print(f"✅ 纠错台账已记录（第 {len(corrections)} 条）：{before} → {after}。"
          f"别忘了同步写回 references 档案并过校验闸门")


def cmd_status(agent_dir):
    p = paths(agent_dir)
    if not os.path.isdir(p["dir"]):
        print(json.dumps({"initialized": False,
                          "hint": "memory/ 尚未初始化，运行 memory.py init"}, ensure_ascii=False))
        return
    log_count = len(read_log(agent_dir))
    meta = read_meta(agent_dir)
    distilled = meta.get("distilledCount", 0)
    pending = max(0, log_count - distilled)
    profile_mtime = ""
    try:
        profile_mtime = datetime.fromtimestamp(
            os.path.getmtime(p["profile"])).astimezone().isoformat(timespec="seconds")
    except OSError:
        pass
    print(json.dumps({
        "initialized": True,
        "memorySchema": meta.get("memorySchema", MEMORY_SCHEMA),
        "logCount": log_count,
        "correctionCount": len(read_corrections(agent_dir)),
        "distilledCount": distilled,
        "pendingDistill": pending,
        "suggestDistill": pending >= DISTILL_THRESHOLD,
        "distillThreshold": DISTILL_THRESHOLD,
        "profileUpdatedAt": profile_mtime,
        "hint": ("建议蒸馏：通读 qa-log 归纳进 profile.md（角色/关注重点/决策习惯/偏好），"
                 "向用户亮摘要后运行 memory.py distilled 重置计数"
                 if pending >= DISTILL_THRESHOLD else ""),
    }, ensure_ascii=False, indent=1))


def cmd_distilled(agent_dir):
    p = paths(agent_dir)
    if not os.path.isdir(p["dir"]):
        sys.exit("❌ memory/ 尚未初始化")
    meta = read_meta(agent_dir)
    meta["distilledCount"] = len(read_log(agent_dir))
    meta["lastDistillAt"] = now_iso()
    write_meta(agent_dir, meta)
    print(f"✅ 蒸馏计数已重置（distilledCount={meta['distilledCount']}）")


def cmd_clear(agent_dir, yes):
    if not yes:
        sys.exit("❌ 清空记忆是不可逆操作，确认用户明确说「忘掉过去」后加 --yes 执行")
    p = paths(agent_dir)
    if not os.path.isdir(p["dir"]):
        print("ℹ️ memory/ 不存在，无需清空")
        return
    backup = os.path.join(os.path.dirname(p["dir"]),
                          f"memory.bak-{datetime.now().strftime('%Y%m%d-%H%M%S')}")
    shutil.move(p["dir"], backup)
    cmd_init(agent_dir, quiet=True)
    print(f"✅ 记忆已清空并重新初始化；旧记忆备份于 {backup}（确认无误后可手动删除）")


# ---------- 参数解析 ----------

def parse_opts(args, valued, flags):
    opts = {}
    i = 0
    while i < len(args):
        a = args[i]
        if a in valued:
            if i + 1 >= len(args):
                sys.exit(f"用法错误: {a} 缺少数值")
            key = a.lstrip("-")
            if key in ("choice",):
                opts.setdefault(key, []).append(args[i + 1])
            else:
                opts[key] = args[i + 1]
            i += 2
        elif a in flags:
            opts[a.lstrip("-")] = True
            i += 1
        else:
            sys.exit(f"用法错误: 未知参数 {a}")
    return opts


USAGE = __doc__


def main():
    args = sys.argv[1:]
    if len(args) < 2:
        sys.exit(USAGE)
    cmd, rest = args[0], args[1:]
    agent_dir = rest[0]
    tail = rest[1:]
    if cmd == "init":
        cmd_init(agent_dir)
    elif cmd == "log":
        cmd_log(agent_dir, parse_opts(tail,
                {"--question", "--route", "--fetch", "--choice", "--note"},
                {"--correction"}))
    elif cmd == "recall":
        query = None
        top, as_json = 3, False
        pos = []
        i = 0
        while i < len(tail):
            if tail[i] == "--top":
                top = int(tail[i + 1]); i += 2
            elif tail[i] == "--json":
                as_json = True; i += 1
            else:
                pos.append(tail[i]); i += 1
        query = pos[0] if pos else None
        cmd_recall(agent_dir, query, top, as_json)
    elif cmd == "correct":
        cmd_correct(agent_dir, parse_opts(tail,
                    {"--type", "--before", "--after", "--target", "--question"}, set()))
    elif cmd == "status":
        cmd_status(agent_dir)
    elif cmd == "distilled":
        cmd_distilled(agent_dir)
    elif cmd == "clear":
        cmd_clear(agent_dir, "--yes" in tail)
    else:
        sys.exit(USAGE)


if __name__ == "__main__":
    main()
