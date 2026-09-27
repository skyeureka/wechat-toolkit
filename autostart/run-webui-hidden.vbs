' run-webui-hidden.vbs - launch ensure-webui.ps1 with no console window.
'
' Registered as the scheduled task action instead of powershell.exe directly, because a
' -WindowStyle Hidden powershell action still flashes a window. Kept pure ASCII: Windows
' Script Host decodes a .vbs with the system ANSI code page unless it carries a UTF-16
' BOM, so a non-ASCII path literal here would silently stop resolving.
'
' Waits for the child (True) and propagates its exit code, so the task can actually
' retry a failure. The False form returns before the work starts and makes a crash look
' like success.
'
' Every failure path is logged through Note(), which creates its own directory first and
' runs with On Error Resume Next. Writing to a missing parent directory raises a runtime
' error, and an unhandled one makes WSH pop a MODAL dialog that blocks until a human
' clicks it - that is how a background launcher ends up frozen on screen.
Option Explicit

Dim fso, shell, base, ps1, logDir, logFile, rc
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

base = fso.GetParentFolderName(WScript.ScriptFullName)
ps1 = base & "\ensure-webui.ps1"
logDir = base & "\logs"
logFile = logDir & "\launcher-error.log"

On Error Resume Next
If Not fso.FolderExists(logDir) Then fso.CreateFolder(logDir)

If fso.FileExists(ps1) Then
    rc = shell.Run("powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & ps1 & """", 0, True)
Else
    Note "ERROR launcher: script not found at " & ps1
    rc = 1
End If

WScript.Quit rc

' Best-effort log write; never raises, never shows a dialog.
Sub Note(msg)
    On Error Resume Next
    Dim log
    If Not fso.FolderExists(logDir) Then fso.CreateFolder(logDir)
    Set log = fso.OpenTextFile(logFile, 8, True)
    log.WriteLine Now & " " & msg
    log.Close
    On Error GoTo 0
End Sub
