# EBG19P 操作知識庫 — worker-a(IT 運維節點)

本檔是 worker-a 對 ASUS ExpertWiFi **EBG19P** 商用 VPN 閘道的操作知識。worker-a 是負責這台設備的 IT operator,
應依此知識執行設定查詢與安全 remediation。資產代號 `lab-asus-ebg19p-01`。

## 連線與認證
- 管理介面:**HTTP**(明文,未開 HTTPS/SSH);位址 `192.168.50.1`(實機靜態)。worker-a 容器可直連。
- 登入:`POST /login.cgi`,body `login_authorization=base64(user:pass)` → 回應 Set-Cookie `asus_token=...`。
- 讀設定:`GET /appGet.cgi?hook=nvram_get(<key>)`(帶 Cookie `asus_token`)。
- 套用設定:`POST /applyapp.cgi`,body `action_mode=apply&action_script=<script>&action_wait=10&<key>=<value>`。
- ⚠️ 套用會觸發服務 restart(restart_wireless/restart_firewall 等),期間裝置短暫無回應且 **asus_token 失效** → 重讀驗證前要重登。
- ⚠️ ASUS 是**單一 session**:多處同時登入會互相作廢 token(host streamer / cron / 本操作彼此會搶)。

## 安全 remediation 操作(確定性、可逆、附驗證)
這些已在端點 `/fix` 以 `EBG_ACTIONS` 確定性實作(不需 LLM)。Hermes 委派 `{"bug":"<id>"}` 到節點 A:

| bug id        | nvram key      | 目標 | apply script      | 用途 |
|---------------|----------------|------|-------------------|------|
| `ebg-wps`     | wps_enable     | 0    | restart_wireless  | 停用 WPS(PIN 易暴力破解) |
| `ebg-wps-on`  | wps_enable     | 1    | restart_wireless  | 啟用 WPS(測試用) |
| `ebg-upnp`    | upnp_enable    | 0    | restart_firewall  | 停用 UPnP(避免自動對外開埠) |
| `ebg-samba`   | enable_samba   | 0    | restart_nasapps   | 停用 Samba 檔案分享 |
| `ebg-ftp`     | enable_ftp     | 0    | restart_nasapps   | 停用 FTP 伺服器 |
| `ebg-ddns`    | ddns_enable_x  | 0    | restart_ddns      | 停用 DDNS |
| `ebg-telnet`  | telnetd_enable | 0    | restart_time      | 停用 Telnet(明文,務必關) |
| `ebg-ssh`     | sshd_enable    | 0    | restart_time      | 停用 SSH 服務 |
| `ebg-wanweb`  | misc_http_x    | 0    | restart_httpd     | 停用 WAN 遠端網頁管理 |
| `ebg-dos`     | fw_dos_x       | 1    | restart_firewall  | 啟用 DoS 防護 |
| `ebg-fw-on`   | fw_enable_x    | 1    | restart_firewall  | 啟用防火牆 |
| `ebg-aiprotect` | TM_EULA + wrs_enable + wrs_mals_enable + bwdpi_db_enable = 1 | restart_wrs | **啟用 AiProtection 惡意網站封鎖**(多鍵;TrendMicro WRS) |
| `ebg-aiprotect-off` | wrs_enable + wrs_mals_enable = 0 | restart_wrs | 停用 AiProtection 惡意網站封鎖 |

⚠️ **AiProtection 依賴**:惡意網站封鎖靠 TrendMicro 訊號庫(`bwdpi_sig_ver`),需**接受 EULA(TM_EULA=1)** + **有 WAN/網路**才能下載/更新訊號。本機目前無 WAN(wan0_ipaddr=0.0.0.0、bwdpi_sig_ver 空)→ 開關可設成功(nvram=1),但實際封鎖要等裝置有對外網路拉到訊號庫才生效。worker-a 會誠實回報「已啟用設定;訊號庫待網路同步」。

執行後端點會重讀 nvram 驗證 before/after,並以正確 `asset=lab-asus-ebg19p-01` 回報;驗收未過 → 自動開 Jira 升級工程師(人在迴路)。
新增操作的方法:在 `EBG_ACTIONS` 加一列 `(nvram_key, 目標值, action_script, 描述)`——key 須先以 `appGet.cgi?hook=nvram_get(key)` 確認存在,script 用對應子系統的標準 restart_*(wireless/firewall/httpd/nasapps/ddns/time)。
⚠️ applyapp.cgi 一定會寫入 nvram(故 nvram 驗證會過),但服務即時生效取決於 action_script 是否對該子系統;不確定即時性的操作在 KB 註明、必要時以重開機保證。

## 其他可查詢的安全相關鍵(現況硬化基準)
telnetd_enable / sshd_enable(遠端管理服務,應為 0)、fw_enable_x(防火牆,應為 1)、
misc_httpsport_x(HTTPS 埠)、bwdpi_db_enable(AiProtection)、wan_nat_x、dmz_ip(DMZ 應空)。
未列入 EBG_ACTIONS 的變更屬「需人工確認」——worker-a 不擅自猜 nvram 鍵/script,改開 Jira 由工程師處理(誠實、不假裝)。

## 邊界
- 只做上表確定性操作 + 唯讀查詢;破壞性/不確定操作一律升級工程師。
- 這台 WAN 目前未取得 IP(DHCP 0.0.0.0、link flap),屬使用者環境;非本知識庫處理範圍。
