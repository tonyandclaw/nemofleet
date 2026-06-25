# provisioning/

Everything needed to replicate the fleet onto a fresh device.

| File | Purpose |
|---|---|
| `install-prereqs.md` | Step-by-step: host prerequisites, inference gateway, sandbox onboarding. Start here. |
| `bootstrap.sh` | Deterministic local setup (certs, bridge token, runtime config). Run after install. Idempotent. |
| `sandboxes.example.json` | **Sanitized** snapshot of the 3 sandboxes (ports, agents, custom egress policies). Secrets redacted, paths templated — a reference for onboarding, not an importable secret. |

```bash
git clone <repo> nemofleet && cd nemofleet
less provisioning/install-prereqs.md
bash provisioning/bootstrap.sh
make boot && make health
```

Real secrets (TLS keys, bridge token, Telegram token, NVD key) are never stored here —
they are generated locally by `bootstrap.sh` / the `gen-*` scripts, or onboarded
directly into the sandboxes.
