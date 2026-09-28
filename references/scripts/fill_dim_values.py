#!/usr/bin/env python3
"""
维度成员值机械回填：从 card-data/_sample_index.json 列画像（+ datasets-raw.json 内嵌
sample.profile）把枚举值补进维度档案的空 values——取值消歧的原料来自采样数据本身，
禁止模型手工誊写（誊写 = 漏值/错值/编造；实机 review 案例：17 个维度 values 全空，
而采样画像里枚举值齐全——种子转出成稿时被手工转写丢失）。
用法:
  python3 fill_dim_values.py <工作目录>     # 搭建工作目录或交付包 references/（同构布局）
规则:
  - 只补 values 为空的维度；已有值视为用户确认结果，绝不改动
  - 列名与维度 name/field 精确匹配才采信（禁止模糊匹配带错值）
  - 单维度上限 60 个（与 check_dims 种子 VALUE_CAP 一致）；去重保序
  - dimensions.json 缺失时回填 dimensions-seed.json；都没有 → exit 2
  - 写回前自动备份 <档案>.bak-fill-<时间戳>
  - 补完提示重跑 check_dims.py（值跨维度重叠/相似值告警以最新 values 重新计算）
退出码: 0 正常（含无需回填）/ 2 档案缺失或无法解析
"""
import json, os, sys
from datetime import datetime

VALUE_CAP = 60


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


def main():
    workdir = sys.argv[1] if len(sys.argv) > 1 else "."
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
    if not enums:
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

    if filled:
        fp = os.path.join(workdir, target)
        bak = f"{fp}.bak-fill-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        with open(fp, encoding="utf-8") as f:
            before = f.read()
        with open(bak, "w", encoding="utf-8") as f:
            f.write(before)
        with open(fp, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=1)
            f.write("\n")
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


if __name__ == "__main__":
    main()
