# harness 治理盤點 + 差異化設計(Phase D)

_唯讀盤點 2026-06-06。改 policy 屬不可逆/可能切斷 inference 的動作 → Phase D active 時才做,且先 snapshot + --dry-run。_

## 現況(兩台受什麼治理)
| | hermes-demo (Hermes) | my-assistant (OpenClaw) |
|---|---|---|
| policy tier | balanced | balanced |
| policies preset | npm, pypi, huggingface, brew | npm, pypi, huggingface, brew, **brave** |
| blueprint | agents/hermes/policy-additions.yaml | nemoclaw-blueprint/policies/openclaw-sandbox.yaml + tiers.yaml |
| egress 特色 | 大量「對人/整合」白名單:github、slack、telegram、discord、wechat、nous/nvidia inference gateways… | 較精簡(openclaw-sandbox 基準 + brave) |

→ 觀察:Hermes 的 egress 偏「對外整合/messaging」(符合對人前台);OpenClaw 偏精簡。兩台 tier 都 balanced。共同點:都靠 `inference.local`(經 gateway proxy)連 Azure 推理 —— **任何 policy 改動都不能切斷 inference.local**。

## 差異化治理設計(提案,尚未套用)
依新角色(Hermes=對人前台、OpenClaw=IT operator)做差異化 egress:
- **OpenClaw(IT)**:允許 IT 實作所需 —— 套件/repo(npm/pypi/github)、內部/IT 目標(示範用:某內網診斷端點)、診斷工具 binaries。
- **Hermes(對人)**:允許對人整合(slack/telegram/github issues),但**不**給 IT 內網直連 —— 規劃完委派給 OpenClaw 動手。
- 用 nemoclaw policy preset(`policy-add --from-file`/`--dry-run`)做,不手改 sandbox 內檔。

## demo 佐證方式(治理「真的在管」)
1. 唯讀展示:`nemoclaw <sb> status` / sandboxes.json 顯示各自 policies。
2. 行為佐證:讓某 agent 嘗試連「不在其白名單」的 host → OpenShell log 出現 `DENIED ...:reason connection not allowed by policy`;允許的則 `ALLOWED`。→ 證明是 code 層強制,不是 prompt。
3. (可選)Phase D active 時:對 OpenClaw `policy-add` 一個 IT 用 egress preset(先 `--dry-run`,snapshot 後再實施),展示「授權後 ALLOWED」。

## 行為佐證(2026-06-06 實測,治理三層級皆生效)
OpenShell OPA 引擎在多層強制(從 `nemoclaw <sb> logs` 撈到的真實行:
- **host 層**:`NET:OPEN ALLOWED inference.local:443` — 只放行推理端點。
- **path/method 層**:`DENIED inference.local:443 [reason:connection not allowed by policy: POST /api/show]` — 連允許的 host,特定路徑/方法仍擋(擋掉 Ollama 式探測)。
- **binary 層**:`DENIED -> example.com / pypi.org [engine:opa] [reason:failed to resolve peer binary]` — 未授權 binary(隨機 shell 的 curl)一律擋,與 host 無關(也是為何手動 curl 測 host 白名單會全 403:proxy 按 binary+path 治理)。
→ 結論:治理是**程式碼/policy 引擎層強制**,非靠 prompt。demo 直接秀這幾行 log 即可。

## 風險與守則
- 改 policy 前必 `nemoclaw <sb> snapshot create`;先 `--dry-run` 看 diff;確認 inference.local/gateway(18080)不受影響再 apply。
- 不可逆/切斷風險高 → 預設只做唯讀展示 + dry-run 建議;真套用前在 PROGRESS 記明並可回滾(snapshot restore)。
