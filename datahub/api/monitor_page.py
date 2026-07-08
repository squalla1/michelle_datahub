"""The /monitor dashboard page, embedded as a string so packaging needs no
static-file handling. Self-contained: inline CSS/JS, no external assets; data
comes from GET /api/v1/stats; auto-refreshes every 60s."""

MONITOR_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Michelle DataHub · 数据监控</title>
<style>
  :root{
    --surface:#fcfcfb; --page:#f9f9f7; --ink:#0b0b0b; --ink-2:#52514e;
    --muted:#898781; --grid:#e1e0d9; --ring:rgba(11,11,11,.10);
    --series:#2a78d6; --good:#0ca30c; --warn:#fab219; --crit:#d03b3b; --neutral:#c3c2b7;
  }
  @media (prefers-color-scheme: dark){
    :root{
      --surface:#1a1a19; --page:#0d0d0d; --ink:#fff; --ink-2:#c3c2b7;
      --muted:#898781; --grid:#2c2c2a; --ring:rgba(255,255,255,.10);
      --series:#3987e5; --neutral:#898781;
    }
  }
  *{box-sizing:border-box;margin:0}
  body{background:var(--page);color:var(--ink);
       font:14px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;padding:24px}
  h1{font-size:18px;font-weight:650}
  .sub{color:var(--muted);font-size:12px;margin:4px 0 20px}
  .card{background:var(--surface);border:1px solid var(--ring);border-radius:10px;padding:16px}
  .tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:20px}
  .tile .v{font-size:26px;font-weight:650;margin-top:2px}
  .tile .k{color:var(--ink-2);font-size:12px}
  .tile .hint{color:var(--muted);font-size:11px;margin-top:2px}
  h2{font-size:13px;font-weight:650;color:var(--ink-2);margin:0 0 10px}
  section{margin-bottom:20px}
  .stack{display:flex;height:22px;border-radius:4px;overflow:hidden;gap:2px;background:var(--page)}
  .stack div{min-width:2px}
  .legend{display:flex;gap:16px;flex-wrap:wrap;margin-top:8px;font-size:12px;color:var(--ink-2)}
  .legend b{color:var(--ink);font-variant-numeric:tabular-nums}
  .dot{display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:5px;vertical-align:-1px}
  table{width:100%;border-collapse:collapse;font-size:13px}
  th{color:var(--muted);font-weight:500;text-align:left;padding:6px 10px;border-bottom:1px solid var(--grid)}
  td{padding:6px 10px;border-bottom:1px solid var(--grid);vertical-align:middle}
  td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
  tr:last-child td{border-bottom:none}
  .bar{background:var(--series);height:14px;border-radius:0 4px 4px 0;min-width:2px}
  .barwrap{display:flex;align-items:center;gap:8px}
  .barwrap span{font-variant-numeric:tabular-nums;color:var(--ink-2);font-size:12px}
  .err{color:var(--crit);font-size:12px;word-break:break-all}
  .muted{color:var(--muted)}
  #tip{position:fixed;pointer-events:none;background:var(--ink);color:var(--page);
       padding:4px 8px;border-radius:5px;font-size:12px;display:none;z-index:9;white-space:nowrap}
  .grid2{display:grid;grid-template-columns:1fr 1fr;gap:12px}
  @media (max-width:760px){.grid2{grid-template-columns:1fr}}
</style>
</head>
<body>
<h1>Michelle DataHub · 数据监控</h1>
<div class="sub" id="meta">加载中…</div>

<div class="tiles" id="tiles"></div>

<div class="grid2">
  <section class="card">
    <h2>正文覆盖(fulltext)</h2>
    <div class="stack" id="ft-bar"></div>
    <div class="legend" id="ft-legend"></div>
  </section>
  <section class="card">
    <h2>近 24 小时抓取执行</h2>
    <div class="stack" id="run-bar"></div>
    <div class="legend" id="run-legend"></div>
  </section>
</div>
<div style="height:12px"></div>

<section class="card">
  <h2>各模块 · 今日入库与库存</h2>
  <table id="mods"><thead><tr>
    <th>模块</th><th style="width:45%">今日入库</th><th class="num">库存</th><th>最新入库(UTC)</th>
  </tr></thead><tbody></tbody></table>
</section>

<section class="card">
  <h2>近 24 小时抓取失败(最近 10 条)</h2>
  <table id="errs"><thead><tr>
    <th>时间(UTC)</th><th>数据源</th><th>错误</th>
  </tr></thead><tbody></tbody></table>
</section>

<div id="tip"></div>
<script>
const $=s=>document.querySelector(s);
const fmt=n=>n==null?"–":n.toLocaleString("en-US");
const t16=s=>s?s.replace("T"," ").slice(5,16):"–";
const tip=$("#tip");
function hover(el,text){
  el.addEventListener("mousemove",e=>{tip.textContent=text;tip.style.display="block";
    tip.style.left=(e.clientX+12)+"px";tip.style.top=(e.clientY+12)+"px";});
  el.addEventListener("mouseleave",()=>tip.style.display="none");
}
function stack(barId,legId,parts){ // parts:[{label,value,color}]
  const total=parts.reduce((a,p)=>a+p.value,0)||1;
  const bar=$(barId),leg=$(legId);bar.innerHTML="";leg.innerHTML="";
  parts.forEach(p=>{
    if(p.value>0){
      const d=document.createElement("div");
      d.style.background=p.color;d.style.width=(100*p.value/total)+"%";
      hover(d,`${p.label} ${fmt(p.value)} (${(100*p.value/total).toFixed(1)}%)`);
      bar.appendChild(d);
    }
    leg.insertAdjacentHTML("beforeend",
      `<span><i class="dot" style="background:${p.color}"></i>${p.label} <b>${fmt(p.value)}</b></span>`);
  });
}
function tile(k,v,hint){return `<div class="card tile"><div class="k">${k}</div><div class="v">${v}</div><div class="hint">${hint||""}</div></div>`}

async function load(){
  const r=await fetch("api/v1/stats");const d=await r.json();
  const T=d.totals,F=d.fulltext,R=d.runs_24h;
  $("#meta").textContent=`生成于 ${t16(d.generated_at)} UTC · 每 60 秒自动刷新 · 最近一次抓取 ${t16(d.last_fetch_at)}`;
  const cov=T.content?(100*F.extracted/T.content).toFixed(1)+"%":"–";
  const rate=R.success_rate==null?"–":(100*R.success_rate).toFixed(1)+"%";
  $("#tiles").innerHTML=
    tile("内容总量",fmt(T.content),"content_item 全库")+
    tile("今日新增",fmt(T.today_new),"UTC 当天入库")+
    tile("24h 抓取成功率",rate,`ok ${fmt(R.ok)} / error ${fmt(R.error)}`)+
    tile("数据源",`${fmt(T.sources_enabled)}<span class="muted" style="font-size:14px">/${fmt(T.sources)}</span>`,"启用 / 总数")+
    tile("正文覆盖率",cov,`已抽取 ${fmt(F.extracted)} 条`);
  stack("#ft-bar","#ft-legend",[
    {label:"✓ 有正文",value:F.extracted,color:"var(--good)"},
    {label:"✕ 抽取失败",value:F.failed,color:"var(--crit)"},
    {label:"待处理",value:F.pending,color:"var(--neutral)"}]);
  stack("#run-bar","#run-legend",[
    {label:"✓ 成功",value:R.ok,color:"var(--good)"},
    {label:"✕ 失败",value:R.error,color:"var(--crit)"},
    {label:"跳过",value:R.skipped,color:"var(--warn)"}]);
  const max=Math.max(...d.modules.map(m=>m.today),1);
  $("#mods tbody").innerHTML=d.modules.map(m=>
    `<tr><td>${m.module}</td>
     <td><div class="barwrap"><div class="bar" style="width:${Math.max(100*m.today/max,1)}%"></div><span>${fmt(m.today)}</span></div></td>
     <td class="num">${fmt(m.total)}</td>
     <td class="muted">${t16(m.last_fetched_at)}</td></tr>`).join("");
  document.querySelectorAll("#mods .bar").forEach((b,i)=>hover(b,`${d.modules[i].module} 今日 ${fmt(d.modules[i].today)} 条`));
  $("#errs tbody").innerHTML=d.recent_errors.length?d.recent_errors.map(e=>
    `<tr><td class="muted" style="white-space:nowrap">${t16(e.started_at)}</td>
     <td>#${e.source_id} ${e.name}</td><td class="err">${(e.error||"").replace(/</g,"&lt;")}</td></tr>`).join("")
    :`<tr><td colspan="3" class="muted">近 24 小时无失败记录 🎉</td></tr>`;
}
load();setInterval(load,60000);
</script>
</body>
</html>
"""
