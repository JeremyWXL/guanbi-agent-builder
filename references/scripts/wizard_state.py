#!/usr/bin/env python3
"""
搭建向导状态机：显式记录八步流程进度，支持会话中断后续建
状态文件: <工作目录>/wizard-state.json
用法:
  python3 wizard_state.py init <工作目录> [--name <agent名>] [--mode full|lite]
  python3 wizard_state.py set <工作目录> --step <N> --status <status> [--note "..."] [--artifact <路径>]...
  python3 wizard_state.py confirm <工作目录> --step <N> [--note "..."] [--artifact <路径>]...
  python3 wizard_state.py show <工作目录> [--json]
  python3 wizard_state.py next <工作目录>
状态取值: pending / in_progress / confirming（已生成待用户确认）/ confirmed / skipped
模式: full（完整八步，默认）/ lite（快速五步，合并执行时各步骤照常 confirm；
  断点续建与深化通道靠 mode 字段恢复行为；旧状态文件无 mode 按 full 处理）
约束: 第 3 步可选允许 skipped；第 4、7 步是质量命门，禁止 skipped（lite 同样适用）
退出码: 0 成功 / 1 参数或状态文件错误 / 2 状态文件损坏 / 3 违反状态机约束
"""
import argparse, json, os, sys, tempfile
from datetime import datetime, timezone

# 与 SKILL.md frontmatter 的 version 保持同步
BUILDER_VERSION = "4.3.0"

MODES = ("full", "lite")
MODE_LABELS = {"full": "完整模式", "lite": "快速模式"}

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

STATE_FILE = "wizard-state.json"


def now_iso():
    """本地时区 ISO 时间戳"""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def state_path(workdir):
    return os.path.join(workdir, STATE_FILE)


def load_state(workdir):
    """读取状态文件。不存在返回 None；损坏抛 StateCorruptedError"""
    path = state_path(workdir)
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


def save_state(workdir, state):
    """原子化写入：先写临时文件再 rename"""
    path = state_path(workdir)
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


def cmd_init(args):
    workdir = args.workdir
    os.makedirs(workdir, exist_ok=True)
    path = state_path(workdir)
    if os.path.exists(path):
        try:
            old = load_state(workdir)
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
        "steps": {str(n): {"status": "pending"} for n in STEP_NAMES},
    }
    save_state(workdir, state)
    print(f"✅ 已初始化搭建状态: {path}")
    if args.mode == "lite":
        print("   快速模式（五步）：从第 1 步【选定数据范围】开始。")
    else:
        print("   从第 1 步【选定数据范围】开始。")


def cmd_set(args, confirmed=False):
    try:
        state = load_state(args.workdir)
    except StateCorruptedError as e:
        corrupted_exit(e)
    if state is None:
        die(f"未找到状态文件 {state_path(args.workdir)}，请先运行 init")
    step = str(args.step)
    status = "confirmed" if confirmed else args.status
    if status == "skipped" and args.step in NON_SKIPPABLE:
        die(f"第 {args.step} 步【{STEP_NAMES[args.step]}】是质量命门，不允许跳过；"
            f"必须完成并确认后才能继续", code=3)
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
    save_state(args.workdir, state)
    label = STATUS_LABELS[status]
    verb = "已确认" if confirmed else f"状态已更新为「{label}」"
    print(f"✅ 第 {args.step} 步【{STEP_NAMES[args.step]}】{verb}")


def cmd_show(args):
    try:
        state = load_state(args.workdir)
    except StateCorruptedError as e:
        corrupted_exit(e)
    if state is None:
        die(f"未找到状态文件 {state_path(args.workdir)}，请先运行 init")
    if args.json:
        print(json.dumps(state, ensure_ascii=False, indent=2))
        return
    name = state.get("agentName") or "（未命名）"
    mode = MODE_LABELS.get(state.get("mode", "full"), "完整模式")
    print(f"搭建进度 —— agent「{name}」（{mode}）")
    print(f"创建于 {state.get('createdAt', '?')}，更新于 {state.get('updatedAt', '?')}"
          f"，当前第 {state.get('currentStep', '?')} 步\n")
    for n, sname in STEP_NAMES.items():
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
    try:
        state = load_state(args.workdir)
    except StateCorruptedError as e:
        corrupted_exit(e)
    if state is None:
        die(f"未找到状态文件 {state_path(args.workdir)}，请先运行 init")
    steps = state.get("steps", {})
    nxt = None
    for n in STEP_NAMES:
        if steps.get(str(n), {}).get("status", "pending") not in ("confirmed", "skipped"):
            nxt = n
            break
    name = state.get("agentName") or "（未命名）"
    mode = state.get("mode", "full")
    mode_label = MODE_LABELS.get(mode, "完整模式")
    if nxt is None:
        print(f"🎉 agent「{name}」八步流程全部完成，搭建已交付（{mode_label}）。")
        if mode == "lite":
            print("快速模式交付已完成。后续如需逐条打磨口径与维度、扩充验收题库，"
                  "可回完整版第 4 步深化——已有档案直接作底稿，无需重建。")
        return
    entry = steps.get(str(nxt), {})
    status = entry.get("status", "pending")
    label = STATUS_LABELS.get(status, status)
    print(f"上次进行到第 {nxt} 步【{STEP_NAMES[nxt]}】（状态：{label}，{mode_label}）。")
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
        print("请从该步骤开始继续搭建。")


def build_parser():
    p = argparse.ArgumentParser(
        prog="wizard_state.py",
        description="搭建向导状态机：记录八步流程进度，支持会话中断后续建")
    sub = p.add_subparsers(dest="command", required=True)

    pi = sub.add_parser("init", help="初始化状态文件")
    pi.add_argument("workdir", help="搭建工作目录")
    pi.add_argument("--name", default="", help="agent 名称")
    pi.add_argument("--mode", default="full", choices=MODES,
                    help="搭建模式：full 完整八步（默认）/ lite 快速五步")
    pi.set_defaults(func=cmd_init)

    ps = sub.add_parser("set", help="更新某一步的状态")
    ps.add_argument("workdir", help="搭建工作目录")
    ps.add_argument("--step", type=int, required=True, choices=sorted(STEP_NAMES),
                    help="步骤号（1-8）")
    ps.add_argument("--status", required=True, choices=STATUSES, help="目标状态")
    ps.add_argument("--note", default=None, help="备注")
    ps.add_argument("--artifact", action="append", default=None,
                    help="产物路径，可重复传入")
    ps.set_defaults(func=lambda a: cmd_set(a, confirmed=False))

    pc = sub.add_parser("confirm", help="确认某一步（= set --status confirmed + confirmedAt）")
    pc.add_argument("workdir", help="搭建工作目录")
    pc.add_argument("--step", type=int, required=True, choices=sorted(STEP_NAMES),
                    help="步骤号（1-8）")
    pc.add_argument("--note", default=None, help="备注")
    pc.add_argument("--artifact", action="append", default=None,
                    help="产物路径，可重复传入")
    pc.set_defaults(func=lambda a: cmd_set(a, confirmed=True))

    pw = sub.add_parser("show", help="人类可读的进度总览")
    pw.add_argument("workdir", help="搭建工作目录")
    pw.add_argument("--json", action="store_true", help="输出原始 JSON")
    pw.set_defaults(func=cmd_show)

    pn = sub.add_parser("next", help="打印续建提示（下一步该做什么）")
    pn.add_argument("workdir", help="搭建工作目录")
    pn.set_defaults(func=cmd_next)

    return p


def main():
    args = build_parser().parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
