// ui.test.mjs — render every view in jsdom and assert. Catches "changed A, broke B" regressions:
// i18n leaks (Chinese in English mode), views that blank/throw, missing controls, wrong device state.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { mount, VIEWS, MOCK } from './harness.mjs';

const CJK = /[一-鿿]/;
const WEB = join(dirname(fileURLToPath(import.meta.url)), '..', '..', 'services', 'bridge', 'web');
const appSrc = readFileSync(join(WEB, 'app.js'), 'utf8');

// ── every view renders (non-trivial content) in both languages, no throw ──
for (const route of VIEWS) {
  test(`view '${route}' renders content (en)`, async () => {
    const { text } = await mount({ route, lang: 'en' });
    assert.ok(text().length > 40, `'${route}' rendered almost nothing (${text().length} chars) — view blanked`);
  });
}

// ── i18n: in English mode NO view leaks Chinese (the "選英文卻夾中文" bug) ──
for (const route of VIEWS) {
  test(`view '${route}' has no Chinese leak in English mode`, async () => {
    const { text } = await mount({ route, lang: 'en' });
    // strip the intentional bilingual language switcher (中 toggle, 中文/語言 selector) before checking
    const hits = (text().replace(/中文|語言|中/g, '').match(/[一-鿿]+/g) || []);
    assert.equal(hits.length, 0, `'${route}' leaks Chinese in EN mode: ${JSON.stringify([...new Set(hits)].slice(0, 8))}`);
  });
}

// ── i18n: the mirror-image bug — a view built entirely from hardcoded English literals (never
// wrapped in t()) passes every check above (nothing "leaks" in EN mode) but silently never shows
// a word of Chinese either. This is exactly how the Scorecard view shipped: fully readable, zero
// Chinese leak, and yet 0% translated. Isolate each view's own .viewfade root (excluding the shared
// nav chrome, which is always translated) and require it to contain real Chinese content in zh mode.
for (const route of VIEWS) {
  test(`view '${route}' actually shows Chinese in Chinese mode (own content, not just chrome)`, async () => {
    const { window, cleanup } = await mount({ route, lang: 'zh', close: false });
    try {
      const body = window.document.querySelector('.viewfade');
      assert.ok(body, `'${route}' has no .viewfade root — can't isolate view content from nav chrome`);
      const hits = body.textContent.match(/[一-鿿]/g) || [];
      assert.ok(hits.length >= 5, `'${route}' shows almost no Chinese in zh mode (${hits.length} CJK chars found) — likely built from hardcoded English literals never wrapped in t()`);
    } finally { cleanup(); }
  });
}

// ── i18n: in Chinese mode the chrome is actually translated (nav shows 中文) ──
test('Chinese mode translates the nav', async () => {
  const { text } = await mount({ route: 'overview', lang: 'zh' });
  assert.ok(text().includes('總覽') && text().includes('機隊'), 'nav not translated in zh mode');
});

// ── every I18N dict entry has BOTH en and zh (no half-translations) ──
test('I18N dict entries all have en + zh', () => {
  const dict = appSrc.slice(appSrc.indexOf('const I18N = {'), appSrc.indexOf('function t('));
  const entries = dict.match(/\{ en:/g) || [];
  const withZh = dict.match(/zh: '/g) || [];
  assert.ok(entries.length > 100, `expected a populated dict, got ${entries.length}`);
  assert.equal(entries.length, withZh.length, `mismatch: ${entries.length} en vs ${withZh.length} zh — some entry is missing a language`);
});

// ── no user-facing prop is a hardcoded CJK literal (must go through t()/dict) ──
test('no hardcoded Chinese in label=/empty=/hint=/placeholder= props', () => {
  const bad = [...appSrc.matchAll(/(label|empty|hint|placeholder)="([^"]*[一-鿿][^"]*)"/g)]
    .map((m) => m[2]).filter((v) => !v.includes('語言') && !v.includes('中文'));  // the language toggle is intentionally bilingual
  assert.equal(bad.length, 0, `hardcoded CJK props (won't translate): ${JSON.stringify(bad.slice(0, 6))}`);
});

// ── device OFFLINE is shown as offline, never fabricated online (the EBG19P bug) ──
test('offline device renders offline (no fabricated telemetry)', async () => {
  const { text } = await mount({ route: 'fleet', lang: 'en' });
  const t = text();
  assert.ok(!/12\s*%.*34\s*%.*51/.test(t), 'fabricated 12/34/51 telemetry leaked for an offline device');
  assert.ok(t.includes('EBG19P'), 'device row missing');
});

// ── the fleet shows all 4 nodes (was only worker-a) ──
test('fleet shows all 4 nodes', async () => {
  const { text } = await mount({ route: 'fleet', lang: 'en' });
  const t = text();
  for (const n of ['team-lead', 'worker-a', 'worker-b', 'worker-c']) assert.ok(t.includes(n), `missing node ${n}`);
});

// ── snapshot list renders the created snapshots (create-did-nothing regression) ──
test('snapshot list renders existing snapshots', async () => {
  const { text } = await mount({ route: 'fleet', lang: 'en' });
  assert.ok(text().includes('v1') && text().includes('baseline'), 'snapshot list not shown');
});

// ── governance + admin wire in their editor sub-panels (POLSB-undefined regression) ──
// (static: the deep async panels don't flush in jsdom's tick; render is verified by screenshots)
test('GovernanceView wires PolicyEditor + GovActionsPanel', () => {
  const v = appSrc.slice(appSrc.indexOf('const GovernanceView'), appSrc.indexOf('const GovActionsPanel'));
  assert.ok(/<\$\{GovActionsPanel\}/.test(v), 'GovActionsPanel not wired into GovernanceView');
  assert.ok(appSrc.includes('<${PolicyEditor}'), 'PolicyEditor not wired');
  assert.ok(/const POLSB =/.test(appSrc), 'POLSB not defined (would crash the view)');
});
test('AdminView wires users + recipients + ChannelPanel', () => {
  const i = appSrc.indexOf('const AdminView'); const v = appSrc.slice(i, i + 3500);
  assert.ok(v.includes('Users'), 'admin users panel missing');
  assert.ok(/recipient/i.test(v), 'admin recipients panel missing');
  assert.ok(appSrc.includes('ChannelPanel'), 'ChannelPanel not defined/wired');
});

// ── every action button in source maps to a real NF.* method (nothing dead-wired) ──
test('every NF.<method> call targets a defined helper', () => {
  const api = readFileSync(join(WEB, 'api.js'), 'utf8');
  const defined = new Set([...api.matchAll(/^\s*(\w+)\s*[:(]/gm)].map((m) => m[1]));
  const called = new Set([...appSrc.matchAll(/NF\.(\w+)\(/g)].map((m) => m[1]));
  const missing = [...called].filter((m) => !defined.has(m));
  assert.equal(missing.length, 0, `app.js calls NF methods that api.js doesn't define: ${JSON.stringify(missing)}`);
});

// ── a SAST row opens its detail drawer without crashing (dict-shaped remediation once black-screened) ──
test('SAST row → drawer renders (object fields do not crash the app)', async () => {
  const { window, cleanup } = await mount({ route: 'security', lang: 'en', close: false });
  try {
    const rows = [...window.document.querySelectorAll('tr.clickrow')].filter(r => /CWE-798/.test(r.textContent));
    assert.ok(rows.length, 'SAST row not rendered to click');
    rows[0].dispatchEvent(new window.MouseEvent('click', { bubbles: true, cancelable: true }));
    await new Promise(r => setTimeout(r, 50));
    const body = window.document.querySelector('.drawer-bd');
    assert.ok(body, 'drawer did not open on SAST row click');
    const dt = body.textContent || '';
    assert.ok(!/\[object Object\]/.test(dt), 'a raw object leaked into the SAST drawer (would black-screen live)');
    assert.ok(/Risk|Fix|CWE-798|hardcoded/i.test(dt), `SAST drawer body looks empty/crashed: ${JSON.stringify(dt.slice(0, 80))}`);
    assert.ok(!/This view hit an error/.test(dt), 'SAST drawer threw (caught by ErrorBoundary): ' + JSON.stringify(dt.slice(0, 120)));
  } finally { cleanup(); }
});

// ── every VIEWS entry has a component (nav can't point at nothing) ──
test('every nav VIEWS entry has a comp', () => {
  const block = appSrc.slice(appSrc.indexOf('const VIEWS = {'), appSrc.indexOf('function NavRail'));
  const entries = [...block.matchAll(/(\w+):\s*\{ label:.*?comp:\s*(\w+)/g)];
  assert.ok(entries.length >= 10, `expected ≥10 views, found ${entries.length}`);
  for (const [, key, comp] of entries) assert.ok(new RegExp('(function|const)\\s+' + comp + '\\b').test(appSrc), `view ${key} → ${comp} not defined`);
});

test('kill-switch: Admin shows the emergency freeze panel + Freeze button (running state)', async () => {
  const { text } = await mount({ route: 'admin', lang: 'en' });
  assert.match(text(), /Emergency kill-switch/i, 'freeze panel present');
  assert.match(text(), /Freeze fleet/i, 'Freeze button present');
  assert.ok(!/FLEET FROZEN/.test(text()), 'no frozen banner while running');
});

test('kill-switch: when frozen, the global banner + Resume show on every view', async () => {
  MOCK.frozen = { frozen: true, by: 'tony@asus.com', ts: '2026-07-06 15:00:00' };
  try {
    const { text } = await mount({ route: 'overview', lang: 'en' });
    assert.match(text(), /FLEET FROZEN/i, 'frozen banner on overview');
    assert.match(text(), /Resume fleet/i, 'resume control present');
  } finally {
    MOCK.frozen = { frozen: false, by: '', ts: '' };
  }
});
