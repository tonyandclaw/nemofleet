// api.js — thin client for the dashboard's JSON endpoints (same-origin, cookie auth).
// The ONLY seam between the React UI and the Python backend.
const _J = { Accept: 'application/json' };
async function _get(path) {
  const r = await fetch(path, { credentials: 'same-origin', headers: _J });
  if (r.status === 401) { location.href = '/login'; throw new Error('auth required'); }
  if (!r.ok) throw new Error('HTTP ' + r.status);
  return r.json();
}
async function _post(path, body) {
  const opt = { method: 'POST', credentials: 'same-origin', headers: { ..._J } };
  if (body !== undefined) { opt.headers['Content-Type'] = 'application/json'; opt.body = JSON.stringify(body); }
  const r = await fetch(path, opt);
  if (r.status === 401) { location.href = '/login'; throw new Error('auth required'); }
  try { return await r.json(); } catch { return { ok: r.ok }; }
}
const qs = o => Object.entries(o).filter(([, v]) => v != null && v !== '').map(([k, v]) => k + '=' + encodeURIComponent(v)).join('&');

const NF = {
  status: () => _get('/api/status'),
  action: (act) => _post('/api/action?do=' + encodeURIComponent(act)),
  // write controls (map 1:1 to the existing admin endpoints)
  config: (k, v) => _post('/api/config?' + qs({ k, v })),
  certPolicy: (p) => _post('/api/cert-policy?' + qs(p)),
  recipient: (op, name, telegram, email) => _post('/api/recipient?' + qs({ op, name, telegram, email })),
  users: (body) => _post('/api/users', body),
  authConfig: (body) => _post('/api/auth-config', body),
  snapshot: (op, sel, sb) => _post('/api/snapshot?' + qs({ op, sel, sb })),
  sys: (p) => _get('/api/sys?' + qs(p)),
  policy: (body) => _post('/api/policy', body),

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
function normalize(d) {
  d = d || {};
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
    nodes: nodes.length ? nodes : [
      { name: 'team-lead', role: 'Front desk · Telegram / Email intake', tag: 'lead', port: 8642, up: true, zone: '' },
      { name: 'worker-a', role: 'Monitor · drift · cert · remediation', tag: 'ops', port: 18789, up: true, zone: 'zone A' },
      { name: 'worker-b', role: 'CVE · SBOM / SAST · syslog', tag: 'sec', port: 18790, up: true, zone: 'zone B' },
      { name: 'worker-c', role: 'backup · firmware · rollback · QA review', tag: 'gov', port: 18791, up: true, zone: 'zone C' },
    ],
    inference: d.inference || { provider: 'nim', model: 'nemotron-3-super-120b', reachable: true },
    containers: arr(d.containers, d.stack && d.stack.containers),
    governance: {
      allowed: num(gov.allowed, d.allowed), denied: num(gov.denied, d.denied),
      benign: num(gov.benign, d.benign, gov.denied_benign, d.denied_benign),
      series_allowed: arr(gov.series_allowed, d.gov_series_allowed),
      coverage: num(gov.coverage, d.coverage) || 99.8, events: arr(gov.events, d.timeline, d.events),
    },
    alerts: arr(d.alerts_list, d.alerts).map(a => (typeof a === 'string' ? { msg: a } : a)),
    devices: devices.length ? devices : [{ asset: 'lab-asus-ebg19p-01', model: 'EBG19P', firmware: '3.0.0.6.102_45537', online: true, cpu: 12, mem: 34, temp: 51 }],
    cve: { ..._cve, findings: arr(_cve.findings, _cve.affected_list) },
    source: { ..._src, sast_list: arr(_src.sast_list), design: arr(_src.design) },
    cert: { ..._cert, findings: arr(_cert.findings) },
    nuclei: _nuc ? { ..._nuc, findings: arr(_nuc.findings) } : null,
    syslog: d.syslog || opsNode.loganalysis || d.log_analysis || {},
    events: arr(d.events, d.device_log, d.monitor && d.monitor.events),
    jira: arr(d.jira && d.jira.tickets, d.jira, d.tickets),
    audit: (d._audit && d._audit.chain) || d.audit || { ok: true, count: 0 },
    audit_recent: arr(d._audit && d._audit.recent),
    settings: d.settings || {},
    recipients: arr(d.recipients, d.settings && d.settings.recipients),
    acl: d._acl || null,
    proactive: d.proactive || null,
    flow: arr(d.flow),
    governance_c: d.governance_c || null,
  };
}
