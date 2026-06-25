# pptx-architecture-map.md — PPTX 架構 ↔ 實機對應表

> 目的:把 `ASUS-AgenticAI-Competition-2026.pptx`(18 頁)畫的每個架構元件,逐項對到實機上「真的有、跑得起來、驗得到」的東西。狀態:**✓** 實機完整對應 / **⚠** 部分或靠邏輯(非獨立實例)/ **✗(roadmap)** 屬未來願景未實作。
> 用法:評審指著投影片某個方塊問「這個實際在哪」,照本表給容器/進程/policy/指令。驗證指令細節見 `EVIDENCE.md`。

## 1. 四大元件(PPTX slide 2/3/10)

| PPTX 元件 | 角色(投影片) | 實機對應 | 驗證指令 | 狀態 |
|---|---|---|---|---|
| **NemoClaw** | 管理層:agent 生命週期/復原 + 模型·通道·policy 路由 | `nemoclaw` CLI;snapshot/recover/rebuild;sandboxes.json(provider 路由) | `nemoclaw list`;`nemoclaw my-assistant snapshot list` | ✓ |
| **OpenShell** | 強制層:沙箱隔離 + OPA 程式碼級 policy + L7 MITM | host gateway :18080;每沙箱獨立 netns;OPA host/path/binary;L7 proxy 10.200.0.1:3128 | `openshell status`;`openshell policy get hermes-demo --full` | ✓ |
| **Hermes** | 對人前台:多通道接需求 + 判型派工 + 結案 | `hermes-demo` 容器(:8642);Telegram + Email(GreenMail)channel | `nemoclaw list \| grep hermes`;demo_telegram A1 | ✓ |
| **OpenClaw ×N** | IT 機隊:監控+CVE / 實修+驗收 / 修不了開 Jira | **2 實例職責分工**:節點A `my-assistant`(運維/網管:monitor+fix,管 rt-ax89x+ebg19p)、節點B `openclaw-2`(資安/原始碼:cve 全機隊+SBOM/SAST+monitor openwrt,172.18.0.4);各自 :9099 端點(BRIDGE_ZONE+caps) | `nemoclaw list`(兩 openclaw);兩台 `/health` 看 role/caps | ✓ 2 節點職責分工(06-14;再多實例=roadmap) |

## 2. 連線與隔離(PPTX slide 4「secure scoped tunnel」/ slide 10「scoped 通道」)

| PPTX 元件 | 實機對應 | 驗證指令 | 狀態 |
|---|---|---|---|
| 兩 agent 沙箱完全隔離 | hermes / my-assistant 各自 netns;預設無互通 | `security-demo.sh` S1(非白名單 DENIED) | ✓ |
| 唯一 scoped 跨代理通道 | `openclaw_bridge` egress policy:allowed_ips `<OpenClaw IP>/32` + :9099 入站 + X-Bridge-Token | `openshell policy get hermes-demo --full \| grep -A3 openclaw_bridge` | ✓ |
| 層級化(企業維運→sandbox→執行) | NemoClaw(host CLI)→ OpenShell gateway → 沙箱容器內 agent | `nemoclaw list` + `docker ps` | ✓ |

## 3. 治理:code 不是 prompt(PPTX slide 11)

| PPTX 宣稱 | 實機對應(engine) | 驗證指令 | 狀態 |
|---|---|---|---|
| 正常行為 ALLOWED(跨agent/通道/Jira) | OPA `[policy:openclaw_bridge/telegram/greenmail_mail/jira]` | `govboard.sh`(6 類 policy 計數) | ✓ |
| OPA host/path/binary 三層強制 | 非白名單→DENIED、未授權 binary→DENIED、L7 MITM 憑證遮罩 | `security-demo.sh`(S1/S4/S7) | ✓ |
| 跨 agent token + /32 雙鎖 | :9099 無 token→403;egress /32 | demo_telegram B1 | ✓ |
| 可形式化證明 | `openshell policy prove`(靜態窮舉外洩面) | `policy-prove-demo.sh` | ✓(loop 新增) |

## 4. 代理流水線:會接力的工作循環(PPTX slide 10)
PPTX 畫:人 → Hermes 判型派工 →(scoped 通道)→ OpenClaw 實修 → 自動驗收 → Hermes 結案 / 修不了→Jira。

| 環節 | 實機對應 | 驗證指令 | 狀態 |
|---|---|---|---|
| 人報修(多通道) | Telegram bot / GreenMail email → Hermes | demo_telegram A1 / A2 | ✓ |
| Hermes 判型 + 自委派 | `it-delegate-openclaw` SKILL → POST :9099/fix | `bridge-regress.sh drift` | ✓ |
| OpenClaw 實修 + 驗收 | run_fix(nsenter→openclaw agent)+ driftcheck.py | 端點 log `[FIX DONE] REGRESSIONS=5→0` | ✓ |
| 結案回報 | Hermes 取 /last → 回客戶 | demo_telegram A1 追蹤 | ✓ |
| 修不了→Jira 升級(人在迴路) | open_jira → policy:jira 治理 egress → mock Jira :3690 | `curl :9099/jira`;OPA log policy:jira | ✓ |

## 5. 監控與機隊(PPTX slide 10「定期掃 CVE / source+design 掃描 / 水平擴展」)

| PPTX 宣稱 | 實機對應 | 驗證指令 | 狀態 |
|---|---|---|---|
| 監控設備狀態 | `/monitor` 現況 vs 核准基準逐鍵比對,退化即 ALERT | `curl :9099/monitor`(managed=3) | ✓ |
| 定期掃 CVE + 生 SBOM | `/cve` 機隊分級 + 內建每日排程 + 歷史 | `cve-scan.sh` | ✓ |
| 查 source code 及 **design document** 自家掃描 | `/source-cve`:SBOM + SAST(CWE-78/798)+ SECURITY-DESIGN.md 符合性 + 建議 patch | `source-cve-demo.sh` | ✓ |
| 機隊(現一台 sample,可橫向擴) | FLEET 6 設備 + MANAGED 3 台逐台巡檢(rt-ax89x/openwrt/**EBG19P 實機**) | `/monitor`、`/cve` | ⚠ 邏輯機隊(實體多 OpenClaw=roadmap) |
| 難題自動升級 Jira | 同 §4 修不了→Jira | `curl :9099/jira` | ✓ |

## 6. 未來展望(PPTX slide 18:Vera Rubin 中央大腦 + 分佈式邊緣機隊)— roadmap

| PPTX 願景 | 現狀 | 差距 / 為何標 roadmap | 狀態 |
|---|---|---|---|
| 多台 OpenClaw 分佈式機隊 | 1 個 OpenClaw 實例管 FLEET 6 設備 | 多實例受 WSL2 7.5G 記憶體限制(idle 6 台≈4G、active 會 OOM);需擴記憶體或多機。**不在本機強做**(06-13 事故教訓) | ✗(roadmap) |
| Vera Rubin 中央管理大腦 | NemoClaw 管單機生命週期 | 跨節點中央編排層未實作 | ✗(roadmap) |
| 跨部門資源整合 | 單機四元件 | 多節點/多部門部署未實作 | ✗(roadmap) |
| NemoClaw × NVIDIA 推理 | egress 治理路徑已通(無 key 回 401) | 需 NVIDIA_API_KEY 才真打 Nemotron | ⚠ 路徑已備 |

## 對齊結論
PPTX slide 1–12 的**核心架構與能力,實機逐項 ✓ 對應**(四元件、隔離、scoped 通道、三層治理、代理流水線、監控/CVE/source-design 掃描、Jira 升級)。slide 18 的**分佈式願景**誠實標為 roadmap(受本機資源限制,且 06-13 已證明在本機強推會破壞 stack)。「機隊」現以一個 OpenClaw 管 6 設備的邏輯機隊呈現,符合「現一台 sample、可橫向擴」的投影片說法。

> 抽驗紀錄(P4-3 逐項實跑):
> - 2026-06-13 10:36 抽驗代表項全對:§1 四元件=2 沙箱 ✓;§2 scoped 通道 `host 172.18.0.2:9099 allowed_ips 172.18.0.2/32` ✓;§3 hermes ALLOWED 5 類 policy(telegram/greenmail_mail/openclaw_bridge/nvidia/github)✓;§4 端點 5 場景+jira/cve/source/design+managed=3 ✓。§1–§5 標 ✓ 的項目確認對得上(基礎隨 boot-stack 全綠+loop-regress fails=0 成立)。§6 roadmap 維持。
