#!/usr/bin/env python3
"""Render results/results.json as a static leaderboard page (results/index.html).

Self-contained: one HTML file, no build step, no third-party JS. Geist from Google
Fonts, monochrome surfaces, tabular numerals, light and dark from the OS preference
with no visible switcher, per the Vercel design guidelines.
"""
import argparse
import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
W, H = 720, 380
PAD = {"l": 56, "r": 24, "t": 16, "b": 44}


def fmt(x, spec, dash="—"):
    return dash if x is None else format(x, spec)


def scatter(rows):
    pts = [r for r in rows if r["pass_at_1"] is not None and r["avg_minutes"]]
    if not pts:
        return '<p class="note">No scored rows yet.</p>'
    xs = [r["avg_minutes"] for r in pts]
    xmax = max(xs) * 1.15
    ymax = max(100.0, max(r["pass_at_1"] * 100 for r in pts) * 1.15)
    iw, ih = W - PAD["l"] - PAD["r"], H - PAD["t"] - PAD["b"]
    fx = lambda v: PAD["l"] + (v / xmax) * iw
    fy = lambda v: PAD["t"] + ih - (v / ymax) * ih
    fam = sorted({r["family"] for r in pts})
    out = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Pass at 1 against wall-clock minutes per task">']
    for i in range(5):
        v = ymax * i / 4
        y = fy(v)
        out.append(f'<line class="grid" x1="{PAD["l"]}" y1="{y:.1f}" x2="{W - PAD["r"]}" y2="{y:.1f}"/>')
        out.append(f'<text class="tick" x="{PAD["l"] - 8}" y="{y + 4:.1f}" text-anchor="end">{v:.0f}%</text>')
    for i in range(5):
        v = xmax * i / 4
        x = fx(v)
        out.append(f'<text class="tick" x="{x:.1f}" y="{H - PAD["b"] + 20}" text-anchor="middle">{v:.0f}</text>')
    out.append(f'<text class="axis" x="{PAD["l"] + iw / 2}" y="{H - 8}" text-anchor="middle">Wall-clock minutes per task</text>')
    out.append(f'<text class="axis" transform="translate(14,{PAD["t"] + ih / 2}) rotate(-90)" text-anchor="middle">Pass@1</text>')
    for r in pts:
        s = fam.index(r["family"]) + 1
        x, y = fx(r["avg_minutes"]), fy(r["pass_at_1"] * 100)
        out.append(f'<circle class="pt series-{s}" cx="{x:.1f}" cy="{y:.1f}" r="5"><title>{html.escape(r["label"])} '
                   f'[{r["effort"]}] — {r["pass_at_1"] * 100:.0f}%, {r["avg_minutes"]:.0f} min</title></circle>')
        tag = f'{r["family"].split()[0]} {r["quant"]} {r["effort"]}'
        out.append(f'<text class="lbl" x="{x + 9:.1f}" y="{y + 4:.1f}">{html.escape(tag)}</text>')
    out.append("</svg>")
    return "".join(out)


def table(rows, best_ids):
    head = ("<thead><tr>"
            '<th scope="col">Model</th>'
            '<th scope="col" class="num">Pass@1</th>'
            '<th scope="col" class="num">Pass@1 @3h</th>'
            '<th scope="col" class="num">Avg min/task</th>'
            '<th scope="col" class="num">Out tok (k)</th>'
            '<th scope="col" class="num">Steps</th>'
            '<th scope="col" class="num">Tasks</th>'
            "</tr></thead>")
    body = []
    for r in rows:
        key = f'{r["server_id"]}__{r["effort"]}'
        p1 = fmt(r["pass_at_1"] and r["pass_at_1"] * 100, ".0f")
        ci = fmt(r["ci_half"] and r["ci_half"] * 100, ".0f")
        body.append(
            f'<tr data-best="{"1" if key in best_ids else "0"}">'
            f'<th scope="row">{html.escape(r["label"])} <span class="eff">[{html.escape(r["effort"])}]</span></th>'
            f'<td class="num">{p1}% <span class="ci">±{ci}</span></td>'
            f'<td class="num">{fmt(r["pass_at_1_3h"] and r["pass_at_1_3h"] * 100, ".0f")}%</td>'
            f'<td class="num">{fmt(r["avg_minutes"], ".1f")}</td>'
            f'<td class="num">{fmt(r["avg_out_tok_k"], ".0f")}</td>'
            f'<td class="num">{fmt(r["avg_steps"], ".0f")}</td>'
            f'<td class="num">{r["n_counted"]}/113</td></tr>')
    return f'<table><caption>DeepSWE pass@1 by model, quantization and reasoning effort</caption>{head}<tbody>{"".join(body)}</tbody></table>'


CSS = """
:root{color-scheme:light dark;--bg:#fff;--fg:#0a0a0a;--fg2:#666;--line:#eaeaea;--line2:#d4d4d4;--focus:#0072f5;
--s1:#0a0a0a;--s2:#7a7a7a;--s3:#b4b4b4}
@media(prefers-color-scheme:dark){:root{--bg:#0a0a0a;--fg:#ededed;--fg2:#a1a1a1;--line:#1f1f1f;--line2:#333;
--s1:#ededed;--s2:#8f8f8f;--s3:#5a5a5a}}
*{box-sizing:border-box;min-width:0}
body{margin:0;background:var(--bg);color:var(--fg);font-family:Geist,-apple-system,system-ui,sans-serif;
font-size:15px;line-height:1.6;font-variant-numeric:tabular-nums}
main{max-width:1060px;margin:0 auto;padding:48px 24px 96px}
h1{font-size:28px;line-height:1.25;font-weight:600;margin:0 0 8px}
h2{font-size:20px;line-height:1.3;font-weight:600;margin:48px 0 12px}
.lede{color:var(--fg2);max-width:68ch;margin:0 0 8px}
.note{color:var(--fg2);font-size:13px;max-width:78ch}
table{width:100%;border-collapse:collapse;margin-top:12px;font-size:14px}
caption{text-align:left;color:var(--fg2);font-size:13px;padding-bottom:8px}
th,td{padding:10px 12px;border-bottom:1px solid var(--line);vertical-align:baseline;text-align:left;font-weight:400}
thead th{color:var(--fg2);font-size:13px;font-weight:500;border-bottom:1px solid var(--line2)}
th[scope=row]{font-weight:500;white-space:nowrap}
.num{text-align:right;white-space:nowrap}
.eff{color:var(--fg2);font-weight:400}
.ci{color:var(--fg2);font-size:12px}
tbody tr:hover{background:color-mix(in srgb,var(--fg) 4%,transparent)}
.controls{display:flex;gap:16px;align-items:center;margin-top:24px;flex-wrap:wrap}
.controls label{display:inline-flex;gap:6px;align-items:center;font-size:14px}
input:focus-visible,a:focus-visible{outline:2px solid var(--focus);outline-offset:2px}
svg{width:100%;height:auto;margin-top:12px}
.grid{stroke:var(--line);stroke-width:1}
.tick,.axis,.lbl{fill:var(--fg2);font-size:11px;font-family:Geist,system-ui,sans-serif}
.axis{fill:var(--fg2);font-size:12px}
.lbl{fill:var(--fg2);font-size:10px}
.pt.series-1{fill:var(--s1)}.pt.series-2{fill:var(--s2)}.pt.series-3{fill:var(--s3)}
footer{margin-top:64px;color:var(--fg2);font-size:13px}
code{font-family:"Geist Mono",ui-monospace,monospace;font-size:0.92em}
.skip{position:absolute;left:-9999px;top:0;background:var(--bg);color:var(--fg);padding:10px 14px;z-index:1}
.skip:focus{left:8px;top:8px}
"""

JS = """
const only=document.getElementById('best');
const apply=()=>document.querySelectorAll('tbody tr').forEach(r=>{
  r.hidden = only.checked && r.dataset.best!=='1';});
only.addEventListener('change',apply);apply();
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results", default=str(ROOT / "results" / "results.json"))
    ap.add_argument("--out", default=str(ROOT / "results" / "index.html"))
    a = ap.parse_args()

    data = json.loads(Path(a.results).read_text())
    rows = sorted(data["rows"], key=lambda r: (-(r["pass_at_1"] if r["pass_at_1"] is not None else -1), r["label"]))
    best = {}
    for r in rows:
        k = (r["family"], r["quant"], r["ctx"])
        if k not in best or (r["pass_at_1"] or -1) > (best[k]["pass_at_1"] or -1):
            best[k] = r
    best_ids = {f'{r["server_id"]}__{r["effort"]}' for r in best.values()}

    page = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>DeepSWE on DwarfStar</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" referrerpolicy="no-referrer" href="https://fonts.googleapis.com/css2?family=Geist:wght@400..600&family=Geist+Mono:wght@400..500&display=swap">
<style>{CSS}</style></head>
<body><a class="skip" href="#main">Skip to content</a><main id="main">
<h1>DeepSWE on DwarfStar</h1>
<p class="lede">Three model families served locally by ds4-server on an Apple M3 Ultra with 512 GB of
unified memory, scored on all 113 DeepSWE tasks through mini-swe-agent 2.3.0 under Pier.</p>
<p class="note">One rollout per task. Pass@1 ± is a 95% bootstrap interval over tasks, not the public
leaderboard's across-rollout interval. Effort labels are the ones the server distinguishes:
<code>xhigh</code> equals <code>high</code>; GLM and DeepSeek render <code>low</code> and
<code>medium</code> as <code>high</code>; <code>max</code> needs a 393216-token context on Qwen and GLM.
Generated {html.escape(data["generated_at"])}.</p>
<div class="controls"><label><input type="checkbox" id="best"> Best effort level only</label></div>
{table(rows, best_ids)}
<h2>Score against wall-clock cost</h2>
{scatter(rows)}
<p class="note">Minutes per task are wall-clock for the agent phase at the concurrency each row ran with,
so they compare configurations on this machine rather than predicting single-stream latency.</p>
<footer>Source and scripts: <a href="https://github.com/OpenSWE/deepswe-local-bench">OpenSWE/deepswe-local-bench</a>.</footer>
</main><script>{JS}</script></body></html>
"""
    Path(a.out).write_text(page)
    print(f"wrote {a.out} ({len(page)} bytes, {len(rows)} rows)")


if __name__ == "__main__":
    main()
