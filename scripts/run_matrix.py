#!/usr/bin/env python3
"""Drive a matrix of ds4-server configurations through Pier + mini-swe-agent on DeepSWE.

One [[server]] in matrix.toml = one ds4-server instance; every effort listed for it
runs against that same instance (reasoning_effort is a per-request field), so the
server restarts once per (model, quant, context), not once per row.

Resumable by construction: a job whose jobs/<job>/result.json exists is skipped, a
job directory without it is resumed with `pier job resume`. Kill the driver at any
time and rerun the same command.
"""
import argparse
import json
import os
import signal
import subprocess
import sys
import time
import tomllib
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def log(msg: str) -> None:
    print(time.strftime("%Y-%m-%d %H:%M:%S"), msg, flush=True)


def expand(p: str) -> Path:
    q = Path(os.path.expanduser(p))
    return q if q.is_absolute() else ROOT / q


def job_name(server_id: str, effort: str, suffix: str | None) -> str:
    return f"{server_id}__{effort}" + (f"__{suffix}" if suffix else "")


def job_done(jobs_dir: Path, name: str) -> bool:
    return (jobs_dir / name / "result.json").exists()


def listeners(port: int) -> list[int]:
    out = subprocess.run(["lsof", "-ti", f"tcp:{port}", "-sTCP:LISTEN"], capture_output=True, text=True).stdout
    return [int(x) for x in out.split()]


def kill_stale_server(port: int) -> None:
    for pid in listeners(port):
        comm = subprocess.run(["ps", "-o", "comm=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
        if comm.endswith("ds4-server"):
            log(f"killing stale ds4-server pid {pid} on port {port}")
            os.kill(pid, signal.SIGTERM)
            for _ in range(60):
                if not listeners(port):
                    break
                time.sleep(2)
        else:
            sys.exit(f"port {port} is held by {comm!r} (pid {pid}); free it first")


def ensure_forwarder(d: dict) -> None:
    """Root-owned 80 -> ds4 port forwarder; Pier's squid allows only ports 80/443."""
    fwd = d.get("forward_port")
    if not fwd or listeners(fwd):
        return
    script = ROOT / "scripts" / "port80_forward.py"
    cmd = ["sudo", "-n", sys.executable, str(script), "--listen-port", str(fwd), "--target-port", str(d["port"])]
    log("starting port forwarder: " + " ".join(cmd))
    out = open(ROOT / "runs" / "port80_forward.log", "ab")
    (ROOT / "runs").mkdir(exist_ok=True)
    subprocess.Popen(cmd, stdout=out, stderr=subprocess.STDOUT, start_new_session=True)
    for _ in range(30):
        if listeners(fwd):
            log(f"forwarder listening on {fwd}")
            return
        time.sleep(1)
    sys.exit(f"port forwarder did not come up on {fwd}; run it manually: sudo {script}")


def has_writer(path: Path) -> bool:
    """True if some process holds the file open for writing (a download still running).

    A reader is fine and expected: the inference server itself mmaps the weights.
    """
    out = subprocess.run(["lsof", "-Fan", "--", str(path)], capture_output=True, text=True).stdout
    return any(line[1:].rstrip(" -").endswith(("w", "u")) for line in out.splitlines() if line.startswith("a"))


def model_ready(path: Path, quiet_s: int = 60) -> bool:
    """Complete on disk: exists, no in-progress sibling, no writer, size stable."""
    if not path.exists() or Path(str(path) + ".assembling").exists() or has_writer(path):
        return False
    size = path.stat().st_size
    time.sleep(quiet_s)
    return path.exists() and path.stat().st_size == size and not has_writer(path)


def wait_for_model(path: Path) -> None:
    announced = False
    while not model_ready(path):
        if not announced:
            log(f"waiting for model file {path} (download in progress elsewhere)")
            announced = True
        time.sleep(300)
    log(f"model file ready: {path} ({path.stat().st_size / 2**30:.1f} GiB)")


def server_cmd(d: dict, s: dict) -> list[str]:
    repo = expand(d["ds4_repo"])
    cmd = [str(repo / "ds4-server"), "-m", str(repo / s["model"]), "--ctx", str(s["ctx"]),
           "--host", "127.0.0.1", "--port", str(d["port"])]
    if s.get("sessions", 1) > 1:
        cmd += ["--batched-session", str(s["sessions"])]
    if s.get("mtp"):
        cmd.append("--mtp")
    if d.get("kv_disk_dir"):
        cmd += ["--kv-disk-dir", d["kv_disk_dir"], "--kv-disk-space-mb", str(d["kv_disk_space_mb"]),
                "--kv-cache-cold-max-tokens", str(d["kv_cold_max_tokens"])]
    cmd += s.get("extra_args", [])
    return cmd


def start_server(d: dict, s: dict, log_path: Path) -> subprocess.Popen:
    kill_stale_server(d["port"])
    log_path.parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, **s.get("env", {}))
    cmd = server_cmd(d, s)
    log("server: " + " ".join(cmd) + (f"  env={s['env']}" if s.get("env") else ""))
    out = open(log_path, "ab")
    return subprocess.Popen(cmd, cwd=expand(d["ds4_repo"]), stdout=out, stderr=subprocess.STDOUT, env=env,
                            start_new_session=True)


def wait_ready(d: dict, proc: subprocess.Popen, log_path: Path) -> None:
    url = f"http://127.0.0.1:{d['port']}/v1/models"
    t0 = time.time()
    while time.time() - t0 < d.get("server_ready_timeout_s", 3600):
        if proc.poll() is not None:
            print(log_path.read_text()[-4000:])
            raise RuntimeError(f"ds4-server exited with {proc.returncode} during startup")
        try:
            with urllib.request.urlopen(url, timeout=5) as r:
                if r.status == 200:
                    log(f"server ready after {time.time() - t0:.0f}s")
                    for line in log_path.read_text(errors="replace").splitlines():
                        if "memory" in line.lower() or "context" in line.lower():
                            log("  server: " + line.strip())
                    return
        except Exception:
            pass
        time.sleep(5)
    raise TimeoutError("ds4-server did not become ready")


def stop_server(proc: subprocess.Popen | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    log("stopping ds4-server")
    os.killpg(proc.pid, signal.SIGTERM)
    try:
        proc.wait(timeout=180)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()


def pier_run_cmd(d: dict, s: dict, effort: str, name: str, jobs_dir: Path, args) -> list[str]:
    cmd = ["pier", "run", "-p", str(expand(d["tasks"])), "--agent", "mini-swe-agent", "-m", f"openai/{s['id']}",
           "--ak", f"version={d['mini_swe_agent_version']}",
           "--ak", "model_class=litellm",                      # chat completions, not the Responses API
           "--ak", f"reasoning_effort={effort}",
           "--ak", "model_kwargs=" + json.dumps({"seed": d["seed"]}),
           "--ae", f"OPENAI_BASE_URL={d['base_url']}", "--ae", f"OPENAI_API_BASE={d['base_url']}",
           "--ae", "OPENAI_API_KEY=dummy",                     # ds4-server has no auth; litellm wants a key
           "-n", str(s["sessions"]), "-k", "1",
           "--agent-timeout-multiplier", str(d["agent_timeout_multiplier"]),
           "-r", str(d.get("max_retries", 1)),
           "-o", str(jobs_dir), "--job-name", name, "-y", "-q"]
    if args.n_tasks:
        cmd += ["-l", str(args.n_tasks), "--sample-seed", str(args.sample_seed)]
    for t in args.task or []:
        cmd += ["-i", t]
    return cmd


def run_logged(cmd: list[str], log_path: Path) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log("$ " + " ".join(cmd))
    with open(log_path, "ab") as out:
        p = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        assert p.stdout is not None
        for line in p.stdout:
            out.write(line)
            sys.stdout.buffer.write(line)
            sys.stdout.flush()
        return p.wait()


def run_job(d: dict, s: dict, effort: str, jobs_dir: Path, args) -> bool:
    name = job_name(s["id"], effort, args.suffix)
    job_log = ROOT / "runs" / s["id"] / f"pier-{name}.log"
    for attempt in range(1, 4):
        if job_done(jobs_dir, name):
            log(f"job {name}: done")
            return True
        if (jobs_dir / name).exists():
            cmd = ["pier", "job", "resume", "-p", str(jobs_dir / name)]
        else:
            cmd = pier_run_cmd(d, s, effort, name, jobs_dir, args)
        if args.dry_run:
            log("dry-run: " + " ".join(cmd))
            return False
        rc = run_logged(cmd, job_log)
        log(f"job {name}: pier exited {rc} (attempt {attempt})")
    return job_done(jobs_dir, name)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--matrix", default=str(ROOT / "matrix.toml"))
    ap.add_argument("--only", action="append", help="server id(s) to run; default all, in matrix order")
    ap.add_argument("--efforts", help="comma-separated subset of efforts")
    ap.add_argument("--n-tasks", type=int, help="Pier -l: seeded task subset (smoke tests, pilots)")
    ap.add_argument("--sample-seed", type=int, default=0)
    ap.add_argument("--task", action="append", help="Pier -i task-name glob (repeatable)")
    ap.add_argument("--suffix", help="job-name suffix so subsets never collide with the real sweep")
    ap.add_argument("--sessions", type=int, help="override sessions/concurrency for the selected servers")
    ap.add_argument("--mtp", dest="mtp", action="store_true", default=None, help="force --mtp on")
    ap.add_argument("--no-mtp", dest="mtp", action="store_false", help="force --mtp off")
    ap.add_argument("--reuse-server", action="store_true",
                    help="use a ds4-server already listening on the port instead of starting/stopping one")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if args.n_tasks and not args.suffix:
        ap.error("--n-tasks requires --suffix so the subset job never shadows a full run")

    m = tomllib.loads(Path(args.matrix).read_text())
    d, servers = m["defaults"], m["server"]
    jobs_dir = expand(d["jobs_dir"])
    jobs_dir.mkdir(parents=True, exist_ok=True)
    if args.only:
        unknown = set(args.only) - {s["id"] for s in servers}
        if unknown:
            ap.error(f"unknown server id(s): {sorted(unknown)}")
        servers = [s for s in servers if s["id"] in args.only]

    failed: list[str] = []
    for s in servers:
        efforts = [e for e in s["efforts"] if not args.efforts or e in args.efforts.split(",")]
        if args.sessions:
            s["sessions"] = args.sessions
        if args.mtp is not None:
            s["mtp"] = args.mtp
        pending = [e for e in efforts if not job_done(jobs_dir, job_name(s["id"], e, args.suffix))]
        if not pending:
            log(f"[{s['id']}] all {len(efforts)} runs done, skipping")
            continue
        log(f"[{s['id']}] pending efforts: {pending}")
        if args.dry_run:
            log("dry-run server: " + " ".join(server_cmd(d, s)))
            for e in pending:
                run_job(d, s, e, jobs_dir, args)
            continue
        wait_for_model(expand(d["ds4_repo"]) / s["model"])
        ensure_forwarder(d)
        server_log = ROOT / "runs" / s["id"] / f"server-{time.strftime('%Y%m%d-%H%M%S')}.log"
        proc = None
        try:
            if args.reuse_server and listeners(d["port"]):
                log(f"reusing ds4-server already listening on port {d['port']}")
            else:
                proc = start_server(d, s, server_log)
                wait_ready(d, proc, server_log)
            for e in pending:
                if not run_job(d, s, e, jobs_dir, args):
                    failed.append(job_name(s["id"], e, args.suffix))
        except KeyboardInterrupt:
            log("interrupted; jobs are resumable — rerun the same command")
            stop_server(proc)
            sys.exit(130)
        finally:
            stop_server(proc)
    if failed:
        log(f"unfinished after retries: {failed}")
        sys.exit(1)
    log("matrix complete")


if __name__ == "__main__":
    main()
