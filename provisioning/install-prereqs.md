# Provisioning a fresh device

`nemofleet` is the orchestration layer. The system components it drives —
**NemoClaw** + **OpenShell** CLIs and the **Hermes** / **OpenClaw** sandboxes — are
installed products, not vendored in this repo. This is the one-time setup to recreate
them on a new machine, after which `make boot` runs the fleet.

## 1. Host prerequisites

- **Docker** (sandboxes + GreenMail run as containers).
- **Node.js** via nvm — provides the `nemoclaw` and `openshell` CLIs.
  `lib/common.sh` auto-detects the newest `~/.nvm/versions/node/*/bin`; pin it with
  `NEMOFLEET_NODE_BIN` in `.env` if needed.
- **NemoClaw + OpenShell** — install per the upstream project (source lives under
  `~/.nemoclaw/source`, remote `github.com/NVIDIA/NemoClaw`). After install,
  `nemoclaw --version` and `openshell --version` should resolve.
- **uv**, **openssl**, **python3**, **socat** — used by the mail channel + cert gen.

> **WSL2 note (this stack's home):** WSL → Windows host (e.g. LM Studio) needs a
> vEthernet firewall rule, and the Windows host IP changes per boot. See memory
> `user_wsl_lmstudio_setup`.

## 2. Inference gateway

NemoClaw routes inference through a local gateway. **Use port `18080`**
(`NEMOCLAW_GATEWAY_PORT=18080`) — `8080` is taken by Token_Hunter on this stack.

Provider is `compatible-endpoint` (OpenAI-compatible). Two known backends:

- **Azure AI**: `https://<resource>.services.ai.azure.com/openai/v1`, Bearer auth,
  body `model: "<deployment>"`. (memory `reference_azure_ai_endpoint`)
- **LM Studio** (Windows host): set `NEMOCLAW_PREFERRED_API=chat-completions` when
  onboarding to skip the Responses-API tool-calling probe that hangs reasoning-only
  models. (memory `feedback_nemoclaw_lmstudio`)

The base URL is only changeable via **re-onboard**. Gateway port `18080`, provider
`custom`/`compatible-endpoint`. (memory `reference_nemoclaw_local_onboard`)

## 3. Create the sandboxes

`provisioning/sandboxes.example.json` is a **sanitized** snapshot of this fleet
(secrets redacted, paths templated). It documents the target shape:

| Sandbox | Port | Agent / role |
|---|---|---|
| `hermes-demo`  | 8642  | Hermes front desk (channels: telegram); default sandbox |
| `my-assistant` | 18789 | OpenClaw node A |
| `openclaw-2`   | 18790 | OpenClaw node B |

Onboard each with `nemoclaw` against your chosen provider (all use `Kimi-K2.5` here;
the difference is harness, not model). For Hermes, supply the real
`TELEGRAM_BOT_TOKEN` during onboarding (it is stored in the sandbox, **not** in git).

Custom egress policies (`openclaw-jira`, `greenmail-mail`, `openclaw-bridge`) are in
`config/presets/`; `boot-stack.sh` renders + applies the bridge/jira ones with the
current container IPs and token.

> **ClawHub skills:** installing ClawHub skills needs a custom `clawhub` egress preset
> and stripping `HTTPS_PROXY` via `sh -c` (not `sh -lc`) to dodge the 403-CONNECT proxy.
> (memory `reference_nemoclaw_clawhub_skill_install`)

## 4. Finish

```bash
bash provisioning/bootstrap.sh     # certs, token, runtime config (idempotent)
bash services/mail/up.sh           # optional: GreenMail + STARTTLS shim
make boot && make health           # bring the fleet up; expect all green
```

On reboot, `scripts/boot-stack-autostart.sh` (cron `@reboot`) re-raises the stack; the
recovery rationale (gateway port, nested netns, `SSL_CERT_FILE`) is in memory
`reference_nemoclaw_reboot_recovery`.
