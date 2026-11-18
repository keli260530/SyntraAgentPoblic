' Syntra 星樞 · 100% 靜默無黑框啟動腳本
Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
currentDir = fso.GetParentFolderName(WScript.ScriptFullName)
appdata = WshShell.ExpandEnvironmentStrings("%APPDATA%")
localappdata = WshShell.ExpandEnvironmentStrings("%LOCALAPPDATA%")
launcherPath = appdata & "\SyntraHub\launcher.py"
If Not fso.FileExists(launcherPath) Then
    launcherPath = currentDir & "\desktop_app.py"
End If
pythonwPath = localappdata & "\Programs\Python\Python311\pythonw.exe"
If Not fso.FileExists(pythonwPath) Then
    pythonwPath = "pythonw.exe"
End If

' 0 = 徹底隱藏命令列黑框，完全在背景運行
WshShell.Run """" & pythonwPath & """ """ & launcherPath & """", 0, False
