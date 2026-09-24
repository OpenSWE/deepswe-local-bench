# DeepSWE on DwarfStar (ds4) — local results

Generated 2026-09-24 06:53 PDT. 113 tasks, one rollout per task, mini-swe-agent 2.3.0 via Pier, Apple M3 Ultra 512 GB. Pass@1 ± is a 95% bootstrap interval over tasks.

| Model | Pass@1 | Pass@1 @3h | Avg min/task | Out tok (k) | Steps | Tasks |
|---|---:|---:|---:|---:|---:|---:|
| Qwen3.8 Flash Next Q2 [medium] ★ | 58% ±9 | 58% | 76.0 | 93 | 121 | 113/113 |
| Qwen3.8 Flash Next Q2 [low] | 56% ±9 | 56% | 51.1 | 72 | 124 | 112/113 (1 infra) |
| Qwen3.8 Flash Next Q2 [high] | 51% ±14 | 49% | 125.3 | 137 | 153 | 43/113 |

★ best effort level within a (family, quant, context) group.  
Effort labels are the ones ds4-server distinguishes: `xhigh` equals `high`; GLM and DeepSeek render `low`/`medium` as `high`; `max` needs a 393216-token context on Qwen and GLM.  
Avg min/task is wall-clock of the agent phase under the row's concurrency (sessions column in results.json); Pass@1 @3h re-scores each task as a failure if the agent phase exceeded the leaderboard's 3 h limit.  
Tasks = counted / total; infra = harness errors excluded from the denominator.
