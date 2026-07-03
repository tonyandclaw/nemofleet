# knowledge/ — the fleet's shared knowledge (single source of truth)

The **one canonical copy** of the facts every node must agree on. `boot-stack.sh` syncs this
directory into each **worker** (which loads it via `services/bridge/knowledge.py`), and team-lead
reads the same **live** via `GET /knowledge`. So the **same** baseline/security-keys drive
worker-a's drift detection **and** what team-lead reads back (an A2A/MCP-shaped read).

This is the "shared context layer": it exists so agents don't each know different facts — the
[most common reason multi-agent orchestration fails in production](https://docs.nvidia.com/nemo/agent-toolkit/1.6/components/integrations/a2a.html) is context inconsistency.

| File | What it is | Who reads it |
|---|---|---|
| `baselines/ebg19p.conf` | Approved EBG19P config baseline — the "correct" state | worker-a compares drift; team-lead cites in reports |
| `security-keys.json` | Which key deviations = a **security** regression (vs. a benign pending-review drift) | worker-a classifies; team-lead reports severity |

## How it's read
- **Locally / on the host:** `knowledge.py` defaults `KNOWLEDGE_DIR` to this repo dir.
- **In a sandbox:** `boot-stack.sh` copies this dir to `/usr/local/share/nemofleet-knowledge` and
  sets `KNOWLEDGE_DIR` so the worker reads the synced copy. If it is ever missing, `knowledge.py`
  falls back to an embedded default so the worker still functions (degraded, flagged by `version`).
- **Consistency check:** `knowledge.version()` is a hash of the canonical files; every node exposes
  it (`GET /knowledge` → `version`) so you can confirm the whole fleet is on the same knowledge.

## Changing shared knowledge
Edit the file here (one place), commit, re-run `make boot` (or the sync step). All nodes pick up the
new `version`. Do **not** edit the synced copies inside sandboxes — they are overwritten on boot.

## Upgrade path (full MCP)
Today this is served natively (`GET /knowledge` + boot sync). The NVIDIA-standard upgrade is to expose
the same content through an **MCP server** that each agent mounts as an MCP client — same knowledge,
standard protocol. The content model here is already MCP-shaped, so that is an adapter, not a rewrite.
