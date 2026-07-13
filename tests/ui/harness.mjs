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
  _me: { email: 'tony@asus.com', role: 'admin' },   // normalize() reads d._me → d.me (collect() emits _me)
  frozen: { frozen: false, by: '', ts: '' },
  // role/role_en deliberately mirror the REAL backend shape (worker-itops.py's ZONE_ROLE is
  // Chinese-only; agent-dashboard.py adds the role_en sibling) — a mock that pre-translates this
  // to English, like an earlier version of this file did, can't catch a missing/broken _en sibling
  // because there's no Chinese left to leak. That's exactly how the live "worker role still shows
  // Chinese in EN mode" bug got past this suite.
  nodes: [
    { name: 'team-lead', role: 'Front desk · Telegram / Email intake', tag: 'lead', port: 8642, up: true, zone: '' },
    { name: 'worker-a', role: 'IT 運維 / 網路管理', role_en: 'IT ops / network management', tag: 'ops', port: 18791, up: true, zone: 'zone A', caps: ['monitor', 'fix', 'cert'] },
    { name: 'worker-b', role: '資安 / 原始碼分析', role_en: 'security / source analysis', tag: 'sec', port: 18792, up: true, zone: 'zone B', caps: ['cve', 'nuclei'] },
    { name: 'worker-c', role: '變更治理 / QA 監督', role_en: 'change governance / QA oversight', tag: 'gov', port: 18793, up: true, zone: 'zone C', caps: ['review', 'backup', 'curate'] },
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
  // real key is d.proactive (see api.js `proactive: d.proactive || null`) — summary/summary_en
  // mirrors teamlead-proactive.sh's real bilingual output; a mock with no Chinese here can't catch
  // the "proactive page shows a raw Chinese sentence in EN mode" bug (that's how it shipped).
  proactive: { enabled: true, patrol_interval_sec: 1200, digest_interval_sec: 3600, safety_net: true,
    last_patrol: '2026-07-10 09:30:01', last_critical: 0, last_warning: 0, last_routine: 0, snooze_until: 0,
    summary: '機隊 1 台;開單 0;CVE affected 84;憑證高風險 0\n- lab-asus-ebg19p-01: offline',
    summary_en: 'Fleet: 1 device(s); open tickets 0; CVE affected 84; cert high-risk 0\n- lab-asus-ebg19p-01: offline',
    log: [] },
  governance_c: { up: true, reviews: [], backups: [], backup_count: 0, firmware: {}, skills_count: 0, curations: [] },
  settings: {}, flow: [],
  eval: { history: [
      { ts: '2026-07-10 03:54:29', npass: 8, n: 11, by_category: { general: { pass: 4, n: 5 }, security: { pass: 1, n: 2 }, ops: { pass: 1, n: 2 }, governance: { pass: 2, n: 2 } }, recovered: 0, lessons_active: 2 },
      { ts: '2026-07-10 04:24:17', npass: 9, n: 11, by_category: { general: { pass: 4, n: 5 }, security: { pass: 1, n: 2 }, ops: { pass: 2, n: 2 }, governance: { pass: 2, n: 2 } }, recovered: 2, lessons_active: 1 },
    ], latest: { ts: '2026-07-10 04:24:17', npass: 9, n: 11, by_category: { general: { pass: 4, n: 5 }, security: { pass: 1, n: 2 }, ops: { pass: 2, n: 2 }, governance: { pass: 2, n: 2 } }, recovered: 2, lessons_active: 1 } },
};

// Wait for React's async render (effects + the NF.status()/subscribe() promise) to actually
// settle, instead of guessing a fixed delay. A fixed setTimeout(80) here used to be the source of
// this suite's flakiness: under load (parallel test workers, a loaded CI runner) 80ms isn't always
// enough, and WHICH view is still mid-render when the snapshot is taken varies run to run — that's
// exactly why a different test failed each time rather than the same one every time. Poll instead:
// keep checking rootEl's rendered text, and only stop once it's read back identical on two
// consecutive polls (i.e. nothing changed the DOM between them) — fast when the app settles
// quickly (most views: 1-2 polls, ~20-40ms), with real headroom (up to maxWait) when it doesn't.
async function settle(rootEl, { maxWait = 2000, interval = 20, stableChecks = 2 } = {}) {
  let prev = null, stable = 0;
  const start = Date.now();
  while (Date.now() - start < maxWait) {
    await new Promise((r) => setTimeout(r, interval));
    const cur = rootEl.textContent || '';
    if (cur.length > 0 && cur === prev) {
      if (++stable >= stableChecks) return;
    } else {
      stable = 0;
    }
    prev = cur;
  }
}

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
  // normalize() calls the module-scoped _localize() (hoisted out so /api/action's {msg} can reuse
  // it too) — slice from _localize, not normalize, or this silently drops it and every view blanks.
  const normalize = apiSrc.slice(apiSrc.indexOf('function _localize'));
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
  const rootEl = window.document.getElementById('root');
  await settle(rootEl);
  if (!close) {
    // live mode: caller drives interaction (e.g. click a row → drawer) then calls cleanup()
    return { window, root: rootEl, text: () => rootEl.textContent || '', cleanup: () => { try { window.close(); } catch { /* ignore */ } } };
  }
  const textStr = rootEl.textContent || '';
  const htmlStr = rootEl.innerHTML || '';
  try { window.close(); } catch { /* ignore */ }
  return { text: () => textStr, html: htmlStr };
}

// Derived from app.js's own `const VIEWS = { key: {...}, ... }` rather than hand-maintained here —
// a hardcoded duplicate list is exactly how the 'scorecard' view shipped invisible to every i18n/
// render check in this suite (added to app.js, never added to a second list nobody remembered).
const _appSrc = read('app.js');
const _viewsBlock = _appSrc.slice(_appSrc.indexOf('const VIEWS = {'), _appSrc.indexOf('const NAV_GROUPS'));
export const VIEWS = [..._viewsBlock.matchAll(/^\s*(\w+):\s*\{ label:/gm)].map((m) => m[1]);
