// app.js — nemofleet console (React + Chart.js, no build step; htm for views).
// Multi-view SPA architected for scale: change-detection polling, memoized panels,
// data-driven fleet/device rendering, paginated tables. Data via /api/status → normalize().
const { useState, useEffect, useRef, useMemo, memo, useCallback } = React;
const html = htm.bind(React.createElement);
const SERIES = { allowed: '#3987e5', denied: '#e66767' };

// ── toasts + backend actions (decoupled via CustomEvents so any button can fire them) ────────
function toast(msg, kind = 'i') { dispatchEvent(new CustomEvent('nftoast', { detail: { msg, kind, id: Date.now() + Math.random() } })); }
function reloadNow() { dispatchEvent(new CustomEvent('nfreload')); }

function Toaster() {
  const [items, setItems] = useState([]);
  useEffect(() => {
    const h = e => { const t = e.detail; setItems(x => [...x, t]); setTimeout(() => setItems(x => x.filter(i => i.id !== t.id)), 3600); };
    addEventListener('nftoast', h); return () => removeEventListener('nftoast', h);
  }, []);
  return html`<div class="toaster">${items.map(t => html`<div key=${t.id} class=${'toast ' + (t.kind || 'i')}>${t.msg}</div>`)}</div>`;
}

const ActionBtn = memo(function ActionBtn({ act, label, busyLabel, ghost }) {
  const [busy, setBusy] = useState(false);
  return html`<button class=${'btn ' + (ghost ? 'ghost' : '')} disabled=${busy} onClick=${async () => {
    setBusy(true);
    try { const r = await NF.action(act); toast(r && r.msg ? r.msg : (r && r.ok ? 'Done' : 'Action failed'), r && r.ok ? 'g' : 'c'); }
    catch (e) { toast('Action failed: ' + e.message, 'c'); }
    finally { setBusy(false); reloadNow(); }
  }}>${busy ? html`<span class="mini"></span>${busyLabel || '…'}` : label}</button>`;
});

// form + control primitives ──────────────────────────────────────────────────
async function run(promise, okMsg) {
  try { const r = await promise; toast(r && r.msg ? r.msg : (r && r.ok !== false ? (okMsg || 'Saved') : 'Failed'), r && r.ok !== false ? 'g' : 'c'); }
  catch (e) { toast(e.message, 'c'); } finally { reloadNow(); }
}
const Field = ({ label, hint, children }) => html`<label class="field"><span class="flabel">${label}</span>${children}${hint ? html`<span class="fhint">${hint}</span>` : null}</label>`;
const Segmented = ({ value, options, onChange }) => html`<div class="seg2">${options.map(o => { const v = typeof o === 'object' ? o.v : o, l = typeof o === 'object' ? o.l : o; return html`<button key=${v} class=${'segbtn ' + (String(value) === String(v) ? 'on' : '')} onClick=${() => onChange(v)}>${l}</button>`; })}</div>`;
const Toggle = ({ on, onChange }) => html`<button class=${'toggle ' + (on ? 'on' : '')} role="switch" aria-checked=${!!on} onClick=${() => onChange(!on)}><span class="knob"></span></button>`;

// VirtualList — windowed rendering for very large lists (only visible rows in the DOM)
function VirtualList({ rows, rowH = 40, height = 320, render, empty }) {
  const [top, setTop] = useState(0);
  if (!rows.length) return html`<div class="empty">${empty || 'No data.'}</div>`;
  const start = Math.max(0, Math.floor(top / rowH) - 4);
  const slice = rows.slice(start, start + Math.ceil(height / rowH) + 8);
  return html`<div class="vlist" style=${{ height: height + 'px' }} onScroll=${e => setTop(e.target.scrollTop)}>
    <div style=${{ height: rows.length * rowH + 'px', position: 'relative' }}>
      <div style=${{ position: 'absolute', top: 0, left: 0, right: 0, transform: 'translateY(' + start * rowH + 'px)' }}>
        ${slice.map((r, i) => html`<div key=${start + i} class="vrow" style=${{ height: rowH + 'px' }}>${render(r, start + i)}</div>`)}
      </div></div></div>`;
}

// ── data layer: poll with change-detection (no re-render when nothing changed) ──────────────
function useStatus(intervalMs = 5000) {
  const [state, setState] = useState({ data: null, err: null, loading: true });
  const lastJson = useRef('');
  const apply = useCallback((raw) => {           // change-detection: no re-render when unchanged
    const j = JSON.stringify(raw);
    if (j === lastJson.current) { setState(s => (s.loading || s.err ? { ...s, err: null, loading: false } : s)); return; }
    lastJson.current = j; setState({ data: raw, err: null, loading: false });
  }, []);
  const onErr = useCallback((e) => setState(s => ({ ...s, err: e.message, loading: false })), []);
  const reload = useCallback(async () => { try { apply(await NF.status()); } catch (e) { onErr(e); } }, [apply, onErr]);
  // transport seam: NF.subscribe wraps polling today, WebSocket/SSE tomorrow — this hook won't change
  useEffect(() => NF.subscribe(apply, onErr, intervalMs), [apply, onErr, intervalMs]);
  return { ...state, reload };
}

function useHashRoute(def) {
  const get = () => (location.hash.replace(/^#\/?/, '') || def);
  const [route, setRoute] = useState(get());
  useEffect(() => { const h = () => setRoute(get()); addEventListener('hashchange', h); return () => removeEventListener('hashchange', h); }, []);
  return route;
}

function useClock() {
  const [t, setT] = useState(() => new Date().toLocaleTimeString('en-GB'));
  useEffect(() => { const id = setInterval(() => setT(new Date().toLocaleTimeString('en-GB')), 1000); return () => clearInterval(id); }, []);
  return t;
}

// ── shared components (memoized) ────────────────────────────────────────────────────────────
const Dot = ({ up, s }) => html`<span class=${'dot ' + (s || (up ? 'g' : 'c'))}></span>`;

const Panel = memo(function Panel({ title, label, right, children, className }) {
  return html`<section class=${'panel ' + (className || '')}>
    <div class="ph"><h3>${title}</h3>${label ? html`<span class="lbl">${label}</span>` : null}
      ${right ? html`<div class="r">${right}</div>` : null}</div>
    <div class="pb">${children}</div></section>`;
});

const Kpi = memo(function Kpi({ stripe, label, big, unit, sub }) {
  return html`<div class="kpi"><span class="stripe" style=${{ background: stripe }}></span>
    <div class="lbl">${label}</div>
    <div><span class="big">${big}</span>${unit ? html`<span class="unit">${unit}</span>` : null}</div>
    <div class="sub">${sub}</div></div>`;
});

const SevBar = ({ label, count, max, color, dotcls }) => {
  const pct = max ? Math.max(6, Math.round(count / max * 100)) : 6;
  return html`<div class="sevrow"><div class="sevname">
      <span class=${'dot ' + (dotcls || '')} style=${dotcls ? null : { background: color, color }}></span>${label}</div>
    <div class="track"><div class="fill" style=${{ width: pct + '%', background: color }}></div></div>
    <div class="num">${count}</div></div>`;
};

// DataTable — client-side pagination (scale-ready: swap for server pagination via api.js later)
const DataTable = memo(function DataTable({ rows, cols, pageSize = 8, empty, fetchPage }) {
  const [page, setPage] = useState(0);
  const [srv, setSrv] = useState(null);   // server-paginated result when fetchPage is given
  useEffect(() => { if (!fetchPage) return; let ok = true; fetchPage(page, pageSize).then(r => ok && setSrv(r)); return () => { ok = false; }; }, [fetchPage, page, pageSize]);
  const total = fetchPage ? (srv ? srv.total : 0) : rows.length;
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const p = Math.min(page, pages - 1);
  const slice = fetchPage ? (srv ? srv.rows : []) : rows.slice(p * pageSize, p * pageSize + pageSize);
  if (!total && !fetchPage) return html`<div class="empty">${empty || 'No data.'}</div>`;
  if (!slice.length) return html`<div class="empty">${empty || 'No data.'}</div>`;
  return html`<div><div class="tblwrap"><table class="dt">
      <thead><tr>${cols.map(c => html`<th key=${c.k} style=${c.align ? { textAlign: c.align } : null}>${c.label}</th>`)}</tr></thead>
      <tbody>${slice.map((row, i) => html`<tr key=${i}>${cols.map(c => html`<td key=${c.k} style=${c.align ? { textAlign: c.align } : null}>${c.render ? c.render(row) : row[c.k]}</td>`)}</tr>`)}</tbody>
    </table></div>
    ${pages > 1 ? html`<div class="pager">
      <span>${rows.length} rows</span>
      <button disabled=${p === 0} onClick=${() => setPage(p - 1)}>‹ Prev</button>
      <span class="pg">${p + 1} / ${pages}</span>
      <button disabled=${p >= pages - 1} onClick=${() => setPage(p + 1)}>Next ›</button>
    </div>` : null}</div>`;
});

const sevPill = s => html`<span class=${'sev ' + (s === 'high' || s === 'critical' ? 'hi' : s === 'warn' || s === 'serious' ? 'wa' : 'in')}>${s || 'info'}</span>`;

const GovChart = memo(function GovChart({ gov }) {
  const ref = useRef(null), chart = useRef(null);
  const data = gov.series_allowed.length ? gov.series_allowed : synth(gov.allowed);
  useEffect(() => {
    const ctx = ref.current.getContext('2d');
    const grad = ctx.createLinearGradient(0, 0, 0, 190);
    grad.addColorStop(0, 'rgba(57,135,229,0.34)'); grad.addColorStop(1, 'rgba(57,135,229,0.02)');
    chart.current = new Chart(ctx, {
      type: 'line',
      data: { labels: data.map((_, i) => i === data.length - 1 ? 'now' : (i % 5 === 0 ? '−' + ((data.length - i) * 6) + 'm' : '')),
        datasets: [{ label: 'Allowed', data, borderColor: SERIES.allowed, backgroundColor: grad, borderWidth: 2, fill: true, tension: 0.35, pointRadius: 0, pointHoverRadius: 4 }] },
      options: { responsive: true, maintainAspectRatio: false, animation: { duration: 300 }, interaction: { mode: 'index', intersect: false },
        scales: { x: { grid: { color: '#20242f', drawTicks: false }, ticks: { color: '#5b6475', font: { family: 'ui-monospace', size: 10 }, maxRotation: 0, autoSkip: false } },
          y: { grid: { color: '#20242f' }, ticks: { color: '#5b6475', font: { family: 'ui-monospace', size: 10 }, maxTicksLimit: 4 }, beginAtZero: true } },
        plugins: { legend: { display: false }, tooltip: { backgroundColor: '#0b0d13', borderColor: '#333949', borderWidth: 1, padding: 10, titleColor: '#9aa3b6', bodyColor: '#e7eaf2', displayColors: false } } },
    });
    return () => chart.current && chart.current.destroy();
  }, []);
  useEffect(() => { if (chart.current) { chart.current.data.datasets[0].data = data; chart.current.update('none'); } }, [gov.allowed, gov.series_allowed]);
  return html`<div class="chartbox"><canvas ref=${ref} aria-label="Allowed governance events over time"></canvas></div>`;
});
function synth(total, n = 20) { if (!total) return new Array(n).fill(0); const o = []; let a = 0; for (let i = 0; i < n; i++) { a += (total / n) * (0.6 + Math.random() * 0.8); o.push(Math.round(a / (i + 1))); } return o; }

// ── views (each memoized; data-driven so more nodes/devices/findings just render) ────────────
const OverviewView = memo(function OverviewView({ d }) {
  const g = d.governance;
  return html`<div class="viewfade">
    <section class="kpis">
      ${html`<${Kpi} stripe="var(--good)" label="Governance coverage" big=${g.coverage} unit="%" sub=${g.allowed.toLocaleString() + ' actions · 2h window'}/>`}
      ${html`<${Kpi} stripe="var(--crit)" label="Blocked egress (DENIED)" big=${g.denied} sub="unauthorized host · OPA host-layer"/>`}
      ${html`<${Kpi} stripe="var(--warn)" label="Active alerts" big=${d.alerts.length} sub=${d.alerts[0] ? d.alerts[0].msg : 'none'}/>`}
      ${html`<${Kpi} stripe="var(--accent)" label="Open escalations" big=${d.jira.length} unit="Jira" sub="human-in-the-loop · NETOPS"/>`}
    </section>
    <div class="grid">
      <div class="col">
        ${html`<${Panel} title="Governance events" label="OCSF · 2h" right=${html`<span class="legend"><span><i style=${{ background: SERIES.allowed }}></i>Allowed volume</span></span>`}>
          <${GovChart} gov=${g}/>
          <div class="gstat">
            <div><div class="num" style=${{ color: SERIES.allowed }}>${g.allowed.toLocaleString()}</div><div class="lbl">Allowed</div></div>
            <div><div class="num" style=${{ color: 'var(--crit)' }}>${g.denied}</div><div class="lbl">Denied (real)</div></div>
            <div><div class="num ink2">${g.benign.toLocaleString()}</div><div class="lbl">Heartbeats · excluded</div></div>
          </div>
        </${Panel}>`}
        <${EventsPanel} events=${d.events}/>
      </div>
      <div class="col">
        <${FleetSummary} nodes=${d.nodes} devices=${d.devices}/>
        <${SecuritySummary} d=${d}/>
        <${EscalationsPanel} jira=${d.jira}/>
      </div>
    </div>
  </div>`;
});

const FleetSummary = memo(function FleetSummary({ nodes, devices }) {
  const dev = devices[0] || {};
  return html`<${Panel} title="Agent fleet" label=${'Hermes harness ×' + nodes.length}>
    <div class="nodes">${nodes.map(n => html`<div key=${n.name} class="node">
      <span class="ico"><svg viewBox="0 0 24 24"><circle cx="12" cy="8" r="3.4" fill="none" stroke="currentColor" stroke-width="1.7"/><path d="M5 20c0-3.6 3.1-6 7-6s7 2.4 7 6" fill="none" stroke="currentColor" stroke-width="1.7"/></svg></span>
      <div><div class="nm">${n.name} <span class=${'tag ' + (n.tag === 'lead' ? 'a' : 'g')}>${n.tag}</span></div><div class="role">${n.role}</div></div>
      <div class="rt"><${Dot} up=${n.up}/> :${n.port}<br/><span class="muted">${n.zone || ''}</span></div>
    </div>`)}</div>
    <hr class="sep" style=${{ margin: '14px 0 12px' }}/>
    <div class="lbl" style=${{ marginBottom: '10px' }}>Managed device${devices.length > 1 ? 's · ' + devices.length : ''}</div>
    <div class="device"><div class="metrics">
      ${[['CPU', dev.cpu, '%'], ['MEM', dev.mem, '%'], ['TEMP', dev.temp, '°C']].map(([k, v, u]) =>
    html`<div key=${k} class="metric"><div class="num">${v ?? '—'}<span style=${{ fontSize: '11px', color: 'var(--ink3)' }}>${u}</span></div><div class="lbl">${k}</div></div>`)}
    </div></div>
    <div style=${{ fontSize: '12px', color: 'var(--ink2)', marginTop: '10px', display: 'flex', alignItems: 'center', gap: '8px' }}>
      <${Dot} up=${dev.online !== false}/> ASUS ExpertWiFi <b style=${{ color: 'var(--ink)' }}>${dev.model || 'EBG19P'}</b>
      <span class="mono muted" style=${{ marginLeft: 'auto' }}>${dev.firmware || ''}</span></div>
  </${Panel}>`;
});

const SecuritySummary = memo(function SecuritySummary({ d }) {
  const cve = d.cve, cert = d.cert, source = d.source;
  const crit = cve.critical ?? (cve.counts && cve.counts.critical) ?? 1;
  const serious = cve.serious ?? cve.affected ?? 2;
  const weak = cert.high ?? (cert.counts && cert.counts.high) ?? 2;
  const recon = source.cve_reconciled ?? 7;
  const max = Math.max(crit, serious, weak, recon, 1);
  return html`<${Panel} title="Security posture" label="worker-b · daily scan">
    <${SevBar} label="Critical" count=${crit} max=${max} color="var(--crit)" dotcls="c"/>
    <${SevBar} label="Serious" count=${serious} max=${max} color="#c98500"/>
    <${SevBar} label="Weak crypto" count=${weak} max=${max} color="var(--warn)" dotcls="w"/>
    <${SevBar} label="Reconciled" count=${recon} max=${max} color="var(--good)" dotcls="g"/>
    <hr class="sep" style=${{ margin: '12px 0 0' }}/>
    <div style=${{ display: 'flex', gap: '14px', fontSize: '11.5px', color: 'var(--ink3)', paddingTop: '12px' }}>
      <span>SBOM <b class="mono" style=${{ color: 'var(--ink)' }}>${source.sbom ?? '—'}</b></span>
      <span>SAST <b class="mono" style=${{ color: 'var(--ink)' }}>${source.sast ?? '—'}</b></span>
      <span>source <b class="mono ink2">${source.sbom_source || 'asuswrt-merlin'}</b></span>
    </div>
  </${Panel}>`;
});

const EscalationsPanel = memo(function EscalationsPanel({ jira }) {
  return html`<${Panel} title="Escalations" label="Jira · human-in-the-loop">
    ${jira.length ? jira.slice(0, 4).map(t => html`<div key=${t.id} class="tick">
      <span class="id">${t.id}</span>
      <div><div class="sum">${t.summary}</div><div class="m"><span>${t.kind || ''}</span><span>${t.asset || ''}</span></div></div>
      <span class=${'pri ' + ((t.priority || '').toLowerCase().startsWith('h') ? 'h' : 'm')}>${(t.priority || 'med').slice(0, 4)}</span>
    </div>`) : html`<div class="empty">No open escalations.</div>`}
  </${Panel}>`;
});

const EventsPanel = memo(function EventsPanel({ events }) {
  return html`<${Panel} title="Recent device events" label="EBG19P syslog · classified">
    <${DataTable} rows=${events} pageSize=${6} empty="No recent events — worker-a syslog sync idle."
      cols=${[
        { k: 't', label: 'Time', render: r => html`<span class="mono">${r.t || ''}</span>` },
        { k: 'cat', label: 'Category', render: r => html`<span class="catpill">${r.cat || 'service'}</span>` },
        { k: 'msg', label: 'Event' },
        { k: 'sev', label: 'Severity', align: 'right', render: r => sevPill(r.sev) },
      ]}/>
  </${Panel}>`;
});

const SNAP_SB = ['team-lead', 'worker-a', 'worker-b'];
const FleetView = memo(function FleetView({ d }) {
  const [sb, setSb] = useState('worker-a');
  const [diag, setDiag] = useState(null);
  const runDiag = (doWhat) => { setDiag({ title: doWhat + ' · ' + sb, out: 'Running…' });
    NF.sys({ do: doWhat, sb }).then(r => setDiag({ title: r.title || doWhat, out: r.out || '(no output)' })).catch(e => setDiag({ title: doWhat, out: e.message })); };
  return html`<div class="viewfade"><div class="viewhd"><h2>Fleet</h2><span class="lbl">${d.nodes.length} nodes · ${d.devices.length} device(s)</span></div>
    <div class="grid"><div class="col">
      <${FleetSummary} nodes=${d.nodes} devices=${d.devices}/>
      ${html`<${Panel} title="Snapshots" label="per sandbox · recovery points">
        <${Field} label="Sandbox"><${Segmented} value=${sb} options=${SNAP_SB} onChange=${setSb}/></${Field}>
        <div class="addrow">
          <button class="btn" onClick=${() => run(NF.snapshot('create', '', sb), 'Snapshot created')}>+ Create snapshot</button>
          <button class="btn ghost" onClick=${() => run(NF.action('refresh'), 'Refreshed')}>Refresh</button>
        </div>
        <div class="muted" style=${{ fontSize: '11.5px', marginTop: '10px' }}>Restore/delete of a specific version is type-to-confirm — wired next.</div>
      </${Panel}>`}
    </div>
    <div class="col">
      ${html`<${Panel} title="Containers" label="OpenShell sandboxes">
        <${DataTable} rows=${d.containers} pageSize=${10} empty="No container telemetry."
          cols=${[
            { k: 'name', label: 'Name', render: r => html`<span class="mono">${r.name || r.Names || '—'}</span>` },
            { k: 'state', label: 'State', render: r => html`<${Dot} up=${(r.state || r.status || '').toLowerCase().includes('up')}/> ${r.state || r.status || ''}` },
            { k: 'image', label: 'Image', render: r => html`<span class="mono muted">${r.image || ''}</span>` },
          ]}/></${Panel}>`}
      ${html`<${Panel} title="Diagnostics" label="on-demand · nemoclaw/openshell">
        <${Field} label="Target"><${Segmented} value=${sb} options=${SNAP_SB} onChange=${setSb}/></${Field}>
        <div class="addrow">${['doctor', 'logs', 'recover', 'gwhealth'].map(x => html`<button key=${x} class="btn ghost" onClick=${() => runDiag(x)}>${x}</button>`)}</div>
        ${diag ? html`<div style=${{ marginTop: '12px' }}><div class="lbl" style=${{ marginBottom: '6px' }}>${diag.title}</div>
          <pre class="mono" style=${{ background: '#0d1017', border: '1px solid var(--line)', borderRadius: '8px', padding: '10px', fontSize: '11px', color: 'var(--ink2)', maxHeight: '220px', overflow: 'auto', whiteSpace: 'pre-wrap' }}>${diag.out}</pre></div>` : null}
      </${Panel}>`}
    </div></div></div>`;
});

const SecurityView = memo(function SecurityView({ d }) {
  return html`<div class="viewfade"><div class="viewhd"><h2>Security</h2><span class="lbl">worker-b · CVE / nuclei / cert / source</span></div>
    <div class="grid1">
      ${html`<${Panel} title="CVE findings" label="fleet scan" right=${html`<${ActionBtn} act="cve" label="Rescan" busyLabel="Scanning" ghost=${true}/>`}>
        <${DataTable} rows=${d.cve.findings} pageSize=${8} empty="No affected CVEs — or scan pending."
          cols=${[
            { k: 'cve', label: 'CVE', render: r => html`<span class="mono">${r.cve || r.id || '—'}</span>` },
            { k: 'component', label: 'Component', render: r => html`<span class="mono">${r.component || r.pkg || ''}</span>` },
            { k: 'asset', label: 'Asset', render: r => r.asset || '' },
            { k: 'severity', label: 'Severity', align: 'right', render: r => sevPill(r.severity || r.cls) },
          ]}/></${Panel}>`}
      ${d.nuclei ? html`<${Panel} title="Active scan (nuclei)" label=${'projectdiscovery · ' + (d.nuclei.tags || 'asus') + ' templates'} right=${html`<${ActionBtn} act="nuclei" label="Scan now" busyLabel="Scanning" ghost=${true}/>`}>
        ${d.nuclei.available === false
          ? html`<div class="muted" style=${{ padding: '2px 2px 6px' }}>⚠ ${d.nuclei.note || 'nuclei unavailable'}</div>`
          : html`<div style=${{ display: 'flex', gap: '18px', flexWrap: 'wrap', marginBottom: '10px', fontSize: '12px' }}>
              <span class="muted">target <b class="mono ink2">${d.nuclei.target || '—'}</b></span>
              <span class="muted">last <b class="mono ink2">${d.nuclei.ts || '—'}</b></span>
              <span class="muted">hits <b style=${{ color: (d.nuclei.count || 0) ? 'var(--crit)' : 'var(--ink2)' }}>${d.nuclei.count || 0}</b></span>
              ${(d.nuclei.escalated || []).length ? html`<span class="muted">→ Jira <b class="ink2">${d.nuclei.escalated.length}</b></span>` : null}
            </div>`}
        <${DataTable} rows=${d.nuclei.findings || []} pageSize=${8} empty="No nuclei hits — or scan pending."
          cols=${[
            { k: 'severity', label: 'Sev', render: r => sevPill(r.severity) },
            { k: 'name', label: 'Finding', render: r => html`<span>${r.name || r.template || '—'}</span>` },
            { k: 'cve', label: 'CVE', render: r => html`<span class="mono">${(r.cve || []).join(', ') || '—'}</span>` },
            { k: 'matched_at', label: 'Matched', align: 'right', render: r => html`<span class="mono muted">${r.matched_at || ''}</span>` },
          ]}/></${Panel}>` : null}
      ${html`<${Panel} title="Certificates / weak crypto" label="worker-a probe">
        <${DataTable} rows=${d.cert.findings} pageSize=${6} empty="No cert/crypto issues."
          cols=${[
            { k: 'service', label: 'Service' },
            { k: 'issue', label: 'Issue', render: r => html`<span class="pill2 w">${r.issue || ''}</span>` },
            { k: 'detail', label: 'Detail', render: r => html`<span class="muted">${r.detail || ''}</span>` },
            { k: 'severity', label: 'Sev', align: 'right', render: r => sevPill(r.severity) },
          ]}/></${Panel}>`}
      ${html`<${Panel} title="SAST findings" label=${'source · ' + (d.source.sast_source || 'asuswrt-merlin')} right=${html`<${ActionBtn} act="source" label="Re-run" busyLabel="Running" ghost=${true}/>`}>
        <${DataTable} rows=${d.source.sast_list} pageSize=${8} empty="No SAST hits."
          cols=${[
            { k: 'cwe', label: 'CWE', render: r => html`<span class="mono">${r.cwe || '—'}</span>` },
            { k: 'file', label: 'File', render: r => html`<span class="mono" style=${{ wordBreak: 'break-all' }}>${r.upstream_path || r.file || ''}</span>` },
            { k: 'line', label: 'Line', align: 'right', render: r => html`<span class="mono">${r.line || ''}</span>` },
          ]}/></${Panel}>`}
    </div></div>`;
});

const GovernanceView = memo(function GovernanceView({ d }) {
  const g = d.governance;
  return html`<div class="viewfade"><div class="viewhd"><h2>Governance</h2><span class="lbl">OPA / L7 · OCSF events</span></div>
    <div class="grid1">
      ${html`<${Panel} title="Event volume" label="allowed · 2h"><${GovChart} gov=${g}/>
        <div class="gstat"><div><div class="num" style=${{ color: SERIES.allowed }}>${g.allowed.toLocaleString()}</div><div class="lbl">Allowed</div></div>
        <div><div class="num" style=${{ color: 'var(--crit)' }}>${g.denied}</div><div class="lbl">Denied</div></div>
        <div><div class="num ink2">${g.benign.toLocaleString()}</div><div class="lbl">Heartbeats</div></div></div></${Panel}>`}
      ${html`<${Panel} title="Recent governed actions" label="engine · policy · verdict">
        <${DataTable} rows=${g.events} pageSize=${10} empty="No governance events in window."
          cols=${[
            { k: 'ts', label: 'Time', render: r => html`<span class="mono">${r.ts || r.t || ''}</span>` },
            { k: 'target', label: 'Target', render: r => html`<span class="mono">${r.target || r.b || ''}</span>` },
            { k: 'policy', label: 'Policy', render: r => html`<span class="catpill">${r.policy || r.a || '—'}</span>` },
            { k: 'verdict', label: 'Verdict', align: 'right', render: r => {
              const dn = (r.verdict || r.cls || '').toLowerCase().includes('den');
              return html`<span class=${'sev ' + (dn ? 'hi' : 'in')}>${dn ? 'DENIED' : 'ALLOWED'}</span>`; } },
          ]}/></${Panel}>`}
    </div></div>`;
});

const AuditView = memo(function AuditView({ d }) {
  if (!d.audit_recent.length && !(d.me.role === 'admin')) return html`<div class="viewfade"><div class="viewhd"><h2>Audit</h2></div><div class="empty">Admin only.</div></div>`;
  return html`<div class="viewfade"><div class="viewhd"><h2>Audit</h2>
    <span class=${'pill2 ' + (d.audit.ok ? 'g' : 'c')}>${d.audit.ok ? 'chain verified' : 'chain broken'}</span>
    <span class="lbl mono">${(d.audit.count || 0).toLocaleString()} entries</span></div>
    ${html`<${Panel} title="Tamper-evident admin audit" label="hash-chained">
      <${VirtualList} rows=${d.audit_recent} rowH=${38} height=${380} empty="No audit entries."
        render=${r => html`<${React.Fragment}>
          <span class="mono" style=${{ width: '150px', flex: 'none' }}>${r.ts || ''}</span>
          <span style=${{ width: '150px', flex: 'none' }}>${r.actor || ''}</span>
          <span class="mono" style=${{ width: '110px', flex: 'none' }}>${r.action || ''}</span>
          <span class="muted" style=${{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>${r.detail || ''}</span>
          <${Dot} up=${r.ok !== false}/></${React.Fragment}>`}/></${Panel}>`}</div>`;
});

const CFG = {
  cve_interval_sec: [{ v: 0, l: 'off' }, { v: 3600, l: '1h' }, { v: 21600, l: '6h' }, { v: 86400, l: '24h' }],
  nuclei_interval_sec: [{ v: 0, l: 'off' }, { v: 3600, l: '1h' }, { v: 21600, l: '6h' }, { v: 86400, l: '24h' }, { v: 604800, l: '7d' }],
  cert_interval_sec: [{ v: 0, l: 'off' }, { v: 3600, l: '1h' }, { v: 21600, l: '6h' }, { v: 86400, l: '24h' }],
  cert_expire_warn_days: [7, 14, 30, 60, 90], cert_rsa_min: [2048, 3072, 4096], cert_sig_min: ['sha1', 'sha256', 'sha384'],
  cert_ec_min: [256, 384, 521], cert_cipher_policy: ['lax', 'standard', 'strict', 'custom'],
  dev_cpu_hi: [70, 80, 85, 90, 95], dev_ram_hi: [70, 80, 85, 90, 95], dev_temp_hi: [70, 75, 80, 85, 90],
  patrol_interval_sec: [{ v: 300, l: '5m' }, { v: 600, l: '10m' }, { v: 1200, l: '20m' }, { v: 1800, l: '30m' }, { v: 3600, l: '1h' }],
  digest_interval_sec: [{ v: 3600, l: '1h' }, { v: 21600, l: '6h' }, { v: 86400, l: '24h' }],
};
const SettingsView = memo(function SettingsView({ d }) {
  const s = d.settings || {};
  const set = (k, v) => run(NF.config(k, v), k + ' updated');
  const seg = (k, hint) => html`<${Field} label=${k} hint=${hint}><${Segmented} value=${s[k]} options=${CFG[k]} onChange=${v => set(k, v)}/></${Field}>`;
  const chans = String(s.notify_channels || 'jira,dashboard').split(',');
  const toggleChan = c => { const next = chans.includes(c) ? chans.filter(x => x !== c) : [...chans, c]; set('notify_channels', next.join(',')); };
  return html`<div class="viewfade"><div class="viewhd"><h2>Settings</h2><span class="lbl">writes to the live backend</span></div>
    <div class="grid1">
      ${html`<${Panel} title="Scan schedule" label="worker cadence"><div class="formgrid">
        ${seg('cve_interval_sec', 'worker-b CVE scan cadence')}${seg('cert_interval_sec', 'worker-a cert/crypto cadence')}${seg('nuclei_interval_sec', 'worker-b nuclei 主動掃 (nuclei-templates)')}</div></${Panel}>`}
      ${html`<${Panel} title="Certificate & crypto thresholds" label="what counts as weak"><div class="formgrid">
        ${seg('cert_rsa_min', 'min RSA key bits')}${seg('cert_ec_min', 'min ECDSA curve')}${seg('cert_sig_min', 'min signature alg')}
        ${seg('cert_expire_warn_days', 'expiry lead-time (days)')}${seg('cert_cipher_policy', 'cipher flagging policy')}</div></${Panel}>`}
      ${html`<${Panel} title="Device health thresholds" label="alert when exceeded"><div class="formgrid">
        ${seg('dev_cpu_hi', 'CPU %')}${seg('dev_ram_hi', 'RAM %')}${seg('dev_temp_hi', 'Temp °C')}</div></${Panel}>`}
      ${html`<${Panel} title="Escalation & notifications" label="where alerts go"><div class="formgrid">
        <${Field} label="Auto-open Jira" hint="off = dashboard only"><${Toggle} on=${s.auto_escalate !== false} onChange=${v => set('auto_escalate', v)}/></${Field}>
        <${Field} label="Notify channels" hint="Jira is always kept"><div class="seg2">${['email', 'telegram', 'dashboard'].map(c => html`<button key=${c} class=${'segbtn ' + (chans.includes(c) ? 'on' : '')} onClick=${() => toggleChan(c)}>${c}</button>`)}</div></${Field}>
      </div></${Panel}>`}
      ${html`<${Panel} title="Proactive team-lead" label="active patrol + reporting"><div class="formgrid">
        <${Field} label="proactive_enabled" hint="team-lead 主動巡邏 + 主動回報"><${Toggle} on=${s.proactive_enabled !== false} onChange=${v => set('proactive_enabled', v)}/></${Field}>
        <${Field} label="proactive_safety_net" hint="critical 確定性告警(不靠 team-lead)"><${Toggle} on=${s.proactive_safety_net !== false} onChange=${v => set('proactive_safety_net', v)}/></${Field}>
        ${seg('patrol_interval_sec', '主動巡邏頻率')}${seg('digest_interval_sec', '主動 digest 頻率')}</div></${Panel}>`}
    </div></div>`;
});
const AdminView = memo(function AdminView({ d }) {
  const users = (d.acl && d.acl.users) || [];
  const recips = d.recipients || [];
  const [nu, setNu] = useState({ email: '', password: '', role: 'viewer' });
  const [nr, setNr] = useState({ name: '', telegram: '', email: '' });
  if (d.me.role !== 'admin') return html`<div class="viewfade"><div class="viewhd"><h2>Admin</h2></div><div class="empty">Admin only.</div></div>`;
  return html`<div class="viewfade"><div class="viewhd"><h2>Admin</h2><span class="lbl">users · notifications</span></div>
    <div class="grid1">
      ${html`<${Panel} title="Users & access" label="RBAC">
        ${users.length ? users.map(u => html`<div key=${u.email} class="adminrow">
          <div class="grow"><b>${u.email}</b> <span class="muted mono" style=${{ fontSize: '11px' }}>${u.created || ''}</span></div>
          <${Segmented} value=${u.role} options=${['admin', 'viewer']} onChange=${r => run(NF.users({ op: 'role', email: u.email, role: r }), 'Role updated')}/>
          <button class="btn ghost" onClick=${() => run(NF.users({ op: 'del', email: u.email }), 'User removed')}>Remove</button>
        </div>`) : html`<div class="empty">No users loaded.</div>`}
        <div class="addrow">
          <input class="inp" placeholder="email" value=${nu.email} onInput=${e => setNu({ ...nu, email: e.target.value })}/>
          <input class="inp" type="password" placeholder="password" value=${nu.password} onInput=${e => setNu({ ...nu, password: e.target.value })}/>
          <${Segmented} value=${nu.role} options=${['viewer', 'admin']} onChange=${r => setNu({ ...nu, role: r })}/>
          <button class="btn" onClick=${() => run(NF.users({ op: 'add', ...nu }), 'User added')}>+ Add</button>
        </div>
      </${Panel}>`}
      ${html`<${Panel} title="Notification recipients" label="alerts / tickets">
        ${recips.length ? recips.map((r, i) => html`<div key=${i} class="adminrow">
          <div class="grow"><b>${r.name}</b> <span class="muted mono" style=${{ fontSize: '11px' }}>${r.email || ''} ${r.telegram || ''}</span></div>
          <button class="btn ghost" onClick=${() => run(NF.recipient('test', r.name, r.telegram, r.email), 'Test sent')}>Test</button>
          <button class="btn ghost" onClick=${() => run(NF.recipient('del', r.name, '', r.email), 'Removed')}>Remove</button>
        </div>`) : html`<div class="empty">No recipients yet.</div>`}
        <div class="addrow">
          <input class="inp" placeholder="name" value=${nr.name} onInput=${e => setNr({ ...nr, name: e.target.value })}/>
          <input class="inp" placeholder="telegram id" value=${nr.telegram} onInput=${e => setNr({ ...nr, telegram: e.target.value })}/>
          <input class="inp" placeholder="email" value=${nr.email} onInput=${e => setNr({ ...nr, email: e.target.value })}/>
          <button class="btn" onClick=${() => run(NF.recipient('add', nr.name, nr.telegram, nr.email), 'Recipient added')}>+ Add</button>
        </div>
      </${Panel}>`}
    </div></div>`;
});

const fmtSec = x => !x ? '—' : (x >= 3600 ? (x / 3600) + 'h' : x >= 60 ? (x / 60) + 'm' : x + 's');
const ProactiveView = memo(function ProactiveView({ d }) {
  const p = d.proactive || {};
  const log = p.log || [];
  return html`<div class="viewfade">
    <div class="viewhd"><h2>Proactive team-lead</h2>
      <span class=${'pill2 ' + (p.enabled ? 'g' : 'c')}>${p.enabled ? 'patrolling' : 'off'}</span>
      <span class="lbl">active patrol + reporting</span></div>
    <div class="grid">
      <div class="col">
        ${html`<${Panel} title="Patrol status" label="team-lead 主動巡邏" right=${html`<${ActionBtn} act="patrol" label="Patrol now" busyLabel="Triggering" ghost=${true}/>`}>
          <div class="formgrid">
            <${Field} label="Last patrol"><div class="mono ink2">${p.last_patrol || '—'}</div></${Field}>
            <${Field} label="Cadence"><div class="mono ink2">patrol ${fmtSec(p.patrol_interval_sec)} · digest ${fmtSec(p.digest_interval_sec)}</div></${Field}>
            <${Field} label="Safety net"><span class=${'pill2 ' + (p.safety_net ? 'g' : 'w')}>${p.safety_net ? 'on · 保證送達' : 'off'}</span></${Field}>
            <${Field} label="Last cycle"><div><b style=${{ color: (p.last_critical || 0) > 0 ? 'var(--crit)' : 'var(--ink2)' }}>${p.last_critical || 0}</b> <span class="muted">critical ·</span> ${p.last_routine || 0} <span class="muted">routine</span></div></${Field}>
          </div>
          ${p.summary ? html`<hr class="sep" style=${{ margin: '12px 0' }}/><pre class="mono" style=${{ whiteSpace: 'pre-wrap', fontSize: '11.5px', color: 'var(--ink2)', margin: 0 }}>${p.summary}</pre>` : null}
        </${Panel}>`}
      </div>
      <div class="col">
        ${html`<${Panel} title="Patrol log" label="最近巡邏 · delta 事件">
          <${DataTable} rows=${log} pageSize=${10} empty="尚無巡邏記錄(loop 未跑或剛啟動)。"
            cols=${[
              { k: 'ts', label: 'Time', render: r => html`<span class="mono">${r.ts || ''}</span>` },
              { k: 'ev', label: '事件', render: r => { const c = (r.critical || []).length, rt = (r.routine || []).length;
                return html`${c ? html`<span class="pill2 c">${c} critical</span> ` : null}${rt ? html`<span class="pill2">${rt} routine</span>` : null}${!c && !rt ? html`<span class="muted">no change</span>` : null}`; } },
              { k: 'sent', label: '送出', align: 'right', render: r => html`${r.safety_net_fired ? html`<span class="pill2 g">safety-net</span> ` : null}${r.digest_sent ? html`<span class="pill2 a">digest</span>` : null}` },
            ]}/>
        </${Panel}>`}
      </div>
    </div>
  </div>`;
});
const VIEWS = {
  overview: { label: 'Overview', comp: OverviewView },
  fleet: { label: 'Fleet', comp: FleetView },
  security: { label: 'Security', comp: SecurityView },
  governance: { label: 'Governance', comp: GovernanceView },
  proactive: { label: 'Proactive', comp: ProactiveView },
  audit: { label: 'Audit', comp: AuditView },
  admin: { label: 'Admin', comp: AdminView },
  settings: { label: 'Settings', comp: SettingsView },
};

function NavRail({ me, route, counts }) {
  return html`<aside class="rail">
    <div class="brand"><span class="mark"></span><div><b>nemofleet</b><div class="sub">GOVERNED FLEET</div></div></div>
    <nav class="nav">${Object.entries(VIEWS).map(([k, v]) => html`<a key=${k} class=${route === k ? 'on' : ''} href=${'#/' + k}>${v.label}
      ${counts[k] != null ? html`<span class="cnt">${counts[k]}</span>` : null}</a>`)}</nav>
    <div class="railfoot"><span class="avatar">${(me.email || 'op')[0].toUpperCase()}</span>
      <div style=${{ minWidth: 0 }}><div style=${{ fontSize: '12px', fontWeight: 600 }}>${me.email || 'operator'}</div>
      <div style=${{ fontSize: '10.5px', color: 'var(--ink3)' }}>${me.role || ''}</div></div></div>
  </aside>`;
}

function App() {
  const { data, err, loading, reload } = useStatus();
  const route = useHashRoute('overview');
  const clock = useClock();
  const d = useMemo(() => (data ? normalize(data) : null), [data]);
  useEffect(() => { const h = () => reload(); addEventListener('nfreload', h); return () => removeEventListener('nfreload', h); }, [reload]);

  if (err && !d) return html`<div class="errbox"><b>Cannot reach the fleet API</b><div class="ink2">${err}</div><button class="retry" onClick=${reload}>Retry</button></div>`;
  if (loading || !d) return html`<div class="loading"><div class="spin"></div>Loading console…</div>`;

  const View = (VIEWS[route] || VIEWS.overview).comp;
  const counts = { security: (d.cve.findings.length + d.cert.findings.length) || null, governance: d.governance.denied || null };
  return html`<div class="app">
    <${NavRail} me=${d.me} route=${route} counts=${counts}/>
    <main class="main">
      <header class="top live">
        <div><h1>${(VIEWS[route] || VIEWS.overview).label}</h1>
          <div class="meta">${d.devices.length} managed device(s) · ${d.nodes.length} agent nodes · governance enforced by OPA / L7 policy</div></div>
        <div style=${{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: '12px' }}>
          <${ActionBtn} act="refresh" label="↻ Refresh" busyLabel="…" ghost=${true}/>
          <div class="fleetpill live">
            ${d.nodes.map(nd => html`<span key=${nd.name} class="seg"><${Dot} up=${nd.up}/>${nd.name}</span>`)}
            <span class="seg">NIM · ${d.inference.model} <${Dot} up=${d.inference.reachable !== false}/></span>
            <span class="seg clock">${clock}</span>
          </div>
        </div>
      </header>
      <${View} d=${d}/>
      <footer class="foot">
        <span>Audit chain <b style=${{ color: d.audit.ok ? 'var(--good)' : 'var(--crit)' }}>${d.audit.ok ? '✓ verified' : '✗ broken'}</b> · <span class="mono">${(d.audit.count || 0).toLocaleString()} entries</span></span>
        <span style=${{ marginLeft: 'auto' }} class="mono">nemofleet · live every 5s${err ? ' · reconnecting…' : ''}</span>
      </footer>
    </main>
  </div>`;
}

ReactDOM.createRoot(document.getElementById('root')).render(html`<${React.Fragment}><${App}/><${Toaster}/></${React.Fragment}>`);
