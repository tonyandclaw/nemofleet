# nemofleet — 受治理的網路維運 agent 艦隊

A policy-governed **team-lead + workers** fleet for ASUS network-device IT operations.
All nodes run the **Hermes** harness on **local NVIDIA NIM — Nemotron 3 Super 120B**. Governance is
**code, not prompts**: every cross-node and egress action passes OPA / L7 policy.

## 三節點分工 (the fleet)

| Node | Role |
|---|---|
| **team-lead** (`:8642`) | Human-facing front desk — multi-channel (Telegram / Email) intake, triage & dispatch to workers, close-out, self-evolving skills. |
| **worker-a** (`:18789`) | Ops worker — device drift vs. approved baseline (ALERT on regression), certificate / weak-crypto audit, EBG19P remediation. |
| **worker-b** (`:18790`) | Security worker — daily CVE scan, SBOM / SAST over upstream firmware source, syslog analysis. |

Supporting products (installed CLIs, not vendored here):

| Component | Role |
|---|---|
| **NemoClaw**  | Agent lifecycle & recovery — deploy / snapshot / one-touch recover / self-heal + model·channel·policy routing. |
| **OpenShell** | Sandbox isolation + OPA security policy — netns / L7 MITM proxy / 3-layer egress (host·path·binary). |

The sandboxes are isolated. The **only** cross-node path is the scoped `worker_bridge`
policy (/32) + the `:9099` in-worker IT-ops endpoint (X-Bridge-Token). The team-lead
delegates work to a worker; the worker executes deterministically (zero-LLM scans +
device remediation) and escalates to **real Jira** when human approval is needed.

**One real managed device**: ASUS ExpertWiFi **EBG19P** (`lab-asus-ebg19p-01`), reached
read-only for monitoring and via governed nvram apply for remediation.

## 倉庫結構 (repository layout)

```
lib/          shared shell library — common.sh (root/paths/ports/containers/backends),
              routing.sh (lead↔worker task router)
services/     long-running services:
  bridge/       status dashboard + the :9099 IT-ops endpoint (worker-itops.py)
  mail/         real-SMTP sender (send.py) + thin shims
scripts/       operations: boot-stack, healthcheck, EBG19P sync/remediate,
              cve-scan, lead↔worker routing (relay/dispatch/route/collab), tls/token gen
tests/        e2e (nemoclaw/openshell) + unit tests (pure logic)
skills/       canonical agent skills — hermes/ (team-lead) , worker/
eval/         eval harness + ledgers (self-learning loop)
config/       policy presets, TLS config, sanitized *.example.json
provisioning/ replicate onto a fresh device — bootstrap + sanitized snapshots
data/         runtime (message bus, logs) — git-ignored
```

Everything host-specific (repo path, node bin, ports, container names, backend creds) is
centralised in `lib/common.sh` and overridable via `.env` (see `.env.example`). Scripts
locate the repo root by the `.nemofleet-root` marker, so they run from any directory.

## 快速上手 (quickstart)

```bash
cp .env.example .env                 # set NIM endpoint, SMTP, Jira, device cred
make bootstrap                       # first time only: certs, bridge token, runtime config
make boot                            # bring up the whole stack (idempotent; re-run if early)
make health                          # zero-cost health / hygiene check (should be all green)
```

Web status board: <http://127.0.0.1:8899> (auto-started by boot-stack, 5 s refresh).

## 推理:本地 NIM (inference)

All three nodes route inference to a **local NVIDIA NIM** OpenAI-compatible endpoint.
Point `.env` at your NIM (`INFER_ENDPOINT`, `INFER_MODEL`), then set it into each sandbox:

```bash
nemoclaw inference set --provider nim --model "$INFER_MODEL" --sandbox team-lead
nemoclaw inference set --provider nim --model "$INFER_MODEL" --sandbox worker-a
nemoclaw inference set --provider nim --model "$INFER_MODEL" --sandbox worker-b
```

> A NIM container needs a GPU. On CPU-only hosts nemotron is impractically slow
> (>60 s/turn); use a GPU host or a hosted NIM endpoint.

## 設定 (configuration)

| Knob | Where | Default |
|---|---|---|
| repo paths / dirs | `lib/common.sh` (derived from `.nemofleet-root`) | auto |
| node bin (`nemoclaw`/`openshell`) | `NEMOFLEET_NODE_BIN` in `.env` | newest `~/.nvm` node |
| ports | `.env` (`HERMES_API_PORT`, `DASH_PORT`, `BRIDGE_PORT`, …) | 8642 / 8899 / 9099 |
| sandbox names | `.env` (`*_CT_NAME`) | team-lead / worker-a / worker-b |
| inference | `.env` (`INFER_ENDPOINT`, `INFER_MODEL`) | local NIM / nemotron-3-super-120b |
| real backends | `.env` (`SMTP_*`, `JIRA_*`, `EBG19P_CRED`) | unset — you provide |

## 複製到新裝置 (replicate to a new device)

The system components (NemoClaw + OpenShell CLIs, the Hermes sandboxes) are installed
products, not vendored here. To stand the fleet up on a fresh machine:

```bash
git clone <your-repo> nemofleet && cd nemofleet
less provisioning/install-prereqs.md       # docker, node, NemoClaw/OpenShell, NIM, onboarding
bash provisioning/bootstrap.sh             # deterministic local setup
```

## 安全 (security)

Secrets are **never** committed: TLS keys/certs, the bridge token, the NVD API key, real
backend credentials (`SMTP_*`, `JIRA_*`, the device cred file), and runtime auth files are
all `.gitignore`d. TLS/token are regenerated by `scripts/gen-dash-ca.sh`,
`scripts/gen-dash-tls.sh`, `scripts/rotate-bridge-token.sh`. The `config/**/*.example.json`
files document schema only — no real credentials.

## 文件 (docs)

- `services/bridge/README.md` — **status dashboard control surface** (every GUI action → CLI → guard)
- `docs/design/architecture.md` — architecture (mermaid + ASCII)
- `docs/design/governance-inventory.md` — governance inventory
- `docs/ebg19p-operations.md` — EBG19P operations knowledge base
- `docs/design/ebg19p-integration-design.md` — real-device integration design
