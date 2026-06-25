# nemofleet — 雙代理受治理網路維運系統

A two-agent, policy-governed fleet for ASUS network-device IT operations. Governance
is **code, not prompts**: every cross-agent and egress action passes OPA / L7 policy.

> Built for the ASUS Agentic AI Competition 2026. This repo is the portable, refactored
> successor to `nemoclaw-combine` — self-locating scripts, extracted libraries, snapshots
> for replication onto a fresh device.

## 四元件分工 (the four components)

| Component | Role |
|---|---|
| **NemoClaw**  | Agent lifecycle & recovery — deploy / snapshot / one-touch recover / self-heal + model·channel·policy routing. |
| **OpenShell** | Sandbox isolation + OPA security policy — netns / L7 MITM proxy / 3-layer egress (host·path·binary). |
| **Hermes**    | Human-facing front desk — multi-channel (Telegram / Email) intake, triage & dispatch, close-out, self-evolving skills. |
| **OpenClaw**  | ASUS network-device IT operator (**fleet; 2 nodes here, scales horizontally**) — monitors device drift vs. approved baseline (ALERT on regression) + daily CVE scan; fixes on report + auto-verifies; escalates to Jira when human approval is needed. |

The two sandboxes are fully isolated. The **only** cross-agent path is the scoped
`openclaw_bridge` policy (/32) + the `:9099` inbound endpoint (X-Bridge-Token).

**Two OpenClaw nodes**: `my-assistant` (:18789) and `openclaw-2` (:18790). Front desk:
`hermes-demo` (:8642). All run on the same harness, differing only by config.

## 倉庫結構 (repository layout)

```
lib/          shared shell library — common.sh (root/paths/ports/containers),
              scenarios.sh (IT bug fixtures), routing.sh (task router)
services/     long-running services:
  bridge/       status dashboard, the :9099 fix endpoint, mock Jira
  mail/         GreenMail SMTP STARTTLS shim + senders (email channel)
scripts/      operations: boot-stack, healthcheck, fleet sync (ebg19p / rt-ax89x),
              cve-scan, agent routing (relay/dispatch/route/collab), tls/token gen
demo/         all *-demo.sh + demo.sh + govboard + runbooks/ (telegram, materials)
tests/        e2e + bridge-regress + loop-regress (deterministic regression guards)
skills/       canonical agent skills — hermes/ , openclaw/
eval/         eval harness + ledgers (self-learning loop)
config/       policy presets, TLS config, sanitized *.example.json
provisioning/ replicate onto a fresh device — bootstrap + sanitized snapshots
docs/         design docs, evidence, archive; decks/ + assets/ (local-only)
tools/        design-system generator, pptx helper
data/         runtime (message bus, logs) — git-ignored
```

Everything host-specific (repo path, node bin, ports, container names) is centralised in
`lib/common.sh` and overridable via `.env` (see `.env.example`). Scripts locate the repo
root by the `.nemofleet-root` marker, so they run from any directory on any machine.

## 快速上手 (quickstart)

```bash
cp .env.example .env                 # optional — defaults work on the dev box
make bootstrap                       # first time only: certs, bridge token, runtime config
make boot                            # bring up the whole stack (idempotent; re-run if early)
make health                          # zero-cost health / hygiene check (should be all green)
make demo                            # one-shot demo runbook
```

Web status board: <http://127.0.0.1:8899> (auto-started by boot-stack, 5 s refresh).

### Competition-day order (record / on-stage)

```bash
make boot                                  # 1. whole stack
make health                                # 2. health (incl. :9099, greenmail, dashboard)
bash tests/bridge-regress.sh drift         # 3. delegation-chain regression (1 Azure turn)
bash scripts/cve-scan.sh                   # 4. CVE scan warm-up (fleet triage + Jira + schedule)
bash demo/monitor-alert-demo.sh --no-push  # 5. (optional) proactive-alert rehearsal (0 Azure)
```

Main demo line (normal → attack contrast) = `demo/runbooks/demo_telegram.md`.

## 設定 (configuration)

| Knob | Where | Default |
|---|---|---|
| repo paths / dirs | `lib/common.sh` (derived from `.nemofleet-root`) | auto |
| node bin (`nemoclaw`/`openshell`) | `NEMOFLEET_NODE_BIN` in `.env` | newest `~/.nvm` node |
| ports | `.env` (`HERMES_API_PORT`, `DASH_PORT`, `BRIDGE_PORT`, …) | 8642 / 8899 / 9099 |
| sandbox names | `.env` (`*_CT_NAME`) | hermes-demo / my-assistant / openclaw-2 |

## 複製到新裝置 (replicate to a new device)

The system components (NemoClaw + OpenShell CLIs, the Hermes/OpenClaw sandboxes) are
installed products, not vendored here. To stand the fleet up on a fresh machine:

```bash
git clone <your-repo> nemofleet && cd nemofleet
less provisioning/install-prereqs.md       # docker, node, NemoClaw/OpenShell, onboarding
bash provisioning/bootstrap.sh             # deterministic local setup
```

See `provisioning/` for the sanitized sandbox snapshot and step-by-step onboarding.

## 安全 (security)

Secrets are **never** committed: TLS keys/certs, the bridge token, the NVD API key, and
runtime auth files are all `.gitignore`d and regenerated by `scripts/gen-dash-ca.sh`,
`scripts/gen-dash-tls.sh`, `scripts/rotate-bridge-token.sh`, and `services/mail/up.sh`.
The `config/**/*.example.json` files document schema only — no real credentials.

## 文件 (docs)

- `services/bridge/README.md` — **status dashboard control surface** (every GUI action → CLI → guard) + how to add more
- `docs/design/architecture.md` — architecture (mermaid + ASCII)
- `docs/design/combined-use-case.md` — combined use case + interface asymmetry
- `docs/design/business-case.md` — business plan draft
- `docs/EVIDENCE.md` — claim → evidence matrix
- `docs/design/qa-prep.md` — reviewer Q&A prep
- `docs/archive/PROGRESS.md` — autonomous-loop progress log (historical)
