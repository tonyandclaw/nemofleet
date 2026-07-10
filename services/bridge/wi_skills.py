#!/usr/bin/env python3
# wi_skills.py — skill-repository curation, adapting SkillOS ("Learning Skill Curation for Self-Evolving
# Agents", arXiv 2605.06614) to nemofleet's governed fleet.
#
# SkillOS pairs a frozen executor (retrieves + uses skills) with a trainable curator that
# insert/update/deletes reusable Markdown skills under composite quality signals (task outcome, operation
# validity, content quality, and conciseness / anti-proliferation), plus cheap BM25 retrieval. We can't
# RL-train a curator here, so we implement the curator's QUALITY GATES + BM25 retrieval as deterministic,
# unit-tested pure functions, and host them on worker-c — which is already the change-governance / QA
# officer, a natural home for curating the fleet's procedural memory. Skills stay human-auditable Markdown
# + YAML frontmatter (nemofleet and SkillOS share this format). No side effects.
#
# r_task (task-outcome reward): compute_skill_stats() replays eval.py's per-skill outcome ledger into a
# success-rate summary, attached to curate()'s result as informational context (see its docstring for
# why it's deliberately non-gating). Still not the paper's RL-trained reward — a deterministic, real
# analog of the same "judge a skill by whether tasks using it succeed" signal, same trade-off as above.
import re
import math


def parse_skill(text):
    """Markdown + YAML frontmatter → {name, description, body}."""
    name = desc = ""
    body = text or ""
    m = re.match(r"\s*---\s*\n(.*?)\n---\s*\n?(.*)", text or "", re.S)
    if m:
        fm, body = m.group(1), m.group(2)
        nm = re.search(r"^name:\s*(.+)$", fm, re.M)
        name = nm.group(1).strip() if nm else ""
        dm = re.search(r"^description:\s*(.+)$", fm, re.M)
        desc = dm.group(1).strip() if dm else ""
    return {"name": name, "description": desc, "body": body.strip()}


_WORD = re.compile(r"[a-z0-9]+")


def _tokens(s):
    return _WORD.findall((s or "").lower())


def bm25_search(query, skills, k1=1.5, b=0.75, top=5):
    """SkillOS's cheap keyword retrieval: rank skills by BM25 over name + description + body."""
    docs = [(_tokens(s.get("name", "") + " " + s.get("description", "") + " " + s.get("body", "")), s) for s in skills]
    if not docs:
        return []
    n = len(docs)
    avgdl = sum(len(d) for d, _ in docs) / n
    df = {}
    for d, _ in docs:
        for t in set(d):
            df[t] = df.get(t, 0) + 1
    scored = []
    q = _tokens(query)
    for d, s in docs:
        tf = {}
        for t in d:
            tf[t] = tf.get(t, 0) + 1
        score = 0.0
        for t in q:
            if t not in tf:
                continue
            idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
            score += idf * (tf[t] * (k1 + 1)) / (tf[t] + k1 * (1 - b + b * len(d) / avgdl))
        if score > 0:
            scored.append((score, s))
    scored.sort(key=lambda x: -x[0])
    return [{"name": s.get("name"), "score": round(sc, 3)} for sc, s in scored[:top]]


def _overlap(a, b):
    """Jaccard token overlap — a cheap near-duplicate signal for anti-proliferation."""
    ta, tb = set(_tokens(a)), set(_tokens(b))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def skill_quality(text, max_body_lines=120):
    """SkillOS-style quality signals as deterministic gates → (parsed_skill, checks)."""
    sk = parse_skill(text)
    checks = []
    fm_ok = bool(sk["name"] and sk["description"])
    checks.append({"name": "frontmatter", "pass": fm_ok,
                   "detail": "有 name + description(可被檢索/稽核)" if fm_ok else "缺 YAML frontmatter 的 name/description",
                   "detail_en": "has name + description (retrievable/auditable)" if fm_ok else "missing name/description in YAML frontmatter"})
    kebab = bool(re.match(r"^[a-z0-9]+(-[a-z0-9]+)*$", sk["name"] or ""))
    checks.append({"name": "name-format", "pass": kebab,
                   "detail": "name 為 kebab-case" if kebab else "name 非 kebab-case",
                   "detail_en": "name is kebab-case" if kebab else "name is not kebab-case"})
    body_ok = len(sk["body"]) >= 20
    checks.append({"name": "has-body", "pass": body_ok,
                   "detail": "有指令內容" if body_ok else "指令內容過短/空",
                   "detail_en": "has instruction content" if body_ok else "instruction content too short/empty"})
    lines = sk["body"].count("\n") + 1
    concise = lines <= max_body_lines
    checks.append({"name": "concise", "pass": concise,
                   "detail": "精簡(非逐字軌跡複製)" if concise else "過長(%d 行 > %d)— 疑似逐字複製,SkillOS compression 建議壓縮" % (lines, max_body_lines),
                   "detail_en": "concise (not a verbatim trajectory copy)" if concise else "too long (%d lines > %d) — looks like a verbatim copy, SkillOS compression suggests condensing" % (lines, max_body_lines)})
    return sk, checks


def compute_skill_stats(outcomes, min_samples=3):
    """SkillOS's r_task reward, as a deterministic (non-trained) aggregate: replay a flat list of
    {skill, pass} outcome events (produced by eval.py attributing eval/tasks.jsonl results to the
    "skill" field a task declares) into a per-skill success-rate summary. Pure function → this is the
    whole "judge a skill by whether tasks that used it actually succeeded" signal, computed without
    the paper's RL/GRPO training loop (see the module docstring — no training environment exists here).
    outcomes: [{"skill": str, "pass": bool, "ts": str|None}, ...] (already filtered to non-transient
    events by the caller — an infra/timeout error is not a verdict on the skill, same principle
    eval.py already applies to lessons.json). Returns {skill_name: {uses, passes, success_rate,
    sample_ok, last_ts}}; sample_ok=False until min_samples uses accumulate, so a skill isn't judged
    off one lucky/unlucky run."""
    stats = {}
    for o in outcomes:
        name = o.get("skill")
        if not name:
            continue
        s = stats.setdefault(name, {"uses": 0, "passes": 0, "last_ts": None})
        s["uses"] += 1
        s["passes"] += 1 if o.get("pass") else 0
        ts = o.get("ts")
        if ts and (s["last_ts"] is None or ts > s["last_ts"]):
            s["last_ts"] = ts
    for s in stats.values():
        s["success_rate"] = round(s["passes"] / s["uses"], 3) if s["uses"] else None
        s["sample_ok"] = s["uses"] >= min_samples
    return stats


def curate(op, text, existing, name="", dup_threshold=0.6, downstream_stats=None):
    """Validate a curator operation (insert / update / delete) → binding verdict.
    existing = [{name, description, body}]. Mirrors SkillOS's insert/update/delete under quality signals.
    downstream_stats (optional): {skill_name: {uses, passes, success_rate, sample_ok, last_ts}} from
    compute_skill_stats() — attached to the result as informational r_task context ONLY. It never
    enters `checks`/`failed`, so it cannot affect verdict/score: a skill with a rough track record is
    surfaced for a human/curator to see, not auto-rejected off what may still be a thin sample. Turning
    this into a binding gate is a deliberate future step, not an oversight."""
    op = (op or "").lower()
    if op == "delete":
        found = any(s.get("name") == name for s in existing)
        return {"op": "delete", "name": name, "verdict": "approve" if found else "reject",
                "checks": [{"name": "exists", "pass": found, "detail": "存在於 repo" if found else "repo 無此技能",
                           "detail_en": "exists in repo" if found else "no such skill in repo"}],
                "reasons": [] if found else ["repo 無此技能:" + name],
                "reasons_en": [] if found else ["no such skill in repo: " + name], "required_fixes": [], "required_fixes_en": []}
    sk, checks = skill_quality(text)
    if op == "insert":
        dup_score, dup_name = max(((_overlap(sk["body"], s.get("body", "")), s.get("name", "")) for s in existing),
                                  default=(0.0, ""))
        not_dup = dup_score < dup_threshold
        checks.append({"name": "non-redundant", "pass": not_dup,
                       "detail": "無高度重疊技能" if not_dup else "與『%s』重疊 %d%% — 建議 update 而非新增(SkillOS 抗膨脹)" % (dup_name, int(dup_score * 100)),
                       "detail_en": "no highly-overlapping skill" if not_dup else "%d%% overlap with '%s' — suggest update instead of insert (SkillOS anti-proliferation)" % (int(dup_score * 100), dup_name)})
    failed = [c for c in checks if not c["pass"]]
    result = {"op": op or "insert", "name": sk["name"], "verdict": "approve" if not failed else "reject",
              "score": round(100 * (len(checks) - len(failed)) / max(len(checks), 1)),
              "checks": checks, "reasons": [c["detail"] for c in failed],
              "reasons_en": [c["detail_en"] for c in failed],
              "required_fixes": ["修正 %s(%s)" % (c["name"], c["detail"]) for c in failed],
              "required_fixes_en": ["fix %s (%s)" % (c["name"], c["detail_en"]) for c in failed]}
    ds = (downstream_stats or {}).get(sk["name"] or name)
    if ds:
        result["downstream_stats"] = ds
    return result
