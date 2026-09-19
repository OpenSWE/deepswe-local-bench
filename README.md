# deepswe-local-bench

Score a **locally served** model on [DeepSWE](https://deepswe.datacurve.ai/) — 113 long-horizon
software-engineering tasks across 91 repositories and 5 languages — with the same harness the public
leaderboard uses, then render the result as a leaderboard-style table, a results JSON and a static
HTML page.

[Pier](https://github.com/datacurve-ai/pier) runs each task in a Docker sandbox,
[mini-swe-agent](https://mini-swe-agent.com/) is the agent inside it, and your own server answers
`/v1/chat/completions`. One `matrix.toml` declares every server configuration; the driver walks it,
restarting the server only when the weights or context change, because reasoning effort is a
per-request field.

Built for [DwarfStar](https://github.com/antirez/ds4) (`ds4-server`), but nothing in the scripts is
specific to it: any server that accepts `tools` and returns `tool_calls` works, including llama.cpp,
vLLM and SGLang.

## The one setting that matters

Give every concurrent agent its own resident session (`sessions = clients` in `matrix.toml`). An
agent re-sends its whole history each step, so one slot cannot hold several conversations — they
evict each other and each step re-prefills the entire context. Measured here on Qwen3.8 Q2:

| Slots / agents | Median prefix reuse | Prefill per step |
|---|--:|--:|
| 1 / 3 | 2.4% | ~60,000 tokens |
| 3 / 3 | 97.2% | ~890 tokens |

`scripts/pick_concurrency.py` measures this per family. It is multi-turn on purpose: a single-shot
benchmark sees only decode contention and will recommend one session, which is wrong.

## Install

```text
npx skills add OpenSWE/deepswe-local-bench
```

Claude Code plugin:

```text
/plugin marketplace add OpenSWE/deepswe-local-bench
/plugin install deepswe-local-bench@deepswe-local-bench
```

## Use

```bash
uv tool install datacurve-pier
git clone https://github.com/datacurve-ai/deep-swe

scripts/run_matrix.py --dry-run                                    # show every command first
scripts/run_matrix.py --n-tasks 1 --suffix smoke --only <server>   # one task, end to end
scripts/run_matrix.py                                              # the whole matrix
scripts/aggregate.py && scripts/render_html.py                     # tables and page
```

The full method, the sandbox networking rule that makes or breaks a run, and the traps worth knowing
are in [`skills/deepswe-local-bench/SKILL.md`](skills/deepswe-local-bench/SKILL.md).

## Two things that will cost you a day if you miss them

**Port 80 is not optional.** Every DeepSWE task runs with `network_mode = "no-network"`, which Pier
implements as an isolated network plus a squid proxy allowing only ports 80 and 443. A server on
8000 is refused and every task fails silently. `scripts/port80_forward.py` binds port 80 under sudo
and forwards to the real port, dropping privileges right after the bind.

**The task images are linux/amd64 only.** On Apple silicon, enable Rosetta before starting, or every
container runs under QEMU at a fraction of the speed.

## Layout

| Path | Role |
|---|---|
| `matrix.toml` | server configurations and the efforts to run against each |
| `scripts/run_matrix.py` | resumable driver |
| `scripts/port80_forward.py` | sandbox-facing port forwarder |
| `scripts/aggregate.py` | job directories → `results/results.json`, `results/RESULTS.md` |
| `scripts/render_html.py` | results JSON → `results/index.html` |
| `DECISIONS.md` | why the benchmark is set up this way |

MIT.

## Resuming

The driver is resumable and idempotent. If the tab closes, the machine reboots, or a run is
interrupted, rerun exactly the same command:

```bash
python3 scripts/run_matrix.py 2>&1 | tee -a runs/driver.log
```

Finished jobs are skipped, an unfinished job is continued with `pier job resume`, and trials that
were cancelled mid-flight are deleted and rerun. `--status` prints one line per planned run.

To publish this repo, create an empty `OpenSWE/deepswe-local-bench` on GitHub and run
`git push -u origin main`. The remote is already set to SSH.
