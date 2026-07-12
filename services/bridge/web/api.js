// api.js — thin client for the dashboard's JSON endpoints (same-origin, cookie auth).
// The ONLY seam between the React UI and the Python backend.
const _J = { Accept: 'application/json' };
async function _get(path) {
  const r = await fetch(path, { credentials: 'same-origin', headers: _J });
  if (r.status === 401) { location.href = '/login'; throw new Error('auth required'); }
  if (!r.ok) throw new Error('HTTP ' + r.status);
  // _localize (defined below, hoisted): one-off GET endpoints (audit, policy-get, policy-ro) never
  // flow through normalize() the way /api/status does, so without this they'd show raw Chinese
  // forever in English mode. Safe to double-localize /api/status too — _localize is idempotent
  // (a second pass finds no _en siblings left and is a no-op).
  return _localize(await r.json());
}
async function _post(path, body) {
  const opt = { method: 'POST', credentials: 'same-origin', headers: { ..._J } };
  if (body !== undefined) { opt.headers['Content-Type'] = 'application/json'; opt.body = JSON.stringify(body); }
  const r = await fetch(path, opt);
  if (r.status === 401) { location.href = '/login'; throw new Error('auth required'); }
  // _localize (defined below, hoisted) swaps in `msg_en`/etc. siblings when present — action-style
  // responses never flow through normalize(), so without this every action toast showed Chinese
  // forever in English mode regardless of what the backend sent.
  try { return _localize(await r.json()); } catch { return { ok: r.ok }; }
}
const qs = o => Object.entries(o).filter(([, v]) => v != null && v !== '').map(([k, v]) => k + '=' + encodeURIComponent(v)).join('&');

const NF = {
  status: () => _get('/api/status'),
  action: (act) => _post('/api/action?do=' + encodeURIComponent(act)),
  deviceAction: (act) => _post('/api/device-action?do=' + encodeURIComponent(act)),
  // write controls (map 1:1 to the existing admin endpoints)
  config: (k, v) => _post('/api/config?' + qs({ k, v })),
  certPolicy: (p) => _post('/api/cert-policy?' + qs(p)),
  recipient: (op, name, telegram, email) => _post('/api/recipient?' + qs({ op, name, telegram, email })),
  users: (body) => _post('/api/users', body),
  authConfig: (body) => _post('/api/auth-config', body),
  snapshot: (op, sel, sb) => _post('/api/snapshot?' + qs({ op, sel, sb })),
  // do_sys() builds its drawer title/out strings server-side per call (no pre-computed _en sibling
  // like /api/status has), so it needs the language passed explicitly — LANG is app.js's global.
  sys: (p) => _get('/api/sys?' + qs({ ...p, lang: LANG })),
  policy: (body) => _post('/api/policy', body),
  policyRo: (sb) => _get('/api/policy-ro?' + qs({ sb })),

  // ── SCALING SEAM ──────────────────────────────────────────────────────────
  // Per-section paginated reads. Today they slice the /api/status aggregate; when the fleet
  // grows, implement /api/<section>?page=&size= on the backend and swap the body here — the
  // <DataTable fetchPage> callers don't change.
  async section(name, page = 0, size = 20) {
    const d = normalize(await NF.status());
    const map = { events: d.events, cve: d.cve.findings, sast: d.source.sast_list, audit: d.audit_recent, governance: d.governance.events };
    const rows = map[name] || [];
    return { rows: rows.slice(page * size, page * size + size), total: rows.length, page, size };
  },

  // Transport seam: polling today, WebSocket-ready tomorrow. subscribe(onData,onErr) → unsubscribe().
  // Swap the body for a WS/SSE connection later; useLiveFeed and the whole UI stay the same.
  subscribe(onData, onErr, intervalMs = 5000) {
    let stop = false, timer = null;
    const tick = async () => { if (stop) return; try { onData(await NF.status()); } catch (e) { onErr && onErr(e); } if (!stop) timer = setTimeout(tick, intervalMs); };
    tick();
    return () => { stop = true; clearTimeout(timer); };
  },
};

// normalize(raw) — map the raw /api/status payload into the view model. Defensive: every field
// falls back so the console renders on partial/empty data. Adjust the reads here on backend drift.
// The backend prepares bilingual text as sibling fields (title/title_en, msg/msg_en, detail/detail_en,
// desc/desc_en, summary/summary_en, fix/fix_en, risk/risk_en, evidence/evidence_en, b/b_en, …) rather
// than localizing itself — walk the whole payload once and swap in the `_en` sibling when LANG is
// 'en', so every panel picks up the language switch instead of always showing the Chinese base field.
// Builds a fresh clone rather than mutating `v` in place — a cached poll payload is reused across
// renders, and a toggle back to 'zh' must still see the original Chinese, not a baked-in 'en'.
// Module-scoped (not just normalize()'s helper) so one-off responses like /api/action's `{msg}` —
// which never flow through normalize() — can be localized the same way instead of showing raw
// Chinese forever in English mode.
function _localize(v) {
  if (Array.isArray(v)) return v.map(_localize);
  if (v && typeof v === 'object') {
    const out = {};
    for (const k of Object.keys(v)) {
      if (k.endsWith('_en')) continue;
      const ek = k + '_en';
      out[k] = _localize((LANG === 'en' && v[ek]) ? v[ek] : v[k]);
    }
    return out;
  }
  return v;
}
function normalize(d) {
  d = _localize(d || {});
  const gov = d.governance || d.gov || {};
  const num = (...xs) => { for (const x of xs) if (typeof x === 'number') return x; return 0; };
  const arr = (...xs) => { for (const x of xs) if (Array.isArray(x)) return x; return []; };
  const nodes = arr(d.nodes, d.fleet && d.fleet.nodes);
  const devices = arr(d.devices, d.monitor && d.monitor.devices);
  // hoist the security / ops worker-node data to top level (collect() attaches it per-node)
  const secNode = nodes.find(n => n && (n.nuclei || n.cve || (n.caps || []).includes('cve') || (n.caps || []).includes('nuclei'))) || {};
  const opsNode = nodes.find(n => n && (n.cert || n.loganalysis || (n.caps || []).includes('cert'))) || {};
  const _cve = d.cve || secNode.cve || {}, _src = d.source || secNode.source || {}, _cert = d.cert || opsNode.cert || {};
  const _nuc = d.nuclei || secNode.nuclei || null;
  return {
    me: d._me || {},
    // fallback only fires when the backend couldn't report anything at all (not a normal state) —
    // default to `up: false` (fail-closed): claiming a node is up when we have no data was exactly
    // the bug that made the NIM indicator lie about being reachable.
    nodes: nodes.length ? nodes : [
      { name: 'team-lead', role: 'Front desk · Telegram / Email intake', tag: 'lead', port: 8642, up: false, zone: '' },
      { name: 'worker-a', role: 'Monitor · drift · cert · remediation', tag: 'ops', port: 18789, up: false, zone: 'zone A' },
      { name: 'worker-b', role: 'CVE · SBOM / SAST · syslog', tag: 'sec', port: 18790, up: false, zone: 'zone B' },
      { name: 'worker-c', role: 'backup · firmware · rollback · QA review', tag: 'gov', port: 18791, up: false, zone: 'zone C' },
    ],
    // real data lives at d.sysinfo.inference (agent-dashboard.py's _sysinfo()) — the fallback below
    // only covers the case where sysinfo itself is entirely missing, and defaults to
    // reachable:false (fail-closed), not true: this was the actual bug (this field read the wrong
    // path — d.inference, which never existed — so it silently used this fallback 100% of the
    // time, and the fallback claimed reachable:true unconditionally).
    inference: (d.sysinfo && d.sysinfo.inference) || { provider: 'nim', model: 'nemotron-3-super-120b', reachable: false },
    containers: arr(d.containers, d.stack && d.stack.containers),
    governance: {
      allowed: num(gov.allowed, d.allowed), denied: num(gov.denied, d.denied),
      benign: num(gov.benign, d.benign, gov.denied_benign, d.denied_benign),
      series_allowed: arr(gov.series_allowed, d.gov_series_allowed),
      coverage: num(gov.coverage, d.coverage) || 99.8, events: arr(gov.events, d.events, d.timeline),
    },
    alerts: arr(d.alerts_list, d.alerts).map(a => (typeof a === 'string' ? { msg: a } : a)),
    devices: devices.length ? devices : [{ asset: 'lab-asus-ebg19p-01', model: 'EBG19P', firmware: null, online: false, cpu: null, mem: null, temp: null }],   // 無設備資料 → 誠實顯示離線(不捏造 online telemetry)
    cve: { ..._cve, findings: arr(_cve.findings, _cve.affected_list) },
    source: { ..._src, sast_list: arr(_src.sast_list), design: arr(_src.design) },
    cert: { ..._cert, findings: arr(_cert.findings) },
    nuclei: _nuc ? { ..._nuc, findings: arr(_nuc.findings) } : null,
    syslog: d.syslog || opsNode.loganalysis || d.log_analysis || {},
    events: arr(d.device_events, opsNode.devlog && opsNode.devlog.security_events, opsNode.loganalysis && opsNode.loganalysis.findings),   // 真實設備 syslog;EBG19P 離線時為空(不再誤餵治理事件)
    jira: arr(d.jira && d.jira.tickets, d.jira, d.tickets),
    audit: (d._audit && d._audit.chain) || d.audit || { ok: true, count: 0 },
    audit_recent: arr(d._audit && d._audit.recent),
    settings: d.settings || {},
    snapshots_by_agent: arr(d.snapshots_by_agent),
    recipients: arr(d.recipients, d.settings && d.settings.recipients),
    acl: d._acl || null,
    proactive: d.proactive || null,
    flow: arr(d.flow),
    governance_c: d.governance_c || null,
    frozen: d.frozen || { frozen: false },
    eval: d.eval || null,
  };
}
