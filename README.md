# SyntraAgent · 桌面操控與 AI 研發監督中心

這是一套專為你的使用習慣量身打造的 Windows 全功能桌面與研發監督 Agent，具備以下核心能力：

## ✨ 核心功能與架構

1. **API Provider 接入與智慧模型路由 (`core/api_manager.py`, `core/model_router.py`, `core/llm_client.py`)**
   - 在「🔑 API Key 接入管理」手動填入 API Key 與端點（金鑰以 Windows DPAPI 加密保存），支援 OpenAI 相容、Anthropic 協議與本機 Ollama。
   - 依任務類型與難度自動挑選模型，首選失敗時自動切換備援。
   - 全程共用連線並以串流逐字輸出；支援原生 tool calling（查詢類工具可並行），不支援的模型自動退回文字協議。
   - 註：舊版說明中的「自動掃描 OpenCode 設定檔」(`core/opencode_loader.py`) 從未接進程式，已於 2026-11-07 移除。

2. **AI 寫程式自動監督閉環 + 3 次卡關智慧熔斷 (`core/supervisor.py`)**
   - 支援選取任意桌面視窗（如 **Antigravity / Cursor / VS Code / OpenCode CLI / 瀏覽器**）。
   - **背景不搶焦點檢查**：使用 Win32 `PrintWindow (PW_RENDERFULLCONTENT)` 在背景擷取視窗畫面，並以無黑窗模式 (`CREATE_NO_WINDOW`) 在背景執行測試指令（如 `pytest`、`npm test`）。
   - **自動回報修復**：當被監督的 AI 回覆完畢但有報錯或未達標時，自動整理修正指令貼回 IDE 對話框。
   - **3 次卡關智慧熔斷**：若連續 3 次（可調）無法修復同一問題，立即暫停自動重試並透過 **Discord** 與 **Gemini 介面** 通知你決定下一步。

3. **遊戲 / 看影片 / 寫功課免打擾保護 (`core/context_guard.py`)**
   - 即時偵測全螢幕遊戲、影音播放器（PotPlayer / VLC / YouTube / Netflix 全螢幕）與滑鼠鍵盤操作狀態 (`GetLastInputInfo`)。
   - 在你打遊戲、看影片或正在打字寫功課時，**嚴格禁止彈窗或搶奪滑鼠焦點**，並自動調降背景程序 CPU 優先權 (`BELOW_NORMAL_PRIORITY_CLASS`) 確保遊戲不掉幀，有事一律改由 **Discord** 通知。

4. **雙向 Discord Bot 通知與遠端互動 (`core/discord_bot.py`)**
   - 支援即時推播：上網透明通報、AI 監督進度/熔斷警報、資安與交易攔截工單（附帶遮罩後截圖）。
   - **手機/遠端雙向操作**：
     - 直接點擊 Discord 訊息下方的按鈕：`[✅ 批准執行]`、`[🛑 拒絕並攔截]`、`[▶️ 重置熔斷並繼續重試 3 次]`。
     - 放行金流交易指令：`!pin <工單ID> <你的安全PIN碼>`
     - 緊急剎車指令：`!stop` 或 `!kill`
     - 直接在設定的 Discord 頻道打字，即可遠端向 Agent 下達任何新指令！

5. **上網內容透明回報 (`core/web_auditor.py`)**
   - 每次搜尋或造訪網頁，即時在 Gemini 介面與 Discord 推送「🌐 網址 + 連線目的 + 內容重點摘要」。
   - 若涉及需登入網站、未知風險網域或上傳資料，強制先攔截並詢問你是否批准。

6. **分級資安防護與嚴禁主動下單 (`core/security_guard.py`)**
   - **禁止主動下單交易**：攔截所有含結帳/購買/下單/付款/轉帳字眼的操作，強制附上截圖並要求輸入你的**安全 PIN 碼**（初始預設為 `0000`，請於設定面板修改）才放行。
   - **敏感視窗自動遮罩**：截圖傳送前自動將密碼管理器（1Password / Bitwarden / KeePass）、網銀與錢包視窗塗黑保護。
   - **防間接 Prompt Injection 沙箱**：所有外部網頁與第三方視窗文字皆包裹於不可信資料沙箱中。
   - **全域緊急停止熱鍵**：隨時按 `Ctrl + Alt + Q` 立即凍結所有桌面操作。

7. **CDR 威脅消除重構、沙箱隔離與電腦防毒中心 (`core/cdr_engine.py`, `core/sandbox_executor.py`, `core/antivirus_scanner.py`)**
   - **CDR (Content Disarm and Reconstruction) 內容無害化重構**：
     - 圖片 CDR：強制像素光柵化重繪，剔除所有 EXIF/XMP/IPTC 隱寫術與 Polyglot 二進制後門。
     - Office / Zip CDR：解包檢驗，強制剝離 VBA 巨集（`vbaProject.bin`）、危險可執行二進制與動態 DDE 注入。
     - PDF CDR：中和並封印 `/JavaScript`, `/JS`, `/Launch`, `/EmbeddedFiles`, `/OpenAction` 等高危標籤。
     - 腳本與文字 CDR：清除 Trojan Source (Bidi U+202E)、零寬隱寫字元與 ANSI Escape 注入碼。
   - **本機安全沙箱執行 (Job Object 限制)**：
     - 採用 Windows Job Object 限制行程記憶體上限 (Max 512MB)、最大行程數 (Max 4)、超時自動熔斷。
     - 環境變數脫敏 (Environment Scrubbing)：自動抹除所有本機 API Key、Token 與密碼，防非信任代碼偷竊憑證。
     - 支援一鍵生成 Windows Sandbox (`.wsb`) 微虛擬機配置隔離執行極高危 EXE。
   - **電腦防毒 (雙引擎防護 + 隔離區 Vault)**：
     - 整合本機 Windows Defender (`MpCmdRun.exe` / `Start-MpScan`) 進行原廠深度防毒。
     - 本地啟發式特徵分析：雙副檔名欺騙偵測、PE MZ 偽裝偵測、香農熵值加殼/加密偵測、勒索軟體特徵指令識別。
     - XOR 混淆加密隔離庫 (`data/quarantine/`)：威脅檔案自動隔離防誤執行，支援解密還原與 0x00 隨機字節多次覆寫徹底粉碎。
     - 開機啟動項 (Registry Run, Startup) 與持久化後門一鍵快篩。

8. **主動網路防禦與網域動態白名單 (`core/active_network_guard.py`)**
   - **動態白名單決策引擎**：支援萬用字元（如 `*.github.com`、`*.google.com`），所有外部網頁抓取與外連連線必須經由白名單檢驗，非白名單網域主動攔截。
   - **惡意 C2 IP 直連攔截**：偵測非信任純公網 IP 直連自動阻斷，杜絕反向 Shell 與未授權遠端控制。
   - **Windows 防火牆動態出站阻斷**：一鍵將惡意 IP 注入 Windows 防火牆出站黑名單 (`netsh advfirewall`)。
   - **本機 Socket 外連即時排查**：背景掃描本機活躍連線，排查是否有非信任 LOLBins (PowerShell/cmd/rundll32) 進行異常外連。

9. **超越傳統防毒之「微秒級主動防禦哨兵」 (`core/hyper_antivirus_sentinel.py`)**
   - **金絲雀誘餌陷阱 (Honeytokens Traps)**：在 Desktop、Documents、Data 目錄布設誘餌檔案。未受信任進程嘗試寫入、覆寫或加密誘餌時，零容忍於 3 毫秒內直接調用 `win32process.TerminateProcess` 物理處決進程。
   - **勒索軟體微秒級加密爆發熔斷 (Burst Encryption Circuit Breaker)**：不依賴過期特徵碼，實時追蹤檔案修改流速；2 秒內連續改動多個檔案且內容香農熵值 $> 7.5$（密碼學加密特徵）即刻判定勒索爆發並瞬間擊殺。
   - **LOLBins 記憶體無檔案攻擊攔截**：監控進程樹，主動擊殺帶有 `-w hidden`、`-enc`、`IEX`、`downloadstring` 等混淆載荷的惡意進程。

10. **全機檔案防篡改與核心防寫保護 (`core/file_integrity_guard.py`)**
   - **Windows 核心排他防寫防刪鎖 (Kernel Exclusive Lock)**：以 `FILE_SHARE_READ` 模式常駐鎖定關鍵檔案控制代碼，作業系統核心層面強制拒絕所有外部行程之寫入或刪除請求（`ERROR_SHARING_VIOLATION`）。
   - **NTFS DACL 防篡改權限硬化**：注入顯式拒絕規則（`icacls /deny Everyone:(DE,DC,WD,AD)`），從檔案系統存取控制層徹底封死覆寫與刪除管道。
   - **Shadow Vault 基準快照與 0 延遲原位自癒 (Self-Healing)**：建立 SHA256 基準線與安全鏡像，檔案遭受惡意竄改、加密或刪除時立即自動回滾還原。
   - **Windows Controlled Folder Access (CFA / 受控資料夾存取) 核心聯動**：連動微軟 `WdFilter.sys` 核心驅動，將資料夾納入白名單受控防寫，阻絕非授權程式入侵。

11. **防奪取電腦控制權 · 防毒不滅自我防護 · 千毒風暴減壓閥 (`core/self_defense_immortal.py`, `core/mass_malware_storm_shield.py`, `core/anti_takeover_guard.py`)**
   - **防毒檔案核心防刪鎖**：以 Win32 `FILE_SHARE_READ` 常駐鎖定防毒軟體所有核心代碼與模組（39 個核心檔案），任何外部病毒執行 `del /f /q` 或竄改，作業系統核心直接回傳 `STATUS_SHARING_VIOLATION`，物理上無法被刪除。
   - **雙子不滅守護看門狗**：獨立守護行程（`scripts/watchdog_immortal.py`）與主進程互結心跳，遭受外部暴力 `taskkill /F` 時於 50 毫秒內瞬間自癒重啟復活。
   - **千毒並發湧浪風暴減壓閥**：監控進程生成速率，1 秒內出現湧浪立即以 `ntdll.NtSuspendProcess` 毫秒級全域並行凍結惡意進程群，並透過線程池高並發平行處決（實測 14 毫秒內凍結並處決 15 個風暴進程）。
   - **防搶奪電腦控制權與 RAT 阻斷**：排查影子管理員帳號（`net user /add` 自動剝奪權限）、阻斷遠端接管工具（AnyDesk/TeamViewer/VNC）、強制攔截破壞性全盤指令（`manage-bde` BitLocker 劫持、`bcdedit safeboot` 安全模式降級、`vssadmin delete shadows`）。

12. **超越傳統 360 / 小紅傘 · 記憶體動態脫殼審查與底層 Minifilter 驅動 (`core/memory_injection_sentinel.py`, `drivers/anti_tamper_minifilter.c`)**
   - **記憶體動態脫殼審查 (EDR In-Memory Dynamic Inspection)**：360 與小紅傘依賴磁碟靜態檔案特徵碼，對加殼 (Themida/VMProtect) 與無檔案注入 (Process Hollowing) 束手無策。本哨兵利用 Win32 `VirtualQueryEx` 深入活體進程虛擬記憶體，實時攔截私有可執行記憶體區段 (`PAGE_EXECUTE_READWRITE` + `MEM_PRIVATE`) 與無實體模組對應之展開 `MZ` 標頭，在惡意程式動態解密執行前即刻擊殺。
   - **核心 Minifilter 驅動架構 (`anti_tamper_minifilter.c`)**：攔截 `IRP_MJ_CREATE` 與 `IRP_MJ_WRITE`，徹底封死 `\\Device\\Harddisk*` DASD 原始磁區繞過；以 `ObRegisterCallbacks` 剝除外部進程的 `PROCESS_TERMINATE` 與 `PROCESS_DUP_HANDLE` 權限，從 NT 核心層徹底免疫各類 KillAV 驅動摘除攻擊。

13. **AI 自適應攻擊鏈推演 · 動態微補丁熱修補 · 深度溯源物理粉碎 (`core/predictive_immune_engine.py`, `core/threat_hunter_tracer.py`)**
   - **MITRE ATT&CK 攻擊鏈狀態機推演 (Predictive Attack Graph)**：當攻擊者在某節點嘗試突破時，系統實時計算下一步轉移機率（如憑證存取失敗 -> 94% 轉向 SAM Hive 讀取 / 88% 轉向 DPAPI Vault）。
   - **零延遲提前封堵 (Preemptive Hardening)**：針對機率 $\ge 75\%$ 之預測向量，提前掛載唯讀鎖、收緊 SMB/RPC 防火牆、切斷 WMI/Schtasks 排程註冊通道，使病毒下一步步步踏空。
   - **動態微補丁即時生成 (Autonomous Micro-Patching)**：即時針對漏洞路徑注入 NTFS 顯式拒絕 DACL 或動態防火牆規則，無需重啟系統完成熱修補。
   - **全生命週期溯源獵捕與物理粉碎 (DoD 5220.22-M Annihilation)**：逆向爬梳進程祖譜樹 (PPID 鏈)，掃描並捕獲臨時目錄中的釋放體 (Droppers)，以 XOR 0x5A 混淆存檔後，以 `0x00` -> `0xFF` -> 隨機位元組 3 輪覆寫磁區清零粉碎。

14. **末日資料要塞 · 自身主動修復補齊 · 主動反殺核心 (`core/doomsday_data_citadel.py`, `core/self_healing_regenerator.py`, `core/counter_strike_offensive.py`)**
   - **末日資料要塞 (OS 崩潰死守)**：AES-256-GCM 軍規加密 + 隨機 Nonce 封存。常駐監控 OS 生命徵象，當可用 RAM 枯竭或核心進程 `csrss.exe` 死亡（BSOD 前夕），微秒內將 RAM 中主密鑰使用 0x00 清零銷毀 (Zeroize Memory Keys) 並鎖死實體磁區，即便攻擊者將硬碟拆下掛到其他電腦或 WinPE 亦物理無法解密。
   - **自身受損主動修補補齊 (Regenerative Self-Healer)**：建立 43 個核心模組的黃金根源映像指紋庫。當防毒自身檔案遭惡意截斷、清空至 0 bytes 或篡改時，微秒級原位重構寫入純淨母本代碼，完美補齊受損代碼並觸發全域反撲。
   - **主動反殺與持久化清剿 (Counter-Strike & Persistence Sweep)**：調用 `AdjustTokenPrivileges` 主動拔除攻擊者進程所有 Token 特權 (`SeDebugPrivilege` 等)；調用 `CreateRemoteThread` 遠程注入 `kernel32!ExitProcess` 迫使病毒在自身記憶體環境內自我了結；並連根拔除病毒在註冊表 (Run/RunOnce) 與工作排程器 (Schtasks) 所有的立足點。

15. **作業系統急救心肺復甦 · 系統救活與關鍵配置校準 (`core/os_resuscitation_cpr.py`)**
   - **資源除顫與惡意死鎖釋放**：微秒級清剿卡死 CPU/RAM 的 Swarm 攻擊進程，避免 OS 假死。
   - **系統管理限制政策全面解除**：解鎖 `DisableTaskMgr` (工作管理員)、`DisableRegistryTools` (登錄編輯器)、`DisableCMD`，恢復管理員控制權。
   - **Winlogon 核心啟動鏈原位校準**：校準修復被惡意劫持的 `Shell` (強制恢復為 `explorer.exe`) 與 `Userinit`。
   - **IFEO 映像劫持清洗**：清空所有針對系統除錯工具之惡意 Debugger 替換。
   - **救活核心服務命脈**：修復並重啟 RPC (`RpcSs`)、WMI (`Winmgmt`)、Cryptographic Services (`CryptSvc`)、VSS 與 EventLog。

16. **BYOVD 核心驅動提權防護與早期開機 (TOCTOU) 審查 (`core/byovd_and_kernel_sentinel.py`)**
   - **BYOVD (Bring Your Own Vulnerable Driver) 惡意核心驅動阻斷**：內建 LOLDrivers 易受攻擊合法簽名驅動特徵庫（如 `RTCore64.sys`, `gdrv.sys`, `capcom.sys`, `procexp.sys` 等），主動封鎖其載入與執行，防止紅方在 Ring 0 透過任意內核讀寫強行拔除 EDR 回調。
   - **開機時間差 (TOCTOU) 審查**：審查 `Start=0` (BOOT_START) 與 `Start=1` (SYSTEM_START) 早期啟動項，排查非微軟標準目錄之預載入後門。
   - **Token 模擬提權硬化**：排查並收緊非系統特權帳號之 `SeImpersonatePrivilege`，阻斷各類 Potato 家族本地權限提升。

17. **全職數位同事感知與自治工作流架構 (`core/ghost_desktop_worker.py`, `core/ui_automation_driver.py`, `core/idle_autonomy_engine.py`, `core/semantic_clipboard_hud.py`, `core/episodic_timeline_memory.py`)**
    - **幽靈虛擬桌面執行器 (Ghost Desktop Worker)**：利用 Win32 `CreateDesktopW` 建立獨立虛擬 Win32 桌面，調度任何 GUI 程式在背後執行，完全不搶奪物理滑鼠游標與螢幕焦點。
    - **原生 UI Automation 語意驅動 (Accessibility Tree)**：直連 Windows IUIAutomation 元素樹，不依賴 OCR 與脆弱座標，毫秒級後台讀寫 Edit 欄位與調用 InvokePattern 點擊按鈕。
    - **離席自律維護引擎 (Idle Autonomy Engine)**：監控 `GetLastInputInfo`，在用戶離開或鎖定螢幕時自動進行專案 Git 狀態盤點、單元測試排查與維護，回歸時即刻生成工作簡報。
    - **語意剪貼簿智慧助理 (Semantic Clipboard HUD)**：掛載 Win32 `AddClipboardFormatListener` 零延遲監聽，即時分類 Traceback 報錯、JSON、SQL、cURL 與 Git Diff 並預判需求。
    - **情境記憶與活動時空歷程 (Episodic Timeline Memory)**：追蹤前景焦點視窗切換與停留時長，SQLite 本機持久化，隨時提供「你在何時做了什麼」之完整情境回溯。

18. **Google Workspace 全家桶套裝原生整合 (`core/google_workspace_suite.py`, `skills/google-workspace/SKILL.md`)**
    - **Gmail 郵件管理**：支援搜尋條件篩選（`is:unread` 等）、郵件內文讀取與安全代發。
    - **Google Drive 雲端硬碟**：支援全文/檔名檢索、本地檔案自動同步、直接字串寫入雲端 Markdown/文件。
    - **Google Calendar 行事曆**：查詢未來會議日程、自動預約會議並建立日程提醒。
    - **Google Docs & Sheets**：原生串接 Docs 文件讀寫與 Sheets 試算表表格數據追加，支援自動產出工作日誌與報表。
    - **零配置本機瀏覽器降級模式**：若未填入 GCP API 憑證，支援一鍵直接調用本機瀏覽器打開對應 Google 服務頁面。

19. **TOTP 雙因子身分驗證器 (人可關/毒不可關) · 智慧下載放行 · 自適應三點共生無限復活 (`core/totp_authenticator_guard.py`, `core/adaptive_symbiotic_guardian.py`)**
    - **智慧無感下載放行與瀏覽器 JIT 保護**：白名單放行所有主流瀏覽器 (`chrome.exe`, `msedge.exe`, `firefox.exe`, `brave.exe`) 與下載工具之 V8/SpiderMonkey JIT `RWX` 分頁，僅針對含有未對齊反射式 `MZ` 標頭之真正注入分頁處決；預設開放合法網域 `GET/HEAD` 下載並攔截純公網 IP C2 直連，絕不干擾日常檔案下載與安裝。
    - **人可關、毒不可關 (TOTP + 實體鍵盤 `LLKHF_INJECTED` 鑑別)**：廢除 `exit_code == 0` 與明文 `sentinel_stop.flag` 退場判斷！關閉或解除安裝必須輸入手機 Google/Microsoft Authenticator 之 6 位數動態驗證碼，並檢查實體硬體按鍵事件，拒絕任何透過 `SendInput`、`keybd_event`、剪貼簿貼上或 `WM_SETTEXT` 合成之自動化攻擊。
    - **三點分散式共生基因膠囊與自適應無限復活**：將 60 個核心程式碼壓縮並以 `XOR 0xA7` 混淆封裝為 `syntra_gene.capsule`，分散共生於 `%LOCALAPPDATA%\SyntraSentinel`、`%APPDATA%\SyntraHub` 與 `data\.golden_root`。任何未持有效 HMAC-SHA256 TOTP 退場憑證的殺進程或刪檔行為，均會在 300ms 內從存活膠囊自動原位重構所有程式碼並無限復活，同時自動提升自適應防禦等級 (Level 0 $\rightarrow$ Level 3)。

## 🚀 啟動方式與捷徑

- **桌面捷徑**：執行 `python scripts/setup_startup_and_shortcut.py` 會在你的桌面建立「開啟 Gemini 桌面 Agent」捷徑；也可以直接雙擊專案內的 `開啟_Gemini_Agent.bat`。
- **開機自主啟動**：已註冊於 Windows `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`，開機時會以 `--tray` 靜默常駐於右下角系統列（System Tray），不主動彈窗搶畫面；雙擊桌面捷徑或點擊右下角 `✦` 圖示即可隨時喚醒 Gemini 視窗。
