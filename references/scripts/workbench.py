#!/usr/bin/env python3
"""
轻量工作台：把搭建/交付产物变成可校验、可编辑的本地页面（WorkBuddy 原生风格）
用法:
  python3 workbench.py <目录>              # 生成只读 <目录>/workbench.html（双击浏览器打开）
  python3 workbench.py <目录> --serve      # 本地编辑/体检服务，打印 WORKBENCH_URL
  python3 workbench.py <目录> --check [--fresh-days 30]
                                         # 体检：看板是否被改过（mtime+结构指纹双信号，具体报出增删卡片）、
                                         #      超过复核阈值提醒、运行脚本可升级提示
  python3 workbench.py --agents [<skills目录>]           # 多 agent 管理总览 agents.html
  python3 workbench.py --agents [<skills目录>] --serve   # 总览 + 逐个体检按钮
识别文件: cards.json（资产表格，含 _meta 学习时点/结构指纹/builderVersion）、learningResult.md、
          businessKnowledge.md、insightThinking.md；<目录>/../SKILL.md 存在时读取 agent 名称/描述/触发词
外观: 跟随系统亮/暗色；URL 加 ?dark 可强制暗色
"""
import json, os, re, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from hashlib import sha1
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

BUILDER_VERSION = "3.8.0"  # 发布时与 SKILL.md frontmatter version 同步；体检时与交付包 _meta.builderVersion 对比
FRESH_DAYS_DEFAULT = 30    # 复核阈值：距上次学习超过 N 天即提醒复核（--fresh-days 可调）

COMMON_CSS = r"""
:root{
  color-scheme: light;
  --paper:#f7f5ef; --paper2:#efecdf; --sheet:#fdfcf7;
  --ink:#1d1a15; --ink2:#5d584b; --ink3:#9a937e;
  --line:#dfdac9; --line2:#c6bfa9;
  --acc:#165f49; --acc-ink:#0d4031; --acc-soft:rgba(22,95,73,.07);
  --ok:#1a7a4a; --warn:#a25c06; --err:#b3261e;
  --ok-soft:rgba(26,122,74,.09); --warn-soft:rgba(162,92,6,.09); --err-soft:rgba(179,38,30,.07);
  --mono:ui-monospace,"SF Mono",Menlo,Consolas,monospace;
  --shadow:0 1px 0 rgba(29,26,21,.03),0 14px 30px -16px rgba(29,26,21,.22);
  --code-bg:#151b17; --code-fg:#cfe3d6;
}
@media (prefers-color-scheme: dark){ :root{
  color-scheme: dark;
  --paper:#0d110e; --paper2:#111613; --sheet:#171e1a;
  --ink:#e8e5da; --ink2:#aba696; --ink3:#6f6a5a;
  --line:#262e28; --line2:#37423b;
  --acc:#57b189; --acc-ink:#8fd2b2; --acc-soft:rgba(87,177,137,.10);
  --ok:#4cc181; --warn:#e0a34a; --err:#e0655d;
  --ok-soft:rgba(76,193,129,.13); --warn-soft:rgba(224,163,74,.13); --err-soft:rgba(224,101,93,.11);
  --shadow:0 1px 0 rgba(0,0,0,.25),0 14px 30px -14px rgba(0,0,0,.55);
  --code-bg:#090d0a; --code-fg:#b7d9c2;
}}
:root[data-theme=light]{
  color-scheme: light;
  --paper:#f7f5ef; --paper2:#efecdf; --sheet:#fdfcf7;
  --ink:#1d1a15; --ink2:#5d584b; --ink3:#9a937e;
  --line:#dfdac9; --line2:#c6bfa9;
  --acc:#165f49; --acc-ink:#0d4031; --acc-soft:rgba(22,95,73,.07);
  --ok:#1a7a4a; --warn:#a25c06; --err:#b3261e;
  --ok-soft:rgba(26,122,74,.09); --warn-soft:rgba(162,92,6,.09); --err-soft:rgba(179,38,30,.07);
  --shadow:0 1px 0 rgba(29,26,21,.03),0 14px 30px -16px rgba(29,26,21,.22);
  --code-bg:#151b17; --code-fg:#cfe3d6;
}
:root[data-theme=dark]{
  color-scheme: dark;
  --paper:#0d110e; --paper2:#111613; --sheet:#171e1a;
  --ink:#e8e5da; --ink2:#aba696; --ink3:#6f6a5a;
  --line:#262e28; --line2:#37423b;
  --acc:#57b189; --acc-ink:#8fd2b2; --acc-soft:rgba(87,177,137,.10);
  --ok:#4cc181; --warn:#e0a34a; --err:#e0655d;
  --ok-soft:rgba(76,193,129,.13); --warn-soft:rgba(224,163,74,.13); --err-soft:rgba(224,101,93,.11);
  --shadow:0 1px 0 rgba(0,0,0,.25),0 14px 30px -14px rgba(0,0,0,.55);
  --code-bg:#090d0a; --code-fg:#b7d9c2;
}
*{box-sizing:border-box;margin:0}
body{background:var(--paper);color:var(--ink);
  font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;
  font-size:14px;line-height:1.65;-webkit-font-smoothing:antialiased;overflow-wrap:break-word;
  -webkit-tap-highlight-color:transparent}
h1,h2,h3{text-wrap:balance}
a{color:var(--acc);text-decoration:none;box-shadow:inset 0 -1px 0 color-mix(in srgb,var(--acc) 35%,transparent);
  transition:box-shadow .15s,color .15s}
a:hover{color:var(--acc-ink);box-shadow:inset 0 -1.5px 0 var(--acc)}
button,textarea{touch-action:manipulation;font-family:inherit}
button:focus-visible,textarea:focus-visible,summary:focus-visible,a:focus-visible{
  outline:2px solid var(--acc);outline-offset:2px;border-radius:4px}
::selection{background:color-mix(in srgb,var(--acc) 22%,transparent)}

/* ---------- 微型标签 / 状态灯 / 等宽数字 ---------- */
.micro{font-family:var(--mono);font-size:10.5px;letter-spacing:.16em;text-transform:uppercase;
  color:var(--ink3);font-weight:500}
.led{display:inline-block;width:7px;height:7px;border-radius:50%;background:currentColor;flex:none;
  box-shadow:0 0 0 3px color-mix(in srgb,currentColor 15%,transparent)}
.led.pulse{animation:ledp 1.5s ease-in-out infinite}
@keyframes ledp{50%{box-shadow:0 0 0 5px color-mix(in srgb,currentColor 6%,transparent);opacity:.6}}

/* ---------- 骨架 ---------- */
.shell{max-width:1120px;margin:0 auto;padding:30px 24px 80px;display:flex;gap:40px;align-items:flex-start}
.side{flex:0 0 206px;position:sticky;top:30px}
.brand{display:flex;align-items:center;gap:12px;padding:2px 4px 20px}
.brand .mark{width:36px;height:36px;color:var(--ink);flex:none}
.brand .t1{font-weight:650;font-size:14px;margin-top:2px}
.brand .t2{font-size:11.5px;color:var(--ink3);margin-top:1px}
.nav{display:flex;flex-direction:column;gap:1px}
.nav button{display:grid;grid-template-columns:24px 1fr;gap:10px;align-items:baseline;padding:8px 10px;
  border:none;background:transparent;color:var(--ink2);font-size:13.5px;cursor:pointer;text-align:left;
  position:relative;transition:color .15s}
.nav button .idx{font-family:var(--mono);font-size:10px;letter-spacing:.08em;color:var(--ink3);
  transition:color .15s}
.nav button::after{content:"";position:absolute;left:10px;right:10px;bottom:3px;height:1.5px;
  background:var(--acc);transform:scaleX(0);transform-origin:left;transition:transform .28s cubic-bezier(.2,.7,.2,1)}
.nav button:hover{color:var(--ink)}
.nav button:hover::after{transform:scaleX(.3)}
.nav button.on{color:var(--ink);font-weight:650}
.nav button.on .idx{color:var(--acc)}
.nav button.on::after{transform:scaleX(1)}
.side .done{margin-top:22px;width:100%;padding:10px 12px;border:none;border-radius:9px;background:var(--ink);
  color:var(--paper);font-size:13px;cursor:pointer;display:flex;align-items:center;justify-content:center;
  gap:8px;transition:opacity .15s}
.side .done:hover{opacity:.85}
.main{flex:1;min-width:0}
.dochead{border-bottom:2px solid var(--ink);padding-bottom:16px;margin-bottom:8px;
  display:flex;align-items:flex-end;gap:16px;flex-wrap:wrap}
.dochead h1{font-size:26px;font-weight:750;letter-spacing:.01em;margin-top:4px}
.dochead .meta{font-size:12px;color:var(--ink3);margin-top:5px;font-family:var(--mono);
  font-variant-numeric:tabular-nums;letter-spacing:.02em}
.modebadge{margin-left:auto;display:inline-flex;align-items:center;gap:8px;flex:none;
  border:1px solid var(--line2);border-radius:999px;padding:5px 13px;
  font-family:var(--mono);font-size:11px;letter-spacing:.08em;color:var(--ink2)}
.modebadge.edit{border-color:color-mix(in srgb,var(--warn) 45%,transparent);color:var(--warn)}
.panel{display:none}.panel.on{display:block;animation:fadein .2s ease}
@keyframes fadein{from{opacity:0;transform:translateY(3px)}to{opacity:1;transform:none}}

/* ---------- 区块：细线分节，不叠卡片 ---------- */
.hint{display:flex;align-items:center;gap:10px;font-size:12.5px;color:var(--ink2);
  margin:18px 0 16px;padding:0 2px}
.hint::before{content:"";width:18px;height:1.5px;background:var(--acc);flex:none}
.block{border-top:1px solid var(--line);padding:18px 0 22px}
.block > h3{font-size:15px;font-weight:650;display:flex;align-items:baseline;gap:10px;
  margin-bottom:12px;flex-wrap:wrap}
.block > h3 .sub,.card > h3 .sub,details.card .sub{font-family:var(--mono);font-size:10.5px;
  letter-spacing:.12em;text-transform:uppercase;color:var(--ink3);font-weight:500}
.sheet{background:var(--sheet);border:1px solid var(--line);border-radius:14px;box-shadow:var(--shadow)}

/* 概览身份卡 */
.idsheet{padding:24px 26px;margin:18px 0 22px}
.id-top{display:flex;gap:18px;align-items:flex-start}
.id-name{font-size:27px;font-weight:750;letter-spacing:.01em;margin:3px 0 6px}
.id-desc{font-size:13.5px;color:var(--ink2);max-width:56em}
.id-tags{display:flex;align-items:center;gap:6px;flex-wrap:wrap;margin-top:16px;padding-top:14px;
  border-top:1px solid var(--line)}
.id-meta{display:flex;gap:0;margin-top:14px;padding-top:12px;border-top:1px solid var(--line);
  font-family:var(--mono);font-size:11.5px;color:var(--ink3);flex-wrap:wrap;row-gap:4px;
  font-variant-numeric:tabular-nums;letter-spacing:.03em}
.id-meta span + span::before{content:"·";margin:0 10px;color:var(--line2)}

/* 指标行：无边框大数字 */
.metrics{display:flex;margin:16px 0 26px;border-top:1px solid var(--line);border-bottom:1px solid var(--line)}
.metric{flex:1;min-width:110px;padding:16px 20px 15px;border-left:1px solid var(--line)}
.metric:first-child{border-left:none;padding-left:2px}
.metric .n{font-family:var(--mono);font-size:29px;font-weight:600;line-height:1.1;
  font-variant-numeric:tabular-nums;letter-spacing:-.01em}
.metric .l{margin-top:5px}

/* 标签（chip 继任者）：描边小胶囊 + 状态灯 */
.tag{display:inline-flex;align-items:center;gap:6px;padding:1.5px 9px;border:1px solid var(--line2);
  border-radius:999px;font-size:11.5px;color:var(--ink2);white-space:nowrap;vertical-align:1px}
.tag .led{width:6px;height:6px;box-shadow:none}
.t-ok{color:var(--ok);border-color:color-mix(in srgb,var(--ok) 38%,transparent)}
.t-warn{color:var(--warn);border-color:color-mix(in srgb,var(--warn) 38%,transparent)}
.t-err{color:var(--err);border-color:color-mix(in srgb,var(--err) 38%,transparent)}

/* 键值行 */
.frow{display:flex;gap:14px;padding:8px 2px;border-top:1px solid var(--line);font-size:13px;
  align-items:baseline}
.frow:first-of-type{border-top:none}
.frow .k{flex:0 0 108px;font-family:var(--mono);font-size:11px;letter-spacing:.05em;color:var(--ink3)}
.frow .v{flex:1;min-width:0}

/* 表格：细线 + 等宽表头 */
table{width:100%;border-collapse:collapse;font-size:12.5px}
th{font-family:var(--mono);font-size:10.5px;letter-spacing:.14em;text-transform:uppercase;
  color:var(--ink3);font-weight:500;text-align:left;padding:9px 10px;
  border-bottom:1.5px solid var(--ink)}
td{padding:8px 10px;border-top:1px solid var(--line);vertical-align:baseline}
tr:hover td{background:var(--acc-soft)}
td.mono,.mono{font-family:var(--mono);font-variant-numeric:tabular-nums}

/* 口径台账 */
.rule{display:grid;grid-template-columns:40px 1fr auto;gap:14px;padding:14px 0 15px;
  border-top:1px solid var(--line)}
.rule .num{font-family:var(--mono);font-size:12.5px;color:var(--ink3);padding-top:2px;
  font-variant-numeric:tabular-nums;letter-spacing:.05em}
.rule.formula{box-shadow:inset 3px 0 0 var(--acc);background:var(--acc-soft);
  padding-left:14px;padding-right:10px}
.rule .rhead{display:flex;align-items:baseline;gap:9px;flex-wrap:wrap}
.rtitle{font-weight:650;font-size:14px}
.src{font-family:var(--mono);font-size:10px;letter-spacing:.08em;color:var(--ink3);
  border:1px solid var(--line2);border-radius:5px;padding:.5px 6px;white-space:nowrap}
.src.warn{color:var(--warn);border-color:color-mix(in srgb,var(--warn) 40%,transparent)}
.rbody{margin-top:5px;color:var(--ink2);font-size:13px;line-height:1.75;white-space:pre-wrap}
.rule .acts{display:flex;gap:6px;align-items:flex-start;opacity:.55;transition:opacity .15s}
.rule:hover .acts,.rule:focus-within .acts{opacity:1}
.addrule{width:100%;padding:13px;border:1.5px dashed var(--line2);border-radius:10px;background:transparent;
  color:var(--ink3);font-family:var(--mono);font-size:12px;letter-spacing:.06em;cursor:pointer;
  transition:border-color .15s,color .15s,background-color .15s;margin-top:14px}
.addrule:hover{border-color:var(--acc);color:var(--acc-ink);background:var(--acc-soft)}

/* 指标档案（metrics.json 表格视图） */
.mformula{margin-top:6px;font-family:var(--mono);font-size:12.5px;color:var(--acc-ink);
  background:var(--acc-soft);border-radius:7px;padding:6px 10px;display:inline-block;
  max-width:100%;overflow-wrap:anywhere}
.mmeta{margin-top:6px;font-size:12px;color:var(--ink3);display:flex;gap:6px;flex-wrap:wrap}
.mmeta b{color:var(--ink2);font-weight:600}
.mnote{margin-top:5px;font-size:12.5px;color:var(--ink2)}
.medit{grid-column:1/-1;display:grid;grid-template-columns:76px 1fr;gap:8px 12px;
  align-items:center;padding:8px 0}
.medit label{font-family:var(--mono);font-size:11px;color:var(--ink3);letter-spacing:.05em}
.medit input,.medit select,.medit textarea{width:100%;padding:7px 10px;border:1px solid var(--line2);
  border-radius:8px;background:var(--sheet);color:var(--ink);font-size:13px;font-family:inherit;
  outline:none}
.medit textarea{resize:vertical;font-family:var(--mono);font-size:12px;line-height:1.6}
.medit input:focus-visible,.medit select:focus-visible,.medit textarea:focus-visible{border-color:var(--acc);
  box-shadow:0 0 0 3px color-mix(in srgb,var(--acc) 18%,transparent)}
.medit .btnrow{grid-column:1/-1}
.rej{margin-top:14px}
.rej .ritem{padding:7px 2px;border-top:1px solid var(--line);font-size:12.5px;color:var(--ink2)}
.rej .ritem .rn{font-weight:600;color:var(--ink)}

/* 折叠区块：hover 展开强调线 */
details.card{padding:0;border-top:1px solid var(--line)}
details.card > summary{list-style:none;cursor:pointer;padding:15px 2px;display:flex;align-items:baseline;
  gap:10px;font-size:14.5px;font-weight:650;position:relative;transition:color .15s}
details.card > summary:hover{color:var(--acc-ink)}
details.card > summary::after{content:"";position:absolute;left:0;right:0;bottom:-1px;height:2px;
  background:var(--acc);transform:scaleX(0);transform-origin:left;transition:transform .3s cubic-bezier(.2,.7,.2,1)}
details.card > summary:hover::after{transform:scaleX(1)}
details.card > summary::-webkit-details-marker{display:none}
details.card > summary .arrow{transition:transform .18s;color:var(--ink3);font-size:10px;flex:none;
  font-family:var(--mono)}
details.card[open] > summary .arrow{transform:rotate(90deg);color:var(--acc)}
details.card > .body{padding:2px 2px 18px}
details.card .sub{font-weight:500}

/* markdown-lite 元素 */
.mh{font-weight:700;font-size:13.5px;margin:14px 0 6px}
.mh:first-child{margin-top:2px}
.block table,.panel .body table{margin:6px 0 10px}
.step{display:flex;gap:10px;padding:5px 0;font-size:13px}
.step .sn{flex:none;font-family:var(--mono);font-size:11px;color:var(--acc);padding-top:2px;
  font-variant-numeric:tabular-nums}
.step .sn::after{content:"."}
.bullet{display:flex;gap:9px;padding:3px 0;font-size:13px}
.bullet::before{content:"";flex:none;width:5px;height:5px;background:var(--acc);margin-top:9px}
.quote{border-left:2px solid var(--acc);background:var(--acc-soft);border-radius:0 8px 8px 0;
  padding:8px 12px;margin:8px 0;font-size:12.5px;color:var(--ink2)}
.legend{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0 12px}

/* 编辑与按钮 */
textarea{width:100%;min-height:110px;font:13px/1.7 var(--mono);
  padding:12px 14px;border:1px solid var(--line2);border-radius:10px;resize:vertical;
  background:var(--sheet);color:var(--ink);outline:none}
textarea:focus-visible{outline:none;border-color:var(--acc);
  box-shadow:0 0 0 3px color-mix(in srgb,var(--acc) 18%,transparent)}
.btn{padding:5px 14px;border-radius:8px;border:1px solid var(--line2);background:transparent;
  cursor:pointer;font-size:12.5px;color:var(--ink2);
  transition:border-color .15s,color .15s,background-color .15s}
.btn:hover{border-color:var(--ink);color:var(--ink)}
.btn.primary{background:var(--acc);border-color:var(--acc);color:#fff;
  display:inline-flex;align-items:center;gap:8px}
.btn.primary:hover{background:var(--acc-ink);border-color:var(--acc-ink);color:#fff}
.btn.primary .led{box-shadow:0 0 0 3px rgba(255,255,255,.25)}
.btn.danger:hover{border-color:var(--err);color:var(--err)}
.btn.mini{padding:2px 10px;font-size:11.5px;font-family:var(--mono);letter-spacing:.03em}
.btnrow{margin-top:12px;display:flex;gap:8px;align-items:center}
.saved{display:inline-flex;align-items:center;gap:5px;font-size:11.5px;color:var(--ok);
  font-family:var(--mono);letter-spacing:.04em}
code.ic{background:var(--paper2);border-radius:5px;padding:0 5px;font:12px var(--mono);color:var(--acc-ink)}
pre.json{background:var(--code-bg);color:var(--code-fg);border-radius:10px;padding:14px 16px;
  font:12px/1.65 var(--mono);overflow:auto;max-height:420px}
.fn{font-family:var(--mono);font-size:13px;font-weight:600}
.empty{border:1.5px dashed var(--line2);border-radius:14px;padding:38px 24px;text-align:center;
  color:var(--ink3);font-size:13px;margin:18px 0}
.empty .t{font-size:14.5px;color:var(--ink2);margin-bottom:6px;font-weight:600}
.avatar{border-radius:11px;display:flex;align-items:center;justify-content:center;color:#fff;
  flex:none;font-weight:700;letter-spacing:0}
#toast{position:fixed;top:18px;right:20px;padding:10px 16px;border-radius:10px;font-size:12.5px;z-index:9;
  display:none;background:var(--sheet);border:1px solid var(--line);box-shadow:var(--shadow);
  border-left:3px solid var(--ok);color:var(--ink)}
#toast.err{border-left-color:var(--err)}
.hidden{display:none!important}

/* 体检结果行 */
.diag{display:flex;align-items:baseline;gap:10px;padding:8px 2px;border-top:1px solid var(--line);
  font-size:13px}
.diag:first-of-type{border-top:none}
.diag .dt{flex:1;min-width:0}
.diag .led{margin-top:1px}

@media (max-width:760px){
  .shell{flex-direction:column;padding:16px 14px 48px;gap:18px}
  .side{position:static;flex:none;width:100%}
  .brand{padding-bottom:12px}
  .nav{flex-direction:row;overflow-x:auto;padding-bottom:6px;gap:4px}
  .nav button{flex:none;grid-template-columns:1fr;gap:0}
  .nav button .idx{display:none}
  .side .done{width:auto}
  .dochead h1{font-size:22px}
  .rule{grid-template-columns:30px 1fr}
  .rule .acts{grid-column:2;justify-content:flex-end;opacity:1}
  .metric{padding:12px 12px}
  .metric .n{font-size:22px}
}
@media print{
  body{background:#fff}
  .side,#toast,.acts,.btnrow,.addrule,.modebadge{display:none!important}
  .shell{display:block;max-width:none;padding:0}
  .dochead{border-bottom-color:#000}
  .panel{display:block!important;animation:none}
  details.card > .body{display:block}
  .idsheet,.rule,.metric,details.card,.empty{box-shadow:none;break-inside:avoid}
  a{box-shadow:none;color:inherit}
}
@media (prefers-reduced-motion: reduce){
  *,*::before,*::after{animation:none!important;transition:none!important}
}
"""

COMMON_JS = r"""
const _q = new URLSearchParams(location.search);
if(_q.has("dark")) document.documentElement.dataset.theme = "dark";
if(_q.has("light")) document.documentElement.dataset.theme = "light";
const esc = s => String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
function el(html){ const d=document.createElement("div"); d.innerHTML=html.trim(); return d.firstChild; }
function toast(msg, ok=true){
  const t = document.getElementById("toast"); t.textContent = msg; t.className = ok ? "ok" : "err";
  t.style.display = "block"; setTimeout(()=> t.style.display = "none", 3000);
}
/* 业务头像：名称首字符 + 哈希纯色 monogram（不用 emoji/渐变） */
function avatarFor(name, size){
  const ch = [...String(name || "agent")][0] || "A";
  const h = [...String(name)].reduce((a,c)=>(a*31+c.charCodeAt(0))>>>0,7) % 360;
  return `<div class="avatar" style="width:${size}px;height:${size}px;font-size:${Math.round(size*0.42)}px;
    background:hsl(${h} 30% 38%)">${esc(ch)}</div>`;
}
/* 状态灯：体检/模式徽章/图例共用 */
function led(color, pulse){
  return `<span class="led${pulse ? " pulse" : ""}"${color ? ` style="color:${color}"` : ""}></span>`;
}
"""

PAGE = r"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#f7f5ef">
<title>Data Agent 校验工作台</title>
<style>__CSS__</style></head><body>
<div id="toast" aria-live="polite"></div>
<div class="shell">
  <aside class="side">
    <div class="brand">
      <svg class="mark" viewBox="0 0 36 36" aria-hidden="true"><rect x="1.4" y="1.4" width="33.2" height="33.2" rx="9.5" fill="none" stroke="currentColor" stroke-width="1.7"/><circle cx="18" cy="18" r="9" fill="none" stroke="currentColor" stroke-width="1.2" opacity=".4"/><circle cx="24" cy="12" r="3.1" fill="var(--acc)" stroke="none"/></svg>
      <div><div class="micro">Data Agent</div><div class="t1">校验工作台</div><div class="t2" id="agentName"></div></div>
    </div>
    <nav class="nav" id="nav"></nav>
    <button class="done hidden" id="doneBtn">✓ 完成 · 关闭工作台</button>
  </aside>
  <div class="main">
    <header class="dochead">
      <div><div class="micro" id="docMeta">Agent Dossier</div><h1 id="pageTitle">概览</h1><div class="meta" id="meta"></div></div>
      <span class="modebadge" id="modeBadge"></span>
    </header>
    <div id="panels"></div>
  </div>
</div>
<script>
__CJS__
const DATA = __DATA__;
const EDIT = __EDIT__;
const $ = s => document.querySelector(s);
let dirty = false;
window.onbeforeunload = () => dirty ? "有未保存的修改" : null;

/* ---------- 基础设施 ---------- */
function savedBadge(host){
  const b = el('<span class="saved">✓ 已保存</span>');
  host.append(b); setTimeout(()=> b.remove(), 2600);
}
async function save(file, content){
  try{
    const r = await fetch("/save", {method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({file, content})});
    const j = await r.json();
    if(j.ok){ dirty=false; DATA.files[file]=content; toast("已保存 ✓ 备份 "+j.backup); }
    else toast("保存失败："+(j.error||"")+"。可在源文件中手动修改，或检查文件权限。", false);
    return j.ok;
  }catch(e){ toast("保存失败："+e.message+"。可检查工作台服务是否还在运行。", false); return false; }
}
function splitSections(text){ return text.split(/(?=^#{1,3}\s)/m).filter(c=>c.length); }

/* markdown-lite 渲染 */
function mdLite(text){
  const inline = s => esc(s)
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/`([^`]+)`/g, '<code class="ic">$1</code>');
  const lines = text.split("\n"); let html = "", inPara = [], inTbl = [];
  const flush = () => {
    if(inPara.length){ html += `<div style="padding:3px 0;font-size:13px">${inPara.map(inline).join("<br>")}</div>`; inPara=[]; }
  };
  const flushTbl = () => {
    if(!inTbl.length) return;
    const rows = inTbl.map(l => l.trim().replace(/^\||\|$/g,"").split("|").map(c => c.trim()));
    const isSep = r => r.every(c => /^:?-{2,}:?$/.test(c));
    let head = null;
    if(rows.length > 1 && isSep(rows[1])){ head = rows[0]; rows.splice(0, 2); }
    else if(isSep(rows[0])) rows.shift();
    html += "<table>" + (head ? `<tr>${head.map(c=>`<th>${inline(c)}</th>`).join("")}</tr>` : "")
      + rows.map(r=>`<tr>${r.map(c=>`<td>${inline(c)}</td>`).join("")}</tr>`).join("") + "</table>";
    inTbl = [];
  };
  for(const ln of lines){
    const t = ln.trim();
    if(t.startsWith("|") && t.endsWith("|")){ flush(); inTbl.push(ln); continue; }
    flushTbl();
    if(!t){ flush(); continue; }
    let m;
    if(m = t.match(/^(#{1,4})\s+(.+)/)){ flush();
      html += `<div class="mh">${inline(m[2])}</div>`;
    } else if(m = t.match(/^(\d+)[.、]\s*(.+)/)){ flush();
      html += `<div class="step"><div class="sn">${m[1]}</div><div>${inline(m[2])}</div></div>`;
    } else if(t.startsWith("- ")){ flush();
      html += `<div class="bullet"><div>${inline(t.slice(2))}</div></div>`;
    } else if(t.startsWith("> ")){ flush();
      html += `<div class="quote">${inline(t.slice(2))}</div>`;
    } else if(/^-{3,}$/.test(t)){ flush(); }
    else inPara.push(t);
  }
  flushTbl(); flush();
  return html;
}
function biUrl(pgId){ return DATA.biBaseUrl ? DATA.biBaseUrl + "/page/" + pgId : null; }

/* 通用分节编辑器 */
function sectionEditor(file, renderChunk){
  const chunks = splitSections(DATA.files[file] || "");
  const wrap = document.createElement("div");
  chunks.forEach((chunk, i) => {
    const card = document.createElement("div");
    const paint = (justSaved) => {
      card.innerHTML = ""; card.append(renderChunk(chunk, () => startEdit(), i));
      if(justSaved){ const h = card.querySelector("h3, summary"); if(h) savedBadge(h); }
    };
    const startEdit = () => {
      card.innerHTML = "";
      const ta = document.createElement("textarea"); ta.value = chunk;
      ta.setAttribute("aria-label", "编辑本段内容");
      ta.rows = Math.min(22, chunk.split("\n").length + 2);
      const row = document.createElement("div"); row.className = "btnrow";
      const ok = el('<button class="btn primary">保存</button>');
      const no = el('<button class="btn">取消</button>');
      ok.onclick = async () => { chunks[i] = ta.value; dirty = true;
        if(await save(file, chunks.join(""))) paint(true); };
      no.onclick = () => paint();
      row.append(ok, no); card.append(ta, row);
      ta.focus();
    };
    paint(); wrap.append(card);
  });
  return wrap;
}
function editBtn(onClick){
  if(!EDIT) return document.createTextNode("");
  const b = el('<button class="btn mini">编辑</button>');
  b.onclick = (e) => { e.preventDefault(); e.stopPropagation(); onClick(); };
  return b;
}
function secTitle(chunk){
  const m = chunk.match(/^(#{1,3})\s*(.+)/);
  return m ? m[2].replace(/[*#]/g,"").trim().slice(0,40) : "说明";
}
function emptyState(title, guide){
  return el(`<div class="empty"><div class="t">${esc(title)}</div>${esc(guide)}</div>`);
}
function pagesOf(){
  if(!DATA.assets) return [];
  const norm = Object.entries(DATA.assets).filter(([k,v]) =>
    k !== "_meta" && v && typeof v === "object" && !Array.isArray(v) && v.cards && !Array.isArray(v.cards));
  if(norm.length) return norm;
  /* 旧版结构降级：pages 为 {名称: pgId} 字典或 [{name, pageId, cards:[...]}] 列表 */
  const old = DATA.assets.pages;
  if(Array.isArray(old)) return old.map(p => [p.name || p.pageId || "看板", {pgId: p.pageId || p.pgId || "",
    cards: Object.fromEntries((p.cards || []).map(c => [c.name || String(c), {type: c.type || "", notes: c.note || ""}]))}]);
  if(old && typeof old === "object"){
    /* 更旧的平铺 schema：cards 为 {"看板__卡片名": {page, type, ...}} 字典，按 page 字段归组 */
    const flat = DATA.assets.cards, byPage = {};
    if(flat && typeof flat === "object") for(const [k, c] of Object.entries(flat)){
      const pg = (c && c.page) || k.split("__")[0];
      const cn = k.includes("__") ? k.split("__").slice(1).join("__") : k;
      (byPage[pg] = byPage[pg] || {})[cn] = c || {};
    }
    return Object.entries(old).map(([n, id]) => [n, {pgId: id, cards: byPage[n] || {}}]);
  }
  return [];
}

/* ---------- 概览 ---------- */
function overviewPanel(){
  const wrap = document.createElement("div");
  const id = DATA.identity || {};
  const pages = pagesOf();
  let nCards = 0; pages.forEach(([,info]) => nCards += Object.keys(info.cards||{}).length);
  const meta = (DATA.assets && DATA.assets._meta) || {};
  const bk = DATA.files["businessKnowledge.md"];
  const nRules = bk ? (bk.match(/^(?:\*\*)?\d+\.(?=\s|【)/gm) || []).length : 0;
  /* 身份卡 */
  const triggers = (id.triggers || []).map(t=>`<span class="tag">${esc(t)}</span>`).join("");
  const metaBits = [`${pages.length} 张看板`, `${nCards} 张卡片`];
  if(nRules) metaBits.push(`${nRules} 条口径`);
  if(meta.builtAt) metaBits.push("学习于 " + esc(meta.builtAt));
  const card = el(`<div class="sheet idsheet">
    <div class="id-top">${avatarFor(id.name || "agent", 64)}
      <div style="flex:1;min-width:0">
        <div class="micro">Agent Identity${id.version ? " · v" + esc(id.version) : ""}</div>
        <h2 class="id-name">${esc(id.name || agentDisplayName())}</h2>
        <div class="id-desc">${esc(id.description || "（未找到 agent 描述）")}</div>
      </div></div>
    ${triggers ? `<div class="id-tags"><span class="micro" style="margin-right:4px">触发词</span>${triggers}</div>` : ""}
    <div class="id-meta">${metaBits.map(b=>`<span>${b}</span>`).join("")}</div>
  </div>`);
  wrap.append(card);
  /* 数据源链接 */
  if(pages.length){
    const rows = pages.map(([name, info], i) => {
      const u = biUrl(info.pgId);
      const pm = (meta.pages||{})[info.pgId];
      return `<div class="frow"><div class="k">看板 ${String(i+1).padStart(2,"0")}</div>
        <div class="v">${u ? `<a href="${esc(u)}" target="_blank" rel="noopener">${esc(name)}&nbsp;↗</a>` : esc(name)}
        <span style="color:var(--ink3);font-size:12px">${pm && pm.mtime ? "&nbsp;&nbsp;学习时更新于 " + esc(pm.mtime) : ""}</span></div></div>`;
    }).join("");
    wrap.append(el(`<div class="block"><h3>数据源 <span class="sub">Source · 点击跳转 BI 平台</span></h3>${rows}</div>`));
  }
  /* 体检区 */
  const hz = el(`<div class="block"><h3>资产体检 <span class="sub">Diagnostic</span></h3>
    <div class="hbody" style="font-size:13px;color:var(--ink2);max-width:56em"></div><div class="btnrow"></div></div>`);
  const hbody = hz.querySelector(".hbody"), hrow = hz.querySelector(".btnrow");
  if(!meta.pages){
    hbody.textContent = "这个 agent 没有记录学习时点（旧版搭建），无法自动体检。可重新搭建或在对话中说「体检资产」。";
  } else if(EDIT){
    hbody.textContent = "检查看板在学习之后是否被修改过（具体报出增删的卡片）；改过的看板需要重新学习，否则助手会引用旧数据。";
    const btn = el(`<button class="btn primary">${led("#fff")}开始体检</button>`);
    const out = el('<div style="margin-top:12px"></div>');
    btn.onclick = async () => {
      btn.disabled = true; btn.innerHTML = led("#fff", true) + "体检中…";
      try{
        const r = await fetch("/check", {method:"POST"}); const j = await r.json();
        out.innerHTML = j.pages.map(p => {
          const st = p.error ? ["var(--err)", "看板不存在或无权访问"]
            : p.stale ? ["var(--warn)", `已更新 ${esc(p.current)}（学习时 ${esc(p.learned)||"未知"}）→ 建议重新学习`]
            : ["var(--ok)", "未变化"];
          const detail = p.stale && p.detail ? `<div style="margin-top:2px;font-size:12px;color:var(--warn)">${esc(p.detail)}</div>` : "";
          return `<div class="diag">${led(st[0])}<div class="dt">${esc(p.title)}&nbsp;&nbsp;<span style="color:var(--ink2)">${st[1]}</span>${detail}</div></div>`;
        }).join("");
        let notes = "";
        if(j.overdue) notes += `<div class="diag">${led("var(--warn)")}<div class="dt" style="color:var(--ink2)">距上次学习已 ${Math.floor(j.ageDays)} 天，超过 ${j.freshDays} 天复核阈值——即使看板未变，也建议复核口径是否仍然适用</div></div>`;
        if(j.upgradeAvailable) notes += `<div class="diag">${led("var(--acc)")}<div class="dt" style="color:var(--ink2)">运行脚本可升级：搭建版本 v${esc(j.builderVersion)||"3.0-"} → 当前 v${esc(j.builderCurrent)}，在对话中说「升级脚本」即可更新</div></div>`;
        out.innerHTML += notes;
        const staleN = j.pages.filter(p=>p.stale||p.error).length;
        toast(staleN ? `体检完成：${staleN} 张看板有变化，建议重新学习` : "体检完成：全部看板未变化 ✓", !staleN);
      }catch(e){ toast("体检失败：" + e.message, false); }
      btn.disabled = false; btn.innerHTML = led("#fff") + "重新体检";
    };
    hrow.append(btn); hz.append(out);
  } else {
    hbody.textContent = "只读页面无法联网体检。想知道资产是否过期，在对话中对助手说「体检资产」即可。";
  }
  wrap.append(hz);
  return wrap;
}

/* ---------- 数据资产 ---------- */
function assetsPanel(){
  const wrap = document.createElement("div");
  const pages = pagesOf();
  if(!pages.length){ wrap.append(emptyState("还没有数据资产", "完成第 2 步看板学习后，这里会列出所有看板和卡片。")); return wrap; }
  let nCards = 0, nDisabled = 0;
  pages.forEach(([,info]) => Object.values(info.cards||{}).forEach(c => { nCards++; if(c["禁用"]) nDisabled++; }));
  wrap.append(el(`<div class="metrics">
    <div class="metric"><div class="n">${pages.length}</div><div class="l micro">看板 · Pages</div></div>
    <div class="metric"><div class="n">${nCards}</div><div class="l micro">数据卡片 · Cards</div></div>
    <div class="metric"><div class="n" style="color:${nDisabled?"var(--err)":"inherit"}">${nDisabled}</div><div class="l micro">标记禁用 · Disabled</div></div>
  </div>`));
  pages.forEach(([name, info], idx) => {
    let rows = "";
    for(const [cn, c] of Object.entries(info.cards || {})){
      let tags = "";
      if(c["全景"]) tags += `<span class="tag t-ok">${led()}全景</span> `;
      if(c["下钻"]) tags += `<span class="tag t-warn">${led()}下钻/局部</span> `;
      if(c["禁用"]) tags += `<span class="tag t-err">${led()}禁用</span>`;
      rows += `<tr><td>${esc(cn)}</td><td class="mono" style="font-size:11.5px;color:var(--ink2)">${esc(c.type||"—")}</td>
        <td>${tags}</td><td style="color:var(--ink2)">${esc(c.notes||"")}</td></tr>`;
    }
    const u = biUrl(info.pgId);
    const link = u ? `<a href="${esc(u)}" target="_blank" rel="noopener" style="margin-left:auto;font-size:12px;font-weight:400">在 BI 中打开&nbsp;↗</a>` : "";
    const d = el(`<details class="card"${idx===0?" open":""}>
      <summary><span class="arrow" aria-hidden="true">▶</span>${esc(name)}
      <span class="sub">${Object.keys(info.cards||{}).length} Cards</span>${link}</summary>
      <div class="body"><table><tr><th>卡片 Card</th><th style="width:170px">类型 Type</th><th style="width:150px">状态 Status</th><th>备注 Notes</th></tr>${rows}</table></div>
    </details>`);
    wrap.append(d);
  });
  if(DATA.files["learningResult.md"]){
    wrap.append(el('<div class="hint">以下为 AI 对每张看板的理解（资产目录），逐块核对，点「编辑」可直接修改</div>'));
    wrap.append(learningEditor());
  }
  return wrap;
}
function learningEditor(){
  return sectionEditor("learningResult.md", (chunk, startEdit) => {
    const frag = document.createElement("div"); frag.className = "block";
    const title = secTitle(chunk);
    const head = el(`<h3>${esc(title)}</h3>`);
    head.append(editBtn(startEdit));
    frag.append(head);
    const body = chunk.replace(/^#{1,3}[^\n]*\n?/, "");
    const fieldRe = /^\*\*([^*：]+)[：:]\*\*\s*(.*)$/;
    const rows = []; let intro = [];
    for(const ln of body.split("\n")){
      const m = ln.match(fieldRe);
      if(m) rows.push({k: m[1].trim(), lines: [m[2].trim()]});
      else if(rows.length) rows[rows.length-1].lines.push(ln);
      else intro.push(ln);
    }
    let html = intro.join("\n").trim() ? mdLite(intro.join("\n")) : "";
    for(const r of rows){
      const v = r.lines.join("\n").trim();
      html += `<div class="frow"><div class="k">${esc(r.k)}</div>
        <div class="v">${v ? mdLite(v) : ""}</div></div>`;
    }
    const bd = document.createElement("div"); bd.innerHTML = html; frag.append(bd);
    return frag;
  });
}

/* ---------- 业务口径 ---------- */
function parseRule(rule){
  let r = rule.replace(/\n+$/,"");
  /* 兼容整行加粗的标题行：**1.【确认】名称 = 内容**（去掉编号后首行仍带 ** 包裹） */
  const nl = r.indexOf("\n");
  const fl = (nl<0 ? r : r.slice(0,nl)).trim();
  if(/^\*\*[^*]+\*\*$/.test(fl)) r = fl.slice(2,-2) + (nl<0 ? "" : r.slice(nl));
  const m = r.match(/^(?:【([^】]+)】)?\s*(?:\*\*)?([^*=\n：:]{1,60}?)(?:\*\*)?\s*[=：:]\s*([\s\S]*)$/);
  if(m){
    let b = m[3].trim();
    /* 旧版整行加粗拆分后，正文首行可能残留不配对的结尾 **，清掉 */
    const bi = b.indexOf("\n");
    const bf = bi<0 ? b : b.slice(0, bi);
    if(/\*\*$/.test(bf) && (bf.split("**").length - 1) % 2 === 1)
      b = bf.slice(0, -2) + (bi<0 ? "" : b.slice(bi));
    return {src:m[1]||"", title:m[2].trim(), body:b};
  }
  const t = (nl<0 ? r : r.slice(0,nl)).replace(/\*\*/g,"").trim();
  const sm = t.match(/^【([^】]+)】/);
  return {src:sm?sm[1]:"", title:(sm?t.slice(sm[0].length):t).trim(), body:(nl<0?"":r.slice(nl+1).trim())};
}
/* ---------- 指标档案（metrics.json 表格视图） ---------- */
const SAFETY_LABEL = {FREE:"可自由换维度",DISTINCT:"换维度须明细现算·去重",AVG:"换维度须明细现算·均值",
  NONADDITIVE:"换维度须明细现算·最值",ROW_LOGIC:"含行级判断逻辑",TIME_MACRO:"与时间宏绑定",CONSTANT:"硬编码常量"};
const SOURCE_LABEL = {card:"看板卡片",dataset:"数据集",user:"用户确认",sql:"SQL 口径"};
function metricsPanel(){
  const raw = DATA.files["metrics.json"];
  if(!raw) return null;
  const wrap = document.createElement("div");
  let doc;
  try{ doc = JSON.parse(raw); }catch(e){
    wrap.append(el(`<div class="hint">metrics.json 解析失败：${esc(e.message)}——可在「输出与脚本」页修复</div>`));
    return wrap;
  }
  if(!Array.isArray(doc.metrics)) doc.metrics = [];
  if(!Array.isArray(doc.rejected)) doc.rejected = [];
  wrap.append(el(`<div class="hint">指标档案 <b style="font-family:var(--mono)">${doc.metrics.length}</b> 项——助手认这些标准名和别名，算法与换维度规则逐行核对${EDIT?"，右侧可编辑":""}</div>`));
  const list = document.createElement("div"); wrap.append(list);

  async function commit(){
    doc.updatedAt = new Date().toISOString().slice(0,10);
    return save("metrics.json", JSON.stringify(doc, null, 1) + "\n");
  }
  function editForm(m, idx){
    const form = el(`<div class="medit"></div>`);
    const csv = v => (v||[]).join("，");
    const uncsv = s => s.split(/[,，、]/).map(x=>x.trim()).filter(Boolean);
    form.innerHTML = `
      <label>指标名</label><input data-k="name" value="${esc(m.name||"")}">
      <label>算法</label><input data-k="formula" value="${esc(m.formula||"")}" placeholder="如 sum([实收])-sum([退款])；物理字段留空填下一行">
      <label>物理字段</label><input data-k="baseField" value="${esc(m.baseField||"")}" placeholder="无公式时填字段名">
      <label>别名</label><input data-k="synonyms" value="${esc(csv(m.synonyms))}" placeholder="逗号分隔，禁止与其他指标撞车">
      <label>维度</label><input data-k="dims" value="${esc(csv(m.dims))}" placeholder="逗号分隔">
      <label>单位</label><input data-k="unit" value="${esc(m.unit||"")}">
      <label>换维度</label><select data-k="safety">${Object.keys(SAFETY_LABEL).map(k=>
        `<option value="${k}"${m.safety===k?" selected":""}>${k} · ${SAFETY_LABEL[k]}</option>`).join("")}</select>
      <label>来源</label><select data-k="source">${Object.keys(SOURCE_LABEL).map(k=>
        `<option value="${k}"${m.source===k?" selected":""}>${SOURCE_LABEL[k]}</option>`).join("")}</select>
      <label>备注</label><input data-k="note" value="${esc(m.note||"")}">`;
    const row = el('<div class="btnrow"></div>');
    const ok = el('<button class="btn primary">保存</button>');
    const no = el('<button class="btn">取消</button>');
    ok.onclick = async () => {
      form.querySelectorAll("[data-k]").forEach(inp => {
        const k = inp.dataset.k, v = inp.value.trim();
        if(k === "synonyms" || k === "dims") m[k] = uncsv(v);
        else if(v) m[k] = v; else delete m[k];
      });
      if(!m.name){ toast("指标名不能为空", false); return; }
      dirty = true;
      if(await commit()) draw(idx);
    };
    no.onclick = () => draw();
    row.append(ok, no); form.append(row);
    return form;
  }
  function draw(savedIdx){
    list.innerHTML = "";
    doc.metrics.forEach((m, i) => {
      const tags = [];
      if(m.safety) tags.push(`<span class="src">${esc(SAFETY_LABEL[m.safety]||m.safety)}</span>`);
      if(m.source) tags.push(`<span class="src">${esc(SOURCE_LABEL[m.source]||m.source)}</span>`);
      const metaBits = [];
      if(m.synonyms && m.synonyms.length) metaBits.push(`<span>别名 <b>${esc(m.synonyms.join("、"))}</b></span>`);
      if(m.dims && m.dims.length) metaBits.push(`<span>维度 <b>${esc(m.dims.join("、"))}</b></span>`);
      if(m.unit) metaBits.push(`<span>单位 <b>${esc(m.unit)}</b></span>`);
      const formula = m.formula || (m.baseField ? m.baseField + (m.aggrType ? "（" + m.aggrType + "）" : "") : "");
      const card = el(`<div class="rule formula">
        <div class="num">${String(i+1).padStart(2,"0")}</div>
        <div><div class="rhead"><span class="rtitle">${esc(m.name||"（未命名）")}</span>${tags.join("")}</div>
        ${formula?`<div class="mformula">${esc(formula)}</div>`:""}
        ${metaBits.length?`<div class="mmeta">${metaBits.join("")}</div>`:""}
        ${m.note?`<div class="mnote">${esc(m.note)}</div>`:""}</div>
        <div class="acts"></div></div>`);
      if(EDIT){
        const acts = card.querySelector(".acts");
        const eb = el('<button class="btn mini">编辑</button>');
        const db = el('<button class="btn mini danger">删除</button>');
        eb.onclick = () => { card.innerHTML = ""; card.append(editForm(m, i)); };
        db.onclick = async () => {
          if(!confirm(`删除指标「${m.name}」？保存会立即写回 metrics.json（有备份可恢复）。`)) return;
          doc.metrics.splice(i,1); dirty = true; if(await commit()) draw();
        };
        acts.append(eb, db);
      }
      if(i === savedIdx) savedBadge(card.querySelector(".acts") || card.querySelector(".rhead"));
      list.append(card);
    });
    if(doc.rejected.length){
      const det = el(`<details class="card rej"><summary><span class="arrow">▶</span>已排除的候选 <span class="sub">${doc.rejected.length} 条——确认过但不收编，防止重新学习时重复提问</span></summary><div class="body"></div></details>`);
      const body = det.querySelector(".body");
      doc.rejected.forEach(r => body.append(el(`<div class="ritem"><span class="rn">${esc(r.name||"?")}</span>　${esc(r.formula||"")}${r.reason?`　· ${esc(r.reason)}`:""}</div>`)));
      list.append(det);
    }
    if(EDIT){
      const add = el('<button class="addrule">+ 加一条指标</button>');
      add.onclick = () => {
        const m = {name:"", formula:"", synonyms:[], dims:[], safety:"FREE", source:"user"};
        doc.metrics.push(m);
        draw();
        const cards = list.querySelectorAll(".rule");
        const last = cards[cards.length-1];
        last.innerHTML = ""; last.append(editForm(m, doc.metrics.length-1));
      };
      list.append(add);
    }
  }
  draw();
  return wrap;
}

/* ---------- 维度档案（dimensions.json 表格视图） ---------- */
function dimsPanel(){
  const raw = DATA.files["dimensions.json"];
  if(!raw) return null;
  const wrap = document.createElement("div");
  let doc;
  try{ doc = JSON.parse(raw); }catch(e){
    wrap.append(el(`<div class="hint">dimensions.json 解析失败：${esc(e.message)}——可在「输出与脚本」页修复</div>`));
    return wrap;
  }
  if(!Array.isArray(doc.dimensions)) doc.dimensions = [];
  wrap.append(el(`<div class="hint">维度档案 <b style="font-family:var(--mono)">${doc.dimensions.length}</b> 个——助手靠它们判断「你在问哪个维度、说的是哪个成员值」，叫法与成员值逐行核对${EDIT?"，右侧可编辑":""}</div>`));
  const list = document.createElement("div"); wrap.append(list);

  async function commit(){
    doc.updatedAt = new Date().toISOString().slice(0,10);
    return save("dimensions.json", JSON.stringify(doc, null, 1) + "\n");
  }
  function editForm(d, idx){
    const form = el(`<div class="medit"></div>`);
    const csv = v => (v||[]).join("，");
    const uncsv = s => s.split(/[,，、]/).map(x=>x.trim()).filter(Boolean);
    const aliasText = Object.entries(d.valueAliases||{}).map(([k,v])=>`${k}=${v}`).join("\n");
    form.innerHTML = `
      <label>维度名</label><input data-k="name" value="${esc(d.name||"")}">
      <label>字段名</label><input data-k="field" value="${esc(d.field||"")}" placeholder="数据集字段名，默认同维度名">
      <label>叫法</label><input data-k="synonyms" value="${esc(csv(d.synonyms))}" placeholder="逗号分隔，禁止与其他维度/指标撞车">
      <label>成员值</label><input data-k="values" value="${esc(csv(d.values))}" placeholder="逗号分隔，来自取数结果，禁止编造">
      <label>值别名</label><textarea data-k="valueAliases" rows="3" placeholder="每行一条：别名=标准成员值，如 华东区=华东">${esc(aliasText)}</textarea>
      <label>易混维度</label><input data-k="similarTo" value="${esc(csv(d.similarTo))}" placeholder="逗号分隔">
      <label>层级上卷</label><input data-k="parent" value="${esc(d.parent||"")}" placeholder="如 城市 上卷到 省份">
      <label>来源</label><select data-k="source">${Object.keys(SOURCE_LABEL).map(k=>
        `<option value="${k}"${d.source===k?" selected":""}>${SOURCE_LABEL[k]}</option>`).join("")}</select>
      <label>备注</label><input data-k="note" value="${esc(d.note||"")}">`;
    const row = el('<div class="btnrow"></div>');
    const ok = el('<button class="btn primary">保存</button>');
    const no = el('<button class="btn">取消</button>');
    ok.onclick = async () => {
      form.querySelectorAll("[data-k]").forEach(inp => {
        const k = inp.dataset.k, v = inp.value.trim();
        if(k === "synonyms" || k === "values" || k === "similarTo"){
          const arr = uncsv(v);
          if(arr.length) d[k] = arr; else delete d[k];
        }else if(k === "valueAliases"){
          const obj = {};
          v.split("\n").forEach(line => {
            const m = line.match(/^([^=＝]+)[=＝](.+)$/);
            if(m) obj[m[1].trim()] = m[2].trim();
          });
          if(Object.keys(obj).length) d.valueAliases = obj; else delete d.valueAliases;
        }
        else if(v) d[k] = v; else delete d[k];
      });
      if(!d.name){ toast("维度名不能为空", false); return; }
      dirty = true;
      if(await commit()) draw(idx);
    };
    no.onclick = () => draw();
    row.append(ok, no); form.append(row);
    return form;
  }
  function draw(savedIdx){
    list.innerHTML = "";
    doc.dimensions.forEach((d, i) => {
      const tags = [];
      if(d.source) tags.push(`<span class="src">${esc(SOURCE_LABEL[d.source]||d.source)}</span>`);
      if(d.similarTo && d.similarTo.length)
        tags.push(`<span class="src warn">易混：${esc(d.similarTo.join("、"))}</span>`);
      if(d.parent) tags.push(`<span class="src">上卷 ${esc(d.parent)}</span>`);
      const metaBits = [];
      if(d.synonyms && d.synonyms.length) metaBits.push(`<span>叫法 <b>${esc(d.synonyms.join("、"))}</b></span>`);
      if(d.values && d.values.length){
        const shown = d.values.slice(0,8).join("、");
        metaBits.push(`<span>成员值 <b>${d.values.length} 个</b>（${esc(shown)}${d.values.length>8?" 等":""}）</span>`);
      }
      const aliases = Object.entries(d.valueAliases||{});
      const card = el(`<div class="rule formula">
        <div class="num">${String(i+1).padStart(2,"0")}</div>
        <div><div class="rhead"><span class="rtitle">${esc(d.name||"（未命名）")}</span>${tags.join("")}</div>
        ${d.field && d.field !== d.name ? `<div class="mformula">${esc(d.field)}</div>` : ""}
        ${metaBits.length?`<div class="mmeta">${metaBits.join("")}</div>`:""}
        ${aliases.length?`<div class="mmeta">${aliases.map(([k,v])=>`<span class="src">${esc(k)} → ${esc(v)}</span>`).join("")}</div>`:""}
        ${d.note?`<div class="mnote">${esc(d.note)}</div>`:""}</div>
        <div class="acts"></div></div>`);
      if(EDIT){
        const acts = card.querySelector(".acts");
        const eb = el('<button class="btn mini">编辑</button>');
        const db = el('<button class="btn mini danger">删除</button>');
        eb.onclick = () => { card.innerHTML = ""; card.append(editForm(d, i)); };
        db.onclick = async () => {
          if(!confirm(`删除维度「${d.name}」？保存会立即写回 dimensions.json（有备份可恢复）。`)) return;
          doc.dimensions.splice(i,1); dirty = true; if(await commit()) draw();
        };
        acts.append(eb, db);
      }
      if(i === savedIdx) savedBadge(card.querySelector(".acts") || card.querySelector(".rhead"));
      list.append(card);
    });
    if(EDIT){
      const add = el('<button class="addrule">+ 加一条维度</button>');
      add.onclick = () => {
        const d = {name:"", synonyms:[], values:[], source:"user"};
        doc.dimensions.push(d);
        draw();
        const cards = list.querySelectorAll(".rule");
        const last = cards[cards.length-1];
        last.innerHTML = ""; last.append(editForm(d, doc.dimensions.length-1));
      };
      list.append(add);
    }
  }
  draw();
  return wrap;
}

/* ---------- 业务口径 ---------- */
function rulesPanel(){
  const wrap = document.createElement("div");
  const mb = metricsPanel();
  if(mb) wrap.append(mb);
  const dp = dimsPanel();
  if(dp) wrap.append(dp);
  const text = DATA.files["businessKnowledge.md"];
  if(!text) { wrap.append(emptyState("还没有业务口径", "完成第 4 步口径确认后，这里会列出逐条规则。")); return wrap; }
  wrap.append(el(`<div class="hint">共 <b class="ruleCount" style="font-family:var(--mono)"></b> 条已确认口径——它们决定助手的计算方式，逐条核对，右侧可编辑或删除</div>`));
  const parts = text.split(/(?=^(?:\*\*)?\d+\.(?=\s|【))/m);
  const pre = parts[0];
  const rules = parts.slice(1).map(r => r.replace(/^(?:\*\*)?\d+\./, ""));
  const list = document.createElement("div"); wrap.append(list);
  async function commit(){
    const body = rules.map((r,i)=> (i+1)+". "+r.replace(/\n+$/,"")).join("\n") + "\n";
    return save("businessKnowledge.md", pre + body);
  }
  function draw(savedIdx){
    list.innerHTML = "";
    const rc = wrap.querySelector(".ruleCount");
    if(rc) rc.textContent = rules.length;
    rules.forEach((rule, i) => {
      const p = parseRule(rule);
      const warn = /^⚠️\s*/.test(p.title);
      if(warn) p.title = p.title.replace(/^⚠️\s*/, "");
      const isFormula = /公式|归因/.test(p.title);
      const card = el(`<div class="rule${isFormula?" formula":""}">
        <div class="num">${String(i+1).padStart(2,"0")}</div>
        <div><div class="rhead">${p.src?`<span class="src">${esc(p.src)}</span>`:""}<span class="rtitle">${esc(p.title||"规则")}</span>${warn?'<span class="src warn">注意</span>':""}</div>
        <div class="rbody">${mdLite(p.body)}</div></div>
        <div class="acts"></div></div>`);
      if(EDIT){
        const acts = card.querySelector(".acts");
        const eb = el('<button class="btn mini">编辑</button>');
        const db = el('<button class="btn mini danger">删除</button>');
        eb.onclick = () => {
          card.innerHTML = "";
          const ta = document.createElement("textarea"); ta.value = rule.trim();
          ta.setAttribute("aria-label", `编辑第 ${i+1} 条规则`);
          ta.rows = Math.min(14, rule.split("\n").length + 2);
          const row = document.createElement("div"); row.className = "btnrow";
          const ok = el('<button class="btn primary">保存这条</button>');
          const no = el('<button class="btn">取消</button>');
          ok.onclick = async () => { rules[i] = ta.value; dirty = true; if(await commit()) draw(i); };
          no.onclick = () => draw();
          row.append(ok, no); card.append(ta, row);
          ta.focus();
        };
        db.onclick = async () => {
          if(!confirm(`删除第 ${i+1} 条规则？删除后保存会立即写回文件（有备份可恢复）。`)) return;
          rules.splice(i,1); dirty = true; if(await commit()) draw();
        };
        acts.append(eb, db);
      }
      if(i === savedIdx) savedBadge(card.querySelector(".acts") || card.querySelector(".rhead"));
      list.append(card);
    });
    if(EDIT){
      const add = el('<button class="addrule">+ 加一条规则</button>');
      add.onclick = () => {
        const v = prompt('新规则（格式：**名称** = 内容，如 **达成率** = 实际 ÷ 预算）：');
        if(v){ rules.push(v.replace(/^\d+\.\s*/,"") + "\n"); dirty = true; commit().then(ok => ok && draw(rules.length-1)); }
      };
      list.append(add);
    }
  }
  draw();
  return wrap;
}

/* ---------- 分析思路 ---------- */
function thinkingPanel(){
  if(!DATA.files["insightThinking.md"])
    return emptyState("还没有分析思路", "完成第 6 步分析框架生成后，这里会展示助手的思考方式。");
  const wrap = document.createElement("div");
  wrap.append(el('<div class="hint">助手的思考方式：角色约束、诊断链、状态阈值与四类场景流程，逐块核对</div>'));
  wrap.append(sectionEditor("insightThinking.md", (chunk, startEdit, idx) => {
    const title = secTitle(chunk);
    const card = el(`<div class="block"><h3>${esc(title)} <span class="sub">§ ${String(idx+1).padStart(2,"0")}</span></h3></div>`);
    card.querySelector("h3").append(editBtn(startEdit));
    const body = chunk.replace(/^#{1,3}[^\n]*\n?/, "");
    if(/状态标记/.test(title)){
      const items = [...body.matchAll(/^-\s*([🔴🟡🟢📈📉]+)\s*=\s*(.+)$/gm)];
      if(items.length){
        const lg = el('<div class="legend"></div>');
        items.forEach(([,e,d]) => {
          const c = (e.includes("🔴")||e.includes("📉")) ? "var(--err)"
            : e.includes("🟡") ? "var(--warn)"
            : (e.includes("🟢")||e.includes("📈")) ? "var(--ok)" : "var(--acc)";
          lg.append(el(`<span class="tag" style="font-size:12.5px">${led(c)}${esc(d)}</span>`));
        });
        card.append(lg);
        const rest = body.replace(/^-\s*[🔴🟡🟢📈📉]+\s*=.*$/gm, "").trim();
        if(rest){ const d=document.createElement("div"); d.innerHTML = mdLite(rest); card.append(d); }
        return card;
      }
    }
    const d = document.createElement("div"); d.innerHTML = mdLite(body); card.append(d);
    return card;
  }));
  return wrap;
}

/* ---------- 输出模板与脚本 ---------- */
function rawPanel(){
  const wrap = document.createElement("div");
  let any = false;
  for(const f of Object.keys(DATA.files)){
    if(["learningResult.md","businessKnowledge.md","insightThinking.md"].includes(f)) continue;
    any = true;
    if(f.endsWith(".json")){
      let pretty; try{ pretty = JSON.stringify(JSON.parse(DATA.files[f]), null, 2); }catch(e){ pretty = DATA.files[f]; }
      const card = el(`<div class="block"><h3><span class="fn">${esc(f)}</span> <span class="sub">JSON</span></h3><pre class="json">${esc(pretty)}</pre></div>`);
      if(EDIT){
        card.querySelector("h3").append(editBtn(() => {
          card.innerHTML = `<h3><span class="fn">${esc(f)}</span></h3>`;
          const ta = document.createElement("textarea"); ta.value = pretty; ta.rows = 18;
          ta.setAttribute("aria-label", "编辑 " + f);
          const row = document.createElement("div"); row.className = "btnrow";
          const ok = el('<button class="btn primary">保存</button>');
          const no = el('<button class="btn">取消</button>');
          ok.onclick = async () => {
            try{ JSON.parse(ta.value); }catch(e){ toast("JSON 格式错误："+e.message+"，请修正后再保存。", false); return; }
            dirty = true; if(await save(f, ta.value)) renderMain();
          };
          no.onclick = renderMain;
          row.append(ok, no); card.append(ta, row);
          ta.focus();
        }));
      }
      wrap.append(card);
    } else {
      const w2 = sectionEditor(f, (chunk, startEdit) => {
        const card = el(`<div class="block"><h3><span class="fn">${esc(f)}</span> <span class="sub">${esc(secTitle(chunk))}</span></h3></div>`);
        card.querySelector("h3").append(editBtn(startEdit));
        const d = document.createElement("div"); d.innerHTML = mdLite(chunk.replace(/^#{1,3}[^\n]*\n?/, ""));
        card.append(d); return card;
      });
      wrap.append(w2);
    }
  }
  if(!any) wrap.append(emptyState("无其他文件", "输出模板、SQL 指南等辅助文件会显示在这里。"));
  return wrap;
}

/* ---------- 框架 ---------- */
const TABS = [
  ["overview", "01", "概览", "Overview", overviewPanel],
  ["assets", "02", "数据资产", "Assets", assetsPanel],
  ["rules", "03", "业务口径", "Rules", rulesPanel],
  ["thinking", "04", "分析思路", "Thinking", thinkingPanel],
  ["raw", "05", "输出与脚本", "Output", rawPanel],
];
let curTab = (location.hash || "").slice(1);
if(!TABS.some(([id]) => id === curTab)) curTab = "overview";
function renderMain(){
  const panels = $("#panels"); panels.innerHTML = "";
  TABS.forEach(([id,,,,build]) => {
    const p = document.createElement("div"); p.className = "panel" + (id===curTab?" on":"");
    p.id = "p-"+id; p.append(build()); panels.append(p);
  });
}
function agentDisplayName(){
  if(DATA.identity && DATA.identity.name) return DATA.identity.name;
  const parts = DATA.dir.split("/").filter(Boolean);
  let name = parts[parts.length-1] || "";
  if(name === "references" && parts.length > 1) name = parts[parts.length-2];
  return name.replace(/^agent-/, "");
}
function summaryLine(){
  const bits = [];
  const pages = pagesOf();
  if(pages.length){
    let cn = 0; pages.forEach(([,i]) => cn += Object.keys(i.cards||{}).length);
    bits.push(pages.length + " 张看板", cn + " 张卡片");
  }
  const bk = DATA.files["businessKnowledge.md"];
  if(bk){ const n = (bk.match(/^(?:\*\*)?\d+\.(?=\s|【)/gm) || []).length; if(n) bits.push(n + " 条口径"); }
  try{ const mj = JSON.parse(DATA.files["metrics.json"] || "{}");
    if(Array.isArray(mj.metrics) && mj.metrics.length) bits.push(mj.metrics.length + " 项指标"); }catch(e){}
  try{ const dj = JSON.parse(DATA.files["dimensions.json"] || "{}");
    if(Array.isArray(dj.dimensions) && dj.dimensions.length) bits.push(dj.dimensions.length + " 个维度"); }catch(e){}
  bits.push("更新于 " + DATA.generated);
  return bits.join(" · ");
}
(function init(){
  $("#agentName").textContent = agentDisplayName();
  $("#meta").textContent = summaryLine();
  document.title = agentDisplayName() + " · Data Agent 校验工作台";
  const mb = $("#modeBadge");
  mb.innerHTML = EDIT ? led("currentColor", true) + "编辑模式 · 保存即写回" : led("currentColor") + "只读模式";
  if(EDIT) mb.classList.add("edit");
  const nav = $("#nav");
  TABS.forEach(([id, idx, label, latin]) => {
    const b = el(`<button><span class="idx" aria-hidden="true">${idx}</span><span>${label}</span></button>`);
    b.onclick = () => {
      curTab = id;
      history.replaceState(null, "", "#"+id);
      nav.querySelectorAll("button").forEach(x=>x.classList.toggle("on", x===b));
      document.querySelectorAll(".panel").forEach(p=>p.classList.toggle("on", p.id==="p-"+id));
      $("#pageTitle").textContent = label;
      $("#docMeta").textContent = "Agent Dossier / " + latin;
    };
    if(id===curTab){ b.classList.add("on"); $("#pageTitle").textContent = label;
      $("#docMeta").textContent = "Agent Dossier / " + latin; }
    nav.append(b);
  });
  if(EDIT){
    const done = $("#doneBtn"); done.classList.remove("hidden");
    done.onclick = async () => {
      if(dirty && !confirm("有未保存修改，确定关闭？")) return;
      await fetch("/shutdown", {method:"POST"});
      document.body.innerHTML = '<div style="max-width:460px;margin:140px auto;text-align:center">'
        + '<div class="micro" style="color:var(--ok)">Session Closed</div>'
        + '<h2 style="margin:14px 0 8px;font-size:24px">工作台已关闭</h2>'
        + '<p style="color:var(--ink2);font-size:13px">可以回到对话继续了</p></div>';
    };
  }
  renderMain();
})();
</script></body></html>"""

FLEET_PAGE = r"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#f7f5ef">
<title>我的 Data Agents</title>
<style>__CSS__
.agent-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:16px;margin-top:22px}
.agent-card{background:var(--sheet);border:1px solid var(--line);border-radius:14px;box-shadow:var(--shadow);
  padding:18px 20px 16px;display:flex;flex-direction:column;gap:12px}
.agent-card .hd{display:flex;gap:13px;align-items:center}
.agent-card .nm{font-size:15.5px;font-weight:700}
.agent-card .ds{font-size:12.5px;color:var(--ink2);display:-webkit-box;-webkit-line-clamp:2;
  -webkit-box-orient:vertical;overflow:hidden;min-height:2.6em}
.agent-card .ft{display:flex;flex-wrap:wrap;row-gap:3px;font-family:var(--mono);font-size:11px;
  color:var(--ink3);letter-spacing:.03em;font-variant-numeric:tabular-nums}
.agent-card .ft span + span::before{content:"·";margin:0 8px;color:var(--line2)}
.agent-card .acts{display:flex;gap:8px;margin-top:auto;padding-top:12px;border-top:1px solid var(--line)}
.agent-card .btn{flex:1;text-align:center;justify-content:center}
.stalebar{display:flex;align-items:baseline;gap:8px;font-size:12px;border-radius:8px;padding:7px 11px}
.stalebar .led{margin-top:1px}
</style></head><body>
<div id="toast" aria-live="polite"></div>
<div class="shell" style="max-width:1160px">
  <div class="main" style="width:100%">
    <header class="dochead">
      <svg viewBox="0 0 36 36" style="width:34px;height:34px;color:var(--ink);flex:none" aria-hidden="true"><rect x="1.4" y="1.4" width="33.2" height="33.2" rx="9.5" fill="none" stroke="currentColor" stroke-width="1.7"/><circle cx="18" cy="18" r="9" fill="none" stroke="currentColor" stroke-width="1.2" opacity=".4"/><circle cx="24" cy="12" r="3.1" fill="var(--acc)" stroke="none"/></svg>
      <div><div class="micro">Fleet Overview</div><h1>我的 Data Agents</h1><div class="meta" id="meta"></div></div>
      <span class="modebadge" id="modeBadge"></span>
    </header>
    <div class="agent-grid" id="grid"></div>
  </div>
</div>
<script>
__CJS__
const DATA = __DATA__;
const EDIT = __EDIT__;
document.getElementById("meta").textContent =
  DATA.dir + " · " + DATA.agents.length + " 个 agent · 生成于 " + DATA.generated;
const _mb = document.getElementById("modeBadge");
_mb.innerHTML = EDIT ? led("currentColor") + "可体检" : led("currentColor") + "只读";
if(EDIT) _mb.classList.add("edit");
const grid = document.getElementById("grid");
if(!DATA.agents.length){
  grid.append(el('<div class="empty" style="grid-column:1/-1"><div class="t">还没有搭建任何 data agent</div>在 WorkBuddy 里使用 guanbi-agent-builder 搭建后，会出现在这里。</div>'));
}
DATA.agents.forEach(a => {
  const bits = [];
  if(a.pages) bits.push(`<span>${a.pages} 看板</span>`);
  if(a.cards) bits.push(`<span>${a.cards} 卡片</span>`);
  if(a.rules) bits.push(`<span>${a.rules} 口径</span>`);
  if(a.metrics) bits.push(`<span>${a.metrics} 指标</span>`);
  if(a.dims) bits.push(`<span>${a.dims} 维度</span>`);
  if(a.builtAt) bits.push(`<span>学习于 ${esc(a.builtAt)}</span>`);
  if(a.upgradeAvailable) bits.push(`<span style="color:var(--acc)">脚本可升级→v${esc(DATA.builderCurrent||"")}</span>`);
  const card = el(`<div class="agent-card">
    <div class="hd">${avatarFor(a.name, 42)}<div><div class="nm">${esc(a.name)}</div>
      <div class="micro" style="margin-top:2px">${esc(a.dirName)}</div></div></div>
    <div class="ds">${esc(a.description || "（无描述）")}</div>
    <div class="ft">${bits.join("")}</div>
    <div class="stale"></div>
    <div class="acts"></div></div>`);
  const acts = card.querySelector(".acts");
  if(a.workbenchUrl){
    acts.append(el(`<a class="btn" href="${esc(a.workbenchUrl)}" target="_blank" rel="noopener">打开工作台&nbsp;↗</a>`));
  }
  if(EDIT && a.hasMeta){
    const cb = el(`<button class="btn primary">${led("#fff")}体检</button>`);
    cb.onclick = async () => {
      cb.disabled = true; cb.innerHTML = led("#fff", true) + "体检中…";
      const stale = card.querySelector(".stale");
      try{
        const r = await fetch("/check?agent=" + encodeURIComponent(a.dirName), {method:"POST"});
        const j = await r.json();
        const bad = j.pages.filter(p => p.stale || p.error);
        stale.innerHTML = bad.length
          ? `<div class="stalebar" style="background:var(--warn-soft);color:var(--warn)">${led("currentColor")}<span>${bad.length} 张看板在学习后被修改：${bad.map(p=>esc(p.title)).join("、")}，建议对该 agent 重新学习</span></div>`
          : `<div class="stalebar" style="background:var(--ok-soft);color:var(--ok)">${led("currentColor")}<span>全部 ${j.pages.length} 张看板未变化（${esc(j.checkedAt)}）</span></div>`;
      }catch(e){ toast("体检失败：" + e.message, false); }
      cb.disabled = false; cb.innerHTML = led("#fff") + "重新体检";
    };
    acts.append(cb);
  }
  grid.append(card);
});
if(EDIT){
  const done = el('<button class="btn" style="position:fixed;bottom:20px;right:20px;background:var(--sheet);box-shadow:var(--shadow)">✓ 完成 · 关闭</button>');
  done.onclick = async () => { await fetch("/shutdown", {method:"POST"});
    document.body.innerHTML = '<div style="max-width:460px;margin:140px auto;text-align:center">'
      + '<div class="micro" style="color:var(--ok)">Session Closed</div>'
      + '<h2 style="margin:14px 0 8px;font-size:24px">已关闭</h2></div>'; };
  document.body.append(done);
}
</script></body></html>"""


# ---------- 数据采集 ----------

def bi_base_url():
    try:
        r = subprocess.run(["guancli", "auth", "status"],
                           capture_output=True, text=True, timeout=30)
        m = re.search(r'^URL:\s*(\S+)', r.stdout, re.M)
        return m.group(1).rstrip('/') if m else ""
    except Exception:
        return ""


def parse_skill_md(path):
    """从 agent SKILL.md 提取名称/描述/触发词（名称优先 displayName → H1 → name）。"""
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read(8000)
    except OSError:
        return None
    name = re.search(r'^name:\s*(.+)$', text, re.M)
    disp = re.search(r'^displayName:\s*(.+)$', text, re.M)
    h1 = re.search(r'^#\s+(.+)$', text, re.M)
    desc = re.search(r'^description:\s*(.+)$', text, re.M)
    ver = re.search(r'^version:\s*"?([^"\n]+)"?\s*$', text, re.M)
    if not name and not desc and not h1:
        return None
    d = desc.group(1).strip() if desc else ""
    quoted = re.findall(r'["「](.+?)["」]', d)
    return {
        "name": (disp.group(1).strip() if disp else "") or (h1.group(1).strip() if h1 else "") \
                or (name.group(1).strip() if name else ""),
        "description": d[:160] + ("…" if len(d) > 160 else ""),
        "version": ver.group(1) if ver else "",
        "triggers": quoted[:5],
    }


def collect(workdir):
    data = {"dir": os.path.abspath(workdir), "generated": time.strftime("%Y-%m-%d %H:%M"),
            "assets": None, "files": {}, "identity": None, "biBaseUrl": ""}
    cj = os.path.join(workdir, "cards.json")
    if os.path.exists(cj):
        with open(cj, encoding="utf-8") as f:
            data["assets"] = json.load(f)
    meta = (data["assets"] or {}).get("_meta") or {}
    data["biBaseUrl"] = meta.get("biBaseUrl") or bi_base_url()
    if os.path.basename(os.path.normpath(workdir)) == "references":
        data["identity"] = parse_skill_md(os.path.join(os.path.dirname(os.path.abspath(workdir)), "SKILL.md"))
    for fn in sorted(os.listdir(workdir)):
        if fn.endswith((".md", ".json")) and not fn.startswith("_") and fn != "cards.json":
            with open(os.path.join(workdir, fn), encoding="utf-8") as f:
                data["files"][fn] = f.read()
    return data


def _structure_hash(cards):
    """卡片结构指纹：cdId+名称排序后取 hash。与 parse_page.py 的实现必须保持一致。"""
    items = sorted((c.get("cdId", ""), (c.get("name") or "").strip()) for c in cards)
    return sha1(json.dumps(items, ensure_ascii=False).encode("utf-8")).hexdigest()[:12]


def _ver_tuple(s):
    """"3.1.0" → (3,1,0)，解析失败返回空元组（恒小于任何有效版本）。"""
    nums = re.findall(r"\d+", s or "")
    return tuple(int(x) for x in nums[:3]) if nums else ()


def page_snapshot(pg_id):
    """取看板当前快照：{mtime, cards: [{cdId, name}] | None, error}。
    cards 为 None 表示 --raw 不可用（只拿到 mtime，无法做结构对比）。"""
    r = subprocess.run(["guancli", "page", "get", pg_id, "--raw"],
                       capture_output=True, text=True, timeout=60)
    if r.returncode == 0:
        try:
            data = json.loads(r.stdout).get("data") or {}
            cards = [{"cdId": c.get("cdId", ""),
                      "name": (c.get("name") or "").strip() or c.get("cdId", "")}
                     for c in data.get("cards") or [] if isinstance(c, dict) and c.get("cdId")]
            return {"mtime": data.get("utime", ""), "cards": cards, "error": False}
        except json.JSONDecodeError:
            pass
    # 回退：文本输出正则只拿更新时间（兼容旧版 guancli）
    r = subprocess.run(["guancli", "page", "get", pg_id],
                       capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        return {"mtime": None, "cards": None, "error": True}
    m = re.search(r'^更新时间: (.+)$', r.stdout, re.M)
    return {"mtime": m.group(1).strip() if m else "", "cards": None, "error": False}


def _diff_cards(learned, current):
    """对比学习时与当前的卡片清单，报出具体增删/改名。"""
    old = {c.get("cdId"): (c.get("name") or "").strip() for c in learned or []}
    new = {c.get("cdId"): (c.get("name") or "").strip() for c in current or []}
    added = [n for cid, n in new.items() if cid not in old]
    removed = [n for cid, n in old.items() if cid not in new]
    renamed = [f"{old[cid]}→{new[cid]}" for cid in old.keys() & new.keys() if old[cid] != new[cid]]
    return {"added": added, "removed": removed, "renamed": renamed}


def check_staleness(workdir, fresh_days=FRESH_DAYS_DEFAULT):
    """体检：mtime + 卡片结构指纹双信号对比，附复核阈值与 builder 版本升级提示。"""
    cj = os.path.join(workdir, "cards.json")
    with open(cj, encoding="utf-8") as f:
        meta = (json.load(f).get("_meta") or {})
    learned_pages = meta.get("pages") or {}

    snapshots = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futs = {pool.submit(page_snapshot, pg_id): pg_id for pg_id in learned_pages}
        for fut in as_completed(futs):
            snapshots[futs[fut]] = fut.result()

    pages = []
    for pg_id, info in learned_pages.items():
        snap = snapshots.get(pg_id) or {"mtime": None, "cards": None, "error": True}
        cur = snap["mtime"]
        stale = bool(cur) and cur != info.get("mtime", "")
        entry = {
            "pgId": pg_id, "title": info.get("title", pg_id),
            "learned": info.get("mtime", ""), "current": cur,
            "error": snap["error"], "stale": stale,
            "changes": None, "detail": "",
        }
        if stale and snap["cards"] is not None:
            if info.get("cards"):
                # 有学习时卡片清单：报具体增删/改名
                ch = _diff_cards(info["cards"], snap["cards"])
                entry["changes"] = ch
                bits = []
                if ch["added"]:
                    bits.append(f"新增 {len(ch['added'])} 张（{'、'.join(ch['added'][:5])}）")
                if ch["removed"]:
                    bits.append(f"删除 {len(ch['removed'])} 张（{'、'.join(ch['removed'][:5])}）")
                if ch["renamed"]:
                    bits.append(f"改名 {len(ch['renamed'])} 张（{'、'.join(ch['renamed'][:3])}）")
                entry["detail"] = "；".join(bits) if bits else "卡片清单未变，是配置/布局调整"
            elif info.get("cardHash"):
                # 只有指纹没有清单：能判断是否动了卡片，但报不出具体名字
                same = _structure_hash(snap["cards"]) == info["cardHash"]
                entry["detail"] = ("卡片清单未变，是配置/布局调整" if same else
                                   "卡片清单有增删（旧版档案未记录明细，重新学习后可看到具体卡片）")
            else:
                entry["detail"] = "旧版档案未记录卡片清单，无法具体对比"
        pages.append(entry)

    # 复核阈值：距上次学习超过 fresh_days 天即提醒（与看板是否变更无关）
    built_at = meta.get("builtAt", "")
    age_days = None
    try:
        age_days = (time.time() - time.mktime(time.strptime(built_at, "%Y-%m-%d %H:%M"))) / 86400
    except (ValueError, OverflowError):
        pass

    # builder 版本升级通道：交付包记录的搭建版本落后于当前脚本即提示
    pkg_ver = meta.get("builderVersion", "")

    return {
        "pages": pages, "checkedAt": time.strftime("%Y-%m-%d %H:%M"),
        "builtAt": built_at,
        "ageDays": round(age_days, 1) if age_days is not None else None,
        "freshDays": fresh_days,
        "overdue": age_days is not None and age_days > fresh_days,
        "builderVersion": pkg_ver,
        "builderCurrent": BUILDER_VERSION,
        "upgradeAvailable": bool(learned_pages) and _ver_tuple(pkg_ver) < _ver_tuple(BUILDER_VERSION),
    }


def collect_agents(skills_dir):
    out = []
    for name in sorted(os.listdir(skills_dir)):
        ref = os.path.join(skills_dir, name, "references")
        if not name.startswith("agent-") or not os.path.isdir(ref):
            continue
        a = {"dirName": name, "name": name.replace("agent-", ""), "description": "",
             "pages": 0, "cards": 0, "rules": 0, "metrics": 0, "dims": 0, "builtAt": "", "hasMeta": False,
             "builderVersion": "", "upgradeAvailable": False,
             "workbenchUrl": ""}
        ident = parse_skill_md(os.path.join(skills_dir, name, "SKILL.md"))
        if ident:
            a.update({k: ident[k] for k in ("name", "description") if ident.get(k)})
        cj = os.path.join(ref, "cards.json")
        if os.path.exists(cj):
            with open(cj, encoding="utf-8") as f:
                assets = json.load(f)
            meta = assets.get("_meta") or {}
            a["builtAt"] = meta.get("builtAt", "")
            a["hasMeta"] = bool(meta.get("pages"))
            a["builderVersion"] = meta.get("builderVersion", "")
            a["upgradeAvailable"] = a["hasMeta"] and \
                _ver_tuple(a["builderVersion"]) < _ver_tuple(BUILDER_VERSION)
            for k, v in assets.items():
                if k == "_meta":
                    continue
                if isinstance(v, dict) and isinstance(v.get("cards"), dict):
                    a["pages"] += 1
                    a["cards"] += len(v["cards"])
                elif k == "pages" and isinstance(v, dict):
                    a["pages"] += len(v)  # 旧版 schema：{pages: {名称: pgId}}
                elif k == "pages" and isinstance(v, list):
                    a["pages"] += len(v)  # 旧版 schema：{pages: [{name, pageId, cards:[...]}]}
                    a["cards"] += sum(len(p.get("cards") or []) for p in v if isinstance(p, dict))
                elif k == "cards" and isinstance(v, dict):
                    a["cards"] += len(v)  # 更旧平铺 schema：{pages: {...}, cards: {"看板__卡片名": {...}}}
        bk = os.path.join(ref, "businessKnowledge.md")
        if os.path.exists(bk):
            with open(bk, encoding="utf-8") as f:
                a["rules"] = len(re.findall(r'^(?:\*\*)?\d+\.(?=\s|【)', f.read(), re.M))
        mj = os.path.join(ref, "metrics.json")
        if os.path.exists(mj):
            try:
                with open(mj, encoding="utf-8") as f:
                    a["metrics"] = len(json.load(f).get("metrics") or [])
            except (json.JSONDecodeError, OSError):
                pass
        dj = os.path.join(ref, "dimensions.json")
        if os.path.exists(dj):
            try:
                with open(dj, encoding="utf-8") as f:
                    a["dims"] = len(json.load(f).get("dimensions") or [])
            except (json.JSONDecodeError, OSError):
                pass
        if os.path.exists(os.path.join(skills_dir, name, "workbench.html")):
            a["workbenchUrl"] = f"{name}/workbench.html"
        out.append(a)
    return out


# ---------- 渲染与服务 ----------

def render(page_tpl, data, edit):
    payload = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")
    return (page_tpl.replace("__CSS__", COMMON_CSS).replace("__CJS__", COMMON_JS)
            .replace("__DATA__", payload)
            .replace("__EDIT__", "true" if edit else "false"))


def make_handler(get_page, on_check=None, on_save=None):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype="text/html; charset=utf-8"):
            b = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):
            if urlparse(self.path).path == "/":
                self._send(200, get_page())
            else:
                self._send(404, "not found", "text/plain")

        def do_POST(self):
            u = urlparse(self.path)
            if u.path == "/shutdown":
                self._send(200, "{}", "application/json")
                import threading
                threading.Timer(0.3, self.server.shutdown).start()
                return
            if u.path == "/check" and on_check:
                q = parse_qs(u.query)
                self._send(200, json.dumps(on_check(q.get("agent", [None])[0]),
                                           ensure_ascii=False), "application/json")
                return
            if u.path == "/save" and on_save:
                try:
                    n = int(self.headers.get("Content-Length", 0))
                    req = json.loads(self.rfile.read(n) or b"{}")
                    self._send(200, json.dumps(on_save(req.get("file", ""),
                               req.get("content", "")), ensure_ascii=False), "application/json")
                except Exception as e:
                    self._send(200, json.dumps({"ok": False, "error": str(e)[:200]}),
                               "application/json")
                return
            self._send(404, "{}", "application/json")

    return H


def make_save_file(workdir):
    """生成保存回调：白名单文件（.md/.json）写回，JSON 先解析校验，旧版自动备份 .bak-<时间戳>。"""
    allowed = {fn for fn in os.listdir(workdir) if fn.endswith((".md", ".json"))}

    def save_file(fn, content):
        if fn not in allowed or "/" in fn:
            return {"ok": False, "error": "不允许的文件: " + fn}
        if fn.endswith(".json"):
            json.loads(content)
        fp = os.path.join(workdir, fn)
        backup = fn + ".bak-" + time.strftime("%Y%m%d-%H%M%S")
        if os.path.exists(fp):
            with open(fp, encoding="utf-8") as f, \
                 open(os.path.join(workdir, backup), "w", encoding="utf-8") as g:
                g.write(f.read())
        with open(fp, "w", encoding="utf-8") as f:
            f.write(content)
        return {"ok": True, "backup": backup}

    return save_file


def serve_single(workdir, fresh_days=FRESH_DAYS_DEFAULT):
    H = make_handler(lambda: render(PAGE, collect(workdir), True),
                     on_check=lambda _a: check_staleness(workdir, fresh_days),
                     on_save=make_save_file(workdir))
    server = HTTPServer(("127.0.0.1", 0), H)
    print(f"WORKBENCH_URL=http://127.0.0.1:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


def serve_fleet(skills_dir, fresh_days=FRESH_DAYS_DEFAULT):
    def check(agent_name):
        ref = os.path.join(skills_dir, agent_name or "", "references")
        if not agent_name or not os.path.isdir(ref):
            return {"pages": [], "checkedAt": time.strftime("%Y-%m-%d %H:%M")}
        return check_staleness(ref, fresh_days)
    H = make_handler(lambda: render(FLEET_PAGE, {
        "dir": os.path.abspath(skills_dir), "generated": time.strftime("%Y-%m-%d %H:%M"),
        "builderCurrent": BUILDER_VERSION,
        "agents": collect_agents(skills_dir)}, True), on_check=check)
    server = HTTPServer(("127.0.0.1", 0), H)
    print(f"WORKBENCH_URL=http://127.0.0.1:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


def main():
    argv = sys.argv[1:]
    serve_mode = "--serve" in argv
    check_mode = "--check" in argv
    agents_mode = "--agents" in argv
    fresh_days = FRESH_DAYS_DEFAULT
    if "--fresh-days" in argv:
        i = argv.index("--fresh-days")
        try:
            fresh_days = int(argv[i + 1])
        except (IndexError, ValueError):
            sys.exit("--fresh-days 需要一个整数天数")
        argv = argv[:i] + argv[i + 2:]
    args = [a for a in argv if not a.startswith("--")]

    if agents_mode:
        skills_dir = os.path.expanduser(args[0] if args else "~/.workbuddy/skills")
        if not os.path.isdir(skills_dir):
            sys.exit(f"目录不存在: {skills_dir}")
        if serve_mode:
            serve_fleet(skills_dir, fresh_days)
        else:
            out = os.path.join(skills_dir, "agents.html")
            with open(out, "w", encoding="utf-8") as f:
                f.write(render(FLEET_PAGE, {
                    "dir": os.path.abspath(skills_dir),
                    "generated": time.strftime("%Y-%m-%d %H:%M"),
                    "builderCurrent": BUILDER_VERSION,
                    "agents": collect_agents(skills_dir)}, False))
            print(f"已生成: {out}")
        return

    if not args:
        sys.exit(__doc__)
    workdir = args[0]
    if not os.path.isdir(workdir):
        sys.exit(f"目录不存在: {workdir}")
    if check_mode:
        r = check_staleness(workdir, fresh_days)
        print(f"资产体检（{r['checkedAt']}）· 复核阈值 {r['freshDays']} 天")
        for p in r["pages"]:
            if p["error"]:
                print(f"  ❌ {p['title']}：看板不存在或无权访问")
            elif p["stale"]:
                print(f"  ⚠️  {p['title']}：学习时 {p['learned'] or '未知'} → 当前 {p['current']}，建议重新学习")
                if p.get("detail"):
                    print(f"      {p['detail']}")
            else:
                print(f"  ✓  {p['title']}：未变化")
        if r.get("overdue"):
            print(f"⏰ 距上次学习已 {int(r['ageDays'])} 天，超过 {r['freshDays']} 天复核阈值——"
                  f"即使看板未变，也建议复核口径是否仍然适用")
        if r.get("upgradeAvailable"):
            print(f"⬆️ 运行脚本可升级：搭建版本 v{r['builderVersion'] or '3.0-'} → 当前 v{r['builderCurrent']}，"
                  f"在对话中说「升级脚本」即可更新交付包里的运行脚本")
        return
    if serve_mode:
        serve_single(workdir, fresh_days)
    else:
        out_dir = workdir
        if os.path.basename(os.path.normpath(workdir)) == "references":
            out_dir = os.path.dirname(os.path.abspath(workdir))  # 交付包根目录
        out = os.path.join(out_dir, "workbench.html")
        with open(out, "w", encoding="utf-8") as f:
            f.write(render(PAGE, collect(workdir), False))
        print(f"已生成: {out}")


if __name__ == "__main__":
    main()
