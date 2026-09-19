#!/usr/bin/env python3
"""Aggregate Pier job directories into a leaderboard-style results table.

Reads jobs/<server_id>__<effort>/*/result.json, applies the DeepSWE leaderboard's
error rules (infrastructure errors leave the denominator; agent timeouts and
context exhaustion count as failures), and writes results/results.json and
results/RESULTS.md. The ± is a 95% bootstrap interval over tasks (one rollout per
task), which is not the leaderboard's across-rollout method.
"""
import argparse
import json
import random
import statistics
import time
import tomllib
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TASK_TIMEOUT_S = 10800          # DeepSWE task.toml agent timeout; the 3 h leaderboard cutoff
N_TASKS = 113

# Pier exception types that mean the harness, not the model, failed.
INFRA_ERRORS = {
    "EnvironmentBuildError", "EnvironmentBuildTimeoutError", "EnvironmentStartError",
    "AgentSetupError", "AgentSetupTimeoutError", "AgentInstallationError",
    "VerifierTimeoutError", "VerifierError", "RewardFileNotFoundError", "RewardFileEmptyError",
    "VerifierOutputParseError", "CancelledError", "DockerError", "DockerComposeError",
    "ConnectionError", "APIConnectionError", "TimeoutError",
}
# Exception types that count as a failed attempt (reward 0).
FAILURE_ERRORS = {"AgentTimeoutError", "ContextWindowExceededError"}

EFFORT_ORDER = ["none", "low", "medium", "high", "xhigh", "max"]


def parse_ts(s):
    return datetime.fromisoformat(s) if s else None


def load_trial(path: Path) -> dict | None:
    try:
        r = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    exc = (r.get("exception_info") or {}).get("exception_type")
    rewards = (r.get("verifier_result") or {}).get("rewards") or {}
    reward = rewards.get("reward")
    ae = r.get("agent_execution") or {}
    t0, t1 = parse_ts(ae.get("started_at")), parse_ts(ae.get("finished_at"))
    duration = (t1 - t0).total_seconds() if t0 and t1 else None
    ar = r.get("agent_result") or {}
    if exc in INFRA_ERRORS:
        status = "infra"
    elif exc in FAILURE_ERRORS:
        status, reward = "failure", 0
    elif exc:
        status = "unknown-error"
    elif reward is None:
        status = "unscored"
    else:
        status = "scored"
    return {
        "task": r.get("task_name"), "trial": path.parent.name, "status": status, "exception": exc,
        "reward": reward, "duration_s": duration, "n_output_tokens": ar.get("n_output_tokens"),
        "steps": r.get("n_agent_steps") or ar.get("n_agent_steps"),
        "peak_context_tokens": ar.get("peak_context_tokens"),
    }


def bootstrap_ci(values: list[float], n: int = 5000, seed: int = 0) -> tuple[float, float]:
    if not values:
        return (0.0, 0.0)
    rng = random.Random(seed)
    k = len(values)
    means = sorted(statistics.fmean(rng.choices(values, k=k)) for _ in range(n))
    return (means[int(0.025 * n)], means[int(0.975 * n) - 1])


def mean_or_none(xs):
    xs = [x for x in xs if x is not None]
    return statistics.fmean(xs) if xs else None


def summarize(server: dict, effort: str, trials: list[dict]) -> dict:
    counted = [t for t in trials if t["status"] in ("scored", "failure", "unscored", "unknown-error")]
    # unscored / unknown-error are conservatively counted as failures but flagged
    rewards = [float(t["reward"]) if t["reward"] is not None else 0.0 for t in counted]
    p = statistics.fmean(rewards) if rewards else None
    lo, hi = bootstrap_ci(rewards)
    at3h = [1.0 if (t["reward"] == 1 and (t["duration_s"] or 0) <= TASK_TIMEOUT_S) else 0.0 for t in counted]
    return {
        "server_id": server["id"], "label": server["label"], "family": server["family"], "quant": server["quant"],
        "ctx": server["ctx"], "sessions": server["sessions"], "mtp": server.get("mtp", False), "effort": effort,
        "n_trials": len(trials), "n_counted": len(counted),
        "n_infra": sum(t["status"] == "infra" for t in trials),
        "n_flagged": sum(t["status"] in ("unscored", "unknown-error") for t in trials),
        "pass_at_1": p, "ci_low": lo, "ci_high": hi, "ci_half": (hi - lo) / 2 if rewards else None,
        "pass_at_1_3h": statistics.fmean(at3h) if at3h else None,
        "avg_minutes": (mean_or_none([t["duration_s"] for t in counted]) or 0) / 60 if counted else None,
        "avg_out_tok_k": (mean_or_none([t["n_output_tokens"] for t in counted]) or 0) / 1000 if counted else None,
        "avg_steps": mean_or_none([t["steps"] for t in counted]),
        "complete": len(counted) >= N_TASKS,
    }


def fmt(x, spec):
    return "—" if x is None else format(x, spec)


def render_md(rows: list[dict], generated: str) -> str:
    rows = sorted(rows, key=lambda r: (-(r["pass_at_1"] or -1), r["label"]))
    best = {}
    for r in rows:
        key = (r["family"], r["quant"], r["ctx"])
        if key not in best or (r["pass_at_1"] or -1) > (best[key]["pass_at_1"] or -1):
            best[key] = r
    out = [f"# DeepSWE on DwarfStar (ds4) — local results", "",
           f"Generated {generated}. 113 tasks, one rollout per task, mini-swe-agent 2.3.0 via Pier, "
           f"Apple M3 Ultra 512 GB. Pass@1 ± is a 95% bootstrap interval over tasks.", "",
           "| Model | Pass@1 | Pass@1 @3h | Avg min/task | Out tok (k) | Steps | Tasks |",
           "|---|---:|---:|---:|---:|---:|---:|"]
    for r in rows:
        star = " ★" if best.get((r["family"], r["quant"], r["ctx"])) is r else ""
        pct = f"{fmt(r['pass_at_1'] and r['pass_at_1']*100, '.0f')}% ±{fmt(r['ci_half'] and r['ci_half']*100, '.0f')}"
        infra = f" ({r['n_infra']} infra)" if r["n_infra"] else ""
        p3 = fmt(r["pass_at_1_3h"] and r["pass_at_1_3h"] * 100, ".0f")
        out.append(
            f"| {r['label']} [{r['effort']}]{star} | {pct} | {p3}% "
            f"| {fmt(r['avg_minutes'], '.1f')} | {fmt(r['avg_out_tok_k'], '.0f')} | {fmt(r['avg_steps'], '.0f')} "
            f"| {r['n_counted']}/{N_TASKS}{infra} |"
        )
    out += ["", "★ best effort level within a (family, quant, context) group.  ",
            "Effort labels are the ones ds4-server distinguishes: `xhigh` equals `high`; GLM and DeepSeek render "
            "`low`/`medium` as `high`; `max` needs a 393216-token context on Qwen and GLM.  ",
            "Avg min/task is wall-clock of the agent phase under the row's concurrency (sessions column in results.json); "
            "Pass@1 @3h re-scores each task as a failure if the agent phase exceeded the leaderboard's 3 h limit.  ",
            "Tasks = counted / total; infra = harness errors excluded from the denominator."]
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--matrix", default=str(ROOT / "matrix.toml"))
    ap.add_argument("--jobs", help="jobs dir (default: matrix defaults.jobs_dir)")
    ap.add_argument("--out", default=str(ROOT / "results"))
    ap.add_argument("--include-suffix", action="store_true", help="also aggregate suffixed (smoke/pilot) jobs")
    args = ap.parse_args()

    m = tomllib.loads(Path(args.matrix).read_text())
    servers = {s["id"]: s for s in m["server"]}
    jobs_dir = Path(args.jobs) if args.jobs else ROOT / m["defaults"]["jobs_dir"]
    out_dir = Path(args.out); out_dir.mkdir(parents=True, exist_ok=True)

    rows, all_trials, unknown = [], {}, set()
    for job in sorted(p for p in jobs_dir.iterdir() if p.is_dir()):
        parts = job.name.split("__")
        if len(parts) < 2 or parts[0] not in servers or (len(parts) > 2 and not args.include_suffix):
            continue
        server, effort = servers[parts[0]], parts[1]
        trials = [t for t in (load_trial(p) for p in job.glob("*/result.json")) if t]
        if not trials:
            continue
        unknown |= {t["exception"] for t in trials if t["status"] == "unknown-error"}
        rows.append(summarize(server, effort, trials))
        all_trials[job.name] = trials

    generated = time.strftime("%Y-%m-%d %H:%M %Z")
    (out_dir / "results.json").write_text(json.dumps({"generated_at": generated, "rows": rows, "trials": all_trials}, indent=1))
    (out_dir / "RESULTS.md").write_text(render_md(rows, generated))
    for r in sorted(rows, key=lambda r: -(r["pass_at_1"] or -1)):
        print(f"{r['label']} [{r['effort']}]: {fmt(r['pass_at_1'] and r['pass_at_1']*100, '.1f')}% "
              f"({r['n_counted']} counted, {r['n_infra']} infra, {r['n_flagged']} flagged)")
    if unknown:
        print("exception types not classified (counted as failures):", sorted(unknown))


if __name__ == "__main__":
    main()
