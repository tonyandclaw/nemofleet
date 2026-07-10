# harness 治理盤點 + 差異化設計(Phase D)

_2026-07-10 校正:原文件是 2026-06-06 對 2-node(team-lead + worker-a)艦隊的唯讀盤點,把角色差異化 egress
標成「提案,尚未套用」。現場對全部 4 個節點重新盤點後,發現差異化其實已經**在跑**(egress preset 隨各節點
實際職責自然長出差異),只是沒人回來更新這份文件確認。改 policy 仍屬不可逆/可能切斷 inference 的動作 →
真的要改動時先 snapshot + `--dry-run`,這條原則不變。_

## 現況(四台受什麼治理,`openshell policy get <sb> --full` 現場盤點)
| | team-lead | worker-a | worker-b | worker-c |
|---|---|---|---|---|
| 角色 | 對人前台 + 協調 | 運維 | 資安 | 治理 |
| 共同 preset | `managed_inference`、`nous_research`、`nvidia` | 同左 | 同左 | 同左 |
| 額外 preset | `telegram`、`worker_bridge` | `pypi` | `pypi`、`github`、`brew` | `pypi`、`huggingface` |

→ 觀察:四台的差異化**已經對齊角色**,不是原文件描述的「兩台都差不多、規劃中要拆開」:
- **team-lead**:只有對人整合(`telegram`)+ 委派用的 scoped `worker_bridge`(/32,僅通往單一 worker 的 `:9099`)——**沒有**任何 IT 內網/裝置直連的 preset,委派一律經 worker 動手。這正是原「差異化治理設計」提案要的效果,已經是現況,不是待套用的規劃。
- **worker-b**:多了 `github`(抓上游韌體原始碼做 SBOM/SAST)+ `brew`(裝掃描工具);資安職責需要的來源存取,其他節點都沒有。
- **worker-c**:多了 `huggingface`(SkillOS curation 相關);沒有 `github`/`brew`,egress 面比 worker-b 精簡。
- **worker-a**:四台裡最精簡,只多一個 `pypi`。

共同點:四台都靠 `inference.local`(經 gateway proxy)連本地 NIM 推理 —— **任何 policy 改動都不能切斷 inference.local**。

## 這份盤點沒有驗證到的地方(誠實列出,別假裝已確認)
- 上面的「額外 preset」只反映**目前**這次盤點當下套用的狀態;沒有回溯每個 preset 是誰、何時、為何加上去的(不是刻意設計出來的差異化,比較像各節點依實際任務自然累積的結果)。
- 沒有查證 `EBG19P_TARGET`/裝置 `/32` 這類**動態渲染**的 egress(boot-stack.sh 每次開機才注入 IP,盤點當下裝置離線,worker-a/worker-c 的 policy 裡看不到裝置專屬規則)—— 這不代表沒有這條規則,只是這次盤點沒能驗到。
- 沒有查「policy tier」(balanced/…)這個原文件提過的概念在哪裡設定/是否仍是現行機制 —— 這次盤點的資料來源(`openshell policy get --full`)沒有回傳這個欄位,不確定它是否還是有意義的分類軸,故本次更新移除了這一行,避免照抄一個可能已經不存在的欄位。

## demo 佐證方式(治理「真的在管」)
1. 唯讀展示:`nemoclaw <sb> status` / `openshell policy get <sb> --full` 顯示各自 policies。
2. 行為佐證:讓某 agent 嘗試連「不在其白名單」的 host → OpenShell log 出現 `DENIED ...:reason connection not allowed by policy`;允許的則 `ALLOWED`。→ 證明是 code 層強制,不是 prompt。
3. 要展示「授權後 ALLOWED」:對節點 `policy-add` 一個新 egress preset(先 `--dry-run`,snapshot 後再實施)。

## 行為佐證(2026-06-06 實測,治理三層級皆生效;機制沒變,沿用原始紀錄)
OpenShell OPA 引擎在多層強制(從 `nemoclaw <sb> logs` 撈到的真實行):
- **host 層**:`NET:OPEN ALLOWED inference.local:443` — 只放行推理端點。
- **path/method 層**:`DENIED inference.local:443 [reason:connection not allowed by policy: POST /api/show]` — 連允許的 host,特定路徑/方法仍擋(擋掉 Ollama 式探測)。
- **binary 層**:`DENIED -> example.com / pypi.org [engine:opa] [reason:failed to resolve peer binary]` — 未授權 binary(隨機 shell 的 curl)一律擋,與 host 無關(也是為何手動 curl 測 host 白名單會全 403:proxy 按 binary+path 治理)。
→ 結論:治理是**程式碼/policy 引擎層強制**,非靠 prompt。demo 直接秀這幾行 log 即可。

## 風險與守則
- 改 policy 前必 `nemoclaw <sb> snapshot create`;先 `--dry-run` 看 diff;確認 inference.local/gateway(18080)不受影響再 apply。
- 不可逆/切斷風險高 → 預設只做唯讀展示 + dry-run 建議;真套用前在 PROGRESS 記明並可回滾(snapshot restore)。
