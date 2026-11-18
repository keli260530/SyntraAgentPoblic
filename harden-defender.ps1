# =====================================================================
#  Microsoft Defender 極限強化腳本（針對未知 / 零時差惡意程式）
#  使用方式：以「系統管理員」身分開啟 PowerShell，執行：
#     Set-ExecutionPolicy -Scope Process Bypass -Force
#     .\harden-defender.ps1
#  若遇到正常程式被誤擋：把 $Mode 改成 2（只稽核不封鎖），觀察一週後再改回 1
# =====================================================================

$Mode = 1   # 1 = Block（封鎖）, 2 = AuditMode（只記錄）, 0 = Disabled

Write-Host "== 1. 雲端防護拉到最高（對未知檔案最關鍵）==" -ForegroundColor Cyan
Set-MpPreference -MAPSReporting Advanced            # 進階雲端回報
Set-MpPreference -SubmitSamplesConsent SendAllSamples # 自動送樣本給雲端分析
Set-MpPreference -CloudBlockLevel ZeroTolerance     # 最嚴格：雲端不認識的程式一律擋
Set-MpPreference -CloudExtendedTimeout 50           # 可疑檔案最多凍結 60 秒等雲端判定

Write-Host "== 2. 即時 / 行為監控全開 ==" -ForegroundColor Cyan
Set-MpPreference -DisableRealtimeMonitoring $false
Set-MpPreference -DisableBehaviorMonitoring $false
Set-MpPreference -DisableIOAVProtection $false
Set-MpPreference -DisableScriptScanning $false
Set-MpPreference -DisableBlockAtFirstSeen $false
Set-MpPreference -DisableArchiveScanning $false
Set-MpPreference -DisableEmailScanning $false
Set-MpPreference -DisableRemovableDriveScanning $false
Set-MpPreference -PUAProtection Enabled             # 封鎖潛在不需要的程式
Set-MpPreference -EnableNetworkProtection Enabled   # 封鎖連往惡意網域
Set-MpPreference -SignatureUpdateInterval 1         # 每小時更新病毒碼

Write-Host "== 3. 受控資料夾存取（防勒索）==" -ForegroundColor Cyan
Set-MpPreference -EnableControlledFolderAccess Enabled

Write-Host "== 4. 攻擊面縮減 (ASR) 規則 ==" -ForegroundColor Cyan
$asr = @{
  '01443614-cd74-433a-b99e-2ecdc07bfc25' = '封鎖「不夠普及/太新/不受信任」的執行檔（對抗全新病毒的核心規則）'
  'c1db55ab-c21a-4637-bb3f-a12568109d35' = '進階勒索軟體防護'
  '56a863a9-875e-4185-98a7-b882c64b5ce5' = '封鎖被濫用的有漏洞簽章驅動程式'
  '9e6c4e1f-7d60-472f-ba1a-a39ef669e4b2' = '封鎖從 LSASS 竊取密碼'
  '5beb7efe-fd9a-4556-801d-275e5ffc04cc' = '封鎖混淆過的腳本'
  'd3e037e1-3eb8-44c8-a917-57927947596d' = '封鎖 JS/VBS 啟動下載的執行檔'
  'be9ba2d9-53ea-4cdc-84e5-9b1eeee46550' = '封鎖郵件中的可執行內容'
  'b2b3f03d-6a65-4f7b-a9c7-1c7ef74a9ba4' = '封鎖 USB 上未簽章程式'
  'e6db77e5-3df2-4cf1-b95a-636979351e5b' = '封鎖 WMI 事件持續化'
  'd4f940ab-401b-4efc-aadc-ad5f3c50688a' = '封鎖 Office 建立子處理程序'
  '3b576869-a4ec-4529-8536-b80a7769e899' = '封鎖 Office 建立執行檔'
  '75668c1f-73b5-4cf0-bb93-3ecf5cb7cc84' = '封鎖 Office 注入其他處理程序'
  '26190899-1602-49e8-8b27-eb1d0a1ce869' = '封鎖 Outlook 建立子處理程序'
  '92e97fa1-2edd-4476-bdd6-9dd0b4dddc7b' = '封鎖 Office 巨集呼叫 Win32 API'
  '7674ba52-37eb-4a4f-a9a1-f0f9a1619a2c' = '封鎖 Adobe Reader 建立子處理程序'
  'd1e49aac-8f56-4280-b9ba-993a6d77406c' = '封鎖 PSExec / WMI 建立處理程序（可能影響部分管理工具）'
}
foreach ($id in $asr.Keys) {
  Add-MpPreference -AttackSurfaceReductionRules_Ids $id -AttackSurfaceReductionRules_Actions $Mode
  Write-Host ("  [{0}] {1}" -f $Mode, $asr[$id])
}

Write-Host "== 5. 弱點驅動程式封鎖清單 ==" -ForegroundColor Cyan
New-Item -Path 'HKLM:\SYSTEM\CurrentControlSet\Control\CI\Config' -Force | Out-Null
Set-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Control\CI\Config' -Name 'VulnerableDriverBlocklistEnable' -Value 1 -Type DWord

Write-Host "== 6. LSA 保護（防止密碼被傾印）==" -ForegroundColor Cyan
Set-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Control\Lsa' -Name 'RunAsPPL' -Value 1 -Type DWord

Write-Host "== 7. 立即更新病毒碼 ==" -ForegroundColor Cyan
Update-MpSignature

Write-Host "`n完成！請重新開機。以下為目前狀態：" -ForegroundColor Green
Get-MpPreference | Select-Object MAPSReporting,CloudBlockLevel,CloudExtendedTimeout,PUAProtection,EnableNetworkProtection,EnableControlledFolderAccess | Format-List
Get-MpComputerStatus | Select-Object RealTimeProtectionEnabled,BehaviorMonitorEnabled,IsTamperProtected | Format-List
