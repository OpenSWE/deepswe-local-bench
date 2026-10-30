# DeepSWE on DwarfStar (ds4) — local results

Generated 2026-10-30 15:35 PDT. 113 tasks, one rollout per task, mini-swe-agent 2.3.0 via Pier, Apple M3 Ultra 512 GB. Pass@1 ± is a 95% bootstrap interval over tasks.

| Model | Pass@1 | f2p | Partial | Pass@1 @3h | Avg min/task | Out tok (k) | Steps | Tasks |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Qwen3.8 Flash Next Q4 [high] ★ | 90% ±15 | 100% | 100% | 90% | 76.1 | 107 | 143 | 10/113 (3 infra) |
| Qwen3.8 Flash Next Q2 [medium] ★ | 59% ±9 | 90% | 96% | 58% | 73.5 | 94 | 122 | 113/113 |
| Qwen3.8 Flash Next Q4 [medium] | 59% ±14 | 94% | 96% | 59% | 47.0 | 67 | 91 | 51/113 |
| Qwen3.8 Flash Next Q4 [low] | 57% ±9 | 93% | 97% | 57% | 46.7 | 63 | 116 | 112/113 (1 infra) |
| Qwen3.8 Flash Next Q2 (native ctx) [high] ★ | 57% ±9 | 77% | 96% | 53% | 138.3 | 117 | 132 | 113/113 |
| Qwen3.8 Flash Next Q2 [low] | 56% ±9 | 94% | 98% | 56% | 51.1 | 72 | 124 | 112/113 (1 infra) |
| Qwen3.8 Flash Next Q2 [high] | 56% ±9 | 89% | 97% | 52% | 128.8 | 139 | 161 | 113/113 |
| Qwen3.8 Flash Next Q2 [max] | 56% ±9 | 88% | 96% | 51% | 130.1 | 140 | 158 | 113/113 |

★ best effort level within a (family, quant, context) group.  
Effort labels are the ones ds4-server distinguishes: `xhigh` equals `high`; GLM and DeepSeek render `low`/`medium` as `high`; `max` needs a 393216-token context on Qwen and GLM.  
Avg min/task is wall-clock of the agent phase under the row's concurrency (sessions column in results.json); Pass@1 @3h re-scores each task as a failure if the agent phase exceeded the leaderboard's 3 h limit.  
f2p is the mean fraction of fail-to-pass tests passed - the tests the bug broke, so this is the repair signal. Partial adds p2p (tests that already passed), and the median task has 165 p2p against 44 f2p, so Partial stays high for a run that changed nothing: DeepSeek Q2 scored 85.9% Partial with 0.0% f2p. Read f2p; keep Partial only to see the gap. A trial with no verifier result (agent timeout) counts as 0 in both.  
Tasks = counted / total; infra = harness errors excluded from the denominator.
