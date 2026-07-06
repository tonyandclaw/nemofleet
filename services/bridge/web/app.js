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
function statusBullet(ok, onLabel, offLabel) { return html`<span style=${{ color: ok ? 'var(--good)' : 'var(--ink3)', fontSize: '9px' }}>${ok ? '●' : '○'}</span> ${ok ? onLabel : offLabel}`; }
// CVE id → clickable NIST NVD detail page (real advisory, opens in a new tab)
function cveLink(id) { if (!id) return html`<span class="mono">—</span>`;
  return html`<a class="mono cvelink" href=${'https://nvd.nist.gov/vuln/detail/' + encodeURIComponent(id)} target="_blank" rel="noopener noreferrer" onClick=${e => e.stopPropagation()}>${id}</a>`; }
// CWE label ("CWE-78 command-injection") → link to the MITRE definition
function cweLink(cwe) { const m = /CWE-(\d+)/.exec(cwe || ''); if (!m) return html`<span class="mono">${cwe || '—'}</span>`;
  return html`<a class="mono cvelink" href=${'https://cwe.mitre.org/data/definitions/' + m[1] + '.html'} target="_blank" rel="noopener noreferrer" onClick=${e => e.stopPropagation()}>${cwe}</a>`; }
// SAST finding path → link to the exact file@commit#line on GitHub (r.url is the pinned permalink); shows the real repo path.
function ghFile(path, url) { if (!path) return html`<span class="mono">—</span>`;
  return url ? html`<a class="mono cvelink" style=${{ wordBreak: 'break-all' }} href=${url} target="_blank" rel="noopener noreferrer" onClick=${e => e.stopPropagation()}>${path}</a>`
    : html`<span class="mono" style=${{ wordBreak: 'break-all' }}>${path}</span>`; }
function fmtVal(v) { if (v == null || v === '') return '—'; if (Array.isArray(v)) return v.length ? v.map(fmtVal).join(', ') : '—'; if (typeof v === 'object') return JSON.stringify(v); return String(v); }
function rowDrawer(title, row) { openDrawer({ title, rows: Object.entries(row).filter(([k]) => k[0] !== '_').map(([k, v]) => ({ k, v: fmtVal(v), mono: true })) }); }
// Render a unified diff / patch with git-style colouring: '-' lines red, '+' lines green, hunks dim.
function diffLines(patch) {
  return String(patch || '').split('\n').map((ln, i) => {
    const c0 = ln.charAt(0);
    const cls = ln.startsWith('@@') ? 'hunk' : (ln.startsWith('+++') || ln.startsWith('---')) ? 'meta'
      : c0 === '+' ? 'add' : c0 === '-' ? 'del' : 'ctx';
    return html`<div key=${i} class=${'dl ' + cls}>${ln || ' '}</div>`;
  });
}
// SAST finding detail — real worker-b pattern-SAST hit against the asuswrt-merlin source.
function sastDrawer(r) {
  openDrawer({ title: t('SAST finding'), sub: r.cwe || 'CWE', node: html`<div class="sastdw">
    <div class="kv"><span class="kvk">CWE</span><span class="kvv">${cweLink(r.cwe)}</span></div>
    <div class="kv"><span class="kvk">${t('File')}</span><span class="kvv">${ghFile((r.upstream_path || r.file || '—') + (r.line ? ':' + r.line : ''), r.url)}</span></div>
    ${r.check_id ? html`<div class="kv"><span class="kvk">${t('Rule')}</span><span class="kvv mono">${r.check_id}${r.severity ? html` <span class="pill2 ${r.severity === 'ERROR' ? 'c' : 'w'}">${r.severity}</span>` : null}</span></div>` : null}
    ${r.message ? html`<div class="sastsec"><div class="lbl">${t('What Semgrep found')}</div><div class="muted" style=${{ fontSize: '12.5px', lineHeight: 1.5 }}>${r.message}</div></div>` : null}
    ${r.violates_design ? html`<div class="kv"><span class="kvk">${t('Design')}</span><span class="kvv"><span class="pill2 c">${t('violates approved baseline')}</span></span></div>` : null}
    ${r.code ? html`<div class="sastsec"><div class="lbl">${t('Matched code')}</div><pre class="codeblock mono">${r.code}</pre></div>` : null}
    ${r.patch ? html`<div class="sastsec"><div class="lbl" style=${{ display: 'flex', alignItems: 'center', gap: '7px' }}>${t('Suggested patch')}${r.patch_verified
        ? html`<span class="pill2 g">${t('verified — sink removed')}</span>` : html`<span class="pill2 w">${t('advisory — needs human review')}</span>`}</div>
      <pre class="diffblock mono">${diffLines(r.patch)}</pre></div>` : null}
    ${r.remediation ? html`<div class="sastsec"><div class="lbl">${t('Remediation')}</div><div class="muted" style=${{ fontSize: '12.5px', lineHeight: 1.5 }}>${(r.remediation && typeof r.remediation === 'object')
      ? html`${r.remediation.risk ? html`<div><b>${t('Risk')}:</b> ${r.remediation.risk}</div>` : null}${r.remediation.fix ? html`<div style=${{ marginTop: '5px' }}><b>${t('Fix')}:</b> ${r.remediation.fix}</div>` : null}${r.remediation.ref ? html`<div style=${{ marginTop: '5px' }}><a class="cvelink" href=${r.remediation.ref} target="_blank" rel="noopener noreferrer">${r.remediation.ref}</a></div>` : null}`
      : r.remediation}</div></div>` : null}
  </div>` });
}
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
  'cve_interval_sec': { en: 'CVE scan interval', zh: 'CVE 掃描間隔' },
  'cert_interval_sec': { en: 'Cert scan interval', zh: '憑證掃描間隔' },
  'nuclei_interval_sec': { en: 'Nuclei scan interval', zh: 'Nuclei 掃描間隔' },
  'cert_rsa_min': { en: 'Min RSA bits', zh: 'RSA 最小位元' },
  'cert_ec_min': { en: 'Min ECDSA curve', zh: 'ECDSA 最小曲線' },
  'cert_sig_min': { en: 'Min signature alg', zh: '簽章演算法下限' },
  'cert_expire_warn_days': { en: 'Cert expiry warning', zh: '憑證到期提醒' },
  'cert_cipher_policy': { en: 'Cipher policy', zh: '加密套件政策' },
  'dev_cpu_hi': { en: 'Device CPU alert', zh: '設備 CPU 告警' },
  'dev_ram_hi': { en: 'Device RAM alert', zh: '設備 RAM 告警' },
  'dev_temp_hi': { en: 'Device temp alert', zh: '設備溫度告警' },
  'patrol_interval_sec': { en: 'Patrol interval', zh: '巡邏間隔' },
  'digest_interval_sec': { en: 'Digest interval', zh: '摘要間隔' },
  'quiet_start': { en: 'Quiet start', zh: '靜音開始' },
  'quiet_end': { en: 'Quiet end', zh: '靜音結束' },
  'quiet_enabled': { en: 'Quiet hours', zh: '靜音時段' },
  'nuclei_tags': { en: 'Nuclei tags', zh: 'Nuclei 標籤' },
  'proactive_enabled': { en: 'Proactive patrol', zh: '主動巡邏' },
  'proactive_safety_net': { en: 'Safety net', zh: '安全網' },
  'auto_escalate': { en: 'Auto-open Jira', zh: '自動開 Jira' },
  'worker-b CVE scan cadence': { en: 'worker-b CVE scan cadence', zh: 'worker-b 掃 CVE 的頻率' },
  'worker-a cert/crypto cadence': { en: 'worker-a cert/crypto cadence', zh: 'worker-a 掃憑證/加密的頻率' },
  'min RSA key bits': { en: 'min RSA key bits', zh: 'RSA 金鑰最小位元數' },
  'min ECDSA curve': { en: 'min ECDSA curve', zh: 'ECDSA 最小曲線強度' },
  'min signature alg': { en: 'min signature alg', zh: '可接受的最弱簽章演算法' },
  'expiry lead-time (days)': { en: 'expiry lead-time (days)', zh: '到期前幾天預警' },
  'cipher flagging policy': { en: 'cipher flagging policy', zh: '標記弱加密的政策' },
  'CPU %': { en: 'CPU %', zh: 'CPU 使用率 %' },
  'RAM %': { en: 'RAM %', zh: 'RAM 使用率 %' },
  'Temp °C': { en: 'Temp °C', zh: '溫度 °C' },
  'No governance events in this window': { en: 'No governance events in this window', zh: '此時段無治理事件' },
  'Email': { en: 'Email', zh: 'Email' },
  'Password': { en: 'Password', zh: '密碼' },
  'current': { en: 'current', zh: '目前' },
  'not available': { en: 'not available', zh: '無法取得(需設備連線)' },
  'chain verified': { en: 'chain verified', zh: '雜湊鏈已驗證' },
  'chain broken': { en: 'chain broken', zh: '雜湊鏈損毀' },
  'Search actor / action / detail…': { en: 'Search actor / action / detail…', zh: '搜尋帳號 / 動作 / 細節…' },
  'Admin only.': { en: 'Admin only.', zh: '僅限管理員。' },
  'Filter services…': { en: 'Filter services…', zh: '篩選服務…' },
  'Editing policy for': { en: 'Editing policy for', zh: '正在編輯的沙箱' },
  'Inference detail': { en: 'Inference detail', zh: '推理詳情' },
  'model': { en: 'model', zh: '模型' },
  'provider': { en: 'provider', zh: '供應商' },
  'reachable': { en: 'reachable', zh: '可達' },
  'unreachable': { en: 'unreachable', zh: '不可達' },
  'endpoint': { en: 'endpoint', zh: '端點' },
  'No snapshots yet — click Create.': { en: 'No snapshots yet — click Create.', zh: '尚無快照 — 點「建立快照」。' },
  'No backups yet (needs device + EBG19P_CRED).': { en: 'No backups yet (needs device + EBG19P_CRED).', zh: '尚無備份(需真機 + EBG19P_CRED)。' },
  'No review verdicts yet (worker-c not deployed / no delegation).': { en: 'No review verdicts yet (worker-c not deployed / no delegation).', zh: '尚無審查判決(worker-c 未部署或尚無委派)。' },
  'No patrol log yet (loop idle or just started).': { en: 'No patrol log yet (loop idle or just started).', zh: '尚無巡邏記錄(loop 未跑或剛啟動)。' },
  'No workflow events yet — appear after a delegation/scan (team-lead → worker → status).': { en: 'No workflow events yet — appear after a delegation/scan (team-lead → worker → status).', zh: '尚無工作流事件 — 委派 / 掃描觸發後會出現(team-lead → worker → 狀態)。' },
  'No skill-curation verdicts yet (worker-c not deployed).': { en: 'No skill-curation verdicts yet (worker-c not deployed).', zh: '尚無技能治理判決(worker-c 未部署或無 insert/update/delete)。' },
  'deterministic critical alerts (independent of team-lead)': { en: 'deterministic critical alerts (independent of team-lead)', zh: 'critical 確定性告警(不靠 team-lead)' },
  'team-lead active patrol + reporting': { en: 'team-lead active patrol + reporting', zh: 'team-lead 主動巡邏 + 主動回報' },
  'enable quiet hours': { en: 'enable quiet hours', zh: '啟用靜音時段' },
  'mute proactive interrupts during maintenance (still patrols + logs)': { en: 'mute proactive interrupts during maintenance (still patrols + logs)', zh: '維護時暫時靜音主動打斷(仍巡邏+記錄)' },
  'comma-separated (asus,cve,exposure…)': { en: 'comma-separated (asus,cve,exposure…)', zh: '逗號分隔(asus,cve,exposure…)' },
  'quality gate on a/b output · reject = binding redo': { en: 'quality gate on a/b output · reject = binding redo', zh: 'a/b 產出的品質閘 · reject 綁定重做' },
  'drift · CVE · nuclei · cert fused into one score': { en: 'drift · CVE · nuclei · cert fused into one score', zh: 'drift · CVE · nuclei · cert 融合成一個分數' },
  'team-lead active patrol': { en: 'team-lead active patrol', zh: 'team-lead 主動巡邏' },
  'worker-a quick actions (needs device link)': { en: 'worker-a quick actions (needs device link)', zh: 'worker-a 快速處置(需設備連線)' },
  'switch provider / model (nemoclaw inference set)': { en: 'switch provider / model (nemoclaw inference set)', zh: '切換 provider / model(nemoclaw inference set)' },
  'skill-repo governance · arXiv 2605.06614': { en: 'skill-repo governance · arXiv 2605.06614', zh: '技能庫治理 · arXiv 2605.06614' },
  'recent patrols · delta events': { en: 'recent patrols · delta events', zh: '最近巡邏 · delta 事件' },
  'recent delegations / handoffs (peer → node)': { en: 'recent delegations / handoffs (peer → node)', zh: '最近的委派 / 交接 (peer → node)' },
  'families flagged as weak (active when cert_cipher_policy=custom)': { en: 'families flagged as weak (active when cert_cipher_policy=custom)', zh: '標記為弱加密的家族(cert_cipher_policy=custom 時生效)' },
  'working nodes light up': { en: 'working nodes light up', zh: '正在工作的節點會亮起' },
  'lifecycle · urgency driven by CVEs': { en: 'lifecycle · urgency driven by CVEs', zh: '生命週期 · urgency 由 CVE 驅動' },
  'quiet hours (critical still pushed) + nuclei scope': { en: 'quiet hours (critical still pushed) + nuclei scope', zh: '靜音時段(critical 仍推)+ nuclei 範圍' },
  'Sync settings': { en: 'Sync settings', zh: '同步設定' },
  'Harden': { en: 'Harden', zh: '一鍵強化' },
  'Restart services': { en: 'Restart services', zh: '重啟服務' },
  'Block unauthorized': { en: 'Block unauthorized', zh: '封鎖未授權' },
  'run against the real EBG19P, confirm?': { en: 'run against the real EBG19P, confirm?', zh: '對真實 EBG19P 執行,確定?' },
  'Off-net → graceful \'unreachable\'; every action audited.': { en: 'Off-net → graceful \'unreachable\'; every action audited.', zh: '設備不在網段時回「不可達」的優雅降級;每筆進稽核。' },
  'Config drift': { en: 'Config drift', zh: '設定安全退化 (drift)' },
  'Cert/crypto high-risk': { en: 'Cert/crypto high-risk', zh: '憑證/加密高風險' },
  'No penalties — fleet posture is healthy ✓': { en: 'No penalties — fleet posture is healthy ✓', zh: '無扣分項 — 機隊安全姿態良好 ✓' },
  'Set cipher policy to': { en: 'Set cipher policy to', zh: '先到 Settings 把 cipher policy 設成' },
  'in Settings; per-family flag/clear applies live to worker-a.': { en: 'in Settings; per-family flag/clear applies live to worker-a.', zh: ';個別家族開/關即時套用到 worker-a 掃描。' },
  'rebuilds the sandbox.': { en: 'rebuilds the sandbox.', zh: '會 rebuild 沙箱。' },
  'rebuilds the sandbox (keeps credentials).': { en: 'rebuilds the sandbox (keeps credentials).', zh: '會 rebuild 沙箱(保留憑證)。' },
  'Stop/Start rebuilds the sandbox; credentials are kept.': { en: 'Stop/Start rebuilds the sandbox; credentials are kept.', zh: 'Stop/Start 會 rebuild 沙箱;憑證保留。' },
  'rebuilds the sandbox (minutes; custom policy must be re-applied via boot-stack).': { en: 'rebuilds the sandbox (minutes; custom policy must be re-applied via boot-stack).', zh: '會重建沙箱(數分鐘;自訂 policy 之後需 boot-stack 重補)。' },
  'Switch inference of': { en: 'Switch inference of', zh: '把推理切換 ·' },
  'on · guaranteed delivery': { en: 'on · guaranteed delivery', zh: 'on · 保證送達' },
  'Events': { en: 'Events', zh: '事件' },
  'Sent': { en: 'Sent', zh: '送出' },
  'who delegated whom · live': { en: 'who delegated whom · live', zh: '誰委派誰、正在做什麼 · 即時' },
  'worker-c · change-governance · zone C': { en: 'worker-c · change-governance · zone C', zh: 'worker-c · 變更治理官 · zone C' },
  'rejected → sent back': { en: 'rejected → sent back', zh: 'rejected → 退回重做' },
  'worker-c not deployed': { en: 'worker-c not deployed', zh: 'worker-c 未部署' },
  'worker-b nuclei active scan (nuclei-templates)': { en: 'worker-b nuclei active scan (nuclei-templates)', zh: 'worker-b nuclei 主動掃 (nuclei-templates)' },
  'proactive patrol cadence': { en: 'proactive patrol cadence', zh: '主動巡邏頻率' },
  'proactive digest cadence': { en: 'proactive digest cadence', zh: '主動 digest 頻率' },
  'quiet start': { en: 'quiet start', zh: '靜音開始' },
  'quiet end': { en: 'quiet end', zh: '靜音結束' },
  'worker-c reviews worker-a remediations + worker-b CVE decisions against the approved baseline. reject → team-lead re-dispatches with required_fixes; 2 fails → escalate to human. human > worker-c > a/b.': { en: 'worker-c reviews worker-a remediations + worker-b CVE decisions against the approved baseline. reject → team-lead re-dispatches with required_fixes; 2 fails → escalate to human. human > worker-c > a/b.', zh: 'worker-c 審 worker-a remediation + worker-b CVE 決策,錨定核准 baseline。reject → team-lead 帶 required_fixes 退回重做,2 次不過升級人。人 > worker-c > a/b。' },
  'CVE-driven: worker-b flags': { en: 'CVE-driven: worker-b flags', zh: 'CVE-driven:worker-b 判' },
  '(firmware update can fix)': { en: '(firmware update can fix)', zh: '(韌體更新可修)' },
  'Set a new password': { en: 'Set a new password', zh: '設定新密碼' },
  'First sign-in — please replace the temporary password before continuing.': { en: 'First sign-in — please replace the temporary password before continuing.', zh: '首次登入 — 請先更換臨時密碼再繼續。' },
  'New password': { en: 'New password', zh: '新密碼' },
  'Confirm password': { en: 'Confirm password', zh: '確認密碼' },
  'Password must be at least 8 characters.': { en: 'Password must be at least 8 characters.', zh: '密碼至少需 8 個字元。' },
  'Passwords do not match.': { en: 'Passwords do not match.', zh: '兩次密碼不一致。' },
  'Password changed': { en: 'Password changed', zh: '密碼已變更' },
  'Set password': { en: 'Set password', zh: '設定密碼' },
  'Saving…': { en: 'Saving…', zh: '儲存中…' },
  'Failed': { en: 'Failed', zh: '失敗' },
  'clean': { en: 'clean', zh: '無警示' },
  'weak certificate / crypto warning(s)': { en: 'weak certificate / crypto warning(s)', zh: '個憑證 / 加密弱點警示' },
  'weak cipher / expiring / untrusted — worker-a flags these against the crypto baseline': { en: 'weak cipher / expiring / untrusted — worker-a flags these against the crypto baseline', zh: '弱加密 / 即將到期 / 不受信任 — worker-a 依加密基準標記' },
  'high': { en: 'high', zh: '高' },
  'medium': { en: 'medium', zh: '中' },
  'Architecture': { en: 'Architecture', zh: '架構' },
  'Nemoclaw × OpenShell × Hermes · governed 4-node fleet': { en: 'Nemoclaw × OpenShell × Hermes · governed 4-node fleet', zh: 'Nemoclaw × OpenShell × Hermes · 受治理四節點艦隊' },
  'Topology': { en: 'Topology', zh: '拓撲' },
  'human at the apex · hub-and-spoke': { en: 'human at the apex · hub-and-spoke', zh: '人在最頂端 · hub-and-spoke' },
  'Human': { en: 'Human', zh: '人' },
  'request': { en: 'request', zh: '需求' },
  'report / escalate': { en: 'report / escalate', zh: '回報 / 升級' },
  'front desk · coordinate · execute worker-c verdicts': { en: 'front desk · coordinate · execute worker-c verdicts', zh: '對人前台 · 協調 · 執行 worker-c 判決' },
  'scoped egress · L7 deny-by-default': { en: 'scoped egress · L7 deny-by-default', zh: 'scoped 出向 · L7 預設全拒' },
  'real device': { en: 'real device', zh: '真實設備' },
  'upstream intel': { en: 'upstream intel', zh: '上游情資' },
  'escalations': { en: 'escalations', zh: '升級工單' },
  'local NIM': { en: 'local NIM', zh: '本地 NIM' },
  'all nodes route here': { en: 'all nodes route here', zh: '四節點都路由到這' },
  'The four layers': { en: 'The four layers', zh: '四層架構' },
  'what each does': { en: 'what each does', zh: '各層職責' },
  'host control plane': { en: 'host control plane', zh: 'host 控制面' },
  'provisioning · model/route/policy strategy · points inference at local NIM': { en: 'provisioning · model/route/policy strategy · points inference at local NIM', zh: '開機編排 · 模型/路由/政策 strategy · 指向本地 NIM' },
  'sandbox + governance': { en: 'sandbox + governance', zh: '沙箱 + 治理' },
  'per-agent sandbox · policy.yaml (egress/binaries/host) · deny-by-default · worker_bridge /32 + token': { en: 'per-agent sandbox · policy.yaml (egress/binaries/host) · deny-by-default · worker_bridge /32 + token', zh: '每 agent 一沙箱 · policy.yaml(出向/binary/host)· 預設全拒 · worker_bridge /32 + token' },
  'agent harness × 4': { en: 'agent harness × 4', zh: 'agent harness × 4' },
  'same harness, different roles: team-lead + worker-a/b/c; skills = SKILL.md; workers run :9099 IT-ops': { en: 'same harness, different roles: team-lead + worker-a/b/c; skills = SKILL.md; workers run :9099 IT-ops', zh: '同一 harness、不同角色:team-lead + worker-a/b/c;技能 = SKILL.md;worker 跑 :9099 IT-ops' },
  'local inference': { en: 'local inference', zh: '本地推理' },
  'Nemotron 3 Super 120B (NVFP4) · OpenAI /v1 · all 4 nodes route here · provider-agnostic seam': { en: 'Nemotron 3 Super 120B (NVFP4) · OpenAI /v1 · all 4 nodes route here · provider-agnostic seam', zh: 'Nemotron 3 Super 120B(NVFP4)· OpenAI /v1 · 四節點共用 · provider-agnostic' },
  'Governance invariants': { en: 'Governance invariants', zh: '治理不變量' },
  'always true': { en: 'always true', zh: '恆真' },
  'Authority: human > worker-c > worker-a/b — worker-c reject is binding; its firmware-apply/rollback need a human token.': { en: 'Authority: human > worker-c > worker-a/b — worker-c reject is binding; its firmware-apply/rollback need a human token.', zh: '權威:人 > worker-c > worker-a/b — worker-c 的 reject 綁定;它的 firmware-apply/rollback 需人核准 token。' },
  'Hub-and-spoke — workers never talk to each other; supervision is arbitrated via team-lead.': { en: 'Hub-and-spoke — workers never talk to each other; supervision is arbitrated via team-lead.', zh: 'Hub-and-spoke — worker 之間不互連;監督透過 team-lead 仲裁。' },
  'Only cross-agent channel — worker_bridge (/32 + X-Bridge-Token) → :9099; A2A rides the same governed channel.': { en: 'Only cross-agent channel — worker_bridge (/32 + X-Bridge-Token) → :9099; A2A rides the same governed channel.', zh: '唯一跨 agent 通道 — worker_bridge(/32 + X-Bridge-Token)→ :9099;A2A 走同一條受治理通道。' },
  'Single source of knowledge — knowledge/ (approved baseline + security keys); version-hash aligned fleet-wide.': { en: 'Single source of knowledge — knowledge/ (approved baseline + security keys); version-hash aligned fleet-wide.', zh: '知識單一權威 — knowledge/(核准 baseline + 安全鍵);version-hash 全隊對齊。' },
  'Governed self-evolution — new skills pass worker-c /skill-review (SkillOS quality gate) before landing.': { en: 'Governed self-evolution — new skills pass worker-c /skill-review (SkillOS quality gate) before landing.', zh: '受治理自我進化 — 新技能落地前過 worker-c /skill-review(SkillOS 品質閘)。' },
  'per-family weak-crypto flags': { en: 'per-family weak-crypto flags', zh: '逐一標記弱加密套件' },
  'flagged': { en: 'flagged', zh: '已標記' },
  'policy: ': { en: 'policy: ', zh: '政策:' },
  'Custom policy is live': { en: 'Custom policy is live', zh: '自訂政策已生效' },
  'Active policy': { en: 'Active policy', zh: '目前政策' },
  'worker-a flags the families switched on below on its next cert scan.': { en: 'worker-a flags the families switched on below on its next cert scan.', zh: 'worker-a 下次憑證掃描時會把下方開啟的套件標為弱。' },
  'These per-family flags only bite when the cipher policy is set to custom — change it in Settings → Certificate & crypto.': { en: 'These per-family flags only bite when the cipher policy is set to custom — change it in Settings → Certificate & crypto.', zh: '這些逐項標記只有在加密政策設為 custom 時才生效 — 到「設定 → 憑證與加密」切換。' },
  'flagged as weak — click to allow': { en: 'flagged as weak — click to allow', zh: '已標為弱 — 點擊改為允許' },
  'allowed — click to flag as weak': { en: 'allowed — click to flag as weak', zh: '允許中 — 點擊標為弱' },
  'weak': { en: 'weak', zh: '弱' },
  'allowed': { en: 'allowed', zh: '允許' },
  'Biased keystream → plaintext recovery': { en: 'Biased keystream → plaintext recovery', zh: '金鑰流有偏差 → 可還原明文' },
  'Stream cipher with keystream biases; RFC 7465 prohibits it in TLS. Enables cookie / plaintext recovery — considered broken in practice since 2013.': { en: 'Stream cipher with keystream biases; RFC 7465 prohibits it in TLS. Enables cookie / plaintext recovery — considered broken in practice since 2013.', zh: '串流加密、金鑰流有統計偏差;RFC 7465 已在 TLS 禁用。可還原 cookie / 明文 — 2013 年起實務上視為破解。' },
  '64-bit block → Sweet32 birthday attack': { en: '64-bit block → Sweet32 birthday attack', zh: '64-bit 區塊 → Sweet32 生日攻擊' },
  'CVE-2016-2183 (Sweet32): a birthday attack recovers plaintext from long-lived connections. NIST disallowed 3DES for TLS after 2023.': { en: 'CVE-2016-2183 (Sweet32): a birthday attack recovers plaintext from long-lived connections. NIST disallowed 3DES for TLS after 2023.', zh: 'CVE-2016-2183(Sweet32):生日攻擊可從長連線還原明文。NIST 於 2023 後禁止 3DES 用於 TLS。' },
  '56-bit key → brute-forceable': { en: '56-bit key → brute-forceable', zh: '56-bit 金鑰 → 可暴力破解' },
  'Single DES has a 56-bit key, exhaustible with modest hardware in hours. Never acceptable for transport security.': { en: 'Single DES has a 56-bit key, exhaustible with modest hardware in hours. Never acceptable for transport security.', zh: '單 DES 金鑰僅 56-bit,一般硬體數小時即可窮舉。傳輸安全上絕不可接受。' },
  'No encryption → cleartext on the wire': { en: 'No encryption → cleartext on the wire', zh: '不加密 → 明文傳輸' },
  'eNULL suites authenticate the peer but do not encrypt; the payload travels in the clear.': { en: 'eNULL suites authenticate the peer but do not encrypt; the payload travels in the clear.', zh: 'eNULL 套件只驗證對端但不加密;內容以明文傳送。' },
  '40/512-bit → FREAK / Logjam downgrade': { en: '40/512-bit → FREAK / Logjam downgrade', zh: '40/512-bit → FREAK / Logjam 降級' },
  '1990s export-grade crypto. FREAK (CVE-2015-0204) and Logjam force a downgrade to key sizes that are broken offline.': { en: '1990s export-grade crypto. FREAK (CVE-2015-0204) and Logjam force a downgrade to key sizes that are broken offline.', zh: '1990 年代出口級加密。FREAK(CVE-2015-0204)與 Logjam 會強制降級到可離線破解的金鑰長度。' },
  'MD5 MAC → collision-broken hash': { en: 'MD5 MAC → collision-broken hash', zh: 'MD5 MAC → 雜湊已可碰撞' },
  'Record MAC built on MD5. MD5 is collision-broken and unfit for message integrity.': { en: 'Record MAC built on MD5. MD5 is collision-broken and unfit for message integrity.', zh: '以 MD5 建的紀錄 MAC。MD5 已可碰撞,不適合做訊息完整性。' },
  'SHA-1 MAC → deprecated hash': { en: 'SHA-1 MAC → deprecated hash', zh: 'SHA-1 MAC → 已淘汰雜湊' },
  'HMAC-SHA1 record MAC. SHA-1 is deprecated (SHATTERED collision, 2017) and being removed from TLS.': { en: 'HMAC-SHA1 record MAC. SHA-1 is deprecated (SHATTERED collision, 2017) and being removed from TLS.', zh: 'HMAC-SHA1 紀錄 MAC。SHA-1 已淘汰(2017 SHATTERED 碰撞),正從 TLS 移除。' },
  'No server authentication → trivial MITM': { en: 'No server authentication → trivial MITM', zh: '無伺服器驗證 → 易遭中間人' },
  'Anonymous (A)DH / (A)ECDH suites skip peer authentication, so an active attacker MITMs the handshake undetected.': { en: 'Anonymous (A)DH / (A)ECDH suites skip peer authentication, so an active attacker MITMs the handshake undetected.', zh: '匿名 (A)DH / (A)ECDH 套件跳過對端驗證,主動攻擊者可無聲中間人握手。' },
  'Legacy 64-bit block cipher': { en: 'Legacy 64-bit block cipher', zh: '舊式 64-bit 區塊加密' },
  'Not broken, but a legacy 64-bit-block cipher. Flagged under strict cipher-suite hygiene.': { en: 'Not broken, but a legacy 64-bit-block cipher. Flagged under strict cipher-suite hygiene.', zh: '未被破解,但屬舊式 64-bit 區塊加密。在嚴格套件衛生政策下標記。' },
  'Regional legacy cipher': { en: 'Regional legacy cipher', zh: '區域性舊式加密' },
  'Korean legacy block cipher; non-standard for modern TLS. Flagged only under a strict minimal-suite policy.': { en: 'Korean legacy block cipher; non-standard for modern TLS. Flagged only under a strict minimal-suite policy.', zh: '韓國舊式區塊加密;非現代 TLS 標準。僅在嚴格最小套件政策下標記。' },
  'Sound but non-preferred vs AES': { en: 'Sound but non-preferred vs AES', zh: '安全但不如 AES 優先' },
  'Cryptographically sound but not preferred over AES; flagged only when you want a strictly minimal cipher suite.': { en: 'Cryptographically sound but not preferred over AES; flagged only when you want a strictly minimal cipher suite.', zh: '密碼學上安全但不比 AES 優先;僅在你要嚴格最小套件時標記。' },
  'asset': { en: 'asset', zh: '資產' },
  'firmware': { en: 'firmware', zh: '韌體' },
  'CPU': { en: 'CPU', zh: 'CPU' },
  'MEM': { en: 'MEM', zh: 'MEM' },
  'TEMP': { en: 'TEMP', zh: 'TEMP' },
  'who is working, and on what': { en: 'who is working, and on what', zh: '誰在忙 · 在做什麼' },
  'working': { en: 'working', zh: '進行中' },
  'idle': { en: 'idle', zh: '閒置' },
  'started': { en: 'started', zh: '開始於' },
  'no activity yet': { en: 'no activity yet', zh: '尚無活動' },
  'control plane · provisions the sandboxes · policy · routes inference': { en: 'control plane · provisions the sandboxes · policy · routes inference', zh: '控制面 · 佈建各沙箱 · 政策 · 路由推理' },
  'needed': { en: 'needed', zh: '需要' },
  'revoke recommended': { en: 'revoke recommended', zh: '建議收回' },
  'review': { en: 'review', zh: '待審' },
  'binaries': { en: 'binaries', zh: '可執行檔' },
  'Filesystem': { en: 'Filesystem', zh: '檔案系統' },
  'default (deny-by-default)': { en: 'default (deny-by-default)', zh: '預設(全拒)' },
  'service(s) recommended to revoke': { en: 'service(s) recommended to revoke', zh: '個服務建議收回' },
  '— a default preset this agent’s job doesn’t use': { en: '— a default preset this agent’s job doesn’t use', zh: '— 此 agent 工作用不到的預設 preset' },
  'Lean': { en: 'Lean', zh: '精簡' },
  '— every service maps to this agent’s job': { en: '— every service maps to this agent’s job', zh: '— 每個服務都對得上此 agent 的職責' },
  'to review (base-image config / maybe needed)': { en: 'to review (base-image config / maybe needed)', zh: '待審(base image 設定 / 可能需要)' },
  'SAST finding': { en: 'SAST finding', zh: 'SAST 原始碼命中' },
  'Design': { en: 'Design', zh: '設計' },
  'violates approved baseline': { en: 'violates approved baseline', zh: '違反核准基準' },
  'Matched code': { en: 'Matched code', zh: '命中的程式碼' },
  'Suggested patch': { en: 'Suggested patch', zh: '建議修補' },
  'verified — sink removed': { en: 'verified — sink removed', zh: '已驗證 — sink 已消除' },
  'advisory — needs human review': { en: 'advisory — needs human review', zh: '建議 — 需人工審查' },
  'Remediation': { en: 'Remediation', zh: '修補說明' },
  'Policy tier': { en: 'Policy tier', zh: '政策層級' },
  'same setting as Settings → Certificate & crypto': { en: 'same setting as Settings → Certificate & crypto', zh: '與「設定 → 憑證與加密」同一項' },
  'Custom — edit each family below': { en: 'Custom — edit each family below', zh: '自訂 — 逐一編輯下方套件' },
  'Tier': { en: 'Tier', zh: '層級' },
  'This tier flags the families highlighted below. Switch to custom to edit them individually.': { en: 'This tier flags the families highlighted below. Switch to custom to edit them individually.', zh: '此層級會標記下方反白的套件。切到 custom 才能逐項編輯。' },
  'set by the tier — switch to custom to edit': { en: 'set by the tier — switch to custom to edit', zh: '由層級決定 — 切到 custom 才能編輯' },
  'Source of truth': { en: 'Source of truth', zh: '原始碼來源' },
  'not synced': { en: 'not synced', zh: '未同步' },
  'Set SAST source to': { en: 'Set SAST source to', zh: '將 SAST 原始碼來源設為' },
  'Sync & scan': { en: 'Sync & scan', zh: '同步並掃描' },
  'source updated — re-syncing': { en: 'source updated — re-syncing', zh: '來源已更新 — 重新同步中' },
  'worker-b syncs the pinned ref and scans it — a GitHub repo or a folder mounted into the sandbox. No demo fallback: if it can’t sync, it says so.': { en: 'worker-b syncs the pinned ref and scans it — a GitHub repo or a folder mounted into the sandbox. No demo fallback: if it can’t sync, it says so.', zh: 'worker-b 同步釘死的 ref 再掃描 —— GitHub repo 或掛載進沙箱的資料夾。無 demo 退回:同步不到就明說。' },
  'No SAST hits — configure a source above, or the pinned ref is clean.': { en: 'No SAST hits — configure a source above, or the pinned ref is clean.', zh: '無 SAST 命中 — 於上方設定來源,或釘死的 ref 本身乾淨。' },
  'Risk': { en: 'Risk', zh: '風險' },
  'Fix': { en: 'Fix', zh: '修法' },
  'packages': { en: 'packages', zh: '元件' },
  'Version': { en: 'Version', zh: '版本' },
  'No SBOM — configure a source in SAST below.': { en: 'No SBOM — configure a source in SAST below.', zh: '無 SBOM — 於下方 SAST 設定來源。' },
  'violate baseline': { en: 'violate baseline', zh: '違反基準' },
  'patch verified': { en: 'patch verified', zh: '修補已驗證' },
  'click a row for code + patch + fix': { en: 'click a row for code + patch + fix', zh: '點一列看程式碼 + patch + 修法' },
  'Rule': { en: 'Rule', zh: '規則' },
  'What Semgrep found': { en: 'What Semgrep found', zh: 'Semgrep 判定' },
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
function PwGate({ me }) {
  const [pw, setPw] = useState(''); const [pw2, setPw2] = useState(''); const [busy, setBusy] = useState(false); const [err, setErr] = useState('');
  if (!me || !me.must_change) return null;
  const submit = async () => {
    if (pw.length < 8) return setErr(t('Password must be at least 8 characters.'));
    if (pw !== pw2) return setErr(t('Passwords do not match.'));
    setBusy(true); setErr('');
    try { const r = await NF.users({ op: 'pw', email: me.email, password: pw }); if (r && r.ok) { toast(t('Password changed'), 'g'); reloadNow(); } else { setErr((r && r.msg) || t('Failed')); } }
    catch (e) { setErr(e.message); } finally { setBusy(false); }
  };
  return html`<div class="modal-scrim"><div class="modal">
    <h3>${t('Set a new password')}</h3>
    <p class="muted" style=${{ fontSize: '13px', marginTop: '4px' }}>${t('First sign-in — please replace the temporary password before continuing.')}</p>
    <label class="fld" style=${{ marginTop: '14px' }}><span>${t('New password')}</span><input class="inp" type="password" autofocus value=${pw} onInput=${e => setPw(e.target.value)}/></label>
    <label class="fld" style=${{ marginTop: '10px' }}><span>${t('Confirm password')}</span><input class="inp" type="password" value=${pw2} onInput=${e => setPw2(e.target.value)} onKeyDown=${e => e.key === 'Enter' && submit()}/></label>
    ${err ? html`<div style=${{ color: 'var(--crit)', fontSize: '12.5px', marginTop: '10px' }}>${err}</div>` : null}
    <button class="btn" style=${{ marginTop: '16px', width: '100%' }} disabled=${busy} onClick=${submit}>${busy ? t('Saving…') : t('Set password')}</button>
  </div></div>`;
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
      <div class="drawer-bd"><${ErrorBoundary}>${dw.node ? dw.node : (dw.rows || []).map((r, i) => html`<div key=${i} class="kv"><span class="kvk">${r.k}</span><span class=${'kvv ' + (r.mono ? 'mono' : '')}>${r.v == null || r.v === '' ? '—' : r.v}</span></div>`)}</${ErrorBoundary}></div>
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
const Dot = ({ up, s }) => { const cls = s === 'on' ? 'g' : s === 'off' ? 'off' : s === 'down' ? 'c' : s ? s : (up ? 'g' : 'c'); return html`<span class=${'dot ' + cls}></span>`; };

const Panel = memo(function Panel({ title, label, right, children, className }) {
  return html`<section class=${'panel ' + (className || '')}>
    <div class="ph"><h3>${t(title)}</h3>${label ? html`<span class="lbl">${t(label)}</span>` : null}
      ${right ? html`<div class="r">${right}</div>` : null}</div>
    <div class="pb">${children}</div></section>`;
});

const Kpi = memo(function Kpi({ stripe, label, big, unit, sub, trend }) {
  return html`<div class="kpi"><span class="stripe" style=${{ background: stripe }}></span>
    <div class="khead"><div class="lbl">${t(label)}</div>${trend != null ? html`<span class=${'ktrend ' + (trend >= 0 ? 'up' : 'dn')}>${trend >= 0 ? '↑' : '↓'} ${Math.abs(trend)}%</span>` : null}</div>
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
      <tbody>${slice.map((row, i) => html`<tr key=${i} class="clickrow" onClick=${() => (onRow ? onRow(row) : rowDrawer(drawerTitle || 'Detail', row))}>${cols.map(c => html`<td key=${c.k} class=${c.cls || ''} style=${c.align ? { textAlign: c.align } : null}>${c.render ? c.render(row) : row[c.k]}</td>`)}</tr>`)}</tbody>
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
  const empty = !gov.allowed && !(gov.series_allowed && gov.series_allowed.some(v => v));
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
  const _emptyOverlay = empty ? html`<div class="chartempty">${t('No governance events in this window')}</div>` : null;
  useEffect(() => { if (chart.current) { chart.current.data.datasets[0].data = data; chart.current.update('none'); } }, [gov.allowed, gov.series_allowed]);
  return html`<div class="chartbox">${_emptyOverlay}<canvas ref=${ref} aria-label="Allowed governance events over time"></canvas></div>`;
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
        { k: t('name'), v: n.name, mono: true }, { k: t('role'), v: n.role }, { k: t('zone'), v: n.zone || '—' }, { k: t('port'), v: ':' + n.port, mono: true },
        { k: t('status'), v: statusBullet(n.up, t('online'), t('offline')) }, { k: t('tag'), v: n.tag }, { k: t('caps'), v: (n.caps || []).join(', ') || '—' } ] })}>
      <span class="ico"><svg viewBox="0 0 24 24"><circle cx="12" cy="8" r="3.4" fill="none" stroke="currentColor" stroke-width="1.7"/><path d="M5 20c0-3.6 3.1-6 7-6s7 2.4 7 6" fill="none" stroke="currentColor" stroke-width="1.7"/></svg></span>
      <div><div class="nm">${n.name} <span class=${'tag ' + (n.tag === 'lead' ? 'a' : 'g')}>${t(n.tag)}</span></div><div class="role">${n.role}</div></div>
      <div class="rt"><${Dot} s=${n.up ? 'on' : 'off'}/> :${n.port}<br/><span class="muted">${n.zone || ''}</span></div>
    </div>`)}</div>
    <hr class="sep" style=${{ margin: '14px 0 12px' }}/>
    <div class="lbl" style=${{ marginBottom: '10px' }}>${t('Managed device')}${devices.length > 1 ? ' · ' + devices.length : ''}</div>
    <div class="device clickcard" onClick=${() => openDrawer({ title: t('Device detail'), sub: dev.model || 'EBG19P', rows: [
        { k: t('asset'), v: dev.asset || 'lab-asus-ebg19p-01', mono: true }, { k: t('model'), v: dev.model || 'EBG19P' }, { k: t('firmware'), v: dev.firmware || '—', mono: true },
        { k: t('CPU'), v: dev.cpu == null ? '—' : dev.cpu + ' %' }, { k: t('MEM'), v: dev.mem == null ? '—' : dev.mem + ' %' }, { k: t('TEMP'), v: dev.temp == null ? '—' : dev.temp + ' °C' }, { k: t('online'), v: statusBullet(dev.online === true, t('online'), t('offline')) } ] })}><div class="metrics">
      ${[['CPU', dev.cpu, '%'], ['MEM', dev.mem, '%'], ['TEMP', dev.temp, '°C']].map(([k, v, u]) =>
    html`<div key=${k} class="metric"><div class="num">${v ?? '—'}<span style=${{ fontSize: '11px', color: 'var(--ink3)' }}>${u}</span></div><div class="lbl">${k}</div></div>`)}
    </div></div>
    <div style=${{ fontSize: '12px', color: 'var(--ink2)', marginTop: '10px', display: 'flex', alignItems: 'center', gap: '8px' }}>
      <${Dot} s=${dev.online === true ? 'on' : 'off'}/> ASUS ExpertWiFi <b style=${{ color: 'var(--ink)' }}>${dev.model || 'EBG19P'}</b>
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
      ${(() => { const grp = (d.snapshots_by_agent || []).find(g => g.sb === sb); const snaps = (grp && grp.items || []).slice().reverse(); return html`<${Panel} title="Snapshots" label="per sandbox · recovery points">
        <${Field} label="Sandbox"><${Segmented} value=${sb} options=${SNAP_SB} onChange=${setSb}/></${Field}>
        <div class="addrow">
          <button class="btn" onClick=${() => run(NF.snapshot('create', '', sb), 'Snapshot created')}>${t('+ Create snapshot')}</button>
          <button class="btn ghost" onClick=${() => run(NF.action('refresh'), 'Refreshed')}>${t('Refresh')}</button>
        </div>
        <div class="snaplist">${snaps.length ? snaps.map(sn => html`<div key=${sn.ts} class="snaprow">
            <div class="grow"><b class="mono">${sn.ver}</b> <span class="muted">${sn.name !== '—' ? sn.name : ''}</span><div class="muted mono" style=${{ fontSize: '11px' }}>${sn.ts}</div></div>
            <${ConfirmBtn} ghost=${true} confirm=${t('Restore') + ' ' + sb + ' ← ' + sn.ts + '?'} run=${() => NF.snapshot('restore', sn.ts, sb)} label=${t('Restore')} busyLabel="…"/>
            <${ConfirmBtn} danger=${true} confirm=${t('Delete') + ' ' + sb + ' · ' + sn.ts + '?'} run=${() => NF.snapshot('delete', sn.ts, sb)} label=${t('Delete')} busyLabel="…"/>
          </div>`) : html`<div class="muted" style=${{ padding: '10px 2px', fontSize: '12px' }}>${t('No snapshots yet — click Create.')}</div>`}</div>
      </${Panel}>`; })()}
    </div>
    <div class="col">
      ${html`<${Panel} title="Containers" label="OpenShell sandboxes">
        <${DataTable} rows=${d.containers} pageSize=${10} empty="No container telemetry."
          cols=${[
            { k: 'name', label: 'Name', render: r => html`<span class="mono">${r.name || r.Names || '—'}</span>` },
            { k: 'state', label: 'State', render: r => html`<${Dot} s=${(r.state || r.status || '').toLowerCase().includes('up') ? 'on' : 'off'}/> ${r.state || r.status || ''}` },
            { k: 'image', label: 'Image', cls: 'imgcell', render: r => html`<span class="mono muted" title=${r.image || ''}>${r.image || ''}</span>` },
          ]}/></${Panel}>`}
      ${html`<${Panel} title="Diagnostics" label="on-demand · nemoclaw/openshell">
        <${Field} label="Target"><${Segmented} value=${sb} options=${SNAP_SB} onChange=${setSb}/></${Field}>
        <div class="addrow">${['doctor', 'logs', 'recover', 'gwhealth', 'stale', 'gsettings'].map(x => html`<button key=${x} class="btn ghost" onClick=${() => runDiag(x)}>${x}</button>`)}
          <${ConfirmBtn} danger=${true} confirm=${t('Rebuild') + ' ' + sb + ' — ' + t('rebuilds the sandbox (minutes; custom policy must be re-applied via boot-stack).')} run=${() => NF.sys({ do: 'rebuild', sb })} label="rebuild" busyLabel="rebuilding"/></div>
        ${diag ? html`<div style=${{ marginTop: '12px' }}><div class="lbl" style=${{ marginBottom: '6px' }}>${diag.title}</div>
          <pre class="mono" style=${{ background: 'var(--inset)', border: '1px solid var(--line)', borderRadius: '8px', padding: '10px', fontSize: '11px', color: 'var(--ink2)', maxHeight: '220px', overflow: 'auto', whiteSpace: 'pre-wrap' }}>${diag.out}</pre></div>` : null}
      </${Panel}>`}
      ${html`<${Panel} title="Inference" label="switch provider / model (nemoclaw inference set)">
        <${Field} label="Sandbox"><${Segmented} value=${sb} options=${SNAP_SB} onChange=${setSb}/></${Field}>
        <div class="addrow">
          <input class="inp" placeholder="provider (vllm-local / nim…)" value=${inf.provider} onInput=${e => setInf({ ...inf, provider: e.target.value })}/>
          <input class="inp" placeholder="model (nemotron-super)" value=${inf.model} onInput=${e => setInf({ ...inf, model: e.target.value })}/>
          <${ConfirmBtn} confirm=${t('Switch inference of') + ' ' + sb + ' → ' + (inf.provider || '?') + ' / ' + (inf.model || '?') + '?'} run=${() => NF.sys({ do: 'infset', sb, provider: inf.provider, model: inf.model })} label="Apply" busyLabel="applying"/>
        </div></${Panel}>`}
      ${html`<${Panel} title="Device ops · EBG19P" label="worker-a quick actions (needs device link)">
        <div class="addrow">${[['sync', t('Sync settings')], ['harden', t('Harden')], ['restart', t('Restart services')], ['block', t('Block unauthorized')]].map(([op, lbl]) => html`<${ConfirmBtn} key=${op} ghost=${true} confirm=${lbl + ' (' + op + ') — ' + t('run against the real EBG19P, confirm?')} run=${() => NF.deviceAction(op)} label=${lbl} busyLabel="…"/>`)}</div>
        <div class="muted" style=${{ fontSize: '11px', marginTop: '8px' }}>${t('Off-net → graceful \'unreachable\'; every action audited.')}</div></${Panel}>`}
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
  pen('Config drift', regs, 8, 40);
  pen('affected CVE', ((d.cve && d.cve.findings) || []).length, 6, 36);
  pen('nuclei high', sev(/high/i), 8, 32);
  pen('Cert/crypto high-risk', certHigh, 7, 28);
  score = Math.max(0, Math.round(score));
  return { score, grade: score >= 90 ? 'A' : score >= 80 ? 'B' : score >= 65 ? 'C' : score >= 50 ? 'D' : 'F', factors };
}
// Cipher families exactly match worker-a's CIPHER_FAMS (OpenSSL cipher-string tokens) — the old
// panel sent lowercase names the worker rejected with "未知套件", so every toggle silently failed.
const CIPHER_FAMS = [
  { k: 'RC4', why: 'Biased keystream → plaintext recovery', detail: 'Stream cipher with keystream biases; RFC 7465 prohibits it in TLS. Enables cookie / plaintext recovery — considered broken in practice since 2013.' },
  { k: '3DES', why: '64-bit block → Sweet32 birthday attack', detail: 'CVE-2016-2183 (Sweet32): a birthday attack recovers plaintext from long-lived connections. NIST disallowed 3DES for TLS after 2023.' },
  { k: 'DES', why: '56-bit key → brute-forceable', detail: 'Single DES has a 56-bit key, exhaustible with modest hardware in hours. Never acceptable for transport security.' },
  { k: 'NULL', why: 'No encryption → cleartext on the wire', detail: 'eNULL suites authenticate the peer but do not encrypt; the payload travels in the clear.' },
  { k: 'EXPORT', why: '40/512-bit → FREAK / Logjam downgrade', detail: '1990s export-grade crypto. FREAK (CVE-2015-0204) and Logjam force a downgrade to key sizes that are broken offline.' },
  { k: '-MD5', why: 'MD5 MAC → collision-broken hash', detail: 'Record MAC built on MD5. MD5 is collision-broken and unfit for message integrity.' },
  { k: '@SHA1MAC', why: 'SHA-1 MAC → deprecated hash', detail: 'HMAC-SHA1 record MAC. SHA-1 is deprecated (SHATTERED collision, 2017) and being removed from TLS.' },
  { k: 'anon', why: 'No server authentication → trivial MITM', detail: 'Anonymous (A)DH / (A)ECDH suites skip peer authentication, so an active attacker MITMs the handshake undetected.' },
  { k: 'IDEA', why: 'Legacy 64-bit block cipher', detail: 'Not broken, but a legacy 64-bit-block cipher. Flagged under strict cipher-suite hygiene.' },
  { k: 'SEED', why: 'Regional legacy cipher', detail: 'Korean legacy block cipher; non-standard for modern TLS. Flagged only under a strict minimal-suite policy.' },
  { k: 'CAMELLIA', why: 'Sound but non-preferred vs AES', detail: 'Cryptographically sound but not preferred over AES; flagged only when you want a strictly minimal cipher suite.' },
];
// Mirrors worker-itops CIPHER_TIERS — which families each tier flags as weak (DES-CBC/DES-CBC3 → DES).
const CIPHER_TIERS = {
  lax: ['RC4', 'NULL', 'EXPORT', 'anon'],
  standard: ['RC4', '3DES', 'DES', 'NULL', 'EXPORT', '-MD5', 'anon'],
  strict: ['RC4', '3DES', 'DES', 'NULL', 'EXPORT', '-MD5', '@SHA1MAC', 'anon', 'IDEA', 'SEED', 'CAMELLIA'],
};
const CipherPolicyPanel = memo(function CipherPolicyPanel({ d }) {
  const [open, setOpen] = useState('');
  const pol = (d.settings && d.settings.cert_cipher_policy) || 'standard';
  const custom = pol === 'custom';
  // effective flagged set — the SAME truth the scan uses: custom → per-family list; a tier → that tier's families.
  const eff = new Set(custom ? ((d.settings && d.settings.cert_cipher_custom) || []) : (CIPHER_TIERS[pol] || CIPHER_TIERS.standard));
  const flaggedN = CIPHER_FAMS.filter(f => eff.has(f.k)).length;
  const setTier = (v) => run(NF.config('cert_cipher_policy', v), 'cipher policy → ' + v);
  return html`<${Panel} title="Cipher policy override" label="tier + per-family weak-crypto flags"
    right=${html`<span class="pill2 c">${flaggedN} ${t('flagged')}</span>`}>
    <div class="cipher-tier">
      <span class="lbl">${t('Policy tier')}</span>
      <${Segmented} value=${pol} options=${['lax', 'standard', 'strict', 'custom']} onChange=${setTier}/>
      <span class="muted" style=${{ fontSize: '10.5px', marginLeft: 'auto', textAlign: 'right' }}>${t('same setting as Settings → Certificate & crypto')}</span>
    </div>
    <div class=${'certpol-banner ' + (custom ? 'on' : 'off')}>
      <span class="certpol-ico">${custom ? '⚑' : 'ⓘ'}</span>
      <div><b>${custom ? t('Custom — edit each family below') : t('Tier') + ': ' + pol}</b>
        <div class="muted" style=${{ fontSize: '11.5px', marginTop: '2px' }}>${custom
          ? t('worker-a flags the families switched on below on its next cert scan.')
          : t('This tier flags the families highlighted below. Switch to custom to edit them individually.')}</div></div>
    </div>
    <div class="cipherlist">${CIPHER_FAMS.map((f) => { const on = eff.has(f.k); const isOpen = open === f.k; return html`<div key=${f.k} class=${'cipherrow' + (isOpen ? ' open' : '')}>
      <button class=${'tglsw' + (on ? ' on' : '') + (custom ? '' : ' ro')} role="switch" aria-checked=${on} disabled=${!custom}
        title=${custom ? (on ? t('flagged as weak — click to allow') : t('allowed — click to flag as weak')) : t('set by the tier — switch to custom to edit')}
        onClick=${() => custom && run(NF.certPolicy({ fam: f.k, on: on ? 0 : 1 }), (on ? 'clear ' : 'flag ') + f.k)}><span></span></button>
      <div class="ciphermain" onClick=${() => setOpen(isOpen ? '' : f.k)}>
        <div class="cipherhd"><code>${f.k}</code><span class="muted">${t(f.why)}</span><span class="cipherexp">${isOpen ? '−' : 'ⓘ'}</span></div>
        ${isOpen ? html`<div class="cipherdetail">${t(f.detail)}</div>` : null}
      </div>
      <span class=${'pill2 ' + (on ? 'c' : 'g')}>${on ? t('weak') : t('allowed')}</span>
    </div>`; })}</div>
  </${Panel}>`;
});
// worker-b SAST source of truth — a GitHub URL / owner-repo, or a folder mounted into the sandbox.
const SastSource = memo(function SastSource({ d }) {
  const curSrc = (d.settings && d.settings.sast_src) || '';
  const curRef = (d.settings && d.settings.sast_ref) || 'master';
  const [src, setSrc] = useState(curSrc);
  const [ref, setRef] = useState(curRef);
  useEffect(() => { setSrc(curSrc); setRef(curRef); }, [curSrc, curRef]);
  const prov = (d.source && d.source.sast_source) || 'not-synced';
  const synced = prov && prov !== 'not-synced';
  const save = () => run(Promise.all([NF.config('sast_src', src.trim()), NF.config('sast_ref', (ref.trim() || 'master'))])
    .then(() => ({ ok: true, msg: t('source updated — re-syncing') })), 'sast-source');
  return html`<div class="sastsrc">
    <div class="lbl" style=${{ display: 'flex', alignItems: 'center', gap: '8px' }}>${t('Source of truth')}
      <span class=${'pill2 ' + (synced ? 'g' : 'w')}>${synced ? prov : t('not synced')}</span></div>
    <div class="addrow" style=${{ flexWrap: 'wrap', marginTop: '8px' }}>
      <input class="inp" style=${{ flex: '1 1 320px' }} placeholder="https://github.com/OWNER/REPO.git  ·  or /mounted/folder" value=${src} onInput=${e => setSrc(e.target.value)}/>
      <input class="inp" style=${{ maxWidth: '150px' }} placeholder="ref (branch / tag / sha)" value=${ref} onInput=${e => setRef(e.target.value)}/>
      <${ConfirmBtn} confirm=${t('Set SAST source to') + ' ' + (src || '—') + ' @ ' + (ref || 'master') + '?'} run=${save} label=${t('Sync & scan')} busyLabel="…"/>
    </div>
    <div class="muted" style=${{ fontSize: '10.5px', marginTop: '7px' }}>${t('worker-b syncs the pinned ref and scans it — a GitHub repo or a folder mounted into the sandbox. No demo fallback: if it can’t sync, it says so.')}</div>
  </div>`;
});
const SecurityView = memo(function SecurityView({ d }) {
  const P = posture(d);
  const gc = P.score >= 80 ? 'var(--ok)' : P.score >= 65 ? 'var(--warn)' : 'var(--crit)';
  return html`<div class="viewfade"><div class="viewhd"><h2>${t('Security')}</h2><span class="lbl">${t('worker-b · CVE / nuclei / cert / source')}</span></div>
    <div class="grid1">
      ${html`<${Panel} title="EBG19P security posture" label="drift · CVE · nuclei · cert fused into one score">
        <div style=${{ display: 'flex', gap: '22px', alignItems: 'center', flexWrap: 'wrap' }}>
          <div style=${{ textAlign: 'center', minWidth: '104px' }}>
            <div style=${{ fontSize: '46px', fontWeight: 800, lineHeight: 1, color: gc }}>${P.score}</div>
            <div style=${{ fontSize: '13px', color: 'var(--ink2)', marginTop: '3px' }}>/ 100 · grade <b style=${{ color: gc }}>${P.grade}</b></div>
          </div>
          <div style=${{ flex: 1, minWidth: '220px' }}>
            ${P.factors.length ? P.factors.map(f => html`<div key=${f.label} style=${{ marginBottom: '7px' }}>
              <div style=${{ display: 'flex', justifyContent: 'space-between', fontSize: '12px' }}><span class="ink2">${t(f.label)} <b>×${f.n}</b></span><span style=${{ color: 'var(--crit)' }}>−${f.penalty}</span></div>
              <div style=${{ height: '4px', background: 'var(--line)', borderRadius: '3px', overflow: 'hidden', marginTop: '3px' }}><div style=${{ width: Math.min(f.penalty * 2, 100) + '%', height: '100%', background: 'var(--crit)' }}></div></div>
            </div>`) : html`<div class="muted">${t('No penalties — fleet posture is healthy ✓')}</div>`}
          </div>
        </div></${Panel}>`}
      ${html`<${Panel} title="CVE findings" label="fleet scan" right=${html`<${ActionBtn} act="cve" label="Rescan" busyLabel="Scanning" ghost=${true}/>`}>
        <${DataTable} rows=${d.cve.findings} pageSize=${8} empty="No affected CVEs — or scan pending."
          cols=${[
            { k: 'cve', label: 'CVE', render: r => cveLink(r.cve || r.id) },
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
            { k: 'cve', label: 'CVE', render: r => (r.cve || []).length ? html`${(r.cve || []).map((id, i) => html`<span key=${id}>${i ? ', ' : ''}${cveLink(id)}</span>`)}` : html`<span class="mono">—</span>` },
            { k: 'matched_at', label: 'Matched', align: 'right', render: r => html`<span class="mono muted">${r.matched_at || ''}</span>` },
          ]}/></${Panel}>` : null}
      ${(() => { const cf = d.cert.findings || []; const hi = cf.filter(f => /high|crit/i.test(f.severity || '')).length; const med = cf.length - hi;
        return html`<${Panel} title="Certificates / weak crypto" label="worker-a probe"
          right=${cf.length ? html`<span class=${'pill2 ' + (hi ? 'c' : 'w')}>${hi ? '⚠ ' + hi + ' ' + t('high') : ''}${hi && med ? ' · ' : ''}${med ? med + ' ' + t('medium') : ''}</span>` : html`<span class="pill2 g">✓ ${t('clean')}</span>`}>
        ${cf.length ? html`<div class="certbanner ${hi ? 'hi' : 'med'}"><span class="certbanner-ico">⚠</span><div><b>${cf.length} ${t('weak certificate / crypto warning(s)')}</b><div class="muted" style=${{ fontSize: '11.5px', marginTop: '2px' }}>${t('weak cipher / expiring / untrusted — worker-a flags these against the crypto baseline')}</div></div></div>` : null}
        <${DataTable} rows=${d.cert.findings} pageSize=${6} empty="No cert/crypto issues."
          cols=${[
            { k: 'service', label: 'Service' },
            { k: 'issue', label: 'Issue', render: r => html`<span class="pill2 w">${r.issue || ''}</span>` },
            { k: 'detail', label: 'Detail', render: r => html`<span class="muted">${r.detail || ''}</span>` },
            { k: 'severity', label: 'Sev', align: 'right', render: r => sevPill(r.severity) },
          ]}/></${Panel}>`; })()}
      ${(d.me && d.me.role === 'admin') ? html`<${CipherPolicyPanel} d=${d}/>` : null}
      ${html`<${Panel} title="SBOM" label=${'components · ' + (d.source.sbom_source || 'not synced')}
        right=${html`<span class="pill2 a">${(d.source.sbom || 0)} ${t('packages')}</span>`}>
        <${DataTable} rows=${d.source.sbom_list || []} pageSize=${10} empty=${t('No SBOM — configure a source in SAST below.')}
          cols=${[
            { k: 'name', label: t('Component'), render: r => html`<span class="mono">${r.name || '—'}</span>` },
            { k: 'version', label: t('Version'), align: 'right', render: r => html`<span class="mono ink2">${r.version || '—'}</span>` },
          ]}/></${Panel}>`}
      ${html`<${Panel} title="SAST findings" label=${(d.source.sast_engine || 'semgrep') + ' · ' + (d.source.sast_source || 'not synced')} right=${html`<${ActionBtn} act="source" label="Re-run" busyLabel="Running" ghost=${true}/>`}>
        <${SastSource} d=${d}/>
        ${(() => { const sl = d.source.sast_list || []; const byCwe = {}; sl.forEach((f) => { const c = (f.cwe || '?').split(' ')[0]; byCwe[c] = (byCwe[c] || 0) + 1; });
          const vd = sl.filter(f => f.violates_design).length; const pv = sl.filter(f => f.patch_verified).length;
          return sl.length ? html`<div class="sastsum">
            ${Object.entries(byCwe).sort((a, b) => b[1] - a[1]).map(([c, n]) => html`<span key=${c} class="pill2 c">${c} ×${n}</span>`)}
            ${vd ? html`<span class="pill2 w">⚑ ${vd} ${t('violate baseline')}</span>` : null}
            ${pv ? html`<span class="pill2 g">✓ ${pv} ${t('patch verified')}</span>` : null}
            <span class="muted" style=${{ fontSize: '10.5px', marginLeft: 'auto' }}>${t('click a row for code + patch + fix')}</span>
          </div>` : null; })()}
        <${DataTable} rows=${d.source.sast_list} pageSize=${12} empty=${t('No SAST hits — configure a source above, or the pinned ref is clean.')} onRow=${sastDrawer}
          cols=${[
            { k: 'cwe', label: 'CWE', render: r => cweLink(r.cwe) },
            { k: 'file', label: 'File', render: r => html`${ghFile(r.upstream_path || r.file, r.url)}${r.violates_design ? html` <span class="pill2 w" style=${{ fontSize: '9px' }}>${r.violates_design}</span>` : null}` },
            { k: 'line', label: 'Line', align: 'right', render: r => r.url ? html`<a class="mono cvelink" href=${r.url} target="_blank" rel="noopener noreferrer" onClick=${e => e.stopPropagation()}>${r.line || ''}</a>` : html`<span class="mono">${r.line || ''}</span>` },
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
        { k: 'ts', label: 'Time', render: r => html`<span class="mono">${r.t || r.ts || '—'}</span>` },
        { k: 'target', label: 'Target', render: r => html`<span class="mono" style=${{ wordBreak: 'break-all' }}>${r.target || r.b || r.reason || r.cls || '—'}</span>` },
        { k: 'policy', label: 'Policy', render: r => html`<span class="catpill">${r.policy || r.a || r.engine || '—'}</span>` },
        { k: 'verdict', label: 'Verdict', align: 'right', render: r => {
          const dn = (r.verb || r.verdict || r.cls || '').toLowerCase().includes('den');
          return html`<span class=${'sev ' + (dn ? 'hi' : 'in')}>${dn ? 'DENIED' : 'ALLOWED'}</span>`; } },
      ]}/></${Panel}>`;
});
// Least-privilege classifier — for the selected agent, is a network service job-critical (keep),
// a default preset nobody's job uses (revoke), or uncertain (review)? Mirrors harden-agent-policies.sh.
const LP_NORM = { npm_yarn: 'npm', local_inference: 'local-inference', worker_bridge: 'worker-bridge', telegram_bot: 'telegram', mail_egress: 'mail' };
const LP_BLOAT = new Set(['weather', 'brew', 'huggingface', 'npm', 'local-inference']);
const LP_KEEP = {
  'team-lead': /telegram|worker-bridge|managed_inference|^mail/,
  'worker-a': /managed_inference|ebg19p|device|worker-bridge/,
  'worker-b': /github|nvd|osv|managed_inference|nuclei/,
  'worker-c': /managed_inference|ebg19p|device|github|skill/,
};
function lpClass(sb, rawName) {
  const name = LP_NORM[rawName] || rawName;
  if ((LP_KEEP[sb] || /$^/).test(name)) return 'keep';
  if (name === 'pypi') return sb === 'worker-b' ? 'review' : 'revoke';
  if (name === 'nvidia' || /nous/.test(name)) return 'review';   // base-image config, not preset-removable
  if (LP_BLOAT.has(name)) return 'revoke';
  return 'other';
}
const lpPresetName = (rawName) => LP_NORM[rawName] || rawName;
const PolicyEditor = memo(function PolicyEditor() {
  const [sb, setSb] = useState('team-lead');
  const [pol, setPol] = useState(null);
  const [preset, setPreset] = useState('');
  const [ep, setEp] = useState({ host: '', port: '443', access: 'full' });
  const [nonce, setNonce] = useState(0);
  const [pq, setPq] = useState('');
  useEffect(() => {
    if (typeof NF.policyRo !== 'function') { setPol({ ok: false, msg: t('policy API unavailable') }); return; }
    let ok = true; setPol({ loading: true });
    NF.policyRo(sb).then(r => ok && setPol(r)).catch(e => ok && setPol({ ok: false, msg: e.message }));
    return () => { ok = false; };
  }, [sb, nonce]);
  const p = (pol && pol.policy) || {};
  const _nets = p.networks || [];
  const nets = pq.trim() ? _nets.filter(n => (n.name + ' ' + (n.eps || []).join(' ')).toLowerCase().includes(pq.trim().toLowerCase())) : _nets;
  const after = () => setNonce(n => n + 1);   // reload the policy after a mutation
  const _ZTAG = { 'team-lead': 'lead', 'worker-a': 'ops', 'worker-b': 'sec', 'worker-c': 'gov' };
  return html`<${Panel} title="Policy editor" label=${t('OpenShell services · open / revoke')}>
    <div class="agentpick">
      <div class="agentpick-lbl">${t('Editing policy for')}</div>
      <div class="agentpick-row">${POLSB.map(a => html`<button key=${a} class=${'agentbtn ' + (sb === a ? 'on' : '')} onClick=${() => setSb(a)}>
        <span class="agentbtn-dot"></span><span class="agentbtn-name">${a}</span><span class=${'tag ' + (a === 'team-lead' ? 'a' : 'g')}>${t(_ZTAG[a] || '')}</span>
      </button>`)}</div>
    </div>
    ${!pol || pol.loading ? html`<div class="muted">${t('loading…')}</div>` : !pol.ok ? html`<div class="muted">${pol.msg || t('policy unavailable')}</div>` : html`<div>
      <div class="muted mono" style=${{ fontSize: '11px', margin: '2px 0 8px' }}>version ${p.version || '?'} · ${(p.hash || '')}</div>
      ${(() => { const rv = _nets.filter(n => lpClass(sb, n.name) === 'revoke').length; const rw = _nets.filter(n => lpClass(sb, n.name) === 'review').length;
        return html`<div class=${'lpsum ' + (rv ? 'warn' : 'ok')}><span class="lpsum-ico">${rv ? '⚠' : '✓'}</span><div>${rv
          ? html`<b>${rv} ${t('service(s) recommended to revoke')}</b> <span class="muted">${t('— a default preset this agent’s job doesn’t use')}</span>`
          : html`<b>${t('Lean')}</b> <span class="muted">${t('— every service maps to this agent’s job')}</span>`}${rw ? html`<div class="muted" style=${{ fontSize: '11px', marginTop: '2px' }}>${rw} ${t('to review (base-image config / maybe needed)')}</div>` : null}</div></div>`; })()}
      <div class="srchbar" style=${{ marginBottom: '7px' }}><input class="inp" placeholder=${t('Filter services…')} value=${pq} onInput=${e => setPq(e.target.value)}/><span class="lbl" style=${{ marginLeft: 'auto' }}>${t('Network services')} · ${nets.length}</span></div>
      ${nets.length ? nets.map((n) => { const cls = lpClass(sb, n.name); const pn = lpPresetName(n.name);
        const asPreset = LP_BLOAT.has(pn) || pn === 'pypi';
        return html`<div key=${n.name} class=${'polrow lp-' + cls}>
        <div class="grow">
          <div style=${{ display: 'flex', alignItems: 'center', gap: '7px', flexWrap: 'wrap' }}>
            <b class="mono" style=${{ fontSize: '12.5px' }}>${n.name}</b>
            ${cls === 'keep' ? html`<span class="pill2 g">${t('needed')}</span>` : cls === 'revoke' ? html`<span class="pill2 c">${t('revoke recommended')}</span>` : cls === 'review' ? html`<span class="pill2 w">${t('review')}</span>` : null}
            ${n.l7 ? html`<span class="pill2 a">L7</span>` : null}
          </div>
          <div class="muted mono" style=${{ fontSize: '11px', marginTop: '3px', wordBreak: 'break-all' }}>${(n.eps || []).join('  ·  ') || t('no endpoints')}</div>
          ${(n.bins && n.bins.length) ? html`<div class="muted" style=${{ fontSize: '10.5px', marginTop: '4px' }}>${t('binaries')}: <span class="mono">${n.bins.join(', ')}</span></div>` : null}
        </div>
        <${ConfirmBtn} danger=${cls !== 'keep'} ghost=${true} confirm=${t('Revoke service') + ' \'' + n.name + '\' (' + sb + ')?'} run=${() => NF.policy(asPreset ? { op: 'preset', name: pn, on: false, sb } : { op: 'rule_remove', name: n.name, sb }).then(r => { after(); return r; })} label=${t('Revoke')} busyLabel="…"/>
      </div>`; }) : html`<div class="muted" style=${{ padding: '6px 0' }}>${t('deny-by-default · no network services')}</div>`}

      ${(p.fs_rw || p.fs_ro) ? html`<div class="lbl" style=${{ margin: '16px 0 7px' }}>${t('Filesystem')}</div>
      <div class="fschips">
        ${(p.fs_rw || []).map(x => html`<span key=${'rw' + x} class="fschip rw"><span class="mono">${x}</span> rw</span>`)}
        ${p.workdir ? html`<span class="fschip rw"><span class="mono">workdir</span> rw</span>` : null}
        ${(p.fs_ro || []).map(x => html`<span key=${'ro' + x} class="fschip ro"><span class="mono">${x}</span> ro</span>`)}
        ${!(p.fs_rw || []).length && !(p.fs_ro || []).length && !p.workdir ? html`<span class="muted">${t('default (deny-by-default)')}</span>` : null}
      </div>` : null}

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
      <${ConfirmBtn} confirm=${t('Start') + ' ' + chan + ' · ' + sb + ' — ' + t('rebuilds the sandbox.')} run=${() => NF.sys({ do: 'chanstart', sb, chan })} label="Start" busyLabel="starting"/>
      <${ConfirmBtn} danger=${true} confirm=${t('Stop') + ' ' + chan + ' · ' + sb + ' — ' + t('rebuilds the sandbox (keeps credentials).')} run=${() => NF.sys({ do: 'chanstop', sb, chan })} label="Stop" busyLabel="stopping"/>
    </div>
    <div class="muted" style=${{ fontSize: '11px', marginTop: '8px' }}>${t('Stop/Start rebuilds the sandbox; credentials are kept.')}</div>
  </${Panel}>`;
});

const AuditView = memo(function AuditView({ d }) {
  const [q, setQ] = useState('');
  if (!d.audit_recent.length && !(d.me.role === 'admin')) return html`<div class="viewfade"><div class="viewhd"><h2>${t('Audit')}</h2></div><div class="empty">${t('Admin only.')}</div></div>`;
  const ql = q.trim().toLowerCase();
  const rows = ql ? d.audit_recent.filter(r => ((r.ts || '') + (r.actor || '') + (r.action || '') + (r.detail || '')).toLowerCase().includes(ql)) : d.audit_recent;
  return html`<div class="viewfade"><div class="viewhd"><h2>${t('Audit')}</h2>
    <span class=${'pill2 ' + (d.audit.ok ? 'g' : 'c')}>${d.audit.ok ? t('chain verified') : t('chain broken')}</span>
    <span class="lbl mono">${(d.audit.count || 0).toLocaleString()} ${t('entries')}</span></div>
    ${html`<${Panel} title="Tamper-evident admin audit" label="hash-chained">
      <div class="srchbar"><input class="inp" placeholder=${t('Search actor / action / detail…')} value=${q} onInput=${e => setQ(e.target.value)}/>${ql ? html`<span class="muted" style=${{ fontSize: '11.5px' }}>${rows.length} / ${d.audit_recent.length}</span>` : null}</div>
      <${VirtualList} rows=${rows} rowH=${38} height=${380} empty=${t('No audit entries.')}
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
        ${seg('cve_interval_sec', 'worker-b CVE scan cadence')}${seg('cert_interval_sec', 'worker-a cert/crypto cadence')}${seg('nuclei_interval_sec', t('worker-b nuclei active scan (nuclei-templates)'))}</div></${Panel}>`}
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
        <${Field} label="proactive_enabled" hint="team-lead active patrol + reporting"><${Toggle} on=${s.proactive_enabled !== false} onChange=${v => set('proactive_enabled', v)}/></${Field}>
        <${Field} label="proactive_safety_net" hint="deterministic critical alerts (independent of team-lead)"><${Toggle} on=${s.proactive_safety_net !== false} onChange=${v => set('proactive_safety_net', v)}/></${Field}>
        ${seg('patrol_interval_sec', t('proactive patrol cadence'))}${seg('digest_interval_sec', t('proactive digest cadence'))}</div></${Panel}>`}
      ${html`<${Panel} title="Quiet hours & scan tags" label="quiet hours (critical still pushed) + nuclei scope"><div class="formgrid">
        <${Field} label="quiet_enabled" hint="enable quiet hours"><${Toggle} on=${s.quiet_enabled === true} onChange=${v => set('quiet_enabled', v)}/></${Field}>
        ${seg('quiet_start', t('quiet start'))}${seg('quiet_end', t('quiet end'))}
        <${Field} label="nuclei_tags" hint="comma-separated (asus,cve,exposure…)"><input class="inp" defaultValue=${s.nuclei_tags || 'asus,cve'} onBlur=${e => set('nuclei_tags', e.target.value)}/></${Field}>
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
          <label class="fld"><span>${t('Email')}</span><input class="inp" placeholder="you@asus.com" value=${nu.email} onInput=${e => setNu({ ...nu, email: e.target.value })}/></label>
          <label class="fld"><span>${t('Password')}</span><input class="inp" type="password" placeholder="••••••" value=${nu.password} onInput=${e => setNu({ ...nu, password: e.target.value })}/></label>
          <label class="fld"><span>${t('Role')}</span><${Segmented} value=${nu.role} options=${['viewer', 'admin']} onChange=${r => setNu({ ...nu, role: r })}/></label>
          <button class="btn" onClick=${() => run(NF.users({ op: 'add', ...nu }), 'User added')}>${t('+ Add')}</button>
        </div>
      </${Panel}>`}
      ${html`<${Panel} title="Notification recipients" label="alerts / tickets">
        ${recips.length ? recips.map((r, i) => html`<div key=${i} class="adminrow">
          <div class="grow"><b>${r.name}</b> <span class="muted mono" style=${{ fontSize: '11px' }}>${r.email || ''} ${r.telegram || ''}</span></div>
          <button class="btn ghost" onClick=${() => run(NF.recipient('test', r.name, r.telegram, r.email), 'Test sent')}>Test</button>
          <button class="btn ghost" onClick=${() => run(NF.recipient('del', r.name, '', r.email), 'Removed')}>Remove</button>
        </div>`) : html`<div class="empty">No recipients yet.</div>`}
        <div class="addrow">
          <label class="fld"><span>${t('name')}</span><input class="inp" placeholder="Ops team" value=${nr.name} onInput=${e => setNr({ ...nr, name: e.target.value })}/></label>
          <label class="fld"><span>Telegram ID</span><input class="inp" placeholder="123456789" value=${nr.telegram} onInput=${e => setNr({ ...nr, telegram: e.target.value })}/></label>
          <label class="fld"><span>${t('Email')}</span><input class="inp" placeholder="ops@asus.com" value=${nr.email} onInput=${e => setNr({ ...nr, email: e.target.value })}/></label>
          <button class="btn" onClick=${() => run(NF.recipient('add', nr.name, nr.telegram, nr.email), 'Recipient added')}>${t('+ Add')}</button>
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
        ${html`<${Panel} title="Patrol status" label="team-lead active patrol" right=${html`<${ActionBtn} act="patrol" label="Patrol now" busyLabel="Triggering" ghost=${true}/>`}>
          <div class="formgrid">
            <${Field} label="Last patrol"><div class="mono ink2">${p.last_patrol || '—'}</div></${Field}>
            <${Field} label="Cadence"><div class="mono ink2">patrol ${fmtSec(p.patrol_interval_sec)} · digest ${fmtSec(p.digest_interval_sec)}</div></${Field}>
            <${Field} label="Safety net"><span class=${'pill2 ' + (p.safety_net ? 'g' : 'w')}>${p.safety_net ? t('on · guaranteed delivery') : 'off'}</span></${Field}>
            <${Field} label="Last cycle"><div><b style=${{ color: (p.last_critical || 0) > 0 ? 'var(--crit)' : 'var(--ink2)' }}>${p.last_critical || 0}</b> <span class="muted">critical ·</span> ${p.last_routine || 0} <span class="muted">routine</span></div></${Field}>
            <${Field} label="Critical alerts" hint="mute proactive interrupts during maintenance (still patrols + logs)">
              ${(p.snooze_until && p.snooze_until * 1000 > Date.now())
                ? html`<span class="pill2 w">snoozed → ${new Date(p.snooze_until * 1000).toLocaleTimeString()}</span> <${ActionBtn} act="snooze_off" label="Resume" busyLabel="…" ghost=${true}/>`
                : html`<span class="pill2 g">active</span> <${ActionBtn} act="snooze30" label="Snooze 30m" busyLabel="…" ghost=${true}/> <${ActionBtn} act="snooze120" label="2h" busyLabel="…" ghost=${true}/>`}
            </${Field}>
          </div>
          ${p.summary ? html`<hr class="sep" style=${{ margin: '12px 0' }}/><pre class="mono" style=${{ whiteSpace: 'pre-wrap', fontSize: '11.5px', color: 'var(--ink2)', margin: 0 }}>${p.summary}</pre>` : null}
        </${Panel}>`}
      </div>
      <div class="col">
        ${html`<${Panel} title="Patrol log" label="recent patrols · delta events">
          <${DataTable} rows=${log} pageSize=${10} empty="No patrol log yet (loop idle or just started)."
            cols=${[
              { k: 'ts', label: 'Time', render: r => html`<span class="mono">${r.ts || ''}</span>` },
              { k: 'ev', label: 'Events', render: r => { const c = (r.critical || []).length, rt = (r.routine || []).length;
                return html`${c ? html`<span class="pill2 c">${c} critical</span> ` : null}${rt ? html`<span class="pill2">${rt} routine</span>` : null}${!c && !rt ? html`<span class="muted">no change</span>` : null}`; } },
              { k: 'sent', label: 'Sent', align: 'right', render: r => html`${r.safety_net_fired ? html`<span class="pill2 g">safety-net</span> ` : null}${r.digest_sent ? html`<span class="pill2 a">digest</span>` : null}${!r.safety_net_fired && !r.digest_sent ? html`<span class="muted">–</span>` : null}` },
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
      <span class="lbl">${t('who delegated whom · live')}</span></div>
    <div class="grid1">
      ${html`<${Panel} title="Fleet activity" label=${t('who is working, and on what')}>
        <div class="actgrid">
          ${nodes.map((n) => { const last = flow.find(e => e.node === n.id);  // flow is newest-first
            const working = !!last && last.status === 'working';
            return html`<div key=${n.id} class=${'actcard' + (working ? ' on' : '')}>
              <div class="act-hd"><${Dot} s=${working ? 'on' : 'off'}/><span class="mono act-nm">${n.label}</span>
                <span class=${'pill2 ' + (working ? 'a' : '')} style=${{ marginLeft: 'auto' }}>${working ? t('working') : t('idle')}</span></div>
              <div class="act-role">${n.role}</div>
              ${last ? html`<div class="act-task"><span class="mono">${last.task || '—'}</span>${last.detail ? html`<span class="muted"> · ${last.detail}</span>` : null}</div>
                <div class="act-meta">${working ? t('started') : last.status} · <span class="mono">${last.ts || ''}</span>${last.peer && last.peer !== n.id ? html` · <span class="muted">← ${last.peer}</span>` : null}</div>`
              : html`<div class="act-task muted">${t('no activity yet')}</div>`}
            </div>`; })}
        </div></${Panel}>`}
      ${html`<${Panel} title="Delegation timeline" label="recent delegations / handoffs (peer → node)" right=${html`<${ActionBtn} act="patrol" label="Trigger patrol" busyLabel="…" ghost=${true}/>`}>
        <${DataTable} rows=${flow} pageSize=${12} empty="No workflow events yet — appear after a delegation/scan (team-lead → worker → status)."
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
      <span class="lbl">${t('worker-c · change-governance · zone C')}</span></div>
    <div class="grid1">
      ${html`<${Panel} title="Review gate" label="quality gate on a/b output · reject = binding redo">
        <div style=${{ display: 'flex', gap: '22px', flexWrap: 'wrap', alignItems: 'center', marginBottom: '10px' }}>
          <div style=${{ textAlign: 'center' }}><div style=${{ fontSize: '30px', fontWeight: 800, color: rejects ? 'var(--crit)' : 'var(--ok)' }}>${rejects}</div><div class="muted" style=${{ fontSize: '11px' }}>${t('rejected → sent back')}</div></div>
          <div style=${{ textAlign: 'center' }}><div style=${{ fontSize: '30px', fontWeight: 800, color: 'var(--ink2)' }}>${reviews.length}</div><div class="muted" style=${{ fontSize: '11px' }}>total verdicts</div></div>
          <div class="muted" style=${{ fontSize: '12px', maxWidth: '340px' }}>${t('worker-c reviews worker-a remediations + worker-b CVE decisions against the approved baseline. reject → team-lead re-dispatches with required_fixes; 2 fails → escalate to human. human > worker-c > a/b.')}</div>
        </div>
        <${DataTable} rows=${reviews} pageSize=${8} empty="No review verdicts yet (worker-c not deployed / no delegation)."
          cols=${[
            { k: 'ts', label: 'Time', render: r => html`<span class="mono">${r.ts || ''}</span>` },
            { k: 'target', label: 'Target', render: r => html`<span class="mono">${r.target || ''} · ${r.kind || ''}</span>` },
            { k: 'ref', label: 'Subject', render: r => html`<span class="mono muted">${r.ref || ''}</span>` },
            { k: 'verdict', label: 'Verdict', align: 'right', render: r => html`${vPill(r.verdict)}${r.escalate ? html` <span class="pill2 c">→ human</span>` : r.redo > 0 ? html` <span class="pill2 w">redo ${r.redo}</span>` : null}` },
          ]}/></${Panel}>`}
      ${html`<${Panel} title="Config backups" label="known-good versions" right=${html`<${ActionBtn} act="backup" label="Backup now" busyLabel="…" ghost=${true}/>`}>
        <div style=${{ display: 'flex', gap: '22px', flexWrap: 'wrap', marginBottom: '9px', fontSize: '12px' }}>
          <span class="muted">count <b class="ink2">${g.backup_count || 0}</b></span>
          <span class="muted">latest <b class="mono ink2">${(g.backups || [])[0] || '—'}</b></span>
        </div>
        <${DataTable} rows=${(g.backups || []).map(b => ({ id: b }))} pageSize=${6} empty="No backups yet (needs device + EBG19P_CRED)."
          cols=${[{ k: 'id', label: 'Backup snapshot', render: r => html`<span class="mono">${r.id}</span>` }]}/></${Panel}>`}
      ${html`<${Panel} title="Firmware" label="lifecycle · urgency driven by CVEs">
        <div style=${{ fontSize: '13px' }}>
          <div style=${{ marginBottom: '5px' }}>${t('current')} <b class="mono ink2">${(() => { const c = g.firmware && g.firmware.current; return (!c || /unknown|未知/i.test(c)) ? t('not available') : c; })()}</b> ${fwUrgent ? html`<span class="pill2 c">update urgent</span>` : html`<span class="pill2 g">current</span>`}</div>
          ${affCves.length ? html`<div class="muted" style=${{ fontSize: '12px' }}>${t('CVE-driven: worker-b flags')} ${affCves.length} affected → <span class="mono">${affCves.slice(0, 3).join(', ')}${affCves.length > 3 ? '…' : ''}</span> ${t('(firmware update can fix)')}</div>` : html`<div class="muted" style=${{ fontSize: '12px' }}>${(g.firmware && g.firmware.note) || t('worker-c not deployed')}</div>`}
        </div></${Panel}>`}
      ${html`<${Panel} title="Skills · curator (SkillOS)" label="skill-repo governance · arXiv 2605.06614" right=${html`<span class="lbl">${g.skills_count || 0} skills</span>`}>
        <${DataTable} rows=${g.curations || []} pageSize=${6} empty="No skill-curation verdicts yet (worker-c not deployed)."
          cols=${[
            { k: 'ts', label: 'Time', render: r => html`<span class="mono">${r.ts || ''}</span>` },
            { k: 'op', label: 'Op', render: r => html`<span class="mono">${r.op || ''} ${r.name || ''}</span>` },
            { k: 'verdict', label: 'Verdict', align: 'right', render: r => html`<span class=${'pill2 ' + (r.verdict === 'approve' ? 'g' : 'c')}>${r.verdict || '—'}</span>` },
          ]}/></${Panel}>`}
    </div></div>`;
});
const ArchitectureView = memo(function ArchitectureView({ d }) {
  const nodes = d.nodes || [];
  const dot = (up) => html`<${Dot} s=${up ? 'on' : 'off'}/>`;
  const layers = [
    { k: 'nemoclaw', color: 'var(--s-blue)', title: 'Nemoclaw', role: t('host control plane'), desc: t('provisioning · model/route/policy strategy · points inference at local NIM') },
    { k: 'openshell', color: 'var(--accent)', title: 'OpenShell', role: t('sandbox + governance'), desc: t('per-agent sandbox · policy.yaml (egress/binaries/host) · deny-by-default · worker_bridge /32 + token') },
    { k: 'hermes', color: 'var(--s-aqua)', title: 'Hermes', role: t('agent harness × 4'), desc: t('same harness, different roles: team-lead + worker-a/b/c; skills = SKILL.md; workers run :9099 IT-ops') },
    { k: 'nim', color: 'var(--s-yellow)', title: 'NIM', role: t('local inference'), desc: t('Nemotron 3 Super 120B (NVFP4) · OpenAI /v1 · all 4 nodes route here · provider-agnostic seam') },
  ];
  const rules = [
    t('Authority: human > worker-c > worker-a/b — worker-c reject is binding; its firmware-apply/rollback need a human token.'),
    t('Hub-and-spoke — workers never talk to each other; supervision is arbitrated via team-lead.'),
    t('Only cross-agent channel — worker_bridge (/32 + X-Bridge-Token) → :9099; A2A rides the same governed channel.'),
    t('Single source of knowledge — knowledge/ (approved baseline + security keys); version-hash aligned fleet-wide.'),
    t('Governed self-evolution — new skills pass worker-c /skill-review (SkillOS quality gate) before landing.'),
  ];
  return html`<div class="viewfade"><div class="viewhd"><h2>${t('Architecture')}</h2><span class="lbl">${t('Nemoclaw × OpenShell × Hermes · governed 4-node fleet')}</span></div>
    <${Panel} title=${t('Topology')} label=${t('human at the apex · hub-and-spoke')}>
      <div class="archmap">
        <div class="archrow"><div class="archbox human">${t('Human')} <span class="muted">· Telegram / Email · approval_token</span></div></div>
        <div class="archconn">↓ ${t('request')} · ↑ ${t('report / escalate')}</div>
        <div class="archplane">
          <div class="archplane-hd"><span class="archplane-mark">◆</span> <b>Nemoclaw</b> <span class="muted">· ${t('control plane · provisions the sandboxes · policy · routes inference')}</span></div>
          <div class="archrow"><div class="osh"><span class="oshtag">openshell</span><div class="archbox lead">${dot((nodes.find(n => n.tag === 'lead') || {}).up)} <b>team-lead</b> <span class="muted">${t('front desk · coordinate · execute worker-c verdicts')}</span></div></div></div>
          <div class="archconn">↓ worker_bridge (/32 + token) · A2A · :9099</div>
          <div class="archrow archworkers">${['ops', 'sec', 'gov'].map((tag) => { const n = nodes.find(x => x.tag === tag) || {}; const nm = tag === 'ops' ? 'worker-a' : tag === 'sec' ? 'worker-b' : 'worker-c'; const zn = tag === 'ops' ? 'A' : tag === 'sec' ? 'B' : 'C';
            return html`<div key=${tag} class="osh"><span class="oshtag">openshell</span><div class=${'archbox w-' + tag}>${dot(n.up)} <b>${nm}</b> <span class="tag ${'g'}">${t(tag)}</span><div class="muted" style=${{ fontSize: '11px', marginTop: '3px' }}>zone ${zn}</div></div></div>`; })}</div>
        </div>
        <div class="archconn">↓ ${t('scoped egress · L7 deny-by-default')}</div>
        <div class="archrow"><div class="archbox device">${dot((d.devices && d.devices[0] && d.devices[0].online) === true)} ASUS EBG19P <span class="muted">· ${t('real device')}</span></div>
          <div class="archbox ext">GitHub · NVD · OSV <span class="muted">· ${t('upstream intel')}</span></div>
          <div class="archbox ext">Jira <span class="muted">· ${t('escalations')}</span></div></div>
        <div class="archnim">${dot(d.inference && d.inference.reachable !== false)} ${t('local NIM')} — Nemotron 3 Super 120B · <span class="mono">/v1</span> · ${t('all nodes route here')}</div>
      </div>
    </${Panel}>
    <div class="grid1" style=${{ marginTop: '12px' }}>
      <${Panel} title=${t('The four layers')} label=${t('what each does')}>
        <div class="archlayers">${layers.map(l => html`<div key=${l.k} class="archlayer"><div class="archlayer-h"><span class="dot" style=${{ background: l.color, color: l.color }}></span><b>${l.title}</b> <span class="muted">${l.role}</span></div><div class="muted" style=${{ fontSize: '12.5px', marginTop: '4px' }}>${l.desc}</div></div>`)}</div>
      </${Panel}>
      <${Panel} title=${t('Governance invariants')} label=${t('always true')}>
        <ul class="archrules">${rules.map((r, i) => html`<li key=${i}>${r}</li>`)}</ul>
      </${Panel}>
    </div>
  </div>`;
});
const VIEWS = {
  overview: { label: 'Overview', comp: OverviewView },
  architecture: { label: 'Architecture', comp: ArchitectureView },
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
  { key: 'monitor', items: ['overview', 'architecture', 'flow', 'fleet'] },
  { key: 'govern', items: ['security', 'governance', 'changectrl', 'audit'] },
  { key: 'system', items: ['proactive', 'admin', 'settings'] },
];
const NAV_ICON = {
  architecture: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="8.5" y="14" width="7" height="7" rx="1"/><path d="M6.5 10v2h11v-2M12 12v2"/>',
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
        <span>${t(VIEWS[k].label)}</span>${counts[k] != null ? html`<span class=${"cnt" + (k === "security" && counts[k] > 0 ? " sev" : "")}>${counts[k]}</span>` : null}</a>`)}
    </div>`)}</nav>
    <div class="railfoot"><span class="avatar">${(me.email || 'op')[0].toUpperCase()}</span>
      <div style=${{ minWidth: 0 }}><div style=${{ fontSize: '12px', fontWeight: 600 }}>${me.email || 'operator'}</div>
      <div style=${{ fontSize: '10.5px', color: 'var(--ink3)' }}>${me.role || ''}</div></div></div>
  </aside>`;
}

function Skeleton() {
  const bar = (w, h) => html`<div class="skq" style=${{ width: w, height: (h || 14) + 'px' }}></div>`;
  return html`<div class="app"><aside class="rail">
      <div class="brand"><span class="mark"></span><div>${bar('80px', 14)}<div style=${{ height: '6px' }}></div>${bar('54px', 8)}</div></div>
      <nav class="nav">${[0, 1, 2, 3, 4, 5, 6].map(i => html`<div key=${i} class="skq" style=${{ height: '30px', margin: '4px 0', borderRadius: '9px' }}></div>`)}</nav>
    </aside>
    <main class="main">
      <header class="top"><div>${bar('120px', 18)}<div style=${{ height: '6px' }}></div>${bar('220px', 10)}</div></header>
      <section class="kpis">${[0, 1, 2, 3].map(i => html`<div key=${i} class="kpi">${bar('60%', 10)}<div style=${{ height: '10px' }}></div>${bar('45%', 26)}<div style=${{ height: '10px' }}></div>${bar('80%', 9)}</div>`)}</section>
      <div class="grid"><div class="col"><div class="panel"><div class="pb">${bar('40%', 14)}<div style=${{ height: '14px' }}></div><div class="skq" style=${{ height: '190px', borderRadius: '10px' }}></div></div></div></div>
        <div class="col"><div class="panel"><div class="pb">${bar('40%', 14)}<div style=${{ height: '14px' }}></div>${[0, 1, 2, 3].map(i => html`<div key=${i} class="skq" style=${{ height: '38px', margin: '7px 0', borderRadius: '8px' }}></div>`)}</div></div></div>
      </div>
    </main>
  </div>`;
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
  if (loading || !d) return html`<${Skeleton}/>`;

  const View = (VIEWS[route] || VIEWS.overview).comp;
  const counts = { security: (d.cve.findings.length + d.cert.findings.length) || null, governance: d.governance.denied || null };
  return html`<div class="app">
    <${PwGate} me=${d.me}/>
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
              { k: t('name'), v: nd.name, mono: true }, { k: t('status'), v: statusBullet(nd.up, t('online'), t('offline')) },
              { k: t('role'), v: nd.role || '—' }, { k: t('zone'), v: nd.zone || '—' }, { k: t('port'), v: ':' + nd.port, mono: true },
              { k: t('tag'), v: nd.tag || '—' }, { k: t('caps'), v: (nd.caps || []).join(', ') || '—' } ] })}><${Dot} s=${nd.up ? 'on' : 'off'}/>${nd.name}</span>`)}
            <span class="seg nodeseg" title=${t('Inference detail')} onClick=${() => openDrawer({ title: t('Inference detail'), sub: 'NIM', rows: [
              { k: t('model'), v: d.inference.model || '—', mono: true },
              { k: t('provider'), v: d.inference.provider || 'nim', mono: true },
              { k: t('status'), v: statusBullet(d.inference.reachable !== false, t('reachable'), t('unreachable')) },
              { k: t('endpoint'), v: d.inference.endpoint || d.inference.base_url || 'inference.local/v1', mono: true } ] })}>NIM · ${d.inference.model} <${Dot} s=${d.inference.reachable !== false ? 'on' : 'off'}/></span>
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
