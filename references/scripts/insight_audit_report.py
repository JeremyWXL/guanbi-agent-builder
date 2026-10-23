#!/usr/bin/env python3
"""
洞察Agent 看板诊断：建议校验 + 报告渲染（Markdown / 单文件 HTML 同源）。

用法:
  python3 insight_audit_report.py <工作目录> [--draft] [--check] [--advice PATH] [--open]

输入:
  <工作目录>/insight-audit.json    必需，audit_insight_pages.py 的结构体检产物
  <工作目录>/insight-advice.json   最终报告与 --check 必需（可用 --advice 指定别的路径）

模式:
  默认        校验建议 → 渲染 insight-audit.md / insight-audit.html
  --draft     不要求建议文件 → 渲染 insight-audit-draft.md / insight-audit-draft.html
  --check     只校验建议，不写任何文件；通过 exit 0，失败 exit 2 并列出全部错误
  --open      渲染完成后在 macOS 上自动打开 HTML（其他平台静默跳过）

退出码:
  0 成功；2 输入缺失/损坏、建议校验不通过
"""
import argparse
import html
import json
import os
import re
import subprocess
import sys

MODES = ["一张宽表", "多层下钻", "主从Agent", "批量分治", "链路复盘"]
AGENT_TYPES = ["探索型", "报告型", "混合型"]
VERDICTS = ["保留", "改造", "拆分", "合并", "新建", "移出"]
PRIORITIES = ["P0", "P1", "P2"]
REQUIRED_KEYS = [
    "auditBuiltAt", "scenario", "businessScope", "mode", "targetArchitecture",
    "pageActions", "crossPageActions", "configHandoff", "roadmap", "openQuestions",
]

DIMENSIONS = [
    ("focus", "场景聚焦", 15),
    ("metrics", "指标可直读", 20),
    ("linkage", "联动筛选", 25),
    ("layers", "分层下钻", 20),
    ("context", "上下文", 10),
    ("ops", "可运维", 10),
]

LEVEL_LABEL = {
    "blocker": "阻断项", "p0": "P0", "p1": "P1", "p2": "P2",
    "warn": "告警", "info": "提示", "ok": "通过",
}
LEVEL_ORDER = {"blocker": 0, "p0": 1, "p1": 2, "p2": 3, "warn": 4, "info": 5, "ok": 6}
LEVEL_GROUPS = ["blocker", "p0", "p1", "p2", "warn", "info", "ok"]

GRADE_CLASS = {
    "可直接配置": "ok", "小改后配置": "mid", "需改造": "warn", "不建议直接配置": "bad",
}

PLACEHOLDER_RE = re.compile(r"^<[^<>\n]{1,200}>$")

RULE_SOURCES = [
    ("官方文档", "洞察Agent 产品简介 / 新建智能体 / 基础信息 / 分析思路 / 业务知识 / 快速入门 / 常见问题"),
    ("官方硬约束", "数据范围最多 10 页；每页必须选联动筛选器；业务范围必填；指标口径由看板固化"),
    ("项目方法论", "场景聚焦、指标前置、筛选承接、分层下钻、跨页联动、去冗余、可运维"),
    ("规则全文", "references/insight-agent-readiness.md（R-01…R-16）"),
]

CSS = """
:root{--ink:#1d2129;--ink2:#4e5969;--ink3:#86909c;--line:#e5e6eb;--bg:#f7f8fa;
  --ok:#00b42a;--warn:#ff7d00;--bad:#f53f3f;--acc:#165dff;--soft:#f2f3f5}
*{box-sizing:border-box;margin:0}
body{font-family:-apple-system,"PingFang SC","Helvetica Neue",sans-serif;
  background:var(--bg);color:var(--ink);padding:36px 20px 60px;line-height:1.65}
main{max-width:1000px;margin:0 auto}
header{margin-bottom:18px}
h1{font-size:23px;letter-spacing:.2px}
.meta{font-size:12.5px;color:var(--ink3);margin-top:5px}
.submeta{font-size:13px;color:var(--ink2);margin-top:3px}
.hero{background:#fff;border:1px solid var(--line);border-radius:12px;
  padding:18px 22px;margin-bottom:16px;display:flex;gap:26px;align-items:center;flex-wrap:wrap}
.big{font-size:38px;font-weight:700;line-height:1;color:var(--ink)}
.big small{font-size:13px;font-weight:400;color:var(--ink3);margin-left:4px}
.grade{display:inline-block;font-size:12.5px;border-radius:6px;padding:3px 10px;border:1px solid}
.grade.ok{color:var(--ok);border-color:color-mix(in srgb,var(--ok) 45%,transparent);background:color-mix(in srgb,var(--ok) 8%,#fff)}
.grade.mid{color:var(--warn);border-color:color-mix(in srgb,var(--warn) 45%,transparent);background:color-mix(in srgb,var(--warn) 8%,#fff)}
.grade.warn{color:#d25f00;border-color:color-mix(in srgb,var(--warn) 55%,transparent);background:color-mix(in srgb,var(--warn) 12%,#fff)}
.grade.bad{color:var(--bad);border-color:color-mix(in srgb,var(--bad) 45%,transparent);background:color-mix(in srgb,var(--bad) 8%,#fff)}
.stats{display:flex;gap:22px;flex-wrap:wrap;margin-left:auto}
.stat{font-size:12px;color:var(--ink3)}
.stat b{display:block;font-size:19px;color:var(--ink);font-weight:600}
.stat.bad b{color:var(--bad)}
.notice{border-radius:10px;padding:12px 16px;margin-bottom:16px;font-size:13px;line-height:1.7}
.notice.draft{background:#fff7e8;border:1px solid #ffd591;color:#874d00}
.banner{background:#fff1f0;border:1px solid #ffccc7;border-radius:10px;padding:14px 18px;margin-bottom:18px}
.banner h2{font-size:14px;color:var(--bad);margin-bottom:8px}
.banner ul{padding-left:18px}
.banner li{font-size:12.8px;color:#a8071a;line-height:1.75}
section{background:#fff;border:1px solid var(--line);border-radius:12px;
  padding:18px 22px;margin-bottom:14px}
section>h2{font-size:16px;margin-bottom:12px;padding-bottom:8px;border-bottom:1px solid var(--line)}
h3{font-size:13.5px;color:var(--ink2);margin:16px 0 8px}
h3:first-of-type{margin-top:4px}
p{font-size:13.2px;color:var(--ink2);margin:6px 0}
ul,ol{padding-left:20px}
li{font-size:13px;color:var(--ink2);margin:3px 0}
a{color:var(--acc);text-decoration:none}
a:hover{text-decoration:underline}
table{width:100%;border-collapse:collapse;margin:8px 0 4px;font-size:12.5px}
th,td{text-align:left;padding:7px 9px;border-bottom:1px solid var(--line);vertical-align:top}
th{background:var(--soft);color:var(--ink2);font-weight:600;font-size:12px}
td.num{text-align:right;font-variant-numeric:tabular-nums;color:var(--ink2)}
.bar{height:6px;border-radius:3px;background:var(--soft);overflow:hidden;margin-top:4px}
.bar>span{display:block;height:100%;border-radius:3px;background:var(--acc)}
.bar.ok>span{background:var(--ok)}.bar.mid>span{background:var(--warn)}
.bar.warn>span{background:#ff7d00}.bar.bad>span{background:var(--bad)}
.tag{display:inline-block;font-size:11px;border-radius:5px;padding:1px 7px;
  border:1px solid var(--line);color:var(--ink2);margin-left:6px;vertical-align:1px;background:#fff}
.tag.p0,.tag.blocker{color:var(--bad);border-color:#ffccc7;background:#fff1f0}
.tag.p1{color:#d25f00;border-color:#ffd591;background:#fff7e8}
.tag.p2{color:var(--ink3)}
.tag.new{color:var(--acc);border-color:#bedaff;background:#f0f7ff}
.fd{border:1px solid var(--line);border-left:3px solid var(--ink3);border-radius:8px;
  padding:10px 14px;margin-bottom:9px}
.fd.blocker{border-left-color:var(--bad);background:#fffbfb}
.fd.p0{border-left-color:#ff7d00}
.fd.p1{border-left-color:#ffc53d}
.fd.p2{border-left-color:#c9cdd4}
.fd .hd{font-size:12.5px;color:var(--ink3);margin-bottom:4px}
.fd .hd b{color:var(--ink);font-size:13px}
.fd .ev{font-size:13px;color:var(--ink);margin:4px 0}
.fd p{font-size:12.6px;margin:3px 0}
.fd .act{color:var(--ink)}
.src{color:var(--ink3);font-size:11.8px}
.kv{font-size:13px;color:var(--ink2);margin:5px 0}
.kv b{color:var(--ink);font-weight:600}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px;color:var(--ink2)}
.empty{font-size:12.8px;color:var(--ink3)}
footer{margin-top:22px;font-size:12.5px;line-height:1.9;color:var(--ink2);
  background:#fff;border:1px dashed var(--line);border-radius:10px;padding:14px 18px}
footer b{color:var(--ink)}
details{margin:6px 0}
summary{cursor:pointer;font-size:12.6px;color:var(--ink2)}
"""


# ---------------------------------------------------------------- 基础工具


def as_list(value):
    return value if isinstance(value, list) else []


def as_dict(value):
    return value if isinstance(value, dict) else {}


def s(value):
    if value is None:
        return ""
    return str(value).strip()


def num(value):
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return int(f) if f.is_integer() else round(f, 1)


def md_escape(value):
    """Markdown 动态文本也做 HTML 实体转义：贴进支持内联 HTML 的文档渲染器时不执行标签。"""
    return s(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def md_cell(value):
    return md_escape(value).replace("|", "\\|").replace("\n", " ")


def md_text(value):
    return md_escape(value).replace("\n", " ")


def page_url(base_url, pg_id):
    if not base_url or not pg_id:
        return ""
    return base_url.rstrip("/") + "/page/" + str(pg_id)


def load_json(path, label):
    if not os.path.exists(path):
        return None, "未找到{}：{}".format(label, path)
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f), ""
    except (OSError, ValueError) as exc:
        return None, "{}无法解析（{}）：{}".format(label, path, exc)


def grade_class(grade):
    return GRADE_CLASS.get(s(grade), "mid")


PAGE_VERDICT_LABEL = {
    "blocker": "有阻断", "warn": "有风险", "ok": "就绪",
    "unavailable": "不可用", "blocked": "不可用",
}


def page_verdict_label(value):
    raw = s(value)
    return PAGE_VERDICT_LABEL.get(raw.lower(), raw)


# ---------------------------------------------------------------- 联动筛选器


def _cd_ids(items):
    out = []
    for item in as_list(items):
        if isinstance(item, dict):
            cd = s(item.get("cdId") or item.get("id"))
        else:
            cd = s(item)
        if cd:
            out.append(cd)
    return out


def linkage_metadata(page):
    """页面的联动筛选器信息。

    返回 (ids, enumerable, count)：
    - ids：筛选栏内（inFilterBar）且有关联卡片（linkedCardCount>0）的 cdId，外加 facts 里的显式清单；
    - enumerable：是否拿得到 cdId 清单（只有数量时为 False，无法机械校验具体 cdId）；
    - count：体检产出的联动筛选器数量（取不到为 None）。
    """
    page = as_dict(page)
    facts = as_dict(page.get("facts"))
    ids = []
    enumerable = False

    cards = page.get("cards")
    if not isinstance(cards, list):
        cards = facts.get("cards")
    if isinstance(cards, list):
        enumerable = True
        for card in cards:
            card = as_dict(card)
            cd = s(card.get("cdId"))
            if not cd:
                continue
            if card.get("inFilterBar") is True and (num(card.get("linkedCardCount")) or 0) > 0:
                ids.append(cd)

    if facts.get("linkageSelectorIds") is not None:
        enumerable = True
        ids.extend(_cd_ids(facts.get("linkageSelectorIds")))
    elif isinstance(facts.get("linkageSelectors"), list):
        enumerable = True
        ids.extend(_cd_ids(facts.get("linkageSelectors")))
    if page.get("linkageSelectorIds") is not None:
        enumerable = True
        ids.extend(_cd_ids(page.get("linkageSelectorIds")))

    value = facts.get("linkageSelectors")
    if isinstance(value, list):
        count = len(value)
    else:
        count = num(value)
    return set(x for x in ids if x), enumerable, count


def linkage_selector_ids(page):
    return linkage_metadata(page)[0]


def linkage_filter_count(page):
    return linkage_metadata(page)[2]


# ---------------------------------------------------------------- 校验


def _walk_strings(obj, path=""):
    if isinstance(obj, str):
        yield path, obj
    elif isinstance(obj, dict):
        for key, value in obj.items():
            if s(key).startswith("_"):
                continue
            child = "{}.{}".format(path, key) if path else s(key)
            for item in _walk_strings(value, child):
                yield item
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            for item in _walk_strings(value, "{}[{}]".format(path, index)):
                yield item


def validate(audit, advice):
    """返回 (errors, warnings)。errors 非空即不允许输出最终报告。"""
    errors = []
    warnings = []

    if not isinstance(advice, dict):
        return ["建议文件顶层必须是 JSON 对象"], warnings

    for key in REQUIRED_KEYS:
        if key not in advice:
            errors.append("缺少必填字段：{}".format(key))

    for path, value in _walk_strings(advice):
        if PLACEHOLDER_RE.match(value.strip()):
            errors.append("字段仍是模板占位符：{} = {}".format(path, value.strip()))

    audit_meta = as_dict(audit.get("meta"))
    built_at = s(audit_meta.get("builtAt"))
    advice_built_at = s(advice.get("auditBuiltAt"))
    if advice_built_at and built_at and advice_built_at != built_at:
        errors.append(
            "建议基于旧体检：advice.auditBuiltAt={!r} 与 audit.meta.builtAt={!r} 不一致，请重新生成建议".format(
                advice_built_at, built_at))

    if not s(advice.get("scenario")):
        errors.append("scenario 不能为空")
    scope = s(advice.get("businessScope"))
    if not scope:
        errors.append("businessScope 不能为空")
    elif len(scope) > 300:
        warnings.append("businessScope 有 {} 个字符（建议 ≤300），洞察Agent 业务范围可能被截断".format(len(scope)))

    mode = advice.get("mode")
    primary = s(mode.get("primary")) if isinstance(mode, dict) else s(mode)
    if not primary:
        errors.append("mode.primary 不能为空")
    elif primary not in MODES:
        errors.append("mode.primary={!r} 不是五模式之一（{}）".format(primary, " / ".join(MODES)))

    pages = [p for p in as_list(audit.get("pages")) if isinstance(p, dict)]
    page_ids = [s(p.get("pgId")) for p in pages]
    page_by_id = {s(p.get("pgId")): p for p in pages}

    findings = [f for f in as_list(audit.get("findings")) if isinstance(f, dict)]
    finding_by_id = {s(f.get("id")): f for f in findings}
    finding_ids = set(finding_by_id)

    arch = [a for a in as_list(advice.get("targetArchitecture")) if isinstance(a, dict)]
    if not arch:
        errors.append("targetArchitecture 必须至少一层")

    page_actions = [a for a in as_list(advice.get("pageActions")) if isinstance(a, dict)]
    if not page_actions:
        errors.append("pageActions 至少需要一条")

    def check_evidence(owner, evidence, where):
        if not isinstance(evidence, list):
            errors.append("{} 的 evidence 必须是数组".format(where))
            return
        for ref in evidence:
            ref = s(ref)
            if not ref:
                errors.append("{} 的 evidence 含空值".format(where))
            elif ref not in finding_ids:
                errors.append("{} 引用了不存在的 finding：{}（{} 里没有这条证据）".format(where, ref, "insight-audit.json"))

    new_actions = []
    for index, action in enumerate(page_actions):
        where = "pageActions[{}]".format(index)
        pg_id = s(action.get("pgId"))
        label = s(action.get("name")) or pg_id
        if not pg_id:
            errors.append("{} 缺少 pgId".format(where))
        elif pg_id != "NEW" and pg_id not in page_by_id:
            errors.append("{} 的 pgId={!r} 不在体检的看板里（可用：{}；新建页写 NEW）".format(
                where, pg_id, "、".join(page_ids) or "无"))
        verdict = s(action.get("verdict"))
        if verdict not in VERDICTS:
            errors.append("{} 的 verdict={!r} 不在 {} 内".format(where, verdict, " / ".join(VERDICTS)))
        priority = s(action.get("priority"))
        if priority not in PRIORITIES:
            errors.append("{} 的 priority={!r} 不在 P0/P1/P2 内".format(where, priority))
        check_evidence(label, action.get("evidence", []), where)

        if pg_id == "NEW":
            new_actions.append((where, action))
            if not s(action.get("name")):
                errors.append("{} 是新建页，必须写 name（建议的新看板名）".format(where))
            actions = [s(x) for x in as_list(action.get("actions")) if s(x)]
            if not actions:
                errors.append("{} 是新建页，actions 不能为空（禁止只写“新建一个看板”）".format(where))
            if not s(action.get("expectedEffect")):
                errors.append("{} 是新建页，必须写 expectedEffect".format(where))
            if verdict and verdict != "新建":
                errors.append("{} 的 pgId=NEW 与 verdict={!r} 不一致，应写 新建".format(where, verdict))

    arch_new_layers = [a for a in arch if "NEW" in [s(x) for x in as_list(a.get("pages"))]]
    if arch_new_layers and not new_actions:
        errors.append("targetArchitecture 引用了 NEW，但 pageActions 没有 pgId=NEW 的新建页条目")
    if new_actions:
        new_layers = arch_new_layers
        if not new_layers:
            errors.append("pageActions 里新建了页面，但 targetArchitecture 没有引用 NEW（需写清层级与目的）")
        for layer in new_layers:
            if not s(layer.get("layer")) or not s(layer.get("purpose")):
                errors.append("targetArchitecture 引用 NEW 的层级必须写清 layer 与 purpose")

    covered_pages = {s(a.get("pgId")) for a in page_actions}
    missing_pages = [pg for pg in page_ids if pg and pg not in covered_pages]
    if missing_pages:
        errors.append("以下看板没有逐页动作（保留/改造/拆分/合并/移出）：{}——每个入选看板都要有结论".format(
            "、".join(missing_pages)))

    cross_actions = [a for a in as_list(advice.get("crossPageActions")) if isinstance(a, dict)]
    p0_evidence = set()
    for index, action in enumerate(page_actions):
        if s(action.get("priority")) == "P0":
            p0_evidence.update(s(x) for x in as_list(action.get("evidence")))
    for index, action in enumerate(cross_actions):
        where = "crossPageActions[{}]".format(index)
        priority = s(action.get("priority"))
        if priority not in PRIORITIES:
            errors.append("{} 的 priority={!r} 不在 P0/P1/P2 内".format(where, priority))
        if priority == "P0":
            p0_evidence.update(s(x) for x in as_list(action.get("evidence")))
        check_evidence(s(action.get("type")) or "跨页动作", action.get("evidence", []), where)
        if not s(action.get("action")):
            errors.append("{} 缺少 action 描述".format(where))
        for pg_id in as_list(action.get("pages")):
            if s(pg_id) != "NEW" and s(pg_id) and s(pg_id) not in page_by_id:
                warnings.append("{} 的 pages 引用了体检里没有的看板：{}".format(where, s(pg_id)))

    blockers = [f for f in findings if s(f.get("level")).lower() == "blocker"]
    uncovered = [s(f.get("id")) for f in blockers if s(f.get("id")) not in p0_evidence]
    if uncovered:
        errors.append("以下阻断项没有任何 P0 逐页/跨页动作覆盖：{}（每条阻断项必须有 P0 动作）".format(
            "、".join(uncovered)))

    config = as_dict(advice.get("configHandoff"))
    for index, item in enumerate(as_list(config.get("linkageFilters"))):
        item = as_dict(item)
        where = "configHandoff.linkageFilters[{}]".format(index)
        pg_id = s(item.get("pgId"))
        cd_id = s(item.get("cdId"))
        if not pg_id:
            errors.append("{} 缺少 pgId".format(where))
            continue
        if not cd_id:
            errors.append("{} 缺少 cdId".format(where))
            continue
        if pg_id == "NEW":
            if not s(item.get("name")) or not s(item.get("field")):
                errors.append("{} 指向新建页，必须写清 name 与 field".format(where))
            continue
        if pg_id not in page_by_id:
            errors.append("{} 的 pgId={!r} 不在体检的看板里".format(where, pg_id))
            continue
        page = page_by_id[pg_id]
        page_label = s(page.get("name")) or pg_id
        valid, enumerable, count = linkage_metadata(page)
        if enumerable:
            if cd_id not in valid:
                errors.append(
                    "{} 的 cdId={!r} 不是《{}》的联动筛选器（该页可用联动筛选器：{}）；"
                    "只接受筛选栏内且有关联卡片的筛选器".format(
                        where, cd_id, page_label, "、".join(sorted(valid)) or "无"))
        elif count == 0:
            errors.append("{} 指向的《{}》没有联动筛选器（0 个），不能作为配置来源（R-02）".format(
                where, page_label))
        elif count is None:
            warnings.append("{}：《{}》未提供联动筛选器信息，cdId={!r} 无法机械校验，请人工核对".format(
                where, page_label, cd_id))
        else:
            warnings.append(
                "{}：《{}》体检产物只有联动筛选器数量（{} 个）没有 cdId 清单，"
                "已跳过 cdId 机械校验，请人工核对 {!r}".format(where, page_label, count, cd_id))

    agent_type = s(config.get("agentType"))
    if not agent_type:
        errors.append("configHandoff.agentType 不能为空（探索型/报告型/混合型）——"
                      "先按 references/insight-agent-thinking-guide.md 判断 Agent 类型")
    elif agent_type not in AGENT_TYPES:
        errors.append("configHandoff.agentType={!r} 不在 {} 内".format(
            agent_type, " / ".join(AGENT_TYPES)))
    if not s(config.get("defaultThinking")):
        errors.append("configHandoff.defaultThinking 不能为空——写探索型路径原则或报告型步骤序列")
    if not s(config.get("outputRequirements")):
        errors.append("configHandoff.outputRequirements 不能为空——写证据、格式、语言风格要求")

    step_plan = [as_dict(x) for x in as_list(config.get("stepPlan"))]
    exploratory_rules = [s(x) for x in as_list(config.get("exploratoryRules")) if s(x)]
    report_framework = [s(x) for x in as_list(config.get("reportFramework")) if s(x)]
    question_examples = [s(x) for x in as_list(config.get("questionExamples")) if s(x)]

    if agent_type == "报告型":
        if len(step_plan) < 2:
            errors.append("报告型 Agent 的 stepPlan 至少 2 步（当前 {} 步）".format(len(step_plan)))
        if len(report_framework) < 3:
            errors.append("报告型 Agent 的 reportFramework 至少 3 章（当前 {} 章）".format(
                len(report_framework)))
        if len(question_examples) < 3:
            errors.append("报告型 Agent 的 questionExamples 至少 3 个（当前 {} 个）".format(
                len(question_examples)))
    elif agent_type == "探索型":
        if len(exploratory_rules) < 2:
            errors.append("探索型 Agent 的 exploratoryRules 至少 2 条路径原则（当前 {} 条）".format(
                len(exploratory_rules)))
    elif agent_type == "混合型":
        if not exploratory_rules:
            errors.append("混合型 Agent 至少需要 1 条 exploratoryRules")
        if not step_plan:
            errors.append("混合型 Agent 至少需要 1 步 stepPlan（报告型专家用）")
        if not report_framework:
            errors.append("混合型 Agent 至少需要 1 章 reportFramework")
        if not question_examples:
            errors.append("混合型 Agent 至少需要 1 个 questionExamples")

    seen_steps = set()
    for index, step in enumerate(step_plan):
        where = "configHandoff.stepPlan[{}]".format(index)
        step_no = num(step.get("step"))
        if not step_no or step_no <= 0:
            errors.append("{} 的 step 必须是正整数".format(where))
        elif step_no in seen_steps:
            errors.append("{} 的 step={} 重复".format(where, step_no))
        else:
            seen_steps.add(step_no)
        if not s(step.get("goal")):
            errors.append("{} 缺少 goal（这一步解决什么问题）".format(where))
        if not s(step.get("output")):
            errors.append("{} 缺少 output（本步结论 + 数据范围 + 证据）".format(where))
        if not s(step.get("nextIf")):
            errors.append("{} 缺少 nextIf（进入下一步的条件）".format(where))
        if not s(step.get("stopIf")):
            errors.append("{} 缺少 stopIf（终止条件）".format(where))
        dashboards = [s(x) for x in as_list(step.get("dashboards")) if s(x)]
        if not dashboards:
            errors.append("{} 缺少 dashboards（这一步看哪张看板）".format(where))
        for pg_id in dashboards:
            if pg_id != "NEW" and pg_id not in page_by_id:
                errors.append("{} 的 dashboards 引用了体检里没有的看板：{}".format(where, pg_id))
        if not [s(x) for x in as_list(step.get("coreQuestions")) if s(x)]:
            warnings.append("{} 没有 coreQuestions（建议写 2-3 个本步核心问题）".format(where))

    page_count = num(audit_meta.get("pageCount")) or len(pages)
    max_pages = num(audit_meta.get("maxPages")) or 10
    if page_count > max_pages:
        warnings.append("看板数 {} 超过 {} 页上限（R-01），报告会单列阻断项".format(page_count, max_pages))
    inputs = as_dict(audit_meta.get("inputs"))
    if inputs.get("samples") is False:
        warnings.append("未采样卡片数据：明细行数“未实测”，上下文风险无法机械确认")

    return errors, warnings


# ---------------------------------------------------------------- 视图组装


def build_view(audit, advice, draft, base_url):
    meta = as_dict(audit.get("meta"))
    pages = [p for p in as_list(audit.get("pages")) if isinstance(p, dict)]
    findings = [f for f in as_list(audit.get("findings")) if isinstance(f, dict)]
    portfolio = as_dict(audit.get("portfolio"))
    advice = advice if isinstance(advice, dict) else {}

    def sort_key(f):
        return (LEVEL_ORDER.get(s(f.get("level")).lower(), 9), s(f.get("id")))

    findings = sorted(findings, key=sort_key)

    page_by_id = {s(p.get("pgId")): p for p in pages}

    new_page_name = "新建页"
    for action in as_list(advice.get("pageActions")):
        if isinstance(action, dict) and s(action.get("pgId")) == "NEW" and s(action.get("name")):
            new_page_name = s(action.get("name"))
            break

    def page_name(pg_id):
        pg_id = s(pg_id)
        if pg_id == "NEW":
            return new_page_name
        page = page_by_id.get(pg_id)
        return (s(page.get("name")) if page else "") or pg_id

    def page_link(pg_id):
        if s(pg_id) == "NEW":
            return ""
        return page_url(base_url, pg_id)

    page_rows = []
    for page in pages:
        scores = as_dict(page.get("scores"))
        dims = []
        for key, label, weight in DIMENSIONS:
            dims.append({"key": key, "label": label, "max": weight, "value": num(scores.get(key))})
        page_rows.append({
            "pgId": s(page.get("pgId")),
            "name": s(page.get("name")) or s(page.get("pgId")),
            "url": page_link(page.get("pgId")),
            "verdict": s(page.get("verdict")),
            "verdictLabel": page_verdict_label(page.get("verdict")),
            "total": num(page.get("total")),
            "grade": s(page.get("grade")),
            "dims": dims,
            "facts": as_dict(page.get("facts")),
            "findingIds": [s(x) for x in as_list(page.get("findings")) if s(x)],
            "unavailable": s(page.get("verdict")).lower() in ("unavailable", "⛔", "blocked"),
        })

    overall = num(portfolio.get("overall"))
    if overall is None:
        overall = num(portfolio.get("score"))

    counts = {}
    for f in findings:
        level = s(f.get("level")).lower()
        counts[level] = counts.get(level, 0) + 1

    blockers = [f for f in findings if s(f.get("level")).lower() == "blocker"]

    summary = []
    usable = [r for r in page_rows if not r["unavailable"]]
    summary.append("看板组合：{} 张看板，可用 {} 张{}。".format(
        len(page_rows), len(usable),
        "，不可用 {} 张（不参与页级均分）".format(len(page_rows) - len(usable)) if len(usable) != len(page_rows) else ""))
    level_bits = ["{} {}".format(len([f for f in findings if s(f.get("level")).lower() == lv]),
                                 LEVEL_LABEL[lv]) for lv in ["blocker", "p0", "p1", "p2"]]
    summary.append("结构体检：{} 条发现（{}）。".format(len(findings), " / ".join(level_bits)))
    if overall is not None:
        summary.append("结构得分：{}/100 · {}——只衡量结构可执行性，不衡量业务价值。".format(
            overall, s(portfolio.get("grade")) or "未评级"))
    if not draft:
        mode = advice.get("mode")
        primary = s(mode.get("primary")) if isinstance(mode, dict) else s(mode)
        if primary:
            summary.append("建议主模式：{}。".format(primary))
        # “先改这三件事”直接取机械体检的 P0/阻断动作，避免 AI 把 P2 动作排到前面
        top_actions = []
        for finding in findings:
            if s(finding.get("level")).lower() not in ("blocker", "p0"):
                continue
            item = s(finding.get("action"))
            if item and item not in top_actions and len(top_actions) < 3:
                top_actions.append(item)
        for action in as_list(advice.get("crossPageActions")):
            if not isinstance(action, dict) or s(action.get("priority")) != "P0":
                continue
            item = s(action.get("action"))
            if item and item not in top_actions and len(top_actions) < 3:
                top_actions.append(item)
        if top_actions:
            summary.append("优先做这几件事：{}。".format("；".join(top_actions[:3])))

    # 发现分组
    groups = []
    for level in LEVEL_GROUPS:
        items = [f for f in findings if s(f.get("level")).lower() == level]
        if items:
            groups.append({"level": level, "label": LEVEL_LABEL[level], "items": items})
    other = [f for f in findings if s(f.get("level")).lower() not in LEVEL_GROUPS]
    if other:
        groups.append({"level": "info", "label": "其他", "items": other})

    # 建议部分
    mode_view = None
    if isinstance(advice.get("mode"), dict) or s(advice.get("mode")):
        mode = advice.get("mode")
        if isinstance(mode, dict):
            mode_view = {
                "primary": s(mode.get("primary")),
                "alternatives": [s(x) for x in as_list(mode.get("alternatives")) if s(x)],
                "reason": s(mode.get("reason")),
            }
        else:
            mode_view = {"primary": s(mode), "alternatives": [], "reason": ""}

    arch_view = []
    for layer in as_list(advice.get("targetArchitecture")):
        layer = as_dict(layer)
        arch_view.append({
            "layer": s(layer.get("layer")) or "未命名层",
            "purpose": s(layer.get("purpose")),
            "pages": [{"pgId": s(x), "name": page_name(x), "url": page_link(x)} for x in as_list(layer.get("pages"))],
            "linkage": [s(x) for x in as_list(layer.get("linkageFilters")) if s(x)],
            "newPage": bool(layer.get("newPage")),
        })

    finding_map = {s(f.get("id")): f for f in findings}

    def refs(ids):
        out = []
        for ref in as_list(ids):
            ref = s(ref)
            if not ref:
                continue
            finding = finding_map.get(ref, {})
            out.append({"id": ref, "rule": s(finding.get("rule")), "level": s(finding.get("level")).lower()})
        return out

    page_actions_view = []
    for action in as_list(advice.get("pageActions")):
        action = as_dict(action)
        pg_id = s(action.get("pgId"))
        page_actions_view.append({
            "pgId": pg_id,
            "name": s(action.get("name")) or page_name(pg_id),
            "url": page_link(pg_id) if pg_id != "NEW" else "",
            "verdict": s(action.get("verdict")),
            "priority": s(action.get("priority")),
            "actions": [s(x) for x in as_list(action.get("actions")) if s(x)],
            "evidence": refs(action.get("evidence")),
            "expectedEffect": s(action.get("expectedEffect")),
        })

    cross_view = []
    for action in as_list(advice.get("crossPageActions")):
        action = as_dict(action)
        cross_view.append({
            "type": s(action.get("type")),
            "priority": s(action.get("priority")),
            "action": s(action.get("action")),
            "pages": [{"pgId": s(x), "name": page_name(x)} for x in as_list(action.get("pages")) if s(x)],
            "evidence": refs(action.get("evidence")),
        })

    config = as_dict(advice.get("configHandoff"))
    linkage_view = []
    for item in as_list(config.get("linkageFilters")):
        item = as_dict(item)
        pg_id = s(item.get("pgId"))
        linkage_view.append({
            "pgId": pg_id,
            "name": s(item.get("name")),
            "field": s(item.get("field")),
            "cdId": s(item.get("cdId")),
            "pageName": page_name(pg_id),
            "url": page_link(pg_id) if pg_id != "NEW" else "",
        })

    step_plan_view = []
    for step in as_list(config.get("stepPlan")):
        step = as_dict(step)
        dashboards = [{"pgId": s(x), "name": page_name(x), "url": page_link(x)}
                      for x in as_list(step.get("dashboards")) if s(x)]
        step_plan_view.append({
            "step": num(step.get("step")),
            "goal": s(step.get("goal")),
            "dashboards": dashboards,
            "coreQuestions": [s(x) for x in as_list(step.get("coreQuestions")) if s(x)],
            "cards": [s(x) for x in as_list(step.get("cards")) if s(x)],
            "filters": [s(x) for x in as_list(step.get("filters")) if s(x)],
            "output": s(step.get("output")),
            "nextIf": s(step.get("nextIf")),
            "stopIf": s(step.get("stopIf")),
        })

    experts = []
    for role in as_list(config.get("expertRoles")):
        role = as_dict(role)
        experts.append({"name": s(role.get("name")), "scope": s(role.get("scope")), "reason": s(role.get("reason"))})

    roadmap = []
    for phase in as_list(advice.get("roadmap")):
        phase = as_dict(phase)
        roadmap.append({
            "phase": s(phase.get("phase")),
            "items": [s(x) for x in as_list(phase.get("items")) if s(x)],
            "effort": s(phase.get("effort")),
        })

    assets = []
    for row in page_rows:
        facts = row["facts"]
        cards = as_list(facts.get("cards")) if isinstance(facts.get("cards"), list) else []
        card_items = []
        for card in cards:
            card = as_dict(card)
            name = s(card.get("name")) or s(card.get("title"))
            if name:
                card_items.append({"name": name, "cdId": s(card.get("cdId")), "type": s(card.get("type"))})
        assets.append({
            "pgId": row["pgId"],
            "name": row["name"],
            "url": row["url"],
            "verdict": row["verdict"],
            "verdictLabel": row["verdictLabel"],
            "total": row["total"],
            "grade": row["grade"],
            "dataCards": num(facts.get("dataCards")),
            "selectors": num(facts.get("selectors")),
            "linkage": linkage_filter_count({"facts": facts}),
            "maxRawRows": num(facts.get("maxRawRows")),
            "mtime": s(facts.get("mtime")),
            "cards": card_items,
            "findingIds": row["findingIds"],
        })

    rule_sources = []
    seen = set()
    for f in findings:
        rule = s(f.get("rule"))
        source = s(f.get("source"))
        key = (rule, source)
        if key in seen:
            continue
        seen.add(key)
        if rule or source:
            rule_sources.append({"rule": rule, "source": source})

    inputs = as_dict(meta.get("inputs"))
    env_notes = []
    if inputs.get("pageCheck") is False:
        env_notes.append("未接入 check_pages.py 产物：适检结论缺失，页面可用性仅按体检结构判断。")
    if inputs.get("formulas") is False:
        env_notes.append("未接入 check_formulas.py 产物：跨页口径冲突可能漏检。")
    if inputs.get("samples") is False:
        env_notes.append("未采样卡片数据：明细行数“未实测”，上下文风险需要人工确认（R-06）。")
    env_notes.append("环境前提（BI 8.1+ / 仪表板洞察可用 / 洞察Agent License）CLI 无法验证，需用户确认（R-03）。")

    return {
        "draft": draft,
        "title": "洞察Agent 看板结构体检（草稿）" if draft else "洞察Agent 看板就绪诊断报告",
        "built_at": s(meta.get("builtAt")),
        "builder_version": s(meta.get("builderVersion")),
        "scenario": s(advice.get("scenario")) or s(meta.get("scenario")),
        "scenario_from_audit": not s(advice.get("scenario")) and bool(s(meta.get("scenario"))),
        "businessScope": s(advice.get("businessScope")),
        "pageCount": num(meta.get("pageCount")) or len(pages),
        "maxPages": num(meta.get("maxPages")) or 10,
        "overall": overall,
        "grade": s(portfolio.get("grade")),
        "pageScore": num(portfolio.get("score")),
        "counts": counts,
        "blockers": blockers,
        "summary": summary,
        "groups": groups,
        "pages": page_rows,
        "mode": mode_view,
        "arch": arch_view,
        "crossActions": cross_view,
        "pageActions": page_actions_view,
        "config": {
            "linkage": linkage_view,
            "businessScope": s(config.get("businessScope")),
            "agentType": s(config.get("agentType")),
            "defaultThinking": s(config.get("defaultThinking")),
            "stepPlan": step_plan_view,
            "exploratoryRules": [s(x) for x in as_list(config.get("exploratoryRules")) if s(x)],
            "reportFramework": [re.sub(r"^\s*(?:\d+[.、]|[-*])\s*", "", s(x))
                                for x in as_list(config.get("reportFramework")) if s(x)],
            "questionExamples": [s(x) for x in as_list(config.get("questionExamples")) if s(x)],
            "outputRequirements": s(config.get("outputRequirements")),
            "knowledgeGaps": [s(x) for x in as_list(config.get("businessKnowledgeGaps")) if s(x)],
            "expertRoles": experts,
        },
        "roadmap": roadmap,
        "openQuestions": [s(x) for x in as_list(advice.get("openQuestions")) if s(x)],
        "assets": assets,
        "ruleSources": rule_sources,
        "envNotes": env_notes,
    }


# ---------------------------------------------------------------- Markdown


def render_markdown(view):
    out = []
    add = out.append
    add("# {}".format(view["title"]))
    add("")
    add("> 目标场景：{}".format(md_text(view["scenario"]) or "待确认"))
    add("> 诊断范围：{} 张看板 · 生成于 {}{}".format(
        view["pageCount"], view["built_at"] or "—",
        " · 体检版本 {}".format(view["builder_version"]) if view["builder_version"] else ""))
    if view["overall"] is not None:
        add("> 结论：{}/100 · {}".format(view["overall"], view["grade"] or "未评级"))
    else:
        add("> 结论：结构体检（未评分）")
    add("")

    if view["draft"]:
        add("> ⚠️ 这是**结构体检草稿**：尚未生成整合建议。"
            "确认体检事实后，再补 `insight-advice.json` 并运行最终报告。")
        add("")

    add("## 1. 结论摘要")
    add("")
    for line in view["summary"]:
        add("- {}".format(md_text(line)))
    add("")
    add("### 先解决这些阻断项")
    add("")
    if view["blockers"]:
        for f in view["blockers"]:
            add("- **{} · {}** {}".format(s(f.get("id")), s(f.get("rule")),
                                          md_text(f.get("evidence")) or md_text(f.get("requirement"))))
            if s(f.get("action")):
                add("  - 动作：{}".format(md_text(f.get("action"))))
    else:
        add("- 无阻断项。")
    add("")

    add("## 2. 目标场景与看板组合")
    add("")
    add("- 目标场景：{}".format(md_text(view["scenario"]) or "待确认"))
    if view["scenario_from_audit"]:
        add("  - 说明：场景取自体检产物，建议在建议文件中用业务语言复述。")
    add("- 业务范围：{}".format(md_text(view["businessScope"]) or "待确认（R-04：业务范围必须清晰）"))
    add("- 看板组合：{} 张（官方上限 {} 张）".format(view["pageCount"], view["maxPages"]))
    add("")
    add("| 看板 | 体检结论 | 总分 | 等级 |")
    add("|---|---|---:|---|")
    for page in view["pages"]:
        name = "[{}]({})".format(md_cell(page["name"]), page["url"]) if page["url"] else md_cell(page["name"])
        add("| {} | {} | {} | {} |".format(
            name, md_cell(page["verdictLabel"]) or "—",
            page["total"] if page["total"] is not None else "—",
            md_cell(page["grade"]) or "—"))
    add("")
    add("> 环境前提：")
    for note in view["envNotes"]:
        add("> - {}".format(md_text(note)))
    add("")

    add("## 3. 体检总表")
    add("")
    header = "| 看板 | " + " | ".join(label for _, label, _ in DIMENSIONS) + " | 总分 | 等级 |"
    add(header)
    add("|---|" + "|".join(["---:"] * len(DIMENSIONS)) + "|---:|---|")
    for page in view["pages"]:
        cells = []
        for dim in page["dims"]:
            cells.append("{}/{}".format(dim["value"], dim["max"]) if dim["value"] is not None else "—")
        add("| {} | {} | {} | {} |".format(
            md_cell(page["name"]), " | ".join(cells),
            page["total"] if page["total"] is not None else "—",
            md_cell(page["grade"]) or "—"))
    add("")
    add("> 权重：{}。评分只衡量结构可执行性，不衡量业务价值。".format(
        " / ".join("{} {}".format(label, weight) for _, label, weight in DIMENSIONS)))
    add("> 含 P0/阻断的看板，总分按规则封顶 64（维度分是原始得分；原始总分见 insight-audit.json 的 rawTotal）。")
    add("")

    add("## 4. 关键发现")
    add("")
    if not view["groups"]:
        add("- 体检未产出发现。")
        add("")
    for group in view["groups"]:
        add("### {}".format(group["label"]))
        add("")
        for f in group["items"]:
            add("- **{} · {} · {}**{}".format(
                s(f.get("id")), s(f.get("rule")) or "无规则编号", group["label"],
                " · `{}`".format(md_text(f.get("scope"))) if s(f.get("scope")) else ""))
            if s(f.get("evidence")):
                add("  - 证据：{}".format(md_text(f.get("evidence"))))
            if s(f.get("requirement")):
                add("  - 要求：{}".format(md_text(f.get("requirement"))))
            if s(f.get("action")):
                add("  - 动作：{}".format(md_text(f.get("action"))))
            if s(f.get("source")):
                add("  - 来源：{}".format(md_text(f.get("source"))))
        add("")

    add("## 5. 整合建议")
    add("")
    if view["draft"]:
        add("**尚未生成整合建议。** 本稿只做结构体检：评分、发现与看板卡片清单；"
            "模式选择、目标架构、逐页动作与配置衔接需要基于用户确认的目标问题单独生成。")
        add("")
    else:
        mode = view["mode"] or {}
        add("### 推荐模式")
        add("")
        add("- 主模式：{}".format(md_text(mode.get("primary")) or "未填写"))
        if mode.get("alternatives"):
            add("- 备选：{}".format("、".join(md_text(x) for x in mode["alternatives"])))
        if mode.get("reason"):
            add("- 理由：{}".format(md_text(mode["reason"])))
        add("")
        add("### 目标架构")
        add("")
        if view["arch"]:
            add("| 层级 | 承担看板 | 解决什么 | 联动筛选器 |")
            add("|---|---|---|---|")
            for layer in view["arch"]:
                pages = "、".join(
                    "[{}]({})".format(md_cell(p["name"]), p["url"]) if p["url"] else md_cell(p["name"])
                    for p in layer["pages"]) or "—"
                add("| {}{} | {} | {} | {} |".format(
                    md_cell(layer["layer"]), "（新建）" if layer["newPage"] else "",
                    pages, md_cell(layer["purpose"]) or "—",
                    md_cell("、".join(layer["linkage"])) or "—"))
        else:
            add("- 未填写目标架构。")
        add("")
        add("### 跨页动作")
        add("")
        if view["crossActions"]:
            add("| 类型 | 优先级 | 动作 | 涉及看板 | 证据 |")
            add("|---|---|---|---|---|")
            for action in view["crossActions"]:
                evidence = "、".join(
                    "{}（{}）".format(r["id"], r["rule"]) if r["rule"] else r["id"] for r in action["evidence"]) or "—"
                pages = "、".join(md_cell(p["name"]) for p in action["pages"]) or "—"
                add("| {} | {} | {} | {} | {} |".format(
                    md_cell(action["type"]) or "—", md_cell(action["priority"]) or "—",
                    md_cell(action["action"]) or "—", pages, evidence))
        else:
            add("- 无跨页动作。")
        add("")

    add("## 6. 逐页调整清单")
    add("")
    if view["draft"]:
        add("**尚未生成整合建议。** 逐页动作（保留 / 改造 / 拆分 / 合并 / 新建 / 移出）需要 AI 基于体检事实给出。")
        add("")
        add("体检已标记的待处理页面：")
        add("")
        for page in view["pages"]:
            if page["verdict"].lower() in ("ok", "✅", "ready"):
                continue
            add("- {}（{}）{}".format(
                md_cell(page["name"]), md_cell(page["verdictLabel"]) or "—",
                "：关联发现 " + "、".join(page["findingIds"]) if page["findingIds"] else ""))
        add("")
    elif not view["pageActions"]:
        add("- 未填写逐页动作。")
        add("")
    else:
        for action in view["pageActions"]:
            name = "[{}]({})".format(md_cell(action["name"]), action["url"]) if action["url"] else md_cell(action["name"])
            add("### {} · {}{}".format(name, action["verdict"] or "—", " · " + action["priority"]))
            add("")
            add("- 优先级：{}｜动作：{}".format(action["priority"] or "—", action["verdict"] or "—"))
            if action["actions"]:
                add("- 具体动作：")
                for item in action["actions"]:
                    add("  - {}".format(md_text(item)))
            if action["evidence"]:
                add("- 证据：{}".format("、".join(
                    "{}（{}）".format(r["id"], r["rule"]) if r["rule"] else r["id"] for r in action["evidence"])))
            if action["expectedEffect"]:
                add("- 预期效果：{}".format(md_text(action["expectedEffect"])))
            add("")

    add("## 7. 洞察Agent 配置衔接")
    add("")
    if view["draft"]:
        add("**尚未生成整合建议。** Agent 类型、分析思路、步骤计划、报告框架、用户提问示例、"
            "联动筛选器、业务范围、输出要求、知识缺口与专家角色都需要在建议文件中给出。")
        add("")
    else:
        config = view["config"]
        add("### Agent 类型与业务范围")
        add("")
        add("- Agent 类型：{}".format(md_text(config["agentType"]) or "未填写"))
        add("")
        add(md_text(config["businessScope"]) or "- 业务范围未填写。")
        add("")
        add("### 联动筛选器")
        add("")
        if config["linkage"]:
            add("| 看板 | 筛选器 | 字段 | cdId |")
            add("|---|---|---|---|")
            for item in config["linkage"]:
                page = "[{}]({})".format(md_cell(item["pageName"]), item["url"]) if item["url"] else md_cell(item["pageName"])
                add("| {} | {} | {} | `{}` |".format(
                    page, md_cell(item["name"]) or "—", md_cell(item["field"]) or "—",
                    md_cell(item["cdId"]) or "—"))
        else:
            add("- 未填写联动筛选器（每张看板至少需要一个，R-02）。")
        add("")
        add("### 分析思路")
        add("")
        add("**默认思路（可直接粘贴到 BI）：**")
        add("")
        add(md_text(config["defaultThinking"]) or "未填写")
        add("")
        if config["stepPlan"]:
            add("#### 步骤计划")
            add("")
            for step in config["stepPlan"]:
                add("**Step {}：{}**".format(step["step"], md_text(step["goal"]) or "（未写目标）"))
                add("")
                if step["dashboards"]:
                    boards = []
                    for board in step["dashboards"]:
                        boards.append("[{}]({})".format(md_cell(board["name"]), board["url"])
                                      if board["url"] else md_cell(board["name"]))
                    add("- 看板：{}".format("、".join(boards)))
                if step["coreQuestions"]:
                    add("- 核心问题：{}".format("；".join(md_text(x) for x in step["coreQuestions"])))
                if step["cards"]:
                    add("- 核心卡片：{}".format("、".join(md_text(x) for x in step["cards"])))
                if step["filters"]:
                    add("- 筛选参数：{}".format("、".join(md_text(x) for x in step["filters"])))
                add("- 本步输出：{}".format(md_text(step["output"]) or "未填写"))
                add("- 进入下一步：{}".format(md_text(step["nextIf"]) or "未填写"))
                add("- 终止条件：{}".format(md_text(step["stopIf"]) or "未填写"))
                add("")
        if config["exploratoryRules"]:
            add("#### 探索型路径原则")
            add("")
            for rule in config["exploratoryRules"]:
                add("- {}".format(md_text(rule)))
            add("")
        if config["reportFramework"]:
            add("### 报告交付框架")
            add("")
            for index, chapter in enumerate(config["reportFramework"], 1):
                add("{}. {}".format(index, md_text(chapter)))
            add("")
        if config["questionExamples"]:
            add("### 用户提问示例")
            add("")
            for example in config["questionExamples"]:
                add("- {}".format(md_text(example)))
            add("")
        add("### 输出要求")
        add("")
        add(md_text(config["outputRequirements"]) or "- 未填写。")
        add("")
        add("### 业务知识缺口")
        add("")
        if config["knowledgeGaps"]:
            for gap in config["knowledgeGaps"]:
                add("- {}".format(md_text(gap)))
        else:
            add("- 无（或未填写）。")
        add("")
        add("### 分析专家建议")
        add("")
        if config["expertRoles"]:
            for role in config["expertRoles"]:
                bits = [x for x in (role["scope"], role["reason"]) if x]
                add("- {}{}".format(md_text(role["name"]) or "未命名专家",
                                    "：" + md_text("；".join(bits)) if bits else ""))
        else:
            add("- 单域场景不建议硬拆专家；跨业务域时再拆。")
        add("")

    add("## 8. 落地路线图")
    add("")
    if view["draft"]:
        add("**尚未生成整合建议。** 路线图在建议确认后给出。")
        add("")
    elif view["roadmap"]:
        for phase in view["roadmap"]:
            add("### {}".format(md_text(phase["phase"]) or "未命名阶段"))
            add("")
            for item in phase["items"]:
                add("- {}".format(md_text(item)))
            if phase["effort"]:
                add("- 预估工作量：{}".format(md_text(phase["effort"])))
            add("")
    else:
        add("- 未填写路线图。")
        add("")

    add("## 9. 待确认问题")
    add("")
    if view["draft"]:
        add("**尚未生成整合建议。** 待确认问题（业务链路、异常阈值、责任部门映射）需要在建议文件中列出。")
        add("")
    elif view["openQuestions"]:
        for index, question in enumerate(view["openQuestions"], 1):
            add("{}. {}".format(index, md_text(question)))
        add("")
    else:
        add("- 无。")
        add("")

    add("## 附录 A：评分说明")
    add("")
    add("页级就绪度（100）：{}。".format(" / ".join("{} {}".format(label, weight) for _, label, weight in DIMENSIONS)))
    add("")
    add("总分 = 页级均分 × 60% + 组合级 × 40%；等级：≥80 可直接配置 / 65–79 小改后配置 / 50–64 需改造 / <50 不建议直接配置。")
    add("")
    add("阻断收敛：不可用页不进页级均分；任一页缺联动筛选器（R-02）时总分最高“需改造”；超过 10 页且未取舍或可用页为 0 → 封顶 49。")
    add("")
    add("## 附录 B：规则来源")
    add("")
    for item in RULE_SOURCES:
        add("- **{}**：{}".format(item[0], item[1]))
    if view["ruleSources"]:
        add("")
        add("本次报告引用的规则：")
        add("")
        for item in view["ruleSources"]:
            add("- {} {}".format(item["rule"] or "—", item["source"]))
    add("")
    add("## 附录 C：看板与卡片清单")
    add("")
    for asset in view["assets"]:
        name = "[{}]({})".format(md_cell(asset["name"]), asset["url"]) if asset["url"] else md_cell(asset["name"])
        add("### {}".format(name))
        add("")
        add("- pgId：`{}`｜体检结论：{}｜总分：{}｜等级：{}".format(
            asset["pgId"] or "—", md_cell(asset["verdictLabel"]) or "—",
            asset["total"] if asset["total"] is not None else "—",
            md_cell(asset["grade"]) or "—"))
        add("- 数据卡 {} 张｜筛选器 {} 个｜联动筛选器 {} 个｜明细最大行数 {}｜更新时间 {}".format(
            asset["dataCards"] if asset["dataCards"] is not None else "—",
            asset["selectors"] if asset["selectors"] is not None else "—",
            asset["linkage"] if asset["linkage"] is not None else "—",
            asset["maxRawRows"] if asset["maxRawRows"] is not None else "未实测",
            asset["mtime"] or "—"))
        if asset["findingIds"]:
            add("- 关联发现：{}".format("、".join(asset["findingIds"])))
        if asset["cards"]:
            names = [c["name"] for c in asset["cards"]]
            shown = names[:40]
            add("- 卡片（{} 张）：{}".format(len(names), "、".join(md_cell(x) for x in shown)))
            if len(names) > len(shown):
                add("  - 其余 {} 张见 BI 页面".format(len(names) - len(shown)))
        add("")

    add("---")
    add("")
    add("本报告是**诊断与建议**，不是已改造完成。按 P0 动作改完后可重新体检，并把本次 JSON 作为基线对比。")
    add("")
    return "\n".join(out)


# ---------------------------------------------------------------- HTML


def _h(value):
    return html.escape(s(value), quote=True)


def _link(name, url, cls="nm"):
    if url:
        return '<a class="{}" href="{}" target="_blank" rel="noopener">{}</a>'.format(
            cls, _h(url), _h(name))
    return '<span class="{}">{}</span>'.format(cls, _h(name))


def _html_hero(view):
    if view["overall"] is not None:
        score = '<div class="big">{}<small>/100</small></div>'.format(view["overall"])
        grade = '<span class="grade {}">{}</span>'.format(
            grade_class(view["grade"]), _h(view["grade"] or "未评级"))
    else:
        score = '<div class="big">—</div>'
        grade = '<span class="grade mid">未评分</span>'
    stats = [
        ('<div class="stat"><b>{}</b>看板</div>'.format(view["pageCount"])),
        ('<div class="stat bad"><b>{}</b>阻断项</div>'.format(len(view["blockers"]))),
        ('<div class="stat"><b>{}</b>P0</div>'.format(view["counts"].get("p0", 0))),
        ('<div class="stat"><b>{}</b>P1</div>'.format(view["counts"].get("p1", 0))),
    ]
    return ('<div class="hero">{}<div><div style="margin-bottom:6px">{}</div>'
            '<div class="meta">结构就绪度（只衡量可执行性）</div></div>'
            '<div class="stats">{}</div></div>').format(score, grade, "".join(stats))


def _html_blockers(view):
    if not view["blockers"]:
        return ""
    items = []
    for f in view["blockers"]:
        items.append("<li><b>{}</b> <span class=\"mono\">{}</span> · {}{}</li>".format(
            _h(f.get("id")), _h(f.get("rule")),
            _h(f.get("evidence") or f.get("requirement")),
            "　→ 动作：" + _h(f.get("action")) if s(f.get("action")) else ""))
    return ('<div class="banner"><h2>先解决这 {} 个阻断项（不解决，洞察Agent 无法稳定运行）</h2>'
            '<ul>{}</ul></div>').format(len(view["blockers"]), "".join(items))


def _html_score_table(view):
    head = "".join("<th>{}</th>".format(_h(label)) for _, label, _ in DIMENSIONS)
    rows = []
    for page in view["pages"]:
        cells = []
        for dim in page["dims"]:
            if dim["value"] is None:
                cells.append('<td class="num">—</td>')
                continue
            ratio = dim["value"] / float(dim["max"]) if dim["max"] else 0
            cls = "ok" if ratio >= 0.8 else ("mid" if ratio >= 0.6 else ("warn" if ratio >= 0.4 else "bad"))
            cells.append('<td class="num">{}<div class="bar {}"><span style="width:{:.0f}%"></span></div></td>'.format(
                dim["value"], cls, max(0, min(100, ratio * 100))))
        total = page["total"]
        if total is None:
            total_html = '<td class="num">—</td>'
        else:
            cls = "ok" if total >= 80 else ("mid" if total >= 65 else ("warn" if total >= 50 else "bad"))
            total_html = ('<td class="num"><b>{}</b><div class="bar {}"><span style="width:{}%"></span></div></td>'
                          .format(total, cls, max(0, min(100, total))))
        rows.append("<tr><td>{}{}</td>{}{}<td>{}</td></tr>".format(
            _link(page["name"], page["url"]),
            " " + _h(page["verdictLabel"]) if page["verdictLabel"] else "",
            "".join(cells), total_html, _h(page["grade"]) or "—"))
    return ('<table><thead><tr><th>看板</th>{}<th>总分</th><th>等级</th></tr></thead>'
            '<tbody>{}</tbody></table>').format(head, "".join(rows))


def _html_findings(view):
    if not view["groups"]:
        return '<p class="empty">体检未产出发现。</p>'
    blocks = []
    for group in view["groups"]:
        blocks.append("<h3>{}（{} 条）</h3>".format(_h(group["label"]), len(group["items"])))
        for f in group["items"]:
            level = group["level"]
            parts = ['<div class="fd {}">'.format(level)]
            parts.append('<div class="hd"><b>{}</b> <span class="mono">{}</span>'
                         '<span class="tag {}">{}</span>{}</div>'.format(
                             _h(f.get("id")), _h(f.get("rule")) or "无规则编号",
                             level, _h(group["label"]),
                             ' <span class="mono">{}</span>'.format(_h(f.get("scope"))) if s(f.get("scope")) else ""))
            if s(f.get("evidence")):
                parts.append('<p class="ev">证据：{}</p>'.format(_h(f.get("evidence"))))
            if s(f.get("requirement")):
                parts.append("<p>要求：{}</p>".format(_h(f.get("requirement"))))
            if s(f.get("action")):
                parts.append('<p class="act">动作：{}</p>'.format(_h(f.get("action"))))
            if s(f.get("source")):
                parts.append('<p class="src">来源：{}</p>'.format(_h(f.get("source"))))
            parts.append("</div>")
            blocks.append("".join(parts))
    return "".join(blocks)


def _html_advice(view):
    if view["draft"]:
        return ('<p class="empty">尚未生成整合建议。本稿只做结构体检；'
                '模式选择、目标架构、逐页动作与配置衔接需要基于用户确认的目标问题单独生成。</p>')
    mode = view["mode"] or {}
    parts = ["<h3>推荐模式</h3>"]
    parts.append('<p class="kv"><b>主模式：</b>{}</p>'.format(_h(mode.get("primary") or "未填写")))
    if mode.get("alternatives"):
        parts.append('<p class="kv"><b>备选：</b>{}</p>'.format(
            _h("、".join(mode["alternatives"]))))
    if mode.get("reason"):
        parts.append('<p class="kv"><b>理由：</b>{}</p>'.format(_h(mode["reason"])))

    parts.append("<h3>目标架构</h3>")
    if view["arch"]:
        rows = []
        for layer in view["arch"]:
            pages = "、".join(_link(p["name"], p["url"]) for p in layer["pages"]) or "—"
            rows.append("<tr><td>{}<span class=\"tag new\">新建</span></td><td>{}</td><td>{}</td><td class=\"mono\">{}</td></tr>".format(
                _h(layer["layer"]), pages, _h(layer["purpose"]) or "—",
                _h("、".join(layer["linkage"])) or "—") if layer["newPage"] else
                "<tr><td>{}</td><td>{}</td><td>{}</td><td class=\"mono\">{}</td></tr>".format(
                    _h(layer["layer"]), pages, _h(layer["purpose"]) or "—",
                    _h("、".join(layer["linkage"])) or "—"))
        parts.append("<table><thead><tr><th>层级</th><th>承担看板</th><th>解决什么</th>"
                     "<th>联动筛选器</th></tr></thead><tbody>{}</tbody></table>".format("".join(rows)))
    else:
        parts.append('<p class="empty">未填写目标架构。</p>')

    parts.append("<h3>跨页动作</h3>")
    if view["crossActions"]:
        rows = []
        for action in view["crossActions"]:
            evidence = "、".join(
                "{}（{}）".format(r["id"], r["rule"]) if r["rule"] else r["id"] for r in action["evidence"]) or "—"
            pages = "、".join(_h(p["name"]) for p in action["pages"]) or "—"
            rows.append("<tr><td>{}<span class=\"tag {}\">{}</span></td><td>{}</td><td>{}</td>"
                        "<td class=\"mono\">{}</td></tr>".format(
                            _h(action["type"]) or "—",
                            _h(action["priority"]).lower(), _h(action["priority"]),
                            _h(action["action"]) or "—", pages, _h(evidence)))
        parts.append("<table><thead><tr><th>类型</th><th>动作</th><th>涉及看板</th>"
                     "<th>证据</th></tr></thead><tbody>{}</tbody></table>".format("".join(rows)))
    else:
        parts.append('<p class="empty">无跨页动作。</p>')
    return "".join(parts)


def _html_page_actions(view):
    if view["draft"]:
        items = []
        for page in view["pages"]:
            if page["verdict"].lower() in ("ok", "✅", "ready"):
                continue
            items.append("<li>{}（{}）{}</li>".format(
                _link(page["name"], page["url"]), _h(page["verdictLabel"]) or "—",
                "：关联发现 " + _h("、".join(page["findingIds"])) if page["findingIds"] else ""))
        return ('<p class="empty">尚未生成整合建议。逐页动作（保留 / 改造 / 拆分 / 合并 / 新建 / 移出）需要 AI 基于体检事实给出。</p>'
                + ("<h3>体检已标记的待处理页面</h3><ul>{}</ul>".format("".join(items)) if items else ""))
    if not view["pageActions"]:
        return '<p class="empty">未填写逐页动作。</p>'
    blocks = []
    for action in view["pageActions"]:
        tag = "新建页" if action["pgId"] == "NEW" else "现有看板"
        blocks.append('<div class="fd {}">'.format(_h(action["priority"]).lower()))
        blocks.append('<h3 style="margin:0 0 6px">{}'
                      '<span class="tag {}">{}</span>'
                      '<span class="tag">{}</span></h3>'.format(
                          _link(action["name"], action["url"]),
                          _h(action["priority"]).lower(), _h(action["priority"]),
                          _h(action["verdict"])))
        blocks.append('<div class="hd">{} · pgId：{}</div>'.format(_h(tag), _h(action["pgId"])))
        if action["actions"]:
            blocks.append("<ul>{}</ul>".format("".join("<li>{}</li>".format(_h(x)) for x in action["actions"])))
        if action["evidence"]:
            blocks.append('<p class="ev">证据：{}</p>'.format(_h("、".join(
                "{}（{}）".format(r["id"], r["rule"]) if r["rule"] else r["id"] for r in action["evidence"]))))
        if action["expectedEffect"]:
            blocks.append("<p>预期效果：{}</p>".format(_h(action["expectedEffect"])))
        blocks.append("</div>")
    return "".join(blocks)


def _html_config(view):
    if view["draft"]:
        return ('<p class="empty">尚未生成整合建议。Agent 类型、分析思路、步骤计划、报告框架、'
                '用户提问示例、联动筛选器、业务范围、输出要求、知识缺口与专家角色都需要在建议文件中给出。</p>')
    config = view["config"]
    parts = ["<h3>Agent 类型与业务范围</h3>"]
    parts.append('<p class="kv"><b>Agent 类型：</b>{}</p>'.format(_h(config["agentType"]) or "未填写"))
    parts.append("<p>{}</p>".format(_h(config["businessScope"]) or "未填写"))

    parts.append("<h3>联动筛选器</h3>")
    if config["linkage"]:
        rows = []
        for item in config["linkage"]:
            page = _link(item["pageName"], item["url"]) if item["url"] else _h(item["pageName"])
            rows.append("<tr><td>{}</td><td>{}</td><td>{}</td><td class=\"mono\">{}</td></tr>".format(
                page, _h(item["name"]) or "—", _h(item["field"]) or "—", _h(item["cdId"]) or "—"))
        parts.append("<table><thead><tr><th>看板</th><th>筛选器</th><th>字段</th><th>cdId</th></tr></thead>"
                     "<tbody>{}</tbody></table>".format("".join(rows)))
    else:
        parts.append('<p class="empty">未填写联动筛选器（每张看板至少需要一个，R-02）。</p>')

    parts.append("<h3>分析思路</h3>")
    parts.append('<p class="kv"><b>默认思路（可直接粘贴到 BI）：</b>{}</p>'.format(
        _h(config["defaultThinking"]) or "未填写"))

    if config["stepPlan"]:
        parts.append("<h4>步骤计划</h4>")
        for step in config["stepPlan"]:
            parts.append('<div class="fd">')
            parts.append('<h4 style="margin:0 0 6px">Step {}：{}</h4>'.format(
                _h(step["step"]), _h(step["goal"]) or "（未写目标）"))
            items = []
            if step["dashboards"]:
                boards = []
                for board in step["dashboards"]:
                    boards.append(_link(board["name"], board["url"]) if board["url"] else _h(board["name"]))
                items.append("<li><b>看板：</b>{}</li>".format("、".join(boards)))
            if step["coreQuestions"]:
                items.append("<li><b>核心问题：</b>{}</li>".format(
                    _h("；".join(step["coreQuestions"]))))
            if step["cards"]:
                items.append("<li><b>核心卡片：</b>{}</li>".format(_h("、".join(step["cards"]))))
            if step["filters"]:
                items.append("<li><b>筛选参数：</b>{}</li>".format(_h("、".join(step["filters"]))))
            items.append("<li><b>本步输出：</b>{}</li>".format(_h(step["output"]) or "未填写"))
            items.append("<li><b>进入下一步：</b>{}</li>".format(_h(step["nextIf"]) or "未填写"))
            items.append("<li><b>终止条件：</b>{}</li>".format(_h(step["stopIf"]) or "未填写"))
            parts.append("<ul>{}</ul></div>".format("".join(items)))

    if config["exploratoryRules"]:
        parts.append("<h4>探索型路径原则</h4>")
        parts.append("<ul>{}</ul>".format("".join(
            "<li>{}</li>".format(_h(x)) for x in config["exploratoryRules"])))
    if config["reportFramework"]:
        parts.append("<h4>报告交付框架</h4>")
        parts.append("<ol>{}</ol>".format("".join(
            "<li>{}</li>".format(_h(x)) for x in config["reportFramework"])))
    if config["questionExamples"]:
        parts.append("<h4>用户提问示例</h4>")
        parts.append("<ul>{}</ul>".format("".join(
            "<li>{}</li>".format(_h(x)) for x in config["questionExamples"])))

    parts.append("<h3>输出要求</h3><p>{}</p>".format(_h(config["outputRequirements"]) or "未填写"))

    parts.append("<h3>业务知识缺口</h3>")
    if config["knowledgeGaps"]:
        parts.append("<ul>{}</ul>".format("".join("<li>{}</li>".format(_h(x)) for x in config["knowledgeGaps"])))
    else:
        parts.append('<p class="empty">无（或未填写）。</p>')

    parts.append("<h3>分析专家建议</h3>")
    if config["expertRoles"]:
        items = []
        for role in config["expertRoles"]:
            bits = [x for x in (role["scope"], role["reason"]) if x]
            items.append("<li>{}：{}</li>".format(_h(role["name"]) or "未命名专家", _h("；".join(bits))) if bits
                         else "<li>{}</li>".format(_h(role["name"]) or "未命名专家"))
        parts.append("<ul>{}</ul>".format("".join(items)))
    else:
        parts.append('<p class="empty">单域场景不建议硬拆专家；跨业务域时再拆。</p>')
    return "".join(parts)


def _html_roadmap(view):
    if view["draft"]:
        return '<p class="empty">尚未生成整合建议。路线图在建议确认后给出。</p>'
    if not view["roadmap"]:
        return '<p class="empty">未填写路线图。</p>'
    blocks = []
    for phase in view["roadmap"]:
        blocks.append("<h3>{}</h3>".format(_h(phase["phase"]) or "未命名阶段"))
        if phase["items"]:
            blocks.append("<ul>{}</ul>".format("".join("<li>{}</li>".format(_h(x)) for x in phase["items"])))
        if phase["effort"]:
            blocks.append('<p class="kv"><b>预估工作量：</b>{}</p>'.format(_h(phase["effort"])))
    return "".join(blocks)


def _html_questions(view):
    if view["draft"]:
        return '<p class="empty">尚未生成整合建议。待确认问题（业务链路、异常阈值、责任部门映射）需要在建议文件中列出。</p>'
    if not view["openQuestions"]:
        return '<p class="empty">无。</p>'
    return "<ol>{}</ol>".format("".join("<li>{}</li>".format(_h(x)) for x in view["openQuestions"]))


def _html_appendix(view):
    parts = ["<h3>评分说明</h3>",
             "<p>页级就绪度（100）：{}。</p>".format(
                 _h(" / ".join("{} {}".format(label, weight) for _, label, weight in DIMENSIONS))),
             "<p>总分 = 页级均分 × 60% + 组合级 × 40%；等级：≥80 可直接配置 / 65–79 小改后配置 / "
             "50–64 需改造 / &lt;50 不建议直接配置。</p>",
             "<p>阻断收敛：不可用页不进页级均分；任一页缺联动筛选器（R-02）时总分最高“需改造”；"
             "超过 10 页且未取舍或可用页为 0 → 封顶 49。</p>",
             "<h3>规则来源</h3>", "<ul>"]
    for name, detail in RULE_SOURCES:
        parts.append("<li><b>{}</b>：{}</li>".format(_h(name), _h(detail)))
    if view["ruleSources"]:
        cited = "；".join(
            "{} {}".format(x["rule"] or "—", x["source"]) for x in view["ruleSources"])
        parts.append("<li><b>本次引用</b>：{}</li>".format(_h(cited)))
    parts.append("</ul>")

    parts.append("<h3>看板与卡片清单</h3>")
    for asset in view["assets"]:
        parts.append('<div class="fd p2" style="border-left-color:var(--line)">')
        parts.append('<div class="hd">{}</div>'.format(_link(asset["name"], asset["url"])))
        parts.append('<p class="mono">pgId {}｜{}｜总分 {}｜{}</p>'.format(
            _h(asset["pgId"]) or "—", _h(asset["verdictLabel"]) or "—",
            asset["total"] if asset["total"] is not None else "—", _h(asset["grade"]) or "—"))
        parts.append("<p>数据卡 {} 张｜筛选器 {} 个｜联动筛选器 {} 个｜明细最大行数 {}｜更新时间 {}</p>".format(
            asset["dataCards"] if asset["dataCards"] is not None else "—",
            asset["selectors"] if asset["selectors"] is not None else "—",
            asset["linkage"] if asset["linkage"] is not None else "—",
            asset["maxRawRows"] if asset["maxRawRows"] is not None else "未实测",
            _h(asset["mtime"]) or "—"))
        if asset["findingIds"]:
            parts.append('<p class="src">关联发现：{}</p>'.format(_h("、".join(asset["findingIds"]))))
        if asset["cards"]:
            names = ["{}".format(c["name"]) for c in asset["cards"]]
            shown = names[:40]
            parts.append('<details><summary>卡片 {} 张（展开）</summary><p>{}{}</p></details>'.format(
                len(names), _h("、".join(shown)),
                _h("…… 其余 {} 张见 BI 页面".format(len(names) - len(shown))) if len(names) > len(shown) else ""))
        parts.append("</div>")
    return "".join(parts)


def render_html(view):
    title = _h(view["title"])
    scenario = _h(view["scenario"]) or "待确认"
    meta_bits = ["诊断范围 {} 张看板".format(view["pageCount"]),
                 "生成于 {}".format(_h(view["built_at"]) or "—")]
    if view["builder_version"]:
        meta_bits.append("体检版本 {}".format(_h(view["builder_version"])))

    draft_notice = ""
    if view["draft"]:
        draft_notice = ('<div class="notice draft">这是<b>结构体检草稿</b>：'
                        '尚未生成整合建议。确认体检事实后，再补 insight-advice.json 并运行最终报告。</div>')

    sections = [
        ("1. 结论摘要", "<ul>{}</ul>".format("".join("<li>{}</li>".format(_h(x)) for x in view["summary"]))),
        ("2. 目标场景与看板组合", "".join([
            '<p class="kv"><b>目标场景：</b>{}</p>'.format(scenario),
            '<p class="kv"><b>业务范围：</b>{}</p>'.format(
                _h(view["businessScope"]) or "待确认（R-04：业务范围必须清晰）"),
            '<p class="kv"><b>看板组合：</b>{} 张（官方上限 {} 张）</p>'.format(view["pageCount"], view["maxPages"]),
            "<table><thead><tr><th>看板</th><th>体检结论</th><th>总分</th><th>等级</th></tr></thead><tbody>",
            "".join("<tr><td>{}</td><td>{}</td><td class=\"num\">{}</td><td>{}</td></tr>".format(
                _link(p["name"], p["url"]), _h(p["verdictLabel"]) or "—",
                p["total"] if p["total"] is not None else "—", _h(p["grade"]) or "—")
                for p in view["pages"]),
            "</tbody></table>",
            '<p class="src">环境前提：{}</p>'.format(_h(" ".join(view["envNotes"]))),
        ])),
        ("3. 体检总表", _html_score_table(view)
         + '<p class="src">权重：{}</p>'.format(_h(" / ".join(
             "{} {}".format(label, weight) for _, label, weight in DIMENSIONS)))
         + '<p class="src">含 P0/阻断的看板，总分按规则封顶 64（维度分是原始得分；原始总分见 insight-audit.json 的 rawTotal）。</p>'),
        ("4. 关键发现", _html_findings(view)),
        ("5. 整合建议", _html_advice(view)),
        ("6. 逐页调整清单", _html_page_actions(view)),
        ("7. 洞察Agent 配置衔接", _html_config(view)),
        ("8. 落地路线图", _html_roadmap(view)),
        ("9. 待确认问题", _html_questions(view)),
        ("附录：评分说明 / 规则来源 / 看板卡片清单", _html_appendix(view)),
    ]

    body = []
    for heading, content in sections:
        body.append("<section><h2>{}</h2>{}</section>".format(_h(heading), content))

    return """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} · {scenario}</title>
<style>{css}</style>
</head>
<body>
<main>
<header>
<h1>{title}</h1>
<div class="meta">{meta}</div>
<div class="submeta">目标场景：{scenario}</div>
</header>
{hero}
{draft}
{blockers}
{sections}
<footer>
这是<b>诊断与建议</b>，不是已改造完成：本工具只读，不修改 BI 看板、不创建洞察Agent。<br>
按 P0 动作改完后可重新体检，并把本次 <span class="mono">insight-audit.json</span> 作为基线对比。<br>
评分只衡量结构可执行性，不衡量业务价值；业务链路、口径裁决与真实数据测试仍需单独确认。
</footer>
</main>
</body>
</html>
""".format(title=title, scenario=scenario, css=CSS,
           meta=" · ".join(meta_bits), hero=_html_hero(view), draft=draft_notice,
           blockers=_html_blockers(view), sections="\n".join(body))


# ---------------------------------------------------------------- CLI


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="洞察Agent 看板诊断：校验 insight-advice.json 并渲染 Markdown / HTML 报告")
    parser.add_argument("workdir", help="工作目录（含 insight-audit.json）")
    parser.add_argument("--draft", action="store_true", help="只渲染结构体检草稿（不要求建议文件）")
    parser.add_argument("--check", action="store_true", help="只校验建议，不写文件")
    parser.add_argument("--advice", default="", help="建议文件路径，默认 <工作目录>/insight-advice.json")
    parser.add_argument("--open", dest="open_report", action="store_true", help="macOS 上渲染后自动打开 HTML")
    args = parser.parse_args(argv)

    workdir = args.workdir
    if not os.path.isdir(workdir):
        print("工作目录不存在：{}".format(workdir), file=sys.stderr)
        return 2

    audit_path = os.path.join(workdir, "insight-audit.json")
    audit, err = load_json(audit_path, "结构体检产物 insight-audit.json")
    if err:
        print(err, file=sys.stderr)
        print("请先运行：python3 references/scripts/audit_insight_pages.py {}".format(workdir), file=sys.stderr)
        return 2
    if not isinstance(audit, dict):
        print("insight-audit.json 顶层必须是对象：{}".format(audit_path), file=sys.stderr)
        return 2

    meta = as_dict(audit.get("meta"))
    base_url = s(meta.get("biBaseUrl"))

    if args.draft and not args.check:
        view = build_view(audit, {}, True, base_url)
        md_path = os.path.join(workdir, "insight-audit-draft.md")
        html_path = os.path.join(workdir, "insight-audit-draft.html")
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(render_markdown(view))
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(render_html(view))
        print("DRAFT_MD={}".format(os.path.abspath(md_path)))
        print("DRAFT_HTML={}".format(os.path.abspath(html_path)))
        print("结构体检草稿已生成（尚未生成整合建议）")
        if args.open_report:
            _open_file(html_path)
        return 0

    advice_path = args.advice or os.path.join(workdir, "insight-advice.json")
    if not os.path.isabs(advice_path):
        advice_path = os.path.abspath(advice_path)
    advice, err = load_json(advice_path, "整合建议 insight-advice.json")
    if err:
        print(err, file=sys.stderr)
        if args.check:
            return 2
        print("也可以用 --draft 先渲染结构体检草稿", file=sys.stderr)
        return 2
    if not isinstance(advice, dict):
        print("建议文件顶层必须是 JSON 对象：{}".format(advice_path), file=sys.stderr)
        return 2

    errors, warnings = validate(audit, advice)

    if errors:
        print("❌ 建议校验未通过（{} 个错误）".format(len(errors)), file=sys.stderr)
        for index, message in enumerate(errors, 1):
            print("{}. {}".format(index, message), file=sys.stderr)
        for message in warnings:
            print("⚠️  {}".format(message), file=sys.stderr)
        return 2

    pages = as_list(audit.get("pages"))
    blockers = [f for f in as_list(audit.get("findings"))
                if isinstance(f, dict) and s(f.get("level")).lower() == "blocker"]
    mode = advice.get("mode")
    primary = s(mode.get("primary")) if isinstance(mode, dict) else s(mode)
    p0_count = len([a for a in as_list(advice.get("pageActions"))
                    if isinstance(a, dict) and s(a.get("priority")) == "P0"])

    if args.check:
        print("✅ 建议校验通过")
        print("看板 {} 张｜逐页动作 {} 条（P0 {} 条）｜跨页动作 {} 条｜发现 {} 条（阻断 {} 条）｜主模式 {}".format(
            len(pages), len(as_list(advice.get("pageActions"))), p0_count,
            len(as_list(advice.get("crossPageActions"))),
            len(as_list(audit.get("findings"))), len(blockers), primary or "—"))
        print("auditBuiltAt={} 与体检一致".format(s(advice.get("auditBuiltAt"))))
        for message in warnings:
            print("⚠️  {}".format(message))
        return 0

    view = build_view(audit, advice, False, base_url)
    md_path = os.path.join(workdir, "insight-audit.md")
    html_path = os.path.join(workdir, "insight-audit.html")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(render_markdown(view))
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(render_html(view))

    print("REPORT_MD={}".format(os.path.abspath(md_path)))
    print("REPORT_HTML={}".format(os.path.abspath(html_path)))
    print("报告已生成：{} 张看板 · 总分 {} · {}".format(
        view["pageCount"], view["overall"] if view["overall"] is not None else "—",
        view["grade"] or "未评级"))
    for message in warnings:
        print("⚠️  {}".format(message))
    if args.open_report:
        _open_file(html_path)
    return 0


def _open_file(path):
    if sys.platform != "darwin":
        return
    try:
        subprocess.run(["open", path], capture_output=True, timeout=20)
    except Exception:
        pass


if __name__ == "__main__":
    sys.exit(main())
