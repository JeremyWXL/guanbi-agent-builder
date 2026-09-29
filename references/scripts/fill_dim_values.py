#!/usr/bin/env python3
"""
维度成员值机械回填：从 card-data/_sample_index.json 列画像（+ datasets-raw.json 内嵌
sample.profile）把枚举值补进维度档案的空 values——取值消歧的原料来自采样数据本身，
禁止模型手工誊写（誊写 = 漏值/错值/编造；实机 review 案例：17 个维度 values 全空，
而采样画像里枚举值齐全——种子转出成稿时被手工转写丢失）。
用法:
  python3 fill_dim_values.py <工作目录>          # 采样画像回填：只补空 values，已确认值不动
  python3 fill_dim_values.py <工作目录> --full   # 全量枚举回填：经同目录 run_sql.py（只读执行器）
                                                 # 对每个匹配到数据集物理字段的维度 SELECT DISTINCT
                                                 # 取全量枚举，与现有 values 并集（去重保序，
                                                 # 已有值可能是用户确认的，绝不删除）
规则:
  - 只补 values 为空的维度；已有值视为用户确认结果，绝不改动（--full 只做并集，同样不删）
  - 列名与维度 name/field 精确匹配才采信（禁止模糊匹配带错值）
  - 单维度上限 60 个（与 check_dims 种子 VALUE_CAP 一致）；去重保序
  - dimensions.json 缺失时回填 dimensions-seed.json；都没有 → exit 2
  - 写回前自动备份 <档案>.bak-fill-<时间戳>
  - 补完提示重跑 check_dims.py（值跨维度重叠/相似值告警以最新 values 重新计算）
--full 补充规则:
  - 数据集来源：直通模式取 datasets-raw.json 的 dsId + 字段清单；看板模式取 cards.json 的
    dsUsage + 采样列名匹配（列名命中 card-data/_sample_index.json 才发 SQL）；
    dsId 越出 scope 白名单（工作目录 cards.json/datasets.json 派生）时不查
  - 只匹配 DIM 物理字段；日期/时间型字段不枚举（values 是取值消歧候选池，日期走时间解析）
  - 全量枚举超过 60 个的维度不塞爆 values，改写 note：
    "取值未全量枚举（实际 N 个），消歧前先 SQL 枚举确认"（N 取自 COUNT(DISTINCT)）
  - run_sql.py 缺失或查询失败 → ⚠️ 降级跳过，不阻断（采样画像回填仍生效）
退出码: 0 正常（含无需回填/降级）/ 2 档案缺失或无法解析
"""
import json, os, subprocess, sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import scope as scope_mod
except ImportError:
    scope_mod = None  # scope.py 不在同目录时降级跳过白名单过滤（与 run_sql 同策略）

VALUE_CAP = 60
RUN_SQL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "run_sql.py")
DATE_TYPES = {"DATE", "DATETIME", "TIMESTAMP", "TIME"}  # 不做成员枚举的字段类型


def load(workdir, fn):
    fp = os.path.join(workdir, fn)
    if not os.path.exists(fp):
        return None
    with open(fp, encoding="utf-8") as f:
        return json.load(f)


def harvest_enums(workdir):
    """采样画像里的可用枚举：列名 → [值...]（合并所有卡片采样文件，去重保序）"""
    enums = {}
    idx = load(workdir, os.path.join("card-data", "_sample_index.json")) or {}
    for entry in idx.values():
        for col, p in ((entry or {}).get("profile") or {}).items():
            if isinstance(p, dict) and p.get("enum"):
                enums.setdefault(col, [])
                for v in p["enum"]:
                    if v not in enums[col]:
                        enums[col].append(v)
    draw = load(workdir, "datasets-raw.json") or {}
    for k, v in draw.items():
        if k.startswith("_") or not isinstance(v, dict):
            continue
        for col, p in ((v.get("sample") or {}).get("profile") or {}).items():
            if isinstance(p, dict) and p.get("enum"):
                enums.setdefault(col, [])
                for val in p["enum"]:
                    if val not in enums[col]:
                        enums[col].append(val)
    return enums


def write_back(workdir, target, doc):
    """备份并写回维度档案，返回备份文件路径"""
    fp = os.path.join(workdir, target)
    bak = f"{fp}.bak-fill-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    with open(fp, encoding="utf-8") as f:
        before = f.read()
    with open(bak, "w", encoding="utf-8") as f:
        f.write(before)
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
        f.write("\n")
    return bak


def sql_rows(ds_id, sql):
    """经 run_sql.py 执行只读查询并解析 JSON 行集；run_sql 不可用/失败/输出非 JSON
    返回 None（⚠️ 降级，不阻断）"""
    try:
        r = subprocess.run([sys.executable, RUN_SQL, ds_id, sql, "-f", "json"],
                           capture_output=True, text=True, timeout=240)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    try:
        rows = json.loads(r.stdout)
    except json.JSONDecodeError:
        return None
    return rows if isinstance(rows, list) else None


def full_targets(workdir, name, field, scope_ids):
    """维度的全量枚举目标清单 [(dsId, 数据集名, 物理列)]（匹配不上返回 []）。
    直通模式：dsId + 字段清单取自 datasets-raw.json（只匹配 DIM 物理字段，日期型不枚举）；
    看板模式：dsId 取自 cards.json 里引用该维度的卡片（∩ dsUsage 白名单），
    列名须命中采样列名（card-data/_sample_index.json）才发 SQL。
    scope_ids 非 None 时按白名单过滤（越界数据集不查）。"""
    targets = []
    draw = load(workdir, "datasets-raw.json") or {}
    if any(not k.startswith("_") for k in draw):
        formulas = ((draw.get("_meta") or {}).get("dsFormulas") or {})
        for k, v in draw.items():
            if k.startswith("_") or not isinstance(v, dict):
                continue
            ds_id = v.get("dsId") or ""
            if not ds_id or (scope_ids is not None and ds_id not in scope_ids):
                continue
            ds_name = (formulas.get(ds_id) or {}).get("dsName") or k
            cols = {c.get("name"): c for c in v.get("columns") or [] if isinstance(c, dict)}
            for col in (field, name):  # field 优先，默认同 name
                c = cols.get(col)
                if c is None or c.get("metaType", "DIM") != "DIM":
                    continue
                if (c.get("fdType") or "").upper() in DATE_TYPES:
                    continue
                targets.append((ds_id, ds_name, col))
                break
        return targets
    cards = load(workdir, "cards.json") or load(workdir, "cards-merged.json") or {}
    formulas = ((cards.get("_meta") or {}).get("dsFormulas") or {})
    sampled = set()
    idx = load(workdir, os.path.join("card-data", "_sample_index.json")) or {}
    for entry in idx.values():
        for col in ((entry or {}).get("profile") or {}):
            sampled.add(col)
    col = field if field in sampled else (name if name in sampled else None)
    if not col:
        return targets
    ds_ids = set()
    for k, v in cards.items():
        if k.startswith("_") or not isinstance(v, dict):
            continue
        usage = set((v.get("dsUsage") or {}).keys())
        for c in v.get("cards") or []:
            if not isinstance(c, dict):
                continue
            hit = col in (c.get("dims") or []) or any(
                isinstance(fd, dict) and fd.get("field") == col
                for fd in c.get("filterDetails") or [])
            if hit and c.get("dsId") and c["dsId"] in usage:
                ds_ids.add(c["dsId"])
    for ds_id in sorted(ds_ids):
        if scope_ids is not None and ds_id not in scope_ids:
            continue
        ds_name = (formulas.get(ds_id) or {}).get("dsName")
        if ds_name:  # 没有数据集名拼不出 FROM 子句，跳过
            targets.append((ds_id, ds_name, col))
    return targets


def full_fill(workdir, dims):
    """--full 全量枚举回填：逐维度找数据集物理字段目标，先 COUNT(DISTINCT) 预检上限，
    未超限才 SELECT DISTINCT 并入 values（并集去重保序，已有值绝不删除）。
    返回 (merged, overcaps, unmatched, degraded, changed)——overcaps 是超上限告警清单
    （note 已写过的不重复改），changed 标记本轮是否真的改动了档案（幂等：零改动不写回不备份）。"""
    scope_ids = None
    if scope_mod is not None:
        sc = scope_mod.load_scope(candidates=[os.path.join(workdir, "cards.json"),
                                              os.path.join(workdir, "cards-merged.json"),
                                              os.path.join(workdir, "datasets.json")])
        if sc is not None:
            scope_ids = sc["dsIds"]
    merged, overcaps, unmatched, degraded = [], [], [], []
    changed = False
    for d in dims:
        if not isinstance(d, dict):
            continue
        name = (d.get("name") or "").strip()
        if not name:
            continue
        field = (d.get("field") or "").strip() or name
        targets = full_targets(workdir, name, field, scope_ids)
        if not targets:
            unmatched.append(name)
            continue
        existing = list(d.get("values") or [])
        values = list(existing)
        cap = max(VALUE_CAP, len(existing))  # 已有值可能是用户确认的，上限只挡新增不删旧值
        added, over, capped = 0, None, False
        for ds_id, ds_name, col in targets:
            rows = sql_rows(ds_id, f"SELECT COUNT(DISTINCT `{col}`) AS n FROM `{ds_name}`")
            if not rows or not isinstance(rows[0], dict) or not rows[0]:
                degraded.append((name, ds_id))
                continue
            try:
                n = int(float(str(next(iter(rows[0].values())))))
            except (TypeError, ValueError):
                degraded.append((name, ds_id))
                continue
            if n > VALUE_CAP:
                over = over or f"实际 {n} 个"
                continue
            rows = sql_rows(ds_id, f"SELECT DISTINCT `{col}` FROM `{ds_name}` ORDER BY `{col}`")
            if rows is None:
                degraded.append((name, ds_id))
                continue
            for r in rows:
                if not isinstance(r, dict) or not r:
                    continue
                v = next(iter(r.values()))
                if v is None or v in values:
                    continue
                if len(values) >= cap:
                    capped = True  # 多数据集并集超上限：截断并写 note
                    continue
                values.append(v)
                added += 1
        if capped and over is None:
            over = f"实际超过 {VALUE_CAP} 个"
        if over is not None:
            note = f"取值未全量枚举（{over}），消歧前先 SQL 枚举确认"
            old = (d.get("note") or "").strip()
            if note not in old:
                d["note"] = f"{old}；{note}" if old else note
                changed = True
            overcaps.append((name, over))
        if values != existing:
            d["values"] = values
            changed = True
            merged.append((name, added, len(values)))
    return merged, overcaps, unmatched, degraded, changed


def main():
    args = [a for a in sys.argv[1:] if a != "--full"]
    full = len(args) != len(sys.argv) - 1
    workdir = args[0] if args else "."
    target = "dimensions.json"
    doc = load(workdir, target)
    if doc is None:
        target = "dimensions-seed.json"
        doc = load(workdir, target)
    if doc is None:
        print(f"❌ 找不到 {workdir}/dimensions.json 或 dimensions-seed.json——"
              "先运行 check_dims.py --seed-dims 生成种子", file=sys.stderr)
        sys.exit(2)
    dims = doc.get("dimensions")
    if not isinstance(dims, list):
        print(f"❌ {target} 结构错误：顶层 dimensions 必须是数组", file=sys.stderr)
        sys.exit(2)

    enums = harvest_enums(workdir)
    if not enums and not full:
        print("⚠️ 采样画像里没有可用枚举值（card-data/_sample_index.json 与 datasets-raw.json 均无）"
              "——先完成第 2 步采样，或从取数结果人工补充")
        sys.exit(0)

    filled, skipped_has_values, no_match = [], [], []
    for d in dims:
        if not isinstance(d, dict):
            continue
        name = (d.get("name") or "").strip()
        if d.get("values"):
            skipped_has_values.append(name)
            continue
        src = enums.get(name) or enums.get((d.get("field") or "").strip())
        if src:
            d["values"] = src[:VALUE_CAP]
            filled.append((name, len(d["values"])))
        else:
            no_match.append(name)

    if not full:
        if filled:
            bak = write_back(workdir, target, doc)
            print(f"✅ 已从采样画像机械回填 {len(filled)} 个维度的成员值（备份 {os.path.basename(bak)}）：")
            for name, n in filled:
                print(f"   「{name}」← {n} 个值")
        else:
            print("无需回填：没有 values 为空且画像可匹配的维度")
        if skipped_has_values:
            print(f"不动已确认值：{'、'.join(skipped_has_values[:10])}"
                  f"{'…' if len(skipped_has_values) > 10 else ''}")
        if no_match:
            print(f"⚠️ 画像中无对应枚举列（取值多为高基数或未被采样命中，可从取数结果补）:"
                  f"{'、'.join(no_match[:10])}{'…' if len(no_match) > 10 else ''}")
        if filled:
            print("请重跑 check_dims.py 校验（值跨维度重叠/相似值告警按最新 values 重算）")
        return

    # ---- --full：经 run_sql.py 全量枚举，与现有 values 并集（不删已有值）----
    merged, overcaps, unmatched, degraded, full_changed = [], [], [], [], False
    if not os.path.exists(RUN_SQL):
        print("⚠️ 未找到同目录 run_sql.py——--full 降级为仅采样画像回填")
    else:
        merged, overcaps, unmatched, degraded, full_changed = full_fill(workdir, dims)

    if filled or full_changed:
        bak = write_back(workdir, target, doc)
        print(f"已备份 {os.path.basename(bak)}")
    if filled:
        print(f"✅ 已从采样画像机械回填 {len(filled)} 个维度的成员值：")
        for name, n in filled:
            print(f"   「{name}」← {n} 个值")
    if merged:
        print("✅ 全量枚举并集回填（经 run_sql.py 只读执行器；已有值一律保留，去重保序）：")
        for name, added, total in merged:
            print(f"   「{name}」+{added} 个新值（共 {total} 个）")
    for name, over in overcaps:
        print(f"⚠️ 「{name}」取值未全量枚举（{over}）——超过单维度上限 {VALUE_CAP} 个，"
              "不塞爆 values，note 已标注「消歧前先 SQL 枚举确认」")
    if not (filled or full_changed):
        print("无需回填：没有可补充的成员值")
    if unmatched:
        print(f"⚠️ 未匹配到可枚举的数据集物理字段（DIM 且非日期型），跳过全量回填：{'、'.join(unmatched[:10])}"
              f"{'…' if len(unmatched) > 10 else ''}")
    if degraded:
        hit = sorted({f"{n}({ds})" for n, ds in degraded})
        print(f"⚠️ run_sql 查询失败已降级跳过（values 保持原样，不阻断）：{'、'.join(hit[:10])}"
              f"{'…' if len(hit) > 10 else ''}")
    if filled or full_changed:
        print("请重跑 check_dims.py 校验（值跨维度重叠/相似值告警按最新 values 重算）")


if __name__ == "__main__":
    main()
