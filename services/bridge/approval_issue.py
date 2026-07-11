#!/usr/bin/env python3
# approval_issue.py — deployed into team-lead's sandbox by boot-stack.sh (APPROVAL_KEY baked in at
# render time, same technique as the BRIDGETOKEN placeholder in SKILL.md files). Run this ONLY
# after a human has actually replied approving one specific action over Telegram — see
# skills/hermes/firmware-approval/SKILL.md for the exact flow this is a step of. It does not talk
# to Telegram itself and does not know whether a human really approved; that check happens before
# this runs, in the calling skill's conversation turn.
#
# Usage: python3 approval_issue.py <action> '<params-json>' <issuer> [ttl_seconds]
#   action     — exactly "rollback" or "firmware-apply" (must match what worker-c's endpoint checks)
#   params     — exactly the action's params, e.g. '{"to": "bk-20260710-120000"}' for rollback
#   issuer     — the human's identity (Telegram username/user id), NOT "team-lead" — this is what
#                makes worker-c's approval-history audit trail traceable to a real person
#   ttl_seconds — default 300; keep short, this is a one-time approval, not a standing credential
import json, sys
sys.path.insert(0, __file__.rsplit("/", 1)[0])
import wi_approval

APPROVAL_KEY = "APPROVALKEY"   # rendered in by boot-stack.sh from services/bridge/.approval-key


def main():
    if len(sys.argv) < 4:
        print("usage: approval_issue.py <action> '<params-json>' <issuer> [ttl_seconds]", file=sys.stderr)
        sys.exit(1)
    action, params_raw, issuer = sys.argv[1], sys.argv[2], sys.argv[3]
    ttl = int(sys.argv[4]) if len(sys.argv) > 4 else 300
    params = json.loads(params_raw or "{}")
    print(wi_approval.issue(action, params, issuer, APPROVAL_KEY, ttl_s=ttl))


if __name__ == "__main__":
    main()
