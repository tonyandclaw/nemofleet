// app.js — nemofleet console (React + Chart.js, no build step; htm for views).
// Multi-view SPA architected for scale: change-detection polling, memoized panels,
// data-driven fleet/device rendering, paginated tables. Data via /api/status → normalize().
const { useState, useEffect, useRef, useMemo, memo, useCallback } = React;
const html = htm.bind(React.createElement);
const SERIES = { allowed: '#3987e5', denied: '#e66767' };

// ── toasts + backend actions (decoupled via CustomEvents so any button can fire them) ────────
function toast(msg, kind = 'i') { dispatchEvent(new CustomEvent('nftoast', { detail: { msg, kind, id: Date.now() + Math.random() } })); }
function reloadNow() { dispatchEvent(new CustomEvent('nfreload')); }
function openDrawer(detail) { dispatchEvent(new CustomEvent('nfdrawer', { detail })); }
function fmtVal(v) { if (v == null || v === '') return '—'; if (Array.isArray(v)) return v.length ? v.map(fmtVal).join(', ') : '—'; if (typeof v === 'object') return JSON.stringify(v); return String(v); }
function rowDrawer(title, row) { openDrawer({ title, rows: Object.entries(row).filter(([k]) => k[0] !== '_').map(([k, v]) => ({ k, v: fmtVal(v), mono: true })) }); }
let THEME = localStorage.getItem('nf-theme') || 'dark';
let LANG = localStorage.getItem('nf-lang') || 'zh';
let DENSITY = localStorage.getItem('nf-density') || 'cozy';
function applyUI() { const e = document.documentElement; e.setAttribute('data-theme', THEME); e.setAttribute('data-density', DENSITY); }
function setTheme(x) { THEME = x; localStorage.setItem('nf-theme', x); applyUI(); dispatchEvent(new CustomEvent('nfui')); }
function setDensity(x) { DENSITY = x; localStorage.setItem('nf-density', x); applyUI(); dispatchEvent(new CustomEvent('nfui')); }
const I18N = {
  'Overview': { en: 'Overview', zh: '總覽' }, 'Flow': { en: 'Flow', zh: '工作流' }, 'Fleet': { en: 'Fleet', zh: '機隊' },
  'Security': { en: 'Security', zh: '資安' }, 'Governance': { en: 'Governance', zh: '治理' }, 'Proactive': { en: 'Proactive', zh: '主動' },
  'Change ctrl': { en: 'Change ctrl', zh: '變更治理' }, 'Audit': { en: 'Audit', zh: '稽核' }, 'Admin': { en: 'Admin', zh: '管理' }, 'Settings': { en: 'Settings', zh: '設定' },
  '↻ Refresh': { en: '↻ Refresh', zh: '↻ 重新整理' }, 'Retry': { en: 'Retry', zh: '重試' },
  'Loading console…': { en: 'Loading console…', zh: '載入主控台…' }, 'Cannot reach the fleet API': { en: 'Cannot reach the fleet API', zh: '無法連上機隊 API' },
  'Rescan': { en: 'Rescan', zh: '重掃' }, 'Scan now': { en: 'Scan now', zh: '立即掃描' }, 'Re-run': { en: 'Re-run', zh: '重跑' }, 'Backup now': { en: 'Backup now', zh: '立即備份' },
  'Restore': { en: 'Restore', zh: '還原' }, 'Delete': { en: 'Delete', zh: '刪除' }, 'Apply': { en: 'Apply', zh: '套用' }, 'rebuild': { en: 'rebuild', zh: '重建' },
  'Test': { en: 'Test', zh: '測試' }, 'Remove': { en: 'Remove', zh: '移除' }, '+ Add': { en: '+ Add', zh: '＋新增' }, '+ Create snapshot': { en: '+ Create snapshot', zh: '＋建立快照' },
  'EBG19P security posture': { en: 'EBG19P security posture', zh: 'EBG19P 安全姿態' }, 'CVE findings': { en: 'CVE findings', zh: 'CVE 弱點' },
  'Active scan (nuclei)': { en: 'Active scan (nuclei)', zh: '主動掃描 (nuclei)' }, 'Certificates / weak crypto': { en: 'Certificates / weak crypto', zh: '憑證 / 弱加密' },
  'SAST findings': { en: 'SAST findings', zh: 'SAST 原始碼弱點' }, 'Cipher policy override': { en: 'Cipher policy override', zh: '加密套件政策覆寫' },
  'Snapshots': { en: 'Snapshots', zh: '快照' }, 'Containers': { en: 'Containers', zh: '容器' }, 'Diagnostics': { en: 'Diagnostics', zh: '診斷' },
  'Inference': { en: 'Inference', zh: '推理' }, 'Device ops · EBG19P': { en: 'Device ops · EBG19P', zh: '設備運維 · EBG19P' },
  'Users & access': { en: 'Users & access', zh: '使用者與權限' }, 'Notification recipients': { en: 'Notification recipients', zh: '通知收件人' },
  'Scan schedule': { en: 'Scan schedule', zh: '掃描排程' }, 'Certificate & crypto thresholds': { en: 'Certificate & crypto thresholds', zh: '憑證與加密門檻' },
  'Device health thresholds': { en: 'Device health thresholds', zh: '設備健康門檻' }, 'Escalation & notifications': { en: 'Escalation & notifications', zh: '升級與通知' },
  'Proactive team-lead': { en: 'Proactive team-lead', zh: '主動 team-lead' }, 'Quiet hours & scan tags': { en: 'Quiet hours & scan tags', zh: '靜音時段與掃描標籤' },
  'Review gate': { en: 'Review gate', zh: '審查閘' }, 'Config backups': { en: 'Config backups', zh: '設定備份' }, 'Firmware': { en: 'Firmware', zh: '韌體' },
  'Skills · curator (SkillOS)': { en: 'Skills · curator (SkillOS)', zh: '技能庫 · curator (SkillOS)' }, 'Change control': { en: 'Change control', zh: '變更治理' },
  'Sandbox': { en: 'Sandbox', zh: '沙箱' }, 'Target': { en: 'Target', zh: '目標' }, 'Detail': { en: 'Detail', zh: '詳情' }, 'Details': { en: 'Details', zh: '詳情' },
  'No data.': { en: 'No data.', zh: '無資料。' }, 'Auto-open Jira': { en: 'Auto-open Jira', zh: '自動開 Jira' }, 'Notify channels': { en: 'Notify channels', zh: '通知管道' },
  'Time': { en: 'Time', zh: '時間' },
  'Policy': { en: 'Policy', zh: '政策' },
  'Verdict': { en: 'Verdict', zh: '判決' },
  'Component': { en: 'Component', zh: '元件' },
  'Asset': { en: 'Asset', zh: '資產' },
  'Severity': { en: 'Severity', zh: '嚴重度' },
  'Sev': { en: 'Sev', zh: '級別' },
  'Service': { en: 'Service', zh: '服務' },
  'Issue': { en: 'Issue', zh: '問題' },
  'File': { en: 'File', zh: '檔案' },
  'Line': { en: 'Line', zh: '行號' },
  'Finding': { en: 'Finding', zh: '發現項' },
  'Name': { en: 'Name', zh: '名稱' },
  'State': { en: 'State', zh: '狀態' },
  'Status': { en: 'Status', zh: '狀態' },
  'Image': { en: 'Image', zh: '映像' },
  'Op': { en: 'Op', zh: '操作' },
  'Category': { en: 'Category', zh: '分類' },
  'Event': { en: 'Event', zh: '事件' },
  'Task': { en: 'Task', zh: '任務' },
  'Handoff': { en: 'Handoff', zh: '交接' },
  'Subject': { en: 'Subject', zh: '主體' },
  'Matched': { en: 'Matched', zh: '匹配於' },
  'Backup snapshot': { en: 'Backup snapshot', zh: '備份快照' },
  'Allowed': { en: 'Allowed', zh: '放行' },
  'Denied': { en: 'Denied', zh: '拒絕' },
  'Role': { en: 'Role', zh: '角色' },
  'Appearance': { en: 'Appearance', zh: '外觀' },
  'Light': { en: 'Light', zh: '亮' },
  'Dark': { en: 'Dark', zh: '暗' },
  'Compact': { en: 'Compact', zh: '緊湊' },
  'Cozy': { en: 'Cozy', zh: '適中' },
  'Spacious': { en: 'Spacious', zh: '寬鬆' },
  'Theme': { en: 'Theme', zh: '主題' },
  'Density': { en: 'Density', zh: '密度' },
  'Node detail': { en: 'Node detail', zh: '節點詳情' },
  'Device detail': { en: 'Device detail', zh: '設備詳情' },
  'Policy editor': { en: 'Policy editor', zh: '政策編輯器' },
  'Messaging channels': { en: 'Messaging channels', zh: '訊息管道' },
  'writes to the live backend': { en: 'writes to the live backend', zh: '即時寫入後端' },
  'Governance coverage': { en: 'Governance coverage', zh: '治理覆蓋率' },
  'Blocked egress (DENIED)': { en: 'Blocked egress (DENIED)', zh: '封鎖出向(DENIED)' },
  'Active alerts': { en: 'Active alerts', zh: '作用中告警' },
  'Open escalations': { en: 'Open escalations', zh: '待處理升級' },
  'unauthorized host · OPA host-layer': { en: 'unauthorized host · OPA host-layer', zh: '未授權主機 · OPA 主機層' },
  'human-in-the-loop · NETOPS': { en: 'human-in-the-loop · NETOPS', zh: '人在迴路 · NETOPS' },
  'none': { en: 'none', zh: '無' },
  'OPA / L7 · OCSF events': { en: 'OPA / L7 · OCSF events', zh: 'OPA / L7 · OCSF 事件' },
  'users · notifications': { en: 'users · notifications', zh: '使用者 · 通知' },
  'worker-b · CVE / nuclei / cert / source': { en: 'worker-b · CVE / nuclei / cert / source', zh: 'worker-b · CVE / nuclei / 憑證 / 原始碼' },
  'fleet scan': { en: 'fleet scan', zh: '機隊掃描' },
  'OCSF · 2h': { en: 'OCSF · 2h', zh: 'OCSF · 2 小時' },
  'engine · policy · verdict': { en: 'engine · policy · verdict', zh: '引擎 · 政策 · 判決' },
  'allowed · 2h': { en: 'allowed · 2h', zh: '放行 · 2 小時' },
  'hash-chained': { en: 'hash-chained', zh: '雜湊鏈接' },
  'Jira · human-in-the-loop': { en: 'Jira · human-in-the-loop', zh: 'Jira · 人在迴路' },
  'EBG19P syslog · classified': { en: 'EBG19P syslog · classified', zh: 'EBG19P syslog · 已分類' },
  'OpenShell sandboxes': { en: 'OpenShell sandboxes', zh: 'OpenShell 沙箱' },
  'on-demand · nemoclaw/openshell': { en: 'on-demand · nemoclaw/openshell', zh: '隨需 · nemoclaw / openshell' },
  'per sandbox · recovery points': { en: 'per sandbox · recovery points', zh: '每沙箱 · 還原點' },
  'OpenShell egress · per sandbox': { en: 'OpenShell egress · per sandbox', zh: 'OpenShell 出向 · 每沙箱' },
  'start / stop per sandbox': { en: 'start / stop per sandbox', zh: '每沙箱啟停' },
  'alerts / tickets': { en: 'alerts / tickets', zh: '告警 / 工單' },
  'RBAC': { en: 'RBAC', zh: '權限控管' },
  'worker cadence': { en: 'worker cadence', zh: 'worker 掃描頻率' },
  'what counts as weak': { en: 'what counts as weak', zh: '何謂弱加密' },
  'alert when exceeded': { en: 'alert when exceeded', zh: '超過即告警' },
  'where alerts go': { en: 'where alerts go', zh: '告警去向' },
  'active patrol + reporting': { en: 'active patrol + reporting', zh: '主動巡邏 + 回報' },
  'Allowed governance events over time': { en: 'Allowed governance events over time', zh: '放行治理事件隨時間' },
  'known-good 版本': { en: 'known-good versions', zh: '已知良好版本' },
  '生命週期 · urgency 由 CVE 驅動': { en: 'lifecycle · urgency driven by CVEs', zh: '生命週期 · urgency 由 CVE 驅動' },
  'No affected CVEs — or scan pending.': { en: 'No affected CVEs — or scan pending.', zh: '無受影響 CVE — 或掃描待執行。' },
  'No audit entries.': { en: 'No audit entries.', zh: '無稽核紀錄。' },
  'No cert/crypto issues.': { en: 'No cert/crypto issues.', zh: '無憑證 / 加密問題。' },
  'No container telemetry.': { en: 'No container telemetry.', zh: '無容器遙測。' },
  'No governance events in window.': { en: 'No governance events in window.', zh: '視窗內無治理事件。' },
  'No nuclei hits — or scan pending.': { en: 'No nuclei hits — or scan pending.', zh: '無 nuclei 命中 — 或掃描待執行。' },
  'No recent events — worker-a syslog sync idle.': { en: 'No recent events — worker-a syslog sync idle.', zh: '無近期事件 — worker-a syslog 閒置。' },
  'No SAST hits.': { en: 'No SAST hits.', zh: '無 SAST 命中。' },
  'off = dashboard only': { en: 'off = dashboard only', zh: '關 = 只在儀表板' },
  'Jira is always kept': { en: 'Jira is always kept', zh: '一律保留 Jira' },
  'grp_monitor': { en: 'MONITOR', zh: '監控' },
  'grp_govern': { en: 'GOVERN', zh: '治理' },
  'grp_system': { en: 'SYSTEM', zh: '系統' },
  'managed devices': { en: 'managed devices', zh: '受管設備' },
  'agent nodes': { en: 'agent nodes', zh: 'agent 節點' },
  'OPA / L7 governed': { en: 'governance enforced by OPA / L7', zh: 'OPA / L7 治理中' },
  'Audit chain': { en: 'Audit chain', zh: '稽核鏈' },
  '✓ verified': { en: '✓ verified', zh: '✓ 已驗證' },
  '✗ broken': { en: '✗ broken', zh: '✗ 已損毀' },
  'entries': { en: 'entries', zh: '筆' },
  'live every 5s': { en: 'live every 5s', zh: '每 5 秒更新' },
  'reconnecting…': { en: 'reconnecting…', zh: '重新連線中…' },
  'actions · 2h window': { en: 'actions · 2h window', zh: '動作 · 2 小時' },
  'Allowed volume': { en: 'Allowed volume', zh: '放行量' },
  'Denied (real)': { en: 'Denied (real)', zh: '拒絕(實際)' },
  'Heartbeats · excluded': { en: 'Heartbeats · excluded', zh: '心跳 · 排除' },
  'Heartbeats': { en: 'Heartbeats', zh: '心跳' },
  'Hermes harness': { en: 'Hermes harness', zh: 'Hermes 節點' },
  'lead': { en: 'lead', zh: '主控' },
  'ops': { en: 'ops', zh: '運維' },
  'sec': { en: 'sec', zh: '資安' },
  'gov': { en: 'gov', zh: '治理' },
  'Critical': { en: 'Critical', zh: '嚴重' },
  'Serious': { en: 'Serious', zh: '高風險' },
  'Weak crypto': { en: 'Weak crypto', zh: '弱加密' },
  'Reconciled': { en: 'Reconciled', zh: '已核銷' },
  'Governance events': { en: 'Governance events', zh: '治理事件' },
  'Agent fleet': { en: 'Agent fleet', zh: 'Agent 機隊' },
  'Recent device events': { en: 'Recent device events', zh: '近期設備事件' },
  'Security posture': { en: 'Security posture', zh: '安全姿態' },
  'Managed device': { en: 'Managed device', zh: '受管設備' },
  'worker-b · daily scan': { en: 'worker-b · daily scan', zh: 'worker-b · 每日掃描' },
  'Event volume': { en: 'Event volume', zh: '事件量' },
  'Recent governed actions': { en: 'Recent governed actions', zh: '近期受治理動作' },
  'This view hit an error': { en: 'This view hit an error', zh: '此頁渲染出錯' },
  'Reload': { en: 'Reload', zh: '重新載入' },
  'Refresh': { en: 'Refresh', zh: '重新整理' },
  'OpenShell services · open / revoke': { en: 'OpenShell services · open / revoke', zh: 'OpenShell 服務 · 開放 / 收回' },
  'Network services': { en: 'Network services', zh: '網路服務' },
  'no endpoints': { en: 'no endpoints', zh: '無端點' },
  'Revoke service': { en: 'Revoke service', zh: '收回服務' },
  'Revoke': { en: 'Revoke', zh: '收回' },
  'Open an endpoint': { en: 'Open an endpoint', zh: '開放端點' },
  'Open': { en: 'Open', zh: '開放' },
  'Apply a preset': { en: 'Apply a preset', zh: '套用 preset' },
  '+ Preset': { en: '+ Preset', zh: '＋Preset' },
  '− Preset': { en: '− Preset', zh: '－Preset' },
  'Apply preset': { en: 'Apply preset', zh: '套用 preset' },
  'Remove preset': { en: 'Remove preset', zh: '移除 preset' },
  'deny-by-default · no network services': { en: 'deny-by-default · no network services', zh: '預設全拒 · 無網路服務' },
  'All changes are prove-gated server-side; deny-by-default stays intact.': { en: 'All changes are prove-gated server-side; deny-by-default stays intact.', zh: '所有變更後端 prove 驗證;預設全拒不變。' },
  'policy API unavailable': { en: 'policy API unavailable', zh: '政策 API 不可用' },
  'policy unavailable': { en: 'policy unavailable', zh: '政策不可用' },
  'loading…': { en: 'loading…', zh: '載入中…' },
  'online': { en: 'online', zh: '在線' },
  'offline': { en: 'offline', zh: '離線' },
  'name': { en: 'name', zh: '名稱' },
  'role': { en: 'role', zh: '角色' },
  'zone': { en: 'zone', zh: '區域' },
  'port': { en: 'port', zh: '埠' },
  'tag': { en: 'tag', zh: '標籤' },
  'caps': { en: 'caps', zh: '能力' },
  'status': { en: 'status', zh: '狀態' },
  'device-offline-or-idle': { en: 'EBG19P offline or no syslog — shown when the device is online.', zh: 'EBG19P 離線或無 syslog — 設備上線後顯示。' },
};
function t(s) { if (s == null) return s; const e = I18N[s]; return e ? (e[LANG] || s) : s; }
function setLang(l) { LANG = l; localStorage.setItem('nf-lang', l); dispatchEvent(new CustomEvent('nfui')); }
applyUI();

class ErrorBoundary extends React.Component {
  constructor(p) { super(p); this.state = { err: null }; }
  static getDerivedStateFromError(err) { return { err }; }
  componentDidCatch(err) { try { console.error('view error:', err); } catch (e) {} }
  render() {
    if (!this.state.err) return this.props.children;
    const e = this.state.err;
    return html`<div class="errbox" style=${{ margin: '20px 0' }}><b>${t('This view hit an error')}</b>
      <pre class="mono" style=${{ whiteSpace: 'pre-wrap', fontSize: '11px', color: 'var(--crit)', maxWidth: '820px', overflow: 'auto', marginTop: '8px' }}>${String((e && e.stack) || e)}</pre>
      <button class="retry" onClick=${() => location.reload()}>${t('Reload')}</button></div>`;
  }
}
function DrawerHost() {
  const [dw, setDw] = useState(null);
  useEffect(() => {
    const h = e => setDw(e.detail);
    const esc = e => { if (e.key === 'Escape') setDw(null); };
    addEventListener('nfdrawer', h); addEventListener('keydown', esc);
    return () => { removeEventListener('nfdrawer', h); removeEventListener('keydown', esc); };
  }, []);
  if (!dw) return null;
  return html`<div class="drawer-scrim" onClick=${() => setDw(null)}>
    <aside class="drawer" onClick=${e => e.stopPropagation()}>
      <div class="drawer-hd"><h3>${dw.title || 'Details'}</h3>${dw.sub ? html`<span class="dwsub">${dw.sub}</span>` : null}<button class="drawer-x" onClick=${() => setDw(null)}>✕</button></div>
      <div class="drawer-bd">${dw.node ? dw.node : (dw.rows || []).map((r, i) => html`<div key=${i} class="kv"><span class="kvk">${r.k}</span><span class=${'kvv ' + (r.mono ? 'mono' : '')}>${r.v == null || r.v === '' ? '—' : r.v}</span></div>`)}</div>
    </aside>
  </div>`;
}
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
  }}>${busy ? html`<span class="mini"></span>${t(busyLabel) || '…'}` : t(label)}</button>`;
});
const ConfirmBtn = memo(function ConfirmBtn({ run: doRun, label, busyLabel, confirm: confirmMsg, ghost, danger }) {
  const [busy, setBusy] = useState(false);
  return html`<button class=${'btn ' + (ghost ? 'ghost ' : '') + (danger ? 'danger' : '')} disabled=${busy} onClick=${async () => {
    if (confirmMsg && !window.confirm(confirmMsg)) return;
    setBusy(true);
    try { const r = await doRun(); const good = r && (r.ok || r.out); toast(r && r.msg ? r.msg : (good ? 'Done' : 'Failed'), good ? 'g' : 'c'); }
    catch (e) { toast('Failed: ' + e.message, 'c'); }
    finally { setBusy(false); reloadNow(); }
  }}>${busy ? html`<span class="mini"></span>${t(busyLabel) || '…'}` : t(label)}</button>`;
});

// form + control primitives ──────────────────────────────────────────────────
async function run(promise, okMsg) {
  try { const r = await promise; toast(r && r.msg ? r.msg : (r && r.ok !== false ? (okMsg || 'Saved') : 'Failed'), r && r.ok !== false ? 'g' : 'c'); }
  catch (e) { toast(e.message, 'c'); } finally { reloadNow(); }
}
const Field = ({ label, hint, children }) => html`<label class="field"><span class="flabel">${t(label)}</span>${children}${hint ? html`<span class="fhint">${t(hint)}</span>` : null}</label>`;
const Segmented = ({ value, options, onChange }) => html`<div class="seg2">${options.map(o => { const v = typeof o === 'object' ? o.v : o, l = typeof o === 'object' ? o.l : o; return html`<button key=${v} class=${'segbtn ' + (String(value) === String(v) ? 'on' : '')} onClick=${() => onChange(v)}>${l}</button>`; })}</div>`;
const Toggle = ({ on, onChange }) => html`<button class=${'toggle ' + (on ? 'on' : '')} role="switch" aria-checked=${!!on} onClick=${() => onChange(!on)}><span class="knob"></span></button>`;

// VirtualList — windowed rendering for very large lists (only visible rows in the DOM)
function VirtualList({ rows, rowH = 40, height = 320, render, empty }) {
  const [top, setTop] = useState(0);
  if (!rows.length) return html`<div class="empty">${t(empty || 'No data.')}</div>`;
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
    <div class="ph"><h3>${t(title)}</h3>${label ? html`<span class="lbl">${t(label)}</span>` : null}
      ${right ? html`<div class="r">${right}</div>` : null}</div>
    <div class="pb">${children}</div></section>`;
});

const Kpi = memo(function Kpi({ stripe, label, big, unit, sub }) {
  return html`<div class="kpi"><span class="stripe" style=${{ background: stripe }}></span>
    <div class="lbl">${t(label)}</div>
    <div><span class="big">${big}</span>${unit ? html`<span class="unit">${unit}</span>` : null}</div>
    <div class="sub">${t(sub)}</div></div>`;
});

const SevBar = ({ label, count, max, color, dotcls }) => {
  const pct = max ? Math.max(6, Math.round(count / max * 100)) : 6;
  return html`<div class="sevrow"><div class="sevname">
      <span class=${'dot ' + (dotcls || '')} style=${dotcls ? null : { background: color, color }}></span>${t(label)}</div>
    <div class="track"><div class="fill" style=${{ width: pct + '%', background: color }}></div></div>
    <div class="num">${count}</div></div>`;
};

// DataTable — client-side pagination (scale-ready: swap for server pagination via api.js later)
const DataTable = memo(function DataTable({ rows, cols, pageSize = 8, empty, fetchPage, onRow, drawerTitle }) {
  const [page, setPage] = useState(0);
  const [srv, setSrv] = useState(null);   // server-paginated result when fetchPage is given
  useEffect(() => { if (!fetchPage) return; let ok = true; fetchPage(page, pageSize).then(r => ok && setSrv(r)); return () => { ok = false; }; }, [fetchPage, page, pageSize]);
  const total = fetchPage ? (srv ? srv.total : 0) : rows.length;
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const p = Math.min(page, pages - 1);
  const slice = fetchPage ? (srv ? srv.rows : []) : rows.slice(p * pageSize, p * pageSize + pageSize);
  if (!total && !fetchPage) return html`<div class="empty">${t(empty || 'No data.')}</div>`;
  if (!slice.length) return html`<div class="empty">${empty || 'No data.'}</div>`;
  return html`<div><div class="tblwrap"><table class="dt">
      <thead><tr>${cols.map(c => html`<th key=${c.k} style=${c.align ? { textAlign: c.align } : null}>${t(c.label)}</th>`)}</tr></thead>
      <tbody>${slice.map((row, i) => html`<tr key=${i} class="clickrow" onClick=${() => (onRow ? onRow(row) : rowDrawer(drawerTitle || 'Detail', row))}>${cols.map(c => html`<td key=${c.k} style=${c.align ? { textAlign: c.align } : null}>${c.render ? c.render(row) : row[c.k]}</td>`)}</tr>`)}</tbody>
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
        scales: { x: { grid: { color: THEME === 'light' ? '#e4e8ee' : '#20242f', drawTicks: false }, ticks: { color: THEME === 'light' ? '#8b93a3' : '#5b6475', font: { family: 'ui-monospace', size: 10 }, maxRotation: 0, autoSkip: false } },
          y: { grid: { color: THEME === 'light' ? '#e4e8ee' : '#20242f' }, ticks: { color: THEME === 'light' ? '#8b93a3' : '#5b6475', font: { family: 'ui-monospace', size: 10 }, maxTicksLimit: 4 }, beginAtZero: true } },
        plugins: { legend: { display: false }, tooltip: { backgroundColor: 'var(--inset)', borderColor: '#333949', borderWidth: 1, padding: 10, titleColor: '#9aa3b6', bodyColor: '#e7eaf2', displayColors: false } } },
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
      ${html`<${Kpi} stripe="var(--good)" label="Governance coverage" big=${g.coverage} unit="%" sub=${g.allowed.toLocaleString() + ' ' + t('actions · 2h window')}/>`}
      ${html`<${Kpi} stripe="var(--crit)" label="Blocked egress (DENIED)" big=${g.denied} sub="unauthorized host · OPA host-layer"/>`}
      ${html`<${Kpi} stripe="var(--warn)" label="Active alerts" big=${d.alerts.length} sub=${d.alerts[0] ? d.alerts[0].msg : 'none'}/>`}
      ${html`<${Kpi} stripe="var(--accent)" label="Open escalations" big=${d.jira.length} unit="Jira" sub="human-in-the-loop · NETOPS"/>`}
    </section>
    <div class="grid">
      <div class="col">
        ${html`<${Panel} title="Governance events" label="OCSF · 2h" right=${html`<span class="legend"><span><i style=${{ background: SERIES.allowed }}></i>${t('Allowed volume')}</span></span>`}>
          <${GovChart} gov=${g}/>
          <div class="gstat">
            <div><div class="num" style=${{ color: SERIES.allowed }}>${g.allowed.toLocaleString()}</div><div class="lbl">${t('Allowed')}</div></div>
            <div><div class="num" style=${{ color: 'var(--crit)' }}>${g.denied}</div><div class="lbl">${t('Denied (real)')}</div></div>
            <div><div class="num ink2">${g.benign.toLocaleString()}</div><div class="lbl">${t('Heartbeats · excluded')}</div></div>
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
  return html`<${Panel} title="Agent fleet" label=${t('Hermes harness') + ' ×' + nodes.length}>
    <div class="nodes">${nodes.map(n => html`<div key=${n.name} class="node clickcard" onClick=${() => openDrawer({ title: t('Node detail'), sub: n.name, rows: [
        { k: 'name', v: n.name, mono: true }, { k: 'role', v: n.role }, { k: 'zone', v: n.zone || '—' }, { k: 'port', v: ':' + n.port, mono: true },
        { k: 'status', v: n.up ? '● up' : '○ down' }, { k: 'tag', v: n.tag }, { k: 'caps', v: (n.caps || []).join(', ') || '—' } ] })}>
      <span class="ico"><svg viewBox="0 0 24 24"><circle cx="12" cy="8" r="3.4" fill="none" stroke="currentColor" stroke-width="1.7"/><path d="M5 20c0-3.6 3.1-6 7-6s7 2.4 7 6" fill="none" stroke="currentColor" stroke-width="1.7"/></svg></span>
      <div><div class="nm">${n.name} <span class=${'tag ' + (n.tag === 'lead' ? 'a' : 'g')}>${t(n.tag)}</span></div><div class="role">${n.role}</div></div>
      <div class="rt"><${Dot} up=${n.up}/> :${n.port}<br/><span class="muted">${n.zone || ''}</span></div>
    </div>`)}</div>
    <hr class="sep" style=${{ margin: '14px 0 12px' }}/>
    <div class="lbl" style=${{ marginBottom: '10px' }}>${t('Managed device')}${devices.length > 1 ? ' · ' + devices.length : ''}</div>
    <div class="device clickcard" onClick=${() => openDrawer({ title: t('Device detail'), sub: dev.model || 'EBG19P', rows: [
        { k: 'asset', v: dev.asset || 'lab-asus-ebg19p-01', mono: true }, { k: 'model', v: dev.model || 'EBG19P' }, { k: 'firmware', v: dev.firmware || '—', mono: true },
        { k: 'CPU', v: (dev.cpu ?? '—') + ' %' }, { k: 'MEM', v: (dev.mem ?? '—') + ' %' }, { k: 'TEMP', v: (dev.temp ?? '—') + ' °C' }, { k: 'online', v: dev.online !== false ? 'yes' : 'no' } ] })}><div class="metrics">
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
  const [cat, setCat] = useState('all');
  const cats = ['all', ...Array.from(new Set((events || []).map(e => e.cat || 'service')))];
  const rows = cat === 'all' ? events : (events || []).filter(e => (e.cat || 'service') === cat);
  return html`<${Panel} title="Recent device events" label="EBG19P syslog · classified"
    right=${html`<div class="seg2 filt">${cats.slice(0, 6).map(c => html`<button key=${c} class=${'segbtn ' + (cat === c ? 'on' : '')} onClick=${() => setCat(c)}>${c}</button>`)}</div>`}>
    <${DataTable} rows=${rows} pageSize=${6} empty=${t("device-offline-or-idle")}
      cols=${[
        { k: 't', label: 'Time', render: r => html`<span class="mono">${r.t || ''}</span>` },
        { k: 'cat', label: 'Category', render: r => html`<span class="catpill">${r.cat || 'service'}</span>` },
        { k: 'msg', label: 'Event' },
        { k: 'sev', label: 'Severity', align: 'right', render: r => sevPill(r.sev) },
      ]}/>
  </${Panel}>`;
});

const SNAP_SB = ['team-lead', 'worker-a', 'worker-b', 'worker-c'];
const POLSB = ['team-lead', 'worker-a', 'worker-b', 'worker-c'];
const FleetView = memo(function FleetView({ d }) {
  const [sb, setSb] = useState('worker-a');
  const [diag, setDiag] = useState(null);
  const [snapSel, setSnapSel] = useState('');
  const [inf, setInf] = useState({ provider: '', model: '' });
  const runDiag = (doWhat) => { setDiag({ title: doWhat + ' · ' + sb, out: 'Running…' });
    NF.sys({ do: doWhat, sb }).then(r => setDiag({ title: r.title || doWhat, out: r.out || '(no output)' })).catch(e => setDiag({ title: doWhat, out: e.message })); };
  return html`<div class="viewfade"><div class="viewhd"><h2>${t('Fleet')}</h2><span class="lbl">${d.nodes.length} nodes · ${d.devices.length} device(s)</span></div>
    <div class="grid"><div class="col">
      <${FleetSummary} nodes=${d.nodes} devices=${d.devices}/>
      ${html`<${Panel} title="Snapshots" label="per sandbox · recovery points">
        <${Field} label="Sandbox"><${Segmented} value=${sb} options=${SNAP_SB} onChange=${setSb}/></${Field}>
        <div class="addrow">
          <button class="btn" onClick=${() => run(NF.snapshot('create', '', sb), 'Snapshot created')}>${t('+ Create snapshot')}</button>
          <button class="btn ghost" onClick=${() => run(NF.action('refresh'), 'Refreshed')}>${t('Refresh')}</button>
        </div>
        <div class="addrow" style=${{ marginTop: '8px' }}>
          <input class="inp" placeholder="snapshot id(空=最新)" value=${snapSel} onInput=${e => setSnapSel(e.target.value)}/>
          <${ConfirmBtn} ghost=${true} confirm=${'還原 ' + sb + ' ← ' + (snapSel || 'latest') + '?'} run=${() => NF.snapshot('restore', snapSel, sb)} label="Restore" busyLabel="restoring"/>
          <${ConfirmBtn} danger=${true} confirm=${'刪除 ' + sb + ' 的快照 ' + (snapSel || 'latest') + '?'} run=${() => NF.snapshot('delete', snapSel, sb)} label="Delete" busyLabel="deleting"/>
        </div>
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
        <div class="addrow">${['doctor', 'logs', 'recover', 'gwhealth', 'stale', 'gsettings'].map(x => html`<button key=${x} class="btn ghost" onClick=${() => runDiag(x)}>${x}</button>`)}
          <${ConfirmBtn} danger=${true} confirm=${'Rebuild ' + sb + '?會重建沙箱(數分鐘;自訂 policy 之後需 boot-stack 重補)。'} run=${() => NF.sys({ do: 'rebuild', sb })} label="rebuild" busyLabel="rebuilding"/></div>
        ${diag ? html`<div style=${{ marginTop: '12px' }}><div class="lbl" style=${{ marginBottom: '6px' }}>${diag.title}</div>
          <pre class="mono" style=${{ background: 'var(--inset)', border: '1px solid var(--line)', borderRadius: '8px', padding: '10px', fontSize: '11px', color: 'var(--ink2)', maxHeight: '220px', overflow: 'auto', whiteSpace: 'pre-wrap' }}>${diag.out}</pre></div>` : null}
      </${Panel}>`}
      ${html`<${Panel} title="Inference" label="切換 provider / model(nemoclaw inference set)">
        <${Field} label="Sandbox"><${Segmented} value=${sb} options=${SNAP_SB} onChange=${setSb}/></${Field}>
        <div class="addrow">
          <input class="inp" placeholder="provider (vllm-local / nim…)" value=${inf.provider} onInput=${e => setInf({ ...inf, provider: e.target.value })}/>
          <input class="inp" placeholder="model (nemotron-super)" value=${inf.model} onInput=${e => setInf({ ...inf, model: e.target.value })}/>
          <${ConfirmBtn} confirm=${'把 ' + sb + ' 的推理切到 ' + (inf.provider || '?') + ' / ' + (inf.model || '?') + '?'} run=${() => NF.sys({ do: 'infset', sb, provider: inf.provider, model: inf.model })} label="Apply" busyLabel="applying"/>
        </div></${Panel}>`}
      ${html`<${Panel} title="Device ops · EBG19P" label="worker-a 快速處置(需設備連線)">
        <div class="addrow">${[['sync', '同步設定'], ['harden', '一鍵強化'], ['restart', '重啟服務'], ['block', '封鎖未授權']].map(([op, lbl]) => html`<${ConfirmBtn} key=${op} ghost=${true} confirm=${lbl + '(' + op + ')— 對真實 EBG19P 執行,確定?'} run=${() => NF.deviceAction(op)} label=${lbl} busyLabel="…"/>`)}</div>
        <div class="muted" style=${{ fontSize: '11px', marginTop: '8px' }}>設備不在網段時回「不可達」的優雅降級;每筆進稽核。</div></${Panel}>`}
    </div></div></div>`;
});

// posture(d) — fuse drift + CVE + nuclei + cert into one EBG19P security-posture score (0-100 + grade
// + what's dragging it down). Pure; reads the normalized model. The payoff of running all four scanners.
function posture(d) {
  let score = 100; const factors = [];
  const pen = (label, n, each, cap) => { if (n > 0) { const p = Math.min(n * each, cap); score -= p; factors.push({ label, n, penalty: p }); } };
  const regs = (d.devices || []).reduce((a, x) => a + ((x.regressions || []).length), 0);
  const nucF = (d.nuclei && d.nuclei.findings) || [];
  const sev = re => nucF.filter(f => re.test(f.severity || '')).length;
  const certHigh = ((d.cert && d.cert.findings) || []).filter(f => /high|crit/i.test(f.severity || f.issue || '')).length;
  pen('nuclei critical', sev(/crit/i), 15, 45);
  pen('設定安全退化 (drift)', regs, 8, 40);
  pen('affected CVE', ((d.cve && d.cve.findings) || []).length, 6, 36);
  pen('nuclei high', sev(/high/i), 8, 32);
  pen('憑證/加密高風險', certHigh, 7, 28);
  score = Math.max(0, Math.round(score));
  return { score, grade: score >= 90 ? 'A' : score >= 80 ? 'B' : score >= 65 ? 'C' : score >= 50 ? 'D' : 'F', factors };
}
const SecurityView = memo(function SecurityView({ d }) {
  const P = posture(d);
  const gc = P.score >= 80 ? 'var(--ok)' : P.score >= 65 ? 'var(--warn)' : 'var(--crit)';
  return html`<div class="viewfade"><div class="viewhd"><h2>${t('Security')}</h2><span class="lbl">${t('worker-b · CVE / nuclei / cert / source')}</span></div>
    <div class="grid1">
      ${html`<${Panel} title="EBG19P security posture" label="drift · CVE · nuclei · cert 融合成一個分數">
        <div style=${{ display: 'flex', gap: '22px', alignItems: 'center', flexWrap: 'wrap' }}>
          <div style=${{ textAlign: 'center', minWidth: '104px' }}>
            <div style=${{ fontSize: '46px', fontWeight: 800, lineHeight: 1, color: gc }}>${P.score}</div>
            <div style=${{ fontSize: '13px', color: 'var(--ink2)', marginTop: '3px' }}>/ 100 · grade <b style=${{ color: gc }}>${P.grade}</b></div>
          </div>
          <div style=${{ flex: 1, minWidth: '220px' }}>
            ${P.factors.length ? P.factors.map(f => html`<div key=${f.label} style=${{ marginBottom: '7px' }}>
              <div style=${{ display: 'flex', justifyContent: 'space-between', fontSize: '12px' }}><span class="ink2">${t(f.label)} <b>×${f.n}</b></span><span style=${{ color: 'var(--crit)' }}>−${f.penalty}</span></div>
              <div style=${{ height: '4px', background: 'var(--line)', borderRadius: '3px', overflow: 'hidden', marginTop: '3px' }}><div style=${{ width: Math.min(f.penalty * 2, 100) + '%', height: '100%', background: 'var(--crit)' }}></div></div>
            </div>`) : html`<div class="muted">無扣分項 — 機隊安全姿態良好 ✓</div>`}
          </div>
        </div></${Panel}>`}
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
      ${(d.me && d.me.role === 'admin') ? html`<${Panel} title="Cipher policy override" label="標記為弱加密的家族(cert_cipher_policy=custom 時生效)">
        <div class="addrow" style=${{ flexWrap: 'wrap' }}>${['rc4', '3des', 'cbc', 'null', 'export', 'md5', 'sha1', 'des'].map(fam => html`<span key=${fam} class="seg2" style=${{ display: 'inline-flex' }}>
          <button class="segbtn" onClick=${() => run(NF.certPolicy({ fam, on: 1 }), 'flag ' + fam)}>flag ${fam}</button>
          <button class="segbtn" onClick=${() => run(NF.certPolicy({ fam, on: 0 }), 'clear ' + fam)}>clear</button></span>`)}</div>
        <div class="muted" style=${{ fontSize: '11px', marginTop: '8px' }}>先到 Settings 把 cipher policy 設成 <b>custom</b>;個別家族開/關即時套用到 worker-a 掃描。</div></${Panel}>` : null}
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
  return html`<div class="viewfade"><div class="viewhd"><h2>${t('Governance')}</h2><span class="lbl">${t('OPA / L7 · OCSF events')}</span></div>
    <div class="grid1">
      ${html`<${Panel} title="Event volume" label="allowed · 2h"><${GovChart} gov=${g}/>
        <div class="gstat"><div><div class="num" style=${{ color: SERIES.allowed }}>${g.allowed.toLocaleString()}</div><div class="lbl">${t('Allowed')}</div></div>
        <div><div class="num" style=${{ color: 'var(--crit)' }}>${g.denied}</div><div class="lbl">${t('Denied')}</div></div>
        <div><div class="num ink2">${g.benign.toLocaleString()}</div><div class="lbl">${t('Heartbeats')}</div></div></div></${Panel}>`}
      ${html`<${GovActionsPanel} events=${g.events}/>`}
      ${d.me && d.me.role === 'admin' ? html`<${PolicyEditor}/>` : null}
    </div></div>`;
});
const GovActionsPanel = memo(function GovActionsPanel({ events }) {
  const [vf, setVf] = useState('all');
  const ev = vf === 'all' ? events : (events || []).filter(r => { const dn = (r.verdict || r.cls || '').toLowerCase().includes('den'); return vf === 'denied' ? dn : !dn; });
  return html`<${Panel} title="Recent governed actions" label="engine · policy · verdict"
    right=${html`<div class="seg2 filt">${['all', 'allowed', 'denied'].map(x => html`<button key=${x} class=${'segbtn ' + (vf === x ? 'on' : '')} onClick=${() => setVf(x)}>${t(x)}</button>`)}</div>`}>
    <${DataTable} rows=${ev} pageSize=${10} empty="No governance events in window."
      cols=${[
        { k: 'ts', label: 'Time', render: r => html`<span class="mono">${r.ts || r.t || ''}</span>` },
        { k: 'target', label: 'Target', render: r => html`<span class="mono">${r.target || r.b || ''}</span>` },
        { k: 'policy', label: 'Policy', render: r => html`<span class="catpill">${r.policy || r.a || '—'}</span>` },
        { k: 'verdict', label: 'Verdict', align: 'right', render: r => {
          const dn = (r.verdict || r.cls || '').toLowerCase().includes('den');
          return html`<span class=${'sev ' + (dn ? 'hi' : 'in')}>${dn ? 'DENIED' : 'ALLOWED'}</span>`; } },
      ]}/></${Panel}>`;
});
const PolicyEditor = memo(function PolicyEditor() {
  const [sb, setSb] = useState('team-lead');
  const [pol, setPol] = useState(null);
  const [preset, setPreset] = useState('');
  const [ep, setEp] = useState({ host: '', port: '443', access: 'full' });
  const [nonce, setNonce] = useState(0);
  useEffect(() => {
    if (typeof NF.policyRo !== 'function') { setPol({ ok: false, msg: t('policy API unavailable') }); return; }
    let ok = true; setPol({ loading: true });
    NF.policyRo(sb).then(r => ok && setPol(r)).catch(e => ok && setPol({ ok: false, msg: e.message }));
    return () => { ok = false; };
  }, [sb, nonce]);
  const p = (pol && pol.policy) || {};
  const nets = p.networks || [];
  const after = () => setNonce(n => n + 1);   // reload the policy after a mutation
  return html`<${Panel} title="Policy editor" label=${t('OpenShell services · open / revoke')}
    right=${html`<${Segmented} value=${sb} options=${POLSB} onChange=${setSb}/>`}>
    ${!pol || pol.loading ? html`<div class="muted">${t('loading…')}</div>` : !pol.ok ? html`<div class="muted">${pol.msg || t('policy unavailable')}</div>` : html`<div>
      <div class="muted mono" style=${{ fontSize: '11px', margin: '2px 0 10px' }}>version ${p.version || '?'} · ${(p.hash || '')}</div>
      <div class="lbl" style=${{ marginBottom: '7px' }}>${t('Network services')} · ${nets.length}</div>
      ${nets.length ? nets.map(n => html`<div key=${n.name} class="polrow">
        <div class="grow">
          <div style=${{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <b class="mono" style=${{ fontSize: '12.5px' }}>${n.name}</b>
            ${n.l7 ? html`<span class="pill2 g">L7</span>` : null}
            ${n.nbin ? html`<span class="muted" style=${{ fontSize: '10.5px' }}>${n.nbin} bin</span>` : null}
          </div>
          <div class="muted mono" style=${{ fontSize: '11px', marginTop: '3px', wordBreak: 'break-all' }}>${(n.eps || []).join('  ·  ') || t('no endpoints')}</div>
        </div>
        <${ConfirmBtn} danger=${true} ghost=${true} confirm=${t('Revoke service') + ' \'' + n.name + '\' (' + sb + ')?'} run=${() => NF.policy({ op: 'rule_remove', name: n.name, sb }).then(r => { after(); return r; })} label=${t('Revoke')} busyLabel="…"/>
      </div>`) : html`<div class="muted" style=${{ padding: '6px 0' }}>${t('deny-by-default · no network services')}</div>`}

      <div class="lbl" style=${{ margin: '15px 0 6px' }}>${t('Open an endpoint')}</div>
      <div class="addrow" style=${{ flexWrap: 'wrap' }}>
        <input class="inp" style=${{ maxWidth: '210px' }} placeholder="host (api.example.com)" value=${ep.host} onInput=${e => setEp({ ...ep, host: e.target.value })}/>
        <input class="inp" style=${{ maxWidth: '80px' }} placeholder="port" value=${ep.port} onInput=${e => setEp({ ...ep, port: e.target.value })}/>
        <${Segmented} value=${ep.access} options=${['full', 'rest', 'websocket']} onChange=${v => setEp({ ...ep, access: v })}/>
        <${ConfirmBtn} confirm=${t('Open') + ' ' + ep.host + ':' + ep.port + ' (' + sb + ')?'} run=${() => NF.policy({ op: 'endpoint_add', host: ep.host, port: ep.port, access: ep.access, sb }).then(r => { after(); return r; })} label=${t('Open')} busyLabel="…"/>
      </div>

      <div class="lbl" style=${{ margin: '15px 0 6px' }}>${t('Apply a preset')}</div>
      <div class="addrow">
        <input class="inp" placeholder="telegram / github / huggingface…" value=${preset} onInput=${e => setPreset(e.target.value)}/>
        <${ConfirmBtn} confirm=${t('Apply preset') + ' \'' + preset + '\' → ' + sb + '?'} run=${() => NF.policy({ op: 'preset', name: preset, on: true, sb }).then(r => { after(); return r; })} label=${t('+ Preset')} busyLabel="…"/>
        <${ConfirmBtn} danger=${true} confirm=${t('Remove preset') + ' \'' + preset + '\' (' + sb + ')?'} run=${() => NF.policy({ op: 'preset', name: preset, on: false, sb }).then(r => { after(); return r; })} label=${t('− Preset')} busyLabel="…"/>
      </div>
      <div class="muted" style=${{ fontSize: '11px', marginTop: '10px' }}>${t('All changes are prove-gated server-side; deny-by-default stays intact.')}</div>
    </div>`}
  </${Panel}>`;
});
const ChannelPanel = memo(function ChannelPanel() {
  const [sb, setSb] = useState('team-lead');
  const [chan, setChan] = useState('telegram');
  return html`<${Panel} title="Messaging channels" label="start / stop per sandbox">
    <div class="addrow" style=${{ flexWrap: 'wrap' }}>
      <${Segmented} value=${sb} options=${POLSB} onChange=${setSb}/>
      <input class="inp" style=${{ maxWidth: '140px' }} value=${chan} onInput=${e => setChan(e.target.value)}/>
      <${ConfirmBtn} confirm=${'Start ' + chan + ' on ' + sb + '?會 rebuild 沙箱。'} run=${() => NF.sys({ do: 'chanstart', sb, chan })} label="Start" busyLabel="starting"/>
      <${ConfirmBtn} danger=${true} confirm=${'Stop ' + chan + ' on ' + sb + '?會 rebuild 沙箱(保留憑證)。'} run=${() => NF.sys({ do: 'chanstop', sb, chan })} label="Stop" busyLabel="stopping"/>
    </div>
    <div class="muted" style=${{ fontSize: '11px', marginTop: '8px' }}>Stop/Start 會 rebuild 沙箱;憑證保留。</div>
  </${Panel}>`;
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
  quiet_start: ['20:00', '21:00', '22:00', '23:00', '00:00'], quiet_end: ['06:00', '07:00', '08:00', '09:00', '10:00'],
};
const SettingsView = memo(function SettingsView({ d }) {
  const s = d.settings || {};
  const set = (k, v) => run(NF.config(k, v), k + ' updated');
  const seg = (k, hint) => html`<${Field} label=${k} hint=${hint}><${Segmented} value=${s[k]} options=${CFG[k]} onChange=${v => set(k, v)}/></${Field}>`;
  const chans = String(s.notify_channels || 'jira,dashboard').split(',');
  const toggleChan = c => { const next = chans.includes(c) ? chans.filter(x => x !== c) : [...chans, c]; set('notify_channels', next.join(',')); };
  return html`<div class="viewfade"><div class="viewhd"><h2>${t('Settings')}</h2><span class="lbl">${t('writes to the live backend')}</span></div>
    <div class="grid1">
      ${html`<${Panel} title="Appearance" label="theme · language · density"><div class="formgrid">
        <${Field} label="Theme"><${Segmented} value=${THEME} options=${[{ v: 'light', l: t('Light') }, { v: 'dark', l: t('Dark') }]} onChange=${setTheme}/></${Field}>
        <${Field} label="Language / 語言"><${Segmented} value=${LANG} options=${[{ v: 'zh', l: '中文' }, { v: 'en', l: 'English' }]} onChange=${setLang}/></${Field}>
        <${Field} label="Density"><${Segmented} value=${DENSITY} options=${[{ v: 'compact', l: t('Compact') }, { v: 'cozy', l: t('Cozy') }, { v: 'spacious', l: t('Spacious') }]} onChange=${setDensity}/></${Field}>
      </div></${Panel}>`}
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
      ${html`<${Panel} title="Quiet hours & scan tags" label="靜音時段(critical 仍推)+ nuclei 範圍"><div class="formgrid">
        <${Field} label="quiet_enabled" hint="啟用靜音時段"><${Toggle} on=${s.quiet_enabled === true} onChange=${v => set('quiet_enabled', v)}/></${Field}>
        ${seg('quiet_start', '靜音開始')}${seg('quiet_end', '靜音結束')}
        <${Field} label="nuclei_tags" hint="逗號分隔(asus,cve,exposure…)"><input class="inp" defaultValue=${s.nuclei_tags || 'asus,cve'} onBlur=${e => set('nuclei_tags', e.target.value)}/></${Field}>
      </div></${Panel}>`}
    </div></div>`;
});
const AdminView = memo(function AdminView({ d }) {
  const users = (d.acl && d.acl.users) || [];
  const recips = d.recipients || [];
  const [nu, setNu] = useState({ email: '', password: '', role: 'viewer' });
  const [nr, setNr] = useState({ name: '', telegram: '', email: '' });
  if (d.me.role !== 'admin') return html`<div class="viewfade"><div class="viewhd"><h2>${t('Admin')}</h2></div><div class="empty">Admin only.</div></div>`;
  return html`<div class="viewfade"><div class="viewhd"><h2>Admin</h2><span class="lbl">${t('users · notifications')}</span></div>
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
      ${html`<${ChannelPanel}/>`}
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
            <${Field} label="Critical alerts" hint="維護時暫時靜音主動打斷(仍巡邏+記錄)">
              ${(p.snooze_until && p.snooze_until * 1000 > Date.now())
                ? html`<span class="pill2 w">snoozed → ${new Date(p.snooze_until * 1000).toLocaleTimeString()}</span> <${ActionBtn} act="snooze_off" label="Resume" busyLabel="…" ghost=${true}/>`
                : html`<span class="pill2 g">active</span> <${ActionBtn} act="snooze30" label="Snooze 30m" busyLabel="…" ghost=${true}/> <${ActionBtn} act="snooze120" label="2h" busyLabel="…" ghost=${true}/>`}
            </${Field}>
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
const FlowView = memo(function FlowView({ d }) {
  const flow = d.flow || [];
  const active = new Set(flow.filter(e => e.status === 'working').map(e => e.node));
  const nodes = [{ id: 'team-lead', label: 'team-lead', role: 'front desk · coordinator' }, { id: 'worker-a', label: 'worker-a', role: 'ops' }, { id: 'worker-b', label: 'worker-b', role: 'security' }, { id: 'worker-c', label: 'worker-c', role: 'governance' }];
  const stPill = st => html`<span class=${'pill2 ' + (st === 'working' ? 'a' : st === 'done' ? 'g' : (st === 'fail' || st === 'error') ? 'c' : '')}>${st}</span>`;
  return html`<div class="viewfade">
    <div class="viewhd"><h2>${t('Flow')}</h2>
      <span class=${'pill2 ' + (active.size ? 'a' : 'g')}>${active.size ? active.size + ' working' : 'idle'}</span>
      <span class="lbl">誰委派誰、正在做什麼 · 即時</span></div>
    <div class="grid1">
      ${html`<${Panel} title="Fleet activity" label="正在工作的節點會亮起">
        <div style=${{ display: 'flex', gap: '12px', flexWrap: 'wrap' }}>
          ${nodes.map(n => html`<div key=${n.id} style=${{ padding: '11px 15px', borderRadius: '11px', border: '1px solid ' + (active.has(n.id) ? 'var(--acc)' : 'var(--line)'), background: active.has(n.id) ? 'rgba(57,135,229,.12)' : 'var(--panel2, var(--panel))', minWidth: '132px', transition: 'all .2s' }}>
            <div class="mono" style=${{ fontWeight: 700, fontSize: '13px' }}>${n.label}</div>
            <div class="muted" style=${{ fontSize: '11px', marginTop: '1px' }}>${n.role}</div>
            <div style=${{ fontSize: '11.5px', marginTop: '5px', fontWeight: 600, color: active.has(n.id) ? 'var(--warn)' : 'var(--ink3, var(--muted))' }}>${active.has(n.id) ? '● working' : '○ idle'}</div>
          </div>`)}
        </div></${Panel}>`}
      ${html`<${Panel} title="Delegation timeline" label="最近的委派 / 交接 (peer → node)" right=${html`<${ActionBtn} act="patrol" label="Trigger patrol" busyLabel="…" ghost=${true}/>`}>
        <${DataTable} rows=${flow} pageSize=${12} empty="尚無工作流事件 — 委派 / 掃描觸發後會出現(team-lead → worker → 狀態)。"
          cols=${[
            { k: 'ts', label: 'Time', render: r => html`<span class="mono">${r.ts || ''}</span>` },
            { k: 'hop', label: 'Handoff', render: r => html`<span><b class="ink2">${r.peer || '?'}</b> <span class="muted">→</span> <b class="ink2">${r.node || '?'}</b></span>` },
            { k: 'task', label: 'Task', render: r => html`<span class="mono">${r.task || ''}</span>${r.detail ? html` <span class="muted" style=${{ fontSize: '11px' }}>${r.detail}</span>` : null}` },
            { k: 'status', label: 'Status', align: 'right', render: r => stPill(r.status) },
          ]}/></${Panel}>`}
    </div></div>`;
});
const ChangeCtrlView = memo(function ChangeCtrlView({ d }) {
  const g = d.governance_c || {};
  const reviews = g.reviews || [];
  const rejects = reviews.filter(r => r.verdict === 'reject').length;
  const affCves = ((d.cve && d.cve.findings) || []).map(f => f.cve).filter(Boolean);
  const fwUrgent = affCves.length > 0 || (g.firmware && g.firmware.urgency === 'high');
  const vPill = v => html`<span class=${'pill2 ' + (v === 'approve' ? 'g' : v === 'reject' ? 'c' : 'w')}>${v || '—'}</span>`;
  return html`<div class="viewfade">
    <div class="viewhd"><h2>Change control</h2>
      <span class=${'pill2 ' + (g.up ? 'g' : 'w')}>${g.up ? 'worker-c up' : 'worker-c not deployed'}</span>
      <span class="lbl">worker-c · 變更治理官 · zone C</span></div>
    <div class="grid1">
      ${html`<${Panel} title="Review gate" label="a/b 產出的品質閘 · reject 綁定重做">
        <div style=${{ display: 'flex', gap: '22px', flexWrap: 'wrap', alignItems: 'center', marginBottom: '10px' }}>
          <div style=${{ textAlign: 'center' }}><div style=${{ fontSize: '30px', fontWeight: 800, color: rejects ? 'var(--crit)' : 'var(--ok)' }}>${rejects}</div><div class="muted" style=${{ fontSize: '11px' }}>rejected → 退回重做</div></div>
          <div style=${{ textAlign: 'center' }}><div style=${{ fontSize: '30px', fontWeight: 800, color: 'var(--ink2)' }}>${reviews.length}</div><div class="muted" style=${{ fontSize: '11px' }}>total verdicts</div></div>
          <div class="muted" style=${{ fontSize: '12px', maxWidth: '340px' }}>worker-c 審 worker-a remediation + worker-b CVE 決策,錨定核准 baseline。reject → team-lead 帶 required_fixes 退回重做,2 次不過升級人。人 > worker-c > a/b。</div>
        </div>
        <${DataTable} rows=${reviews} pageSize=${8} empty="尚無審查判決(worker-c 未部署或尚無委派)。"
          cols=${[
            { k: 'ts', label: 'Time', render: r => html`<span class="mono">${r.ts || ''}</span>` },
            { k: 'target', label: 'Target', render: r => html`<span class="mono">${r.target || ''} · ${r.kind || ''}</span>` },
            { k: 'ref', label: 'Subject', render: r => html`<span class="mono muted">${r.ref || ''}</span>` },
            { k: 'verdict', label: 'Verdict', align: 'right', render: r => html`${vPill(r.verdict)}${r.escalate ? html` <span class="pill2 c">→ human</span>` : r.redo > 0 ? html` <span class="pill2 w">redo ${r.redo}</span>` : null}` },
          ]}/></${Panel}>`}
      ${html`<${Panel} title="Config backups" label="known-good 版本" right=${html`<${ActionBtn} act="backup" label="Backup now" busyLabel="…" ghost=${true}/>`}>
        <div style=${{ display: 'flex', gap: '22px', flexWrap: 'wrap', marginBottom: '9px', fontSize: '12px' }}>
          <span class="muted">count <b class="ink2">${g.backup_count || 0}</b></span>
          <span class="muted">latest <b class="mono ink2">${(g.backups || [])[0] || '—'}</b></span>
        </div>
        <${DataTable} rows=${(g.backups || []).map(b => ({ id: b }))} pageSize=${6} empty="尚無備份(需真機 + EBG19P_CRED)。"
          cols=${[{ k: 'id', label: 'Backup snapshot', render: r => html`<span class="mono">${r.id}</span>` }]}/></${Panel}>`}
      ${html`<${Panel} title="Firmware" label="生命週期 · urgency 由 CVE 驅動">
        <div style=${{ fontSize: '13px' }}>
          <div style=${{ marginBottom: '5px' }}>current <b class="mono ink2">${(g.firmware && g.firmware.current) || '—'}</b> ${fwUrgent ? html`<span class="pill2 c">update urgent</span>` : html`<span class="pill2 g">current</span>`}</div>
          ${affCves.length ? html`<div class="muted" style=${{ fontSize: '12px' }}>CVE-driven:worker-b 判 ${affCves.length} 個 affected → <span class="mono">${affCves.slice(0, 3).join(', ')}${affCves.length > 3 ? '…' : ''}</span>(韌體更新可修)</div>` : html`<div class="muted" style=${{ fontSize: '12px' }}>${(g.firmware && g.firmware.note) || 'worker-c 未部署'}</div>`}
        </div></${Panel}>`}
      ${html`<${Panel} title="Skills · curator (SkillOS)" label="技能庫治理 · arXiv 2605.06614" right=${html`<span class="lbl">${g.skills_count || 0} skills</span>`}>
        <${DataTable} rows=${g.curations || []} pageSize=${6} empty="尚無技能治理判決(worker-c 未部署或無 insert/update/delete)。"
          cols=${[
            { k: 'ts', label: 'Time', render: r => html`<span class="mono">${r.ts || ''}</span>` },
            { k: 'op', label: 'Op', render: r => html`<span class="mono">${r.op || ''} ${r.name || ''}</span>` },
            { k: 'verdict', label: 'Verdict', align: 'right', render: r => html`<span class=${'pill2 ' + (r.verdict === 'approve' ? 'g' : 'c')}>${r.verdict || '—'}</span>` },
          ]}/></${Panel}>`}
    </div></div>`;
});
const VIEWS = {
  overview: { label: 'Overview', comp: OverviewView },
  flow: { label: 'Flow', comp: FlowView },
  fleet: { label: 'Fleet', comp: FleetView },
  security: { label: 'Security', comp: SecurityView },
  governance: { label: 'Governance', comp: GovernanceView },
  proactive: { label: 'Proactive', comp: ProactiveView },
  changectrl: { label: 'Change ctrl', comp: ChangeCtrlView },
  audit: { label: 'Audit', comp: AuditView },
  admin: { label: 'Admin', comp: AdminView },
  settings: { label: 'Settings', comp: SettingsView },
};

const NAV_GROUPS = [
  { key: 'monitor', items: ['overview', 'flow', 'fleet'] },
  { key: 'govern', items: ['security', 'governance', 'changectrl', 'audit'] },
  { key: 'system', items: ['proactive', 'admin', 'settings'] },
];
const NAV_ICON = {
  overview: '<rect x="3" y="3" width="7.5" height="7.5" rx="1.5"/><rect x="13.5" y="3" width="7.5" height="7.5" rx="1.5"/><rect x="3" y="13.5" width="7.5" height="7.5" rx="1.5"/><rect x="13.5" y="13.5" width="7.5" height="7.5" rx="1.5"/>',
  flow: '<circle cx="5" cy="12" r="2.4"/><circle cx="19" cy="6" r="2.4"/><circle cx="19" cy="18" r="2.4"/><path d="M7.3 10.9 16.7 6.9M7.3 13.1 16.7 17.1"/>',
  fleet: '<rect x="3" y="4" width="18" height="5.5" rx="1.5"/><rect x="3" y="14.5" width="18" height="5.5" rx="1.5"/><path d="M6.5 6.75h.01M6.5 17.25h.01"/>',
  security: '<path d="M12 3 20 6v5.5c0 5-3.4 7.6-8 9-4.6-1.4-8-4-8-9V6z"/>',
  governance: '<path d="M12 3.5v17M6 7.5h12M8 7.5 5 14h6zM16 7.5 13 14h6zM8.5 20.5h7"/>',
  changectrl: '<circle cx="6.5" cy="6" r="2.3"/><circle cx="6.5" cy="18" r="2.3"/><circle cx="17.5" cy="12" r="2.3"/><path d="M6.5 8.3v7.4M8.7 6H13a2.2 2.2 0 0 1 2.2 2.2v2"/>',
  proactive: '<circle cx="12" cy="12" r="1.8"/><path d="M8.2 8.2a5.4 5.4 0 0 0 0 7.6M15.8 8.2a5.4 5.4 0 0 1 0 7.6M5.4 5.4a10.5 10.5 0 0 0 0 13.2M18.6 5.4a10.5 10.5 0 0 1 0 13.2"/>',
  audit: '<rect x="4.5" y="3" width="15" height="18" rx="2"/><path d="M8 8h8M8 12h8M8 16h5"/>',
  admin: '<circle cx="12" cy="8" r="3.2"/><path d="M5.5 20c0-3.5 3-5.8 6.5-5.8s6.5 2.3 6.5 5.8"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M12 3.5v3M12 17.5v3M4.5 12h3M16.5 12h3M6.2 6.2 8.3 8.3M15.7 15.7l2.1 2.1M17.8 6.2 15.7 8.3M8.3 15.7 6.2 17.8"/>',
};
function NavRail({ me, route, counts }) {
  return html`<aside class="rail">
    <div class="brand"><span class="mark"></span><div><b>nemofleet</b><div class="sub">GOVERNED FLEET</div></div></div>
    <nav class="nav">${NAV_GROUPS.map(g => html`<div key=${g.key} class="navgroup">
      <div class="navgh">${t('grp_' + g.key)}</div>
      ${g.items.map(k => html`<a key=${k} class=${route === k ? 'on' : ''} href=${'#/' + k}>
        <svg class="navico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" dangerouslySetInnerHTML=${{ __html: NAV_ICON[k] || '' }}></svg>
        <span>${t(VIEWS[k].label)}</span>${counts[k] != null ? html`<span class="cnt">${counts[k]}</span>` : null}</a>`)}
    </div>`)}</nav>
    <div class="railfoot"><span class="avatar">${(me.email || 'op')[0].toUpperCase()}</span>
      <div style=${{ minWidth: 0 }}><div style=${{ fontSize: '12px', fontWeight: 600 }}>${me.email || 'operator'}</div>
      <div style=${{ fontSize: '10.5px', color: 'var(--ink3)' }}>${me.role || ''}</div></div></div>
  </aside>`;
}

function App() {
  const { data, err, loading, reload } = useStatus();
  const route = useHashRoute('overview');
  const clock = useClock();
  const [, uiN] = useState(0);
  useEffect(() => { const h = () => uiN(n => n + 1); addEventListener('nfui', h); return () => removeEventListener('nfui', h); }, []);
  const d = useMemo(() => (data ? normalize(data) : null), [data]);
  useEffect(() => { const h = () => reload(); addEventListener('nfreload', h); return () => removeEventListener('nfreload', h); }, [reload]);

  if (err && !d) return html`<div class="errbox"><b>${t('Cannot reach the fleet API')}</b><div class="ink2">${err}</div><button class="retry" onClick=${reload}>${t('Retry')}</button></div>`;
  if (loading || !d) return html`<div class="loading"><div class="spin"></div>${t('Loading console…')}</div>`;

  const View = (VIEWS[route] || VIEWS.overview).comp;
  const counts = { security: (d.cve.findings.length + d.cert.findings.length) || null, governance: d.governance.denied || null };
  return html`<div class="app">
    <${NavRail} me=${d.me} route=${route} counts=${counts}/>
    <main class="main">
      <header class="top live">
        <div><h1>${t((VIEWS[route] || VIEWS.overview).label)}</h1>
          <div class="meta">${d.devices.length} ${t('managed devices')} · ${d.nodes.length} ${t('agent nodes')} · ${t('OPA / L7 governed')}</div></div>
        <div style=${{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: '12px' }}>
          <button class="hdrbtn" title="Language / 語言" onClick=${() => setLang(LANG === 'zh' ? 'en' : 'zh')}>${LANG === 'zh' ? 'EN' : '中'}</button>
          <button class="hdrbtn" title=${THEME === 'dark' ? 'Switch to light' : 'Switch to dark'} onClick=${() => setTheme(THEME === 'dark' ? 'light' : 'dark')}>${THEME === 'dark' ? '☀' : '🌙'}</button>
          <${ActionBtn} act="refresh" label="↻ Refresh" busyLabel="…" ghost=${true}/>
          <div class="fleetpill live">
            ${d.nodes.map(nd => html`<span key=${nd.name} class="seg nodeseg" title=${t('Node detail')} onClick=${() => openDrawer({ title: t('Node detail'), sub: nd.name, rows: [
              { k: t('name'), v: nd.name, mono: true }, { k: t('status'), v: nd.up ? '● ' + t('online') : '○ ' + t('offline') },
              { k: t('role'), v: nd.role || '—' }, { k: t('zone'), v: nd.zone || '—' }, { k: t('port'), v: ':' + nd.port, mono: true },
              { k: t('tag'), v: nd.tag || '—' }, { k: t('caps'), v: (nd.caps || []).join(', ') || '—' } ] })}><${Dot} up=${nd.up}/>${nd.name}</span>`)}
            <span class="seg">NIM · ${d.inference.model} <${Dot} up=${d.inference.reachable !== false}/></span>
            <span class="seg clock">${clock}</span>
          </div>
        </div>
      </header>
      <${ErrorBoundary} key=${route}><${View} d=${d}/></${ErrorBoundary}>
      <footer class="foot">
        <span>${t('Audit chain')} <b style=${{ color: d.audit.ok ? 'var(--good)' : 'var(--crit)' }}>${d.audit.ok ? t('✓ verified') : t('✗ broken')}</b> · <span class="mono">${(d.audit.count || 0).toLocaleString()} ${t('entries')}</span></span>
        <span style=${{ marginLeft: 'auto' }} class="mono">nemofleet · ${t('live every 5s')}${err ? ' · ' + t('reconnecting…') : ''}</span>
      </footer>
    </main>
  </div>`;
}

ReactDOM.createRoot(document.getElementById('root')).render(html`<${React.Fragment}><${App}/><${Toaster}/><${DrawerHost}/></${React.Fragment}>`);
