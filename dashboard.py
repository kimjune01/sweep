#!/usr/bin/env python3
"""Sweep pipeline dashboard. Reads ~/.sweep state, serves live HTML on port 8321."""

import json, glob, os, html as htmlmod
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime
from pathlib import Path

PORT = 8321
SWEEP = os.path.expanduser("~/.sweep")

def rj(p):
    try:
        with open(p) as f: return json.load(f)
    except: return {}

def rjl(p):
    out = []
    try:
        with open(p) as f:
            for l in f:
                l = l.strip()
                if l:
                    try: out.append(json.loads(l))
                    except: pass
    except: pass
    return out

def rf(p):
    try:
        with open(p) as f: return f.read()
    except: return ""

def lvw(entries):
    p = {}
    for e in entries:
        k = e.get("key")
        if k: p[k] = e
    return p

HYPS = [
    ("H0", "Issue-first PRs merge at higher rate than unsolicited"),
    ("H1", "Review schema conformance predicts merge outcome"),
    ("H2", "Standing is a gate that supersedes technical quality"),
    ("H3", "Drip pacing prevents standing damage"),
    ("H4", "Framing affects outcome independently of code quality"),
    ("H5", "Maintainers optimize for review efficiency, not correctness"),
    ("H6", "The pipeline produces higher merge rates than ad-hoc"),
]

READY = [
    ("aider", "#3702", "2 lines", "Python", "priority label"),
    ("compiler", "#1091", "2 lines", "Go", "exact code ref"),
    ("compiler", "#1139", "10-15 lines", "Go", "pre-approved"),
    ("compiler", "#1096", "2-5 lines", "Go", "scope boundary"),
    ("ruff", "#16519", "~5 lines", "Rust", "collaborator endorsed"),
    ("mypy", "#8603", "~20 lines", "Python", "maintainer invited"),
    ("gemini-cli", "#25459", "~30 lines", "TypeScript", "reviewer gave changes"),
    ("mvdan/sh", "#813", "~35 lines", "Go", "8 merges/3mo"),
    ("marimo", "#4153", "medium", "TS+Py", "WIP blueprint"),
]

BLOCKED = [
    ("gemini-cli", "#25693", "competing PR #25728"),
    ("gemini-cli", "#25689", "competing PR #25729"),
    ("node", "#62838", "competing PR #63162"),
    ("TypeScript", "#30408", "must target TypeScript-go"),
]

SC = {
    "ready":"#22c55e","merged":"#22c55e","triaged":"#3b82f6",
    "in_progress":"#06b6d4","pending_schema":"#eab308",
    "pending_review":"#f59e0b","dormant":"#6b7280",
    "evicted":"#ef4444","monitoring":"#a855f7",
}

def badge(s):
    c = SC.get(s, "#6b7280")
    return f'<span style="background:{c};color:#fff;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600">{htmlmod.escape(s)}</span>'

def gather():
    repos = rj(f"{SWEEP}/repos.json").get("repos", [])
    retro_params = {}
    for f in glob.glob(f"{SWEEP}/retro/*.jsonl"):
        k = os.path.basename(f).replace(".jsonl","")
        retro_params[k] = lvw(rjl(f))
    retro_graphs = {}
    drip = {}
    triage = {}
    rd = f"{SWEEP}/repos"
    if os.path.isdir(rd):
        for d in os.listdir(rd):
            rg = rf(f"{rd}/{d}/RETRO_GRAPH.md")
            if rg: retro_graphs[d] = rg
            tg = rf(f"{rd}/{d}/TRIAGE_GRAPH.md")
            if tg: triage[d] = tg
    for f in glob.glob(f"{SWEEP}/drip-queue/*.jsonl"):
        k = os.path.basename(f).replace(".jsonl","")
        drip[k] = rjl(f)
    candidates = rjl(f"{SWEEP}/actionable/candidates.jsonl")
    return repos, retro_params, retro_graphs, triage, drip, candidates

def count_evidence(graphs):
    """Count FOR/AGAINST across all retro graphs for each hypothesis."""
    counts = {h: {"for": 0, "against": 0, "neutral": 0} for h, _ in HYPS}
    for repo, content in graphs.items():
        for line in content.splitlines():
            lo = line.lower()
            for hid, _ in HYPS:
                if hid.lower() in lo:
                    if "| for" in lo or "FOR |" in line:
                        counts[hid]["for"] += 1
                    elif "| against" in lo or "AGAINST |" in line:
                        counts[hid]["against"] += 1
                    elif "| neutral" in lo or "NEUTRAL |" in line:
                        counts[hid]["neutral"] += 1
    return counts

def render(repos, rp, rg, triage, drip, cands):
    now = datetime.now().strftime("%H:%M:%S")
    active = [r for r in repos if r["status"] not in ("evicted","dormant")]
    evicted = [r for r in repos if r["status"] == "evicted"]

    ev = count_evidence(rg)

    def hyp_bar(hid):
        f, a = ev[hid]["for"], ev[hid]["against"]
        t = f + a or 1
        pct = int(f/t*100)
        return f"""<div style="display:flex;align-items:center;gap:8px;margin-top:6px">
            <div style="flex:1;height:4px;background:#262626;border-radius:2px;overflow:hidden">
                <div style="width:{pct}%;height:100%;background:{'#22c55e' if pct>60 else '#eab308' if pct>40 else '#ef4444'}"></div>
            </div>
            <span style="font-size:10px;color:#737373">{f}↑ {a}↓</span>
        </div>"""

    hyps_html = "".join(f"""<div style="background:#1a1a1a;border-radius:6px;padding:12px;border:1px solid #262626">
        <span style="font-weight:700;color:#a855f7">{hid}</span>
        <div style="font-size:12px;color:#a3a3a3;margin-top:4px">{desc}</div>
        {hyp_bar(hid)}
        <div style="font-size:10px;margin-top:4px;color:#525252">UNCONFIRMED</div>
    </div>""" for hid, desc in HYPS)

    ready_html = "".join(f'<tr style="border-left:3px solid #22c55e"><td>{r}</td><td>{i}</td><td>{f}</td><td>{l}</td><td style="color:#737373">{s}</td></tr>' for r,i,f,l,s in READY)

    blocked_html = "".join(f'<tr style="border-left:3px solid #ef4444"><td>{r}</td><td>{i}</td><td style="color:#737373">{b}</td></tr>' for r,i,b in BLOCKED)

    repo_html = "".join(f"""<tr>
        <td>{htmlmod.escape(r['repo'])}</td>
        <td>{badge(r['status'])}</td>
        <td style="font-size:11px;color:#525252">{r.get('added','')}</td>
        <td style="font-size:11px;color:#525252">{htmlmod.escape(r.get('cooldown_until','') or r.get('reason',''))}</td>
    </tr>""" for r in repos if r['status'] != 'evicted')

    evicted_html = "".join(f'<tr><td style="color:#525252">{htmlmod.escape(r["repo"])}</td><td style="color:#525252;font-size:11px">{htmlmod.escape(r.get("reason",""))}</td></tr>' for r in evicted)

    retro_html = "".join(f"""<div style="background:#1a1a1a;border-radius:6px;padding:10px;border:1px solid #262626">
        <div style="font-weight:600;font-size:12px">{htmlmod.escape(repo)}</div>
        <div style="font-size:11px;color:#737373;margin-top:4px">{len(content.splitlines())} lines</div>
        <div style="font-size:10px;color:#a855f7;margin-top:4px">{'prior art + pre-reg' if 'Prior art' in content or 'Pre-reg' in content else 'own outcomes' if 'MERGED' in content or 'CLOSED' in content else 'building...'}</div>
    </div>""" for repo, content in sorted(rg.items()))

    rp_html = "".join(f"""<tr>
        <td style="font-size:11px">{htmlmod.escape(repo)}</td>
        <td style="font-size:11px;color:#737373">{', '.join(f'{k}' for k in list(params.keys())[:4])}</td>
    </tr>""" for repo, params in sorted(rp.items()))

    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>Sweep</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'SF Mono','Fira Code',monospace;background:#0a0a0a;color:#e5e5e5;padding:20px}}
h2{{font-size:13px;color:#a3a3a3;margin:20px 0 10px;text-transform:uppercase;letter-spacing:2px}}
table{{width:100%;border-collapse:collapse}}
th{{text-align:left;padding:6px 10px;font-size:10px;color:#525252;text-transform:uppercase;letter-spacing:1px;border-bottom:1px solid #262626}}
td{{padding:6px 10px;font-size:12px;border-bottom:1px solid #1a1a1a}}
tr:hover{{background:#141414}}
.box{{background:#141414;border-radius:8px;border:1px solid #262626;padding:14px;margin-bottom:14px}}
.hdr{{display:flex;gap:32px;align-items:baseline;padding:14px;background:#141414;border-radius:8px;border:1px solid #262626;margin-bottom:14px}}
.st{{text-align:center}}.st .n{{font-size:32px;font-weight:700}}.st .l{{font-size:10px;color:#525252;text-transform:uppercase;letter-spacing:1px}}
.g{{color:#22c55e}}.b{{color:#3b82f6}}.y{{color:#eab308}}.c{{color:#06b6d4}}.p{{color:#a855f7}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:10px}}
.two{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}
@media(max-width:800px){{.two{{grid-template-columns:1fr}}.hdr{{flex-wrap:wrap}}}}
</style></head><body>

<div class="hdr">
<div class="st"><div class="n g">2</div><div class="l">merged</div></div>
<div class="st"><div class="n">29</div><div class="l">submitted</div></div>
<div class="st"><div class="n y">6%</div><div class="l">rate</div></div>
<div class="st"><div class="n c">{len(READY)}</div><div class="l">ready</div></div>
<div class="st"><div class="n b">{len(active)}</div><div class="l">active</div></div>
<div class="st"><div class="n p">{len(rg)}</div><div class="l">retro graphs</div></div>
</div>

<h2>Meta-Hypothesis Graph</h2>
<div class="box"><div class="grid">{hyps_html}</div></div>

<h2>Ready Queue</h2>
<div class="box"><table>
<tr><th>Repo</th><th>Issue</th><th>Fix</th><th>Lang</th><th>Signal</th></tr>
{ready_html}
</table></div>

<h2>Blocked</h2>
<div class="box"><table>
<tr><th>Repo</th><th>Issue</th><th>Reason</th></tr>
{blocked_html}
</table></div>

<div class="two">
<div>
<h2>Repos</h2>
<div class="box"><table>
<tr><th>Repo</th><th>Status</th><th>Added</th><th>Notes</th></tr>
{repo_html}
</table></div>
</div>
<div>
<h2>Evicted</h2>
<div class="box"><table><tr><th>Repo</th><th>Reason</th></tr>{evicted_html or '<tr><td colspan=2 style="color:#525252">none</td></tr>'}</table></div>
<h2>Retro Params</h2>
<div class="box"><table><tr><th>Repo</th><th>Keys</th></tr>{rp_html}</table></div>
</div>
</div>

<h2>Retro Graphs ({len(rg)} repos)</h2>
<div class="box"><div class="grid">{retro_html or '<div style="color:#525252">agents building...</div>'}</div></div>

<div style="font-size:10px;color:#333;text-align:right;margin-top:12px">{now} &middot; refreshes every 10s</div>
<script>setInterval(()=>fetch('/').then(r=>r.text()).then(h=>{{let d=new DOMParser().parseFromString(h,'text/html');document.body.innerHTML=d.body.innerHTML}}),10000)</script>
</body></html>"""

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        data = gather()
        if self.path == "/api":
            self.send_response(200); self.send_header("Content-Type","application/json"); self.end_headers()
            repos, rp, rg, triage, drip, cands = data
            self.wfile.write(json.dumps({"repos":[r for r in repos],"retro_graphs":list(rg.keys()),"ready":len(READY)},indent=2).encode())
        else:
            self.send_response(200); self.send_header("Content-Type","text/html"); self.end_headers()
            self.wfile.write(render(*data).encode())
    def log_message(self,*a): pass

if __name__=="__main__":
    import subprocess
    try:
        pid = subprocess.check_output(["lsof","-ti",f":{PORT}"],text=True).strip()
        if pid:
            for p in pid.split("\n"): os.kill(int(p),9)
    except: pass
    print(f"Dashboard: http://localhost:{PORT}")
    HTTPServer(("127.0.0.1",PORT),H).serve_forever()
