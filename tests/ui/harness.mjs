// harness.mjs — boot the nemofleet SPA inside jsdom so tests can render real views.
// No build step: loads the same vendored React/htm + api.js normalize + app.js the browser loads.
import { JSDOM } from 'jsdom';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const WEB = join(dirname(fileURLToPath(import.meta.url)), '..', '..', 'services', 'bridge', 'web');
const read = (p) => readFileSync(join(WEB, p), 'utf8');

// A fixed mock fleet state covering the interesting cases (device OFFLINE, 4 nodes, findings…).
export const MOCK = {
  me: { email: 'tony@asus.com', role: 'admin' },
  nodes: [
    { name: 'team-lead', role: 'Front desk', tag: 'lead', port: 8642, up: true, zone: '' },
    { name: 'worker-a', role: 'ops', tag: 'ops', port: 18791, up: true, zone: 'zone A', caps: ['monitor', 'fix', 'cert'] },
    { name: 'worker-b', role: 'sec', tag: 'sec', port: 18792, up: true, zone: 'zone B', caps: ['cve', 'nuclei'] },
    { name: 'worker-c', role: 'gov', tag: 'gov', port: 18793, up: true, zone: 'zone C', caps: ['review', 'backup', 'curate'] },
  ],
  devices: [{ asset: 'lab-asus-ebg19p-01', model: 'EBG19P', online: false, cpu: null, mem: null, temp: null, firmware: null }],
  containers: [{ name: 'openshell-worker-a-2b91', state: 'up 6d', image: 'openshell/sandbox:2026.4' }],
  governance: { allowed: 1240, denied: 3, benign: 418, coverage: 99.8, series_allowed: [1, 2, 3, 4, 5], events: [{ ts: '14:22', target: 'api.telegram.org:443', policy: 'telegram', verdict: 'allowed' }] },
  cve: { critical: 1, serious: 2, counts: { critical: 1, affected: 84 }, findings: [{ cve: 'CVE-2024-6119', component: 'openssl', asset: 'ebg19p', severity: 'critical' }] },
  cert: { high: 0, counts: {}, findings: [] },
  source: { sbom: 142, sast: 6, sbom_source: 'RMerl/asuswrt-merlin.ng@92e9b31110', sbom_list: [{ name: 'openssl', version: '3.0.12' }, { name: 'dropbear', version: '2022.83' }], sast_source: 'RMerl/asuswrt-merlin.ng@92e9b31110', cve_reconciled: 7,
    // real backend shape — remediation is an OBJECT (a raw-object render here once black-screened the app)
    sast_list: [{ cwe: 'CWE-798 hardcoded-credential', file: 'real/001_netcfg.c', upstream_path: 'release/src/router/rc/common.c', line: 6,
      code: 'static const char *ADMIN_PASSWORD = "x";', patch: '--- a/x.c\n+++ b/x.c\n@@ -4,1 +4,1 @@\n-bad\n+good', patch_verified: true, violates_design: 'REQ-SEC-05', url: 'https://github.com/RMerl/asuswrt-merlin.ng/blob/b8c473/release/src/router/rc/common.c#L6',
      remediation: { risk: 'hardcoded key is extractable from firmware', fix: 'load from secrets, not source', ref: 'https://cwe.mitre.org/data/definitions/798.html' } }] },
  events: [],
  jira: { tickets: [{ id: 'NETOPS-1', summary: 'x', kind: 'cve', asset: 'ebg19p', priority: 'High' }] },
  audit_recent: [{ ts: '2026-07-03 14:20', actor: 'tony@asus.com', action: 'login', detail: 'ok', ok: true }],
  _audit: { chain: { ok: true, count: 1204 }, recent: [] },
  snapshots_by_agent: [{ label: 'worker-a', sb: 'worker-a', items: [{ ver: 'v1', name: 'baseline', ts: '2026-07-03T14-02-33-771Z' }] }],
  inference: { model: 'nemotron-super', provider: 'vllm-local', reachable: true, endpoint: 'inference.local/v1' },
  proactive_enabled: true, patrol: { enabled: true }, patrol_log: [],
  governance_c: { up: true, reviews: [], backups: [], backup_count: 0, firmware: {}, skills_count: 0, curations: [] },
  settings: {}, flow: [],
};

// Boot a fresh App in jsdom at a given route + language; returns { window, root, text }.
export async function mount({ route = 'overview', lang = 'en', theme = 'dark', close = true } = {}) {
  const dom = new JSDOM('<!doctype html><html><head></head><body><div id="root"></div></body></html>',
    { url: 'https://localhost/app#/' + route, pretendToBeVisual: true, runScripts: 'dangerously' });
  const { window } = dom;
  window.localStorage.setItem('nf-lang', lang);
  window.localStorage.setItem('nf-theme', theme);
  window.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} });
  window.requestAnimationFrame = (f) => setTimeout(f, 0);
  window.cancelAnimationFrame = () => {};
  // stub canvas so Chart.js code paths don't explode
  window.HTMLCanvasElement.prototype.getContext = () => ({ createLinearGradient: () => ({ addColorStop() {} }) });

  // Run each script in the window's own global scope (document/window defined). UMD → browser branch → window.React etc.
  const run = (src) => window.eval(src);
  run(read('vendor/react.production.min.js'));
  run(read('vendor/react-dom.production.min.js'));
  run(read('vendor/htm.umd.js'));
  window.Chart = function () { this.destroy = () => {}; this.update = () => {}; this.data = { datasets: [{}] }; };

  const apiSrc = read('api.js');
  const normalize = apiSrc.slice(apiSrc.indexOf('function normalize'));
  const nf = `var NF = { status:()=>Promise.resolve(${JSON.stringify(MOCK)}),
    subscribe:(onData,onErr,iv)=>{ onData(${JSON.stringify(MOCK)}); return ()=>{}; },
    section:(n,p,s)=>Promise.resolve({rows:[],total:0,page:0,size:s||20}),
    policyRo:(sb)=>Promise.resolve({ok:true,policy:{sandbox:sb,version:'4',hash:'abc',networks:[{name:'telegram',eps:['api.telegram.org:443'],nbin:2,l7:true}]},sandboxes:['team-lead','worker-a','worker-b','worker-c']}),
    action:()=>Promise.resolve({ok:true}), sys:()=>Promise.resolve({ok:true,out:''}), config:()=>Promise.resolve({ok:true}),
    certPolicy:()=>Promise.resolve({ok:true}), recipient:()=>Promise.resolve({ok:true}), users:()=>Promise.resolve({ok:true}),
    authConfig:()=>Promise.resolve({ok:true}), snapshot:()=>Promise.resolve({ok:true}), policy:()=>Promise.resolve({ok:true}),
    deviceAction:()=>Promise.resolve({ok:true}) };
    function poll(cb){ NF.status().then(cb); return ()=>{}; }`;
  run(nf);
  run(normalize);
  run(read('app.js'));

  // Let effects + the status promise flush, then snapshot and tear down (jsdom timers must not keep node alive).
  await new Promise((r) => setTimeout(r, 80));
  const rootEl = window.document.getElementById('root');
  if (!close) {
    // live mode: caller drives interaction (e.g. click a row → drawer) then calls cleanup()
    return { window, root: rootEl, text: () => rootEl.textContent || '', cleanup: () => { try { window.close(); } catch { /* ignore */ } } };
  }
  const textStr = rootEl.textContent || '';
  const htmlStr = rootEl.innerHTML || '';
  try { window.close(); } catch { /* ignore */ }
  return { text: () => textStr, html: htmlStr };
}

export const VIEWS = ['overview', 'architecture', 'flow', 'fleet', 'security', 'governance', 'changectrl', 'audit', 'proactive', 'admin', 'settings'];
