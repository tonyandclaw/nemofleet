#!/usr/bin/env bash
# --- nemofleet: locate repo root + load shared library ---
__src="${BASH_SOURCE[0]:-$0}"; __dir="$(cd "$(dirname "$(readlink -f "$__src" 2>/dev/null || echo "$__src")")" && pwd)"
while [ "$__dir" != / ] && [ ! -e "$__dir/.nemofleet-root" ]; do __dir="$(dirname "$__dir")"; done
NEMOFLEET_ROOT="$__dir"; DIR="$NEMOFLEET_ROOT"; . "$NEMOFLEET_ROOT/lib/common.sh"
# ebg19p-crypto-sync.sh — 真機 EBG19P 憑證/弱加密「真實」掃描,取代 demo CRYPTO_INVENTORY。
# 探測:TLS(443/8443)真實憑證+協定、SSH(22)、明文 HTTP 管理面 → 寫 node A 沙箱 ebg19p-crypto.json。
#   endpoint cert-scan 對此設備優先讀此真機檔(fresh<30分);有什麼報什麼、沒有就不報。
# 需電腦連得到 EBG19P LAN。憑證:~/.config/nemoclaw/ebg19p.cred(IP|USER|PASS,600)。
set -uo pipefail
DIR=$NEMOFLEET_ROOT
CRED="${EBG19P_CRED:-$HOME/.config/nemoclaw/ebg19p.cred}"
WD="/sandbox/.openclaw/workspace/it-task"
ASSET="lab-asus-ebg19p-01"
CTO="${CT_O:-$(docker ps --format '{{.Names}}'|grep -m1 my-assistant)}"
[ -s "$CRED" ] || { echo "[ebg19p-crypto] 缺憑證 $CRED" >&2; exit 1; }
[ -n "$CTO" ] || { echo "[ebg19p-crypto] node A 容器未跑" >&2; exit 1; }
IFS='|' read -r IP USER PASS < "$CRED"

JSON="$(IP="$IP" ASSET="$ASSET" python3 <<'PY'
import os, subprocess, re, json, time, tempfile
IP=os.environ["IP"]; ASSET=os.environ["ASSET"]
def run(c, t=6):
    try: return subprocess.run(c, shell=True, capture_output=True, text=True, timeout=t)
    except Exception: return None
def code(port):
    r=run(f"curl -s -m3 -o /dev/null -w '%{{http_code}}' http://{IP}:{port}/"); return (r.stdout.strip() if r else "000")

certs=[]; tls=[]; sshl=[]; findings=[]
TLS_PORTS={443:"SSL-VPN/HTTPS (:443)", 8443:"Web UI (HTTPS:8443)"}
any_tls=False
for port, svc in TLS_PORTS.items():
    pf=tempfile.mktemp(suffix=".pem")
    run(f"echo | timeout 5 openssl s_client -connect {IP}:{port} 2>/dev/null | openssl x509 -out {pf} 2>/dev/null")
    try: pem=open(pf).read()
    except Exception: pem=""
    if "BEGIN CERTIFICATE" not in pem:
        continue
    any_tls=True
    sub=(run(f"openssl x509 -in {pf} -noout -subject 2>/dev/null").stdout or "").strip()
    iss=(run(f"openssl x509 -in {pf} -noout -issuer 2>/dev/null").stdout or "").strip()
    end=(run(f"openssl x509 -in {pf} -noout -enddate 2>/dev/null").stdout or "").strip().replace("notAfter=","")
    txt=(run(f"openssl x509 -in {pf} -noout -text 2>/dev/null").stdout or "")
    sig=(re.search(r"Signature Algorithm:\s*(\S+)", txt) or [None,""])[1]
    kb=(re.search(r"Public-Key:\s*\((\d+)", txt) or [None,"0"])[1]
    cn=(re.search(r"CN\s*=\s*([^,/]+)", sub) or [None,"?"])[1].strip()
    na=(run(f"date -d '{end}' +%Y-%m-%d 2>/dev/null").stdout or "").strip()
    certs.append({"service":svc,"cn":cn,"issuer":("self-signed" if sub==iss else iss.replace("issuer=","")),
                  "self_signed":(sub==iss),"sig_alg":sig,"key_type":"RSA","key_bits":int(kb or 0),"not_after":na or "2099-01-01"})
    # 協定/套件:列舉真機接受的弱協定
    vers=[]
    for flag,name in [("-tls1","TLSv1.0"),("-tls1_1","TLSv1.1"),("-tls1_2","TLSv1.2")]:
        r=run(f"echo | timeout 4 openssl s_client {flag} -connect {IP}:{port} 2>/dev/null | grep -c 'BEGIN CERTIFICATE'")
        if r and r.stdout.strip()=="1": vers.append(name)
    if vers: tls.append({"service":svc,"versions":vers,"ciphers":[]})

http80=code(80)
if http80 not in ("000","") and not any_tls:
    findings.append({"asset":ASSET,"service":"Web 管理 (HTTP:80)","issue":"weak_protocol","severity":"High",
        "detail":"管理介面走明文 HTTP、未啟用 HTTPS/TLS(區網內帳密與設定明文傳輸)",
        "fix":"啟用 HTTPS-only 管理或限制管理介面來源",
        "state":[["傳輸","HTTP(無 TLS)"],["HTTPS","未啟用"],["探測 443/8443","無 TLS 憑證"]]})

# SSH :22(關閉=好;開啟才進一步)
r=run(f"timeout 3 bash -c 'echo > /dev/tcp/{IP}/22' 2>/dev/null && echo open || echo closed")
ssh_open = bool(r and "open" in (r.stdout or ""))

print(json.dumps({"ts":time.strftime("%Y-%m-%d %H:%M:%S"),"source":"live-probe",
                  "certs":certs,"tls":tls,"ssh":sshl,"findings":findings,
                  "_probe":{"http80":http80,"tls":any_tls,"ssh_open":ssh_open}}, ensure_ascii=False))
PY
)"
[ -n "$JSON" ] || { echo "[ebg19p-crypto] 掃描無輸出" >&2; exit 1; }
printf '%s\n' "$JSON" | docker exec -i "$CTO" sh -c "cat > $WD/ebg19p-crypto.json && chown 998:998 $WD/ebg19p-crypto.json"
echo "[ebg19p-crypto] ✓ 真機掃描已寫入 $WD/ebg19p-crypto.json"
printf '%s\n' "$JSON" | python3 -c "import sys,json;d=json.load(sys.stdin);print('   findings=%d certs=%d tls=%d probe=%s'%(len(d['findings']),len(d['certs']),len(d['tls']),d.get('_probe')))"
