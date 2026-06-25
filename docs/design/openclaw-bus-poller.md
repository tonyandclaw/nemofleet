# OpenClaw 端 bus poller — 已實作(選項 1 MVP,並擴充為免 UI 全自動)

_round 9 設計 — 2026-06-05;同日完成實作並驗收(run/all 子指令為後續擴充)_

## 問題
目前轉派是「host→Hermes(HTTP API)」單向自動。OpenClaw 沒有入站 API、`connect` 只有互動式 SSH,所以 **OpenClaw 無法被程式自動驅動去消費 bus 任務**。要補上「OpenClaw 也能主動處理 bus/inbox」這個缺口。

## 限制
- `nemoclaw <name> share mount` 是 **sandbox→host** 方向(把沙箱 FS 掛到 host),不能把 host 的 bus 掛進沙箱。
- 要把 host 的 bus 內容送進 OpenClaw 沙箱,只能 `docker cp` 或在沙箱內放輪詢腳本去 host(但 egress 受策略限制)。

## 選項(由可行到困難)
1. **host-side relay-by-cp（推薦 MVP）**:host 腳本讀 `bus/inbox` 中 `to=openclaw` 的任務 → `docker cp` 成沙箱內檔案 `/sandbox/.openclaw/workspace/bus-task.md` → 由 OpenClaw 的一個 skill 在使用者於 UI 觸發時讀取處理 → 結果寫沙箱內 outbox → host `docker cp` 回 `bus/outbox`。半自動(需人在 UI 觸發一次)。
2. **sandbox-side cron worker**:在 OpenClaw 沙箱內裝 cron + 一個 worker 腳本輪詢沙箱內 bus 目錄;host 端負責把任務 cp 進去、把結果 cp 出來。較自動,但要動沙箱內 cron 與 egress 策略,風險較高。
3. **messaging channel**:給 OpenClaw 接一個 channel(如本地 webhook),用發訊觸發。最「正規」但設定最重。

## 實作現況(選項 1 已落地,且超出原設計)
- `scripts/openclaw-cp-task.sh`:`put`(docker cp 投遞 + **chown 998**,避免 agent EACCES)/ `run`(**超出原設計**:nsenter 進 gateway netns 直接跑 `openclaw agent`,免 UI 全自動)/ `get`(取回 `bus/outbox`)/ `all`(一條龍)。
- `skills/bus-worker/SKILL.md` 已裝進 my-assistant;`dispatch.sh` 的 openclaw 腿即走此管道(✅ 端到端,見 README 腳本表)。
- 另一條入站路徑(06-09 起):`bridge/openclaw-fix-endpoint.py` 常駐 :9099,Hermes 經 scoped `openclaw_bridge` policy 可直接委派(見 `bridge/`)。
- 選項 2(沙箱內 cron worker)未做——OpenClaw 自帶 gateway cron 排程器可原生實現,列為可加值項。

## 驗收點(已驗)
- host 投遞任務 → `run` 觸發(免 UI)→ 結果出現在 `bus/outbox` → 可選 skill-sync 回 Hermes。✅
