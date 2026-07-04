# web/ — nemofleet console (React + Chart.js, no build step)

A multi-view SPA served by `agent-dashboard.py` at **`/app`** (auth-gated). It talks to the
same JSON API as the classic UI. No bundler: React/Chart.js/htm are **vendored** under
`vendor/` and loaded by `<script>` — the browser makes **zero external CDN calls** (this is a
governed-egress system).

## Files
| File | Role |
|---|---|
| `index.html` | Shell — loads vendored libs + app; `<div id="root">`. |
| `api.js` | `NF` API client + `normalize()` — **the only seam to the backend**. |
| `app.js` | The SPA: data hook, hash router, shared components, views. |
| `styles.css` | Design system (dark NOC console; built on the existing blue tokens). |
| `vendor/` | React 18, ReactDOM, htm, Chart.js 4 (UMD, pinned). |

## Built for scale

The fleet is expected to grow (more workers, more managed devices, more findings). The console
is architected so growth is a data change, not a rewrite:

- **Change-detection polling** (`useStatus`): re-renders only when `/api/status` actually
  changes — a 5 s poll on an idle fleet costs zero renders.
- **Memoized panels + data-driven rendering**: nodes, devices, findings, events are all
  `map`ped from arrays. 3 nodes or 30, 1 device or 20 — the UI just renders them.
- **Paginated tables** (`DataTable`): events / CVE / SAST / audit lists page client-side today.
  When a section's payload gets heavy, add a paginated endpoint and swap it in behind the same
  method in `api.js` — the views don't change (see the "SCALING SEAM" note there).
- **Immutable static caching**: the backend serves `vendor/*` with a 1-year immutable cache and
  ETag/304 for app files, so the browser never re-fetches the libraries.

## Backend seam

`api.js` → `normalize(raw)` maps the raw `/api/status` payload into the view model. When the
backend adds or renames fields, adjust the reads there; nothing else in the UI changes. To move
off the single aggregate, add `NF.events()`, `NF.cve()`, … (paginated) and call them from the
views that need them.

## Run / verify
```bash
make boot                 # or: DASHBOARD_PORT=8899 python3 ../agent-dashboard.py
# open https://<host>:8899/app  (after login)
```
Once verified against the live backend, point `GET /` at `web/index.html` and delete the
inline HTML blob in `agent-dashboard.py`.
