#!/usr/bin/env python3
"""Print one line per newly finished Pier trial. Used as a Monitor source."""
import json, sys, time
from pathlib import Path

root = Path(sys.argv[1])
seen: set[Path] = set()

while True:
    for f in sorted(root.glob("*/result.json")):
        if f in seen:
            continue
        try:
            r = json.loads(f.read_text())
        except Exception:
            continue
        v = r.get("verifier_result") or {}
        a = r.get("agent_result") or {}
        ex = r.get("exception_info") or {}
        rew = (v.get("rewards") or {}).get("reward")
        if rew is None and not ex:
            continue  # still being written
        seen.add(f)
        print(
            f"{f.parent.name[:36]:36s} reward={rew} steps={a.get('n_agent_steps')} "
            f"out_tok={a.get('n_output_tokens')} exc={ex.get('exception_type')}",
            flush=True,
        )
    time.sleep(15)
