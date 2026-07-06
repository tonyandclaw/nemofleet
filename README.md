# nemofleet — 受治理的網路維運 agent 艦隊

A policy-governed **team-lead + workers** fleet for ASUS network-device IT operations.
All nodes run the **Hermes** harness on **local NVIDIA NIM — Nemotron 3 Super 120B**. Governance is
**code, not prompts**: every cross-node and egress action passes OPA / L7 policy.

## 四節點分工 (the fleet)

| Node | Role |
|---|---|
| **team-lead** (API `:8642` · UI `:18790`) | Human-facing front desk — multi-channel (Telegram / Email) intake, triage & dispatch to workers, close-out, self-evolving skills. |
| **worker-a** (UI `:18791`) | Ops worker — device drift vs. approved baseline (ALERT on regression), certificate / weak-crypto audit, EBG19P remediation. |
| **worker-b** (UI `:18792`) | Security worker — daily CVE scan, SBOM / SAST over upstream firmware source, syslog analysis. |
| **worker-c** (UI `:18793`) | Governance worker — config backup / firmware lifecycle / rollback (human-approved), **QA review gate over a/b** (binding reject → redo), SkillOS skill curation. |

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

## 守門 (guardrails)

Layered controls keep the fleet governed — infrastructure is strong, and the agent layer is guarded:

- **🛡 Request guardrail** — every inbound request is screened by the local NIM **before the fleet acts**
  (`POST /guardrail`): it blocks **prompt-injection / jailbreak** (override instructions, exfiltrate the
  bridge token), **out-of-scope**, and **destructive** intent (factory reset, disable all security), and
  allows only in-scope hardening/scan/report. team-lead screens at intake; the worker **re-screens the
  request at the `/fix` action gate** (defense-in-depth — a manipulated team-lead can't push a device
  change past it). Uses the local vLLM only (scoped, auditable egress); fails **open** with a logged note
  if inference is down, so it never drops a legitimate ops request.
- **Sandbox** — each agent runs in its own OpenShell sandbox: **deny-by-default egress** (L7), a
  **least-privilege** allowlist (default presets stripped), a **binary allowlist**, a filesystem policy
  (`ro /usr /lib`, `rw /sandbox /tmp`), **credential rewriting at the boundary** (agents never see raw
  secrets), and **OCSF audit** on every ALLOWED/DENIED egress.
- **Topology** — hub-and-spoke: workers are isolated, only team-lead delegates over the scoped
  `worker_bridge` (**/32 + X-Bridge-Token**).
- **Action governance** — `approval_token` (human) for firmware-apply/rollback; **worker-c binding
  review gate** over a/b (reject → redo); device remediation is **deterministic + read-back verified**
  (not LLM-guessed); SAST is deterministic **Semgrep**, with Nemotron only **triaging** (not inventing
  findings) and gating escalation.
- **🛑 Emergency kill-switch** — one admin action freezes the whole fleet: every agent sandbox is
  `docker pause`d (SIGSTOP — processes stop instantly, nothing runs) and resumed on demand. The
  dashboard + local NIM stay up as the control surface; a global banner marks a frozen fleet; audited.
- **Data egress** — app-layer **DLP** (masks credentials/long-secrets/card numbers, audited) on
  notifications, plus the boundary credential rewriting.

Known gaps (roadmap): extend DLP to the agent's own free-text sends; per-agent action budget /
rate-limit; broaden the human-approval gate to any egress-widening policy edit; drop the residual
`nvidia`/`nous_research` base-image egress.

## 文件 (docs)

- `services/bridge/README.md` — **status dashboard control surface** (every GUI action → CLI → guard)
- `docs/design/architecture.md` — architecture (mermaid + ASCII)
- `docs/design/governance-inventory.md` — governance inventory
- `docs/ebg19p-operations.md` — EBG19P operations knowledge base
- `docs/design/ebg19p-integration-design.md` — real-device integration design
