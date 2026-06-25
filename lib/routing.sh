#!/usr/bin/env bash
# routing.sh — single source of truth for task routing between the two harnesses.
# dispatch.sh and route.sh both call this so the heuristics never diverge.
#
# route_decide "<task>" -> echoes "openclaw" or "hermes"
#   OpenClaw = IT operator(網管/診斷/bug 修復/部署 的實作)
#   Hermes   = 對人前台 + 自我進化(規劃/解釋/報告/需求,預設)
route_decide() {
  local lc; lc=$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')
  if printf '%s' "$lc" | grep -qiE '網路|網管|連線|ping|port|埠|防火牆|firewall|dns|部署|deploy|服務|service|重啟|restart|log|日誌|診斷|diagnose|debug|bug|修復|fix|patch|ops|devops|ssh|憑證|cert|監控|monitor|sandbox|容器|container'; then
    echo openclaw   # IT operator:動手做
  else
    echo hermes     # 對人前台:接需求/規劃/解釋/報告(預設)
  fi
}
