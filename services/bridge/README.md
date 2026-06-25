# services/bridge/ — status dashboard + cross-agent bridge

Host-side web app + the scoped Hermes→OpenClaw channel.

| File | What |
|---|---|
| `agent-dashboard.py` | The status board + control panel. Host web server on **:8899** (`DASHBOARD_PORT`). Started by `scripts/boot-stack.sh`. |
| `openclaw-fix-endpoint.py` | The in-sandbox `:9099` fix endpoint (the only cross-agent channel). |
| `jira-mock.py` | Mock Jira/ITSM target for escalation demos. |
| `assets/brand.svg` | Logo. |

> Default dashboard login is seeded from `config/bridge/dash-seed.json` — see
> `config/bridge/README.md`. Open <http://127.0.0.1:8899>.

## GUI capability list

Read-only status is always shown; the **actions** below are the buttons. All actions
are **admin-only**, localhost-only, and run the real `nemoclaw`/`openshell` CLI. Output
appears in the side drawer.

### Lifecycle & diagnostics (System tab → Diagnostics card)
| Button | CLI | Scope | Guard |
|---|---|---|---|
| Doctor | `nemoclaw <sb> doctor` | per agent | — |
| Logs | `nemoclaw <sb> logs --tail` | per agent | — |
| **Recover** | `nemoclaw <sb> recover` | per agent | confirm |
| **Rebuild** | `nemoclaw <sb> rebuild --yes` | per agent | **type sandbox name** |
| Gateway health | `openshell status` + `openshell doctor` | global | — |
| Check stale | `nemoclaw upgrade-sandboxes --check` | global | — |
| Global settings | `openshell settings get --global` | global | — |
| **GC preview / clean** | `nemoclaw gc --dry-run` / `--yes` | global | clean=confirm |

### Maintenance (System tab → Maintenance card)
| Button | CLI | Scope | Guard |
|---|---|---|---|
| **Backup all** | `nemoclaw backup-all` | global | confirm |
| **Upgrade stale** | `nemoclaw upgrade-sandboxes --auto --yes` | global | confirm |
| **Debug bundle** | `nemoclaw debug --quick --output /tmp/…tgz` | global | writes tarball on host |
| **Host aliases** | `nemoclaw <sb> hosts-list / -add <name> <ip> / -remove <name>` | per agent | add/remove validated; remove=confirm |
| **Port forwards** | `openshell forward start / stop <port> [sb]` | global | stop=confirm |

### Inference & channels (System tab)
| Button | CLI | Guard |
|---|---|---|
| **Switch model** | `nemoclaw inference set --provider --model` | provider/model whitelist-validated |
| **Channel stop / start** | `nemoclaw <sb> channels stop\|start <channel>` | confirm; channel name validated |

### Governance / policy (Governance tab)
- View any agent's live OPA policy (read-only).
- **Edit policy** (prove-gated): toggle egress presets, add/remove endpoints, edit raw
  YAML — every apply runs `openshell policy prove` and is **rejected if it raises the
  critical/high gap count** (differential gate). Per-sandbox OpenShell settings toggles.

### Other existing controls
- **Snapshots**: create / restore / delete per agent (`nemoclaw <sb> snapshot …`; delete
  is type-the-version confirmed).
- **Access control**: users + RBAC (admin/viewer), session/timeout/IP-whitelist, reset
  password. Tamper-evident **admin audit** (hash-chained).
- **Recipients / scan settings / certs**: notify recipients, scan-schedule & alert
  thresholds, cert/weak-crypto view.
- **Scan triggers** (`POST /api/action`): `cve`, `source`, `jira_reset`, `refresh`.

## Security model

- **localhost-only** bind; session cookie auth; **admin RBAC** gates every action.
- The `X-Bridge-Token` is **server-side only** — never sent to the browser.
- State-changing actions are **confirm-gated**; destructive ones (rebuild, snapshot
  delete) require **typing the name/version**. All CLI args are **`shlex.quote`d** and
  regex-validated server-side.
- Read path is a cached (~8 s) aggregate; heavy actions are on-demand (not in the poll).

## How a control is wired (to add more)

1. **Backend** — add a branch to `do_sys(do, sb, tail, provider, model, chan, a1, a2)`;
   return `{"ok", "title", "out"}`. It's reached via admin-gated `GET /api/sys?do=…`.
2. **Frontend** — add a button with one of:
   - `data-act="sysdo" data-do="X" [data-sb] [data-confirm]` — simple action → drawer.
   - `data-act="syscmd" data-do="X" data-prompts="key1|key2"` — prompts for `a1`/`a2`.
   - a dedicated `act` (e.g. `rebuild`) for type-to-confirm flows.
3. **i18n** — add the label keys to **both** language tables (zh + en).

After editing: `python3 -m py_compile services/bridge/agent-dashboard.py`, then restart
the dashboard (`make boot`) to load the new controls.
