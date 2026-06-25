#!/usr/bin/env bash
# --- nemofleet: locate repo root + load shared library ---
__src="${BASH_SOURCE[0]:-$0}"; __dir="$(cd "$(dirname "$(readlink -f "$__src" 2>/dev/null || echo "$__src")")" && pwd)"
while [ "$__dir" != / ] && [ ! -e "$__dir/.nemofleet-root" ]; do __dir="$(dirname "$__dir")"; done
NEMOFLEET_ROOT="$__dir"; DIR="$NEMOFLEET_ROOT"; . "$NEMOFLEET_ROOT/lib/common.sh"
# jira-reset.sh — demo 前重置工單佇列(OpenClaw 本機工單 + host mock Jira),讓現場掃描能「現開」工單。
# 注意:cve-scan-history.jsonl(定期掃描歷史)刻意保留 —— 那是「定期」的時間戳證據。
set -uo pipefail
DIR=$NEMOFLEET_ROOT
cd "$DIR"; :
[ -n "$CT_O" ] || { echo "[jira-reset] my-assistant 容器未跑" >&2; exit 1; }
docker exec -u 0 "$CT_O" sh -c 'rm -f /sandbox/.openclaw/workspace/it-task/jira-queue.jsonl /sandbox/.openclaw/workspace/it-task/jira-tickets/*.json 2>/dev/null; true'
rm -f /tmp/jira-mock-issues.jsonl
echo "[jira-reset] OpenClaw 工單佇列 + host mock Jira 已清空(掃描歷史保留;demo 可現開單)"
