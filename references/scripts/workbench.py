#!/usr/bin/env python3
"""
轻量工作台：把搭建/交付产物变成可校验、可编辑的本地页面（WorkBuddy 原生风格）
用法:
  python3 workbench.py <目录>              # 生成只读 <目录>/workbench.html（双击浏览器打开）
  python3 workbench.py <目录> --serve      # 本地编辑/体检服务，打印 WORKBENCH_URL
  python3 workbench.py <目录> --check      # 体检：看板在 agent 学习后是否被改过（打印报告）
  python3 workbench.py --agents [<skills目录>]           # 多 agent 管理总览 agents.html
  python3 workbench.py --agents [<skills目录>] --serve   # 总览 + 逐个体检按钮
识别文件: cards.json（资产表格，含 _meta 学习时点）、learningResult.md、businessKnowledge.md、
          insightThinking.md；<目录>/../SKILL.md 存在时读取 agent 名称/描述/触发词
外观: 跟随系统亮/暗色；URL 加 ?dark 可强制暗色
"""
import json, os, re, subprocess, sys, time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

COMMON_CSS = r"""
:root{
  color-scheme: light;
  --bg:#f6f8f5; --card:#ffffff; --border:#dce7dd; --soft:#e8f0e9;
  --pri:#3c8c4e; --deep:#1f7237; --text:#12261ae6; --text2:#12261ab3; --text3:#12261a80;
  --ok-bg:#d1fae5; --ok:#047857; --warn-bg:#fef3c7; --warn:#b45309; --err-bg:#fee2e2; --err:#dc2626;
  --cyan:#0e7490; --cyan-bg:#06b6d414;
  --shadow:0 12px 24px -8px rgba(0,0,0,.05),0 2px 4px -4px rgba(0,0,0,.05);
  --code-bg:#12261a; --code-fg:#d7f0dd;
}
@media (prefers-color-scheme: dark){ :root{
  color-scheme: dark;
  --bg:#0e130f; --card:#182019; --border:#2a352c; --soft:#1f2c22;
  --pri:#59ac65; --deep:#8fca97; --text:#e8f0eadf; --text2:#e8f0eaaa; --text3:#e8f0ea73;
  --ok-bg:#04785733; --ok:#4ade80; --warn-bg:#d9770629; --warn:#fbbf24; --err-bg:#dc262629; --err:#f87171;
  --cyan:#67e8f9; --cyan-bg:#06b6d41f;
  --shadow:0 12px 24px -8px rgba(0,0,0,.35),0 2px 4px -4px rgba(0,0,0,.3);
  --code-bg:#0a0f0b; --code-fg:#b7e3c2;
}}
:root[data-theme=dark]{
  color-scheme: dark;
  --bg:#0e130f; --card:#182019; --border:#2a352c; --soft:#1f2c22;
  --pri:#59ac65; --deep:#8fca97; --text:#e8f0eadf; --text2:#e8f0eaaa; --text3:#e8f0ea73;
  --ok-bg:#04785733; --ok:#4ade80; --warn-bg:#d9770629; --warn:#fbbf24; --err-bg:#dc262629; --err:#f87171;
  --cyan:#67e8f9; --cyan-bg:#06b6d41f;
  --shadow:0 12px 24px -8px rgba(0,0,0,.35),0 2px 4px -4px rgba(0,0,0,.3);
  --code-bg:#0a0f0b; --code-fg:#b7e3c2;
}
*{box-sizing:border-box;margin:0}
body{background:var(--bg);color:var(--text);
  font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Helvetica Neue","Microsoft YaHei",sans-serif;
  font-size:14px;line-height:1.6;-webkit-font-smoothing:antialiased;overflow-wrap:break-word;
  -webkit-tap-highlight-color:transparent}
h1,h3{text-wrap:balance}
a{color:var(--pri);text-decoration:none}
a:hover{text-decoration:underline}
button,textarea{touch-action:manipulation;font-family:inherit}
button:focus-visible,textarea:focus-visible,summary:focus-visible,a:focus-visible{
  outline:2px solid var(--pri);outline-offset:2px;border-radius:6px}
.shell{max-width:1080px;margin:0 auto;padding:24px 20px 64px;display:flex;gap:20px;align-items:flex-start}
.side{flex:0 0 188px;position:sticky;top:24px}
.brand{display:flex;align-items:center;gap:10px;padding:6px 8px 18px}
.brand .logo{width:34px;height:34px;border-radius:10px;background:linear-gradient(135deg,#59ac65,#1f7237);
  display:flex;align-items:center;justify-content:center;font-size:17px;flex:none;color:#fff}
.brand .t1{font-weight:600;font-size:14px}.brand .t2{font-size:11px;color:var(--text3)}
.nav{display:flex;flex-direction:column;gap:4px}
.nav button{display:flex;align-items:center;gap:9px;padding:9px 12px;border:none;border-radius:10px;
  background:transparent;color:var(--text2);font-size:13.5px;cursor:pointer;text-align:left;
  transition:background-color .15s,color .15s}
.nav button:hover{background:#ffffff14}
.nav button.on{background:var(--card);color:var(--deep);font-weight:600;box-shadow:var(--shadow)}
.nav button.on .ico{background:var(--pri);color:#fff}
.nav .ico{width:22px;height:22px;border-radius:7px;background:var(--soft);display:flex;
  align-items:center;justify-content:center;font-size:12px;flex:none}
.side .done{margin-top:18px;width:100%;padding:10px;border:none;border-radius:10px;background:var(--pri);
  color:#fff;font-size:13.5px;cursor:pointer;box-shadow:var(--shadow);transition:background-color .15s}
.side .done:hover{background:var(--deep)}
.main{flex:1;min-width:0}
.topbar{background:var(--card);border:1px solid var(--border);border-radius:14px;box-shadow:var(--shadow);
  padding:16px 20px;margin-bottom:16px;display:flex;align-items:center;gap:14px;flex-wrap:wrap}
.topbar h1{font-size:19px;font-weight:650}
.topbar .meta{font-size:12px;color:var(--text3);margin-top:3px;font-variant-numeric:tabular-nums}
.mode{margin-left:auto;font-size:12px;padding:3px 10px;border-radius:999px;background:var(--soft);color:var(--deep);flex:none}
.mode.edit{background:var(--warn-bg);color:var(--warn)}
.panel{display:none}.panel.on{display:block;animation:fadein .18s ease}
@keyframes fadein{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:none}}
.hint{background:var(--card);border:1px dashed var(--border);border-radius:12px;padding:10px 14px;
  font-size:12.5px;color:var(--text2);margin-bottom:14px}
.stats{display:flex;gap:10px;margin-bottom:14px;flex-wrap:wrap}
.stat{flex:1;min-width:120px;background:var(--card);border:1px solid var(--border);border-radius:12px;
  padding:14px 18px;box-shadow:var(--shadow)}
.stat .n{font-size:26px;font-weight:700;color:var(--deep);font-variant-numeric:tabular-nums;line-height:1.2}
.stat .l{font-size:12px;color:var(--text3);margin-top:2px}
.card{background:var(--card);border:1px solid var(--border);border-radius:12px;
  box-shadow:var(--shadow);padding:16px 18px;margin-bottom:14px}
.card > h3{font-size:15px;font-weight:600;display:flex;align-items:center;gap:8px;margin-bottom:10px;flex-wrap:wrap}
.card > h3 .sub{font-size:12px;color:var(--text3);font-weight:400}
.chip{display:inline-flex;align-items:center;padding:1px 9px;border-radius:999px;font-size:11.5px;font-weight:500}
.c-ok{background:var(--ok-bg);color:var(--ok)}
.c-warn{background:var(--warn-bg);color:var(--warn)}
.c-err{background:var(--err-bg);color:var(--err)}
.c-soft{background:var(--soft);color:var(--deep)}
.c-cyan{background:var(--cyan-bg);color:var(--cyan)}
details.card{padding:0}
details.card > summary{list-style:none;cursor:pointer;padding:14px 18px;display:flex;align-items:center;
  gap:8px;font-size:14.5px;font-weight:600;border-radius:12px;transition:background-color .15s}
details.card > summary:hover{background:color-mix(in srgb,var(--pri) 6%,transparent)}
details.card > summary::-webkit-details-marker{display:none}
details.card > summary .arrow{transition:transform .15s;color:var(--text3);font-size:11px;flex:none}
details.card[open] > summary .arrow{transform:rotate(90deg)}
details.card > .body{padding:0 18px 16px;border-top:1px solid var(--border)}
details.card .sub{font-size:12px;color:var(--text3);font-weight:400}
.frow{display:flex;gap:10px;padding:7px 0;border-top:1px solid color-mix(in srgb,var(--text) 5%,transparent);font-size:13px}
.frow:first-of-type{border-top:none}
.frow .k{flex:0 0 96px;color:var(--text3);font-size:12.5px;padding-top:1px}
.frow .v{flex:1;min-width:0}
table{width:100%;border-collapse:collapse;font-size:12.5px}
th{background:var(--soft);color:var(--deep);font-weight:600;text-align:left;padding:7px 10px}
td{padding:7px 10px;border-top:1px solid color-mix(in srgb,var(--text) 6%,transparent)}
tr:hover td{background:color-mix(in srgb,var(--soft) 45%,transparent)}
.rule{background:var(--card);border:1px solid var(--border);border-radius:12px;box-shadow:var(--shadow);
  padding:14px 16px;margin-bottom:10px;position:relative}
.rule .head{display:flex;align-items:center;gap:10px;padding-right:150px}
.num{flex:none;width:24px;height:24px;border-radius:8px;background:var(--soft);color:var(--deep);
  font-size:12.5px;font-weight:700;display:flex;align-items:center;justify-content:center;
  font-variant-numeric:tabular-nums}
.rtitle{font-weight:600;font-size:14px}
.rbody{margin-top:6px;padding-left:34px;color:var(--text2);font-size:13px;line-height:1.75;white-space:pre-wrap}
.rule .acts{position:absolute;top:12px;right:12px;display:flex;gap:6px;align-items:center}
.addrule{width:100%;padding:13px;border:1.5px dashed var(--border);border-radius:12px;background:transparent;
  color:var(--text3);font-size:13px;cursor:pointer;transition:border-color .15s,color .15s,background-color .15s}
.addrule:hover{border-color:var(--pri);color:var(--deep);background:color-mix(in srgb,var(--card) 60%,transparent)}
.step{display:flex;gap:10px;padding:5px 0;font-size:13px}
.step .sn{flex:none;width:20px;height:20px;border-radius:6px;background:var(--cyan-bg);color:var(--cyan);
  font-size:11.5px;font-weight:600;display:flex;align-items:center;justify-content:center;margin-top:1px;
  font-variant-numeric:tabular-nums}
.bullet{display:flex;gap:8px;padding:3px 0;font-size:13px}
.bullet::before{content:"";flex:none;width:5px;height:5px;border-radius:50%;background:var(--pri);margin-top:9px}
.quote{border-left:3px solid var(--pri);background:var(--soft);border-radius:0 8px 8px 0;
  padding:8px 12px;margin:8px 0;font-size:12.5px;color:var(--text2)}
.legend{display:flex;gap:8px;flex-wrap:wrap;margin:8px 0}
textarea{width:100%;min-height:110px;font:13px/1.7 ui-monospace,Menlo,Consolas,monospace;
  padding:10px 12px;border:1px solid var(--border);border-radius:10px;resize:vertical;
  background:color-mix(in srgb,var(--soft) 40%,var(--card));color:var(--text);outline:none}
textarea:focus-visible{outline:none;border-color:var(--pri);box-shadow:0 0 0 3px color-mix(in srgb,var(--pri) 20%,transparent)}
.btn{padding:5px 14px;border-radius:8px;border:1px solid var(--border);background:var(--card);
  cursor:pointer;font-size:12.5px;color:var(--text);transition:border-color .15s,color .15s,background-color .15s}
.btn:hover{border-color:var(--pri);color:var(--deep)}
.btn.primary{background:var(--pri);border-color:var(--pri);color:#fff}
.btn.primary:hover{background:var(--deep);border-color:var(--deep);color:#fff}
.btn.danger:hover{border-color:var(--err);color:var(--err)}
.btn.mini{padding:2px 10px;font-size:12px}
.btnrow{margin-top:10px;display:flex;gap:8px;align-items:center}
.saved{display:inline-flex;align-items:center;font-size:12px;color:var(--ok);font-weight:500}
code.ic{background:var(--soft);border-radius:5px;padding:0 5px;font:12px ui-monospace,Menlo,monospace;color:var(--deep)}
pre.json{background:var(--code-bg);color:var(--code-fg);border-radius:10px;padding:14px;
  font:12px/1.6 ui-monospace,Menlo,monospace;overflow:auto;max-height:420px}
.empty{padding:32px 24px;text-align:center;color:var(--text3);font-size:13px}
.empty .t{font-size:14px;color:var(--text2);margin-bottom:6px}
.avatar{border-radius:12px;display:flex;align-items:center;justify-content:center;color:#fff;flex:none}
#toast{position:fixed;top:18px;right:20px;padding:9px 16px;border-radius:10px;font-size:13px;z-index:9;
  display:none;box-shadow:var(--shadow)}
#toast.ok{background:var(--ok-bg);color:var(--ok)}
#toast.err{background:var(--err-bg);color:var(--err)}
.hidden{display:none!important}
@media (max-width:760px){
  .shell{flex-direction:column;padding:16px 12px 48px}
  .side{position:static;flex:none;width:100%}
  .nav{flex-direction:row;overflow-x:auto;padding-bottom:4px}
  .nav button{flex:none}
  .side .done{width:auto}
  .rule .head{padding-right:0}
  .rule .acts{position:static;margin-top:8px;justify-content:flex-end}
}
@media print{
  body{background:#fff}
  .side,#toast,.acts,.btnrow,.addrule,.mode{display:none!important}
  .shell{display:block;max-width:none;padding:0}
  .panel{display:block!important;animation:none}
  details.card > .body{display:block}
  .card,.rule,.stat,details.card{box-shadow:none;break-inside:avoid}
}
@media (prefers-reduced-motion: reduce){
  *,*::before,*::after{animation:none!important;transition:none!important}
}
"""

COMMON_JS = r"""
if(new URLSearchParams(location.search).has("dark")) document.documentElement.dataset.theme = "dark";
const esc = s => String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
function el(html){ const d=document.createElement("div"); d.innerHTML=html.trim(); return d.firstChild; }
function toast(msg, ok=true){
  const t = document.getElementById("toast"); t.textContent = msg; t.className = ok ? "ok" : "err";
  t.style.display = "block"; setTimeout(()=> t.style.display = "none", 3000);
}
/* 业务头像：名称关键词 → 代表性 emoji + 哈希渐变 */
const AVATAR_KW = [
  [/餐饮|茶饮|外卖/, "🍜"], [/电商|跨境/, "🛒"], [/财务|费用|毛利|资金/, "💰"],
  [/制造|工厂|生产/, "🏭"], [/会员|客户|用户/, "👥"], [/供应链|库存|采购/, "🚚"],
  [/人力|人资|组织/, "🧑‍💼"], [/市场|品牌|营销/, "📣"], [/商品|产品/, "📦"],
  [/零售|门店|连锁|销售|业绩/, "🛍"], [/经营|管理|分析/, "📈"],
];
function avatarFor(name, size){
  let emoji = "🧭";
  for(const [re, e] of AVATAR_KW){ if(re.test(name)){ emoji = e; break; } }
  if(emoji === "🧭"){ const pool = ["🧭","📊","🗺️","🔭","🧮","🎯"]; emoji = pool[[...name].reduce((a,c)=>a+c.charCodeAt(0),0) % pool.length]; }
  const h = [...name].reduce((a,c)=>(a*31+c.charCodeAt(0))>>>0,7) % 360;
  return `<div class="avatar" style="width:${size}px;height:${size}px;font-size:${Math.round(size*0.52)}px;
    background:linear-gradient(135deg,hsl(${h},45%,55%),hsl(${(h+40)%360},50%,38%))">${emoji}</div>`;
}
"""

PAGE = r"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#f6f8f5">
<title>Data Agent 工作台</title>
<style>__CSS__</style></head><body>
<div id="toast" aria-live="polite"></div>
<div class="shell">
  <aside class="side">
    <div class="brand"><div class="logo" aria-hidden="true">📊</div>
      <div><div class="t1">Data Agent 工作台</div><div class="t2" id="agentName"></div></div>
    </div>
    <nav class="nav" id="nav"></nav>
    <button class="done hidden" id="doneBtn">✅ 完成，关闭工作台</button>
  </aside>
  <div class="main">
    <div class="topbar">
      <div><h1 id="pageTitle">概览</h1><div class="meta" id="meta"></div></div>
      <span class="mode" id="modeBadge"></span>
    </div>
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
  const lines = text.split("\n"); let html = "", inPara = [];
  const flush = () => {
    if(inPara.length){ html += `<div style="padding:3px 0;font-size:13px">${inPara.map(inline).join("<br>")}</div>`; inPara=[]; }
  };
  for(const ln of lines){
    const t = ln.trim();
    if(!t){ flush(); continue; }
    let m;
    if(m = t.match(/^(\d+)[.、]\s*(.+)/)){ flush();
      html += `<div class="step"><div class="sn">${m[1]}</div><div>${inline(m[2])}</div></div>`;
    } else if(t.startsWith("- ")){ flush();
      html += `<div class="bullet"><div>${inline(t.slice(2))}</div></div>`;
    } else if(t.startsWith("> ")){ flush();
      html += `<div class="quote">${inline(t.slice(2))}</div>`;
    } else if(/^-{3,}$/.test(t)){ flush(); }
    else inPara.push(t);
  }
  flush();
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
      card.innerHTML = ""; card.append(renderChunk(chunk, () => startEdit()));
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
  const b = el('<button class="btn mini">✏️ 编辑</button>');
  b.onclick = (e) => { e.preventDefault(); e.stopPropagation(); onClick(); };
  return b;
}
function secTitle(chunk){
  const m = chunk.match(/^(#{1,3})\s*(.+)/);
  return m ? m[2].replace(/[*#]/g,"").trim().slice(0,40) : "说明";
}
function emptyState(title, guide){
  return el(`<div class="card"><div class="empty"><div class="t">${esc(title)}</div>${esc(guide)}</div></div>`);
}
function pagesOf(){
  if(!DATA.assets) return [];
  return Object.entries(DATA.assets).filter(([k]) => k !== "_meta");
}

/* ---------- 概览 ---------- */
function overviewPanel(){
  const wrap = document.createElement("div");
  const id = DATA.identity || {};
  const pages = pagesOf();
  let nCards = 0; pages.forEach(([,info]) => nCards += Object.keys(info.cards||{}).length);
  const meta = (DATA.assets && DATA.assets._meta) || {};
  /* 身份卡 */
  const triggers = (id.triggers || []).map(t=>`<span class="chip c-soft" style="margin:2px 4px 2px 0">${esc(t)}</span>`).join("");
  const card = el(`<div class="card" style="display:flex;gap:16px;align-items:flex-start">
    ${avatarFor(id.name || "agent", 56)}
    <div style="flex:1;min-width:0">
      <h3 style="margin-bottom:4px">${esc(id.name || agentDisplayName())}
        <span class="sub">${esc(id.version || "")}</span></h3>
      <div style="font-size:13px;color:var(--text2);margin-bottom:8px">${esc(id.description || "（未找到 agent 描述）")}</div>
      ${triggers ? `<div style="margin-bottom:8px"><span style="font-size:12px;color:var(--text3)">触发词：</span>${triggers}</div>` : ""}
      <div style="font-size:12px;color:var(--text3)">
        ${pages.length} 张看板 · ${nCards} 张卡片${meta.builtAt ? " · 学习于 " + esc(meta.builtAt) : ""}
      </div>
    </div></div>`);
  wrap.append(card);
  /* 数据源链接 */
  if(pages.length){
    const rows = pages.map(([name, info]) => {
      const u = biUrl(info.pgId);
      const pm = (meta.pages||{})[info.pgId];
      return `<div class="frow"><div class="k" style="flex-basis:auto;min-width:96px">📈 看板</div>
        <div class="v">${u ? `<a href="${esc(u)}" target="_blank" rel="noopener">${esc(name)} ↗</a>` : esc(name)}
        <span style="color:var(--text3);font-size:12px">${pm && pm.mtime ? " · 学习时更新于 " + esc(pm.mtime) : ""}</span></div></div>`;
    }).join("");
    wrap.append(el(`<div class="card"><h3>🔗 数据源（点击跳转 BI 平台）</h3>${rows}</div>`));
  }
  /* 体检区 */
  const hz = el(`<div class="card"><h3>🩺 资产体检</h3><div class="hbody" style="font-size:13px;color:var(--text2)"></div><div class="btnrow"></div></div>`);
  const hbody = hz.querySelector(".hbody"), hrow = hz.querySelector(".btnrow");
  if(!meta.pages){
    hbody.textContent = "这个 agent 没有记录学习时点（旧版搭建），无法自动体检。可重新搭建或在对话中说「体检资产」。";
  } else if(EDIT){
    hbody.textContent = "检查看板在学习之后是否被修改过，改过则需要重新学习。";
    const btn = el('<button class="btn primary">开始体检</button>');
    const out = el('<div style="margin-top:10px"></div>');
    btn.onclick = async () => {
      btn.disabled = true; btn.textContent = "体检中…";
      try{
        const r = await fetch("/check", {method:"POST"}); const j = await r.json();
        out.innerHTML = j.pages.map(p =>
          `<div class="frow"><div class="k" style="flex-basis:auto">📈</div><div class="v">${esc(p.title)}
            ${p.error ? '<span class="chip c-err">看板不存在或无权访问</span>'
              : p.stale ? `<span class="chip c-warn">已更新 ${esc(p.current)}</span>（学习时 ${esc(p.learned)||"未知"}）→ 建议重新学习`
              : '<span class="chip c-ok">未变化</span>'}</div></div>`).join("");
        const staleN = j.pages.filter(p=>p.stale||p.error).length;
        toast(staleN ? `体检完成：${staleN} 张看板有变化，建议重新学习` : "体检完成：全部看板未变化 ✓", !staleN);
      }catch(e){ toast("体检失败：" + e.message, false); }
      btn.disabled = false; btn.textContent = "重新体检";
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
  wrap.append(el(`<div class="stats">
    <div class="stat"><div class="n">${pages.length}</div><div class="l">看板</div></div>
    <div class="stat"><div class="n">${nCards}</div><div class="l">数据卡片</div></div>
    <div class="stat"><div class="n" style="color:${nDisabled?"var(--err)":"var(--deep)"}">${nDisabled}</div><div class="l">已标记禁用</div></div>
  </div>`));
  pages.forEach(([name, info], idx) => {
    let rows = "";
    for(const [cn, c] of Object.entries(info.cards || {})){
      let chips = "";
      if(c["全景"]) chips += '<span class="chip c-ok">全景</span> ';
      if(c["下钻"]) chips += '<span class="chip c-warn">下钻/局部</span> ';
      if(c["禁用"]) chips += '<span class="chip c-err">禁用</span>';
      rows += `<tr><td>${esc(cn)}</td><td><span class="chip c-soft">${esc(c.type||"")}</span></td>
        <td>${chips}</td><td style="color:var(--text2)">${esc(c.notes||"")}</td></tr>`;
    }
    const u = biUrl(info.pgId);
    const link = u ? `<a href="${esc(u)}" target="_blank" rel="noopener" class="chip c-cyan" style="margin-left:auto">在 BI 中打开 ↗</a>` : "";
    const d = el(`<details class="card"${idx===0?" open":""}>
      <summary><span class="arrow" aria-hidden="true">▶</span>📈 ${esc(name)}
      <span class="sub">${Object.keys(info.cards||{}).length} 张卡片</span>${link}</summary>
      <div class="body"><table><tr><th>卡片</th><th style="width:180px">类型</th><th style="width:150px">状态</th><th>备注</th></tr>${rows}</table></div>
    </details>`);
    wrap.append(d);
  });
  if(DATA.files["learningResult.md"]){
    wrap.append(el('<div class="hint">📖 以下为 AI 对每张看板的理解（资产目录），逐块核对，点"编辑"可直接修改</div>'));
    wrap.append(learningEditor());
  }
  return wrap;
}
function learningEditor(){
  return sectionEditor("learningResult.md", (chunk, startEdit) => {
    const frag = document.createElement("div"); frag.className = "card";
    const title = secTitle(chunk);
    const head = el(`<h3>🗂 ${esc(title)}</h3>`);
    head.append(editBtn(startEdit));
    frag.append(head);
    const ICONS = {"核心价值":"🎯","全部筛选器":"🎛","关键筛选器":"🎛","核心数据模块":"🧩","使用场景":"💡","数据注意":"⚠️"};
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
      const icon = Object.keys(ICONS).find(x=>r.k.includes(x));
      const v = r.lines.join("\n").trim();
      html += `<div class="frow"><div class="k">${icon?ICONS[icon]:"▫️"} ${esc(r.k)}</div>
        <div class="v">${v ? mdLite(v) : ""}</div></div>`;
    }
    const bd = document.createElement("div"); bd.innerHTML = html; frag.append(bd);
    return frag;
  });
}

/* ---------- 业务口径 ---------- */
function rulesPanel(){
  const wrap = document.createElement("div");
  const text = DATA.files["businessKnowledge.md"];
  if(!text) { wrap.append(emptyState("还没有业务口径", "完成第 4 步口径确认后，这里会列出逐条规则。")); return wrap; }
  wrap.append(el(`<div class="hint">📏 共 <b class="ruleCount"></b> 条已确认口径。这些规则决定助手的计算方式，点卡片右上角可编辑或删除</div>`));
  const parts = text.split(/(?=^\d+\.\s)/m);
  const pre = parts[0];
  const rules = parts.slice(1).map(r => r.replace(/^\d+\.\s*/, ""));
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
      const m = rule.match(/^\*\*([^*]+)\*\*\s*[=：:]\s*([\s\S]*)$/);
      const title = m ? m[1].trim() : "";
      const bodyT = m ? m[2].trim() : rule.trim();
      const card = el(`<div class="rule">
        <div class="head"><div class="num">${i+1}</div><div class="rtitle">${title?esc(title):"规则"}</div></div>
        <div class="rbody">${mdLite(bodyT)}</div>
        <div class="acts"></div></div>`);
      if(EDIT){
        const acts = card.querySelector(".acts");
        const eb = el('<button class="btn mini">✏️ 编辑</button>');
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
      if(i === savedIdx) savedBadge(card.querySelector(".acts") || card.querySelector(".head"));
      list.append(card);
    });
    if(EDIT){
      const add = el('<button class="addrule">＋ 加一条规则</button>');
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
const SEC_ICONS = [
  [/角色|约束/, "🎭"], [/诊断链|铁律/, "⛓️"], [/状态标记|标记规则/, "🚦"],
  [/场景一|问数/, "💬"], [/场景二|归因/, "🔍"], [/场景三|异常/, "⚡"], [/场景四|综合|报告/, "📑"],
];
function thinkingPanel(){
  if(!DATA.files["insightThinking.md"])
    return emptyState("还没有分析思路", "完成第 6 步分析框架生成后，这里会展示助手的思考方式。");
  const wrap = document.createElement("div");
  wrap.append(el('<div class="hint">🧠 助手的思考方式：角色约束、诊断链、状态阈值与四类场景流程，逐块核对</div>'));
  wrap.append(sectionEditor("insightThinking.md", (chunk, startEdit) => {
    const title = secTitle(chunk);
    const icon = (SEC_ICONS.find(([re]) => re.test(title)) || [,"📌"])[1];
    const card = el(`<div class="card"><h3>${icon} ${esc(title)}</h3></div>`);
    card.querySelector("h3").append(editBtn(startEdit));
    const body = chunk.replace(/^#{1,3}[^\n]*\n?/, "");
    if(/状态标记/.test(title)){
      const items = [...body.matchAll(/^-\s*([🔴🟡🟢📈📉]+)\s*=\s*(.+)$/gm)];
      if(items.length){
        const lg = el('<div class="legend"></div>');
        items.forEach(([,e,d]) => lg.append(el(`<span class="chip c-soft" style="font-size:12.5px">${e} ${esc(d)}</span>`)));
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
      const card = el(`<div class="card"><h3>🗂 ${esc(f)}</h3><pre class="json">${esc(pretty)}</pre></div>`);
      if(EDIT){
        card.querySelector("h3").append(editBtn(() => {
          card.innerHTML = `<h3>🗂 ${esc(f)}</h3>`;
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
        const card = el(`<div class="card"><h3>📄 ${esc(f)} · ${esc(secTitle(chunk))}</h3></div>`);
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
  ["overview", "🏠", "概览", overviewPanel],
  ["assets", "📦", "数据资产", assetsPanel],
  ["rules", "📏", "业务口径", rulesPanel],
  ["thinking", "🧠", "分析思路", thinkingPanel],
  ["raw", "🗂", "输出模板与脚本", rawPanel],
];
let curTab = (location.hash || "").slice(1);
if(!TABS.some(([id]) => id === curTab)) curTab = "overview";
function renderMain(){
  const panels = $("#panels"); panels.innerHTML = "";
  TABS.forEach(([id,,,build]) => {
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
  if(bk){ const n = (bk.match(/^\d+\.\s/gm) || []).length; if(n) bits.push(n + " 条口径"); }
  bits.push("更新于 " + DATA.generated);
  return bits.join(" · ");
}
(function init(){
  $("#agentName").textContent = agentDisplayName();
  $("#meta").textContent = summaryLine();
  document.title = agentDisplayName() + " · Data Agent 工作台";
  const mb = $("#modeBadge");
  mb.textContent = EDIT ? "编辑模式 · 保存即写回并备份" : "只读模式";
  if(EDIT) mb.classList.add("edit");
  const nav = $("#nav");
  TABS.forEach(([id, ico, label]) => {
    const b = el(`<button><span class="ico" aria-hidden="true">${ico}</span>${label}</button>`);
    b.onclick = () => {
      curTab = id;
      history.replaceState(null, "", "#"+id);
      nav.querySelectorAll("button").forEach(x=>x.classList.toggle("on", x===b));
      document.querySelectorAll(".panel").forEach(p=>p.classList.toggle("on", p.id==="p-"+id));
      $("#pageTitle").textContent = label;
    };
    if(id===curTab){ b.classList.add("on"); $("#pageTitle").textContent = label; }
    nav.append(b);
  });
  if(EDIT){
    const done = $("#doneBtn"); done.classList.remove("hidden");
    done.onclick = async () => {
      if(dirty && !confirm("有未保存修改，确定关闭？")) return;
      await fetch("/shutdown", {method:"POST"});
      document.body.innerHTML = '<div style="max-width:480px;margin:120px auto;text-align:center">'
        + '<div style="font-size:40px">✅</div><h2 style="margin:12px 0 6px">工作台已关闭</h2>'
        + '<p style="color:var(--text2);font-size:13px">可以回到对话继续了</p></div>';
    };
  }
  renderMain();
})();
</script></body></html>"""

FLEET_PAGE = r"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#f6f8f5">
<title>我的 Data Agents</title>
<style>__CSS__
.agent-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:14px}
.agent-card{background:var(--card);border:1px solid var(--border);border-radius:14px;box-shadow:var(--shadow);
  padding:16px 18px;display:flex;flex-direction:column;gap:10px}
.agent-card .hd{display:flex;gap:12px;align-items:center}
.agent-card .nm{font-size:15px;font-weight:650}
.agent-card .ds{font-size:12.5px;color:var(--text2);display:-webkit-box;-webkit-line-clamp:2;
  -webkit-box-orient:vertical;overflow:hidden;min-height:2.4em}
.agent-card .ft{display:flex;gap:8px;align-items:center;flex-wrap:wrap;font-size:12px;color:var(--text3)}
.agent-card .acts{display:flex;gap:8px;margin-top:auto}
.agent-card .btn{flex:1;text-align:center}
.stalebar{font-size:12.5px;border-radius:8px;padding:6px 10px}
</style></head><body>
<div id="toast" aria-live="polite"></div>
<div class="shell" style="max-width:1160px">
  <div class="main" style="width:100%">
    <div class="topbar">
      <div class="logo avatar" style="width:34px;height:34px;font-size:17px;background:linear-gradient(135deg,#59ac65,#1f7237)" aria-hidden="true">🤖</div>
      <div><h1>我的 Data Agents</h1><div class="meta" id="meta"></div></div>
      <span class="mode" id="modeBadge"></span>
    </div>
    <div class="agent-grid" id="grid"></div>
  </div>
</div>
<script>
__CJS__
const DATA = __DATA__;
const EDIT = __EDIT__;
document.getElementById("meta").textContent =
  DATA.dir + " · " + DATA.agents.length + " 个 agent · 生成于 " + DATA.generated;
document.getElementById("modeBadge").textContent = EDIT ? "可体检" : "只读";
if(EDIT) document.getElementById("modeBadge").classList.add("edit");
const grid = document.getElementById("grid");
if(!DATA.agents.length){
  grid.append(el('<div class="card" style="grid-column:1/-1"><div class="empty"><div class="t">还没有搭建任何 data agent</div>在 WorkBuddy 里使用 guanbi-agent-builder 搭建后，会出现在这里。</div></div>'));
}
DATA.agents.forEach(a => {
  const chips = [];
  if(a.pages) chips.push(`<span class="chip c-soft">${a.pages} 看板</span>`);
  if(a.cards) chips.push(`<span class="chip c-soft">${a.cards} 卡片</span>`);
  if(a.rules) chips.push(`<span class="chip c-soft">${a.rules} 口径</span>`);
  if(a.builtAt) chips.push(`<span>学习于 ${esc(a.builtAt)}</span>`);
  const card = el(`<div class="agent-card">
    <div class="hd">${avatarFor(a.name, 44)}<div><div class="nm">${esc(a.name)}</div>
      <div style="font-size:11.5px;color:var(--text3)">${esc(a.dirName)}</div></div></div>
    <div class="ds">${esc(a.description || "（无描述）")}</div>
    <div class="ft">${chips.join("")}</div>
    <div class="stale"></div>
    <div class="acts"></div></div>`);
  const acts = card.querySelector(".acts");
  if(a.workbenchUrl){
    acts.append(el(`<a class="btn" href="${esc(a.workbenchUrl)}" target="_blank" rel="noopener">打开工作台 ↗</a>`));
  }
  if(EDIT && a.hasMeta){
    const cb = el('<button class="btn primary">🩺 体检</button>');
    cb.onclick = async () => {
      cb.disabled = true; cb.textContent = "体检中…";
      const stale = card.querySelector(".stale");
      try{
        const r = await fetch("/check?agent=" + encodeURIComponent(a.dirName), {method:"POST"});
        const j = await r.json();
        const bad = j.pages.filter(p => p.stale || p.error);
        stale.innerHTML = bad.length
          ? `<div class="stalebar" style="background:var(--warn-bg);color:var(--warn)">⚠️ ${bad.length} 张看板在学习后被修改：${bad.map(p=>esc(p.title)).join("、")}，建议对该 agent 重新学习</div>`
          : `<div class="stalebar" style="background:var(--ok-bg);color:var(--ok)">✓ 全部 ${j.pages.length} 张看板未变化（${esc(j.checkedAt)}）</div>`;
      }catch(e){ toast("体检失败：" + e.message, false); }
      cb.disabled = false; cb.textContent = "🩺 重新体检";
    };
    acts.append(cb);
  }
  grid.append(card);
});
if(EDIT){
  const done = el('<button class="btn" style="position:fixed;bottom:20px;right:20px;box-shadow:var(--shadow)">✅ 完成，关闭</button>');
  done.onclick = async () => { await fetch("/shutdown", {method:"POST"});
    document.body.innerHTML = '<div style="max-width:480px;margin:120px auto;text-align:center"><div style="font-size:40px">✅</div><h2 style="margin:12px 0 6px">已关闭</h2></div>'; };
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


def page_mtime(pg_id):
    r = subprocess.run(["guancli", "page", "get", pg_id],
                       capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        return None
    m = re.search(r'^更新时间: (.+)$', r.stdout, re.M)
    return m.group(1).strip() if m else ""


def check_staleness(workdir):
    """对比 cards.json._meta 记录的学习时 mtime 与当前线上 mtime。"""
    cj = os.path.join(workdir, "cards.json")
    with open(cj, encoding="utf-8") as f:
        meta = (json.load(f).get("_meta") or {})
    pages = []
    for pg_id, info in (meta.get("pages") or {}).items():
        cur = page_mtime(pg_id)
        pages.append({
            "pgId": pg_id, "title": info.get("title", pg_id),
            "learned": info.get("mtime", ""), "current": cur,
            "error": cur is None,
            "stale": bool(cur) and cur != info.get("mtime", ""),
        })
    return {"pages": pages, "checkedAt": time.strftime("%Y-%m-%d %H:%M")}


def collect_agents(skills_dir):
    out = []
    for name in sorted(os.listdir(skills_dir)):
        ref = os.path.join(skills_dir, name, "references")
        if not name.startswith("agent-") or not os.path.isdir(ref):
            continue
        a = {"dirName": name, "name": name.replace("agent-", ""), "description": "",
             "pages": 0, "cards": 0, "rules": 0, "builtAt": "", "hasMeta": False,
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
            for k, v in assets.items():
                if k == "_meta":
                    continue
                if isinstance(v, dict) and isinstance(v.get("cards"), dict):
                    a["pages"] += 1
                    a["cards"] += len(v["cards"])
                elif k == "pages" and isinstance(v, dict):
                    a["pages"] += len(v)  # 旧版 schema：{pages: {名称: pgId}}
        bk = os.path.join(ref, "businessKnowledge.md")
        if os.path.exists(bk):
            with open(bk, encoding="utf-8") as f:
                a["rules"] = len(re.findall(r'^\d+\.\s', f.read(), re.M))
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


def serve_single(workdir):
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

    H = make_handler(lambda: render(PAGE, collect(workdir), True),
                     on_check=lambda _a: check_staleness(workdir),
                     on_save=save_file)
    server = HTTPServer(("127.0.0.1", 0), H)
    print(f"WORKBENCH_URL=http://127.0.0.1:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


def serve_fleet(skills_dir):
    def check(agent_name):
        ref = os.path.join(skills_dir, agent_name or "", "references")
        if not agent_name or not os.path.isdir(ref):
            return {"pages": [], "checkedAt": time.strftime("%Y-%m-%d %H:%M")}
        return check_staleness(ref)
    H = make_handler(lambda: render(FLEET_PAGE, {
        "dir": os.path.abspath(skills_dir), "generated": time.strftime("%Y-%m-%d %H:%M"),
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
    args = [a for a in argv if not a.startswith("--")]

    if agents_mode:
        skills_dir = os.path.expanduser(args[0] if args else "~/.workbuddy/skills")
        if not os.path.isdir(skills_dir):
            sys.exit(f"目录不存在: {skills_dir}")
        if serve_mode:
            serve_fleet(skills_dir)
        else:
            out = os.path.join(skills_dir, "agents.html")
            with open(out, "w", encoding="utf-8") as f:
                f.write(render(FLEET_PAGE, {
                    "dir": os.path.abspath(skills_dir),
                    "generated": time.strftime("%Y-%m-%d %H:%M"),
                    "agents": collect_agents(skills_dir)}, False))
            print(f"已生成: {out}")
        return

    if not args:
        sys.exit(__doc__)
    workdir = args[0]
    if not os.path.isdir(workdir):
        sys.exit(f"目录不存在: {workdir}")
    if check_mode:
        r = check_staleness(workdir)
        print(f"资产体检（{r['checkedAt']}）")
        for p in r["pages"]:
            if p["error"]:
                print(f"  ❌ {p['title']}：看板不存在或无权访问")
            elif p["stale"]:
                print(f"  ⚠️  {p['title']}：学习时 {p['learned'] or '未知'} → 当前 {p['current']}，建议重新学习")
            else:
                print(f"  ✓  {p['title']}：未变化")
        return
    if serve_mode:
        serve_single(workdir)
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
