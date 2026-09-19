---
name: deepswe-local-bench
description: Benchmark a local OpenAI-compatible inference server on DeepSWE (113 long-horizon SWE tasks) across a matrix of models, quantizations, reasoning efforts and speculative-decoding settings, then render a leaderboard-style table, JSON and static HTML page. Use when asked to score a locally served model on DeepSWE or SWE-bench-style agentic tasks, compare quantizations or reasoning efforts on pass@1, reproduce the deepswe.datacurve.ai table for local models, or drive Pier plus mini-swe-agent against llama.cpp, DwarfStar ds4-server, vLLM, SGLang or any /v1/chat/completions endpoint.
---

# DeepSWE against a local inference server

Scores a locally served model on [DeepSWE](https://deepswe.datacurve.ai/) — 113 contamination-free
software-engineering tasks across 91 repositories and 5 languages — using the same harness the public
leaderboard uses, so rows sit next to published ones.

The moving parts: **Pier** runs each task in a Docker sandbox, **mini-swe-agent** is the agent inside
it, and your server answers `/v1/chat/completions`. One `matrix.toml` declares every server
configuration; `scripts/run_matrix.py` walks it, restarting the server only when the model file or
context changes, because reasoning effort is a per-request field.

## Setup

```bash
uv tool install datacurve-pier                       # the runner; needs Python >= 3.12
git clone https://github.com/datacurve-ai/deep-swe   # the 113 tasks
```

Docker must be running with enough room for `n_concurrent` task containers at 8 GiB each, and the
task images are **linux/amd64 only** — on Apple silicon enable Rosetta (Docker Desktop: Apple
Virtualization plus "Use Rosetta"; colima: `--vm-type vz --vz-rosetta`). Without it every container
falls back to QEMU and runs several times slower. Verify with:

```bash
docker run --rm --platform linux/amd64 alpine uname -m     # must print x86_64
```

## Prove the verifier before the sweep

An agent trial can run for hours before it ever reaches the verifier, so a broken grading stage
stays invisible while days of compute are already committed. Pier's `oracle` agent applies each
task's own reference solution, which exercises the collect hook, the patch, the separate verifier
image and the grader without the model at all:

```bash
pier run -p <tasks> --agent oracle -i '<one-task-name>' -n 1 -k 1 -o /tmp/oracle-check --job-name oracle -y -q
cat /tmp/oracle-check/oracle/*/verifier/reward.json
```

Expect `{"reward": 1, ...}` with every fail-to-pass and pass-to-pass test passing. It takes minutes
and needs no inference server. Do this before launching the matrix.

## The port-80 rule

Every DeepSWE task declares `network_mode = "no-network"`. Pier implements that as an isolated
Docker network plus a squid proxy whose generated config contains `acl Safe_ports port 80 443`, so
**a server on any other port is refused with 403** and the agent silently fails every task. Two
consequences:

- Point the agent at `http://host.docker.internal/v1`, port 80 implied. Never `127.0.0.1` — that is
  in the container's `NO_PROXY` and resolves to the container itself.
- On macOS a normal user cannot bind port 80, so `scripts/port80_forward.py` binds it under `sudo`
  and forwards to the real server port, dropping privileges immediately after the bind. The
  inference server itself stays unprivileged. On Linux, bind port 80 directly and skip the forwarder.

Confirm the route before a long run:

```bash
docker run --rm --platform linux/amd64 curlimages/curl -sS http://host.docker.internal/v1/models
```

## Running a matrix

```bash
scripts/run_matrix.py --dry-run                            # print every server and pier command
scripts/run_matrix.py --n-tasks 1 --suffix smoke --only <server-id>    # one task, end to end
scripts/run_matrix.py                                      # the whole matrix, in order
```

Resumable by construction: a job with a `result.json` is skipped, a half-finished job directory is
resumed with `pier job resume`, and a job is retried up to three times. Kill it whenever and rerun the
same command. `--n-tasks` requires `--suffix` so a subset can never shadow a full run.

Each `[[server]]` block gives the model file, context, session count, whether to enable speculative
decoding, an optional environment overlay, and the list of efforts to run against it. The driver waits
for a model file that is still downloading: it requires the file to exist, have no `.assembling`
sibling, hold no open write handle, and keep a stable size for a minute.

## Reading the results

```bash
scripts/aggregate.py        # jobs/ -> results/results.json + results/RESULTS.md
scripts/render_html.py      # results.json -> results/index.html
```

Aggregation follows the leaderboard's error rules: harness failures such as an image build error or a
verifier crash leave the denominator, while an agent timeout or context exhaustion counts as a failed
attempt. With one rollout per task the ± is a 95% bootstrap interval over tasks, which is **not** the
leaderboard's across-rollout interval, so label it wherever it is published.

## Prove the effort axis reaches the server

mini-swe-agent's pinned config sets litellm's `drop_params: true`, and litellm drops parameters it
believes a provider does not support. If it dropped `reasoning_effort`, every effort row would be
an identical run under a different name and the matrix would be meaningless. Verify before
sweeping, with a throwaway HTTP server that prints the request body:

```python
import litellm
litellm.drop_params = True
litellm.completion(model="openai/<your-id>", messages=[{"role":"user","content":"hi"}],
                   reasoning_effort="low", seed=0)
```

Measured against litellm as pinned here, the body carried `reasoning_effort`, carried `seed`, and
carried no `temperature`, so the server's own default sampling applies. That is the leaderboard's
condition, which sets no temperature either. Re-check after any litellm upgrade.

## Traps worth knowing

- **Effort labels collapse.** A server may map several of `low`/`medium`/`high`/`xhigh`/`max` to the
  same internal mode, and a maximum-thinking mode may need a minimum context to engage at all. Probe
  the mapping in the server's own source or docs before spending days on rows that are duplicates.
- **`model` is usually a free-form label.** A single-model server answers whatever name you send, so
  use the name as the row label. It does not select a model.
- **Pier forces the Responses API** for any model named `openai/…`. Pass `--ak model_class=litellm`
  to use `/v1/chat/completions` instead.
- **mini-swe-agent 2.3.0 uses native tool calling**, not fenced bash blocks. The server must accept
  `tools` and return `tool_calls` with `finish_reason: "tool_calls"`. Check with one curl before a run.
- **Cost is blank for an unpriced model.** litellm has no price entry, so Pier records null and the
  cost column is meaningless. Report wall-clock minutes per task instead.
- **Batched sessions can be much slower, not faster.** Published batching figures are often measured
  at ~1k contexts, while agent trajectories reach 20k-100k, where per-session decode can collapse.
  Measured on ds4 + DeepSeek V4.1 Flash Q2 at 21k-token prompts: **6.44** aggregate output tok/s with
  one resident session against **2.80** with six, a 2.3x loss. Run `scripts/pick_concurrency.py`
  before every family and trust the number over the documentation.
- **Concurrency should come from queued clients, not slots.** The same server with one slot serving
  three concurrent clients held **6.34** tok/s, so extra agents queue for free and their container
  time overlaps. Keep `sessions = 1` and raise `clients`. One slot also re-enables speculative
  decoding on servers that disable it while batching.
- **A first run pays for 113 emulated image builds.** They cache, so only the first configuration is slow.
- **Concurrency shapes wall-clock per task**, so never compare minutes across rows that ran at
  different session counts without saying so.

## Files

| Path | Role |
|---|---|
| `matrix.toml` | every server configuration and its effort list |
| `scripts/run_matrix.py` | resumable driver: waits for weights, starts the server, runs Pier |
| `scripts/port80_forward.py` | root-owned 80 → server-port forwarder for the sandbox |
| `scripts/aggregate.py` | job directories → `results/results.json` and `RESULTS.md` |
| `scripts/render_html.py` | results JSON → static leaderboard page |

## Running it in a herdr tab

A full matrix takes days, so give it its own tab rather than a foreground shell:

```bash
TAB=$(herdr tab create --workspace "$HERDR_WORKSPACE_ID" --label deepswe-bench --no-focus \
      | python3 -c 'import sys,json; print(json.load(sys.stdin)["result"]["root_pane"]["pane_id"])')
herdr pane run "$TAB" "cd <repo> && python3 scripts/run_matrix.py 2>&1 | tee -a runs/matrix.log"
herdr pane read "$TAB" --source recent --lines 40        # check on it later
```

The driver is resumable, so a closed tab or a reboot costs only the task in flight.
