#!/usr/bin/env python3
"""
轻量工作台：把搭建/交付产物变成可校验、可编辑的本地页面（WorkBuddy 原生风格）
用法:
  python3 workbench.py <目录>             # 生成只读 <目录>/workbench.html（双击浏览器打开）
  python3 workbench.py <目录> --serve     # 启动本地编辑服务，打印 WORKBENCH_URL=http://127.0.0.1:<port>
编辑模式：页面内分块编辑 → 保存写回源文件（自动备份 .bak-<时间戳>）→ 侧栏"完成"自动关服务
识别文件: cards.json（资产表格）、learningResult.md（看板卡片化）、
          businessKnowledge.md（逐条规则卡片）、insightThinking.md（章节结构化）、
          及其余 .md/.json（其他文件区）
"""
import json, os, sys, time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

PAGE = r"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Data Agent 工作台</title>
<style>
:root{
  --bg:#f6f8f5; --card:#ffffff; --border:#dce7dd; --soft:#e8f0e9;
  --pri:#3c8c4e; --deep:#1f7237; --text:#12261ae6; --text2:#12261ab3; --text3:#12261a80;
  --ok-bg:#d1fae5; --ok:#047857; --warn-bg:#fef3c7; --warn:#b45309; --err-bg:#fee2e2; --err:#dc2626;
  --orange:#f5a623; --cyan:#06b6d4;
  --shadow:0 12px 24px -8px rgba(0,0,0,.05),0 2px 4px -4px rgba(0,0,0,.05);
}
*{box-sizing:border-box;margin:0}
body{background:var(--bg);color:var(--text);
  font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Helvetica Neue","Microsoft YaHei",sans-serif;
  font-size:14px;line-height:1.6;-webkit-font-smoothing:antialiased}
.shell{max-width:1080px;margin:0 auto;padding:24px 20px 64px;display:flex;gap:20px;align-items:flex-start}

/* 侧栏 */
.side{flex:0 0 188px;position:sticky;top:24px}
.brand{display:flex;align-items:center;gap:10px;padding:6px 8px 18px}
.brand .logo{width:34px;height:34px;border-radius:10px;background:linear-gradient(135deg,#59ac65,#1f7237);
  display:flex;align-items:center;justify-content:center;font-size:17px}
.brand .t1{font-weight:600;font-size:14px}.brand .t2{font-size:11px;color:var(--text3)}
.nav{display:flex;flex-direction:column;gap:4px}
.nav button{display:flex;align-items:center;gap:9px;padding:9px 12px;border:none;border-radius:10px;
  background:transparent;color:var(--text2);font-size:13.5px;cursor:pointer;text-align:left;transition:.15s}
.nav button:hover{background:#ffffff90}
.nav button.on{background:var(--card);color:var(--deep);font-weight:600;box-shadow:var(--shadow)}
.nav button.on .ico{background:var(--pri);color:#fff}
.nav .ico{width:22px;height:22px;border-radius:7px;background:var(--soft);display:flex;
  align-items:center;justify-content:center;font-size:12px;flex:none}
.side .done{margin-top:18px;width:100%;padding:10px;border:none;border-radius:10px;background:var(--pri);
  color:#fff;font-size:13.5px;cursor:pointer;box-shadow:var(--shadow)}
.side .done:hover{background:var(--deep)}

/* 主区 */
.main{flex:1;min-width:0}
.topbar{background:var(--card);border:1px solid var(--border);border-radius:14px;box-shadow:var(--shadow);
  padding:16px 20px;margin-bottom:16px;display:flex;align-items:center;gap:14px;flex-wrap:wrap}
.topbar h1{font-size:17px;font-weight:600}
.topbar .meta{font-size:12px;color:var(--text3);margin-top:2px}
.mode{margin-left:auto;font-size:12px;padding:3px 10px;border-radius:999px;background:var(--soft);color:var(--deep)}
.mode.edit{background:var(--warn-bg);color:var(--warn)}
.panel{display:none}.panel.on{display:block}
.hint{background:var(--card);border:1px dashed var(--border);border-radius:12px;padding:10px 14px;
  font-size:12.5px;color:var(--text2);margin-bottom:14px}
.stats{display:flex;gap:10px;margin-bottom:14px;flex-wrap:wrap}
.stat{flex:1;min-width:120px;background:var(--card);border:1px solid var(--border);border-radius:12px;
  padding:12px 16px;box-shadow:var(--shadow)}
.stat .n{font-size:22px;font-weight:700;color:var(--deep)}
.stat .l{font-size:12px;color:var(--text3)}

/* 卡片 */
.card{background:var(--card);border:1px solid var(--border);border-radius:12px;
  box-shadow:var(--shadow);padding:16px 18px;margin-bottom:14px}
.card > h3{font-size:14.5px;font-weight:600;display:flex;align-items:center;gap:8px;margin-bottom:10px;flex-wrap:wrap}
.card > h3 .sub{font-size:12px;color:var(--text3);font-weight:400}
.chip{display:inline-flex;align-items:center;padding:1px 9px;border-radius:999px;font-size:11.5px;font-weight:500}
.c-ok{background:var(--ok-bg);color:var(--ok)}
.c-warn{background:var(--warn-bg);color:var(--warn)}
.c-err{background:var(--err-bg);color:var(--err)}
.c-soft{background:var(--soft);color:var(--deep)}
.c-cyan{background:#06b6d414;color:#0e7490}
.c-orange{background:#f5a62314;color:#b45309}

/* 字段行（看板资产目录） */
.frow{display:flex;gap:10px;padding:7px 0;border-top:1px solid #12261a0a;font-size:13px}
.frow:first-of-type{border-top:none}
.frow .k{flex:0 0 96px;color:var(--text3);font-size:12.5px;padding-top:1px}
.frow .v{flex:1;min-width:0}
.frow .v .mod{display:inline-block;background:var(--soft);border-radius:7px;padding:1px 8px;margin:2px 4px 2px 0;font-size:12.5px}

/* 表格 */
table{width:100%;border-collapse:collapse;font-size:12.5px}
th{background:var(--soft);color:var(--deep);font-weight:600;text-align:left;padding:7px 10px}
td{padding:7px 10px;border-top:1px solid #12261a0a;color:var(--text)}
tr:hover td{background:#f6f8f580}

/* 规则卡 */
.rule{background:var(--card);border:1px solid var(--border);border-radius:12px;box-shadow:var(--shadow);
  padding:14px 16px;margin-bottom:10px;position:relative}
.rule .head{display:flex;align-items:center;gap:10px}
.num{flex:none;width:24px;height:24px;border-radius:8px;background:var(--soft);color:var(--deep);
  font-size:12.5px;font-weight:700;display:flex;align-items:center;justify-content:center}
.rtitle{font-weight:600;font-size:13.5px}
.rbody{margin-top:6px;padding-left:34px;color:var(--text2);font-size:13px;line-height:1.75;white-space:pre-wrap}
.rule .acts{position:absolute;top:12px;right:12px;display:flex;gap:6px;opacity:0;transition:.15s}
.rule:hover .acts{opacity:1}
.addrule{width:100%;padding:13px;border:1.5px dashed var(--border);border-radius:12px;background:transparent;
  color:var(--text3);font-size:13px;cursor:pointer;transition:.15s}
.addrule:hover{border-color:var(--pri);color:var(--deep);background:#ffffff80}

/* 分析思路步骤 */
.step{display:flex;gap:10px;padding:5px 0;font-size:13px;color:var(--text)}
.step .sn{flex:none;width:20px;height:20px;border-radius:6px;background:#06b6d414;color:#0e7490;
  font-size:11.5px;font-weight:600;display:flex;align-items:center;justify-content:center;margin-top:1px}
.bullet{display:flex;gap:8px;padding:3px 0;font-size:13px;color:var(--text)}
.bullet::before{content:"";flex:none;width:5px;height:5px;border-radius:50%;background:var(--pri);margin-top:9px}
.quote{border-left:3px solid var(--pri);background:var(--soft);border-radius:0 8px 8px 0;
  padding:8px 12px;margin:8px 0;font-size:12.5px;color:var(--text2)}
.legend{display:flex;gap:8px;flex-wrap:wrap;margin:8px 0}

/* 编辑 */
textarea{width:100%;min-height:110px;font:13px/1.7 ui-monospace,Menlo,Consolas,monospace;
  padding:10px 12px;border:1px solid var(--border);border-radius:10px;resize:vertical;background:#fbfdfb;
  color:var(--text);outline:none}
textarea:focus{border-color:var(--pri);box-shadow:0 0 0 3px #3c8c4e22}
.btn{padding:5px 14px;border-radius:8px;border:1px solid var(--border);background:var(--card);
  cursor:pointer;font-size:12.5px;color:var(--text);transition:.15s}
.btn:hover{border-color:var(--pri);color:var(--deep)}
.btn.primary{background:var(--pri);border-color:var(--pri);color:#fff}
.btn.primary:hover{background:var(--deep);color:#fff}
.btn.danger:hover{border-color:var(--err);color:var(--err)}
.btn.mini{padding:2px 10px;font-size:12px}
.btnrow{margin-top:10px;display:flex;gap:8px}
code.ic{background:var(--soft);border-radius:5px;padding:0 5px;font:12px ui-monospace,Menlo,monospace;color:var(--deep)}
pre.json{background:#12261a;color:#d7f0dd;border-radius:10px;padding:14px;font:12px/1.6 ui-monospace,Menlo,monospace;
  overflow:auto;max-height:420px}
.empty{padding:32px;text-align:center;color:var(--text3);font-size:13px}

#toast{position:fixed;top:18px;right:20px;padding:9px 16px;border-radius:10px;font-size:13px;z-index:9;
  display:none;box-shadow:var(--shadow)}
#toast.ok{background:var(--ok-bg);color:var(--ok)}
#toast.err{background:var(--err-bg);color:var(--err)}
.hidden{display:none!important}
</style></head><body>
<div id="toast"></div>
<div class="shell">
  <aside class="side">
    <div class="brand"><div class="logo">📊</div>
      <div><div class="t1">Data Agent 工作台</div><div class="t2" id="agentName"></div></div>
    </div>
    <nav class="nav" id="nav"></nav>
    <button class="done hidden" id="doneBtn">✅ 完成，关闭工作台</button>
  </aside>
  <div class="main">
    <div class="topbar">
      <div><h1 id="pageTitle">数据资产</h1><div class="meta" id="meta"></div></div>
      <span class="mode" id="modeBadge"></span>
    </div>
    <div id="panels"></div>
  </div>
</div>
<script>
const DATA = __DATA__;
const EDIT = __EDIT__;
const $ = s => document.querySelector(s);
const esc = s => String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
let dirty = false;
window.onbeforeunload = () => dirty ? "有未保存的修改" : null;

/* ---------- 基础设施 ---------- */
function toast(msg, ok=true){
  const t = $("#toast"); t.textContent = msg; t.className = ok ? "ok" : "err";
  t.style.display = "block"; setTimeout(()=> t.style.display = "none", 3000);
}
async function save(file, content){
  try{
    const r = await fetch("/save", {method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({file, content})});
    const j = await r.json();
    if(j.ok){ dirty=false; DATA.files[file]=content; toast("已保存 ✓ 备份 "+j.backup); }
    else toast("保存失败："+(j.error||""), false);
    return j.ok;
  }catch(e){ toast("保存失败："+e.message, false); return false; }
}
function splitSections(text){ return text.split(/(?=^#{1,3}\s)/m).filter(c=>c.length); }
function el(html){ const d=document.createElement("div"); d.innerHTML=html.trim(); return d.firstChild; }

/* markdown-lite 渲染：粗体/行内代码/引用/有序步骤/无序列表 */
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

/* 通用分节编辑器：展示=结构化渲染，编辑=本节原文 textarea，保存=整文件重建 */
function sectionEditor(file, renderChunk){
  const chunks = splitSections(DATA.files[file] || "");
  const wrap = document.createElement("div");
  chunks.forEach((chunk, i) => {
    const card = document.createElement("div");
    const paint = () => { card.innerHTML = ""; card.append(renderChunk(chunk, () => startEdit())); };
    const startEdit = () => {
      card.innerHTML = "";
      const ta = document.createElement("textarea"); ta.value = chunk;
      ta.rows = Math.min(22, chunk.split("\n").length + 2);
      const row = document.createElement("div"); row.className = "btnrow";
      const ok = el('<button class="btn primary">保存</button>');
      const no = el('<button class="btn">取消</button>');
      ok.onclick = async () => { chunks[i] = ta.value; dirty = true;
        if(await save(file, chunks.join(""))) paint(); };
      no.onclick = paint;
      row.append(ok, no); card.append(ta, row);
    };
    paint(); wrap.append(card);
  });
  return wrap;
}
function editBtn(onClick){
  if(!EDIT) return document.createTextNode("");
  const b = el('<button class="btn mini">✏️ 编辑</button>');
  b.onclick = onClick; return b;
}
function secTitle(chunk){
  const m = chunk.match(/^(#{1,3})\s*(.+)/);
  return m ? m[2].replace(/[*#]/g,"").trim().slice(0,40) : "说明";
}

/* ---------- 数据资产 ---------- */
function assetsPanel(){
  const wrap = document.createElement("div");
  const a = DATA.assets;
  if(!a){ wrap.append(el('<div class="card"><div class="empty">未找到 cards.json</div></div>')); return wrap; }
  const pages = Object.entries(a);
  let nCards = 0, nDisabled = 0;
  pages.forEach(([,info]) => Object.values(info.cards||{}).forEach(c => { nCards++; if(c["禁用"]) nDisabled++; }));
  wrap.append(el(`<div class="stats">
    <div class="stat"><div class="n">${pages.length}</div><div class="l">看板</div></div>
    <div class="stat"><div class="n">${nCards}</div><div class="l">数据卡片</div></div>
    <div class="stat"><div class="n" style="color:${nDisabled?"var(--err)":"var(--deep)"}">${nDisabled}</div><div class="l">已标记禁用</div></div>
  </div>`));
  pages.forEach(([name, info]) => {
    let rows = "";
    for(const [cn, c] of Object.entries(info.cards || {})){
      let chips = "";
      if(c["全景"]) chips += '<span class="chip c-ok">全景</span> ';
      if(c["下钻"]) chips += '<span class="chip c-warn">下钻/局部</span> ';
      if(c["禁用"]) chips += '<span class="chip c-err">禁用</span>';
      rows += `<tr><td>${esc(cn)}</td><td><span class="chip c-soft">${esc(c.type||"")}</span></td>
        <td>${chips}</td><td style="color:var(--text2)">${esc(c.notes||"")}</td></tr>`;
    }
    wrap.append(el(`<div class="card"><h3>📈 ${esc(name)}
      <span class="sub">${Object.keys(info.cards||{}).length} 张卡片 · ${esc(info.pgId||"")}</span></h3>
      <table><tr><th>卡片</th><th style="width:180px">类型</th><th style="width:150px">状态</th><th>备注</th></tr>${rows}</table></div>`));
  });
  if(DATA.files["learningResult.md"]){
    wrap.append(el('<div class="hint">📖 以下为 AI 对每张看板的理解（资产目录），逐块核对，点"编辑"可直接修改</div>'));
    wrap.append(learningEditor());
  }
  return wrap;
}
/* learningResult：按 ## 看板 切块，**字段：** 解析成标签行 */
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
    let html = "", pending = [];
    const flush = () => {
      if(!pending.length) return;
      html += `<div style="padding:2px 0 6px">${mdLite(pending.join("\n"))}</div>`; pending = [];
    };
    for(const ln of body.split("\n")){
      const m = ln.match(fieldRe);
      if(m){
        flush();
        const k = m[1].trim(), v = m[2].trim();
        const icon = Object.keys(ICONS).find(x=>k.includes(x));
        html += `<div class="frow"><div class="k">${icon?ICONS[icon]:"▫️"} ${esc(k)}</div>
          <div class="v">${mdLite(v||"（见下）")}</div></div>`;
      } else pending.push(ln);
    }
    flush();
    const bd = document.createElement("div"); bd.innerHTML = html; frag.append(bd);
    return frag;
  });
}

/* ---------- 业务口径 ---------- */
function rulesPanel(){
  const wrap = document.createElement("div");
  const text = DATA.files["businessKnowledge.md"];
  if(!text){ wrap.append(el('<div class="card"><div class="empty">未找到 businessKnowledge.md</div></div>')); return wrap; }
  wrap.append(el(`<div class="hint">📏 共 <b class="ruleCount"></b> 条已确认口径。这些规则决定助手的计算方式，点击卡片右上角可编辑或删除</div>`));
  const parts = text.split(/(?=^\d+\.\s)/m);
  const pre = parts[0];
  const rules = parts.slice(1).map(r => r.replace(/^\d+\.\s*/, ""));
  const list = document.createElement("div"); wrap.append(list);
  async function commit(){
    const body = rules.map((r,i)=> (i+1)+". "+r.replace(/\n+$/,"")).join("\n") + "\n";
    return save("businessKnowledge.md", pre + body);
  }
  function draw(){
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
          ta.rows = Math.min(14, rule.split("\n").length + 2);
          const row = document.createElement("div"); row.className = "btnrow";
          const ok = el('<button class="btn primary">保存这条</button>');
          const no = el('<button class="btn">取消</button>');
          ok.onclick = async () => { rules[i] = ta.value; dirty = true; if(await commit()) draw(); };
          no.onclick = draw;
          row.append(ok, no); card.append(ta, row);
        };
        db.onclick = async () => {
          if(!confirm(`删除第 ${i+1} 条规则？`)) return;
          rules.splice(i,1); dirty = true; if(await commit()) draw();
        };
        acts.append(eb, db);
      }
      list.append(card);
    });
    if(EDIT){
      const add = el('<button class="addrule">＋ 加一条规则</button>');
      add.onclick = () => {
        const v = prompt('新规则（格式：**名称** = 内容，如 **达成率** = 实际 ÷ 预算）：');
        if(v){ rules.push(v.replace(/^\d+\.\s*/,"") + "\n"); dirty = true; commit().then(ok => ok && draw()); }
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
    return el('<div class="card"><div class="empty">未找到 insightThinking.md</div></div>');
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

/* ---------- 其他文件 ---------- */
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
          const row = document.createElement("div"); row.className = "btnrow";
          const ok = el('<button class="btn primary">保存</button>');
          const no = el('<button class="btn">取消</button>');
          ok.onclick = async () => {
            try{ JSON.parse(ta.value); }catch(e){ toast("JSON 格式错误："+e.message, false); return; }
            dirty = true; if(await save(f, ta.value)) renderMain();
          };
          no.onclick = renderMain;
          row.append(ok, no); card.append(ta, row);
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
  if(!any) wrap.append(el('<div class="card"><div class="empty">无其他文件</div></div>'));
  return wrap;
}

/* ---------- 框架 ---------- */
const TABS = [
  ["assets", "📦", "数据资产", assetsPanel],
  ["rules", "📏", "业务口径", rulesPanel],
  ["thinking", "🧠", "分析思路", thinkingPanel],
  ["raw", "🗂", "其他文件", rawPanel],
];
let curTab = (location.hash || "").slice(1);
if(!TABS.some(([id]) => id === curTab)) curTab = "assets";
function renderMain(){
  const panels = $("#panels"); panels.innerHTML = "";
  TABS.forEach(([id,,,build]) => {
    const p = document.createElement("div"); p.className = "panel" + (id===curTab?" on":"");
    p.id = "p-"+id; p.append(build()); panels.append(p);
  });
}
(function init(){
  $("#agentName").textContent = DATA.dir.split("/").filter(Boolean).pop() || "";
  $("#meta").textContent = DATA.dir + " · 生成于 " + DATA.generated;
  const mb = $("#modeBadge");
  mb.textContent = EDIT ? "编辑模式 · 保存即写回并备份" : "只读模式";
  if(EDIT) mb.classList.add("edit");
  const nav = $("#nav");
  TABS.forEach(([id, ico, label]) => {
    const b = el(`<button><span class="ico">${ico}</span>${label}</button>`);
    b.dataset.tab = id;
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
        + '<p style="color:#12261ab3;font-size:13px">可以回到对话继续了</p></div>';
    };
  }
  renderMain();
})();
</script></body></html>"""


def collect(workdir):
    data = {"dir": os.path.abspath(workdir), "generated": time.strftime("%Y-%m-%d %H:%M"),
            "assets": None, "files": {}}
    cj = os.path.join(workdir, "cards.json")
    if os.path.exists(cj):
        with open(cj, encoding="utf-8") as f:
            data["assets"] = json.load(f)
    for fn in sorted(os.listdir(workdir)):
        if fn.endswith((".md", ".json")) and not fn.startswith("_") and fn != "cards.json":
            with open(os.path.join(workdir, fn), encoding="utf-8") as f:
                data["files"][fn] = f.read()
    return data


def render_page(data, edit):
    payload = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")
    return (PAGE.replace("__DATA__", payload)
                .replace("__EDIT__", "true" if edit else "false"))


def serve(workdir):
    allowed = {fn for fn in os.listdir(workdir) if fn.endswith((".md", ".json"))}

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
                self._send(200, render_page(collect(workdir), True))
            else:
                self._send(404, "not found", "text/plain")

        def do_POST(self):
            path = urlparse(self.path).path
            if path == "/shutdown":
                self._send(200, "{}", "application/json")
                import threading
                threading.Timer(0.3, server.shutdown).start()
                return
            if path != "/save":
                self._send(404, "{}", "application/json")
                return
            try:
                n = int(self.headers.get("Content-Length", 0))
                req = json.loads(self.rfile.read(n) or b"{}")
                fn, content = req.get("file", ""), req.get("content", "")
                if fn not in allowed or "/" in fn:
                    raise ValueError("不允许的文件: " + fn)
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
                self._send(200, json.dumps({"ok": True, "backup": backup}), "application/json")
            except Exception as e:
                self._send(200, json.dumps({"ok": False, "error": str(e)[:200]}), "application/json")

    server = HTTPServer(("127.0.0.1", 0), H)
    print(f"WORKBENCH_URL=http://127.0.0.1:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        sys.exit(__doc__)
    workdir = args[0]
    if not os.path.isdir(workdir):
        sys.exit(f"目录不存在: {workdir}")
    if "--serve" in sys.argv:
        serve(workdir)
    else:
        out = os.path.join(workdir, "workbench.html")
        with open(out, "w", encoding="utf-8") as f:
            f.write(render_page(collect(workdir), False))
        print(f"已生成: {out}")


if __name__ == "__main__":
    main()
