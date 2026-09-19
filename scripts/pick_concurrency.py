#!/usr/bin/env python3
"""Measure aggregate throughput against session count, to pick --batched-session.

Batched sessions are not free: on some backends per-session decode collapses at
agent-length contexts, so N sessions can be slower in aggregate than one. This
fires N concurrent agent-shaped requests (long prompt, short reply) at a server
started with --batched-session N and reports aggregate output tokens/sec.

    scripts/pick_concurrency.py --model gguf/X.gguf --ctx 262144 --sessions 1,2,3,6

Pick the session count with the highest aggregate; ties go to the lower count,
which keeps per-task wall-clock shorter.
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


def one_request(url, prompt, max_tokens, effort):
    t0 = time.time()
    r = post(url, {"model": "bench", "reasoning_effort": effort, "max_tokens": max_tokens,
                   "messages": [{"role": "user", "content": prompt}]})
    u = r.get("usage") or {}
    return u.get("completion_tokens", 0), u.get("prompt_tokens", 0), time.time() - t0


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
    ap.add_argument("--effort", default="high")
    ap.add_argument("--port", type=int, default=8000)
    a = ap.parse_args()

    d = tomllib.loads(Path(a.matrix).read_text())["defaults"]
    repo = Path(os.path.expanduser(d["ds4_repo"]))
    corpus = (repo / "ds4.c").read_text(errors="replace")
    url = f"http://127.0.0.1:{a.port}/v1/chat/completions"

    print(f"{'sessions':>8} {'clients':>7} {'wall_s':>8} {'out_tok':>8} {'agg_tok/s':>10} {'per_cli':>9} {'prompt_tok':>10}")
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
            t0 = time.time()
            with ThreadPoolExecutor(max_workers=c) as ex:
                res = list(ex.map(lambda p: one_request(url, p, a.max_tokens, a.effort), prompts))
            wall = time.time() - t0
            out = sum(r[0] for r in res)
            ptok = sum(r[1] for r in res) // max(c, 1)
            agg = out / wall
            rows.append((n, wall, out, agg))
            print(f"{n:>8} {c:>7} {wall:>8.0f} {out:>8} {agg:>10.2f} {agg / c:>9.2f} {ptok:>10}")
        finally:
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(timeout=120)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
            time.sleep(5)

    if rows:
        best = max(rows, key=lambda r: (round(r[3], 2), -r[0]))
        print(f"\nbest: --batched-session {best[0]} at {best[3]:.2f} aggregate tok/s")


if __name__ == "__main__":
    main()
