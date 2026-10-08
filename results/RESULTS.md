# DeepSWE on DwarfStar (ds4) — local results

Generated 2026-10-08 10:36 PDT. 113 tasks, one rollout per task, mini-swe-agent 2.3.0 via Pier, Apple M3 Ultra 512 GB. Pass@1 ± is a 95% bootstrap interval over tasks.

| Model | Pass@1 | Partial | Pass@1 @3h | Avg min/task | Out tok (k) | Steps | Tasks |
|---|---:|---:|---:|---:|---:|---:|---:|
| Qwen3.8 Flash Next Q2 (native ctx) [high] ★ | 71% ±16 | 98% | 65% | 118.9 | 118 | 130 | 31/113 (82 infra) |
| Qwen3.8 Flash Next Q2 [medium] ★ | 59% ±9 | 96% | 58% | 73.5 | 94 | 122 | 113/113 |
| Qwen3.8 Flash Next Q2 [low] | 56% ±9 | 98% | 56% | 51.1 | 72 | 124 | 112/113 (1 infra) |
| Qwen3.8 Flash Next Q2 [high] | 56% ±9 | 97% | 52% | 128.8 | 139 | 161 | 113/113 |
| Qwen3.8 Flash Next Q2 [max] | 56% ±9 | 96% | 51% | 130.1 | 140 | 158 | 113/113 |

★ best effort level within a (family, quant, context) group.  
Effort labels are the ones ds4-server distinguishes: `xhigh` equals `high`; GLM and DeepSeek render `low`/`medium` as `high`; `max` needs a 393216-token context on Qwen and GLM.  
Avg min/task is wall-clock of the agent phase under the row's concurrency (sessions column in results.json); Pass@1 @3h re-scores each task as a failure if the agent phase exceeded the leaderboard's 3 h limit.  
Partial is the mean fraction of f2p+p2p tests passed, so it credits a run that fixed most of the bug; a trial with no verifier result (agent timeout) counts as 0.  
Tasks = counted / total; infra = harness errors excluded from the denominator.
