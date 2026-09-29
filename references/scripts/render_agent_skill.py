#!/usr/bin/env python3
"""
交付助手 SKILL.md 机械渲染器：模板 + manifest → SKILL.md
LLM 只交付 manifest（需要判断力的槽位值：场景名/触发词/能力边界结论），
SKILL.md 本体由模板机械填充——缺节、漏节、CLI 凭记忆写错从结构上不可能发生。
用法:
  python3 render_agent_skill.py --manifest <manifest.json> [-o <输出路径>]   # 缺省打印到 stdout
manifest 字段（* 必填）:
  *slug             agent 标识（frontmatter name = agent-<slug>）
  *scenario         业务场景名（如：业财经营分析）
  *keywords         description 触发关键词（如：收入/毛利/费用、达成率、归因）
  *dashboards       看板清单（"》《"连接；build_package 从 cards-raw 自动带入；直通模式填数据集名，
                    build_package 从 datasets-raw 自动带入）
  *typicalQuestions 4 个典型问题 [问数, 归因, 异常, 洞察]（build_package 从 examples.json 自动带入）
  date              搭建日期（缺省今天）
  mode              dashboard（默认）| dataset（数据集直通：保留「数据探索型变体」节）
  datasetCount      直通模式数据集个数（填入变体节自我介绍）
  lite              true → 搭建注追加快速模式标注
  buildNote         搭建注追加的自定义说明（如冲突裁决摘要）
  sqlAvailable      false → SQL 节替换为"当前不可用"标注（第 7 步探活结论；缺省/true 保持可用表述）
  extraRedLines     业务特定红线列表（追加进「数据红线」节，如"3.5 预算口径达成率失真，用百分点偏差"）
校验: 渲染后残留 {占位符}、缺必需章节、模式与变体节不一致——任一即 exit 2 报错（模板漂移在此拦截）
退出码: 0 成功 / 2 manifest 缺字段或渲染校验失败
"""
import json, os, re, sys
from datetime import datetime

PLACEHOLDER_RE = re.compile(r"\{[^{}\n]{1,30}\}")
REQUIRED_SECTIONS = ["使用方式", "对话体验规范", "记忆系统", "前置检查", "执行流程", "数据红线", "维护"]
VARIANT_MARK = "【数据探索型变体"
SQL_NOTE_MARK = "> 💡 **SQL 直查触发条件**"
SQL_NOTE_MARK_DATASET = "> 💡 **SQL 直查即主路径**"
SQL_UNAVAILABLE_NOTE = (
    "> ⚠️ **SQL 直查当前不可用**（第 7 步探活实测失效）：取数以卡片缓存与未筛选（数据集级）卡片"
    "为准，禁止宣称可 SQL 直查。恢复条件：数据集重新可用后按第 7 步流程探活验证，再把本节改回可用表述。"
    "references 中保留 sql-guide.md 与 run_sql.py 备用。")
SQL_UNAVAILABLE_NOTE_DATASET = (
    "> ⚠️ **SQL 直查当前不可用**（第 7 步探活实测失效）：取数以已验收示例的缓存结论为准，"
    "禁止宣称可 SQL 直查。恢复条件：数据集重新可用后按第 7 步流程探活验证，再把本节改回可用表述。"
    "references 中保留 sql-guide.md 与 run_sql.py 备用。")
# 模式条件块：<!-- MODE: dashboard|dataset --> ... <!-- /MODE -->，按 manifest.mode 二选一
MODE_BLOCK_RE = re.compile(r"<!-- MODE: (dashboard|dataset) -->\n([\s\S]*?)<!-- /MODE -->\n?")
# 直通模式产物不得出现的看板模式资产引用（cards.json/sample_cards/make_link 不随直通包分发，
# 残留即悬空引用——渲染期拦截）
DATASET_FORBIDDEN_REFS = ["cards.json", "card-data", "sample_cards", "make_link"]

REQUIRED_KEYS = ["slug", "scenario", "keywords", "dashboards", "typicalQuestions"]


def template_path():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "..", "templates", "agent-SKILL.md")


def die(msg):
    print(f"❌ {msg}", file=sys.stderr)
    sys.exit(2)


def render(manifest):
    for k in REQUIRED_KEYS:
        if not manifest.get(k):
            die(f"manifest 缺少必填字段「{k}」（必填：{'、'.join(REQUIRED_KEYS)}）")
    tq = manifest["typicalQuestions"]
    if not isinstance(tq, list) or len(tq) != 4 or not all(str(q).strip() for q in tq):
        die("manifest.typicalQuestions 必须是 4 个非空问题 [问数, 归因, 异常, 洞察]")
    mode = manifest.get("mode", "dashboard")
    if mode not in ("dashboard", "dataset"):
        die(f"manifest.mode 只能是 dashboard / dataset，收到: {mode}")

    with open(template_path(), encoding="utf-8") as f:
        text = f.read()

    repl = {
        "{场景名}": manifest["slug"],
        "{业务场景}": manifest["scenario"],
        "{看板清单}": manifest["dashboards"],
        "{典型问题关键词列表}": manifest["keywords"],
        "{日期}": manifest.get("date") or datetime.now().strftime("%Y-%m-%d"),
    }
    for i, q in enumerate(tq, 1):
        repl["{典型问题%d}" % i] = str(q)
    for k, v in repl.items():
        text = text.replace(k, v)

    # 模式与变体节
    if mode == "dashboard":
        text = re.sub(r"\n---\n\n> " + re.escape(VARIANT_MARK) + r"[\s\S]*?\n---\n", "\n", text, count=1)
        if VARIANT_MARK in text:
            die("数据探索型变体节移除失败——模板结构可能已漂移，请人工检查")
    else:
        n = manifest.get("datasetCount")
        if n:
            text = text.replace("数据来自 N 个数据集", f"数据来自 {n} 个数据集")
        # 直通模式措辞修正：description 按数据集口径；场景名本身以"数据探索"结尾时去掉重复
        text = text.replace("以观远 BI 看板《", "以观远 BI 数据集《", 1)
        text = text.replace("数据探索数据探索", "数据探索")

    # 模式条件块：命中模式的块去标记保留内容，另一模式的块整块移除（看板模式产物逐字节不变）
    text = MODE_BLOCK_RE.sub(lambda m: m.group(2) if m.group(1) == mode else "", text)
    if "<!-- MODE:" in text:
        die("模式条件块解析失败（存在未闭合的 <!-- MODE: --> 标记）——模板结构可能已漂移，请人工检查")

    # SQL 直查可用性（以第 7 步探活实测为准）
    if manifest.get("sqlAvailable") is False:
        mark = SQL_NOTE_MARK if mode == "dashboard" else SQL_NOTE_MARK_DATASET
        note = SQL_UNAVAILABLE_NOTE if mode == "dashboard" else SQL_UNAVAILABLE_NOTE_DATASET
        lines = text.splitlines()
        for i, ln in enumerate(lines):
            if ln.startswith(mark):
                lines[i] = note
                break
        else:
            die("找不到 SQL 直查触发条件注释行——模板结构可能已漂移，请人工检查")
        text = "\n".join(lines)

    # 搭建注：快速模式标注 / 自定义说明
    notes = []
    if manifest.get("lite"):
        notes.append("快速模式：共识口径按看板算法默认采纳，冲突已逐条裁决，可随时深化")
    if manifest.get("buildNote"):
        notes.append(str(manifest["buildNote"]))
    if notes:
        text = text.replace("数据源与业务口径已经业务用户确认。",
                            "数据源与业务口径已经业务用户确认（" + "；".join(notes) + "）。", 1)

    # 业务特定红线
    extra = [str(x) for x in manifest.get("extraRedLines") or [] if str(x).strip()]
    if extra:
        marker = "\n## 维护"
        if marker not in text:
            die("找不到「## 维护」节——模板结构可能已漂移，请人工检查")
        text = text.replace(marker, "\n" + "\n".join(f"- {x}" for x in extra) + "\n" + marker, 1)

    # 渲染校验：占位符清零 + 必需章节齐全 + 模式一致
    leftover = PLACEHOLDER_RE.findall(text)
    if leftover:
        die(f"渲染后仍残留占位符: {'、'.join(sorted(set(leftover)))}——manifest 字段缺失或模板漂移")
    for sec in REQUIRED_SECTIONS:
        if not re.search(r"^##\s*[^\n]*" + sec, text, re.M):
            die(f"渲染结果缺少必需章节「{sec}」——模板结构可能已漂移，请人工检查")
    if mode == "dataset" and VARIANT_MARK not in text:
        die("直通模式渲染结果缺少数据探索型变体节——模板结构可能已漂移")
    if mode == "dataset":
        bad = [r for r in DATASET_FORBIDDEN_REFS if r in text]
        if bad:
            die(f"直通模式渲染结果残留看板模式资产引用: {'、'.join(bad)}——"
                "这些文件不随直通包分发，模板结构可能已漂移，请人工检查")
    return text


def main():
    args = sys.argv[1:]
    manifest_path = out_path = None
    i = 0
    while i < len(args):
        if args[i] == "--manifest":
            manifest_path = args[i + 1]; i += 2
        elif args[i] == "-o":
            out_path = args[i + 1]; i += 2
        else:
            sys.exit(__doc__)
    if not manifest_path:
        sys.exit(__doc__)
    try:
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as e:
        die(f"manifest 无法解析: {e}")
    text = render(manifest)
    if out_path:
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"✅ SKILL.md 已渲染 → {out_path}")
    else:
        print(text)


if __name__ == "__main__":
    main()
