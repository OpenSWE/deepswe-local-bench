<!-- AI-maintained, append-only -->

# Decisions

Why this benchmark is set up the way it is. Kept per the
[`log-decisions`](https://github.com/OpenSWE/log-decisions) skill. Q1–Q8 record the answers from the
grilling session that scoped the work; later entries are calls made while building and running it.

## Q1 — grill/matrix — tradeoff

**Question:** The request listed "with or without vision" as a benchmark dimension. DeepSWE tasks are text-only; does loading the vision encoder change anything measurable?
**Options considered:** run pass@1 with and without the encoder / measure it as a speed dimension / drop it
**Chosen:** Drop it. No vision encoder is loaded for any row.
**Decided-by:** human
**Justification:** ds4 opens the encoder as a separate lazily-paged mapping and a text-only request never touches it; the text weights file is identical either way (ds4 `docs/MODELS.md`, request path in `ds4_server.c` around the multimodal tokenizer early-return). Neither quality, speed nor resident memory can differ.
**Outcome:** applied
**Ref:** matrix.toml

## Q2 — grill/matrix — tradeoff

**Question:** "With or without MTP" was requested as a dimension. MTP is speculative decoding, near-lossless by design, so it moves tokens/s rather than pass@1. Run it as a quality dimension anyway?
**Options considered:** full pass@1 matrix over MTP on/off / MTP always on / MTP as a throughput-only measurement
**Chosen:** MTP always on wherever the server allows it. DeepSeek V4.1 Flash has no MTP; the server disables MTP for GLM whenever more than one session is batched, so GLM's setting comes from a 3-task pilot (single session with MTP vs 3 sessions without, faster wins).
**Decided-by:** human
**Justification:** ds4 `docs/SPECULATIVE_DECODING.md` and `ds4_server.c` (the `qwen4_batch_mtp` gate): only Qwen3.8 on Metal keeps MTP under batching.
**Outcome:** applied
**Ref:** matrix.toml

## Q3 — grill/effort — gate-resolution

**Question:** The request asked for effort levels low, medium, high, xhigh, max. ds4-server maps `xhigh` and `high` to the same mode, GLM and DeepSeek render `low` and `medium` as high, and `max` silently downgrades to high unless ctx >= 393216 (all but DeepSeek V4.1). Run all five labels?
**Options considered:** all five labels with duplicate rows / distinct levels only / distinct plus a no-thinking row
**Chosen:** Distinct levels only: Qwen low/medium/high/max, GLM high/max, DeepSeek high/max. Footnote the collapse in the table.
**Decided-by:** human
**Justification:** mapping table in `ds4_server.c` (`parse_reasoning_effort_name`) and the Think Max context gate in `ds4.c`; `ds4.h` note that non-Qwen models render low/medium as high.
**Outcome:** applied
**Ref:** matrix.toml

## Q4 — grill/qwen-ctx — tradeoff

**Question:** Qwen3.8's native context is 262144 but `max` needs 393216, reachable only with a 2x YaRN extension the docs warn may cost quality on short prompts.
**Options considered:** skip Qwen max / all Qwen rows at 393216+YaRN plus a native-context control / only max at 393216
**Chosen:** All four Qwen levels at 393216 with `DS4_QWEN4_YARN_FACTOR=2`, plus one control run of `high` at native 262144 per quant to measure the YaRN cost.
**Decided-by:** human
**Justification:** one extra run keeps the effort axis on a single server configuration; ds4 `docs/QWEN38_FLASH_NEXT.md` documents the YaRN env var.
**Outcome:** applied
**Ref:** matrix.toml

## Q5 — grill/table — gate-resolution

**Question:** The leaderboard's "Avg cost" is dollars per task from API prices; a local model has none. What goes in that column?
**Options considered:** wall-clock minutes per task / synthetic dollars from a machine rate / both / drop it
**Chosen:** Wall-clock minutes per task (mean), measured from Pier's agent-execution timestamps. Out tok and Steps carry over unchanged.
**Decided-by:** human
**Justification:** the honest primary number; concurrency is footnoted because it shapes per-task wall-clock.
**Outcome:** applied
**Ref:** scripts/aggregate.py

## Q6 — grill/network — gate-resolution

**Question:** Every DeepSWE task runs with `network_mode = "no-network"`, which Pier implements as an isolated network plus a squid proxy allowing only destination ports 80 and 443. How does the agent container reach ds4-server?
**Options considered:** ds4-server on loopback port 80 / edit each task's network_mode to public / patch Pier's allowlist
**Chosen:** ds4-server binds 127.0.0.1:80; the agent uses `http://host.docker.internal/v1`. macOS allows unprivileged binds below 1024 and Docker Desktop forwards host.docker.internal to the host loopback, so nothing is exposed beyond the machine.
**Decided-by:** human
**Justification:** zero changes to the benchmark or the runner; Pier's squid template (`pier/environments/agent_setup.py`, `Safe_ports`) and its allowlist built from `OPENAI_BASE_URL`.
**Outcome:** applied
**Ref:** matrix.toml `[defaults]`

## Q7 — grill/stats — tradeoff

**Question:** The public leaderboard runs about four rollouts per task and reports 1.96·std/√runs. One rollout everywhere, or four for the full-set rows?
**Options considered:** one rollout plus bootstrap CI over tasks / four rollouts for winners / four everywhere
**Chosen:** One rollout per task for every row; the ± is a 95% bootstrap interval over tasks, labelled as such.
**Decided-by:** human
**Justification:** GLM decodes at about 25 tok/s here, so four rollouts would cost about eight days per GLM configuration. Aggregation follows the leaderboard's error rules: infrastructure errors leave the denominator, timeouts and context exhaustion count as failures.
**Outcome:** applied
**Ref:** scripts/aggregate.py

## Q8 — grill/timeout — tradeoff

**Question:** Tasks allow 3 h of agent wall-clock. Local decode is 5–10x slower than the leaderboard's APIs and the containers run under Rosetta, so a fixed 3 h penalises the setup twice.
**Options considered:** keep 3 h / 6 h and also report the 3 h cutoff post hoc / 6 h only
**Chosen:** `--agent-timeout-multiplier 2.0` (6 h); aggregate.py also reports each row's pass@1 as it would have been at the 3 h cutoff, from trial timestamps.
**Decided-by:** human
**Justification:** one run, two honest numbers.
**Outcome:** applied
**Ref:** matrix.toml, scripts/aggregate.py

## Q9 — setup/deepseek-q4 — deviation

**Question:** The grilling answer approved deleting `DeepSeek-V4.1-Flash-Q4.gguf.assembling.lock` if the file's checksum matched. Should the lock go?
**Options considered:** delete after verifying / keep
**Chosen:** Keep it. The file is verified (size equals part1+part2 exactly; join seam and tail match the remote parts byte for byte; the join script only renames the final file after a SHA-256 pass), but ds4's `download_model.sh` keeps that lock on purpose so two joins can never race on the same path.
**Decided-by:** agent
**Justification:** comment above the `flock` in `download_model.sh`'s Q4 join block: "Keep this lock file".
**Outcome:** applied
**Ref:** ds4 `download_model.sh` (download_ds41_q4)

## Q10 — setup/order — deviation

**Question:** Planned order was Qwen Q2 first as the fastest pipeline check, DeepSeek Q4 last to avoid disk contention with in-flight downloads.
**Options considered:** planned order / DeepSeek first
**Chosen:** DeepSeek V4.1 Flash Q2 then Q4 first; Qwen and GLM follow as their downloads finish. The driver waits for a model file to be complete and unopened before starting its server.
**Decided-by:** human
**Justification:** the user's mid-turn instruction: DeepSeek Q2 and Q4 are the only families fully on disk.
**Outcome:** applied
**Ref:** matrix.toml (server order)

## Q11 — setup/docker — irreversible-action

**Question:** Docker Desktop's VM defaulted to 24 CPUs and 7.7 GiB, far below six concurrent 8 GiB task containers.
**Options considered:** GUI / edit `settings-store.json` / colima
**Chosen:** Wrote `Cpus=16`, `MemoryMiB=65536`, `SwapMiB=4096`, `UseVirtualizationFrameworkRosetta=true` into `~/Library/Group Containers/group.com.docker/settings-store.json` with Docker stopped, then restarted it. Verified 16 CPUs / 62.7 GiB and the `rosetta` binfmt handler inside the VM. Backup of the previous file at `/tmp/settings-store.json.bak`.
**Decided-by:** agent
**Justification:** grilling answer accepted 16 CPUs / 64 GiB with Rosetta; the file edit is the only scriptable route (`docker desktop` CLI has no settings command).
**Outcome:** applied
**Ref:** scripts/run_matrix.py (assumes the daemon is up)

## Q12 — setup/binaries — gate-resolution

**Question:** The ds4 binaries were built 2026-09-15 21:52, but `ds4.c`/`ds4_server.c` changed in commits on 2026-09-16 (batched Qwen MTP, oversized-request rejection).
**Options considered:** use stale binaries / rebuild
**Chosen:** `make -j12 all` at HEAD 8db1d1d before any run.
**Decided-by:** agent
**Justification:** every server behaviour cited in this journal was read from the current sources.
**Outcome:** applied
**Ref:** ds4 HEAD 8db1d1d

## Q13 — setup/port80 — deviation

**Question:** Grilling Q17 chose "ds4-server binds 127.0.0.1:80" on the premise that macOS permits an unprivileged bind below 1024. The server refused to start: `failed to listen on 127.0.0.1:80: Permission denied`.
**Options considered:** run ds4-server under sudo / a root-owned forwarder on 80 to the server's real port / pf redirect / patch Pier's squid allowlist
**Chosen:** `scripts/port80_forward.py`, started with passwordless sudo, binds 127.0.0.1:80 and forwards to 127.0.0.1:8000, then drops to the invoking uid immediately after the bind. ds4-server stays unprivileged on 8000.
**Decided-by:** agent
**Justification:** keeps the original intent of Q17 (no benchmark or runner changes, loopback only, nothing on the LAN) while running a ~40-line forwarder as root instead of a 150 GiB inference server. Verified end to end: an amd64 container reaches `http://host.docker.internal/v1/models`, and a tool-calling chat completion returns `finish_reason: "tool_calls"`.
**Outcome:** applied
**Ref:** scripts/port80_forward.py, matrix.toml `[defaults] forward_port`

## Q14 — setup/job-done — deviation

**Question:** The driver treated the presence of `jobs/<job>/result.json` as proof a job had finished, so it would skip or mis-resume live jobs.
**Options considered:** presence of the file / require a `finished_at` timestamp / count trials
**Chosen:** A job counts as done only when `result.json` carries a non-null `finished_at`.
**Decided-by:** agent
**Justification:** observed directly in the smoke run: Pier writes `result.json` at job start with `finished_at: null` and `n_running_trials: 1`, updating it as trials land.
**Outcome:** applied
**Ref:** scripts/run_matrix.py (job_done)

## Q15 — setup/model-ready — deviation

**Question:** The driver's "weights are fully downloaded" check rejected any file held open by another process, so it waited forever on a model the inference server itself had mapped.
**Options considered:** drop the open-handle check / detect writers only / rely on size stability alone
**Chosen:** Detect *writers* only, via `lsof -Fan` access modes, alongside no `.assembling` sibling and a stable size across a quiet minute. Readers are expected: the server mmaps the weights.
**Decided-by:** agent
**Justification:** the in-flight downloads write to temporary names, so a complete file with only readers is genuinely ready; verified against both the served Q2 file and the two downloads running in other tabs.
**Outcome:** applied
**Ref:** scripts/run_matrix.py (has_writer, model_ready)

## Q16 — setup/github — escalated

**Question:** Grilling Q10 approved publishing the skill repo publicly in the OpenSWE GitHub organization. `gh repo create` failed: the active token carries only `admin:public_key`, `admin:ssh_signing_key`, `read:user` and `user:email`.
**Options considered:** create the repo with a differently-scoped token / ask the user to create it / skip publishing
**Chosen:** —
**Decided-by:** agent
**Justification:** only a human can grant the `public_repo` scope or create the repository. The local repository at `~/github.com/OpenSWE/deepswe-local-bench` is committed and complete, which satisfies the literal request; publishing waits for a token or a repository created by hand, after which `git push -u origin main` finishes it.
**Outcome:** escalated
**Ref:** (pending)

## Q17 — run/glm-pilot — gate-resolution

**Question:** Grilling Q23 chose a 3-task pilot to settle GLM's session count, since ds4 disables MTP whenever more than one session is resident. What runs until the pilot happens?
**Options considered:** block GLM rows on the pilot / ship a default and pilot when GLM's turn arrives
**Chosen:** Default to 3 sessions without MTP in matrix.toml, and run the pilot immediately before the first GLM row:
`scripts/run_matrix.py --only glm-5.3-flash-q2 --efforts high --n-tasks 3 --suffix pilot-mtp --sessions 1 --mtp` against the same three tasks at `--sessions 3 --no-mtp`, keeping the faster.
**Decided-by:** agent
**Justification:** agent workloads are bursty — a session idles while its container runs a shell command — so overlapping sessions should beat a 1.3–1.6x single-stream MTP gain, especially as GLM's native batching falls back to ordered decoding past about 2051 visible tokens, which every agent context exceeds. The pilot decides it on measurement rather than this reasoning; GLM's turn is days away, so nothing is blocked meanwhile.
**Outcome:** assumed
**Ref:** matrix.toml (glm-5.3-flash-q2)

## Q18 — run/concurrency — deviation

**Question:** Grilling Q21 set concurrency at (Qwen 12, DeepSeek 6, GLM 3) resident sessions, reasoning from ds4's documented native session batching. The first live run contradicted it: DeepSeek V4.1 Flash Q2 decoded at about 1.0 tok/s per session across 6 sessions at 20k–87k contexts, against 15.4 tok/s single-session.
**Options considered:** keep the planned session counts / measure aggregate throughput against session count and use the winner
**Chosen:** Measure, then decide per family with `scripts/pick_concurrency.py`. For DeepSeek V4.1 Flash Q2 the measured aggregate output throughput at a 21k-token prompt was: 1 session 6.44 tok/s, 2 sessions 1.95, 3 sessions 2.24, 6 sessions 2.80. A single resident session is 2.3x the best batched setting, so DeepSeek runs unbatched.
**Decided-by:** agent
**Justification:** ds4's published batching figures are measured at 1k contexts (`QA_BEFORE_RELEASES.md`), while agent trajectories here reach 20k–87k tokens, where per-session decode collapses. Running 18 configurations at the planned setting would have cost days for a 2.3x throughput loss. The run was stopped 45 minutes in, before any row was scored, so nothing measured under the wrong setting reaches the results.
**Outcome:** applied
**Ref:** scripts/pick_concurrency.py, runs/pick-deepseek-q2.txt

## Q19 — run/pier-concurrency — tradeoff

**Question:** With one resident session, does Pier still get to run several tasks at once, so container and shell time overlaps model time?
**Options considered:** Pier concurrency 1, strictly serial / Pier concurrency above the server's slot count, letting the server queue
**Chosen:** Keep Pier's task concurrency above the server's session count and let ds4 queue the extra requests, provided the queued measurement shows no aggregate loss against a single client.
**Decided-by:** agent
**Justification:** ds4 queues requests when all slots are busy rather than rejecting them (`docs/SERVER.md`). Agent steps are mostly model time, so the overlap gain is modest, but it is free if queuing costs nothing. Measured with `--sessions 1 --clients 3`.
**Outcome:** applied
**Ref:** scripts/pick_concurrency.py (--clients), runs/pick-deepseek-q2-queued.txt

## Q18 — Verifier proven independently with Pier's oracle agent
**Context:** After 90 minutes the first agent trials still had not reached the verifier, leaving the
last link in the pipeline untested while a multi-day sweep was already committed.
**Decision:** Run `pier run --agent oracle` on one task. The oracle applies the task's reference
solution, so it exercises collect-hook, patch, verifier image and grader without the model at all.
**Result:** `abs-module-cache-flags` scored `reward=1`, 20/20 fail-to-pass and 3/3 pass-to-pass.
**Why it matters:** ~8 minutes of work validated the stage that would otherwise have been unproven
for hours, and it is now the documented first step in the skill.

## Q19 — Run order corrected to Qwen Q2 first
**Context:** The accepted plan put Qwen Q2 first (on disk, ~2.5x faster than DeepSeek). The matrix
file as written ran DeepSeek Q2 first, so the driver started on the slowest family.
**Decision:** Reorder to Qwen Q2 -> Qwen Q2 native -> DeepSeek Q2 -> GLM Q2 -> Qwen Q4 -> Qwen Q4
native -> GLM Q4 -> DeepSeek Q4, and restart the driver. The interrupted DeepSeek trials were
written with `CancelledError`, which `pier job resume` deletes and reruns by default, so nothing
is lost beyond ~75 minutes of compute.
**Why:** Matches the accepted order and puts the first complete configuration hours sooner.

## Q20 — Observed task cost on DeepSeek V4.1 Flash Q2
**Context:** Needed a defensible runtime projection for the full matrix.
**Measured:** three trials cancelled at 75 minutes each had reached 51 agent steps and 17.6k / 23.3k
/ 30.2k output tokens, with the server ~100% busy throughout (305 completed phases in 71 minutes,
median 5s between completions).
**Implication:** roughly 2.2 days per configuration for this family, so the 18-row matrix is on the
order of 40 days rather than the ~2 weeks estimated before measurement. Recorded rather than acted
on: the accepted budget is unlimited, and the cheapest trim if that changes is Qwen's low/medium
efforts, which the server renders distinctly only for Qwen.

## Q21 — Verified that reasoning_effort survives litellm's drop_params
**Context:** mini.yaml sets `drop_params: true`. litellm drops parameters it thinks a provider does
not support, and a silently dropped `reasoning_effort` would make all 18 rows differ only in name.
**Check:** pointed the pinned litellm at a local echo server and inspected the outgoing body.
**Result:** body carried `reasoning_effort: low` and `seed: 0`, and carried no `temperature`, so the
server's default sampling applies — matching the leaderboard, which sets no temperature either.
**Why it matters:** this is the single assumption the whole effort axis rests on, and it is cheap to
verify and cheap to regress on a litellm upgrade. Added to the skill as a pre-sweep step.

## Q22 — Sessions raised to match clients; my concurrency benchmark was measuring the wrong thing
**Context:** Under 1 resident session with 3 concurrent agents, the step rate decayed steadily
(1.47/min at 15 min, 0.50/min at 120 min) and no task finished in two hours.
**Cause:** an agent re-sends its whole history every step, so a single slot cannot hold three
conversations — they evict each other and each step re-prefills the full context. Measured from the
server log: median prefix reuse **2.4%**, ~60k tokens re-prefilled per step, 1,513,771 prefill
tokens across 25 steps.
**Fix:** `sessions = clients = 3` on every row. Re-measured: median reuse **97.2%**, ~890 tokens per
step, 26,760 across 30 steps — a 67x reduction in prefill work. Early step rate went from 66 steps
in 15 minutes to 70 in 5. Speculative decoding stays active (Qwen/Metal keeps it for 2-16 sessions)
and the planned memory line was unchanged, because slots share the prefill workspace.
**The deeper error:** `pick_concurrency.py` fired fresh, unrelated prompts, which measures decode
contention only — under that test one session always wins, and it is what led me to `sessions = 1`
in Q17. It is now multi-turn and reports reuse per row from
`usage.prompt_tokens_details.cached_tokens` (verified present on this server). A benchmark whose
workload shape differs from the real one will confidently recommend the wrong setting.
**Cost:** ~2 hours of trials discarded to keep the comparison clean and the matrix uniform.

## Q23 — The session fix scales with trajectory length (the point of it)
**Evidence, same run, as contexts grew:** first 30 prompts — 85.2% median reuse, max context 25,424,
45,028 prefill tokens. Latest 30 prompts — 99.0% reuse, max context 59,235, 20,123 prefill tokens.
Reuse *rose* and total prefill work *fell* while contexts more than doubled.
**Why it matters:** under 1 slot, per-step cost grew with trajectory length, which is why the step
rate decayed from 1.47/min to 0.50/min over two hours. With a slot per agent, per-step cost is flat,
and the aggregate rate held at ~13 steps/min across the same growth. Long-horizon agent benchmarks
are dominated by this, not by raw decode speed.
**Projection:** ~12 hours per configuration for this family, against the ~2.5 days implied by the
old configuration.

## Q24 — Stayed at 3 sessions rather than testing 6
**Context:** with prefill effectively free (99.9% reuse), decode became the bottleneck. Qwen/Metal
supports 2-16 sessions with speculative decoding, so more slots could raise aggregate decode.
**Observed:** ~60 tok/s aggregate at 1 session with MTP, ~90 at 3 (28-32 per session). A 1.5x gain
for 3x the slots, i.e. clearly diminishing — the GPU is near saturation.
**Decision:** keep 3. A third sweep restart costs in-flight trials, more slots need proportionally
more KV and one more 8 GiB container each competing for CPU during tool execution, and the expected
gain is maybe 1.2x. The 67x prefill win is already captured.
**Revisit:** the driver restarts the server only when weights or context change, so the next free
opportunity is after the four Qwen Q2 efforts. Measure with `scripts/pick_concurrency.py --sessions
3,6 --turns 8` before changing anything.
**Also worth noting:** step cost varies enormously with this model — single steps ranged from 74 to
7,752 generated tokens (3s to 280s), so short-window step rates are noise. Average over >10 minutes.
