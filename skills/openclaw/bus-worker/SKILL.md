---
name: bus-worker
description: Read a delegated task delivered by the host bus and write the answer back. Use when the user says "處理 bus 任務" / "process the bus task" / mentions bus-task.md.
---

# bus-worker — 消費 host 投遞的轉派任務

## WHEN TO USE
- 使用者要求「處理 bus 任務」「process the bus task」或提到 `bus-task.md`。

## STEPS
1. 讀取 `~/.openclaw/workspace/bus-task.md`(或 `/sandbox/.openclaw/workspace/bus-task.md`)。
2. 依任務內容完成工作(查資料、整理、產出)。保持輸出精簡(本地模型較慢)。
3. 把最終回覆**寫入** `~/.openclaw/workspace/bus-result.md`(覆蓋舊內容),格式:
   ```
   # bus result
   <你的回覆>
   ```
4. 回報已寫入 bus-result.md。host 端會用 `openclaw-cp-task.sh get` 取回到 bus/outbox。

## NOTES
- 這是 OpenClaw×Hermes 結合的「OpenClaw 腿」:OpenClaw 沒有入站 API,故由 host 用 docker cp 投遞任務、本 skill 負責消費並寫回結果。
- 若任務其實更適合強推理(複雜/需產技能),建議在回覆中標註 "→ 建議轉派 Hermes",host 端可改用 dispatch.sh。
