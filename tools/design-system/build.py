#!/usr/bin/env python3
# build.py — 從 NemoClaw dashboard 的設計系統,產出 Claude Design 元件庫。
# 單一來源:SHARED_CSS = dashboard <style> 全文 + .dsdark(暗色 token)+ preview 殼。
# 每個元件 → claude-design/components/<name>/index.html(首行 @dsCard 標記),明暗雙主題並排。
import os

OUT = os.path.join(os.path.dirname(__file__), "components")

# ── dashboard <style> 全文(bridge/agent-dashboard.py 的設計系統,逐字)──
DASH_CSS = r"""
:root{
 --bg:#fafafc;--card:#ffffff;--card2:#f3f4f7;--seg:#ececf0;--tx:#111114;--tx2:#5f636b;--tx3:#9398a1;--line:#e7e8ee;
 --accent:#0066ff;--ok:#0a875a;--okbg:#e6f5ee;--warn:#946200;--warnbg:#fbf0d9;--danger:#d11a2a;--dangerbg:#fbe9ea;--purple:#6e56cf;--purplebg:#efeafc;--accentbg:#e9f1ff;
 --sh1:0 0 0 1px rgba(20,20,40,.04);--sh2:0 2px 8px rgba(20,20,45,.05),0 14px 34px rgba(20,20,45,.05);
 --r:18px;--rs:10px;
}
.dsdark{
 --bg:#0b0b0d;--card:#161618;--card2:#202024;--seg:#26262b;--tx:#f2f2f4;--tx2:#a0a3ab;--tx3:#70737b;--line:#2a2a31;
 --accent:#4d8dff;--ok:#2ecc8f;--okbg:#0f3023;--warn:#e0a030;--warnbg:#2e2410;--danger:#ff5a66;--dangerbg:#331417;--purple:#a18aff;--purplebg:#1f1a36;--accentbg:#12233f;
 --sh1:0 0 0 1px rgba(255,255,255,.05);--sh2:0 2px 10px rgba(0,0,0,.35),0 16px 40px rgba(0,0,0,.45);
}
*{box-sizing:border-box;margin:0;padding:0}
.dsroot{color:var(--tx);font-variant-numeric:tabular-nums;
 font:14.5px/1.55 -apple-system,BlinkMacSystemFont,"SF Pro Display","SF Pro Text","Inter","Helvetica Neue","PingFang TC","Microsoft JhengHei","Noto Sans TC",system-ui,sans-serif;
 -webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility}
a{color:inherit;text-decoration:none}
.seg{display:inline-flex;background:var(--seg);border-radius:11px;padding:3px;gap:2px}
.seg button{border:0;background:transparent;color:var(--tx2);font:inherit;font-size:12.5px;font-weight:560;padding:5px 13px;border-radius:8px;cursor:pointer;transition:.18s;white-space:nowrap}
.seg button:hover{color:var(--tx)}
.seg button.on{background:var(--card);color:var(--tx);box-shadow:0 1px 3px rgba(0,0,0,.14)}
.tlabel{color:var(--tx3);font-size:12px;font-weight:560}
.btn{border:1px solid var(--line);background:var(--card);color:var(--tx);font:inherit;font-size:12.5px;font-weight:560;padding:7px 15px;border-radius:980px;cursor:pointer;transition:.16s;box-shadow:var(--sh1)}
.btn:hover{background:var(--card2);transform:translateY(-1px)}.btn:active{transform:translateY(0) scale(.98)}
.btn[disabled]{opacity:.5;cursor:default;transform:none}
.bn{display:flex;align-items:center;gap:10px;border-radius:14px;padding:13px 18px;font-weight:600;font-size:13.5px;border:1px solid;margin-bottom:14px}
.bn:last-child{margin-bottom:0}
.bn.ok{background:var(--okbg);color:var(--ok);border-color:transparent}
.bn.bad{background:var(--dangerbg);color:var(--danger);border-color:var(--danger)}
.kpis{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}
a.kpi{background:var(--card);border:1px solid var(--line);border-radius:var(--r);padding:17px 18px;box-shadow:var(--sh2);text-decoration:none;color:inherit;display:block;position:relative}
.kpi .n{font-size:33px;font-weight:600;letter-spacing:-.035em;line-height:1.04}
.kpi .n small{font-size:14px;color:var(--tx3);font-weight:560;letter-spacing:0}
.kpi .l{color:var(--tx2);font-size:12.5px;margin-top:7px;font-weight:500}
.red{color:var(--danger)}.ok{color:var(--ok)}.mut{color:var(--tx2)}
.sec{font-size:12px;color:var(--tx3);margin:0 4px 13px;font-weight:680;letter-spacing:.05em;text-transform:uppercase}
.grid{display:grid;gap:16px}.g2{grid-template-columns:1fr 1fr}
.card{background:var(--card);border:1px solid var(--line);border-radius:var(--r);padding:19px 20px;box-shadow:var(--sh2)}
.cardlink{display:block}
.ct{font-size:12.5px;color:var(--tx2);font-weight:600;margin-bottom:14px;display:flex;align-items:center;gap:9px}
.ct b{color:var(--tx);font-size:14.5px;font-weight:660}
.ico{width:25px;height:25px;border-radius:8px;display:grid;place-items:center;font-size:13px;flex:0 0 auto}
.kv{display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-top:1px solid var(--line);font-size:14px}
.kv:first-of-type{border-top:0}.kv .k{color:var(--tx2)}.kv .v{font-weight:600}
.pill{padding:3px 11px;border-radius:980px;font-size:12px;font-weight:600;white-space:nowrap}
.pill.ok{color:var(--ok);background:var(--okbg)}.pill.bad{color:var(--danger);background:var(--dangerbg)}
.dot{width:7px;height:7px;border-radius:50%;display:inline-block;margin-right:9px;vertical-align:middle}
.dot.g{background:var(--ok)}.dot.r{background:var(--danger)}.dot.a{background:var(--warn)}
.mono{font-family:"SF Mono",ui-monospace,Menlo,Consolas,monospace;font-size:12.5px;letter-spacing:-.01em}
.tags{margin:0 0 12px}.tag{display:inline-block;background:var(--card2);border-radius:7px;padding:3px 10px;margin:0 6px 6px 0;font-size:11.5px;color:var(--tx2);font-weight:560}
.chip{display:inline-block;background:var(--card2);border-radius:6px;padding:2px 8px;margin:2px 5px 2px 0;font-size:11.5px;font-family:"SF Mono",ui-monospace,monospace;color:var(--tx2)}
table.tb{width:100%;border-collapse:collapse;font-size:13px;margin-top:4px}
.tb th{text-align:left;color:var(--tx3);font-size:11px;font-weight:680;text-transform:uppercase;letter-spacing:.03em;padding:7px 10px;border-bottom:1px solid var(--line)}
.tb td{padding:9px 10px;border-bottom:1px solid var(--line)}
.tb tr:last-child td{border-bottom:0}
.sev{font-weight:800;font-size:11px;text-transform:uppercase;letter-spacing:.02em}.sev.high{color:var(--danger)}.sev.med{color:var(--warn)}
.split{display:flex;gap:20px;align-items:center;margin-top:4px}
.legend{font-size:12.5px;color:var(--tx2);line-height:2}.legend i{display:inline-block;width:9px;height:9px;border-radius:3px;margin-right:7px}
.stat{display:flex;gap:10px;margin-top:14px}.stat .s{background:var(--card2);border-radius:12px;padding:12px;flex:1;text-align:center}
.stat .s b{display:block;font-size:22px;font-weight:600;letter-spacing:-.02em}.stat .s span{font-size:11.5px;color:var(--tx2)}
.bar{display:flex;align-items:center;gap:11px;margin:11px 0;font-size:13px}
.bar .bl{width:172px;color:var(--tx2);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.bar .bt{flex:1;height:8px;background:var(--card2);border-radius:6px;overflow:hidden}
.bar .bf{height:100%;border-radius:6px;background:var(--accent)}
.bar .bv{width:48px;text-align:right;font-weight:600}
.evrow{border-top:1px solid var(--line)}.evrow:first-child{border-top:0}
.ev{display:flex;align-items:center;gap:10px;padding:8px 0;font-size:13px;cursor:pointer;border-radius:8px}
.ev .t{color:var(--tx3);font-size:11.5px;width:96px;flex:0 0 auto;font-variant-numeric:tabular-nums}
.evx{margin-left:8px;color:var(--tx3);font-size:10px;flex:0 0 auto}
.evd{padding:2px 10px 13px 106px;display:grid;grid-template-columns:1fr 1fr;gap:8px 22px}
.evdk{display:flex;flex-direction:column;gap:2px;font-size:12.5px;min-width:0}
.evdk span{color:var(--tx3);font-size:10.5px;text-transform:uppercase;letter-spacing:.03em}.evdk b{color:var(--tx);font-weight:600;word-break:break-word;font-family:"SF Mono",ui-monospace,monospace}
.ev .vb{font-size:10.5px;font-weight:800;width:54px;flex:0 0 auto;letter-spacing:.02em}.ev .vb.a{color:var(--ok)}.ev .vb.d{color:var(--danger)}
.ev .pol{font-size:12px;color:var(--accent);font-weight:600;font-family:"SF Mono",ui-monospace,monospace;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:40%}.ev .pol.d{color:var(--danger)}.ev .pol.n{color:var(--tx2)}.ev .tg{color:var(--tx3);font-size:12px;margin-left:auto;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:42%;font-family:"SF Mono",ui-monospace,monospace}
.gh{display:flex;gap:5px;align-items:flex-end;flex-wrap:wrap}
.gb{width:15px;height:26px;border-radius:4px;background:var(--ok)}.gb.f{background:var(--danger)}.gb.br{box-shadow:inset 0 0 0 2px var(--accent)}
.tlrow{display:flex;align-items:center;gap:13px;padding:9px 0;border-top:1px solid var(--line);font-size:13px}
.tlrow:first-child{border-top:0}
.tlt{color:var(--tx2);flex:0 0 90px;font-size:12px;font-variant-numeric:tabular-nums}
.tlty{flex:0 0 78px;font-size:11.5px;font-weight:600;color:var(--tx2)}
.tlty.gov{color:var(--accent)}.tlty.jira{color:var(--warn)}.tlty.audit{color:var(--purple)}.tlty.guard{color:var(--ok)}
.tla{flex:0 0 auto;font-weight:600;color:var(--tx)}
.tla.d{color:var(--danger)}.tla.a{color:var(--ok)}.tla.w{color:var(--warn)}
.tlb{flex:1;min-width:0;color:var(--tx2);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.dsec{font-size:11px;color:var(--tx3);font-weight:680;letter-spacing:.05em;text-transform:uppercase;margin:0 2px 9px}
.acts{display:flex;gap:9px;flex-wrap:wrap;margin-top:15px}
"""

PREVIEW_CSS = """
body{background:#e7e9ef;padding:22px}
.dsstage{display:flex;gap:20px;flex-wrap:wrap;align-items:flex-start}
.dspanel{flex:1 1 380px;min-width:320px;background:var(--bg);border:1px solid var(--line);border-radius:20px;padding:20px}
.dslabel{font:10.5px/1 -apple-system,sans-serif;font-weight:800;letter-spacing:.1em;text-transform:uppercase;color:#9aa0ab;margin-bottom:13px}
.swatch{display:flex;align-items:center;gap:10px;padding:6px 0;font-size:12.5px}
.sw{width:34px;height:22px;border-radius:7px;border:1px solid var(--line);flex:0 0 auto}
.tyrow{display:flex;align-items:baseline;gap:14px;padding:6px 0;border-top:1px solid var(--line)}
.tyrow:first-child{border-top:0}.tyrow .tym{color:var(--tx3);font-size:11px;width:90px;flex:0 0 auto}
"""

# ── 元件清單:(name, group, light_html) ; 同一段 html 會渲染明、暗兩面板 ──
COMPONENTS = []
def comp(name, group, html):
    COMPONENTS.append((name, group, html))

comp("foundations-colors", "Foundations", """
<div class="dslabel">Color tokens</div>
""" + "".join(
    f'<div class="swatch"><span class="sw" style="background:var({v})"></span><span class="mono">{v}</span><span class="mut" style="margin-left:auto">{lbl}</span></div>'
    for v, lbl in [("--accent","accent / link"),("--ok","ok / online"),("--warn","needs-review"),
                   ("--danger","alert / denied"),("--purple","control plane"),("--card","surface"),
                   ("--card2","surface-2"),("--line","border"),("--tx","text"),("--tx2","text-muted")]))

comp("foundations-type", "Foundations", """
<div class="dslabel">Type scale</div>
<div class="tyrow"><span class="tym">h2 / 22</span><span style="font-size:22px;font-weight:660;letter-spacing:-.02em">總覽 Overview</span></div>
<div class="tyrow"><span class="tym">kpi / 33</span><span style="font-size:33px;font-weight:600;letter-spacing:-.035em">44</span></div>
<div class="tyrow"><span class="tym">body / 14.5</span><span>受管設備 · 全 ok</span></div>
<div class="tyrow"><span class="tym">section / 12</span><span class="sec" style="margin:0">關鍵指標 · 點擊深入</span></div>
<div class="tyrow"><span class="tym">mono / 12.5</span><span class="mono">172.18.0.2/32</span></div>
""")

comp("atoms-status", "Foundations", """
<div class="dslabel">Pills · dots · tags · severity</div>
<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:12px">
 <span class="pill ok">在線</span><span class="pill bad">離線</span>
 <span><span class="dot g"></span>online</span><span><span class="dot a"></span>review</span><span><span class="dot r"></span>alert</span></div>
<div style="margin-bottom:10px"><span class="tag">fix</span><span class="tag">monitor</span><span class="tag">cve</span><span class="tag">source</span></div>
<div style="margin-bottom:10px"><span class="chip">CVE-2023-48795</span><span class="chip">dropbear 2022.83-3</span></div>
<div><span class="sev high">High</span> &nbsp; <span class="sev med">Medium</span></div>
""")

comp("controls-buttons", "Controls", """
<div class="dslabel">Buttons · segmented · filter</div>
<div class="acts" style="margin-top:0;margin-bottom:14px"><button class="btn">↻ 重新整理</button><button class="btn">🛡 套用安全基準</button><button class="btn" disabled>執行中…</button></div>
<div style="display:flex;align-items:center;gap:11px;margin-bottom:12px"><span class="tlabel">節點篩選</span>
 <div class="seg"><button class="on">全部</button><button>運維 A</button><button>資安 B</button></div></div>
<div class="seg"><button class="on">總覽</button><button>5s</button><button>15s</button><button>30s</button></div>
""")

comp("banner", "Components", """
<div class="dslabel">Status banner</div>
<div class="bn ok">✓ 全系統正常 · 兩節點各司其職 · 無告警</div>
<div class="bn bad">⚠︎ 節點 A 離線　｜　lab-asus-ebg19p-01 ALERT</div>
""")

comp("kpi", "Components", """
<div class="dslabel">KPI tiles</div>
<div class="kpis">
 <a class="kpi"><div class="n">2 <small>/ 2</small></div><div class="l">OpenClaw 節點在線</div></a>
 <a class="kpi"><div class="n"><span class="red">3</span></div><div class="l">越權擋下 DENIED</div></a>
 <a class="kpi"><div class="n">44 秒</div><div class="l">修復 MTTR</div></a>
</div>
""")

comp("card-component", "Components", """
<div class="dslabel">Component card</div>
<div class="card">
 <div class="ct"><span class="ico" style="background:var(--card2);color:var(--purple)">◆</span>NemoClaw · <b>管理層</b></div>
 <div class="kv"><span class="k">生命週期 / 復原</span><span class="v">12 快照</span></div>
 <div class="kv"><span class="k">最新還原點</span><span class="v mono">combine-pre-loop-0612</span></div>
</div>
""")

comp("card-node", "Components", """
<div class="dslabel">Node card</div>
<a class="card cardlink">
 <div class="ct"><span class="ico" style="background:var(--card2);color:var(--ok)">🔧</span>節點 A · <b>IT 運維 / 網路管理</b><span style="margin-left:auto"><span class="pill ok">在線</span></span></div>
 <div class="tags"><span class="tag">fix</span><span class="tag">monitor</span></div>
 <div class="kv"><span class="k">網路設備健康</span><span class="v">3/3 設備 ok</span></div>
 <div class="mut" style="font-size:12px;margin-top:9px">查看完整詳情 →</div>
</a>
""")

comp("viz-donut", "Data viz", """
<div class="dslabel">CVE triage donut</div>
<div class="card"><div class="ct"><span class="ico" style="background:var(--card2);color:var(--danger)">🛡</span>機隊 CVE 分級 · <b>掃 6 台</b></div>
<div class="split">
 <div style="position:relative;width:108px;height:108px;flex:0 0 auto"><div style="width:108px;height:108px;border-radius:50%;background:conic-gradient(var(--danger) 0% 33%,var(--warn) 33% 50%,#1aa05e 50% 88%,#9aa3af 88% 100%);-webkit-mask:radial-gradient(transparent 56%,#000 57%);mask:radial-gradient(transparent 56%,#000 57%)"></div><div style="position:absolute;inset:0;display:grid;place-items:center"><div style="text-align:center"><div style="font-size:27px;font-weight:600">4</div><div style="font-size:11px;color:var(--tx2)">affected</div></div></div></div>
 <div class="legend"><div><i style="background:var(--danger)"></i>affected 4</div><div><i style="background:var(--warn)"></i>needs_review 2</div><div><i style="background:#1aa05e"></i>not_affected 9</div><div><i style="background:#9aa3af"></i>inventory_gap 1</div></div>
</div></div>
""")

comp("viz-spark-stat", "Data viz", """
<div class="dslabel">Sparkline · stats</div>
<div class="card"><div class="ct"><span class="ico" style="background:var(--card2);color:var(--accent)">📶</span>WAN 流量 · <b>EBG19P</b></div>
<div class="split" style="gap:24px">
 <svg width="120" height="30"><polygon points="0,30 0,18 20,20 40,12 60,16 80,7 100,11 120,5 120,30" fill="var(--accent)" opacity=".12"/><polyline points="0,18 20,20 40,12 60,16 80,7 100,11 120,5" fill="none" stroke="var(--accent)" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/><circle cx="120" cy="5" r="2.4" fill="var(--accent)"/></svg>
 <div class="stat" style="margin-top:0;flex:1"><div class="s"><b>62</b><span>目前 Mbps</span></div><div class="s"><b>48</b><span>基線均值</span></div><div class="s"><b>91</b><span>峰值</span></div></div>
</div></div>
""")

comp("viz-bars-guard", "Data viz", """
<div class="dslabel">Policy bars · guard heatmap</div>
<div class="card" style="margin-bottom:14px"><div class="ct">治理覆蓋 · <b>ALLOWED by policy</b></div>
 <div class="bar"><span class="bl">policy:greenmail_mail</span><div class="bt"><div class="bf" style="width:100%"></div></div><span class="bv">34</span></div>
 <div class="bar"><span class="bl">policy:openclaw_bridge</span><div class="bt"><div class="bf" style="width:62%"></div></div><span class="bv">21</span></div>
 <div class="bar"><span class="bl">policy:telegram</span><div class="bt"><div class="bf" style="width:30%"></div></div><span class="bv">10</span></div>
</div>
<div class="card"><div class="ct">守護歷史 <span class="mut" style="font-weight:400">綠pass · 紅fail · 框主鏈</span></div>
 <div class="gh">""" + "".join('<span class="gb"></span>' for _ in range(9)) + '<span class="gb br"></span>' + '<span class="gb f"></span>' + "".join('<span class="gb"></span>' for _ in range(3)) + """</div></div>
""")

comp("list-events", "Components", """
<div class="dslabel">Governance event stream</div>
<div class="card"><div class="ct"><span class="ico" style="background:var(--card2);color:var(--accent)">⚡</span>即時治理事件流</div>
 <div class="evrow"><div class="ev"><span class="t">06-18 17:42:11</span><span class="vb d">DENIED</span><span class="pol d">curl → api.telegram.org:443</span><span class="tg">no allow policy → denied</span><span class="evx">▾</span></div>
  <div class="evd"><div class="evdk"><span>動作</span><b>嘗試開啟網路連線 · NET:OPEN</b></div><div class="evdk"><span>判定引擎</span><b>opa</b></div><div class="evdk"><span>目標</span><b>api.telegram.org:443</b></div><div class="evdk"><span>原因</span><b>not in egress allowlist</b></div></div></div>
 <div class="evrow"><div class="ev"><span class="t">06-18 17:41:50</span><span class="vb a">ALLOWED</span><span class="pol">policy:greenmail_mail</span><span class="tg">mail :3993</span><span class="evx">▸</span></div></div>
</div>
""")

comp("list-timeline", "Components", """
<div class="dslabel">Activity timeline</div>
<div class="card"><div class="ct"><span class="ico" style="background:var(--card2);color:var(--purple)">◷</span>活動時間軸</div>
 <div class="tlrow"><span class="tlt">06-18 17:42</span><span class="tlty gov">⚡ 治理</span><span class="tla d">DENIED</span><span class="tlb">curl → api.telegram.org:443</span></div>
 <div class="tlrow"><span class="tlt">06-16 09:30</span><span class="tlty jira">🎫 工單</span><span class="tla w">NETOPS-…093001-02</span><span class="tlb">lab-asus-ebg19p-01 安全合規退化</span></div>
 <div class="tlrow"><span class="tlt">06-17 09:54</span><span class="tlty audit">🔧 處置</span><span class="tla d">harden</span><span class="tlb">登入失敗(192.168.50.1)</span></div>
 <div class="tlrow"><span class="tlt">06-15 00:53</span><span class="tlty guard">🛡 守護</span><span class="tla a">fails=0</span><span class="tlb">bridge PASS</span></div>
</div>
""")

comp("table", "Components", """
<div class="dslabel">Data table</div>
<div class="card"><div class="ct"><span class="ico" style="background:var(--card2);color:var(--danger)">⚠︎</span>Affected 弱點 · <b>已開 Jira 升級</b></div>
<table class="tb"><thead><tr><th>CVE</th><th>資產</th><th>元件</th><th>版本</th><th>嚴重度</th></tr></thead><tbody>
 <tr><td class="mono">CVE-2023-48795</td><td>openwrt-gateway-01</td><td>dropbear</td><td class="mono">2022.83-3</td><td><span class="sev med">Medium</span></td></tr>
 <tr><td class="mono">CVE-2023-5678</td><td>openwrt-gateway-01</td><td>openssl</td><td class="mono">3.0.12-1</td><td><span class="sev med">Medium</span></td></tr>
</tbody></table></div>
""")

comp("pattern-drawer", "Patterns", """
<div class="dslabel">Device drawer (slide-over content)</div>
<div class="dsec">設備身分</div>
<div class="card" style="margin-bottom:16px"><div class="kv"><span class="k">型號</span><span class="v mono">ASUS EBG19P</span></div><div class="kv"><span class="k">韌體</span><span class="v mono">3.0.0.4.386</span></div><div class="kv"><span class="k">WAN</span><span class="v mono">pppoe</span></div></div>
<div class="dsec">快速處置</div>
<div class="card"><div class="acts" style="margin-top:0"><button class="btn">↻ 強制同步</button><button class="btn">🛡 套用安全基準</button><button class="btn">⛔ 封鎖未授權</button></div></div>
""")

PAGE = """<!-- @dsCard group="{group}" -->
<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{name}</title><style>{css}{preview}</style></head>
<body>
 <div class="dsstage">
  <div class="dsroot dspanel"><div class="dslabel" style="color:#9aa0ab">☀ Light</div>{html}</div>
  <div class="dsroot dspanel dsdark" style="background:#0b0b0d"><div class="dslabel" style="color:#70737b">☾ Dark</div>{html}</div>
 </div>
</body></html>"""

def main():
    n = 0
    for name, group, html in COMPONENTS:
        d = os.path.join(OUT, name)
        os.makedirs(d, exist_ok=True)
        page = PAGE.format(group=group, name=name, css=DASH_CSS, preview=PREVIEW_CSS, html=html)
        with open(os.path.join(d, "index.html"), "w", encoding="utf-8") as f:
            f.write(page)
        n += 1
        print(f"  ✓ components/{name}/index.html  [{group}]")
    print(f"\n{n} components → {OUT}")

if __name__ == "__main__":
    main()
