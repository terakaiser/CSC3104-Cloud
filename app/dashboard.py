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
import webbrowser
from datetime import UTC, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import psutil

from app import demo
from app.resources import pod_usage

RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
ANSI_ESCAPE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|[@-_])")
RESULTS = Path("results/demo")
POD_TAIL = 80
SINGAPORE_TIME = timezone(timedelta(hours=8), "SGT")
TRAINING_STATE = demo.ROOT / "dashboard-training.json"
TRAINING_LOG = demo.ROOT / "dashboard-training.log"
TRAINING_LOCK = threading.Lock()

PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="theme-color" content="#0a0a0a">
<title>Bank Federation | Operations Dashboard</title>
<style>
/* shadcn/ui neutral dark tokens; colour is reserved for state and data, one emerald accent for the primary action. */
:root{color-scheme:dark;--bg:#0a0a0a;--card:#141414;--raised:#1c1c1c;--muted-bg:#262626;--border:rgb(255 255 255/.08);--input:rgb(255 255 255/.14);--ring:#a3a3a3;--text:#fafafa;--muted:#a1a1a1;--faint:#737373;--radius:10px;
--green:#34d399;--cyan:#38bdf8;--amber:#fbbf24;--red:#f87171;--idle:#737373}
*{box-sizing:border-box}html{background:var(--bg)}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.5 "Inter","Segoe UI Variable Text","Segoe UI",system-ui,sans-serif;-webkit-font-smoothing:antialiased;-webkit-tap-highlight-color:transparent}
.skip{position:absolute;left:16px;top:-60px;background:var(--text);color:var(--bg);padding:8px 12px;border-radius:8px;z-index:10}.skip:focus{top:12px}
main{max-width:1400px;margin:auto;padding:32px 24px 48px}header{display:flex;justify-content:space-between;align-items:flex-end;gap:16px;margin-bottom:24px;flex-wrap:wrap}
h1{font-size:28px;line-height:1.1;font-weight:600;letter-spacing:-.025em;margin:0;text-wrap:balance}.subline{color:var(--muted);margin-top:6px}
.status{display:inline-flex;align-items:center;gap:8px;height:32px;padding:0 12px;border:1px solid var(--border);border-radius:8px;background:var(--card);color:var(--muted);font-size:13px}
.subtle,.muted{color:var(--muted)}code{font:12px/1.5 "JetBrains Mono","Cascadia Code",Consolas,monospace;color:#d4d4d4}
button,select,input{font:inherit;color:var(--text);touch-action:manipulation}
button{display:inline-flex;align-items:center;justify-content:center;gap:8px;height:36px;padding:0 14px;border:1px solid var(--input);border-radius:8px;background:transparent;font-weight:500;cursor:pointer;transition:background-color .15s,border-color .15s,color .15s,opacity .15s}
button:hover:not(:disabled){background:var(--raised)}button:active:not(:disabled){transform:translateY(1px)}button:disabled{opacity:.45;cursor:not-allowed}
:focus-visible{outline:2px solid var(--ring);outline-offset:2px}
select,.controls input{height:36px;padding:0 10px;background-color:rgb(255 255 255/.04);color:var(--text);border:1px solid var(--input);border-radius:8px;transition:border-color .15s}select option{background:var(--card);color:var(--text)}select:hover,.controls input:hover{border-color:rgb(255 255 255/.24)}
.grid{display:grid;gap:16px}.stats{grid-template-columns:repeat(4,minmax(0,1fr));margin-bottom:16px}.cols{grid-template-columns:1.15fr .85fr}.thirds{grid-template-columns:repeat(3,minmax(0,1fr))}
.card{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);padding:20px;min-width:0}
.card h2{font-size:15px;font-weight:600;letter-spacing:-.01em;margin:0 0 14px;display:flex;justify-content:space-between;align-items:center;gap:12px}
.label{font-size:13px;color:var(--muted)}.value{font-size:28px;font-weight:600;letter-spacing:-.025em;margin-top:4px;font-variant-numeric:tabular-nums;overflow-wrap:anywhere}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--faint);flex:none}.ok{color:var(--green)}.ok .dot{background:var(--green)}.warn{color:var(--amber)}.warn .dot{background:var(--amber)}.bad{color:var(--red)}.bad .dot{background:var(--red)}.info{color:var(--cyan)}
.scroll{overflow:auto;max-height:360px;overscroll-behavior:contain}table{width:100%;border-collapse:collapse;font-size:13px;font-variant-numeric:tabular-nums}th{text-align:left;color:var(--muted);font-weight:500;font-size:12px;position:sticky;top:0;background:var(--card)}
td,th{padding:10px 10px;border-bottom:1px solid var(--border);vertical-align:top}td{overflow-wrap:anywhere}tbody tr{transition:background-color .15s}tbody tr:hover{background:rgb(255 255 255/.025)}
.alerts{display:grid;gap:8px}.alert{padding:10px 12px;border:1px solid var(--border);border-left:3px solid var(--cyan);background:var(--raised);border-radius:8px}.alert b{font-weight:600}.alert div{color:var(--muted);font-size:13px;margin-top:2px;display:-webkit-box;-webkit-line-clamp:4;-webkit-box-orient:vertical;overflow:hidden;overflow-wrap:anywhere}.alert.warning{border-left-color:var(--amber)}.alert.critical{border-left-color:var(--red)}
.logs{height:285px;overflow:auto;overscroll-behavior:contain;background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:12px;margin:0;font:12px/1.6 "JetBrains Mono","Cascadia Code",Consolas,monospace;white-space:pre-wrap;word-break:break-word;color:#d4d4d4}
.wide{grid-column:1/-1}.charts{grid-template-columns:1fr 1fr}.chart{width:100%;height:220px}
.metric{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);padding:16px 20px;font-size:24px;font-weight:600;letter-spacing:-.02em;font-variant-numeric:tabular-nums;overflow-wrap:anywhere}.metric small{display:block;font-size:13px;color:var(--muted);font-weight:400;letter-spacing:0;margin-top:4px}
.pill{display:inline-flex;align-items:center;height:22px;padding:0 8px;border-radius:6px;background:var(--muted-bg);color:var(--muted);font-size:12px;font-weight:500;white-space:nowrap;font-variant-numeric:tabular-nums}.blank{padding:24px;text-align:center;color:var(--muted)}
.tabs{display:inline-flex;gap:2px;padding:3px;background:var(--card);border:1px solid var(--border);border-radius:10px;margin:0 0 16px}.tab{height:30px;padding:0 14px;border:0;border-radius:7px;color:var(--muted)}.tab:hover:not(:disabled){background:transparent;color:var(--text)}.tab.active,.tab.active:hover{background:var(--muted-bg);color:var(--text)}.tab-panel[hidden]{display:none}
.controls{display:flex;align-items:end;gap:12px;flex-wrap:wrap}.controls label{display:grid;gap:6px;color:var(--muted);font-size:13px}.controls input{width:140px;font-variant-numeric:tabular-nums}
.primary{background:var(--green);border-color:transparent;color:#03140d;font-weight:600}.primary:hover:not(:disabled){background:#6ee7b7}
.danger{background:rgb(248 113 113/.1);border-color:rgb(248 113 113/.4);color:#fca5a5}.danger:hover:not(:disabled){background:rgb(248 113 113/.18)}.danger.armed,.danger.armed:hover:not(:disabled){background:#dc2626;border-color:transparent;color:#fff}
#clusterNote{display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden;overflow-wrap:anywhere;font-size:13px}
.runSelect{min-width:280px}.notice{margin-top:12px;color:var(--muted);font-size:13px;min-height:20px}.result-status{font-size:20px;font-weight:600;letter-spacing:-.01em}
#faultTracker{margin-top:12px;font-size:13px;display:grid;gap:4px}#faultTracker b{color:var(--text);font-weight:500}
.service{padding:8px 10px;border-bottom:1px solid var(--border)}.service b{font-weight:500}
.tech{margin-top:16px}.tech summary{cursor:pointer;font-weight:600;font-size:15px}.tech[open] summary{margin-bottom:14px}.tech h3{display:flex;align-items:center;gap:8px;margin:0 0 8px;font-size:13px;font-weight:500;color:var(--muted)}.techgrid{grid-template-columns:1fr 1fr}
@media(max-width:950px){.cols,.thirds,.charts,.techgrid{grid-template-columns:1fr}.stats{grid-template-columns:repeat(2,minmax(0,1fr))}main{padding:20px 16px 40px}}
.hero{margin-bottom:16px;padding:22px 24px 24px}.hero-head h2{margin:0 0 2px;color:var(--muted);font-weight:500;font-size:14px}.hero-title{font-size:22px;font-weight:600;letter-spacing:-.02em;font-variant-numeric:tabular-nums}
.story{color:var(--muted);margin:6px 0 22px;max-width:78ch;min-height:21px;text-wrap:pretty}
.s-idle{--c:var(--idle)}.s-training{--c:var(--green)}.s-sent{--c:var(--cyan)}.s-waiting{--c:var(--amber)}.s-down{--c:var(--red)}
.fed{display:grid;grid-template-columns:minmax(280px,350px) minmax(48px,1fr) minmax(250px,300px);align-items:center}
.banks,.lanes{display:grid;grid-template-rows:repeat(__BANKS__,120px);gap:14px}
.ico{width:16px;height:16px;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round;flex:none}
.bank{display:grid;grid-template-rows:auto auto 1fr auto;gap:7px;padding:13px 16px;border:1px solid var(--border);border-left:3px solid var(--c);border-radius:var(--radius);background:color-mix(in srgb,var(--c) 5%,var(--raised));transition:border-color .3s,background-color .3s}
.bank-top{display:flex;justify-content:space-between;align-items:center;gap:8px}.bank-name{display:inline-flex;align-items:center;gap:8px;font-weight:600;font-size:15px}.bank-name .ico{color:var(--muted)}
.state{display:inline-flex;align-items:center;gap:6px;height:24px;padding:0 10px;border-radius:999px;font-size:12.5px;font-weight:500;color:var(--c);background:color-mix(in srgb,var(--c) 15%,transparent);white-space:nowrap}
.st{display:none}.s-training .st-training,.s-sent .st-sent,.s-waiting .st-waiting,.s-down .st-down,.s-idle .st-idle{display:block}.st-training{animation:hxSpin .9s linear infinite}
.bank-sub{display:flex;align-items:center;gap:6px;color:var(--faint);font-size:12.5px;min-width:0}.bank-sub span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.strip{display:flex;gap:2px;height:10px;align-self:center}.strip i{flex:1;min-width:2px;border-radius:2px;background:rgb(255 255 255/.06)}.strip i.on{background:var(--green)}.strip i.off{background:rgb(255 255 255/.2)}
.bank-foot{display:flex;justify-content:space-between;color:var(--muted);font-size:12.5px;font-variant-numeric:tabular-nums}
.lane{width:100%;height:120px;display:block;overflow:visible}.lane .track{fill:none;stroke:var(--c);stroke-width:2;opacity:.22}.lane .port{fill:var(--c);opacity:.6}
.lane.s-training .track{opacity:.65;stroke-dasharray:6 8;animation:hxDash 1s linear infinite}.lane.s-sent .track{opacity:.55}.lane.s-down .track{opacity:.6;stroke-dasharray:2 7}
.coord{--c:var(--idle);display:grid;gap:16px;justify-items:center;padding:18px 18px 20px;border:1px solid var(--border);border-radius:14px;background:var(--raised);transition:border-color .3s}
.coord.core-live{--c:var(--green);border-color:color-mix(in srgb,var(--green) 35%,transparent)}.coord.core-down{--c:var(--red);border-color:color-mix(in srgb,var(--red) 45%,transparent)}
.coord-head{display:flex;align-items:center;gap:8px;font-weight:600;font-size:15px}.coord-head .ico{color:var(--muted)}.coord-head small{color:var(--faint);font-weight:400;font-size:13px}
.ringwrap{position:relative;width:150px;height:150px}.ringwrap svg{width:100%;height:100%;transform:rotate(-90deg)}.ring-bg{fill:none;stroke:rgb(255 255 255/.07);stroke-width:9}
.ring-fg{fill:none;stroke:var(--c);stroke-width:9;stroke-linecap:round;transition:stroke-dashoffset .6s ease,stroke .3s}.coord.core-idle .ring-fg{stroke:var(--green);opacity:.75}
.ring-txt{position:absolute;inset:0;display:grid;place-content:center;text-align:center}.ring-txt small{color:var(--faint);font-size:12px}.ring-txt b{font-size:36px;line-height:1.1;font-weight:600;letter-spacing:-.03em;font-variant-numeric:tabular-nums}.ring-txt span{color:var(--muted);font-size:12.5px;font-variant-numeric:tabular-nums}
.coord.pulse .ringwrap{animation:hxPop .6s ease-out}
.quorum{justify-self:stretch;display:grid;gap:8px}.q-label{display:flex;justify-content:space-between;gap:8px;color:var(--muted);font-size:12.5px}
.slots{display:grid;grid-template-columns:repeat(__BANKS__,1fr);gap:6px}.slot{height:30px;display:grid;place-items:center;border-radius:7px;border:1px dashed rgb(255 255 255/.16);color:var(--faint);font-size:12px;transition:background-color .3s,border-color .3s,color .3s}
.slot.on{border:1px solid transparent;background:color-mix(in srgb,var(--cyan) 18%,transparent);color:var(--cyan);font-weight:500}
.hxtag{fill:var(--red);font-size:12px;font-weight:600;text-anchor:end;animation:hxRise 1.8s ease-out forwards}
@keyframes hxSpin{to{transform:rotate(360deg)}}@keyframes hxDash{to{stroke-dashoffset:-28}}@keyframes hxPop{40%{transform:scale(1.06)}}@keyframes hxRise{0%{opacity:0;transform:translateY(0)}15%{opacity:1}100%{opacity:0;transform:translateY(-18px)}}
@media(max-width:900px){.fed{grid-template-columns:1fr;gap:14px}.lanes{display:none}.coord{order:-1}.banks{grid-template-rows:none}}
@media(prefers-reduced-motion:reduce){.hero *{animation:none!important;transition:none!important}button:active:not(:disabled){transform:none}}
</style>
</head>
<body><a class="skip" href="#main">Skip to Content</a><main id="main">
<header><div><h1>Bank Federation Operations</h1><div class="subline">CSC3104 Group 18<span id="updated" class="bad"> · Connecting to the demo…</span></div></div>
<div class="status" id="clusterChip"><span class="dot"></span><span id="clusterChipText">Checking cluster…</span></div></header>
<section class="card hero" aria-labelledby="hxHeading"><div class="hero-head"><h2 id="hxHeading">Live Federation</h2><div class="hero-title" id="hxTitle" aria-live="polite">Connecting…</div></div>
<p class="story" id="hxStory">Each bank trains on its own data and sends only model updates to the coordinator.</p>
<div class="fed"><div class="banks" id="hxBanks"></div><div class="lanes" id="hxLanes" aria-hidden="true"></div>
<div class="coord core-idle" id="hxCenter"><div class="coord-head"><svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="3" width="18" height="7" rx="2"/><rect x="3" y="14" width="18" height="7" rx="2"/><path d="M7 6.5h.01M7 17.5h.01"/></svg>Coordinator <small id="hxAlgo">FedAvg</small></div>
<div class="ringwrap"><svg viewBox="0 0 120 120" aria-hidden="true"><circle class="ring-bg" cx="60" cy="60" r="52"/><circle class="ring-fg" id="hxRing" cx="60" cy="60" r="52" stroke-dasharray="326.73" stroke-dashoffset="326.73"/></svg>
<div class="ring-txt"><small>Global model</small><b id="hxVer">v0</b><span id="hxRound">No rounds yet</span></div></div>
<div class="quorum"><div class="q-label"><span id="hxQLabel">Updates per round</span><span id="hxQNeed">quorum</span></div><div class="slots" id="hxSlots"></div></div></div></div></section>
<nav class="tabs" role="tablist" aria-label="Dashboard sections"><button class="tab active" role="tab" aria-selected="true" aria-controls="monitorPanel" data-tab="monitor">Live Monitor</button><button class="tab" role="tab" aria-selected="false" aria-controls="resultsPanel" data-tab="results">Results</button></nav>
<section class="tab-panel" id="monitorPanel" role="tabpanel">
<section class="grid cols" style="margin-bottom:16px"><article class="card"><h2>Start a Training Run <span class="pill" id="trainState">Ready</span></h2>
<form id="trainForm" class="controls"><label>Training rounds<input id="roundInput" name="rounds" type="number" inputmode="numeric" autocomplete="off" min="1" max="1000" value="30" required></label>
<label>Attempt deadline (seconds)<input id="deadlineInput" name="deadline" type="number" inputmode="decimal" autocomplete="off" min="0.001" step="any" value="30" required></label>
<label>Algorithm<select id="muInput" name="mu"><option value="0" selected>FedAvg (μ = 0)</option><option value="0.01">FedProx μ = 0.01 · gentle</option><option value="0.1">FedProx μ = 0.1 · moderate</option><option value="1">FedProx μ = 1 · strong</option></select></label>
<button class="primary" id="startTraining" type="submit">Start Training</button></form>
<div class="notice" id="trainMessage" aria-live="polite">Training runs on the prepared Kubernetes demo cluster. Results appear in the Results tab after export and evaluation.</div></article>
<article class="card"><h2>Simulate Self-Healing</h2>
<form id="faultForm" class="controls"><label>Bank to fail<select id="faultBank" name="bank"></select></label>
<label>Failure type<select id="faultKind" name="kind"><option value="kill" selected>Delete pod (Kubernetes recreates it)</option><option value="absence">Offline for __OUTAGE__ s (temporary outage)</option></select></label>
<button class="danger" id="simulateFailure" type="submit" disabled>Inject Failure</button></form>
<div class="notice" id="faultMessage" aria-live="polite">Start training to enable bank failure simulations.</div>
<div id="faultTracker" class="subtle">Deleted pod and replacement details will appear here.</div></article></section>
<section class="grid stats">
<article class="card"><div class="label">Kubernetes cluster</div><div class="value" id="cluster">—</div><div class="subtle" id="clusterNote">Checking cluster</div></article>
<article class="card"><div class="label">Ready pods</div><div class="value" id="podCount">—</div><div class="subtle">Coordinator + bank workers</div></article>
<article class="card"><div class="label">Training</div><div class="value" id="training">—</div><div class="subtle" id="trainingNote">Waiting for run data</div></article>
<article class="card"><div class="label">Current run</div><div class="value" id="runStatus">—</div><div class="subtle" id="runNote">No training run loaded</div></article>
</section>
<section class="grid cols">
<article class="card"><h2>Pods <span class="pill" id="podBadge">—</span></h2><div class="scroll"><table><thead><tr><th>Pod</th><th>Role</th><th>Phase / readiness</th><th>Restarts</th><th title="1000m = one CPU core; limit 1000m">CPU</th><th title="Limit 1024 MiB">Memory</th><th>Conditions / issue</th></tr></thead><tbody id="pods"></tbody></table></div></article>
<article class="card"><h2>Alerts &amp; Observations <span class="pill" id="alertCount">0</span></h2><div class="alerts" id="alerts"><div class="blank">No alerts loaded</div></div></article>
<article class="card"><h2>Deployments</h2><div class="scroll"><table><thead><tr><th>Name</th><th>Ready</th><th>Available</th><th>Image</th></tr></thead><tbody id="deployments"></tbody></table></div></article>
<article class="card"><h2>Kubernetes Events <span class="pill">latest 10 · times in SGT</span></h2><div class="scroll"><table><thead><tr><th>Time (SGT)</th><th>Type / reason</th><th>Object</th><th>Message</th></tr></thead><tbody id="kubeEvents"></tbody></table></div></article>
<article class="card wide"><h2>Training Progress <span class="pill" id="progressBadge">No run selected</span></h2><div class="grid"><canvas class="chart" id="roundChart" role="img" aria-label="Attempt duration by attempt"></canvas></div><div class="scroll"><table><thead><tr><th>Attempt</th><th>Version</th><th>Outcome</th><th>Duration</th><th>Accepted banks</th><th>Examples</th></tr></thead><tbody id="rounds"></tbody></table></div></article>
</section>
<!-- Raw diagnostics stay available for debugging, but closed by default so the demo screen stays readable. -->
<details class="card tech"><summary>Show technical details</summary><div class="grid techgrid">
<article class="wide"><h3>Services</h3><div id="services"></div></article>
<article><h3>Training event stream <span class="pill">events.jsonl</span></h3><pre class="logs" id="trainLog">Waiting for training events…</pre></article>
<article><h3>Pod logs <span class="pill">latest 80 lines</span></h3><pre class="logs" id="podLogs">Waiting for pod logs…</pre></article>
</div></details>
</section>
<section class="tab-panel" id="resultsPanel" role="tabpanel" hidden>
<article class="card" style="margin-bottom:16px"><div class="controls"><label>Run to inspect<select id="runSelect" class="runSelect" aria-label="Select a training run"></select></label><div><div class="label">Run outcome</div><div id="resultTitle" class="result-status">No run selected</div></div></div>
<div id="resultMessage" class="notice">Start a training run from Live monitor. Once it finishes, its exported evaluation will be available here.</div></article>
<div class="grid thirds" id="metrics"></div>
<article class="card" style="margin-top:16px"><h2>Model Quality Across Versions</h2><canvas class="chart" id="qualityChart" role="img" aria-label="Test average precision by model version"></canvas><div id="evaluationNote" class="subtle"></div></article>
<article class="card" style="margin-top:16px"><h2>Evaluation by Bank <span class="pill">test set</span></h2><div class="scroll"><table><thead><tr><th>Bank</th><th>Precision</th><th>Recall</th><th>F1</th><th>Average precision</th><th>ROC-AUC</th><th>False positive rate</th></tr></thead><tbody id="bankMetrics"></tbody></table></div></article>
</section>
</main>
<script>
const el=id=>document.getElementById(id), fmt=(n,d=1)=>Number.isFinite(Number(n))?Number(n).toFixed(d):"—";
function cell(v){return v===undefined||v===null||v===""?"—":String(v)}
function esc(s){return String(s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]))}
function row(values){return "<tr>"+values.map(v=>"<td>"+esc(cell(v))+"</td>").join("")+"</tr>"}
function badgeClass(s){return /completed|ready|running|committed|normal/i.test(s)?"ok":/deadline|warning|pending|late|stale|not ready|restart/i.test(s)?"warn":/failed|error|crash|backoff|insufficient|timeout/i.test(s)?"bad":"info"}
function chart(canvas,series,title,yLabel){const ctx=canvas.getContext("2d"),w=canvas.clientWidth,h=canvas.clientHeight,ratio=devicePixelRatio||1;canvas.width=w*ratio;canvas.height=h*ratio;ctx.scale(ratio,ratio);ctx.clearRect(0,0,w,h);ctx.fillStyle="#a1a1a1";ctx.font="12px Inter, Segoe UI, system-ui, sans-serif";ctx.fillText(title,8,14);if(!series.length){ctx.fillText("No data available",10,40);return}const all=series.flatMap(s=>s.points).filter(p=>Number.isFinite(p[0])&&Number.isFinite(p[1]));if(!all.length)return;const xmin=Math.min(...all.map(p=>p[0])),xmax=Math.max(...all.map(p=>p[0])),ymin=Math.min(0,...all.map(p=>p[1])),ymax=Math.max(...all.map(p=>p[1]));const pad={l:40,r:10,t:25,b:25},cw=w-pad.l-pad.r,ch=h-pad.t-pad.b;ctx.strokeStyle="#262626";ctx.fillStyle="#a1a1a1";ctx.lineWidth=1;for(let i=0;i<4;i++){let y=pad.t+ch*i/3;ctx.beginPath();ctx.moveTo(pad.l,y);ctx.lineTo(w-pad.r,y);ctx.stroke()}ctx.fillText(fmt(ymax-(ymax-ymin)*.0,2),3,pad.t+4);ctx.fillText(fmt(ymin,2),3,h-pad.b);const X=x=>pad.l+(x-xmin)/(xmax-xmin||1)*cw,Y=y=>pad.t+ch-(y-ymin)/(ymax-ymin||1)*ch;const colors=["#34d399","#38bdf8","#fbbf24","#f87171"];series.forEach((s,i)=>{ctx.strokeStyle=colors[i%colors.length];ctx.fillStyle=ctx.strokeStyle;ctx.lineWidth=2;ctx.beginPath();s.points.forEach((p,j)=>j?ctx.lineTo(X(p[0]),Y(p[1])):ctx.moveTo(X(p[0]),Y(p[1])));ctx.stroke();s.points.forEach(p=>{ctx.beginPath();ctx.arc(X(p[0]),Y(p[1]),3,0,7);ctx.fill()})})}
let activeTab="monitor";
function setTab(name){activeTab=name;document.querySelectorAll(".tab").forEach(b=>b.classList.toggle("active",b.dataset.tab===name)||b.setAttribute("aria-selected",b.dataset.tab===name));el("monitorPanel").hidden=name!=="monitor";el("resultsPanel").hidden=name!=="results";if(window.lastData)renderRun(window.lastData);history.replaceState(null,"",name==="results"?"#results":"#monitor")}
function formatEvent(event){const details=[];for(const key of ["attempt","version","bank","outcome","status","valid","required","committed_rounds"]){if(event[key]!==undefined&&event[key]!==null)details.push(`${key}=${Array.isArray(event[key])?event[key].join(","):event[key]}`)}if(event.accepted)details.push(`accepted=${event.accepted.join(",")}`);if(event.error)details.push(`error=${event.error}`);const elapsed=Number(event.elapsed_seconds);return `[${Number.isFinite(elapsed)?elapsed.toFixed(2)+"s":"time unknown"}] ${event.event||"event"}${details.length?" · "+details.join(" · "):""}`}
function renderRun(d){const run=d.run||{},s=run.summary||{},ev=run.evaluation||{},final=ev.final||{},options=d.runs||[],selected=run.run_id||"",rounds=run.rounds||[];
if(el("runSelect").dataset.current!==options.map(o=>o.id).join("|")){el("runSelect").innerHTML=options.map(o=>`<option value="${esc(o.id)}">${esc(o.label)}</option>`).join("");el("runSelect").dataset.current=options.map(o=>o.id).join("|")}el("runSelect").value=selected;
el("progressBadge").textContent=selected?`${selected}${d.active?" · LIVE":""}`:"No run selected";
el("resultTitle").textContent=s.status||"No run selected";
el("resultMessage").textContent=d.active?"Training is still running. The final test evaluation will appear here after the run exports and evaluates its checkpoints.":ev.final?`Results for ${selected}. Metrics are calculated from the run's saved checkpoints and evaluation dataset.`:"No exported evaluation is available for this run yet.";
const events=run.events||[];el("trainLog").textContent=events.length?events.slice(-80).map(formatEvent).join("\n"):d.active?"Waiting for events from the coordinator…":selected?"No training events recorded for this run.":"Start training to see coordinator events.";el("trainLog").scrollTop=el("trainLog").scrollHeight;
const metrics=[["Committed rounds",s.committed_rounds],["Attempts",s.attempts],["Successful round rate",s.successful_round_rate===undefined?null:fmt(s.successful_round_rate*100,1)+"%"],["Processed examples",s.processed_examples_returned===undefined?null:new Intl.NumberFormat().format(s.processed_examples_returned)],["Average precision",final.pr_auc_average_precision===undefined?null:fmt(final.pr_auc_average_precision,4)],["F1 score",final.f1===undefined?null:fmt(final.f1,4)],["ROC-AUC",final.roc_auc===undefined?null:fmt(final.roc_auc,4)],["Training time",s.training_seconds===undefined?null:fmt(s.training_seconds,1)+" s"],["Participation",Object.entries(s.participation||{}).map(([k,v])=>`${k}: ${v}`).join(" · ")] ];el("metrics").innerHTML=metrics.map(([k,v])=>`<div class="metric">${esc(cell(v))}<small>${esc(k)}</small></div>`).join("");
el("rounds").innerHTML=rounds.slice().reverse().map(r=>row([r.attempt,r.version,r.status,`${fmt(r.seconds,1)} s`,r.accepted,r.samples])).join("")||'<tr><td colspan="6" class="blank">Round records will appear when training starts.</td></tr>';
const curve=ev.curve||[];const bank=ev.per_bank||{};el("bankMetrics").innerHTML=Object.entries(bank).map(([name,m])=>row([name,fmt(m.precision,3),fmt(m.recall,3),fmt(m.f1,3),fmt(m.pr_auc_average_precision,3),fmt(m.roc_auc,3),fmt(m.false_positive_rate,4)])).join("")||'<tr><td colspan="7" class="blank">Evaluation appears after the run is exported and evaluated.</td></tr>';el("evaluationNote").textContent=ev.synthetic_data?"Synthetic dataset: software-check metrics only, not fraud-detection evidence.":ev.threshold_rule||"";
if(activeTab==="monitor")chart(el("roundChart"),[{points:rounds.map(r=>[Number(r.attempt),Number(r.seconds)])}],"Attempt duration (seconds)","seconds");if(activeTab==="results")chart(el("qualityChart"),[{points:curve.map(x=>[Number(x.version),Number(x.pr_auc_average_precision)])}],"Test average precision by model version","AP")}
function render(d){window.lastData=d;el("updated").textContent="";el("cluster").textContent=d.kubernetes?.available?"Connected":d.prepared?"Unavailable":"Not set up";el("clusterChip").className="status "+(d.kubernetes?.available?"ok":d.prepared?"bad":"warn");el("clusterChipText").textContent=d.kubernetes?.available?"Cluster connected":d.prepared?"Cluster unavailable":"Setup required";el("clusterNote").textContent=el("clusterNote").title=d.kubernetes?.error?"Start Docker Desktop, then wait for the cluster to reconnect. "+d.kubernetes.error:(d.prepared?"Context kind-bank-fl-demo / namespace bank-fl":"Run bank-fl demo setup first");const pods=d.kubernetes?.pods||[];const ready=pods.filter(p=>p.ready).length;el("podCount").textContent=pods.length?`${ready} / ${pods.length}`:"—";el("podBadge").textContent=`${ready} ready`;el("pods").innerHTML=pods.length?pods.map(p=>row([p.name,p.role,p.phase+(p.ready?" · Ready":" · Not Ready"),p.restarts,p.cpu_millicores==null?null:fmt(p.cpu_millicores,0)+"m",p.memory_mib==null?null:fmt(p.memory_mib,0)+" MiB",p.issues.join("; ")])).join(""):'<tr><td colspan="7" class="blank">No pods returned</td></tr>';
el("deployments").innerHTML=(d.kubernetes?.deployments||[]).map(x=>row([x.name,`${x.ready}/${x.desired}`,x.available,x.images.join(", ")])).join("")||'<tr><td colspan="4" class="blank">No deployments found</td></tr>';
el("services").innerHTML=(d.kubernetes?.services||[]).map(s=>`<div class="service"><b>${esc(s.name)}</b> <span class="muted">${esc(s.cluster_ip)} · ${esc(s.ports.join(", "))}</span></div>`).join("")||'<div class="blank">No services found</div>';
el("kubeEvents").innerHTML=(d.kubernetes?.events||[]).slice(0,10).map(e=>row([e.time,`${e.type} / ${e.reason}`,e.object,e.message])).join("")||'<tr><td colspan="4" class="blank">No recent events</td></tr>';
el("alerts").innerHTML=d.alerts.length?d.alerts.map(a=>`<div class="alert ${a.level}"><b>${esc(a.title)}</b><div title="${esc(a.message)}">${esc(a.message)}</div></div>`).join(""):'<div class="alert">No issues detected in the latest snapshot.</div>';el("alertCount").textContent=d.alerts.length;
const run=d.run||{},s=run.summary||{};el("training").textContent=d.active?"RUNNING":s.status||"IDLE";el("trainingNote").textContent=d.active?`${s.committed_rounds||0} committed · attempt ${run.latest_attempt||0}`:`${s.committed_rounds||0} committed rounds`;el("runStatus").textContent=s.status||"—";el("runNote").textContent=s.attempts?`${s.committed_rounds} / ${run.config?.rounds||"?"} rounds · ${fmt(s.successful_round_rate*100,0)}% success rate`:"No summary yet";
const canStart=d.prepared&&d.kubernetes?.available;el("startTraining").disabled=d.active||!canStart;el("trainState").textContent=d.active?"Training in progress":!d.prepared?"Setup required":!d.kubernetes?.available?"Cluster unavailable":"Ready to train";const logLines=(d.training_log||"").trim().split("\n");const lastLog=logLines[logLines.length-1]||"";el("trainMessage").textContent=d.active?`Run ${run.run_id||"starting"} is active. Follow live progress here; open Results after it finishes.`:s.status?`Latest run: ${s.status}. Open Results to inspect its exported evaluation.`:!d.prepared?"Run `uv run bank-fl demo setup` before starting a training run.":!d.kubernetes?.available?`Kubernetes is unavailable: ${d.kubernetes?.error||"cluster connection failed"}`:lastLog||"Choose rounds and deadline, then start. Training runs through Flower on the Kubernetes demo cluster.";
hero(d);const fault=d.fault||{},record=fault.record;el("simulateFailure").disabled=!fault.available||fault.requested;el("faultMessage").textContent=record?.status==="ready"?`Failure ${fault.count}: ${record.bank} recovered and became Ready in ${fmt(record.fault_to_ready_seconds,1)} s${record.kind==="absence"?" (including "+fmt(record.duration,0)+" s offline)":""}. You can inject another failure.`:record?.status==="timed_out"?"Replacement did not become Ready before the recovery timeout.":record?.status==="failed"?`Failure simulation failed: ${record.error||"unknown error"}`:fault.requested?"Failure injected; tracking pod replacement…":fault.available?"Choose a bank and a failure type. Training continues with the other banks; the bank rejoins when its pod is back.":d.active?"Training is starting; wait for the coordinator before simulating a failure.":"Start training to enable bank failure simulations.";el("faultTracker").innerHTML=record?`<div>Failure ${fault.count} (${record.kind==="absence"?"temporary outage":"pod deleted"}) · Bank: <b>${esc(record.bank)}</b> · Status: <b>${esc(record.status||"unknown")}</b></div><div>Deleted pod: <code>${esc(record.deleted_pod||"waiting")}</code></div><div>Replacement pod: <code>${esc(record.replacement_pod||"waiting for Kubernetes")}</code></div><div>Replacement UID: <code>${esc(record.replacement_uid||"—")}</code></div>`:"Deleted pod and replacement details will appear here.";
renderRun(d);el("podLogs").textContent=d.kubernetes?.logs||d.kubernetes?.logs_error||"No pod logs available."}
let busy=false,refreshQueued=false,selectionVersion=0;async function refresh(){if(busy){refreshQueued=true;return}busy=true;const version=selectionVersion;try{const q=el("runSelect").value;const r=await fetch("/api/dashboard"+(q?"?run="+encodeURIComponent(q):""),{cache:"no-store"});const d=await r.json();if(!r.ok)throw new Error(d.error||"Dashboard refresh failed");if(version===selectionVersion)render(d)}catch(e){if(version===selectionVersion)el("updated").textContent=" · Dashboard update failed: "+e.message}finally{busy=false;if(refreshQueued){refreshQueued=false;refresh()}}}
document.querySelectorAll(".tab").forEach(b=>b.addEventListener("click",()=>setTab(b.dataset.tab)));el("runSelect").addEventListener("change",()=>{selectionVersion++;refresh()});
el("trainForm").addEventListener("submit",async event=>{event.preventDefault();const button=el("startTraining");button.disabled=true;selectionVersion++;el("runSelect").value="";render({...window.lastData,active:true,runs:[],run:{run_id:null,summary:{},evaluation:{},rounds:[],events:[],config:{},latest_attempt:0}});el("trainMessage").textContent="Starting the Kubernetes training run…";try{const response=await fetch("/api/train",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({rounds:Number(el("roundInput").value),deadline:Number(el("deadlineInput").value),mu:Number(el("muInput").value)})});const result=await response.json();if(!response.ok)throw new Error(result.error||"Unable to start training");el("trainMessage").textContent=`Training started (process ${result.pid}). Live progress will appear here.`;await refresh()}catch(error){el("trainMessage").textContent=error.message;button.disabled=false;await refresh()}});
// Failing a bank is disruptive: the first click arms the button, a second click within 4 s confirms.
let disarm;el("faultForm").addEventListener("submit",async event=>{event.preventDefault();const button=el("simulateFailure");
if(!button.classList.contains("armed")){button.classList.add("armed");button.textContent=`Confirm: ${el("faultKind").value==="kill"?"Delete":"Take Offline"} ${el("faultBank").value}`;clearTimeout(disarm);disarm=setTimeout(()=>{button.classList.remove("armed");button.textContent="Inject Failure"},4000);return}
clearTimeout(disarm);button.classList.remove("armed");button.textContent="Inject Failure";button.disabled=true;el("faultMessage").textContent=el("faultKind").value==="kill"?"Deleting the pod and waiting for Kubernetes to recreate it…":"Taking the bank offline for __OUTAGE__ s, then waiting for its pod to come back…";try{const response=await fetch("/api/fail",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({bank:el("faultBank").value,kind:el("faultKind").value})});const result=await response.json();if(!response.ok)throw new Error(result.error||"Unable to simulate the failure");el("faultMessage").textContent=result.record.recovery_censored?"Replacement was not observed before the timeout. Check the pod status and event stream.":`${result.bank} recovered and became Ready in ${fmt(result.record.fault_to_ready_seconds,1)} seconds.`;await refresh()}catch(error){el("faultMessage").textContent=error.message;button.disabled=false;await refresh()}});
// Federation visualiser: bank states come from pod readiness and the coordinator's event log.
const NS="http://www.w3.org/2000/svg",NBANKS=__BANKS__,BANKS=Array.from({length:NBANKS},(_,i)=>"bank-"+(i+1)),ROW=120,GAP=14;
const ICONS={training:'<path d="M21 12a9 9 0 1 1-6.22-8.56"/>',sent:'<path d="M20 6 9 17l-5-5"/>',waiting:'<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',down:'<circle cx="12" cy="12" r="9"/><path d="m15 9-6 6M9 9l6 6"/>',idle:'<circle cx="12" cy="12" r="3"/>'};
const ico=(p,cls="")=>`<svg class="ico ${cls}" viewBox="0 0 24 24" aria-hidden="true">${p}</svg>`,bankName=b=>"Bank "+b.split("-")[1];
const hxSeen={run:undefined,n:0},hxMotion=!matchMedia("(prefers-reduced-motion: reduce)").matches;
function hxInit(){el("faultBank").innerHTML=BANKS.map((b,i)=>`<option${i===NBANKS-1?" selected":""}>${b}</option>`).join("");el("hxBanks").innerHTML=BANKS.map(b=>`<div class="bank s-idle" id="hx-${b}"><div class="bank-top"><span class="bank-name">${ico('<path d="M3 21h18M5 21v-9M19 21v-9M9.5 21v-9M14.5 21v-9M2 10l10-7 10 7z"/>')}${bankName(b)}</span><span class="state">${Object.entries(ICONS).map(([k,p])=>ico(p,"st st-"+k)).join("")}<span class="st-label">Idle</span></span></div>
<div class="bank-sub">${ico('<rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>')}<span class="hx-data">Private data never leaves this bank</span></div><div class="strip" aria-hidden="true"></div><div class="bank-foot"><span class="hx-used">No rounds yet</span><span class="hx-pct"></span></div></div>`).join("");
el("hxLanes").innerHTML=BANKS.map(b=>`<svg class="lane s-idle" id="hxlane-${b}"><path class="track" id="hxl-${b}"/><circle class="port" r="3.5"/><circle class="port" r="3.5"/></svg>`).join("");
hxLayout();if(window.ResizeObserver)new ResizeObserver(hxLayout).observe(el("hxLanes"))}
// Each lane runs from its bank card to the coordinator, which sits level with the middle of the banks.
function hxLayout(){const w=el("hxLanes").clientWidth;BANKS.forEach((b,i)=>{const y0=ROW/2,y1=y0+((NBANKS-1)/2-i)*(ROW+GAP),ports=el("hxlane-"+b).querySelectorAll(".port");
el("hxl-"+b).setAttribute("d",`M0 ${y0} C${w*.55} ${y0} ${w*.45} ${y1} ${w} ${y1}`);ports[0].setAttribute("cx",0);ports[0].setAttribute("cy",y0);ports[1].setAttribute("cx",w);ports[1].setAttribute("cy",y1)})}
function hxPulse(){const c=el("hxCenter");c.classList.remove("pulse");void c.offsetWidth;c.classList.add("pulse")}
function hxFly(bank,inbound,color,tag){const p=el("hxl-"+bank),svg=p.ownerSVGElement;if(!hxMotion||!svg.getClientRects().length)return;const L=p.getTotalLength(),c=document.createElementNS(NS,"circle"),t0=performance.now(),dur=1000;c.setAttribute("r",5);c.setAttribute("fill",color);svg.append(c);
function step(t){const k=Math.min(1,(t-t0)/dur),e=k<.5?2*k*k:1-(-2*k+2)**2/2,pt=p.getPointAtLength((inbound?e:1-e)*L);c.setAttribute("cx",pt.x);c.setAttribute("cy",pt.y);if(k<1)return requestAnimationFrame(step);c.remove();
if(inbound&&tag){const s=document.createElementNS(NS,"text");s.setAttribute("class","hxtag");s.setAttribute("x",pt.x-8);s.setAttribute("y",pt.y-10);s.textContent=tag;svg.append(s);setTimeout(()=>s.remove(),1900)}}requestAnimationFrame(step)}
function hero(d){const run=d.run||{},act=d.active,starting=act&&!!run.summary?.status,ev=starting?[]:run.events||[],cfg=starting?{}:run.config||{},pods=d.kubernetes?.pods||[],k8s=d.kubernetes?.available;
const pending={},sent=[],rejoining={},contrib={},byVersion=[];let version=0;
for(const e of ev){if(e.event==="attempt_started")sent.length=0;else if(e.event==="dispatched")pending[e.bank]=e.request_id;
else if(e.event==="reply"){if(e.request_id&&pending[e.bank]===e.request_id)delete pending[e.bank];if(e.outcome==="accepted"){if(!sent.includes(e.bank))sent.push(e.bank);rejoining[e.bank]=false}else if(e.outcome==="client_error")rejoining[e.bank]=true}
else if(e.event==="committed"){version=e.version;byVersion[e.version]=new Set(e.accepted||[]);(e.accepted||[]).forEach(b=>contrib[b]=(contrib[b]||0)+1)}}
const live=pods.filter(p=>!p.terminating),up=role=>live.some(p=>p.role===role&&p.ready),f=act&&!starting?d.fault?.record:null;
const parts=run["run.json"]?.dataset?.partitions?.train||{},total=cfg.rounds||version,needed=cfg.quorum||Math.floor(NBANKS/2)+1,nb=cfg.banks||NBANKS,states={};
for(const b of BANKS){const exists=live.some(p=>p.role===b),lost=f?.bank===b&&!ev.some(e=>e.event==="dispatched"&&e.bank===b&&e.unix_time>f.unix_time);let s,label;
if(!k8s){s="idle";label="Offline"}else if(!up(b)){s="down";label=exists?"Restarting":"Pod down"}else if(lost){s="down";label="Recovering"}
else if(act&&pending[b]){s="training";label="Training"}else if(act&&sent.includes(b)){s="sent";label="Update sent"}
else if(act){s="waiting";label=rejoining[b]?"Rejoining":"Waiting"}else{s="idle";label="Idle"}states[b]=s;
const card=el("hx-"+b),n=parts[b]?.samples,used=contrib[b]||0,cells=[];card.className="bank s-"+s;card.querySelector(".st-label").textContent=label;
card.querySelector(".hx-data").textContent=n?`${new Intl.NumberFormat().format(n)} private transactions · never shared`:"Private data never leaves this bank";
for(let v=1;v<=Math.min(Math.max(total,version),120);v++)cells.push(`<i class="${byVersion[v]?(byVersion[v].has(b)?"on":"off"):""}"></i>`);card.querySelector(".strip").innerHTML=cells.join("");
card.querySelector(".hx-used").textContent=version?`Used in ${used} of ${version} rounds`:"No rounds yet";card.querySelector(".hx-pct").textContent=version?Math.round(used/version*100)+"%":"";
el("hxlane-"+b).setAttribute("class","lane s-"+s)}
const mu=act&&cfg.mu===undefined?Number(el("muInput").value):cfg.mu;el("hxAlgo").textContent=mu>0?`FedProx μ=${mu}`:"FedAvg";const center=el("hxCenter"),round=Math.min(version+1,total||version+1);center.className="coord "+(k8s&&!up("coordinator")?"core-down":act?"core-live":"core-idle")+(center.classList.contains("pulse")?" pulse":"");
el("hxRing").style.strokeDashoffset=326.73*(1-(total?Math.min(1,version/total):0));el("hxVer").textContent="v"+version;el("hxRound").textContent=total?`${version} of ${total} rounds`:"No rounds yet";
// Rounds commit almost as soon as the quorum arrives, so between arrivals show what the last round used.
const live_=act&&sent.length,got=live_?sent:[...(byVersion[version]||[])].sort();el("hxQLabel").textContent=live_?`Round ${round} updates`:version?`Round ${version} averaged`:"Updates per round";el("hxQNeed").textContent=`quorum ${needed} of ${nb}`;el("hxSlots").innerHTML=Array.from({length:nb},(_,i)=>got[i]?`<span class="slot on">${bankName(got[i])}</span>`:`<span class="slot">${i<needed?"needed":"optional"}</span>`).join("");
el("hxTitle").textContent=!k8s?"Kubernetes cluster unavailable":starting?"Starting training…":act?`Training · round ${round}${total?" of "+total:""}`:run.summary?.status?`Last run ${run.summary.status.replace(/_/g," ")} · ${version} rounds`:"Ready to train";
const names=list=>list.length>1?list.slice(0,-1).map(bankName).join(", ")+" and "+bankName(list.at(-1)):bankName(list[0]),tr=BANKS.filter(b=>states[b]==="training"),dn=BANKS.filter(b=>states[b]==="down");
el("hxStory").textContent=!k8s?"Start Docker Desktop so the dashboard can reach the Kubernetes cluster.":starting?"Starting Flower and connecting the banks…":act?[tr.length?`${names(tr)} ${tr.length>1?"are":"is"} training on ${tr.length>1?"their":"its"} own data.`:"",dn.length?`${names(dn)} ${dn.length>1?"are":"is"} down, so the other banks carry on without ${dn.length>1?"them":"it"}.`:"",`Once ${needed} updates arrive, the coordinator waits a few seconds for the rest, then averages them and sends the new global model back to every bank.`].filter(Boolean).join(" "):run.summary?.status?`The last run committed ${version} rounds. Each bank trained only on its own data; only model updates reached the coordinator.`:"Press Start Training. Each bank trains on its own data and sends only model updates to the coordinator, which averages them into one shared model.";
// Animate only events that arrived since the previous refresh; never replay an old run.
if(hxSeen.run!==run.run_id||ev.length<hxSeen.n){hxSeen.run=run.run_id;hxSeen.n=ev.length;return}
const fresh=ev.slice(hxSeen.n);hxSeen.n=ev.length;let t=0,arrive=0;
for(const e of fresh){if(e.event==="reply"&&e.bank&&e.outcome!=="client_error"){const ok=e.outcome==="accepted",at=t;setTimeout(()=>hxFly(e.bank,true,ok?"#38bdf8":"#f87171",ok?null:e.outcome.replace(/_/g," ")+" ✕"),at);arrive=Math.max(arrive,at+1000);t+=160}
else if(e.event==="committed"){t=Math.max(t,arrive);setTimeout(hxPulse,t);t+=450}else if(e.event==="dispatched"&&e.bank){const at=t;setTimeout(()=>hxFly(e.bank,false,"#fafafa"),at);t+=140}}}
hxInit();
if(location.hash==="#results")setTab("results");refresh();setInterval(refresh,2000);
</script></body></html>"""


def _read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):  # missing, or caught mid-write
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


def _algorithm(path):
    try:
        run = json.loads((path / "run.json").read_text(encoding="utf-8"))
        mu = run["config"].get("mu", 0)
        skew = run["dataset"].get("skew", 1.0)
        label = f" · FedProx μ={mu:g}" if mu > 0 else " · FedAvg"
        return label + (f" · skew {skew:g}" if skew != 1 else "")
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return ""  # live run not exported yet, or an unreadable run.json


def launch_training(rounds, deadline, mu):
    from app.config import RunConfig

    config = RunConfig(rounds=rounds, deadline=deadline, mu=mu)
    if not (demo.ROOT / "settings.json").is_file():
        raise ValueError("Run `uv run bank-fl demo setup` before starting training.")
    with TRAINING_LOCK:
        if _training_active():
            raise RuntimeError("Training is already running.")
        demo.ROOT.mkdir(exist_ok=True)
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
                    "--mu",
                    str(config.mu),
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
        demo.save(TRAINING_STATE.name, {"pid": process.pid, "created": created})
    return {"status": "starting", "pid": process.pid}


def _kubectl(*args):
    result = subprocess.run(
        [*demo.KUBECTL, "-n", "bank-fl", *args],
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
            if status.get("phase") == "Succeeded":
                continue  # A finished CronJob run, not a workload; failed runs still show.
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
            spec = item.get("spec", {})
            deployments.append(
                {
                    "name": name,
                    "desired": spec.get("replicas", 1),
                    "ready": status.get("readyReplicas", 0),
                    "available": status.get("availableReplicas", 0),
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
    # Live CPU/memory from metrics-server; optional, and a brand-new pod has none yet.
    try:
        usage = {row["pod"]: row for row in pod_usage(_kubectl)}
    except (OSError, RuntimeError, subprocess.TimeoutExpired, ValueError, KeyError, TypeError):
        usage = {}
    for pod in pods:
        measured = usage.get(pod["name"], {})
        pod["cpu_millicores"] = measured.get("cpu_millicores")
        pod["memory_mib"] = measured.get("memory_mib")
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


def simulate_self_healing(bank, kind="kill"):
    demo.check_fault(bank, kind)
    if not demo.active():
        raise RuntimeError("Start a training run before simulating self-healing.")
    # Raises ValueError while the previous failure is still recovering.
    demo.fail(bank, kind, demo.OUTAGE_SECONDS)
    latest = _read_json(demo.ROOT / "latest.json") or {}
    output = latest.get("output")
    records = demo.fault_records(Path(output)) if isinstance(output, str) else []
    record = _read_json(records[-1]) if records else None
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
    # While a run is live its files are still in the coordinator pod, not exported yet.
    remote = (_read_remote_run(latest) if demo_active else None) or {}
    remote_files = remote.get("files", {})
    if demo_active and not active_id:
        active_id = remote.get("run_id")
        if active_id and RUN_ID_PATTERN.fullmatch(active_id):
            latest["run_id"] = active_id
            run_paths.setdefault(active_id, Path(latest.get("output", RESULTS)) / active_id)
        else:
            active_id = None
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
            "label": f"{item}{_algorithm(run_paths[item])}{' · live' if item == active_id else ''}",
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
    no_cluster = {
        "available": False,
        "pods": [],
        "deployments": [],
        "services": [],
        "events": [],
        "logs": "",
    }
    try:
        kubernetes = _kubernetes() if prepared else no_cluster
    except (OSError, RuntimeError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        kubernetes = {**no_cluster, "error": str(exc)}
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
        "fault": {
            **_fault_status(latest),
            "available": demo_active and kubernetes.get("available", False),
        },
        "training_log": _read_training_log(),
        "runs": runs,
        "run": run,
        "kubernetes": kubernetes,
        "alerts": alerts,
    }


def _fault_status(latest):
    output = latest.get("output")
    if not isinstance(output, str):
        return {"requested": False, "record": None, "count": 0}
    records = demo.fault_records(Path(output))
    # "requested" means a kill is still in progress, which disables the button until it ends.
    return {
        "requested": bool(records) and not demo.fault_finished(records[-1]),
        "record": _read_json(records[-1]) if records else None,
        "count": len(records),
    }


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
            # The page is drawn for the bank count the demo cluster was set up with.
            page = PAGE.replace("__BANKS__", str(demo.banks()))
            body = page.replace("__OUTAGE__", f"{demo.OUTAGE_SECONDS:g}").encode("utf-8")
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
        endpoint = urlsplit(self.path).path
        if endpoint not in {"/api/train", "/api/fail"}:
            self.send_error(404)
            return
        if not _valid_dashboard_origin(self):
            self.send_error(403, "Dashboard actions must come from this local dashboard.")
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
            if endpoint == "/api/train":
                rounds = body.get("rounds")
                deadline = body.get("deadline")
                mu = body.get("mu", 0.0)
                if type(rounds) is not int or any(
                    isinstance(value, bool) or not isinstance(value, (int, float))
                    for value in (deadline, mu)
                ):
                    raise ValueError("Rounds must be an integer; deadline and mu must be numbers.")
                result = launch_training(rounds, deadline, mu)
                status = 202
            else:
                result = simulate_self_healing(body.get("bank"), body.get("kind", "kill"))
                status = 200
            payload = json.dumps(result).encode("utf-8")
        except (ValueError, TypeError, OverflowError, json.JSONDecodeError) as exc:
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
