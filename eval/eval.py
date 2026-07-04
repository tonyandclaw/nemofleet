#!/usr/bin/env python3
# eval.py — 真實任務 eval + 規則評分 + 負案例沉澱(下次自動回灌教訓)。
# 閉環:跑任務 → 規則檢查 → 記 LEDGER → 失敗寫入 lessons.json → 下次把該任務的教訓 prepend 進 prompt。
# 在 host 跑(呼叫 Hermes API :8642)。零額外 LLM judge,評分純規則,成本=每任務 1 次 bounded 推理 turn。
import json, re, os, sys, time, urllib.request, datetime

EVAL = os.path.dirname(os.path.abspath(__file__))   # nemofleet/eval
BASE = os.path.dirname(EVAL)                          # repo root
TASKS = f"{EVAL}/tasks.jsonl"
LESSONS = f"{EVAL}/lessons.json"
LEDGER = f"{EVAL}/ledgers/LEDGER.md"
HERMES = f"http://127.0.0.1:{os.environ.get('HERMES_API_PORT', '8642')}/v1/chat/completions"

def load_lessons():
    try:
        return json.load(open(LESSONS))
    except Exception:
        return {}

def save_lessons(d):
    json.dump(d, open(LESSONS, "w"), ensure_ascii=False, indent=2)

def call_hermes(prompt, maxtok):
    body = json.dumps({"model": "hermes-agent", "stream": False, "max_tokens": maxtok,
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request(HERMES, data=body, headers={"Content-Type": "application/json"})
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
    results = []
    for tk in tasks:
        tid = tk["id"]; prompt = tk["prompt"]
        prior = lessons.get(tid, [])
        if prior:
            prompt = "（過去教訓,請務必避免重蹈:\n" + "\n".join(f"- {x}" for x in prior) + "\n）\n\n" + prompt
        try:
            content = call_hermes(prompt, tk.get("maxtok", 200))
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
        results.append({"id": tid, "desc": tk.get("desc",""), "pass": passed,
                        "errored": errored, "err": err,
                        "fails": fails, "recovered": recovered,
                        "content": content[:300], "injected_lessons": prior})
    save_lessons(lessons)

    npass = sum(1 for r in results if r["pass"]); n = len(results)
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
    nerr = sum(1 for r in results if r["errored"])
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
    sys.exit(0 if npass == n else 1)

if __name__ == "__main__":
    main()
