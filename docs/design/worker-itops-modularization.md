# worker-itops 模組化(#11)— 現況與剩餘計畫

`worker-itops.py` 原本是單檔 monolith(~2.6k 行)。已抽出 **8 個 co-located 模組**(boot-stack `cp` 到 `/usr/local/bin` 與端點並存),核心降到 ~2.09k 行,且抽出的部分**都可單元測試**。

## 已抽出(8 模組)

| 模組 | 職責 | 模式 | 測試 |
|---|---|---|---|
| `ebg19p.py` | EBG19P 裝置 client(login/nvget/apply) | direct-import | — (真機) |
| `knowledge.py` | 共享知識層(baseline / 安全鍵 / 版本) | direct-import | ✔ |
| `wi_util.py` | 純 helper(version/cert/cipher/conf parse) | direct-import | ✔ |
| `wi_a2a.py` | A2A 協定(Agent Card + JSON-RPC),`run_skill` 回呼注入 | callback DI | ✔(間接) |
| `wi_nuclei.py` | worker-b nuclei 主動掃描子系統 | `configure()` DI | ✔(間接) |
| `wi_review.py` | worker-c QA 審查閘(純) | direct-import | ✔ |
| `wi_skills.py` | SkillOS 技能 curation(純) | direct-import | ✔ |
| `wi_flow.py` | 跨節點 flow 事件環(GUI Flow) | `configure()` DI | ✔ |

**兩種模式**:① **direct-import**(純程式碼,無宿主狀態)② **`configure()` DI**(有狀態子系統,啟動時注入宿主依賴 `zone_has` / `load_settings` / `open_jira` / `zone`)。

## 剩餘:device/fleet 耦合叢集(刻意延後到實機)

核心仍留著一組**彼此耦合、且依賴真機/實 fleet** 的掃描器:

- `run_cve_scan` / `load_live_cves` / NVD / OSV 分級(`_nvd_query` / `_osv_*`)
- `fetch_upstream_sbom` / `fetch_upstream_sast` / advisories / `_make_patch`
- `run_cert_scan` / cert policy 狀態機
- `run_monitor` / `seed_monitor_assets` / drift
- `run_syslog_analysis` / device-log / traffic

它們共用**可變狀態基座**:`load_settings/save_setting`、`open_jira/_open_jira_dedup`、recipients、`flow`、device client。

**為何延後(而非現在硬拆)**:抽這些要先把基座(settings / jira / device)以 `configure()` DI 抽成 `wi_settings` / `wi_jira` / `wi_device`,blast radius 大;而且掃描器的真正邏輯**只有對真 EBG19P + 實 fleet 才跑得到**,在只有 `my-hermes` 沙箱的這裡無法驗證掃描路徑。無法驗證就搬 = 可能靜默壞掉,違反「只要真的東西、別弄壞」。

## 基座優先(foundation-first)計畫 — 與實機一起做

1. 抽 `wi_settings.py`(SETTINGS_DEFAULTS + load/save)→ `configure()` 注入 WD。
2. 抽 `wi_jira.py`(open_jira/dedup/governed post)→ 注入 settings + egress。
3. 抽 `wi_device.py`(device-log / traffic / nvram 讀取的宿主側包裝,底層仍是 `ebg19p`)。
4. 基座就緒後,逐一抽 `wi_cve` / `wi_source` / `wi_cert` / `wi_monitor` / `wi_syslog`,**每抽一個就對真機 + 全 fleet 跑一次該掃描**驗證。
5. 目標:`worker-itops.py` 只剩 HTTP handler + zone 路由 + 各模組的 `configure()` 接線。

## 安全網(讓未來的抽取有依靠)
- **55 unit**(pure 邏輯)+ **28 integration**(18 條 authed route 皆 no-token→403 的 wired 檢查 + zone-specific 行為)。
- 每抽一個模組:`make lint/test/itest` + `my-hermes` 沙箱部署路徑 smoke(curl 端點、查 import error)。
- routes-wired 檢查專門擋「模組化把路由接線搞掉」的回歸。

## §#13 — sync 腳本改用共享 client(同樣 device-gated)

`scripts/ebg19p-*-sync.sh`(asset / crypto / monitor / syslog / traffic)各自用 bash(curl + base64 + `login.cgi` / `appGet.cgi`)對**真機** EBG19P 做唯讀 RPC。#13 要把這段 RPC 改走共享的 `ebg19p.py` client(去重跨語言的登入/取值邏輯)。

**為何延後**:這是重寫(shell RPC → python client 呼叫),而每支 sync 的**逐 hook 輸出契約**(`get_clientlist` / `nvram_dump` / `netdev` … 的解析格式)只有對**實體 EBG19P** 才驗得了。無裝置就重寫 = 可能靜默改壞正在運作的 device sync,違反「只要真的東西、別弄壞」。與上面的掃描器叢集同一個閘:**與真機/實 fleet 一起做**,每改一支就對真機驗一次輸出。
