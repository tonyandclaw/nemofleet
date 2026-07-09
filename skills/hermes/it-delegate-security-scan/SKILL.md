---
name: it-delegate-security-scan
description: Delegate SBOM/SAST/CVE source-code scanning of a pasted GitHub link/repo to worker-b (security), route any affected-CVE finding through worker-c's QA review before reporting, and report back a size-bounded summary. Use whenever a user pastes a GitHub URL / owner-repo, or asks to scan code / a repository for vulnerabilities, SAST, or SBOM.
tags: [it, security, sast, sbom, cve, delegation, worker-b, worker-c, governance]
---
# 委派原始碼安全掃描給 worker-b(SBOM/SAST/CVE),worker-c 覆核

使用者貼 GitHub 連結(URL 或 `owner/repo`)、或要求掃描程式碼的漏洞/SAST/SBOM 時,**不要自己讀 repo 或分析程式碼** —— 這是 worker-b(資安節點)的職責,你只協調 + 覆核 + 回報。掃描結果裡任何「affected」CVE 判定,回報人之前一定先過 worker-c 覆核(它是變更治理官;完整重做/升級流程見 `review-gate` 技能)。

## 🛡 第零步 + ⚑ 第一步:守門 + 記工作流
`/guardrail` 與 `/flow` 不分 zone,任一 worker 端點都能過,這裡直接用 worker-b:
```
curl -s -X POST http://%%WB_IP%%:9099/guardrail -H 'Content-Type: application/json' -H 'X-Bridge-Token: BRIDGETOKEN' \
  -d '{"text":"<使用者需求原文,含貼的連結>","peer":"human"}'
```
`verdict:"block"` → 不執行任何動作,照 `it-delegate-worker` 技能的擋法回覆使用者。`verdict:"allow"` → 記一筆 `working` flow 事件(`detail` 帶使用者原文截 ~100 字),流程結束後補記 `done` —— 做法與 `it-delegate-worker` 的「記工作流」一節完全相同,呼叫 `%%WB_IP%%:9099/flow` 即可,不重複貼。

## 第一步:設定掃描目標(持久設定,不是每次帶的參數)
`sast_src` 存在 worker-b 的設定裡,不是 A2A 呼叫的參數 —— 要先設定,worker-b 才知道掃哪個 repo:
```
curl -s -X POST http://%%WB_IP%%:9099/settings -H 'X-Bridge-Token: BRIDGETOKEN' -H 'Content-Type: application/json' \
  -d '{"sast_src":"<使用者貼的 owner/repo 或 GitHub URL>"}'
```
使用者有指定分支/tag/commit 才需要額外設(沒指定就別碰,沿用上次設定或預設 `master`):
```
curl -s -X POST http://%%WB_IP%%:9099/settings -H 'X-Bridge-Token: BRIDGETOKEN' -H 'Content-Type: application/json' \
  -d '{"sast_ref":"<branch/tag/sha>"}'
```

## 第二步:觸發掃描(A2A `source-scan`,同步等結果)
```
curl -s -X POST http://%%WB_IP%%:9099/a2a -H 'X-Bridge-Token: BRIDGETOKEN' -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":"1","method":"message/send","params":{"message":{"role":"user","messageId":"m-1","parts":[{"kind":"text","text":"source-scan"}],"metadata":{"skill":"source-scan"}}}}'
```
會跑一段時間(GitHub API 抓碼 + Semgrep + Nemotron 複審),同步等結果即可,不用 poll `/last`(那條是 `/fix` remediation 專用的非同步路徑,這裡不適用)。回應是 JSON-RPC task,結果在 `result.artifacts[0].parts[0].text`(JSON 字串,`json.loads` 解開)。

**回應在 worker-b 端已裁切過**,不是完整原始資料:`sast_findings` 最多 15 筆,按 Nemotron 複審結果排序(confirmed → likely → 未複審 → false_positive)。看兩個欄位知道有沒有被裁:`sast_findings_total`(實際命中總數)、`sast_findings_truncated`。被裁掉的細節仍完整留在 worker-b 的 `source-cve-report.json`(裁切時 `full_report_note` 會指到這份檔)——**不要**為了拿到「完整資料」而想辦法繞過這層裁切或改小 `SAST_A2A_CAP`,這層裁切正是防止你自己的對話 context 被灌爆(過去發生過 `max compression attempts(3) reached`);你已經拿到的量就是該回報的量。

## 第三步:affected CVE 一定先過 worker-c 覆核,別直接當結論回報
`cve_reconciled` 裡任何 `verdict=="affected"` 的項目,回報人之前先送 worker-c(`kind="source"`,沿用跟 CVE 一樣的覆核閘):
```
curl -s -X POST http://%%WC_IP%%:9099/review -H 'X-Bridge-Token: BRIDGETOKEN' -H 'Content-Type: application/json' \
  -d '{"kind":"source","subject":{"cve":"<cve id>","verdict":"affected","component":"<component>","our_version":"<目前版本>","fixed_version":"<修補版本>"}}'
```
- **approve** → 可以把這筆當結論回報(worker-b 通常已自動開 Jira 去重,不用你再開一次)。
- **reject** → **不可當結論回報**。照 `review-gate` 技能的做法處理:required_fixes 帶回去讓 worker-b 重判、複審 worker-c,重做上限 2 次仍 reject → 升級真人(Telegram/Email + Jira,附 worker-c 的 reasons)。
- worker-c 未部署/未回應 → fail-open(放行但在回報時註記「未經 worker-c 覆核」),別因為治理節點沒起來就卡住整個掃描回報。

> `sast_findings`(Semgrep 命中)沒有 CVE id/元件版本這種佐證欄位,`review_cve` 這個閘對它沒意義,**不用**送去 `/review`——照原樣回報就好(每筆已經帶 Nemotron 複審的 `triage.verdict` 可參考,confirmed 的才是 worker-b 已自動開 Jira 的那批)。

## 第四步:回報使用者
中文口吻總結,不要貼整包 JSON:
- SBOM:套件數(`sbom_packages`)、來源(`sbom_source`)。
- CVE:幾筆 affected(附是否已過 worker-c 審)、幾筆 needs_review。
- SAST:`sast_findings_total` 筆,幾筆 confirmed;有被裁切(`sast_findings_truncated`)就說一句「僅列前 15 筆,完整清單在 worker-b」。
- 已自動開的 Jira 數(`jira_opened`)。

## 先查艦隊技能庫,再發明作法
不確定的細節(例如使用者要求的掃描範圍很特殊、或想同時要 nuclei 主動掃描),先查 worker-c 的技能庫再重新發明 —— 做法見 `it-delegate-worker` 技能「先查艦隊技能庫」一節,一字不改地照做。

## 邊界
- worker-b 的 `:9099` 端點是**唯一**能讓你觸發原始碼掃描的管道;不要自己 clone / 讀取 / 分析程式碼,也不要把 GitHub API 或 Semgrep 結果自己編出來。
- affected CVE 的覆核閘不可略過(治理政策;worker-c 的判決會進稽核鏈)。
- 會改動 EBG19P 設備設定的請求(remediation)不歸這支技能——那走 `it-delegate-worker`。
