# Provisioning a fresh device

`nemofleet` is the orchestration layer. The system components it drives —
**NemoClaw** + **OpenShell** CLIs and the **Hermes** / **worker** sandboxes — are
installed products, not vendored in this repo. This is the one-time setup to recreate
them on a new machine, after which `make boot` runs the fleet.

## 1. Host prerequisites

- **Docker** (sandboxes + the local NIM run as containers).
- **Node.js** via nvm — provides the `nemoclaw` and `openshell` CLIs.
  `lib/common.sh` auto-detects the newest `~/.nvm/versions/node/*/bin`; pin it with
  `NEMOFLEET_NODE_BIN` in `.env` if needed.
- **NemoClaw + OpenShell** — install per the upstream project (source lives under
  `~/.nemoclaw/source`, remote `github.com/NVIDIA/NemoClaw`). After install,
  `nemoclaw --version` and `openshell --version` should resolve.
- **openssl**, **python3** — used by cert gen + the SMTP sender.
- **NVIDIA GPU + drivers + NVIDIA Container Toolkit** — required to run the local NIM
  (nemotron). CPU-only hosts are impractically slow (>60 s/turn).

> **WSL2 note (this stack's home):** WSL → Windows host (e.g. LM Studio) needs a
> vEthernet firewall rule, and the Windows host IP changes per boot. See memory
> `user_wsl_lmstudio_setup`.

## 2. Inference: local NVIDIA NIM

All three nodes run the Hermes harness on a **local NVIDIA NIM — Nemotron 3 Super 120B-A12B**,
OpenAI-compatible. NemoClaw routes inference through a local gateway on port `18080`
(`NEMOCLAW_GATEWAY_PORT=18080`) — `8080` is taken by Token_Hunter on this stack.

> Nemotron 3 Super 120B is a 120B / 12B-active hybrid Mamba-MoE **reasoning** model trained
> natively in **NVFP4** (~60GB at 4-bit) — it fits a single **GB10** (e.g. ASUS Ascent GX10,
> 128GB) with room for KV cache, runs at native FP4 on Blackwell (no quantization penalty), and
> is tuned for agentic / tool-use + IT-ticket automation. Two GX10 give extra KV / longer-context
> headroom. (It's a reasoning model — it emits a reasoning trace per turn; use the effort toggle
> to keep simple turns cheap.)

1. Run the NIM container (needs GPU + NVIDIA Container Toolkit). It serves an
   OpenAI-compatible `/v1` endpoint — set `INFER_ENDPOINT` / `INFER_MODEL` in `.env`
   to match (default `http://127.0.0.1:8000/v1`, `nvidia/nemotron-3-super-120b-a12b`).
2. Point each sandbox at it:

   ```bash
   for sb in team-lead worker-a worker-b; do
     nemoclaw inference set --provider nim --model "$INFER_MODEL" --sandbox "$sb"
   done
   ```

The base URL is only changeable via **re-onboard** (provider `nim` / `compatible-endpoint`,
gateway port `18080`).

## 3. Create the sandboxes

`provisioning/sandboxes.example.json` is a **sanitized** snapshot of this fleet
(secrets redacted, paths templated). It documents the target shape:

| Sandbox | Port | Agent / role |
|---|---|---|
| `team-lead`  | 8642  | Hermes front desk (channels: telegram); default sandbox |
| `worker-a` | 18789 | worker node A |
| `worker-b`   | 18790 | worker node B |

Onboard each with `nemoclaw` against the local NIM (all three run the same Hermes
harness + model; they differ only by role/config). For the team-lead, supply the real
`TELEGRAM_BOT_TOKEN` during onboarding (it is stored in the sandbox, **not** in git).

Custom egress policies (`worker-jira`, `worker-bridge`) are in `config/presets/`;
`boot-stack.sh` renders + applies them with the current container IPs, token, and the
real Jira host from `.env`. Outbound mail goes host-side via `services/mail/send.py`
to your real SMTP relay; the team-lead's inbound email adapter reaches your real
IMAP/SMTP over governed egress (add that host to a mail egress preset).

### worker-b active scanning (nuclei)

worker-b runs **scheduled `nuclei` scans** against the EBG19P — active vulnerability probing with
[`projectdiscovery/nuclei-templates`](https://github.com/projectdiscovery/nuclei-templates),
complementing the version-based CVE scan. Three prerequisites, all governed:

1. **nuclei binary** in the worker-b sandbox at `/usr/local/bin/nuclei` (install per upstream). The
   OpenShell binaries policy must allow it — `scripts/worker-b-allow-device.sh` adds the allow.
2. **Templates** via `nuclei -update-templates` (GitHub egress is already allowed by
   `worker-b-allow-github.sh`).
3. **Device egress** — worker-b → the EBG19P IP. `boot-stack.sh` injects `EBG19P_TARGET` (the IP
   **only**, no credentials) and runs `worker-b-allow-device.sh` (a scoped allow to that one host).

Cadence + template filter live in the dashboard **Settings** (`nuclei_interval_sec`, `nuclei_tags`
default `asus`; `0` disables). High/critical hits open a real Jira ticket per `auto_escalate`.
Endpoints on worker-b: `GET /nuclei` (last result), `POST /nuclei-scan` (trigger), and A2A skill
`nuclei-scan`. Until the binary is installed the scan degrades gracefully (`available: false`).

> **ClawHub skills:** installing ClawHub skills needs a custom `clawhub` egress preset
> and stripping `HTTPS_PROXY` via `sh -c` (not `sh -lc`) to dodge the 403-CONNECT proxy.
> (memory `reference_nemoclaw_clawhub_skill_install`)

## 4. Finish

```bash
bash provisioning/bootstrap.sh     # certs, token, runtime config (idempotent)
bash services/mail/up.sh           # validate the real SMTP config from .env
make boot && make health           # bring the fleet up; expect all green
```

On reboot, `scripts/boot-stack-autostart.sh` (cron `@reboot`) re-raises the stack; the
recovery rationale (gateway port, nested netns, `SSL_CERT_FILE`) is in memory
`reference_nemoclaw_reboot_recovery`.
