#!/usr/bin/env python3
"""Measure aggregate throughput against session count, to pick --batched-session.

Each client runs a MULTI-TURN conversation that grows the way an agent's does: a long
seed prompt, then a synthetic tool result appended each turn. That is deliberate. A
single-shot benchmark measures only decode contention and will tell you to use one
session, but an agent re-sends its whole history every step, so what dominates is
whether the server still holds that history. One resident session cannot hold several
agents at once — they evict each other and every step re-prefills the full context.
Measured here on a real sweep, median prefix reuse with 1 session and 3 concurrent
agents was 2.4%, i.e. ~70-90k tokens re-prefilled per step.

    scripts/pick_concurrency.py --model gguf/X.gguf --ctx 393216 --sessions 1,2,3,6 --mtp

Reported per row: aggregate output tokens/sec and mean prefix reuse. Pick the highest
aggregate; if two are close, prefer the one with higher reuse, because reuse is what
keeps per-step cost flat as the trajectory grows.
"""
import argparse
import json
import os
import signal
import subprocess
import sys
import time
import tomllib
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def log(m):
    print(time.strftime("%H:%M:%S"), m, flush=True)


def post(url, payload, timeout=1800):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def one_conversation(url, seed, filler, turns, max_tokens, effort):
    """One agent-shaped conversation: same prefix every turn, a new tool result appended."""
    msgs = [{"role": "user", "content": seed}]
    out = ptok = cached = 0
    for t in range(turns):
        r = post(url, {"model": "bench", "reasoning_effort": effort, "max_tokens": max_tokens,
                       "messages": msgs})
        u = r.get("usage") or {}
        out += u.get("completion_tokens", 0)
        ptok += u.get("prompt_tokens", 0)
        det = u.get("prompt_tokens_details") or {}
        cached += det.get("cached_tokens", 0)
        msgs.append({"role": "assistant",
                     "content": (r["choices"][0]["message"].get("content") or "")[:2000] or "ok"})
        msgs.append({"role": "user",
                     "content": f"Tool output for step {t}:\n" + filler[t * 4000:(t + 1) * 4000 + 4000]})
    return out, ptok, cached


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--matrix", default=str(ROOT / "matrix.toml"))
    ap.add_argument("--model", required=True, help="GGUF path relative to the ds4 repo")
    ap.add_argument("--ctx", type=int, default=262144)
    ap.add_argument("--sessions", default="1,2,3,6")
    ap.add_argument("--clients", type=int, default=0,
                    help="concurrent requests to fire; default = the session count. Set it higher than "
                         "--sessions to measure a server that QUEUES extra agents (Pier -n above the slot count).")
    ap.add_argument("--mtp", action="store_true")
    ap.add_argument("--prompt-chars", type=int, default=60000, help="~15k tokens of source text per request")
    ap.add_argument("--max-tokens", type=int, default=300)
    ap.add_argument("--turns", type=int, default=6,
                    help="turns per client; >1 is what exposes prefix-cache thrashing")
    ap.add_argument("--effort", default="high")
    ap.add_argument("--port", type=int, default=8000)
    a = ap.parse_args()

    d = tomllib.loads(Path(a.matrix).read_text())["defaults"]
    repo = Path(os.path.expanduser(d["ds4_repo"]))
    corpus = (repo / "ds4.c").read_text(errors="replace")
    url = f"http://127.0.0.1:{a.port}/v1/chat/completions"

    print(f"{'sessions':>8} {'clients':>7} {'wall_s':>8} {'out_tok':>8} {'agg_tok/s':>10} {'per_cli':>9} {'reuse':>10}")
    rows = []
    for n in [int(x) for x in a.sessions.split(",")]:
        cmd = [str(repo / "ds4-server"), "-m", str(repo / a.model), "--ctx", str(a.ctx),
               "--host", "127.0.0.1", "--port", str(a.port)]
        if n > 1:
            cmd += ["--batched-session", str(n)]
        if a.mtp:
            cmd.append("--mtp")
        logf = open(ROOT / "runs" / f"pick-concurrency-{n}.log", "wb")
        (ROOT / "runs").mkdir(exist_ok=True)
        proc = subprocess.Popen(cmd, cwd=repo, stdout=logf, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            for _ in range(720):
                try:
                    urllib.request.urlopen(f"http://127.0.0.1:{a.port}/v1/models", timeout=5)
                    break
                except (urllib.error.URLError, OSError):
                    if proc.poll() is not None:
                        sys.exit(f"server exited {proc.returncode}; see runs/pick-concurrency-{n}.log")
                    time.sleep(5)
            # Distinct slices so prefix caching cannot collapse the sessions into one.
            c = a.clients or n
            prompts = [f"// session {i}\n" + corpus[i * 5000: i * 5000 + a.prompt_chars] +
                       "\n\nSummarize what this code does in two sentences." for i in range(c)]
            filler = corpus[400000:400000 + 60000]
            t0 = time.time()
            with ThreadPoolExecutor(max_workers=c) as ex:
                res = list(ex.map(
                    lambda p: one_conversation(url, p, filler, a.turns, a.max_tokens, a.effort), prompts))
            wall = time.time() - t0
            out = sum(r[0] for r in res)
            ptok = sum(r[1] for r in res)
            cached = sum(r[2] for r in res)
            reuse = 100 * cached / ptok if ptok else 0.0
            agg = out / wall
            rows.append((n, wall, out, agg, reuse))
            print(f"{n:>8} {c:>7} {wall:>8.0f} {out:>8} {agg:>10.2f} {agg / c:>9.2f} {reuse:>9.1f}%")
        finally:
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(timeout=120)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
            time.sleep(5)

    if rows:
        best = max(rows, key=lambda r: (round(r[3], 2), round(r[4]), -r[0]))
        print(f"\nbest: --batched-session {best[0]} at {best[3]:.2f} aggregate tok/s, "
              f"{best[4]:.1f}% prefix reuse")


if __name__ == "__main__":
    main()
