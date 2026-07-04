#!/usr/bin/env python3
# wi_review.py — worker-c QA-review gates (pure, deterministic). Evaluates a worker-a / worker-b output
# against the approved baseline + evidence rules → a binding verdict (approve/reject + required_fixes).
# Deterministic gates only; the LLM nuance (root-cause, false-positive judgment) is a team-lead /
# worker-c-agent layer on top — see docs/design/worker-c-spec.md. No side effects → unit-tested directly.
import re


def _vt(s):
    return tuple(int(x) for x in re.findall(r"\d+", s or ""))


def _conf_kv(text):
    d = {}
    for line in (text or "").splitlines():
        m = re.match(r"\s*([A-Za-z0-9_.]+)\s*=\s*(.*?)\s*$", line)
        if m:
            d[m.group(1)] = m.group(2).strip()
    return d


def _verdict(target, kind, checks, ref=""):
    failed = [c for c in checks if not c["pass"]]
    return {
        "verdict": "approve" if not failed else "reject",
        "score": round(100 * (len(checks) - len(failed)) / max(len(checks), 1)),
        "target": target, "kind": kind, "checks": checks,
        "reasons": [c["detail"] for c in failed],
        "required_fixes": ["修正 %s(%s)" % (c["name"], c["detail"]) for c in failed],
        "subject_ref": ref,
    }


def review_remediation(subject, baseline_text, security_keys):
    """審 worker-a remediation:subject = {bug, ok, before, after(dict|conf-str), asset}。錨定核准 baseline。"""
    base = _conf_kv(baseline_text)
    after = subject.get("after") or {}
    if isinstance(after, str):
        after = _conf_kv(after)
    checks = []
    # gate 1 — verified:worker-a 有重讀驗證(ok 欄位 + after 快照都在)
    verified = subject.get("ok") is not None and bool(subject.get("after"))
    checks.append({"name": "verified", "pass": verified,
                   "detail": "有重讀驗證(ok + after)" if verified else "缺 ok / after — 未驗證就回報"})
    # gate 2 — baseline-match:被處理的安全鍵,after 值須等於核准 baseline
    mismatched = [k for k in security_keys if k in after and k in base and after[k] != base[k]]
    bm = not mismatched
    checks.append({"name": "baseline-match", "pass": bm,
                   "detail": "安全鍵符合核准 baseline" if bm else "仍偏離 baseline:" + ", ".join(mismatched)})
    # gate 3 — success-consistent:回報 ok=true 卻仍偏離 baseline = 可疑,擋
    consistent = not (subject.get("ok") and mismatched)
    checks.append({"name": "success-consistent", "pass": consistent,
                   "detail": "回報成功且值一致" if consistent else "回報 ok=true 但值仍偏離 baseline"})
    # gate 4 — scope:修改只該動宣告的目標鍵;before→after 若動到「其他」安全鍵 = 範圍外副作用,擋
    before = subject.get("before") or {}
    if isinstance(before, str):
        before = _conf_kv(before)
    target = subject.get("target_key")   # worker-a 該回報它改了哪個鍵;無則不查此閘
    if before and target:
        changed = [k for k in security_keys if k in before and k in after and before[k] != after[k] and k != target]
        in_scope = not changed
        checks.append({"name": "scope", "pass": in_scope,
                       "detail": "只動了目標鍵" if in_scope else "改動溢出到範圍外的安全鍵:" + ", ".join(changed)})
    return _verdict("worker-a", "remediation", checks, subject.get("bug", ""))


def review_cve(subject):
    """審 worker-b CVE 決策:subject = {cve, verdict, component, our_version, ...}。查證據 + 一致性。"""
    aff = str(subject.get("verdict", "")).lower() == "affected"
    checks = []
    has_ev = bool(subject.get("component")) and bool(subject.get("our_version"))
    checks.append({"name": "evidence", "pass": has_ev,
                   "detail": "有元件 + 版本佐證" if has_ev else "缺元件 / 版本佐證"})
    ok_cve = (not aff) or bool(subject.get("cve"))
    checks.append({"name": "cve-id", "pass": ok_cve,
                   "detail": "affected 附 CVE id" if ok_cve else "判 affected 卻無 CVE id"})
    # version-consistency:判 affected 且有修復版本 → our_version 應 < fixed(否則 affected 判定可疑)
    fixed = subject.get("fixed_version") or subject.get("fixed")
    ver = subject.get("our_version")
    if aff and fixed and ver:
        vc = _vt(ver) < _vt(fixed)
        checks.append({"name": "version-consistent", "pass": vc,
                       "detail": "our_version < fixed,affected 判定一致" if vc else "our_version 已 >= fixed,affected 判定可疑(疑假陽性)"})
    return _verdict("worker-b", "cve", checks, subject.get("cve", ""))


def review(kind, subject, baseline_text="", security_keys=None):
    """統一入口。未知 kind → 無閘可審 → approve(不擋)。"""
    if kind == "remediation":
        return review_remediation(subject or {}, baseline_text, security_keys or [])
    if kind in ("cve", "source"):
        return review_cve(subject or {})
    return {"verdict": "approve", "kind": kind, "note": "無對應審查閘,放行", "checks": []}
