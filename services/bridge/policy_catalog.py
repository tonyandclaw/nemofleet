# policy_catalog.py — load + validate the fleet's Action Catalog (the decision boundary).
#
# The catalog (policy/action-catalog.json) is the single, versioned, machine-readable statement of
# EVERY action the fleet may perform, with each action's trigger, blast radius, reversibility, and
# approval tier (auto | human | forbidden). It is the "明確清晰的決策邊界" — the boundary drawn on the
# wall. It is ENFORCED, not decorative: tests/unit/test_action_catalog.py binds it 1:1 to the code's
# real capabilities (worker-itops' EBG_ACTIONS/EBG_MULTI) and asserts every `forbidden` action is
# blocked by the guardrail. Change what the fleet can do → change this file, or CI fails.
#
# Pure (json only, no third-party deps → runs in CI unchanged) + direct-import (like wi_util/wi_review).
import json, os

DEFAULT_PATH = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                             "..", "..", "policy", "action-catalog.json"))
TIERS = ("auto", "human", "forbidden")
NVRAM_EFFECTS = ("nvram-apply", "nvram-multi")


def load(path=None):
    with open(path or DEFAULT_PATH, encoding="utf-8") as f:
        return json.load(f)


def actions(cat):
    return cat.get("actions", [])


def by_id(cat, aid):
    for a in actions(cat):
        if a.get("id") == aid:
            return a
    return None


def ids_by_tier(cat, tier):
    return {a["id"] for a in actions(cat) if a.get("approval_tier") == tier}


def nvram_action_ids(cat):
    # the subset of the catalog that maps to a concrete device nvram change (the auto/human tighten set)
    return {a["id"] for a in actions(cat) if (a.get("effect") or {}).get("type") in NVRAM_EFFECTS}


def gate(cat, action_id, allow_effects=None):
    """Runtime decision-boundary check for ONE action id. Returns {allow, tier, reason}. Denies an
    action the boundary does not sanction: an unknown id, a `forbidden` tier, or — when allow_effects
    is given — an effect type outside that set (e.g. a rollback/firmware id sent down the nvram path).
    A defense-in-depth FLOOR in front of the device: it does not replace the guardrail or the approval
    token, it guarantees nothing reaches the device that isn't a published, non-forbidden action of the
    expected kind. Pure — the caller decides fail-open vs fail-closed."""
    a = by_id(cat, action_id)
    if a is None:
        return {"allow": False, "tier": None, "reason": f"'{action_id}' is not in the decision boundary (action-catalog)"}
    tier = a.get("approval_tier")
    if tier == "forbidden":
        return {"allow": False, "tier": tier, "reason": f"'{action_id}' is forbidden by the decision boundary"}
    if allow_effects is not None and (a.get("effect") or {}).get("type") not in allow_effects:
        return {"allow": False, "tier": tier,
                "reason": f"'{action_id}' is not a device nvram action (effect={(a.get('effect') or {}).get('type')})"}
    return {"allow": True, "tier": tier, "reason": "within decision boundary"}


def validate(cat):
    """Return a list of human-readable problems (empty == valid). Encodes the schema + the invariants
    that make the boundary trustworthy, so this can also gate a future runtime action-gate, not just CI."""
    errs = []
    if not isinstance(cat.get("version"), int):
        errs.append("version must be an int")
    seen = set()
    for a in actions(cat):
        aid = a.get("id")
        if not aid:
            errs.append("an action is missing 'id'"); continue
        if aid in seen:
            errs.append(f"{aid}: duplicate id")
        seen.add(aid)
        if not a.get("title"):
            errs.append(f"{aid}: missing title")
        tier = a.get("approval_tier")
        if tier not in TIERS:
            errs.append(f"{aid}: approval_tier {tier!r} not in {TIERS}")
        eff = a.get("effect") or {}
        if not eff.get("type"):
            errs.append(f"{aid}: effect.type missing")
        rev = (a.get("reversibility") or {}).get("reversible")
        # INVARIANT — an `auto` (no-human) action must be a single-device nvram change AND reversible.
        # Nothing irreversible, multi-device, or firmware/rollback may ever run without a human.
        if tier == "auto":
            if eff.get("type") not in NVRAM_EFFECTS:
                errs.append(f"{aid}: auto action effect.type must be one of {NVRAM_EFFECTS}")
            if rev is not True:
                errs.append(f"{aid}: auto action must be reversible:true")
            if (a.get("blast_radius") or {}).get("scope") != "single-device":
                errs.append(f"{aid}: auto action blast_radius.scope must be 'single-device'")
            if not a.get("restores_invariant"):
                errs.append(f"{aid}: auto action must state the invariant it restores")
        # INVARIANT — a `forbidden` action carries a blocked_example so the negative test can prove the
        # guardrail actually stops it (boundary is provable, not merely declared).
        if tier == "forbidden":
            if eff.get("type") != "forbidden":
                errs.append(f"{aid}: forbidden action effect.type must be 'forbidden'")
            if not a.get("blocked_example"):
                errs.append(f"{aid}: forbidden action must carry a blocked_example phrase")
    return errs


def render_markdown(cat):
    """Human-readable view of the boundary (the 'contract' page). Kept byte-identical to the JSON by
    test_action_catalog.py, so it can never drift. Regenerate: python3 services/bridge/policy_catalog.py"""
    L = []
    L.append(f"# {cat.get('title', 'Action catalog')}")
    L.append("")
    L.append(f"> Generated from `policy/action-catalog.json` (version {cat.get('version')}, signed_by "
             f"`{cat.get('signed_by')}`). Do not hand-edit — run `python3 services/bridge/policy_catalog.py`.")
    L.append("")
    L.append(cat.get("description", ""))
    L.append("")
    for dc in cat.get("degradation_classes", []):
        L.append(f"- **{dc['id']}** — {dc['def']}")
    L.append("")
    for tier in TIERS:
        rows = [a for a in actions(cat) if a.get("approval_tier") == tier]
        if not rows:
            continue
        L.append(f"## `{tier}` — {len(rows)} action(s)")
        L.append("")
        if tier == "forbidden":
            L.append("| id | title | why forbidden | blocked example |")
            L.append("|---|---|---|---|")
            for a in rows:
                L.append(f"| `{a['id']}` | {a['title']} | {a.get('rationale','')} | {a.get('blocked_example','')} |")
        else:
            L.append("| id | title | class | effect | blast radius | reversible | restores invariant |")
            L.append("|---|---|---|---|---|---|---|")
            for a in rows:
                eff = a.get("effect") or {}
                if eff.get("type") == "nvram-apply":
                    e = f"`{eff.get('key')}={eff.get('value')}` · {eff.get('restart')}"
                elif eff.get("type") == "nvram-multi":
                    e = f"{len(eff.get('sets', []))} keys · {eff.get('restart')}"
                else:
                    e = eff.get("type", "")
                br = a.get("blast_radius") or {}
                brs = f"{br.get('scope','')} · {br.get('service_impact','')}".strip(" ·")
                rev = "✓" if (a.get("reversibility") or {}).get("reversible") else "✗"
                L.append(f"| `{a['id']}` | {a['title']} | {a.get('degradation_class') or '—'} | {e} | {brs} | {rev} | {a.get('restores_invariant') or '—'} |")
        L.append("")
    return "\n".join(L).rstrip() + "\n"


if __name__ == "__main__":
    _cat = load()
    _errs = validate(_cat)
    if _errs:
        import sys
        print("INVALID catalog:", *("\n  - " + e for e in _errs), file=sys.stderr)
        sys.exit(1)
    print(render_markdown(_cat), end="")
