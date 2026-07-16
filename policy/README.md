# policy/ — the fleet's decision boundary

`action-catalog.json` is the **single, versioned, machine-readable statement of every action the fleet
may perform** on a managed device, and every action it must refuse — the "明確清晰的決策邊界". Each entry
carries its trigger, blast radius, reversibility, and **approval tier**:

- **`auto`** — restores a security invariant with a *single-device, reversible, read-back-verified*
  nvram change; runs without a human.
- **`human`** — rollback, firmware, or any *security-relaxing* change; requires a bound, single-use
  approval token (`wi_approval.py`).
- **`forbidden`** — refused at the guardrail (factory reset, disable-all-security, credential exfil).

## It is enforced, not decorative

`tests/unit/test_action_catalog.py` (runs in CI via `make test`) binds this file **1:1 to the code's
real capabilities** (`worker-itops` `EBG_ACTIONS`/`EBG_MULTI`) and proves the guardrail blocks every
`forbidden` example. So the fleet **cannot gain a capability the catalog doesn't list, lose a guarantee
the catalog states, or let a forbidden action through** — any divergence fails CI.

`action-catalog.md` is a generated human-readable view (the "contract" page), kept byte-identical to the
JSON by that same test.

## Changing the boundary

1. Edit `action-catalog.json` (and the code, if you're adding/removing a real capability).
2. Regenerate the view: `python3 services/bridge/policy_catalog.py > policy/action-catalog.md`
3. `make test` — the conformance suite must stay green.

## Roadmap (not yet wired)

Today the catalog is enforced at the **test** layer (code ⟺ catalog can't diverge). The P1 step is a
**runtime** action-gate that consults `policy_catalog.validate()` + `approval_tier()` before executing,
so the boundary is enforced in the live path too — plus a read-only "Decision boundary" dashboard view
rendered from this file. See `docs/design/enterprise-readiness.md`.
