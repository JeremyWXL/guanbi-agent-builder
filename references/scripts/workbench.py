#!/usr/bin/env python3
"""
轻量工作台：把搭建/交付产物变成可校验、可编辑的本地页面
用法:
  python3 workbench.py <目录>             # 生成只读 <目录>/workbench.html（双击浏览器打开）
  python3 workbench.py <目录> --serve     # 启动本地编辑服务，打印 WORKBENCH_URL=http://127.0.0.1:<port>
编辑模式：页面内分节编辑 → 保存写回源文件（自动备份 .bak-<时间戳>）→ 页面点"完成"自动关服务
识别文件: cards.json（资产表格）、learningResult.md、businessKnowledge.md（逐条规则编辑）、
          insightThinking.md、outputFormat.json，及其余 .md/.json（原始查看）
"""
import json, os, re, sys, time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

PAGE = r"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Data Agent 工作台</title>
<style>
*{box-sizing:border-box;margin:0}
body{font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;background:#f5f6f8;color:#24292f;padding:24px;max-width:960px;margin:0 auto}
h1{font-size:20px}h2{font-size:16px}
.meta{color:#666;font-size:12px;margin:6px 0 16px}
.tabs{display:flex;gap:8px;margin-bottom:16px;flex-wrap:wrap}
.tab{padding:6px 14px;border-radius:16px;background:#e8eaed;cursor:pointer;font-size:14px;border:none}
.tab.on{background:#1f6feb;color:#fff}
.panel{display:none}.panel.on{display:block}
.card{background:#fff;border:1px solid #e1e4e8;border-radius:8px;padding:14px 16px;margin-bottom:12px}
.card h3{font-size:14px;margin-bottom:8px;color:#1f6feb}
.body{white-space:pre-wrap;font-size:13px;line-height:1.7;color:#333}
textarea{width:100%;min-height:120px;font:13px/1.6 ui-monospace,Menlo,monospace;padding:8px;border:1px solid #d0d7de;border-radius:6px;resize:vertical}
.btn{padding:4px 12px;border-radius:6px;border:1px solid #d0d7de;background:#f6f8fa;cursor:pointer;font-size:13px;margin-right:6px}
.btn.primary{background:#1f6feb;border-color:#1f6feb;color:#fff}
.btn.danger{color:#cf222e}
.btnrow{margin-top:8px}
table{width:100%;border-collapse:collapse;font-size:13px}
td,th{border:1px solid #e1e4e8;padding:5px 8px;text-align:left}
th{background:#f6f8fa}
.badge{display:inline-block;padding:1px 8px;border-radius:10px;font-size:11px;margin-left:6px}
.b-ok{background:#dafbe1;color:#1a7f37}.b-warn{background:#fff8c5;color:#9a6700}.b-no{background:#ffebe9;color:#cf222e}
.rule{display:flex;gap:8px;align-items:flex-start}
.rule .no{flex:0 0 26px;height:26px;border-radius:50%;background:#ddf4ff;color:#0969da;font-size:12px;display:flex;align-items:center;justify-content:center;margin-top:4px}
.rule .ct{flex:1}
#status{position:fixed;top:12px;right:16px;padding:8px 16px;border-radius:8px;font-size:13px;display:none;z-index:9;background:#dafbe1;color:#1a7f37;box-shadow:0 2px 8px rgba(0,0,0,.12)}
.hidden{display:none}
</style></head><body>
<div id="status"></div>
<h1>📊 Data Agent 工作台</h1>
<div class="meta" id="meta"></div>
<div class="tabs" id="tabs"></div>
<div id="panels"></div>
<script>
const DATA = __DATA__;
const EDIT = __EDIT__;
const $ = s => document.querySelector(s);
const esc = s => s.replace(/&/g,"&amp;").replace(/</g,"&lt;");
let dirty = false;
window.onbeforeunload = () => dirty ? "有未保存的修改" : null;

function toast(msg, ok=true){
  const t = $("#status"); t.textContent = msg; t.style.display = "block";
  t.style.background = ok ? "#dafbe1" : "#ffebe9"; t.style.color = ok ? "#1a7f37" : "#cf222e";
  setTimeout(()=> t.style.display="none", 3000);
}
async function save(file, content){
  const r = await fetch("/save", {method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify({file, content})});
  const j = await r.json();
  if(j.ok){ dirty=false; DATA.files[file]=content; toast("已保存 ✓（备份 "+j.backup+"）"); }
  else toast("保存失败: "+(j.error||""), false);
  return j.ok;
}
function splitSections(text){ // 按 # 标题切块，lookahead 保证 join 无损
  return text.split(/(?=^#{1,3}\s)/m).filter(c=>c.length);
}
function sectionTitle(chunk){
  const m = chunk.match(/^(#{1,3})\s*(.+)/);
  return m ? m[2].trim().slice(0,40) : "（开头）";
}
// ---- 通用 markdown 分节编辑器 ----
function mdEditor(file){
  const chunks = splitSections(DATA.files[file] || "");
  const wrap = document.createElement("div");
  chunks.forEach((chunk, i) => {
    const card = document.createElement("div"); card.className="card";
    const view = `<h3>${esc(sectionTitle(chunk))}</h3><div class="body">${esc(chunk)}</div>`;
    card.innerHTML = view;
    if(EDIT){
      const row = document.createElement("div"); row.className="btnrow";
      const btn = document.createElement("button"); btn.className="btn"; btn.textContent="✏️ 编辑本节";
      btn.onclick = () => {
        card.innerHTML = `<h3>${esc(sectionTitle(chunk))}</h3>`;
        const ta = document.createElement("textarea"); ta.value = chunk; ta.rows = Math.min(20, chunk.split("\n").length+2);
        const r2 = document.createElement("div"); r2.className="btnrow";
        const ok = document.createElement("button"); ok.className="btn primary"; ok.textContent="保存本节";
        const no = document.createElement("button"); no.className="btn"; no.textContent="取消";
        ok.onclick = async () => {
          chunks[i] = ta.value; dirty = true;
          if(await save(file, chunks.join(""))) render();
        };
        no.onclick = render;
        r2.append(ok, no); card.append(ta, r2);
      };
      row.append(btn); card.append(row);
    }
    wrap.append(card);
  });
  return wrap;
}
// ---- 业务口径：逐条规则编辑器 ----
function rulesEditor(file){
  const text = DATA.files[file] || "";
  const parts = text.split(/(?=^\d+\.\s)/m);
  const pre = parts[0];
  const rules = parts.slice(1).map(r => r.replace(/^\d+\.\s*/, ""));
  const wrap = document.createElement("div");
  const head = document.createElement("div"); head.className="card";
  head.innerHTML = `<div class="body">${esc(pre)}</div>`; wrap.append(head);
  const list = document.createElement("div"); wrap.append(list);
  function draw(){
    list.innerHTML = "";
    rules.forEach((rule, i) => {
      const card = document.createElement("div"); card.className="card";
      const row = document.createElement("div"); row.className="rule";
      row.innerHTML = `<div class="no">${i+1}</div><div class="ct"><div class="body">${esc(rule)}</div></div>`;
      card.append(row);
      if(EDIT){
        const btns = document.createElement("div"); btns.className="btnrow";
        const eb = document.createElement("button"); eb.className="btn"; eb.textContent="✏️ 编辑";
        const db = document.createElement("button"); db.className="btn danger"; db.textContent="删除";
        eb.onclick = () => {
          row.querySelector(".ct").innerHTML = "";
          const ta = document.createElement("textarea"); ta.value = rule;
          const r2 = document.createElement("div"); r2.className="btnrow";
          const ok = document.createElement("button"); ok.className="btn primary"; ok.textContent="保存这条";
          const no = document.createElement("button"); no.className="btn"; no.textContent="取消";
          ok.onclick = async () => { rules[i] = ta.value; dirty=true; if(await commit()) draw(); };
          no.onclick = draw;
          r2.append(ok,no); row.querySelector(".ct").append(ta, r2);
        };
        db.onclick = async () => {
          if(!confirm("删除第 "+(i+1)+" 条规则？")) return;
          rules.splice(i,1); dirty=true; if(await commit()) draw();
        };
        btns.append(eb, db); card.append(btns);
      }
      list.append(card);
    });
    if(EDIT){
      const add = document.createElement("button"); add.className="btn primary"; add.textContent="＋ 加一条规则";
      add.onclick = () => {
        const text = prompt("输入新规则（如：达成率 = 实际 ÷ 预算）：");
        if(text){ rules.push(text+"\n"); dirty=true; commit().then(ok=>{ if(ok) draw(); }); }
      };
      list.append(add);
    }
  }
  async function commit(){
    const body = rules.map((r,i)=> (i+1)+". "+r.replace(/\n+$/,"") ).join("\n") + "\n";
    return save(file, pre + body);
  }
  draw();
  return wrap;
}
// ---- 数据资产：cards.json 表格 ----
function assetsView(){
  const wrap = document.createElement("div");
  const a = DATA.assets;
  if(!a){ wrap.innerHTML = `<div class="card"><div class="body">（未找到 cards.json）</div></div>`; return wrap; }
  for(const [page, info] of Object.entries(a)){
    const card = document.createElement("div"); card.className="card";
    let rows = "";
    for(const [name, c] of Object.entries(info.cards || {})){
      let badges = "";
      if(c["全景"]) badges += `<span class="badge b-ok">全景</span>`;
      if(c["禁用"]) badges += `<span class="badge b-no">禁用</span>`;
      if(c["下钻"]) badges += `<span class="badge b-warn">下钻/局部</span>`;
      rows += `<tr><td>${esc(name)}${badges}</td><td>${esc(c.type||"")}</td><td>${esc(c.notes||"")}</td></tr>`;
    }
    card.innerHTML = `<h3>📈 ${esc(page)}</h3><table><tr><th>卡片</th><th>类型</th><th>备注</th></tr>${rows}</table>`;
    wrap.append(card);
  }
  return wrap;
}
// ---- JSON 原文编辑器 ----
function jsonEditor(file){
  const wrap = document.createElement("div");
  const card = document.createElement("div"); card.className="card";
  const pretty = JSON.stringify(JSON.parse(DATA.files[file]), null, 2);
  card.innerHTML = `<h3>${esc(file)}</h3><div class="body">${esc(pretty)}</div>`;
  if(EDIT){
    const row = document.createElement("div"); row.className="btnrow";
    const btn = document.createElement("button"); btn.className="btn"; btn.textContent="✏️ 编辑";
    btn.onclick = () => {
      card.innerHTML = `<h3>${esc(file)}</h3>`;
      const ta = document.createElement("textarea"); ta.value = pretty; ta.rows = 20;
      const r2 = document.createElement("div"); r2.className="btnrow";
      const ok = document.createElement("button"); ok.className="btn primary"; ok.textContent="保存";
      const no = document.createElement("button"); no.className="btn"; no.textContent="取消";
      ok.onclick = async () => {
        try{ JSON.parse(ta.value); }catch(e){ toast("JSON 格式错误: "+e.message, false); return; }
        dirty=true; if(await save(file, ta.value)) render();
      };
      no.onclick = render;
      r2.append(ok,no); card.append(ta,r2);
    };
    row.append(btn); card.append(row);
  }
  wrap.append(card); return wrap;
}
function render(){
  $("#meta").textContent = "目录：" + DATA.dir + "　·　生成于 " + DATA.generated + (EDIT ? "　·　编辑模式" : "　·　只读");
  const tabsDef = [
    ["assets","📦 数据资产", () => {
      const w = document.createElement("div");
      w.append(assetsView());
      if(DATA.files["learningResult.md"]){
        const h = document.createElement("h2"); h.textContent = "看板资产目录（learningResult）"; h.style.margin="16px 0 8px";
        w.append(h, mdEditor("learningResult.md"));
      }
      return w;
    }],
    ["rules","📏 业务口径", () => DATA.files["businessKnowledge.md"] ? rulesEditor("businessKnowledge.md") : blank("businessKnowledge.md")],
    ["think","🧠 分析思路", () => DATA.files["insightThinking.md"] ? mdEditor("insightThinking.md") : blank("insightThinking.md")],
    ["raw","🗂 其他文件", () => {
      const w = document.createElement("div");
      for(const f of Object.keys(DATA.files)){
        if(["learningResult.md","businessKnowledge.md","insightThinking.md"].includes(f)) continue;
        w.append(f.endsWith(".json") ? jsonEditor(f) : mdEditor(f));
      }
      if(!w.children.length) w.innerHTML = `<div class="card"><div class="body">（无其他文件）</div></div>`;
      return w;
    }],
  ];
  function blank(f){ const d=document.createElement("div"); d.className="card"; d.innerHTML=`<div class="body">（未找到 ${f}）</div>`; return d; }
  const tabsEl = $("#tabs"), panelsEl = $("#panels");
  tabsEl.innerHTML=""; panelsEl.innerHTML="";
  tabsDef.forEach(([id, label, build], i) => {
    const t = document.createElement("button"); t.className="tab"+(i===0?" on":""); t.textContent=label;
    const p = document.createElement("div"); p.className="panel"+(i===0?" on":""); p.append(build());
    t.onclick = () => { document.querySelectorAll(".tab,.panel").forEach(e=>e.classList.remove("on")); t.classList.add("on"); p.classList.add("on"); };
    tabsEl.append(t); panelsEl.append(p);
  });
  if(EDIT){
    const done = document.createElement("button"); done.className="tab"; done.textContent="✅ 完成，关闭工作台";
    done.onclick = async () => {
      if(dirty && !confirm("有未保存修改，确定关闭？")) return;
      await fetch("/shutdown", {method:"POST"}); document.body.innerHTML="<h2 style='margin-top:40px;text-align:center'>工作台已关闭，可以回到对话继续了</h2>";
    };
    $("#tabs").append(done);
  }
}
render();
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
    return (PAGE.replace("__DATA__", json.dumps(data, ensure_ascii=False))
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
