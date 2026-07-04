---
name: review-gate
description: Before accepting or reporting a worker-a remediation or a worker-b CVE / security decision, run it past worker-c (the QA / change-governance officer) and enforce the verdict. worker-c's reject is binding — you must send it back for redo. Use whenever a worker's solution/decision will be applied or reported to the human.
tags: [governance, review, worker-c, quality, supervisor]
---
# Review-gate:worker-c 品質閘(接受 a/b 產出前先過審)

worker-c 是**變更治理官**。它的 **reject 是綁定的 —— 你(team-lead)必須執行重做,不能放行**。worker-c 只審品質、不直接命令 a/b;由你當傳輸執行它的判決(維持 worker 之間不互連)。

## 何時觸發
worker-a 回報一個 remediation 結果、或 worker-b 給一個 CVE/資安判定,而它**即將被套用或回報給人**時 —— 先過 worker-c,不要直接放行。

## 流程(務必照做)
1. 拿到 a/b 的產出:remediation 讀 worker-a 的 `/last`;CVE 取 worker-b 的一筆 finding。
2. **送審 worker-c**(A2A `message/send` skill=`review`,metadata 帶 `{kind, subject}`;或直接 curl):
   ```
   curl -s -X POST http://%%WC_IP%%:9099/review -H 'X-Bridge-Token: BRIDGETOKEN' -H 'Content-Type: application/json' \
     -d '{"kind":"remediation","subject":{"bug":"ebg-wps","ok":true,"after":{"wps.enabled":"false"}}}'
   ```
   - `kind="remediation"`,subject = worker-a 的 `/last`(含 `bug` / `ok` / `after`)。
   - `kind="cve"`,subject = worker-b 的一筆 finding(含 `cve` / `verdict` / `component` / `our_version`)。
3. 讀判決 `verdict`:
   - **approve** → 放行:回報結案 / 套用。
   - **reject** → **必須重做**:把 `required_fixes` 帶回去重派 a/b(worker-a 重修、worker-b 重判);改完**再送 worker-c 複審**。
4. **重做上限 2 次**仍 reject → **升級真人**(Telegram/Email + 開 Jira),附 worker-c 的 `reasons`,別無限迴圈。
5. worker-c 自己的高風險動作(`firmware-apply` / `rollback`)→ **先問人核准**,拿到 `approval_token` 再委派;沒 token 一律不做。

## 邊界
- 不可忽略 worker-c 的 reject(治理政策;判決會進稽核鏈)。
- 品質層級:**人 > worker-c > worker-a/b**。你照 worker-c 的判決行動,人在最頂端。
- 整個「提案 → 審 → 退回重做 → 複審 → 放行」的來回,worker 端會自動記 flow 事件,GUI **Flow** 視圖看得到。
