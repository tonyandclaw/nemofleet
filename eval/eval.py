#!/usr/bin/env python3
# eval.py — 真實任務 eval + 規則評分 + 負案例沉澱(下次自動回灌教訓)。
# 閉環:跑任務 → 規則檢查 → 記 LEDGER → 失敗寫入 lessons.json → 下次把該任務的教訓 prepend 進 prompt。
# 在 host 跑,經 `openshell forward` 到 team-lead 的 Hermes API :8642(帶 gateway token 認證 —
# 見 eval.sh,它會先確保 forward 存在)。零額外 LLM judge,評分純規則,成本=每任務 1 次 bounded 推理 turn。
import json, re, os, sys, time, urllib.request, datetime, subprocess

EVAL = os.path.dirname(os.path.abspath(__file__))   # nemofleet/eval
BASE = os.path.dirname(EVAL)                          # repo root
TASKS = f"{EVAL}/tasks.jsonl"
LESSONS = f"{EVAL}/lessons.json"
LEDGER = f"{EVAL}/ledgers/LEDGER.md"
HISTORY = f"{EVAL}/ledgers/history.jsonl"   # structured per-run record (LEDGER.md stays the human-readable log)
SKILL_OUTCOMES = f"{EVAL}/skill-outcomes.jsonl"   # raw ledger: which "skill"-tagged task passed/failed, when
SKILL_STATS = f"{BASE}/skills/skill-stats.json"   # computed r_task summary; lives under skills/ so it rides
                                                    # along with boot-stack.sh's existing skills/ → worker-c sync
HERMES = f"http://127.0.0.1:{os.environ.get('HERMES_API_PORT', '8642')}/v1/chat/completions"

sys.path.insert(0, os.path.join(BASE, "services", "bridge"))
from wi_skills import compute_skill_stats  # noqa: E402 — r_task: replay skill-outcomes.jsonl into a stats summary

def load_lessons():
    try:
        return json.load(open(LESSONS))
    except Exception:
        return {}

def save_lessons(d):
    json.dump(d, open(LESSONS, "w"), ensure_ascii=False, indent=2)

def get_gateway_token():
    # The gateway rejects unauthenticated calls (API_SERVER_KEY minted per sandbox — this
    # harness predates that requirement and never sent one). HERMES_GATEWAY_TOKEN overrides;
    # otherwise ask nemoclaw for team-lead's current token. Best-effort: an empty/missing
    # token just means the call below will 401, which call_hermes surfaces as a normal
    # (transient) error like any other connection failure.
    tok = os.environ.get("HERMES_GATEWAY_TOKEN")
    if tok:
        return tok
    try:
        out = subprocess.run(["nemoclaw", "team-lead", "gateway-token", "--quiet"],
                             capture_output=True, text=True, timeout=15)
        return out.stdout.strip() or None
    except Exception:
        return None

def call_hermes(prompt, maxtok, token):
    body = json.dumps({"model": "nemotron-super", "stream": False, "max_tokens": maxtok,
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(HERMES, data=body, headers=headers)
    with urllib.request.urlopen(req, timeout=240) as r:
        d = json.loads(r.read())
    return d["choices"][0]["message"].get("content") or ""

def strip_fences(s):
    s = s.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\n?", "", s); s = re.sub(r"\n?```$", "", s)
    return s.strip()

def run_check(content, chk):
    t = chk["type"]; arg = chk.get("arg")
    if t == "json":
        try:
            return isinstance(json.loads(strip_fences(content)), dict), "需為可解析的純 JSON 物件(勿加說明文字或 ``` 圍欄)"
        except Exception:
            return False, "需為可解析的純 JSON 物件(勿加說明文字或 ``` 圍欄)"
    if t == "json_keys":
        try:
            o = json.loads(strip_fences(content)); ok = all(k in o for k in arg)
        except Exception:
            ok = False
        return ok, f"JSON 必須包含 key: {', '.join(arg)}"
    if t == "contains":
        return (arg in content), f"輸出必須包含「{arg}」"
    if t == "contains_all":
        miss = [a for a in arg if a not in content]
        return (not miss), f"輸出必須包含全部:{', '.join(arg)}(缺:{', '.join(miss)})"
    if t == "regex":
        ok = re.search(arg, content) is not None
        # 把簡單的「擇一」alternation 轉成人看得懂的可行動提示(否則回灌只是貼 regex,沒幫助)
        if re.fullmatch(r"[^()\\.*+?\[\]{}^$|]+(\|[^()\\.*+?\[\]{}^$|]+)+", arg):
            hint = "用詞需明確包含下列任一詞:" + "、".join(arg.split("|"))
        else:
            hint = f"輸出需符合格式 /{arg}/"
        return ok, hint
    if t == "max_len":
        return (len(content.strip()) <= arg), f"輸出要更精簡(≤{arg} 字,目前 {len(content.strip())})"
    return False, f"未知檢查 {t}"

def main():
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lessons = load_lessons()
    tasks = [json.loads(l) for l in open(TASKS) if l.strip()]
    token = get_gateway_token()
    if not token:
        print("⚠ 拿不到 gateway token(nemoclaw 不在 PATH 或 team-lead 未註冊)— 呼叫大概率 401,視同 transient 錯誤處理")
    results = []
    for tk in tasks:
        tid = tk["id"]; prompt = tk["prompt"]
        prior = lessons.get(tid, [])
        if prior:
            prompt = "（過去教訓,請務必避免重蹈:\n" + "\n".join(f"- {x}" for x in prior) + "\n）\n\n" + prompt
        try:
            content = call_hermes(prompt, tk.get("maxtok", 200), token)
            err = None
        except Exception as e:
            content, err = "", f"呼叫失敗: {e}"
        # 區分「基礎設施呼叫失敗(逾時/429/連線)」與「內容檢查失敗」:
        # 前者是 transient 噪音,不是教訓 —— 不沉澱、也不可清掉既有教訓(否則會把真教訓覆蓋/抹掉)。
        errored = err is not None
        fails = []
        if not errored:
            for chk in tk.get("checks", []):
                ok, why = run_check(content, chk)
                if not ok: fails.append(why)
        passed = (not errored) and (not fails)
        had_lesson = bool(prior)
        # 沉澱:內容失敗→把缺失寫成教訓(去重);通過且先前有教訓→記為「修復」;errored→兩者都不做。
        recovered = False
        if errored:
            pass  # transient:保留既有教訓不動,不新增噪音
        elif not passed:
            cur = lessons.setdefault(tid, [])
            for f in fails:
                if f not in cur: cur.append(f)
        elif had_lesson:
            recovered = True
            lessons.pop(tid, None)  # 通過了,清掉舊教訓
        # r_task:任務若宣告 "skill"(見 eval/tasks.jsonl),把這輪 pass/fail 記進 skill-outcomes.jsonl。
        # 跟 lessons 沉澱同一個原則:errored(逾時/連線)是 transient 噪音,不算一次真的技能成效量測。
        skill = tk.get("skill")
        if skill and not errored:
            try:
                with open(SKILL_OUTCOMES, "a") as f:
                    f.write(json.dumps({"ts": ts, "skill": skill, "task_id": tid, "pass": passed}, ensure_ascii=False) + "\n")
            except Exception:
                pass
        results.append({"id": tid, "desc": tk.get("desc",""), "category": tk.get("category","general"), "pass": passed,
                        "errored": errored, "err": err,
                        "fails": fails, "recovered": recovered,
                        "content": content[:300], "injected_lessons": prior})
    save_lessons(lessons)
    # r_task:重放整份 outcome ledger 算最新的每技能成效統計(純函式、全量重算,不做增量更新 —
    # 跟這個檔案其他地方一樣,寧可每次算好算滿,也不要留增量更新的漂移風險)。
    try:
        outcomes = [json.loads(l) for l in open(SKILL_OUTCOMES) if l.strip()]
    except Exception:
        outcomes = []
    skill_stats = compute_skill_stats(outcomes) if outcomes else {}
    if skill_stats:
        os.makedirs(os.path.dirname(SKILL_STATS), exist_ok=True)
        json.dump(skill_stats, open(SKILL_STATS, "w"), ensure_ascii=False, indent=2)

    npass = sum(1 for r in results if r["pass"]); n = len(results)
    nerr = sum(1 for r in results if r["errored"])
    # 結構化歷史(給 dashboard 畫競爭力趨勢用;LEDGER.md 保持人類可讀,這份只是額外附加)。
    # 全部 errored(呼叫層/認證層掛掉)不算一次真的競爭力量測 — 跳過,避免趨勢圖出現假的 0% 尖峰。
    if nerr < n:
        by_cat = {}
        for r in results:
            c = by_cat.setdefault(r["category"], {"pass": 0, "n": 0})
            c["n"] += 1; c["pass"] += 1 if r["pass"] else 0
        with open(HISTORY, "a") as f:
            f.write(json.dumps({"ts": ts, "npass": npass, "n": n, "by_category": by_cat,
                                "recovered": sum(1 for r in results if r["recovered"]),
                                "lessons_active": sum(len(v) for v in lessons.values())}, ensure_ascii=False) + "\n")
    # 寫 LEDGER.md
    with open(LEDGER, "a") as f:
        f.write(f"\n## eval {ts} — {npass}/{n} 通過\n")
        for r in results:
            mark = "⚠️" if r["errored"] else ("✅" if r["pass"] else "❌")
            line = f"- {mark} {r['id']} ({r['desc']})"
            if r["errored"]: line += f" 呼叫逾時/失敗(transient,未沉澱):{r['err']}"
            if r["recovered"]: line += " 🔁已修復(先前失敗→本次通過)"
            if r["injected_lessons"]: line += f" [回灌{len(r['injected_lessons'])}條教訓]"
            f.write(line + "\n")
            for fa in r["fails"]:
                f.write(f"    - 失敗:{fa}\n")
    # 終端摘要
    tail = f"(其中 {nerr} 個呼叫逾時,未沉澱)" if nerr else ""
    print(f"== eval {ts} ==  分數 {npass}/{n} {tail}")
    for r in results:
        mark = "ERR " if r["errored"] else ("PASS" if r["pass"] else "FAIL")
        extra = " (recovered)" if r["recovered"] else (f" [+{len(r['injected_lessons'])} lessons]" if r["injected_lessons"] else "")
        print(f"  [{mark}] {r['id']}{extra}")
        if r["errored"]:
            print(f"        - {r['err']}(transient,保留既有教訓、不新增)")
        for fa in r["fails"]:
            print(f"        - {fa}")
    print(f"教訓沉澱:{LESSONS}(目前 {sum(len(v) for v in lessons.values())} 條,涵蓋 {len(lessons)} 個任務)")
    print(f"歷史帳本:{LEDGER}")
    if skill_stats:
        print(f"r_task 技能成效:{SKILL_STATS}(涵蓋 {len(skill_stats)} 個技能)")
        for name, s in sorted(skill_stats.items()):
            flag = "" if s["sample_ok"] else " (樣本數不足,未達判斷門檻)"
            print(f"  {name}: {s['passes']}/{s['uses']} = {s['success_rate']}{flag}")
    sys.exit(0 if npass == n else 1)

if __name__ == "__main__":
    main()
