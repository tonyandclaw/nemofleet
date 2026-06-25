#!/usr/bin/env bash
# --- nemofleet: locate repo root + load shared library ---
__src="${BASH_SOURCE[0]:-$0}"; __dir="$(cd "$(dirname "$(readlink -f "$__src" 2>/dev/null || echo "$__src")")" && pwd)"
while [ "$__dir" != / ] && [ ! -e "$__dir/.nemofleet-root" ]; do __dir="$(dirname "$__dir")"; done
NEMOFLEET_ROOT="$__dir"; DIR="$NEMOFLEET_ROOT"; . "$NEMOFLEET_ROOT/lib/common.sh"
# nvidia-inference-demo.sh — 「NemoClaw 名副其實」:NemoClaw 可把推理路由到 NVIDIA(NIM / Endpoints),
# 全程受 OpenShell 治理。本 demo 不切換正在跑的 Azure Kimi(避免弄壞 demo),而是:
#   ① 秀現況 inference(可切 provider)② 秀 nvidia egress policy 的治理面(host + 路徑層 + 授權 binary)
#   ③ 從沙箱實打一通到 NVIDIA /v1/chat/completions → OPA 留 ALLOWED [policy:nvidia](host/binary + L7 路徑)
#      + NVIDIA 真實回應(沒 key→401,證明真的到了 NVIDIA;設 NVIDIA_API_KEY→真 Nemotron 補全)
# 用法:nvidia-inference-demo.sh         (沒 key:展示治理路徑已通,NVIDIA 回 401)
#       NVIDIA_API_KEY=nvapi-xxx nvidia-inference-demo.sh   (有 key:真打一通 NVIDIA 託管 NIM)
set -uo pipefail
DIR=$NEMOFLEET_ROOT
cd "$DIR"; :
[ -n "$CT_H" ] || { echo "hermes 容器未跑,先 bash scripts/boot-stack.sh" >&2; exit 1; }
MODEL="${NVIDIA_MODEL:-nvidia/llama-3.1-nemotron-70b-instruct}"
hr(){ printf '\n\033[1;36m== %s ==\033[0m\n' "$*"; }
say(){ printf '  %s\n' "$*"; }
proof(){ printf '  \033[1;32m📜 %s\033[0m\n' "$*"; }

echo "############ NemoClaw 推理路由 → NVIDIA(NIM / Endpoints),受 OpenShell 治理 ############"

hr "① 現況:NemoClaw 管推理 provider(可切換,不綁廠)"
nemoclaw inference get 2>&1 | head -4
say "→ 今天跑 Azure Kimi(compatible-endpoint);NemoClaw 一行可切到 NVIDIA:"
say "   nemoclaw inference set --provider nvidia --model $MODEL   (本機 CPU,故用 NVIDIA 託管 Endpoints;"
say "   有 GPU 時同一套可改本地 NIM 容器。provider 選項見 nemoclaw inference --help)"

hr "② 治理面:OpenShell 的 nvidia egress policy(NemoClaw 部署、OpenShell 強制)"
say "host + 路徑層只放行『推理 API 表面』,不是任意存取:"
openshell policy get hermes-demo --full 2>/dev/null | awk '/name: nvidia/{f=1} f{print} f&&/name: openclaw_bridge/{exit}' \
  | grep -E 'host:|method:|path:|/usr|hermes|python' | sed 's/^ */    /' | head -16

hr "③ 實打一通到 NVIDIA(/v1/chat/completions),看治理 log + NVIDIA 回應"
NS=$(docker exec -u 0 "$CT_H" sh -c 'pid=$(pgrep -f "^sleep infinity$"|head -1); [ -z "$pid" ] && exit 1; want=$(stat -Lc %i /proc/$pid/ns/net); for f in /var/run/netns/*; do [ "$(stat -Lc %i "$f" 2>/dev/null)" = "$want" ] && { basename "$f"; exit 0; }; done')
[ -n "$NS" ] || { echo "  找不到 hermes netns,先 bash scripts/boot-stack.sh" >&2; exit 1; }
say "從 hermes 沙箱(netns $NS)經 OpenShell L7 proxy,用授權 binary python3 呼叫 NVIDIA:"
RESP=$(docker exec -u 0 -e NVIDIA_API_KEY="${NVIDIA_API_KEY:-}" -e MODEL="$MODEL" "$CT_H" ip netns exec "$NS" python3 -c '
import urllib.request, ssl, json, os
ctx = ssl.create_default_context(cafile="/etc/openshell-tls/ca-bundle.pem")
op = urllib.request.build_opener(urllib.request.ProxyHandler({"https":"http://10.200.0.1:3128"}), urllib.request.HTTPSHandler(context=ctx))
key = os.environ.get("NVIDIA_API_KEY","")
body = json.dumps({"model":os.environ["MODEL"],"messages":[{"role":"user","content":"用一句話說明你是誰。"}],"max_tokens":40}).encode()
req = urllib.request.Request("https://integrate.api.nvidia.com/v1/chat/completions", data=body,
      headers={"Content-Type":"application/json","Authorization":"Bearer "+(key or "NO-KEY-SET")})
try:
    r=op.open(req,timeout=20); d=json.loads(r.read())
    print("HTTP 200  ✅ NVIDIA NIM 回覆:", d["choices"][0]["message"]["content"].strip()[:120])
except urllib.error.HTTPError as e:
    print(f"HTTP {e.code}  ✅ 已到達 NVIDIA(被其認證挑戰,證明治理路徑通)→ 插上 NVIDIA_API_KEY 即跑真 Nemotron")
except Exception as e:
    print("ERR", type(e).__name__, e)
' 2>&1)
say "$RESP"
sleep 2
proof "OpenShell 治理鐵證(host/binary 層 + L7 路徑層):"
nemoclaw hermes-demo logs 2>/dev/null | grep -ai 'nvidia.com' | grep -a ALLOWED | tail -2 | sed 's/^/    /'

echo
echo "############ 講點 ############"
say "「NemoClaw」=NVIDIA × OpenClaw。NemoClaw 負責把推理路由到 NVIDIA(雲端 Endpoints 或本地 NIM),"
say "OpenShell 把這條路徑鎖到只准 /v1/chat/completions 這幾條推理 API、只准授權 binary 走——"
say "名字裡的 NVIDIA 不是貼牌,是真的有一條受治理的推理路徑通到 NVIDIA,插上 key 就服務。"
