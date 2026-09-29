#!/usr/bin/env python3
"""
范围守卫白名单提取：从交付包/工作目录的 cards.json（或 datasets.json）提取覆盖范围。
白名单**从档案派生、永不手动维护**——增量学习经 merge_cards.py 合并后自动扩容，
交付包升级替换 cards.json 后白名单同步生效。按 ID 判定（pgId/dsId/cdId），
不看看板名——用户权限大、同名/相似看板多时名字匹配必然误判。

用法（被 run_sql.py / sample_cards.py / scope_audit.py 共享）:
  scope = load_scope()          # 自动按候选路径查找
  if scope and ds_id not in scope["dsIds"]: ...   # 越界拦截

load_scope 返回:
  {"pgIds": {pgId: 看板名},         # _meta.pages（旧档案无则空集，降级不报错）
   "dsIds": {dsId, ...},            # 各页 dsUsage 键（数据集直通模式：datasets.json 条目 dsId）
   "cdIds": {cdId: "页面__卡片"},   # 各页 cards（sample_cards --scope 用）
   "metricIds": {metricId, ...},    # 同目录 metrics.json 各条目 governedRef.metricId
                                    # （指标中心口径引用白名单，run_metric.py 用；
                                    #   旧档案无 metrics.json / 无 governedRef → 空集，降级不报错）
   "titles": [看板名, ...],         # 超范围话术列举已学看板用
   "source": 路径}
找不到 scope 文件返回 None——调用方降级跳过校验（脱离交付包单独运行不阻断）。
"""
import json, os

# 候选路径（顺序优先）：搭建工作目录（scripts/ 下）→ 交付包 references/ → 增量会话 → 数据集直通
DEFAULT_CANDIDATES = (
    os.path.join("{here}", "..", "cards.json"),
    os.path.join("{here}", "cards.json"),
    os.path.join("{here}", "..", "cards-merged.json"),
    os.path.join("{here}", "datasets.json"),
    os.path.join("{here}", "..", "datasets.json"),
)


def _find_scope_file(candidates):
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


def _load_metric_ids(scope_dir):
    """从 scope 文件同目录的 metrics.json 提取指标中心引用白名单（governedRef.metricId）。
    文件缺失/解析失败/条目无 governedRef → 空集，不报错（多数指标没有引用，正常）。"""
    fp = os.path.join(scope_dir, "metrics.json")
    ids = set()
    if not os.path.exists(fp):
        return ids
    try:
        with open(fp, encoding="utf-8") as f:
            doc = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        return ids
    for m in doc.get("metrics") or []:
        if not isinstance(m, dict):
            continue
        ref = m.get("governedRef")
        if isinstance(ref, dict) and ref.get("metricId"):
            ids.add(ref["metricId"])
    return ids


def load_scope(candidates=None):
    """提取白名单。candidates 为路径列表（{here} 占位符自动替换为脚本所在目录）；
    默认按 DEFAULT_CANDIDATES 查找。找不到返回 None。"""
    here = os.path.dirname(os.path.abspath(__file__))
    if candidates is None:
        candidates = [p.format(here=here) for p in DEFAULT_CANDIDATES]
    path = _find_scope_file(candidates)
    if path is None:
        return None
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    scope = {"pgIds": {}, "dsIds": set(), "cdIds": {}, "metricIds": set(),
             "titles": [], "source": path}
    scope["metricIds"] = _load_metric_ids(os.path.dirname(path))
    if os.path.basename(path) == "datasets.json":
        # 数据集直通模式：无卡片层，白名单 = 已学数据集的 dsId
        for k, v in doc.items():
            if k.startswith("_") or not isinstance(v, dict):
                continue
            ds = v.get("dsId")
            if ds:
                scope["dsIds"].add(ds)
        return scope
    # 看板模式
    meta = doc.get("_meta") or {}
    for pg_id, info in (meta.get("pages") or {}).items():
        scope["pgIds"][pg_id] = info.get("title", pg_id)
    for k, v in doc.items():
        if k.startswith("_") or not isinstance(v, dict):
            continue
        scope["titles"].append(k)
        for ds in (v.get("dsUsage") or {}).keys():
            scope["dsIds"].add(ds)
        cards = v.get("cards") or []
        for c in cards:
            if isinstance(c, dict) and c.get("cdId"):
                scope["cdIds"][c["cdId"]] = f"{k}__{c.get('name', '')}"
    return scope
