# 編譯一鍵安裝啟動器 Syntra_Setup.exe（輸出到專案根目錄）
# 使用 Windows 內建的 .NET Framework C# 編譯器，不需要另外安裝任何工具。
# 用法：powershell -ExecutionPolicy Bypass -File installer\build_exe.ps1
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$csc = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path $csc)) { $csc = Join-Path $env:WINDIR 'Microsoft.NET\Framework\v4.0.30319\csc.exe' }
if (-not (Test-Path $csc)) { throw '找不到 .NET Framework 4 的 csc.exe' }

$src = Join-Path $PSScriptRoot 'launcher\SyntraSetup.cs'
$out = Join-Path $root 'Syntra_Setup.exe'
$icon = Join-Path $root 'assets\gemini_icon.ico'
$cscArgs = @('/nologo', '/target:exe', '/optimize+', '/codepage:65001', "/out:$out")
if (Test-Path $icon) { $cscArgs += "/win32icon:$icon" }
$cscArgs += $src

& $csc @cscArgs
if ($LASTEXITCODE -ne 0) { throw "編譯失敗（代碼 $LASTEXITCODE）" }
Write-Host "完成：$out"
