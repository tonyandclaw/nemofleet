# config/bridge/

Runtime config + the **seed account** for the status dashboard
(`services/bridge/agent-dashboard.py`, <http://127.0.0.1:8899>).

## Default dashboard account (`dash-seed.json`)

The dashboard seeds its **first admin** from `config/bridge/dash-seed.json` on first
run. That file is **git-ignored** — your real account/password never goes to GitHub.

Set it up on each machine:

```bash
cp config/bridge/dash-seed.example.json config/bridge/dash-seed.json
$EDITOR config/bridge/dash-seed.json      # set your own email + password
```

```jsonc
{
  "email": "you@example.com",   // login email
  "password": "change-me-now",  // plaintext here; hashed (pbkdf2) on first run
  "role": "admin",              // admin | viewer
  "must_change": true           // force a password change at first login
}
```

On first start the dashboard reads this file, writes the **hashed** user into
`services/bridge/dash-users.json` (also git-ignored), and — with `must_change: true`
— forces a password change at first login. After that, `dash-seed.json` is no longer
read (delete it if you like). If no seed file exists, **no account is created** and
you must add one before logging in.

## Other files here

| File | Tracked? | Purpose |
|---|---|---|
| `dash-seed.example.json` | ✅ committed | schema template (placeholder creds) |
| `dash-seed.json`         | 🚫 ignored  | your real seed account |
| `dash-auth.example.json` | ✅ committed | session/timeout/IP-whitelist defaults |
| `dash-users.example.json`| ✅ committed | user-store schema (no real creds) |

Real runtime files (`services/bridge/dash-users.json`, `dash-auth.json`) are written
by the dashboard and git-ignored.
