# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

nemofleet is a policy-governed multi-agent fleet for ASUS network-device IT operations. Four
nodes (**team-lead**, **worker-a**, **worker-b**, **worker-c**) all run the **Hermes** harness on
a local NVIDIA NIM (Nemotron 3 Super 120B) endpoint, each in its own **OpenShell** sandbox.
team-lead is the human-facing front desk (Telegram/Email intake, triage, self-evolving skills);
worker-a is ops (drift/cert/EBG19P remediation); worker-b is security (CVE/SBOM/SAST/syslog);
worker-c is governance (backup/firmware/rollback, QA review gate over a/b, skill curation).
NemoClaw (agent lifecycle) and OpenShell (sandbox isolation + egress policy) are installed CLI
products consumed by this repo, not vendored here.

**One real managed device**: ASUS ExpertWiFi EBG19P (`lab-asus-ebg19p-01`) — read-only
monitoring plus governed nvram-apply remediation. There are no mocks for devices or backends
(SMTP/Jira are real); tests that need those are gated by device/fleet availability (see below).

Read `README.md` first for the full picture (repo layout, quickstart, guardrails). Read
`docs/design/architecture.md` for the node/role diagram and `docs/design/governance-inventory.md`
for how OpenShell policy enforcement actually works (updated 2026-07-10 against a live 4-node
policy dump — re-verify with `openshell policy get <sb> --full` before trusting exact preset names
if this drifts again; the doc itself now flags what it couldn't confirm, e.g. dynamic device-egress
rules and whether "policy tier" is still a live concept).

## Commands

```bash
make bootstrap   # first-time setup on a new device (certs, bridge token, runtime config)
make boot        # bring up the whole live stack (idempotent — re-run to fix partial boot)
make health      # zero-cost health/hygiene check
make lint        # bash -n every *.sh + python3 -m py_compile every *.py (no live stack)
make test        # python3 -m unittest discover -s tests/unit -p 'test_*.py' (pure logic only)
make uitest      # jsdom render tests for the dashboard SPA (tests/ui/ui.test.mjs)
make itest       # integration tests: services started standalone (python3 + curl only, no live stack)
make clean       # wipe data/bus + data/logs + __pycache__ (keeps dirs)
make gen-certs   # regen dashboard CA/TLS + rotate the bridge token
make mail-up     # bring up the real SMTP relay used by services/mail
make security-scan  # Semgrep-scan this repo itself with worker-b's own ruleset
```

Run a single unit test: `python3 -m unittest tests.unit.test_wi_review -v` (from repo root).
Run a single integration test: `bash tests/integration/worker_endpoint.sh`.

CI (`.github/workflows/lint.yml`) runs only `lint` + `test` + `itest` — no live sandboxes, no
NIM, no device. The heavier e2e suites (`tests/e2e-nemoclaw.sh`, `tests/e2e-openshell.sh`,
`tests/e2e.sh`, `tests/bridge-regress.sh`) require a live boot and stay dev-box-only.

After editing `services/bridge/agent-dashboard.py` or the `worker-itops.py` module cluster,
`python3 -m py_compile` the file, then `make boot` to restart and pick up the change (nothing
hot-reloads).

## Repo-root resolution — read before writing any script

Every shell script self-locates the repo root via a `.nemofleet-root` marker file, so scripts
run correctly from any cwd and any host. New scripts must start with the standard header (see
any file in `scripts/` for the exact boilerplate, e.g. `scripts/boot-stack.sh` lines 3-5):

```bash
__src="${BASH_SOURCE[0]:-$0}"; __dir="$(cd "$(dirname "$(readlink -f "$__src" 2>/dev/null || echo "$__src")")" && pwd)"
while [ "$__dir" != / ] && [ ! -e "$__dir/.nemofleet-root" ]; do __dir="$(dirname "$__dir")"; done
NEMOFLEET_ROOT="$__dir"; DIR="$NEMOFLEET_ROOT"; . "$NEMOFLEET_ROOT/lib/common.sh"
```

`lib/common.sh` is the single source of truth for every host-specific knob: paths, ports,
container name fragments, inference endpoint, real-backend creds (SMTP/Jira/device). It reads
`.env` (git-ignored, copy from `.env.example`) and resolves live container names via
`docker ps | grep openshell-<fragment>-` into `CT_LEAD`/`CT_WA`/`CT_WB`/`CT_WC` (these change on
every sandbox rebuild — never hardcode a container name/id). It also sources `lib/routing.sh`
(`route_decide`: keyword heuristic deciding whether a task goes to a worker vs. stays with
Hermes) and defines `skill_gate()` (the SkillOS quality gate — see below).

Exception: the worker control-UI ports are *not* actually driven by `.env`. `lib/common.sh`
defines `WORKERA_UI_PORT`/`WORKERB_UI_PORT` but nothing reads them — the real ports (18791/18792,
plus 18793 for worker-c) are hardcoded in `services/bridge/agent-dashboard.py`'s `_ZPORT` dict.
Don't expect a `.env` override of those two vars to do anything.

## The only cross-node channel

Nodes are otherwise network-isolated (hub-and-spoke; workers never talk to each other). The
**only** path between team-lead and a worker is the scoped `worker_bridge` OpenShell policy
(destination pinned /32) hitting the worker's in-container `:9099` IT-ops endpoint
(`services/bridge/worker-itops.py`), authenticated with `X-Bridge-Token`
(`services/bridge/.bridge-token`, git-ignored, rotated by `scripts/rotate-bridge-token.sh`).
worker-c's high-risk actions (rollback/firmware-apply) additionally require an `approval_token`
body field — this used to be a truthiness check (any non-empty string "approved" a rollback),
then a flat shared-secret compare; it's now a real per-action token (`wi_approval.py`): minted by
team-lead's `services/bridge/approval_issue.py` only after a human approves a specific action over
Telegram (`skills/hermes/firmware-approval/SKILL.md`), HMAC-signed with `APPROVAL_KEY`
(`services/bridge/.approval-key`, zone C + team-lead only, generated by `boot-stack.sh`), and
bound to the exact action + params, expiring, and single-use — verified and recorded (for
traceability) by worker-c's `_approval_verify_and_record()`. Still not cryptographically enforced:
whether team-lead's LLM actually waited for a real human reply before minting — see
`docs/design/worker-c-spec.md` §7 for the honest limitation.

That endpoint exposes two delegation shapes:
- **`POST /fix`** — async remediation (`{"bug": "ebg-wps", ...}`): accepted immediately, executed
  in the background (nvram apply + read-back verification), polled via `GET /last`.
- **A2A (Agent2Agent)** — standard capability discovery (`GET /.well-known/agent-card.json`) and
  synchronous delegation (`POST /a2a`, JSON-RPC `message/send`) for scans/status, over the same
  governed channel. `services/bridge/a2a_client.py` is the client; `wi_a2a.py` is the adapter.

Every inbound request to `/fix` is re-screened by the request guardrail at the action gate
(defense-in-depth against a manipulated team-lead) — see README "守門 (guardrails)" for the full
layered-control list (sandbox egress policy, kill-switch, action governance, DLP).

## `worker-itops.py` — mid-modularization, read this before touching it

`worker-itops.py` is a large in-progress extraction target — check `wc -l` against HEAD rather
than trusting a fixed number here; it isn't monotonically shrinking (multi-ecosystem SBOM parsing
and Semgrep-based SAST helpers are actively growing the still-unextracted scanner cluster even as
other parts get pulled out). It's the single HTTP handler running inside each worker sandbox,
`cp`'d into place by `boot-stack.sh` alongside its co-located helper modules. Full state and
rationale: `docs/design/worker-itops-modularization.md` (also drifts — re-check line counts there
too).

Already extracted (import these, don't reinvent): `ebg19p.py` (device client — the only place
that logs into EBG19P), `knowledge.py` (shared baseline/security-keys — same knowledge team-lead
reads via `GET /knowledge`), `wi_util.py` (pure version/cert/cipher/conf-parse helpers),
`wi_a2a.py`, `wi_nuclei.py`, `wi_review.py` (worker-c QA gate), `wi_skills.py` (SkillOS
curation), `wi_flow.py` (cross-node flow-event ring for the GUI Flow view).

Two extraction patterns are in play — match whichever the module already uses:
1. **direct-import** — pure logic, no host state (`ebg19p.py`, `wi_util.py`, `wi_review.py`, `wi_skills.py`).
2. **`configure()` DI** — stateful subsystem, host deps (`zone_has`/`load_settings`/`open_jira`/`zone`)
   injected once at startup (`wi_a2a.py`, `wi_nuclei.py`, `wi_flow.py`).

What's deliberately **not** extracted yet: the CVE/SBOM/SAST/cert/monitor/syslog scanners. They
share a mutable foundation (`load_settings/save_setting`, `open_jira`, the device client) that
hasn't been DI'd out, and — more importantly — their real logic only exercises against a live
EBG19P + full fleet, which isn't available in isolation here. Don't extract or rewrite this
cluster (or the `scripts/ebg19p-*-sync.sh` shell RPC callers) without a real device to verify
against — an unverifiable move here can silently break a working device-facing path. Semgrep is
the underlying SAST engine here (rules staged by `scripts/fetch-semgrep-rules.sh`, same ruleset
`make security-scan` runs against this repo itself) — worker-b's SBOM side now parses
`package.json`/`requirements.txt`/`go.mod`/`Cargo.toml`/`composer.json`/`pyproject.toml`/
`Pipfile`/`Gemfile.lock`/`pom.xml`/`build.gradle`.

The regression net for future extractions: unit tests in `tests/unit` (pure logic, run via
`make test`) + integration tests in `tests/integration` (authed routes checked no-token→403, plus
zone-specific behavior, run via `make itest`) — don't trust a fixed test count here, it drifts;
check with `python3 -m unittest discover -s tests/unit -p 'test_*.py' -v` if you need the current
number. Run both after any change in this area; `itest` specifically guards against
modularization breaking route wiring.

## Adding a dashboard control

`services/bridge/agent-dashboard.py` (host-side, `:8899`) is a status board + admin control
panel over the real `nemoclaw`/`openshell` CLIs. Two front-ends currently coexist on the same
JSON API: the classic UI at `/` and the newer React console at `/app`
(`services/bridge/web/`, no build step, `web/api.js` → `normalize()` is the only backend seam).
To wire up a new control end-to-end, follow `services/bridge/README.md` § "How a control is
wired": add a branch in `do_sys(...)`, add a frontend button (`data-act="sysdo"` or
`data-act="syscmd"`), add i18n labels to **both** the zh and en tables. All actions are
admin-only + localhost-only; state-changing actions are confirm-gated, destructive ones require
typing the name/version to confirm; all CLI args are `shlex.quote`d and regex-validated
server-side — preserve this when adding new actions.

## Skills and self-evolution

`skills/hermes/` and `skills/worker/` hold canonical `SKILL.md` agent skills (frontmatter +
Markdown instructions, `%%PLACEHOLDER%%` tokens filled in at deploy time by boot-stack, e.g.
`%%WA_IP%%`, `BRIDGETOKEN`). team-lead writes new skills for repeated request patterns; before
one lands it passes `skill_gate()` (`lib/common.sh`) — a POST to worker-c's `/skill-review` that
can bindingly reject (quality gate + anti-bloat over the skill library, modeled on SkillOS,
arXiv 2605.06614). If worker-c isn't deployed or unreachable, the gate fails open (logged) so
self-evolution isn't blocked by an absent governance node.

## Eval loop

`eval/eval.py` runs real tasks (`eval/tasks.jsonl`) against the live Hermes API (`:8642`),
rule-scores the output (no LLM judge), records to `eval/ledgers/LEDGER.md`, and on failure
appends to `eval/lessons.json` — which gets prepended into that task's prompt next run. This is
a closed loop against a live stack, not a unit test; it needs `make boot` first.

## Style notes specific to this repo

- Comments and doc prose are frequently bilingual (Mandarin explaining rationale, English for
  code/identifiers) — match the existing convention in a file rather than converting it.
- Real backends only: no mock SMTP/Jira/device servers exist or should be added. Tests that need
  a real dependency belong in the dev-box-only e2e tier, not `tests/unit` or `tests/integration`.
- Secrets are always git-ignored, never hand-edited or committed, and regenerated via
  `make gen-certs` / `rotate-bridge-token.sh` — see README § 安全 for the full list.
