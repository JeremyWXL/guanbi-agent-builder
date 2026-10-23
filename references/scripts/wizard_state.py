#!/usr/bin/env python3
"""
搭建向导状态机：显式记录八步流程进度，支持会话中断后续建；
增量学习（incr 模式）复用 1/2/4/7/8 步语义，状态文件独立为 wizard-state-incr.json；
看板诊断（audit 模式）走四步，状态文件独立为 wizard-state-audit.json
状态文件: <工作目录>/wizard-state.json（搭建）/ wizard-state-incr.json（增量）
  / wizard-state-audit.json（看板诊断）
用法:
  python3 wizard_state.py init <工作目录> [--name <agent名>] [--mode full|lite|incr|audit]
  python3 wizard_state.py set <工作目录> [--state build|incr|audit] --step <N> --status <status> [--note "..."] [--artifact <路径>]...
  python3 wizard_state.py confirm <工作目录> [--state build|incr|audit] --step <N> [--note "..."] [--artifact <路径>]...
  python3 wizard_state.py show <工作目录> [--state build|incr|audit] [--json]
  python3 wizard_state.py next <工作目录> [--state build|incr|audit]
状态取值: pending / in_progress / confirming（已生成待用户确认）/ confirmed / skipped
模式: full（完整八步，默认）/ lite（快速五步，合并执行时各步骤照常 confirm；
  断点续建与深化通道靠 mode 字段恢复行为；旧状态文件无 mode 按 full 处理）
  / incr（增量学习：往已交付的 agent 加看板/改版重学/移除看板；
  第 4、7 步命门在 incr 下同样禁止 skipped）
  / audit（看板诊断：洞察Agent 看板就绪度诊断，四步 A1 选定看板与场景 → A2 学习与结构体检
  → A3 整合与调整建议 → A4 报告输出；诊断链路无必选项之外的可选项，四步全部禁止 skipped）
约束: 第 3 步可选允许 skipped；第 4、7 步是质量命门，禁止 skipped（lite/incr 同样适用）；
  audit 四步全部禁止 skipped；
  confirm 第 7 步需 examples.json 验收基准全部回填确认（--record/--confirm 的证据），
  confirm 第 8 步需 package-check.json 体检通过（build_package.py 的产出）；
  audit confirm 第 2 步需 insight-audit.json（audit_insight_pages.py 产出）、
  第 3 步需 insight-advice.json（建议底稿补全）、
  第 4 步需 insight-audit.md 与 insight-audit.html（insight_audit_report.py 产出）——
  状态机从"记状态"升级为"验产物"，质量命门不看口头申报看产物
退出码: 0 成功 / 1 参数或状态文件错误 / 2 状态文件损坏 / 3 违反状态机约束
"""
import argparse, json, os, sys, tempfile
from datetime import datetime, timezone

# 与 SKILL.md frontmatter 的 version 保持同步
BUILDER_VERSION = "4.12.0"

MODES = ("full", "lite", "incr", "audit")
MODE_LABELS = {"full": "完整模式", "lite": "快速模式", "incr": "增量模式",
               "audit": "看板诊断模式"}

STEP_NAMES = {
    1: "选定数据范围",
    2: "看板资产学习",
    3: "业务认知补充",
    4: "业务口径确认",
    5: "分析场景定义",
    6: "分析框架与输出模板",
    7: "测试验收",
    8: "固化交付",
}
# 增量学习（incr 模式）复用 1/2/4/7/8 步语义：选新看板/学习比对/口径裁决/验收回归/交付更新
INCR_STEP_NAMES = {
    1: "增量选看板",
    2: "增量学习",
    4: "增量口径裁决",
    7: "增量验收",
    8: "交付更新",
}
# 看板诊断（audit 模式）：四步，状态文件独立
AUDIT_STEP_NAMES = {
    1: "选定看板与场景",
    2: "学习与结构体检",
    3: "整合与调整建议",
    4: "报告输出",
}
STATUSES = ("pending", "in_progress", "confirming", "confirmed", "skipped")
STATUS_LABELS = {
    "pending": "未开始",
    "in_progress": "进行中",
    "confirming": "待用户确认",
    "confirmed": "已确认",
    "skipped": "已跳过",
}
STATUS_ICONS = {
    "pending": "⬜",
    "in_progress": "🔵",
    "confirming": "🕐",
    "confirmed": "✅",
    "skipped": "⏭️",
}
# 质量命门：不允许跳过
NON_SKIPPABLE = {4, 7}
# 诊断链路没有可选项：audit 四步全部不允许跳过
AUDIT_NON_SKIPPABLE = frozenset(AUDIT_STEP_NAMES)

STATE_FILE = "wizard-state.json"
STATE_FILE_INCR = "wizard-state-incr.json"
STATE_FILE_AUDIT = "wizard-state-audit.json"


def now_iso():
    """本地时区 ISO 时间戳"""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def state_path(workdir, mode="build"):
    """build → 搭建档案 wizard-state.json；incr → 增量会话 wizard-state-incr.json；
    audit → 看板诊断 wizard-state-audit.json（三档独立文件，互不覆盖）"""
    name = {"incr": STATE_FILE_INCR, "audit": STATE_FILE_AUDIT}.get(mode, STATE_FILE)
    return os.path.join(workdir, name)


def state_mode_for(mode):
    """init --mode 映射到状态档位：incr/audit 各自独立，full/lite 共用搭建档案"""
    return mode if mode in ("incr", "audit") else "build"


def step_names_for(mode):
    """看板诊断用四步表，增量模式用增量步骤表，其余用八步表"""
    if mode == "audit":
        return AUDIT_STEP_NAMES
    return INCR_STEP_NAMES if mode == "incr" else STEP_NAMES


def non_skippable_for(mode):
    """该模式下禁止 skipped 的步骤集合：audit 四步全禁，其余为第 4、7 步命门"""
    return AUDIT_NON_SKIPPABLE if mode == "audit" else NON_SKIPPABLE


def load_state(workdir, mode="build"):
    """读取状态文件。不存在返回 None；损坏抛 StateCorruptedError"""
    path = state_path(workdir, mode)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise StateCorruptedError(path, e)


class StateCorruptedError(Exception):
    def __init__(self, path, cause):
        self.path = path
        self.cause = cause
        super().__init__(str(cause))


def save_state(workdir, state, mode="build"):
    """原子化写入：先写临时文件再 rename"""
    path = state_path(workdir, mode)
    state["updatedAt"] = now_iso()
    fd, tmp = tempfile.mkstemp(dir=workdir, prefix=".wizard-state-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def corrupted_exit(e):
    print(f"❌ 状态文件损坏，无法解析: {e.path}", file=sys.stderr)
    print(f"   解析错误: {e.cause}", file=sys.stderr)
    print("   原文件已保留未做改动。请人工检查修复，或确认无用后手动删除该文件再重新 init。",
          file=sys.stderr)
    sys.exit(2)


def die(msg, code=1):
    print(f"❌ {msg}", file=sys.stderr)
    sys.exit(code)


def load_json_quiet(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        return None


def gate_confirm_artifacts(workdir, step, mode="build"):
    """confirm 的产物校验（质量命门看产物不看口头申报）。返回错误信息或 None
    build/incr：第 7 步 examples.json、第 8 步 package-check.json；
    audit：第 2 步 insight-audit.json、第 3 步 insight-advice.json、
    第 4 步 insight-audit.md 与 insight-audit.html"""
    if mode == "audit":
        required = {
            2: (("insight-audit.json",),
                "第 2 步【学习与结构体检】确认需要 insight-audit.json——先运行 "
                "audit_insight_pages.py 完成机械体检并落盘"),
            3: (("insight-advice.json",),
                "第 3 步【整合与调整建议】确认需要 insight-advice.json——先用 "
                "audit_insight_pages.py --seed-advice 生成建议底稿并补全（模板 "
                "references/templates/insight-advice.json）"),
            4: (("insight-audit.md", "insight-audit.html"),
                "第 4 步【报告输出】确认需要 insight-audit.md 与 insight-audit.html——"
                "先运行 insight_audit_report.py 渲染报告"),
        }.get(step)
        if not required:
            return None
        files, hint = required
        missing = [f for f in files if not os.path.isfile(os.path.join(workdir, f))]
        if missing:
            return f"{hint}（缺少：{'、'.join(missing)}）"
        return None
    if step == 7:
        ex = load_json_quiet(os.path.join(workdir, "examples.json"))
        scenarios = (ex or {}).get("scenarios")
        if not isinstance(scenarios, dict) or not scenarios:
            return ("第 7 步【测试验收】确认需要 examples.json 验收基准——每场景至少 1 题实测；"
                    "用 eval_examples.py --suggest 看取数源数值、--record 回填、--confirm 确认")
        bad = []
        for sname, items in scenarios.items():
            if not items:
                bad.append(f"场景「{sname}」无示例题")
                continue
            for it in items:
                if not isinstance(it, dict):
                    continue
                if not it.get("humanConfirmed"):
                    bad.append(f"{it.get('id', '?')} 未验收确认")
                expect = it.get("expect") or {}
                if not expect.get("values") and not expect.get("keywords"):
                    bad.append(f"{it.get('id', '?')} expect 为空")
        if bad:
            return ("第 7 步验收实测证据不足：" + "；".join(bad[:6])
                    + "——eval_examples.py --record/--confirm 回填后再确认")
    elif step == 8:
        rec = load_json_quiet(os.path.join(workdir, "package-check.json"))
        if rec is None:
            return ("第 8 步【固化交付】确认需要 package-check.json——先运行 build_package.py "
                    "机械组装交付包并通过 check_package 体检（禁止手工拼装交付包）")
        if rec.get("result") != "pass":
            return (f"交付包体检未通过（{len(rec.get('errors') or [])} 个 ❌）——"
                    "按 package-check.json 的 errors 修复后重跑 build_package.py")
        if not os.path.isdir(rec.get("package") or ""):
            return f"package-check.json 记录的交付包不存在: {rec.get('package')}"
    return None


def cmd_init(args):
    workdir = args.workdir
    os.makedirs(workdir, exist_ok=True)
    smode = state_mode_for(args.mode)
    path = state_path(workdir, smode)
    if os.path.exists(path):
        try:
            old = load_state(workdir, smode)
        except StateCorruptedError as e:
            print(f"❌ 已存在状态文件但无法解析: {path}", file=sys.stderr)
            print(f"   解析错误: {e.cause}", file=sys.stderr)
            print("   原文件已保留未做改动。请人工检查修复，或确认无用后手动删除该文件再重新 init。",
                  file=sys.stderr)
            sys.exit(2)
        die(f"状态文件已存在（agent「{old.get('agentName', '')}」，当前第 "
            f"{old.get('currentStep', '?')} 步），如需续建请用 show/next 查看；"
            f"如需重新开始请先手动删除 {path}")
    state = {
        "version": 1,
        "builderVersion": BUILDER_VERSION,
        "agentName": args.name or "",
        "mode": args.mode,
        "createdAt": now_iso(),
        "updatedAt": now_iso(),
        "currentStep": 1,
        "steps": {str(n): {"status": "pending"} for n in step_names_for(args.mode)},
    }
    save_state(workdir, state, smode)
    if args.mode == "audit":
        print(f"✅ 已初始化看板诊断状态: {path}")
        print("   看板诊断（四步）：从第 1 步【选定看板与场景】开始。")
        return
    print(f"✅ 已初始化搭建状态: {path}")
    if args.mode == "incr":
        print("   增量学习（五步）：从第 1 步【增量选看板】开始。")
    elif args.mode == "lite":
        print("   快速模式（五步）：从第 1 步【选定数据范围】开始。")
    else:
        print("   从第 1 步【选定数据范围】开始。")


def cmd_set(args, confirmed=False):
    mode = args.state
    try:
        state = load_state(args.workdir, mode)
    except StateCorruptedError as e:
        corrupted_exit(e)
    if state is None:
        die(f"未找到状态文件 {state_path(args.workdir, mode)}，请先运行 init")
    step = str(args.step)
    status = "confirmed" if confirmed else args.status
    names = step_names_for(mode)
    if args.step not in names:
        die(f"第 {args.step} 步在{MODE_LABELS.get(mode, '完整模式')}下不存在"
            f"（可选：{', '.join(str(n) for n in sorted(names))}）")
    if status == "skipped" and args.step in non_skippable_for(mode):
        if mode == "audit":
            die(f"第 {args.step} 步【{names[args.step]}】在看板诊断模式下不允许跳过；"
                f"诊断链路四步都是必做项，必须完成并确认后才能继续", code=3)
        die(f"第 {args.step} 步【{names[args.step]}】是质量命门，不允许跳过；"
            f"必须完成并确认后才能继续", code=3)
    if confirmed:
        gate = gate_confirm_artifacts(args.workdir, args.step, mode)
        if gate:
            die(gate, code=3)
    entry = state["steps"].get(step, {})
    entry["status"] = status
    if confirmed:
        entry["confirmedAt"] = now_iso()
        entry.pop("note_pending", None)
    if args.note is not None:
        entry["note"] = args.note
    for art in args.artifact or []:
        arts = entry.setdefault("artifacts", [])
        if art not in arts:
            arts.append(art)
    state["steps"][step] = entry
    state["currentStep"] = args.step
    save_state(args.workdir, state, mode)
    label = STATUS_LABELS[status]
    verb = "已确认" if confirmed else f"状态已更新为「{label}」"
    print(f"✅ 第 {args.step} 步【{names[args.step]}】{verb}")


def cmd_show(args):
    mode = args.state
    try:
        state = load_state(args.workdir, mode)
    except StateCorruptedError as e:
        corrupted_exit(e)
    if state is None:
        die(f"未找到状态文件 {state_path(args.workdir, mode)}，请先运行 init")
    if args.json:
        print(json.dumps(state, ensure_ascii=False, indent=2))
        return
    name = state.get("agentName") or "（未命名）"
    smode = state.get("mode", "full")
    mode_label = MODE_LABELS.get(smode, "完整模式")
    if smode == "audit":
        print(f"看板诊断进度 —— 诊断对象「{name}」（{mode_label}）")
    else:
        print(f"搭建进度 —— agent「{name}」（{mode_label}）")
    print(f"创建于 {state.get('createdAt', '?')}，更新于 {state.get('updatedAt', '?')}"
          f"，当前第 {state.get('currentStep', '?')} 步\n")
    for n, sname in step_names_for(smode).items():
        entry = state.get("steps", {}).get(str(n), {})
        status = entry.get("status", "pending")
        icon = STATUS_ICONS.get(status, "⬜")
        line = f"{icon} 第 {n} 步【{sname}】{STATUS_LABELS.get(status, status)}"
        if entry.get("confirmedAt"):
            line += f"（确认于 {entry['confirmedAt']}）"
        print(line)
        if entry.get("note"):
            print(f"     备注: {entry['note']}")
        for art in entry.get("artifacts", []):
            print(f"     产物: {art}")


def cmd_next(args):
    mode = args.state
    try:
        state = load_state(args.workdir, mode)
    except StateCorruptedError as e:
        corrupted_exit(e)
    if state is None:
        die(f"未找到状态文件 {state_path(args.workdir, mode)}，请先运行 init")
    steps = state.get("steps", {})
    names = step_names_for(mode)
    nxt = None
    for n in names:
        if steps.get(str(n), {}).get("status", "pending") not in ("confirmed", "skipped"):
            nxt = n
            break
    name = state.get("agentName") or "（未命名）"
    smode = state.get("mode", "full")
    mode_label = MODE_LABELS.get(smode, "完整模式")
    audit = smode == "audit"
    if nxt is None:
        if mode == "incr":
            print(f"🎉 agent「{name}」本轮增量已交付（增量模式）。")
            print("如需继续加看板或看板再改版，可再发起一轮增量学习（说「增量学习」）。")
            return
        if audit:
            print(f"🎉 看板诊断「{name}」四步已完成，诊断报告已生成（{mode_label}）。")
            print("报告为 insight-audit.md / insight-audit.html；"
                  "如需按建议改造看板，走 BI 实施流程（诊断只读，不改看板）。")
            return
        print(f"🎉 agent「{name}」八步流程全部完成，搭建已交付（{mode_label}）。")
        if smode == "lite":
            print("快速模式交付已完成。后续如需逐条打磨口径与维度、扩充验收题库，"
                  "可回完整版第 4 步深化——已有档案直接作底稿，无需重建。")
        print("后续如需接入新看板或看板改版，可说「增量学习」——只学增量、不动已有口径与记忆。")
        return
    entry = steps.get(str(nxt), {})
    status = entry.get("status", "pending")
    label = STATUS_LABELS.get(status, status)
    print(f"上次进行到第 {nxt} 步【{names[nxt]}】（状态：{label}，{mode_label}）。")
    arts = entry.get("artifacts") or []
    if arts:
        print(f"产物: {', '.join(arts)}")
    if entry.get("note"):
        print(f"备注: {entry['note']}")
    if status == "confirming":
        print("该步骤产物已生成、等待用户确认。请把产物交给用户确认/纠偏，"
              "确认后执行 confirm 再继续。")
    elif status == "in_progress":
        print("该步骤已开始但未完成，请从中断处继续执行本步骤。")
    else:
        print("请从该步骤开始继续看板诊断。" if audit else "请从该步骤开始继续搭建。")


def build_parser():
    p = argparse.ArgumentParser(
        prog="wizard_state.py",
        description="搭建向导状态机：记录八步流程进度，支持会话中断后续建；"
                    "增量学习（--state incr）复用 1/2/4/7/8 步语义；"
                    "看板诊断（--state audit）走独立四步，状态文件各自独立")
    sub = p.add_subparsers(dest="command", required=True)
    state_help = "状态文件：build 搭建（默认）/ incr 增量会话 / audit 看板诊断"
    step_help = "步骤号（1-8；incr 仅 1/2/4/7/8，audit 仅 1-4）"

    pi = sub.add_parser("init", help="初始化状态文件")
    pi.add_argument("workdir", help="搭建工作目录")
    pi.add_argument("--name", default="", help="agent 名称（audit 下为诊断对象/场景名）")
    pi.add_argument("--mode", default="full", choices=MODES,
                    help="搭建模式：full 完整八步（默认）/ lite 快速五步 / incr 增量学习"
                         " / audit 看板诊断四步")
    pi.set_defaults(func=cmd_init)

    ps = sub.add_parser("set", help="更新某一步的状态")
    ps.add_argument("workdir", help="搭建工作目录")
    ps.add_argument("--state", default="build", choices=("build", "incr", "audit"),
                    help=state_help)
    ps.add_argument("--step", type=int, required=True, choices=sorted(STEP_NAMES),
                    help=step_help)
    ps.add_argument("--status", required=True, choices=STATUSES, help="目标状态")
    ps.add_argument("--note", default=None, help="备注")
    ps.add_argument("--artifact", action="append", default=None,
                    help="产物路径，可重复传入")
    ps.set_defaults(func=lambda a: cmd_set(a, confirmed=False))

    pc = sub.add_parser("confirm", help="确认某一步（= set --status confirmed + confirmedAt）")
    pc.add_argument("workdir", help="搭建工作目录")
    pc.add_argument("--state", default="build", choices=("build", "incr", "audit"),
                    help=state_help)
    pc.add_argument("--step", type=int, required=True, choices=sorted(STEP_NAMES),
                    help=step_help)
    pc.add_argument("--note", default=None, help="备注")
    pc.add_argument("--artifact", action="append", default=None,
                    help="产物路径，可重复传入")
    pc.set_defaults(func=lambda a: cmd_set(a, confirmed=True))

    pw = sub.add_parser("show", help="人类可读的进度总览")
    pw.add_argument("workdir", help="搭建工作目录")
    pw.add_argument("--state", default="build", choices=("build", "incr", "audit"),
                    help=state_help)
    pw.add_argument("--json", action="store_true", help="输出原始 JSON")
    pw.set_defaults(func=cmd_show)

    pn = sub.add_parser("next", help="打印续建提示（下一步该做什么）")
    pn.add_argument("workdir", help="搭建工作目录")
    pn.add_argument("--state", default="build", choices=("build", "incr", "audit"),
                    help=state_help)
    pn.set_defaults(func=cmd_next)

    return p


def main():
    args = build_parser().parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
