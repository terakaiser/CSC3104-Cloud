"""Local operations dashboard for the Kubernetes demo."""

# The UI is embedded so the dashboard also works from the installed CLI package.
# ruff: noqa: E501
import csv
import io
import json
import re
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import UTC, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import psutil

from app import demo

RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
ANSI_ESCAPE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|[@-_])")
RESULTS = Path("results/demo")
POD_TAIL = 80
SINGAPORE_TIME = timezone(timedelta(hours=8), "SGT")
TRAINING_STATE = demo.ROOT / "dashboard-training.json"
TRAINING_LOG = demo.ROOT / "dashboard-training.log"
TRAINING_LOCK = threading.Lock()
FAULT_LOG = demo.ROOT / "dashboard-fault.log"
FAULT_STATE = demo.ROOT / "dashboard-fault.json"
FAULT_LOCK = threading.Lock()
BANKS = ("bank-1", "bank-2", "bank-3")
_fault_process = None

PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Bank Federation | Operations Dashboard</title>
<style>
:root{color-scheme:dark;--bg:#0b1220;--panel:#121d2e;--line:#26364c;--muted:#91a3ba;--text:#e8eef7;--cyan:#62d6d0;--green:#4bd49a;--amber:#ffcb72;--red:#ff7b82}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(ellipse at top,#15263b 0,var(--bg) 50%);color:var(--text);font:14px/1.45 "Segoe UI",system-ui,sans-serif}
main{max-width:1500px;margin:auto;padding:28px}header{display:flex;justify-content:space-between;align-items:center;gap:16px;margin-bottom:22px}
h1{font-size:24px;margin:0;letter-spacing:.2px}.eyebrow{font-size:11px;text-transform:uppercase;letter-spacing:1.4px;color:var(--cyan);font-weight:700}
.subtle,.muted{color:var(--muted)}button,select{background:#17263a;border:1px solid var(--line);color:var(--text);border-radius:7px;padding:9px 12px}
.grid{display:grid;gap:14px}.stats{grid-template-columns:repeat(4,minmax(0,1fr));margin-bottom:14px}.cols{grid-template-columns:1.15fr .85fr}.thirds{grid-template-columns:1fr 1fr 1fr}
.card{background:linear-gradient(145deg,rgba(20,32,49,.97),rgba(16,27,42,.97));border:1px solid var(--line);border-radius:11px;padding:16px;min-width:0;box-shadow:0 10px 30px #0002}
.card h2{font-size:14px;margin:0 0 13px;display:flex;justify-content:space-between;align-items:center}.value{font-size:26px;font-weight:700;margin-top:6px}.label{font-size:11px;text-transform:uppercase;letter-spacing:1px;color:var(--muted)}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--muted);margin-right:7px}.ok{color:var(--green)}.ok .dot{background:var(--green)}.warn{color:var(--amber)}.warn .dot{background:var(--amber)}.bad{color:var(--red)}.bad .dot{background:var(--red)}.info{color:var(--cyan)}
.scroll{overflow:auto;max-height:360px}table{width:100%;border-collapse:collapse;font-size:12px}th{text-align:left;color:var(--muted);font-weight:600;font-size:10px;text-transform:uppercase;letter-spacing:.8px}
td,th{padding:9px 8px;border-bottom:1px solid #26364c;vertical-align:top}td code{font-size:11px;color:#cbd9eb}.alerts{display:grid;gap:8px}.alert{padding:9px 11px;border-left:3px solid var(--cyan);background:#18283b;border-radius:4px}.alert.warning{border-color:var(--amber)}.alert.critical{border-color:var(--red)}
.logs{height:285px;overflow:auto;background:#080e18;border:1px solid #26364c;border-radius:7px;padding:10px;font:11px/1.55 Consolas,"Cascadia Code",monospace;white-space:pre-wrap;word-break:break-word;color:#c8d6e8}
.wide{grid-column:1/-1}.charts{grid-template-columns:1fr 1fr}.chart{width:100%;height:210px}.metric{font-size:22px;font-weight:700}.metric small{display:block;font-size:10px;color:var(--muted);font-weight:400;text-transform:uppercase;letter-spacing:.8px}
.pill{border:1px solid var(--line);border-radius:99px;padding:3px 8px;font-size:10px;color:var(--muted)}.blank{padding:24px;text-align:center;color:var(--muted)}
.tabs{display:flex;gap:8px;border-bottom:1px solid var(--line);margin:0 0 16px}.tab{background:transparent;border:0;border-bottom:2px solid transparent;border-radius:0;color:var(--muted);padding:11px 16px;cursor:pointer}.tab.active{border-color:var(--cyan);color:var(--text)}.tab-panel[hidden]{display:none}
<<<<<<< Updated upstream
.controls{display:flex;align-items:end;gap:12px;flex-wrap:wrap}.controls label{display:grid;gap:5px;color:var(--muted);font-size:11px}.controls input{width:120px;background:#0b1422;border:1px solid var(--line);border-radius:6px;color:var(--text);padding:9px}.primary{background:#145e63;border-color:#237d81;color:#efffff;font-weight:700;cursor:pointer}.primary:disabled{opacity:.5;cursor:not-allowed}.runSelect{min-width:260px}.notice{margin-top:10px;color:var(--muted);min-height:20px}.result-status{font-size:20px;font-weight:700}
@media(max-width:950px){.cols,.thirds,.charts{grid-template-columns:1fr}.stats{grid-template-columns:repeat(2,1fr)}main{padding:16px}header{align-items:flex-start}}
=======
.controls{display:flex;align-items:end;gap:12px;flex-wrap:wrap}.controls label{display:grid;gap:5px;color:var(--muted);font-size:11px}.controls input{width:120px;background:#0b1422;border:1px solid var(--line);border-radius:6px;color:var(--text);padding:9px}.primary{background:#145e63;border-color:#237d81;color:#efffff;font-weight:700;cursor:pointer}.primary:disabled{opacity:.5;cursor:not-allowed}.danger{background:#6b1f27;border-color:#a33a44}.runSelect{min-width:260px}.notice{margin-top:10px;color:var(--muted);min-height:20px}.result-status{font-size:20px;font-weight:700}
@media(max-width:950px){.cols,.thirds,.charts{grid-template-columns:1fr}.stats{grid-template-columns:repeat(2,1fr)}main{padding:16px}header{align-items:flex-start}.toolbar{flex-wrap:wrap;justify-content:flex-end}}
.hero{margin-bottom:18px;padding:18px 22px 12px;background:radial-gradient(ellipse at 50% 55%,#152b52 0,#0e1a33 65%)}.hero-head{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;flex-wrap:wrap}.hero-title{font-size:21px;font-weight:700;margin:2px 0 0}.legend{display:flex;gap:14px;flex-wrap:wrap;color:var(--muted);font-size:12px;padding-top:4px}.legend i{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:6px;vertical-align:-1px}.hero-note{color:var(--muted);font-size:12px;text-align:center;margin-top:4px}
#hx{width:100%;height:auto;display:block;max-height:470px;--c:#7d8fa8}.s-idle{--c:#7d8fa8}.s-training{--c:var(--green)}.s-sent{--c:var(--cyan)}.s-waiting{--c:var(--amber)}.s-down{--c:var(--red)}
.hxbox{fill:#0c1830;stroke:var(--c);stroke-width:3;transition:stroke .4s}.s-down .hxbox{animation:hxBlink 1.1s ease-in-out infinite}.db .dbbody{fill:var(--c);opacity:.8}.db .dbtop{fill:var(--c)}.db .dbshine{fill:#fff;opacity:.3}
.hxflow{stroke:var(--c);stroke-width:2.5;fill:none;stroke-dasharray:6 6}.s-training .hxflow{animation:hxDash .8s linear infinite}.hxhead{stroke:var(--c);stroke-width:2.5;fill:none;stroke-linecap:round;stroke-linejoin:round}.hxmini{color:var(--c);opacity:.8;--bar:#0c1830}
.hxicon .bg{fill:var(--c);fill-opacity:.16;stroke:var(--c);stroke-width:2}.hxi{display:none;stroke:var(--c);stroke-width:3;fill:none;stroke-linecap:round;stroke-linejoin:round}.i-idle{fill:var(--c);stroke:none}
.s-training .i-training,.s-sent .i-sent,.s-waiting .i-waiting,.s-down .i-down,.s-idle .i-idle{display:inline}.i-training{animation:hxSpin 1.3s linear infinite;transform-box:fill-box;transform-origin:center}
.hxname{fill:var(--text);font-weight:700;font-size:15px;letter-spacing:.08em}.hxstate{fill:var(--c);font-size:15px;font-weight:600}.hxcount{fill:var(--muted);font-size:13px}
.hxlink{fill:none;stroke:var(--c);stroke-width:3;opacity:.35;transition:stroke .4s}.hxlink.s-training{stroke-dasharray:8 10;animation:hxDash 1s linear infinite;opacity:.75}.hxlink.s-down{stroke-dasharray:3 9;opacity:.6}
.hxbar{fill:var(--bar,#fff)}#hxCore{color:#5d6f96;transition:color .4s}.core-live #hxCore{color:#7f97cf}.core-down #hxCore{color:var(--red)}#hxHalo{fill:none;stroke:var(--c);stroke-width:2;opacity:.35}.core-live{--c:var(--green)}.core-down{--c:var(--red)}.core-live #hxHalo{animation:hxBreathe 2.4s ease-in-out infinite}
#hxRing{fill:none;stroke:var(--cyan);stroke-width:3;opacity:0}#hxRing.pulse{animation:hxPulse 1s ease-out}.hxver{fill:var(--text);font-size:46px;font-weight:800;text-anchor:middle}.hxcap{fill:var(--muted);font-size:13px;text-anchor:middle;letter-spacing:.12em}.hxsub{fill:var(--muted);font-size:14px;text-anchor:middle}
.hxtag{fill:var(--red);font-size:15px;font-weight:700;text-anchor:middle;animation:hxRise 1.8s ease-out forwards}
@keyframes hxSpin{to{transform:rotate(360deg)}}@keyframes hxDash{to{stroke-dashoffset:-36}}@keyframes hxBlink{50%{stroke-opacity:.35}}@keyframes hxBreathe{50%{opacity:.9}}@keyframes hxPulse{0%{opacity:.95;r:74px}100%{opacity:0;r:130px}}@keyframes hxRise{0%{opacity:0;transform:translateY(0)}15%{opacity:1}100%{opacity:0;transform:translateY(-30px)}}
@media(prefers-reduced-motion:reduce){#hx *{animation:none!important}}
>>>>>>> Stashed changes
</style>
</head>
<body><main>
<header><div><div class="eyebrow">CSC3104 · Resilient bank federation</div><h1>Operations dashboard</h1><div id="updated" class="subtle">Connecting to the demo…</div></div>
<<<<<<< Updated upstream
</header>
=======
<div class="toolbar"><button id="refresh">Refresh</button></div></header>
<section class="card hero" aria-label="Live federation visualiser"><div class="hero-head"><div><div class="label">Live federation</div><div class="hero-title" id="hxTitle">Connecting…</div></div>
<div class="legend"><span><i style="background:var(--green)"></i>Training</span><span><i style="background:var(--cyan)"></i>Update sent</span><span><i style="background:var(--amber)"></i>Waiting for round</span><span><i style="background:var(--red)"></i>Down / recovering</span><span><i style="background:#7d8fa8"></i>Idle</span></div></div>
<svg id="hx" viewBox="0 0 1000 455" role="img" aria-label="Three banks training locally and sending model updates to the global model">
<defs><filter id="hxGlow" x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation="5" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
<symbol id="hxBrainSym" viewBox="-64 -54 128 108"><g fill="currentColor"><circle cx="-34" cy="-26" r="22"/><circle cx="-46" cy="4" r="22"/><circle cx="-32" cy="30" r="22"/><circle cx="-14" cy="-36" r="18"/><circle cx="-14" cy="38" r="16"/><circle cx="-22" cy="2" r="26"/><circle cx="34" cy="-26" r="22"/><circle cx="46" cy="4" r="22"/><circle cx="32" cy="30" r="22"/><circle cx="14" cy="-36" r="18"/><circle cx="14" cy="38" r="16"/><circle cx="22" cy="2" r="26"/></g><rect class="hxbar" x="-5" y="-40" width="10" height="80" rx="4"/></symbol></defs>
<g id="hxLinks"></g>
<text class="hxcap" x="500" y="58">GLOBAL MODEL</text><text class="hxver" id="hxVer" x="500" y="106">v0</text><text class="hxsub" id="hxRound" x="500" y="132">—</text>
<g id="hxCenter" class="core-idle"><circle id="hxHalo" cx="500" cy="222" r="88"/><circle id="hxRing" cx="500" cy="222" r="74"/><use id="hxCore" href="#hxBrainSym" x="428" y="161" width="144" height="122" filter="url(#hxGlow)"/></g>
<g id="hxBanks"></g><g id="hxPackets"></g></svg>
<div class="hero-note">White dots carry the global model out to the banks · cyan dots are bank updates · red dots are rejected (stale or late) updates</div></section>
>>>>>>> Stashed changes
<nav class="tabs" aria-label="Dashboard sections"><button class="tab active" data-tab="monitor">Live monitor</button><button class="tab" data-tab="results">Results</button></nav>
<section class="tab-panel" id="monitorPanel">
<section class="grid cols" style="margin-bottom:14px"><article class="card"><h2>Start a training run <span class="pill" id="trainState">Ready</span></h2>
<form id="trainForm" class="controls"><label>Training rounds<input id="roundInput" type="number" min="1" max="1000" value="30" required></label>
<label>Attempt deadline (seconds)<input id="deadlineInput" type="number" min="0.001" step="any" value="30" required></label>
<button class="primary" id="startTraining" type="submit">Start training</button></form>
<div class="notice" id="trainMessage">Training runs on the prepared Kubernetes demo cluster. Results appear in the Results tab after export and evaluation.</div></article>
<<<<<<< Updated upstream
<article class="card"><h2>Simulate self-healing</h2>
<form id="faultForm" class="controls"><label>Bank to fail<select id="faultBank"><option>bank-1</option><option>bank-2</option><option>bank-3</option></select></label>
<button class="primary" id="simulateFailure" type="submit" disabled>Delete bank pod</button></form>
<div class="notice" id="faultMessage">Start training to enable one bank failure simulation.</div>
<div id="faultTracker" class="subtle">Deleted pod and replacement details will appear here.</div></article></section>
=======
<article class="card" style="margin-bottom:14px"><h2>Simulate a bank failure <span class="pill" id="faultState">Waiting for training</span></h2>
<form id="faultForm" class="controls"><label>Bank to kill<select id="faultBank"><option>bank-1</option><option>bank-2</option><option selected>bank-3</option></select></label>
<button class="primary danger" id="killBank" type="submit" disabled>Kill bank pod</button></form>
<div class="notice" id="faultMessage">After a few rounds commit, kill one bank's pod. The other two keep training and Kubernetes replaces the killed pod.</div></article>
>>>>>>> Stashed changes
<section class="grid stats">
<article class="card"><div class="label">Kubernetes cluster</div><div class="value" id="cluster">—</div><div class="subtle" id="clusterNote">Checking cluster</div></article>
<article class="card"><div class="label">Ready pods</div><div class="value" id="podCount">—</div><div class="subtle">Coordinator + bank workers</div></article>
<article class="card"><div class="label">Training</div><div class="value" id="training">—</div><div class="subtle" id="trainingNote">Waiting for run data</div></article>
<article class="card"><div class="label">Current run</div><div class="value" id="runStatus">—</div><div class="subtle" id="runNote">No training run loaded</div></article>
</section>
<section class="grid cols">
<article class="card"><h2>Pods <span class="pill" id="podBadge">—</span></h2><div class="scroll"><table><thead><tr><th>Pod</th><th>Role</th><th>Phase / readiness</th><th>Restarts</th><th>Node</th><th>Conditions / issue</th></tr></thead><tbody id="pods"></tbody></table></div></article>
<article class="card"><h2>Alerts &amp; observations <span class="pill" id="alertCount">0</span></h2><div class="alerts" id="alerts"><div class="blank">No alerts loaded</div></div></article>
<article class="card"><h2>Deployments</h2><div class="scroll"><table><thead><tr><th>Name</th><th>Ready</th><th>Available</th><th>Image</th></tr></thead><tbody id="deployments"></tbody></table></div></article>
<article class="card"><h2>Services &amp; recent Kubernetes events <span class="pill">times in SGT</span></h2><div class="scroll"><div id="services"></div><table><thead><tr><th>Time (SGT)</th><th>Type / reason</th><th>Object</th><th>Message</th></tr></thead><tbody id="kubeEvents"></tbody></table></div></article>
<article class="card wide"><h2>Training progress <span class="pill" id="progressBadge">No run selected</span></h2><div class="grid"><canvas class="chart" id="roundChart"></canvas></div><div class="scroll"><table><thead><tr><th>Attempt</th><th>Version</th><th>Outcome</th><th>Duration</th><th>Accepted banks</th><th>Examples</th></tr></thead><tbody id="rounds"></tbody></table></div></article>
<article class="card"><h2>Training event stream <span class="pill">events.jsonl</span></h2><pre class="logs" id="trainLog">Waiting for training events…</pre></article>
<article class="card"><h2>Pod logs <span class="pill">latest 80 lines</span></h2><pre class="logs" id="podLogs">Waiting for pod logs…</pre></article>
</section>
</section>
<section class="tab-panel" id="resultsPanel" hidden>
<article class="card" style="margin-bottom:14px"><div class="controls"><label>Run to inspect<select id="runSelect" class="runSelect" aria-label="Select a training run"></select></label><div><div class="label">Run outcome</div><div id="resultTitle" class="result-status">No run selected</div></div></div>
<div id="resultMessage" class="notice">Start a training run from Live monitor. Once it finishes, its exported evaluation will be available here.</div></article>
<div class="grid thirds" id="metrics"></div>
<article class="card" style="margin-top:14px"><h2>Model quality across versions</h2><canvas class="chart" id="qualityChart"></canvas><div id="evaluationNote" class="subtle"></div></article>
<article class="card" style="margin-top:14px"><h2>Evaluation by bank <span class="pill">test set</span></h2><div class="scroll"><table><thead><tr><th>Bank</th><th>Precision</th><th>Recall</th><th>F1</th><th>Average precision</th><th>ROC-AUC</th><th>False positive rate</th></tr></thead><tbody id="bankMetrics"></tbody></table></div></article>
</section>
</main>
<script>
const el=id=>document.getElementById(id), fmt=(n,d=1)=>Number.isFinite(Number(n))?Number(n).toFixed(d):"—";
function cell(v){return v===undefined||v===null||v===""?"—":String(v)}
function esc(s){return String(s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]))}
function row(values){return "<tr>"+values.map(v=>"<td>"+esc(cell(v))+"</td>").join("")+"</tr>"}
function badgeClass(s){return /completed|ready|running|committed|normal/i.test(s)?"ok":/deadline|warning|pending|late|stale|not ready|restart/i.test(s)?"warn":/failed|error|crash|backoff|insufficient|timeout/i.test(s)?"bad":"info"}
function chart(canvas,series,title,yLabel){const ctx=canvas.getContext("2d"),w=canvas.clientWidth,h=canvas.clientHeight,ratio=devicePixelRatio||1;canvas.width=w*ratio;canvas.height=h*ratio;ctx.scale(ratio,ratio);ctx.clearRect(0,0,w,h);ctx.fillStyle="#91a3ba";ctx.font="11px Segoe UI";ctx.fillText(title,8,14);if(!series.length){ctx.fillText("No data available",10,40);return}const all=series.flatMap(s=>s.points).filter(p=>Number.isFinite(p[0])&&Number.isFinite(p[1]));if(!all.length)return;const xmin=Math.min(...all.map(p=>p[0])),xmax=Math.max(...all.map(p=>p[0])),ymin=Math.min(0,...all.map(p=>p[1])),ymax=Math.max(...all.map(p=>p[1]));const pad={l:40,r:10,t:25,b:25},cw=w-pad.l-pad.r,ch=h-pad.t-pad.b;ctx.strokeStyle="#26364c";ctx.fillStyle="#91a3ba";ctx.lineWidth=1;for(let i=0;i<4;i++){let y=pad.t+ch*i/3;ctx.beginPath();ctx.moveTo(pad.l,y);ctx.lineTo(w-pad.r,y);ctx.stroke()}ctx.fillText(fmt(ymax-(ymax-ymin)*.0,2),3,pad.t+4);ctx.fillText(fmt(ymin,2),3,h-pad.b);const X=x=>pad.l+(x-xmin)/(xmax-xmin||1)*cw,Y=y=>pad.t+ch-(y-ymin)/(ymax-ymin||1)*ch;const colors=["#62d6d0","#ffcb72","#ff7b82","#9c9aff"];series.forEach((s,i)=>{ctx.strokeStyle=colors[i%colors.length];ctx.fillStyle=ctx.strokeStyle;ctx.lineWidth=2;ctx.beginPath();s.points.forEach((p,j)=>j?ctx.lineTo(X(p[0]),Y(p[1])):ctx.moveTo(X(p[0]),Y(p[1])));ctx.stroke();s.points.forEach(p=>{ctx.beginPath();ctx.arc(X(p[0]),Y(p[1]),3,0,7);ctx.fill()})})}
let activeTab="monitor";
function setTab(name){activeTab=name;document.querySelectorAll(".tab").forEach(b=>b.classList.toggle("active",b.dataset.tab===name));el("monitorPanel").hidden=name!=="monitor";el("resultsPanel").hidden=name!=="results";if(window.lastData)renderRun(window.lastData);history.replaceState(null,"",name==="results"?"#results":"#monitor")}
function formatEvent(event){const details=[];for(const key of ["attempt","version","bank","outcome","status","valid","required","committed_rounds"]){if(event[key]!==undefined&&event[key]!==null)details.push(`${key}=${Array.isArray(event[key])?event[key].join(","):event[key]}`)}if(event.accepted)details.push(`accepted=${event.accepted.join(",")}`);if(event.error)details.push(`error=${event.error}`);const elapsed=Number(event.elapsed_seconds);return `[${Number.isFinite(elapsed)?elapsed.toFixed(2)+"s":"time unknown"}] ${event.event||"event"}${details.length?" · "+details.join(" · "):""}`}
function renderRun(d){const run=d.run||{},s=run.summary||{},ev=run.evaluation||{},final=ev.final||{},options=d.runs||[],selected=run.run_id||"",rounds=run.rounds||[];
<<<<<<< Updated upstream
if(el("runSelect").dataset.current!==options.map(o=>o.id).join("|")){el("runSelect").innerHTML=options.map(o=>`<option value="${esc(o.id)}">${esc(o.label)}</option>`).join("");el("runSelect").dataset.current=options.map(o=>o.id).join("|")}el("runSelect").value=selected;
=======
// The blank option follows the newest/live run; only an explicit choice pins an older run.
if(el("runSelect").dataset.current!==options.map(o=>o.id).join("|")){const keep=el("runSelect").value;el("runSelect").innerHTML='<option value="">Latest run (follows live training)</option>'+options.map(o=>`<option value="${esc(o.id)}">${esc(o.label)}</option>`).join("");el("runSelect").dataset.current=options.map(o=>o.id).join("|");el("runSelect").value=options.some(o=>o.id===keep)?keep:""}
>>>>>>> Stashed changes
el("progressBadge").textContent=selected?`${selected}${d.active?" · LIVE":""}`:"No run selected";
el("resultTitle").textContent=s.status||"No run selected";
el("resultMessage").textContent=d.active?"Training is still running. The final test evaluation will appear here after the run exports and evaluates its checkpoints.":ev.final?`Results for ${selected}. Metrics are calculated from the run's saved checkpoints and evaluation dataset.`:"No exported evaluation is available for this run yet.";
const events=run.events||[];el("trainLog").textContent=events.length?events.slice(-80).map(formatEvent).join("\n"):d.active?"Waiting for events from the coordinator…":selected?"No training events recorded for this run.":"Start training to see coordinator events.";el("trainLog").scrollTop=el("trainLog").scrollHeight;
const metrics=[["Committed rounds",s.committed_rounds],["Attempts",s.attempts],["Successful round rate",s.successful_round_rate===undefined?null:fmt(s.successful_round_rate*100,1)+"%"],["Processed examples",s.processed_examples_returned],["Average precision",final.pr_auc_average_precision===undefined?null:fmt(final.pr_auc_average_precision,4)],["F1 score",final.f1===undefined?null:fmt(final.f1,4)],["ROC-AUC",final.roc_auc===undefined?null:fmt(final.roc_auc,4)],["Training time",s.training_seconds===undefined?null:fmt(s.training_seconds,1)+" s"],["Participation",Object.entries(s.participation||{}).map(([k,v])=>`${k}: ${v}`).join(" · ")] ];el("metrics").innerHTML=metrics.map(([k,v])=>`<div class="metric">${esc(cell(v))}<small>${esc(k)}</small></div>`).join("");
el("rounds").innerHTML=rounds.slice().reverse().map(r=>row([r.attempt,r.version,r.status,`${fmt(r.seconds,1)} s`,r.accepted,r.samples])).join("")||'<tr><td colspan="6" class="blank">Round records will appear when training starts.</td></tr>';
const curve=ev.curve||[];const bank=ev.per_bank||{};el("bankMetrics").innerHTML=Object.entries(bank).map(([name,m])=>row([name,fmt(m.precision,3),fmt(m.recall,3),fmt(m.f1,3),fmt(m.pr_auc_average_precision,3),fmt(m.roc_auc,3),fmt(m.false_positive_rate,4)])).join("")||'<tr><td colspan="7" class="blank">Evaluation appears after the run is exported and evaluated.</td></tr>';el("evaluationNote").textContent=ev.synthetic_data?"Synthetic dataset: software-check metrics only, not fraud-detection evidence.":ev.threshold_rule||"";
if(activeTab==="monitor")chart(el("roundChart"),[{points:rounds.map(r=>[Number(r.attempt),Number(r.seconds)])}],"Attempt duration (seconds)","seconds");if(activeTab==="results")chart(el("qualityChart"),[{points:curve.map(x=>[Number(x.version),Number(x.pr_auc_average_precision)])}],"Test average precision by model version","AP")}
function render(d){window.lastData=d;el("updated").textContent="Last updated "+new Date(d.generated_at).toLocaleTimeString();el("cluster").textContent=d.kubernetes?.available?"Connected":d.prepared?"Unavailable":"Not set up";el("clusterNote").textContent=d.kubernetes?.error|| (d.prepared?"Context kind-bank-fl-demo / namespace bank-fl":"Run bank-fl demo setup first");const pods=d.kubernetes?.pods||[];const ready=pods.filter(p=>p.ready).length;el("podCount").textContent=pods.length?`${ready} / ${pods.length}`:"—";el("podBadge").textContent=`${ready} ready`;el("pods").innerHTML=pods.length?pods.map(p=>row([p.name,p.role,p.phase+(p.ready?" · Ready":" · Not Ready"),p.restarts,p.node,p.issues.join("; ")])).join(""):'<tr><td colspan="6" class="blank">No pods returned</td></tr>';
el("deployments").innerHTML=(d.kubernetes?.deployments||[]).map(x=>row([x.name,`${x.ready}/${x.desired}`,x.available,x.images.join(", ")])).join("")||'<tr><td colspan="4" class="blank">No deployments found</td></tr>';
el("services").innerHTML=(d.kubernetes?.services||[]).map(s=>`<div style="padding:7px;border-bottom:1px solid #26364c"><b>${esc(s.name)}</b> <span class="muted">${esc(s.cluster_ip)} · ${esc(s.ports.join(", "))}</span></div>`).join("")||'<div class="blank">No services found</div>';
el("kubeEvents").innerHTML=(d.kubernetes?.events||[]).map(e=>row([e.time,`${e.type} / ${e.reason}`,e.object,e.message])).join("")||'<tr><td colspan="4" class="blank">No recent events</td></tr>';
el("alerts").innerHTML=d.alerts.length?d.alerts.map(a=>`<div class="alert ${a.level}"><b>${esc(a.title)}</b><div>${esc(a.message)}</div></div>`).join(""):'<div class="alert">No issues detected in the latest snapshot.</div>';el("alertCount").textContent=d.alerts.length;
const run=d.run||{},s=run.summary||{};el("training").textContent=d.active?"RUNNING":s.status||"IDLE";el("trainingNote").textContent=d.active?`${s.committed_rounds||0} committed · attempt ${run.latest_attempt||0}`:`${s.committed_rounds||0} committed rounds`;el("runStatus").textContent=s.status||"—";el("runNote").textContent=s.attempts?`${s.committed_rounds} / ${run.config?.rounds||"?"} rounds · ${fmt(s.successful_round_rate*100,0)}% success rate`:"No summary yet";
const canStart=d.prepared&&d.kubernetes?.available;el("startTraining").disabled=d.active||!canStart;el("trainState").textContent=d.active?"Training in progress":!d.prepared?"Setup required":!d.kubernetes?.available?"Cluster unavailable":"Ready to train";const logLines=(d.training_log||"").trim().split("\n");const lastLog=logLines[logLines.length-1]||"";el("trainMessage").textContent=d.active?`Run ${run.run_id||"starting"} is active. Follow live progress here; open Results after it finishes.`:s.status?`Latest run: ${s.status}. Open Results to inspect its exported evaluation.`:!d.prepared?"Run `uv run bank-fl demo setup` before starting a training run.":!d.kubernetes?.available?`Kubernetes is unavailable: ${d.kubernetes?.error||"cluster connection failed"}`:lastLog||"Choose rounds and deadline, then start. Training runs through Flower on the Kubernetes demo cluster.";
<<<<<<< Updated upstream
const fault=d.fault||{},record=fault.record;el("simulateFailure").disabled=!fault.available||fault.requested;el("faultMessage").textContent=record?.status==="ready"?`${record.bank} recovered and became Ready in ${fmt(record.fault_to_ready_seconds,1)} s. Only one simulation is allowed per run.`:record?.status==="timed_out"?"Replacement did not become Ready before the recovery timeout.":record?.status==="failed"?`Failure simulation failed: ${record.error||"unknown error"}`:fault.requested?"Failure injected; tracking pod replacement…":fault.available?"Choose a bank and delete its pod. Kubernetes should create a replacement while training continues.":d.active?"Training is starting; wait for the coordinator before simulating a failure.":"Start training to enable one bank failure simulation.";el("faultTracker").innerHTML=record?`<div>Bank: <b>${esc(record.bank)}</b> · Status: <b>${esc(record.status||"unknown")}</b></div><div>Deleted pod: <code>${esc(record.deleted_pod||"waiting")}</code></div><div>Replacement pod: <code>${esc(record.replacement_pod||"waiting for Kubernetes")}</code></div><div>Replacement UID: <code>${esc(record.replacement_uid||"—")}</code></div>`:"Deleted pod and replacement details will appear here.";
renderRun(d);el("podLogs").textContent=d.kubernetes?.logs||d.kubernetes?.logs_error||"No pod logs available."}
let busy=false,refreshQueued=false,selectionVersion=0;async function refresh(){if(busy){refreshQueued=true;return}busy=true;const version=selectionVersion;try{const q=el("runSelect").value;const r=await fetch("/api/dashboard"+(q?"?run="+encodeURIComponent(q):""),{cache:"no-store"});const d=await r.json();if(!r.ok)throw new Error(d.error||"Dashboard refresh failed");if(version===selectionVersion)render(d)}catch(e){if(version===selectionVersion)el("updated").textContent="Dashboard update failed: "+e.message}finally{busy=false;if(refreshQueued){refreshQueued=false;refresh()}}}
document.querySelectorAll(".tab").forEach(b=>b.addEventListener("click",()=>setTab(b.dataset.tab)));el("runSelect").addEventListener("change",()=>{selectionVersion++;refresh()});
el("trainForm").addEventListener("submit",async event=>{event.preventDefault();const button=el("startTraining");button.disabled=true;selectionVersion++;el("runSelect").value="";render({...window.lastData,active:true,runs:[],run:{run_id:null,summary:{},evaluation:{},rounds:[],events:[],config:{},latest_attempt:0}});el("trainMessage").textContent="Starting the Kubernetes training run…";try{const response=await fetch("/api/train",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({rounds:Number(el("roundInput").value),deadline:Number(el("deadlineInput").value)})});const result=await response.json();if(!response.ok)throw new Error(result.error||"Unable to start training");el("trainMessage").textContent=`Training started (process ${result.pid}). Live progress will appear here.`;await refresh()}catch(error){el("trainMessage").textContent=error.message;button.disabled=false;await refresh()}});
el("faultForm").addEventListener("submit",async event=>{event.preventDefault();const button=el("simulateFailure");button.disabled=true;el("faultMessage").textContent="Injecting the failure and waiting for Kubernetes to recreate the pod…";try{const response=await fetch("/api/fail",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({bank:el("faultBank").value})});const result=await response.json();if(!response.ok)throw new Error(result.error||"Unable to simulate the failure");el("faultMessage").textContent=result.record.recovery_censored?"Replacement was not observed before the timeout. Check the pod status and event stream.":`${result.bank} recovered and became Ready in ${fmt(result.record.fault_to_ready_seconds,1)} seconds.`;await refresh()}catch(error){el("faultMessage").textContent=error.message;button.disabled=false;await refresh()}});
if(location.hash==="#results")setTab("results");refresh();setInterval(refresh,5000);
=======
hero(d);const faultLines=(d.fault_log||"").trim().split("\n").filter(Boolean);el("killBank").disabled=!d.active||faultPending||faultLines.length>0;el("faultState").textContent=d.active?(faultLines.length?"Fault injected":"Ready to kill"):"Waiting for training";if(faultLines.length)el("faultMessage").textContent=faultLines[faultLines.length-1];
renderRun(d);el("podLogs").textContent=d.kubernetes?.logs||d.kubernetes?.logs_error||"No pod logs available."}
let busy=false;async function refresh(){if(busy)return;busy=true;try{const q=el("runSelect").value;const r=await fetch("/api/dashboard"+(q?"?run="+encodeURIComponent(q):""),{cache:"no-store"});const d=await r.json();if(!r.ok)throw new Error(d.error||"Dashboard refresh failed");render(d)}catch(e){el("updated").textContent="Dashboard update failed: "+e.message}finally{busy=false}}
document.querySelectorAll(".tab").forEach(b=>b.addEventListener("click",()=>setTab(b.dataset.tab)));el("refresh").addEventListener("click",refresh);el("runSelect").addEventListener("change",refresh);
el("trainForm").addEventListener("submit",async event=>{event.preventDefault();const button=el("startTraining");button.disabled=true;el("runSelect").value="";el("trainMessage").textContent="Starting the Kubernetes training run…";try{const response=await fetch("/api/train",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({rounds:Number(el("roundInput").value),deadline:Number(el("deadlineInput").value)})});const result=await response.json();if(!response.ok)throw new Error(result.error||"Unable to start training");el("trainMessage").textContent=`Training started (process ${result.pid}). Live progress will appear here.`;await refresh()}catch(error){el("trainMessage").textContent=error.message;button.disabled=false}});
let faultPending=false;el("faultForm").addEventListener("submit",async event=>{event.preventDefault();const bank=el("faultBank").value;faultPending=true;el("killBank").disabled=true;el("faultMessage").textContent=`Terminating ${bank}'s pod…`;try{const response=await fetch("/api/fail",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({bank})});const result=await response.json();if(!response.ok)throw new Error(result.error||"Unable to kill the bank");el("faultMessage").textContent=`Killing ${bank}. Watch the Pods table: a replacement pod starts while the other banks keep committing rounds.`;await refresh()}catch(error){el("faultMessage").textContent=error.message}finally{faultPending=false}});
// Federation visualiser: bank states come from pod readiness and the coordinator's event log.
const NS="http://www.w3.org/2000/svg",HXB=[["bank-1",40,30,"M200 140 C200 230 320 232 438 218"],["bank-2",640,30,"M800 140 C800 230 680 232 562 218"],["bank-3",340,335,"M500 335 C500 318 500 302 500 286"]];
const hxSeen={run:undefined,n:0},hxMotion=!matchMedia("(prefers-reduced-motion: reduce)").matches;
function hxInit(){el("hxLinks").innerHTML=HXB.map(([b,,,d])=>`<path id="hxl-${b}" class="hxlink s-idle" d="${d}"/>`).join("");
el("hxBanks").innerHTML=HXB.map(([b,x,y])=>`<g id="hx-${b}" class="s-idle" transform="translate(${x},${y})"><rect class="hxbox" width="320" height="110" rx="22" filter="url(#hxGlow)"/>
<g class="db" transform="translate(34,18)"><path class="dbbody" d="M0 8 V38 A30 8 0 0 0 60 38 V8 Z"/><ellipse class="dbtop" cx="30" cy="8" rx="30" ry="8"/><ellipse class="dbshine" cx="30" cy="8" rx="30" ry="8"/></g>
<path class="hxflow" d="M110 41 H168"/><path class="hxhead" d="M162 35 L169 41 L162 47"/><use class="hxmini" href="#hxBrainSym" x="178" y="12" width="70" height="60"/>
<g class="hxicon" transform="translate(283,41)"><circle class="bg" r="18"/><g class="hxi i-training"><path d="M10 0 A10 10 0 0 1 -7 7"/><path d="M-2 7 L-7 7 L-7 12"/><path d="M-10 0 A10 10 0 0 1 7 -7"/><path d="M2 -7 L7 -7 L7 -12"/></g>
<path class="hxi i-sent" d="M-7 0 L-2 5 L8 -6"/><path class="hxi i-down" d="M-6 -6 L6 6 M6 -6 L-6 6"/><g class="hxi i-waiting"><circle r="9"/><path d="M0 -5 V0 L4 3"/></g><circle class="hxi i-idle" r="5"/></g>
<text class="hxname" x="34" y="94">${b.toUpperCase().replace("-"," ")}</text><text class="hxstate" x="120" y="94">Idle</text><text class="hxcount" x="296" y="94" text-anchor="end">0 rounds</text></g>`).join("")}
function hxSvg(tag,attrs){const n=document.createElementNS(NS,tag);for(const k in attrs)n.setAttribute(k,attrs[k]);el("hxPackets").append(n);return n}
function hxPulse(){const r=el("hxRing");r.classList.remove("pulse");void r.getBoundingClientRect();r.classList.add("pulse")}
function hxFly(bank,inbound,color,tag){if(!hxMotion)return;const p=el("hxl-"+bank),L=p.getTotalLength(),c=hxSvg("circle",{r:7,fill:color,filter:"url(#hxGlow)"}),t0=performance.now(),dur=1100;
function step(t){const k=Math.min(1,(t-t0)/dur),e=k<.5?2*k*k:1-(-2*k+2)**2/2,pt=p.getPointAtLength((inbound?e:1-e)*L);c.setAttribute("cx",pt.x);c.setAttribute("cy",pt.y);if(k<1)return requestAnimationFrame(step);c.remove();
if(inbound&&tag){const s=hxSvg("text",{class:"hxtag",x:pt.x,y:pt.y-14});s.textContent=tag;setTimeout(()=>s.remove(),1900)}}requestAnimationFrame(step)}
function hero(d){const run=d.run||{},act=d.active,starting=act&&!!run.summary?.status,ev=starting?[]:run.events||[],cfg=starting?{}:run.config||{},pods=d.kubernetes?.pods||[],k8s=d.kubernetes?.available;
const pending={},sent=new Set(),rejoining={},contrib={};let version=0;
for(const e of ev){if(e.event==="attempt_started")sent.clear();else if(e.event==="dispatched")pending[e.bank]=e.request_id;
else if(e.event==="reply"){if(e.request_id&&pending[e.bank]===e.request_id)delete pending[e.bank];if(e.outcome==="accepted"){sent.add(e.bank);rejoining[e.bank]=false}else if(e.outcome==="client_error")rejoining[e.bank]=true}
else if(e.event==="committed"){version=e.version;(e.accepted||[]).forEach(b=>contrib[b]=(contrib[b]||0)+1)}}
const live=pods.filter(p=>!p.terminating),up=role=>live.some(p=>p.role===role&&p.ready),f=act&&!starting?d.fault:null;
for(const [b] of HXB){const exists=live.some(p=>p.role===b),lost=f?.bank===b&&!ev.some(e=>e.event==="dispatched"&&e.bank===b&&e.unix_time>f.unix_time);let s,label;
if(!k8s){s="idle";label="Offline"}else if(!up(b)){s="down";label=exists?"Restarting":"Pod down"}else if(lost){s="down";label="Recovering"}
else if(act&&pending[b]){s="training";label="Training"}else if(act&&sent.has(b)){s="sent";label="Update sent"}
else if(act){s="waiting";label=rejoining[b]?"Rejoining":"Waiting"}else{s="idle";label="Idle"}
const g=el("hx-"+b);g.setAttribute("class","s-"+s);g.querySelector(".hxstate").textContent=label;g.querySelector(".hxcount").textContent=`${contrib[b]||0} round${contrib[b]===1?"":"s"}`;el("hxl-"+b).setAttribute("class","hxlink s-"+s)}
el("hxCenter").setAttribute("class",k8s&&!up("coordinator")?"core-down":act?"core-live":"core-idle");
const total=cfg.rounds||0,status=run.summary?.status;el("hxVer").textContent="v"+version;
el("hxRound").textContent=starting?"Connecting to the banks":total?`${version} / ${total} rounds · quorum ${cfg.quorum||2} of ${cfg.banks||3}`:"No training run yet";
el("hxTitle").textContent=!k8s?"Kubernetes cluster unavailable":starting?"Starting training…":act?`Training · round ${Math.min(version+1,total||version+1)}${total?" of "+total:""}`:status?`Last run ${status.replace(/_/g," ")} · ${version} rounds`:"Ready to train";
// Animate only events that arrived since the previous refresh; never replay an old run.
if(hxSeen.run!==run.run_id||ev.length<hxSeen.n){hxSeen.run=run.run_id;hxSeen.n=ev.length;return}
const fresh=ev.slice(hxSeen.n);hxSeen.n=ev.length;let t=0,arrive=0;
for(const e of fresh){if(e.event==="reply"&&e.bank&&e.outcome!=="client_error"){const ok=e.outcome==="accepted",at=t;setTimeout(()=>hxFly(e.bank,true,ok?"#62d6d0":"#ff7b82",ok?null:e.outcome.replace(/_/g," ")+" ✕"),at);arrive=Math.max(arrive,at+1100);t+=160}
else if(e.event==="committed"){t=Math.max(t,arrive);setTimeout(hxPulse,t);t+=450}else if(e.event==="dispatched"&&e.bank){const at=t;setTimeout(()=>hxFly(e.bank,false,"#e8eef7"),at);t+=140}}}
hxInit();
if(location.hash==="#results")setTab("results");refresh();setInterval(refresh,2000);
>>>>>>> Stashed changes
</script></body></html>"""


def _read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


def _dashboard_process_active():
    state = _read_json(TRAINING_STATE) or {}
    pid = state.get("pid")
    created = state.get("created")
    if type(pid) is not int or not isinstance(created, (int, float)):
        return False
    try:
        process = psutil.Process(pid)
        return process.create_time() == created and process.is_running()
    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
        return False


def _training_active():
    return demo.active() or _dashboard_process_active()


def launch_training(rounds, deadline):
    from app.config import RunConfig

    config = RunConfig(rounds=rounds, deadline=deadline)
    if not (demo.ROOT / "settings.json").is_file():
        raise ValueError("Run `uv run bank-fl demo setup` before starting training.")
    with TRAINING_LOCK:
        if _training_active():
            raise RuntimeError("Training is already running.")
        demo.ROOT.mkdir(exist_ok=True)
        FAULT_LOG.unlink(missing_ok=True)  # A new run starts without an injected fault.
        FAULT_STATE.unlink(missing_ok=True)
        with TRAINING_LOG.open("w", encoding="utf-8") as log:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "app.cli",
                    "demo",
                    "start",
                    "--rounds",
                    str(config.rounds),
                    "--deadline",
                    str(config.deadline),
                ],
                env=demo.environment(),
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
        try:
            created = psutil.Process(process.pid).create_time()
        except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
            exit_code = process.poll()
            detail = _read_training_log().strip()
            raise RuntimeError(
                f"Training process exited during startup (code {exit_code}): {detail or exc}"
            ) from exc
        state = {"pid": process.pid, "created": created}
        temporary = TRAINING_STATE.with_suffix(".tmp")
        temporary.write_text(json.dumps(state), encoding="utf-8")
        temporary.replace(TRAINING_STATE)
    return {"status": "starting", "pid": process.pid}


def launch_fault(bank):
    global _fault_process
    if bank not in BANKS:
        raise ValueError(f"Bank must be one of {', '.join(BANKS)}.")
    if not demo.active():
        raise RuntimeError("Start training and wait for a few committed rounds first.")
    with FAULT_LOCK:
        if _fault_process is not None and _fault_process.poll() is None:
            raise RuntimeError("A bank failure is already in progress.")
        # `demo fail` waits for the replacement pod, so it runs in the background.
        with FAULT_LOG.open("w", encoding="utf-8") as log:
            _fault_process = subprocess.Popen(
                [sys.executable, "-m", "app.cli", "demo", "fail", "--bank", bank],
                env=demo.environment(),
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
        # The visualiser keeps the bank red until the coordinator dispatches to it again.
        FAULT_STATE.write_text(json.dumps({"bank": bank, "unix_time": time.time()}))
    return {"status": "terminating", "bank": bank, "pid": _fault_process.pid}


def _read_fault_log():
    try:
        return FAULT_LOG.read_text(encoding="utf-8", errors="replace")[-4_000:]
    except FileNotFoundError:
        return ""


def _kubectl(*args):
    result = subprocess.run(
        ["kubectl", "--context", f"kind-{demo.CLUSTER}", "-n", "bank-fl", *args],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=8,
        env=demo.environment(),
    )
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"
        raise RuntimeError(detail)
    return result.stdout


def _age(timestamp):
    if not timestamp:
        return ""
    try:
        value = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(SINGAPORE_TIME).strftime("%Y-%m-%d %H:%M:%S SGT")
    except ValueError:
        return timestamp


def _kubernetes():
    data = json.loads(_kubectl("get", "pods,deployments,services,events", "-o", "json"))
    pods, deployments, services, events = [], [], [], []
    for item in data.get("items", []):
        kind = item["kind"]
        metadata = item.get("metadata", {})
        name = metadata.get("name", "")
        status = item.get("status", {})
        if kind == "Pod":
            containers = status.get("containerStatuses", [])
            ready = bool(containers) and all(c.get("ready", False) for c in containers)
            issues = []
            for container in containers:
                if container.get("restartCount", 0):
                    issues.append(
                        f"{container.get('name')}: {container['restartCount']} restart(s)"
                    )
                state = container.get("state", {})
                waiting = state.get("waiting")
                terminated = state.get("terminated")
                if waiting:
                    issues.append(f"{container.get('name')}: {waiting.get('reason', 'waiting')}")
                if terminated and terminated.get("exitCode", 0):
                    issues.append(f"{container.get('name')}: exited {terminated['exitCode']}")
            conditions = status.get("conditions", [])
            if not ready:
                issues.extend(
                    f"{c.get('type')}: {c.get('message') or c.get('reason')}"
                    for c in conditions
                    if c.get("status") == "False" and c.get("type") in ("Ready", "PodScheduled")
                )
            role = next(
                (key for key in ("app", "component") if metadata.get("labels", {}).get(key)),
                "unknown",
            )
            pods.append(
                {
                    "name": name,
                    "role": metadata.get("labels", {}).get(role, role),
                    "phase": status.get("phase", "Unknown"),
                    "ready": ready,
                    "terminating": bool(metadata.get("deletionTimestamp")),
                    "restarts": sum(c.get("restartCount", 0) for c in containers),
                    "node": item.get("spec", {}).get("nodeName", "—"),
                    "issues": issues,
                }
            )
        elif kind == "Deployment":
            spec, deployment_status = item.get("spec", {}), status
            deployments.append(
                {
                    "name": name,
                    "desired": spec.get("replicas", 1),
                    "ready": deployment_status.get("readyReplicas", 0),
                    "available": deployment_status.get("availableReplicas", 0),
                    "images": [
                        container.get("image", "")
                        for container in spec.get("template", {})
                        .get("spec", {})
                        .get("containers", [])
                    ],
                }
            )
        elif kind == "Service":
            services.append(
                {
                    "name": name,
                    "cluster_ip": item.get("spec", {}).get("clusterIP", "—"),
                    "ports": [
                        f"{p.get('port')}/{p.get('protocol', 'TCP')}"
                        for p in item.get("spec", {}).get("ports", [])
                    ],
                }
            )
        elif kind == "Event":
            events.append(
                {
                    "time": _age(
                        item.get("eventTime")
                        or item.get("lastTimestamp")
                        or metadata.get("creationTimestamp")
                    ),
                    "type": item.get("type", "Normal"),
                    "reason": item.get("reason", ""),
                    "object": item.get("involvedObject", {}).get("name", ""),
                    "message": item.get("message", ""),
                    "count": item.get("count", 1),
                }
            )
    events.sort(key=lambda event: event["time"], reverse=True)
    logs, logs_error = "", None
    try:
        logs = ANSI_ESCAPE.sub(
            "",
            _kubectl(
                "logs",
                "-l",
                "project=bank-fl",
                "--all-containers=true",
                "--prefix=true",
                f"--tail={POD_TAIL}",
                "--max-log-requests=10",
            ),
        ).strip()
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        logs_error = f"Unable to read pod logs: {exc}"
    return {
        "available": True,
        "pods": sorted(pods, key=lambda pod: pod["name"]),
        "deployments": sorted(deployments, key=lambda deployment: deployment["name"]),
        "services": sorted(services, key=lambda service: service["name"]),
        "events": events[:20],
        "logs": logs,
        "logs_error": logs_error,
    }


def _read_csv(text):
    if not text:
        return []
    return [
        {
            **row,
            "attempt": int(row["attempt"]),
            "version": int(row["version"]),
            "seconds": float(row["seconds"]),
            "samples": int(row["samples"]),
        }
        for row in csv.DictReader(io.StringIO(text))
    ]


def _jsonl(text):
    events = []
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.strip():
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                if index == len(lines) - 1 and not text.endswith("\n"):
                    break
                raise
    return events


def _run_ids():
    found = {}
    if RESULTS.exists():
        for path in RESULTS.glob("*/*/run.json"):
            run_id = path.parent.name
            if RUN_ID_PATTERN.fullmatch(run_id):
                found[run_id] = path.parent
    latest = _read_json(demo.ROOT / "latest.json") or {}
    run_id = latest.get("run_id")
    if isinstance(run_id, str) and RUN_ID_PATTERN.fullmatch(run_id):
        found.setdefault(run_id, Path(latest.get("output", RESULTS)) / run_id)
    return found, latest


def _read_remote_run(latest):
    pod = latest.get("pod")
    if not pod:
        return None
    script = (
        "import json,pathlib,sys;"
        "root=pathlib.Path('/results');"
        "wanted=sys.argv[1];"
        "started=float(sys.argv[2]);"
        "runs=list(root.glob('*/run.json'));"
        "folders=[path.parent for path in runs if path.stat().st_mtime>=started];"
        "folders=[root/wanted] if wanted and root.joinpath(wanted,'run.json').is_file() "
        "and (root/wanted/'run.json').stat().st_mtime>=started else folders;"
        "folder=max(folders,key=lambda path:path.stat().st_mtime,default=None);"
        "names=('run.json','summary.json','evaluation.json','rounds.csv','events.jsonl');"
        "files={name:(folder/name).read_text(encoding='utf-8') for name in names "
        "if folder and (folder/name).is_file()};"
        "print(json.dumps({'run_id':folder.name if folder else None,'files':files}))"
    )
    try:
        active_state = _read_json(demo.ROOT / "active.json") or {}
        output = _kubectl(
            "exec",
            pod,
            "--",
            "python",
            "-c",
            script,
            latest.get("run_id") or "",
            str(active_state.get("started_at", 0)),
        )
        return json.loads(output)
    except (OSError, RuntimeError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        latest["discovery_error"] = str(exc)
        return None


def _load_run(run_id, path, remote_files=None):
    files = {}
    for name in ("run.json", "summary.json", "evaluation.json", "rounds.csv", "events.jsonl"):
        local = path / name
        if local.is_file():
            files[name] = local.read_text(encoding="utf-8")
    for name, content in (remote_files or {}).items():
        files.setdefault(name, content)
    run_data = {}
    for name in ("run.json", "summary.json", "evaluation.json"):
        if files.get(name):
            run_data[name] = json.loads(files[name])
    run_data["rounds"] = _read_csv(files.get("rounds.csv", ""))
    run_data["events"] = _jsonl(files.get("events.jsonl", ""))
    run_data["run_id"] = run_id
    run_data["config"] = run_data.get("run.json", {}).get("config", {})
    run_data["latest_attempt"] = max(
        (event.get("attempt", 0) for event in run_data["events"]), default=0
    )
    run_data["summary"] = run_data.get("summary.json", {})
    run_data["evaluation"] = run_data.get("evaluation.json", {})
    return run_data


def _alerts(kubernetes, run, prepared):
    alerts = []
    if not prepared:
        alerts.append(
            {
                "level": "warning",
                "title": "Demo not set up",
                "message": "Run `uv run bank-fl demo setup` before starting Kubernetes training.",
            }
        )
    if kubernetes.get("error"):
        alerts.append(
            {"level": "critical", "title": "Kubernetes unavailable", "message": kubernetes["error"]}
        )
        return alerts
    for pod in kubernetes.get("pods", []):
        if not pod["ready"]:
            alerts.append(
                {
                    "level": "critical" if pod["phase"] == "Failed" else "warning",
                    "title": f"Pod not ready: {pod['name']}",
                    "message": "; ".join(pod["issues"]) or f"Pod phase is {pod['phase']}.",
                }
            )
        elif pod["restarts"]:
            alerts.append(
                {
                    "level": "warning",
                    "title": f"Container restarts: {pod['name']}",
                    "message": f"{pod['restarts']} restart(s) observed.",
                }
            )
    for deployment in kubernetes.get("deployments", []):
        if deployment["available"] < deployment["desired"]:
            alerts.append(
                {
                    "level": "warning",
                    "title": f"Deployment not fully available: {deployment['name']}",
                    "message": f"{deployment['available']} of {deployment['desired']} replicas are available.",
                }
            )
    for event in kubernetes.get("events", []):
        if event["type"] == "Warning":
            alerts.append(
                {
                    "level": "warning",
                    "title": f"Kubernetes warning: {event['reason']}",
                    "message": f"{event['object']}: {event['message']}",
                }
            )
    summary = run.get("summary", {})
    if summary.get("status") and summary["status"] != "completed":
        alerts.append(
            {
                "level": "critical",
                "title": f"Training ended: {summary['status']}",
                "message": f"{summary.get('committed_rounds', 0)} rounds committed across {summary.get('attempts', 0)} attempts.",
            }
        )
    for event in run.get("events", []):
        if event.get("event") == "deadline":
            alerts.append(
                {
                    "level": "warning",
                    "title": f"Attempt {event.get('attempt')} missed its deadline",
                    "message": f"{event.get('valid', 0)} of {event.get('required', 0)} replies arrived before the deadline.",
                }
            )
        elif event.get("event") == "startup_failed":
            alerts.append(
                {
                    "level": "critical",
                    "title": "Training startup failed",
                    "message": f"Coordinator required {event.get('required')} available banks.",
                }
            )
    rejected = {}
    for event in run.get("events", []):
        if event.get("event") == "reply" and event.get("outcome") not in (None, "accepted"):
            reason = event["outcome"]
            rejected[reason] = rejected.get(reason, 0) + 1
    if rejected:
        details = ", ".join(f"{reason}: {count}" for reason, count in sorted(rejected.items()))
        alerts.append(
            {
                "level": "warning",
                "title": "Training replies rejected",
                "message": f"{sum(rejected.values())} reply/replies were not used ({details}). Stale or late replies can result from deadline timing.",
            }
        )
    if summary:
        participation = summary.get("participation", {})
        absent = [bank for bank, count in participation.items() if count == 0]
        if absent and summary.get("committed_rounds", 0):
            alerts.append(
                {
                    "level": "warning",
                    "title": "Uneven bank participation",
                    "message": f"No committed update from {', '.join(absent)}.",
                }
            )
        if summary.get("synthetic_data"):
            alerts.append(
                {
                    "level": "warning",
                    "title": "Synthetic data",
                    "message": "Metrics are software checks, not evidence of real fraud-detection quality.",
                }
            )
    return alerts[:30]


def simulate_self_healing(bank):
    if bank not in {"bank-1", "bank-2", "bank-3"}:
        raise ValueError("bank must be bank-1, bank-2, or bank-3")
    if not demo.active():
        raise RuntimeError("Start a training run before simulating self-healing.")
    try:
        demo.fail(bank)
    except FileExistsError as exc:
        raise RuntimeError("Only one bank failure simulation is allowed per training run.") from exc
    latest = _read_json(demo.ROOT / "latest.json") or {}
    output = latest.get("output")
    record = _read_json(Path(output) / "fault.json") if isinstance(output, str) else None
    if record is None:
        raise RuntimeError("Failure simulation finished without writing a recovery record.")
    return {"bank": bank, "record": record}


def dashboard_data(selected_run=None):
    settings = _read_json(demo.ROOT / "settings.json")
    prepared = settings is not None
    active = False
    demo_active = False
    active_error = None
    try:
        demo_active = demo.active()
        active = demo_active or _dashboard_process_active()
    except (psutil.AccessDenied, OSError, KeyError, TypeError) as exc:
        active_error = str(exc)
    run_paths, latest = _run_ids()
    active_id = latest.get("run_id") if demo_active else None
    remote_files = {}
    if demo_active and not active_id:
        remote = _read_remote_run(latest)
        active_id = remote.get("run_id") if remote else None
        if remote:
            remote_files = remote.get("files", {})
        if active_id:
            if RUN_ID_PATTERN.fullmatch(active_id):
                latest["run_id"] = active_id
                run_paths.setdefault(active_id, Path(latest.get("output", RESULTS)) / active_id)
            else:
                active_id = None
    elif demo_active and latest.get("pod"):
        remote = _read_remote_run(latest)
        if remote:
            remote_files = remote.get("files", {})
    ordered = sorted(
        run_paths,
        key=lambda run_id: run_paths[run_id].stat().st_mtime if run_paths[run_id].exists() else 0,
        reverse=True,
    )
    if active_id in run_paths:
        ordered.remove(active_id)
        ordered.insert(0, active_id)
    if selected_run:
        if selected_run not in run_paths:
            raise ValueError("Requested run is not available in this demo.")
        run_id = selected_run
    else:
        run_id = active_id if active else (ordered[0] if ordered else None)
    runs = [
        {
            "id": item,
            "label": f"{item}{' · live' if item == active_id else ''}",
        }
        for item in ordered[:20]
    ]
    run = (
        _load_run(
            run_id,
            run_paths[run_id],
            remote_files if active and run_id == active_id else None,
        )
        if run_id
        else {
            "run_id": None,
            "summary": {},
            "evaluation": {},
            "rounds": [],
            "events": [],
            "config": {},
            "latest_attempt": 0,
        }
    )
    try:
        kubernetes = (
            _kubernetes()
            if prepared
            else {
                "available": False,
                "pods": [],
                "deployments": [],
                "services": [],
                "events": [],
                "logs": "",
            }
        )
        kubernetes_error = None
    except (OSError, RuntimeError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        kubernetes_error = str(exc)
        kubernetes = {
            "available": False,
            "error": kubernetes_error,
            "pods": [],
            "deployments": [],
            "services": [],
            "events": [],
            "logs": "",
        }
    alerts = _alerts(kubernetes, run, prepared)
    if active_error:
        alerts.append(
            {
                "level": "warning",
                "title": "Training process status unavailable",
                "message": active_error,
            }
        )
    if latest.get("discovery_error"):
        alerts.append(
            {
                "level": "warning",
                "title": "Live run details not discovered",
                "message": latest["discovery_error"],
            }
        )
    if kubernetes.get("logs_error"):
        alerts.append(
            {
                "level": "warning",
                "title": "Pod logs unavailable",
                "message": kubernetes["logs_error"],
            }
        )
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "prepared": prepared,
        "active": active,
        "fault": {**_fault_status(latest), "available": demo_active and kubernetes.get("available", False)},
        "training_log": _read_training_log(),
        "fault_log": _read_fault_log(),
        "fault": _read_json(FAULT_STATE),
        "runs": runs,
        "run": run,
        "kubernetes": kubernetes,
        "alerts": alerts,
    }


def _fault_status(latest):
    output = latest.get("output")
    if not isinstance(output, str):
        return {"requested": False, "record": None}
    directory = Path(output)
    record = _read_json(directory / "fault.json")
    return {"requested": (directory / "fault-requested").exists(), "record": record}


def _read_training_log():
    try:
        with TRAINING_LOG.open("rb") as stream:
            stream.seek(0, 2)
            size = stream.tell()
            stream.seek(max(0, size - 16_384))
            text = stream.read().decode("utf-8", errors="replace")
        if size > 16_384:
            text = text.split("\n", 1)[-1]
        return text[-12_000:]
    except FileNotFoundError:
        return ""


def _valid_dashboard_origin(handler):
    host = handler.headers.get("Host", "").split(":", 1)[0].strip("[]").lower()
    origin = urlsplit(handler.headers.get("Origin", ""))
    return (
        origin.scheme in ("http", "https")
        and origin.hostname in ("127.0.0.1", "localhost")
        and origin.netloc.lower() == handler.headers.get("Host", "").lower()
        and host in ("127.0.0.1", "localhost")
    )


class DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlsplit(self.path)
        if parsed.path == "/":
            body = PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path != "/api/dashboard":
            self.send_error(404)
            return
        selected = parse_qs(parsed.query).get("run", [None])[0]
        try:
            payload = json.dumps(dashboard_data(selected), allow_nan=False).encode("utf-8")
            self.send_response(200)
        except ValueError as exc:
            payload = json.dumps({"error": str(exc)}).encode("utf-8")
            self.send_response(400)
        except (OSError, RuntimeError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
            payload = json.dumps({"error": str(exc)}).encode("utf-8")
            self.send_response(500)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self):
<<<<<<< Updated upstream
        endpoint = urlsplit(self.path).path
        if endpoint not in {"/api/train", "/api/fail"}:
            self.send_error(404)
            return
        if not _valid_dashboard_origin(self):
            self.send_error(403, "Dashboard actions must come from this local dashboard.")
=======
        route = urlsplit(self.path).path
        if route not in ("/api/train", "/api/fail"):
            self.send_error(404)
            return
        if not _valid_dashboard_origin(self):
            self.send_error(403, "Dashboard requests must come from this local dashboard.")
>>>>>>> Stashed changes
            return
        if self.headers.get_content_type() != "application/json":
            self.send_error(415, "Expected application/json.")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 1 <= length <= 4096:
                raise ValueError("Request body must be between 1 and 4096 bytes.")
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError("Expected a JSON object.")
<<<<<<< Updated upstream
            if endpoint == "/api/train":
=======
            if route == "/api/fail":
                result = launch_fault(body.get("bank"))
            else:
>>>>>>> Stashed changes
                rounds = body.get("rounds")
                deadline = body.get("deadline")
                if (
                    type(rounds) is not int
                    or isinstance(deadline, bool)
                    or not isinstance(deadline, (int, float))
                ):
                    raise ValueError("Rounds must be an integer and deadline must be a number.")
                result = launch_training(rounds, deadline)
<<<<<<< Updated upstream
                status = 202
            else:
                result = simulate_self_healing(body.get("bank"))
                status = 200
=======
>>>>>>> Stashed changes
            payload = json.dumps(result).encode("utf-8")
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            payload = json.dumps({"error": str(exc)}).encode("utf-8")
            status = 400
        except FileExistsError as exc:
            payload = json.dumps({"error": str(exc)}).encode("utf-8")
            status = 409
        except OSError as exc:
            payload = json.dumps({"error": f"Dashboard action failed: {exc}"}).encode("utf-8")
            status = 500
        except RuntimeError as exc:
            payload = json.dumps({"error": str(exc)}).encode("utf-8")
            status = 409
        except subprocess.SubprocessError as exc:
            payload = json.dumps({"error": f"Failure simulation failed: {exc}"}).encode("utf-8")
            status = 500
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format, *args):
        print(f"dashboard: {format % args}")


def serve(port=8765, open_browser=True):
    if not 1 <= port <= 65535:
        raise ValueError("dashboard port must be between 1 and 65535")
    server = ThreadingHTTPServer(("127.0.0.1", port), DashboardHandler)
    url = f"http://127.0.0.1:{port}"
    print(f"Dashboard available at {url} (Ctrl+C to stop)", flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard stopped.", flush=True)
    finally:
        server.server_close()
