#!/usr/bin/env python3
"""
选看板核对页生成器：把第 1 步已勾选的看板清单 + 适检结论 + agent-ready 评分渲染成一页 HTML，
供用户在浏览器里核对（看板名可点击跳转 BI 看内容），核对后回到对话确认
用法:
  python3 selection_page.py <工作目录> [--scope "业务范围说明"]
输入: <工作目录>/page-check.json（check_pages.py -o 的产物，含每张看板的适检结论与评分）
输出: <工作目录>/selection.html；stdout 打印 SELECTION_HTML=<绝对路径>
注意: 本页只是核对辅助——用户的确认动作仍在对话中完成（确认点红线不破）
"""
import json, os, re, subprocess, sys, html
from datetime import datetime

VERDICT_LABEL = {"✅": "适合", "⚠️": "有风险", "⛔": "不可用"}
VERDICT_CLASS = {"✅": "ok", "⚠️": "warn", "⛔": "bad"}
GRADE_CLASS = {"高": "hi", "中": "mid", "低": "lo"}


def bi_base_url():
    try:
        r = subprocess.run(["guancli", "auth", "status"],
                           capture_output=True, text=True, timeout=30)
        m = re.search(r'^URL:\s*(\S+)', r.stdout, re.M)
        return m.group(1).rstrip('/') if m else ""
    except Exception:
        return ""


def render(doc, scope, base_url):
    pages = doc.get("pages") or []
    n_ok = sum(1 for p in pages if p.get("verdict") == "✅")
    n_warn = sum(1 for p in pages if p.get("verdict") == "⚠️")
    n_bad = sum(1 for p in pages if p.get("verdict") == "⛔")

    cards = []
    for p in pages:
        v = p.get("verdict", "⚠️")
        name = html.escape(p.get("name") or p.get("pgId", ""), quote=True)
        url = f"{base_url}/page/{p.get('pgId')}" if base_url and p.get("pgId") else ""
        title = (f'<a class="nm" href="{html.escape(url, quote=True)}" target="_blank" '
                 f'rel="noopener">{name}&nbsp;↗</a>') if url else f'<span class="nm">{name}</span>'
        reasons = "".join(f'<li class="risk">{html.escape(r)}</li>' for r in p.get("reasons") or [])
        notes = "".join(f'<li class="plus">{html.escape(n)}</li>' for n in p.get("notes") or [])
        ar = p.get("agentReady") or {}
        score_html = ""
        if ar:
            g = ar.get("grade", "")
            score_html = (f'<span class="score {GRADE_CLASS.get(g, "mid")}">'
                          f'agent-ready {ar.get("score", "?")}/100 · {html.escape(g)}</span>')
        red = "".join(f'<li class="line">{html.escape(x)}</li>' for x in ar.get("redLines") or [])
        bnd = "".join(f'<li class="bnd">{html.escape(x)}</li>' for x in ar.get("boundaries") or [])
        detail = f"<ul>{red}{reasons}{bnd}{notes}</ul>" if red or reasons or bnd or notes else ""
        cards.append(
            f'<div class="card {VERDICT_CLASS.get(v, "warn")}">'
            f'<span class="badge">{v} {VERDICT_LABEL.get(v, "")}</span>{title}{score_html}{detail}</div>')

    scope_html = (f'<div class="scope"><h2>业务范围</h2><p>{html.escape(scope)}</p></div>'
                  if scope else "")
    summary = f'{len(pages)} 张看板'
    if pages:
        summary += f'（✅ {n_ok}　⚠️ {n_warn}　⛔ {n_bad}）'

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>数据范围确认 · Data Agent 搭建向导</title>
<style>
:root{{--ink:#1d2129;--ink2:#4e5969;--ink3:#86909c;--line:#e5e6eb;
  --ok:#00b42a;--warn:#ff7d00;--bad:#f53f3f;--acc:#165dff}}
*{{box-sizing:border-box;margin:0}}
body{{font-family:-apple-system,"PingFang SC","Helvetica Neue",sans-serif;
  background:#f7f8fa;color:var(--ink);padding:40px 20px}}
main{{max-width:680px;margin:0 auto}}
h1{{font-size:22px;margin-bottom:6px}}
.meta{{font-size:12.5px;color:var(--ink3);margin-bottom:24px}}
.scope{{background:#fff;border:1px solid var(--line);border-radius:10px;
  padding:14px 18px;margin-bottom:20px}}
.scope h2{{font-size:13px;color:var(--ink3);margin-bottom:6px;font-weight:600}}
.scope p{{font-size:14px;line-height:1.7;color:var(--ink2)}}
.card{{background:#fff;border:1px solid var(--line);border-radius:10px;
  padding:13px 18px;margin-bottom:10px}}
.badge{{display:inline-block;font-size:11.5px;border-radius:5px;padding:1px 7px;
  margin-right:9px;vertical-align:1px}}
.ok .badge{{color:var(--ok);border:1px solid color-mix(in srgb,var(--ok) 40%,transparent)}}
.warn .badge{{color:var(--warn);border:1px solid color-mix(in srgb,var(--warn) 40%,transparent)}}
.bad .badge{{color:var(--bad);border:1px solid color-mix(in srgb,var(--bad) 40%,transparent)}}
.nm{{font-size:15px;font-weight:600;color:var(--ink);text-decoration:none}}
a.nm:hover{{color:var(--acc)}}
ul{{margin:8px 0 0;padding-left:18px}}
li{{font-size:12.5px;line-height:1.7;color:var(--ink2)}}
li.risk::marker{{color:var(--warn)}}
li.plus::marker{{color:var(--ok)}}
li.line::marker{{color:var(--bad)}}
li.bnd::marker{{color:var(--acc)}}
.score{{display:inline-block;font-size:11.5px;border-radius:5px;padding:1px 7px;
  margin-left:9px;vertical-align:1px;border:1px solid}}
.score.hi{{color:var(--ok);border-color:color-mix(in srgb,var(--ok) 40%,transparent)}}
.score.mid{{color:var(--warn);border-color:color-mix(in srgb,var(--warn) 40%,transparent)}}
.score.lo{{color:var(--bad);border-color:color-mix(in srgb,var(--bad) 40%,transparent)}}
footer{{margin-top:26px;font-size:13px;line-height:1.9;color:var(--ink2);
  background:#fff;border:1px dashed var(--line);border-radius:10px;padding:14px 18px}}
footer b{{color:var(--ink)}}
</style>
</head>
<body>
<main>
<h1>数据范围确认</h1>
<div class="meta">{summary} · 生成于 {datetime.now().strftime("%Y-%m-%d %H:%M")}</div>
{scope_html}
{"".join(cards)}
<footer>
核对方式：<b>点看板名</b>可以在 BI 里打开看内容。<br>
都没问题 → 回到对话说「<b>确认</b>」；要调整 → 直接说，比如「把《XX》去掉」「再加上《YY》」。
</footer>
</main>
</body>
</html>
"""


def main():
    args = sys.argv[1:]
    scope = ""
    if "--scope" in args:
        i = args.index("--scope")
        try:
            scope = args[i + 1]
        except IndexError:
            sys.exit("--scope 需要一段业务范围说明文字")
        args = args[:i] + args[i + 2:]
    if not args:
        sys.exit(__doc__)
    workdir = args[0]
    pc = os.path.join(workdir, "page-check.json")
    if not os.path.exists(pc):
        sys.exit(f"未找到 {pc}——请先运行 check_pages.py <pageId>... -o <工作目录> 生成适检结论")
    with open(pc, encoding="utf-8") as f:
        doc = json.load(f)
    out = os.path.join(workdir, "selection.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(render(doc, scope, bi_base_url()))
    print(f"SELECTION_HTML={os.path.abspath(out)}")


if __name__ == "__main__":
    main()
