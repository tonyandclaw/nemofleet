# Hermes × OpenClaw 結合架構(對人前台 + IT operator,由 harness 治理)

_更新 2026-06-06 — 重定位_

## Mermaid
```mermaid
flowchart LR
  user([人 / 需求])
  subgraph host[WSL host(結合層)]
    route[route_decide]
    dispatch[dispatch.sh<br/>自動分流]
    collab[collab.sh<br/>委派鏈]
    bus[(bus/ 信箱)]
  end
  subgraph hz[OpenShell sandbox:Hermes]
    hermes[Hermes<br/>對人前台·自我進化<br/>API :8642]
  end
  subgraph oc[OpenShell sandbox:OpenClaw]
    openclaw[OpenClaw<br/>IT operator<br/>網管/診斷/修 bug]
  end
  gov[[harness 治理<br/>OpenShell policy.yaml<br/>+ nemoclaw strategy]]

  user -->|需求| hermes
  hermes -->|規劃/分流| route
  route -->|規劃/報告| hermes
  route -->|IT/網管/bug| dispatch --> openclaw
  openclaw -->|實作結果| bus --> hermes -->|回報| user
  gov -. 治理(egress/binaries/route/tier) .-> hermes
  gov -. 治理 .-> openclaw
```

## ASCII(投影片用)
```
                ┌──────────────── WSL host(結合層)────────────────┐
  人 ──需求──►  │  Hermes(對人前台) ──規劃/分流──► route_decide      │
       ◄─回報── │     ▲                              │ IT/網管/bug    │
                │     │ 結果經 bus 回收               ▼                │
                │     └────────────────  dispatch ─► [OpenClaw]       │
                │                                     IT operator      │
                │                                     網管·診斷·修 bug │
                └──────────────────────────────────────────────────────┘
   ┌── harness 治理 ──┐  OpenShell policy.yaml(egress/binaries)
   │  誰能做什麼/去哪 │  + nemoclaw strategy(model/route/policy tier)
   └──────────────────┘  → 以 log ALLOWED/DENIED 佐證(code, not prompt)
   兩 agent 各自在獨立 OpenShell 沙箱(Landlock+seccomp+netns+egress policy)
```

## 角色分工
- **Hermes(對人前台 + 自我進化)**:接需求、規劃、解釋、產出給人看;把重複模式寫成 SKILL.md。介面=OpenAI 相容 API `:8642`。
- **OpenClaw(IT operator)**:網路管理/診斷、bug 修復、部署/重啟 的**實作**(沙箱內動手)。經 `nsenter` 進 gateway netns 用 `openclaw agent` 驅動。
- **harness 治理層**:OpenShell `policy.yaml`(egress/binaries)+ nemoclaw strategy(model/route/policy tier)管控兩者能做什麼、能去哪 —— 程式碼層強制,可由 log `ALLOWED`/`DENIED` 佐證。
- **結合層(host)**:route_decide(分流)、dispatch(自動委派)、collab(委派鏈)、bus(信箱)、eval+lessons(學習沉澱)。

## 即時 demo 亮點(可選)
Hermes 內建 `creative/architecture-diagram` 技能,demo 時可現場請它產一張 SVG 架構圖,展示「自我進化」的實際產出。
