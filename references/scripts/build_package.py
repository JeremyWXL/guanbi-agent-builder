#!/usr/bin/env python3
"""
交付包机械组装器：第 8 步固化交付的唯一入口。
把"LLM 手工组装交付包"（实机 review 案例：cards.json 被裁成纯卡片名单 →
run_sql 白名单全拦截 / make_link 无筛选器可用 / sample_cards 整批拒绝，三功能连锁瘫痪）
变成脚本复制派生——模型无法破坏它从不经手的东西（correct by construction）。
用法:
  python3 build_package.py <工作目录> --package <交付包路径> [--manifest <路径>] [--force]
  --manifest 缺省取 <工作目录>/agent-manifest.json（字段见 render_agent_skill.py docstring；
    dashboards / typicalQuestions / mode / datasetCount / date 缺省时从学习产物自动带入）
  --force    允许写入已存在的交付包目录；重建前清空受控区（references/ 与生成的 workbench.html，
             防止旧采样/旧模式文件残留），memory/ 永不覆盖——init 幂等，重跑/重建都安全
动作（全机械，顺序固定）:
  1. 前置校验（exit 2）: cards-raw.json（或 datasets-raw.json）/ metrics.json / dimensions.json /
     learningResult.md / businessKnowledge.md / insightThinking.md / examples.json 齐全；
     examples.json 每场景 ≥1 题、全部 humanConfirmed=true 且 expect 非空
     （第 7 步验收实测的硬证据——未回填确认禁止交付；
     用 eval_examples.py --suggest/--record/--confirm 机械回填）
  2. 机械回填: fill_dim_values.py（空 values 维度从采样画像补齐）→ 双闸门
     check_metrics.py / check_dims.py 必过（❌ 未清零禁止交付）
  3. 组装: cards.json 由 cards-raw.json 整体复制派生（_meta/filtered/dsUsage/filterDetails/
     筛选器交互字段天然完整，禁止任何形式的裁剪）；脚本按清单复制；card-data/ 复制；
     SKILL.md 由 render_agent_skill.py 模板渲染；memory init（幂等）
  4. workbench.py 生成只读 workbench.html（写到交付包根目录）
  5. 总闸门: check_package.py 三层体检（结构/内容/功能冒烟），❌ 即 exit 1（包保留供排查）
  6. 落盘 <工作目录>/package-check.json——wizard_state confirm --step 8 的硬性凭证
退出码: 0 交付成功 / 1 体检未过 / 2 前置校验失败或用法错误
"""
import json, os, shutil, subprocess, sys, tempfile
from datetime import date, datetime

# 与 SKILL.md frontmatter 的 version 保持同步
BUILDER_VERSION = "4.8.1"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# 复制进交付包 references/ 的脚本（维护期自检/取数/回归全靠它们；check_package 的
# SCRIPT_LIST 是验收口径，这里额外带 fill_dim_values/render 以外的维护工具）
PACKAGE_SCRIPTS = ["attribute.py", "make_link.py", "memory.py", "check_metrics.py",
                   "check_dims.py", "eval_examples.py", "sample_cards.py", "run_sql.py",
                   "run_metric.py", "workbench.py", "scope.py", "scope_audit.py", "feedback.py",
                   "check_package.py", "fill_dim_values.py"]
DATASET_MODE_DROP = {"make_link.py", "sample_cards.py"}  # 直通模式无卡片层
OPTIONAL_CONTENT = ["industry-notes.md", "report-insights.md", "conversation-insights.md"]
SCENARIO_ORDER = ["问数", "归因", "异常", "洞察"]


def die(msg, code=2):
    print(f"❌ {msg}", file=sys.stderr)
    sys.exit(code)


def run(argv, stream=True):
    """子进程执行；stream=True 时实时透传输出。返回 (returncode, combined_output)"""
    r = subprocess.run(argv, capture_output=True, text=True)
    out = (r.stdout or "") + (r.stderr or "")
    if stream and out.strip():
        print(out.rstrip())
    return r.returncode, out


def load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        return None


def precheck(workdir, mode):
    """前置校验：产物齐全 + 验收实测证据（exit 2）"""
    raw = "cards-raw.json" if mode == "dashboard" else "datasets-raw.json"
    required = [raw, "metrics.json", "dimensions.json", "formulas.json",
                "learningResult.md", "businessKnowledge.md", "insightThinking.md", "examples.json"]
    missing = [f for f in required if not os.path.isfile(os.path.join(workdir, f))]
    if missing:
        die(f"工作目录缺少产物: {'、'.join(missing)}——按向导步骤完成后再交付（断点续建用 preflight 检测）")
    ex = load_json(os.path.join(workdir, "examples.json"))
    scenarios = (ex or {}).get("scenarios")
    if not isinstance(scenarios, dict) or not scenarios:
        die("examples.json 缺少 scenarios——第 5 步先与用户确认典型问题")
    problems = []
    for sname, items in scenarios.items():
        if not isinstance(items, list) or not items:
            problems.append(f"场景「{sname}」没有示例题")
            continue
        for it in items:
            if not isinstance(it, dict):
                continue
            tag = f"场景「{sname}」{it.get('id', '?')}"
            if not it.get("humanConfirmed"):
                problems.append(f"{tag} 未验收确认（humanConfirmed=false）")
            expect = it.get("expect") or {}
            if not expect.get("values") and not expect.get("keywords"):
                problems.append(f"{tag} expect 为空（无数据层断言）")
    if problems:
        die("第 7 步验收实测证据不足，禁止交付：\n  - " + "\n  - ".join(problems[:12])
            + "\n用 eval_examples.py --suggest 看取数源显著数值、--record 回填、--confirm 确认后重试")


def auto_manifest(workdir, mode, manifest):
    """从学习产物自动带入 manifest 缺省字段（模型只须提供判断性槽位）"""
    m = dict(manifest or {})
    if mode == "dashboard":
        raw = load_json(os.path.join(workdir, "cards-raw.json")) or {}
        titles = [k for k, v in raw.items() if not k.startswith("_") and isinstance(v, dict)]
        m.setdefault("dashboards", "》《".join(titles))
        m.setdefault("mode", "dashboard")
    else:
        draw = load_json(os.path.join(workdir, "datasets-raw.json")) or {}
        names = [k for k in draw if not k.startswith("_")]
        n = len(names)
        # dashboards 槽位直通模式填数据集名（渲染为《fact_sales_daily》而非"N 个数据集"）
        m.setdefault("dashboards", "》《".join(names) if names else f"{n} 个数据集")
        m.setdefault("mode", "dataset")
        m.setdefault("datasetCount", n)
    if "typicalQuestions" not in m:
        ex = load_json(os.path.join(workdir, "examples.json")) or {}
        scenarios = ex.get("scenarios") or {}
        qs = []
        for sname in SCENARIO_ORDER:
            items = scenarios.get(sname) or []
            if items and isinstance(items[0], dict) and items[0].get("question"):
                qs.append(items[0]["question"])
        if len(qs) == 4:
            m["typicalQuestions"] = qs
    m.setdefault("date", date.today().isoformat())
    return m


def main():
    args = sys.argv[1:]
    package = manifest_path = None
    force = "--force" in args
    pos = []
    i = 0
    while i < len(args):
        if args[i] == "--package":
            package = args[i + 1]; i += 2
        elif args[i] == "--manifest":
            manifest_path = args[i + 1]; i += 2
        elif args[i] == "--force":
            i += 1
        else:
            pos.append(args[i]); i += 1
    if not pos or not package:
        sys.exit(__doc__)
    workdir = os.path.abspath(pos[0])
    package = os.path.abspath(package)
    manifest_path = manifest_path or os.path.join(workdir, "agent-manifest.json")

    mode = "dashboard" if os.path.isfile(os.path.join(workdir, "cards-raw.json")) else "dataset"
    if mode == "dataset" and not os.path.isfile(os.path.join(workdir, "datasets-raw.json")):
        die(f"工作目录既无 cards-raw.json 也无 datasets-raw.json——先完成第 2 步资产学习: {workdir}")
    print(f"第 8 步 · 固化交付（{'看板模式' if mode == 'dashboard' else '数据集直通模式'}）")

    # ---- 1. 前置校验 ----
    precheck(workdir, mode)
    if not os.path.isfile(manifest_path):
        die(f"找不到 agent manifest: {manifest_path}——第 8 步需要它提供 agent 的判断性槽位"
            "（slug/scenario/keywords 必填；sqlAvailable/lite/buildNote/extraRedLines 可选，"
            "字段说明见 render_agent_skill.py docstring）")
    manifest = load_json(manifest_path)
    if manifest is None:
        die(f"agent manifest 无法解析: {manifest_path}")

    # ---- 2. 机械回填 + 双闸门 ----
    print("\n[1/5] 维度成员值机械回填 + 双闸门")
    run([sys.executable, os.path.join(SCRIPT_DIR, "fill_dim_values.py"), workdir])
    for gate in ("check_metrics.py", "check_dims.py"):
        code, out = run([sys.executable, os.path.join(SCRIPT_DIR, gate), workdir])
        if code != 0:
            die(f"{gate} 未通过（exit {code}）——❌ 清零后才能交付", code=2)

    # ---- 3. 组装 ----
    print("\n[2/5] 组装交付包（复制派生，禁止裁剪）")
    if os.path.isdir(package) and os.listdir(package) and not force:
        die(f"交付包目录已存在且非空: {package}——确认要覆盖请加 --force（memory/ 永不覆盖）")
    refs = os.path.join(package, "references")
    # --force 重建前先清空受控区：copytree(dirs_exist_ok=True) 是合并语义，旧 references/ 文件
    # 与已删除卡片的旧采样会残留（看板↔数据集模式切换时旧 cards.json 残留会让体检误判模式）；
    # memory/ 是用户资产永不触碰，SKILL.md 随后整体重渲染
    if os.path.isdir(refs):
        shutil.rmtree(refs)
    old_workbench = os.path.join(package, "workbench.html")
    if os.path.isfile(old_workbench):
        os.unlink(old_workbench)
    os.makedirs(refs, exist_ok=True)
    if mode == "dashboard":
        shutil.copy(os.path.join(workdir, "cards-raw.json"), os.path.join(refs, "cards.json"))
        src_cd = os.path.join(workdir, "card-data")
        if os.path.isdir(src_cd):
            shutil.copytree(src_cd, os.path.join(refs, "card-data"), dirs_exist_ok=True)
    else:
        shutil.copy(os.path.join(workdir, "datasets-raw.json"), os.path.join(refs, "datasets.json"))
    content = ["formulas.json", "metrics.json", "dimensions.json", "examples.json",
               "learningResult.md", "businessKnowledge.md", "insightThinking.md"]
    for fn in content + OPTIONAL_CONTENT:
        src = os.path.join(workdir, fn)
        if os.path.isfile(src):
            shutil.copy(src, os.path.join(refs, fn))
    of = os.path.join(workdir, "outputFormat.json")
    shutil.copy(of if os.path.isfile(of)
                else os.path.join(SCRIPT_DIR, "..", "templates", "outputFormat.json"),
                os.path.join(refs, "outputFormat.json"))
    sql_guide = os.path.join(SCRIPT_DIR, "..", "sql-guide.md")
    if os.path.isfile(sql_guide):
        shutil.copy(sql_guide, os.path.join(refs, "sql-guide.md"))
    copied = []
    for fn in PACKAGE_SCRIPTS:
        if mode == "dataset" and fn in DATASET_MODE_DROP:
            continue
        src = os.path.join(SCRIPT_DIR, fn)
        if os.path.isfile(src):
            shutil.copy(src, os.path.join(refs, fn))
            copied.append(fn)
    print(f"   内容文件 {len(content)} 项 + 脚本 {len(copied)} 个已复制")

    # SKILL.md 模板渲染（manifest 自动带入缺省字段）
    m = auto_manifest(workdir, mode, manifest)
    fd, eff = tempfile.mkstemp(prefix=".agent-manifest-", suffix=".json", dir=workdir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(m, f, ensure_ascii=False, indent=1)
        code, out = run([sys.executable, os.path.join(SCRIPT_DIR, "render_agent_skill.py"),
                         "--manifest", eff, "-o", os.path.join(package, "SKILL.md")])
    finally:
        os.unlink(eff)
    if code != 0:
        die("SKILL.md 渲染失败——按上方报错补齐 manifest 字段", code=2)

    # 记忆区初始化（幂等，已有记忆永不覆盖）
    code, _ = run([sys.executable, os.path.join(refs, "memory.py"), "init", package])
    if code != 0:
        die("memory init 失败", code=2)

    # ---- 4. workbench.html ----
    print("\n[3/5] 生成只读工作台 workbench.html")
    code, _ = run([sys.executable, os.path.join(refs, "workbench.py"), refs])
    if code != 0 or not os.path.isfile(os.path.join(package, "workbench.html")):
        die("workbench.html 生成失败", code=2)

    # ---- 5. 总闸门 ----
    print("\n[4/5] 交付包体检（check_package.py 三层校验）")
    code, out = run([sys.executable, os.path.join(SCRIPT_DIR, "check_package.py"),
                     package, "--json"], stream=False)
    try:
        report = json.loads(out)
    except json.JSONDecodeError:
        die(f"check_package 输出无法解析（exit {code}）: {out[:300]}", code=1)
    result = "pass" if code == 0 else "fail"
    record = {"package": package, "checkedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
              "builderVersion": BUILDER_VERSION, "result": result,
              "errors": report.get("errors") or [], "warnings": report.get("warnings") or []}
    with open(os.path.join(workdir, "package-check.json"), "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=1)
        f.write("\n")
    for e in record["errors"]:
        print(f"  ❌ {e}")
    for w in record["warnings"]:
        print(f"  ⚠️  {w}")
    if code != 0:
        die(f"体检 {len(record['errors'])} 个 ❌ 未清零——修复后重跑本脚本（包已保留供排查）", code=1)

    # ---- 6. 完成 ----
    print(f"\n[5/5] ✅ 交付包已就绪: {package}")
    print(f"体检凭证已落盘: {os.path.join(workdir, 'package-check.json')}"
          "（wizard_state confirm --step 8 的依据）")


if __name__ == "__main__":
    main()
