' open-webui-hidden.vbs - ensure the Web UI is listening, then open it in the browser.
'
' This is the target behind the desktop shortcut: one double-click either brings the
' service up or finds it already running, then lands on the page. The ensure step is the
' same script the scheduled task uses, so both paths share one definition of "is it up".
'
' Kept pure ASCII for the same reason as run-webui-hidden.vbs (WSH reads a .vbs on the
' system ANSI code page without a UTF-16 BOM).
Option Explicit

Dim fso, shell, base, ensure, url
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

base = fso.GetParentFolderName(WScript.ScriptFullName)
ensure = base & "\ensure-webui.ps1"
url = "http://127.0.0.1:8714/"

On Error Resume Next
If fso.FileExists(ensure) Then
    ' Wait for the ensure pass so the page is not opened before the port is listening.
    shell.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & ensure & """", 0, True
End If
shell.Run url, 1, False
WScript.Quit 0
