# Whole-fleet backup & restore — take nemofleet to another host

NemoClaw only snapshots **individual** sandboxes. `make export` / `make import` bundle the **whole
fleet's** portable state so the system can be moved to a new machine. The design splits a running
fleet into three layers; only Layer 1 is backed up, Layer 2 is re-derived, Layer 3 is a prerequisite.

## The three layers

**Layer 1 — portable state (this is what gets backed up).** The fleet's identity + memory that isn't
in git and can't be regenerated:

| Group | What | Where |
|---|---|---|
| Secrets | bridge token, approval key, NVD key, the self-signed dashboard CA + TLS cert/key, dashboard users | `services/bridge/` (git-ignored) |
| | `.env` (SMTP / Jira / Telegram) | repo root |
| NemoClaw state | the tamper-evident admin-audit chain **and its HMAC key** (both — the key is stored separately by design), the governance-ledger seen-set, the EBG19P device credential + device audit, the notify env | `~/.config/nemoclaw/` |
| Host runtime | proactive snapshots/logs, eval ledgers + lessons, skill r_task stats | `data/`, `eval/`, `skills/` |
| Sandbox WD | per-worker: agent settings (incl. `patrol_auto`), scan histories, governance verdict histories (review/curation/rollback/guardrail/approval), EBG19P baselines + the **known-good config backups**, asset inventory | inside each worker sandbox (`docker cp`'d out) |

Re-derivable caches are **excluded** (the SAST source clone — worker-b re-fetches it from GitHub on
the next scan — and python caches), keeping the bundle small.

**Layer 2 — re-derived at boot (not backed up).** Container names, IPs, gateway port, forwards, and
OpenShell policies. `boot-stack.sh` re-renders all of these from the Layer 1 secrets every boot —
which is exactly why moving hosts works. `import` runs `make boot` at the end to regenerate them.

**Layer 3 — prerequisites on the target host (not something a backup can provide).** `import` *checks*
these and refuses to proceed if they're missing:

- NemoClaw + OpenShell installed, a running NIM (Nemotron) inference endpoint (`provisioning/install-prereqs.md`)
- the 4 OpenShell sandboxes (team-lead + worker-a/b/c) already created (provisioning / onboard)
- the repo checked out at the bundle's `git_commit` (so code + restored data match)
- network reachability to the EBG19P device (physical — not portable; a replacement at the same address works)

## Usage

```bash
# on the source host — produce one archive (default: $HOME/nemofleet-export-<ts>.tar.gz, chmod 600)
make export
make export ARGS='--gpg you@example.com'      # optional: gpg-encrypt (bundle holds every secret)

# move the archive to the target host over an encrypted channel, then on the target:
make import ARGS='nemofleet-export-<ts>.tar.gz --dry-run'   # show the plan, change nothing
make import ARGS='nemofleet-export-<ts>.tar.gz'             # preflight → restore Layer 1 → make boot
```

`--dry-run` runs the full Layer-3 preflight and prints every restore action without touching anything.
`--no-boot` skips the final `make boot` (run it yourself later). `import` overwrites the target's
secrets + sandbox data, so it prompts for confirmation unless `--yes`.

## Security

The bundle contains **every** token, key, TLS private key, and the EBG19P device password. Treat it as
top-secret: `export` sets it `chmod 600`, `.gitignore` blocks `nemofleet-export-*.tar.gz*`, and moving
it between hosts should go over an encrypted channel (`--gpg`, or `scp`/`age`). It is not committed and
never should be.

## What restore does NOT do

- It doesn't install NemoClaw/OpenShell or start a NIM (Layer 3 — do that first).
- It doesn't create the sandboxes (Layer 3) — it errors telling you which are missing.
- It doesn't bundle NemoClaw's per-agent container snapshots (large + version/host-specific). The
  worker code is redeployed by `make boot`; the worker **data** is restored from the bundle — same
  result, cleaner.
- The physical EBG19P isn't portable; its credential + baselines + known-good config backups are, so a
  target host that can reach the same (or a replacement) device is fully functional.

## After a restore: the audit chain may show "broken" (expected — here's why)

The tamper-evident admin-audit chain (`~/.config/nemoclaw/admin-audit.jsonl`) hashes each entry with
`HMAC(key, prev_hash + entry)`, where `key` lives in a **separate** file (`admin-audit.hmac-key`) that
is *not* in the log — so an attacker who can rewrite the whole log but doesn't have the key can't forge
a chain that passes `verify_audit()`. That separation is the whole security property (see
`docs/design/worker-c-spec.md` and the `test_full_chain_recompute_without_key_is_detected` unit test).

A **restore/import replaces that key file along with everything else.** If the bundle's key differs from
whatever key the target host's *pre-existing* log was written under (e.g. you restore onto a host that
already had its own audit history, or the bundle predates later live entries), those older entries stop
verifying under the now-current key. The dashboard footer / Overview attention strip will show **"audit
chain broken."** This is the mechanism working correctly, not tampering: the log is still one continuous
chain (prev-hash pointers intact, no gaps) — only the key behind the hashes changed at one clean point.

Diagnose it (read-only): `make audit-rebaseline ARGS=--dry-run` — reports the break seq, how many entries
are orphaned under the old key vs. valid under the current key, and the single key-transition seq (a
*single* transition point is the signature of one clean rotation = benign; multiple/scattered mismatches
would warrant a tampering investigation of the archived log first).

Fix it, **only once you've confirmed the cause is a benign rotation** — `make audit-rebaseline`:
- **archives the entire old chain verbatim** to `admin-audit.jsonl.pre-rebaseline-<ts>` (nothing rewritten
  — it stays independently inspectable for forensics),
- writes a fresh `audit-rebaseline` genesis entry under the current key whose detail **hash-references the
  archived chain's last hash** (so the rotation itself is auditable and the continuity is provable),
- and pauses/restarts the dashboard around it so no live write races the swap.

It deliberately does **not** re-hash the old entries under the new key — that would be forging the ledger,
exactly the attack `verify_audit()` exists to catch. If you can't rule out tampering, don't run it;
investigate the archived log first. The implementation is `scripts/audit-rebaseline.sh`.
