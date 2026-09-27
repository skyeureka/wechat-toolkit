# register-webui-task.ps1 - keep the ChatTrace Web UI reachable at a fixed address.
#
# Creates (or updates) one scheduled task so http://127.0.0.1:8714/ is available after
# every logon without anyone starting it by hand. Reuses an existing task's own settings
# object when present so a re-run merges rather than clobbers.
#
# Action is wscript.exe running a .vbs launcher: a -WindowStyle Hidden powershell action
# still flashes a console window, and the VBS waits and propagates a real exit code so
# RestartOnFailure can actually engage.
$ErrorActionPreference = 'Stop'

$TaskName = 'ChatTrace Web UI'
$Base     = 'T:\wx4win\wechat-toolkit\autostart'
$Vbs      = Join-Path $Base 'run-webui-hidden.vbs'
$User     = "$env:USERDOMAIN\$env:USERNAME"

if (-not (Test-Path $Vbs)) { throw "launcher not found: $Vbs" }

$action = New-ScheduledTaskAction -Execute 'wscript.exe' -Argument ('"' + $Vbs + '"')

# Logon trigger, delayed past the boot-time I/O storm (disks/AV/indexers still busy).
$logon = New-ScheduledTaskTrigger -AtLogOn -User $User
$logon.Delay = 'PT1M30S'

# Repeating trigger so a service that dies mid-session comes back on its own, which is
# exactly the failure the operator hit (the process was killed and nothing restarted it).
$repeat = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
            -RepetitionInterval (New-TimeSpan -Minutes 30) `
            -RepetitionDuration (New-TimeSpan -Days 3650)

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    $settings = $existing.Settings          # reuse, do not construct fresh
    Write-Host "existing task found: reusing its settings"
} else {
    $settings = New-ScheduledTaskSettingsSet
}
$settings.RestartCount       = 3
$settings.RestartInterval    = 'PT2M'
$settings.StartWhenAvailable = $true
$settings.ExecutionTimeLimit = 'PT10M'
$settings.AllowDemandStart   = $true

if ($existing) {
    Set-ScheduledTask -TaskName $TaskName -Action $action -Settings $settings `
        -Trigger @($logon, $repeat) | Out-Null
    Write-Host "updated task: $TaskName"
} else {
    Register-ScheduledTask -TaskName $TaskName -Action $action -Settings $settings `
        -Trigger @($logon, $repeat) -Description 'Keep the ChatTrace WeChat viewer listening on 127.0.0.1:8714' | Out-Null
    Write-Host "registered task: $TaskName"
}

$t = Get-ScheduledTask -TaskName $TaskName
Write-Host ''
Write-Host "state    : $($t.State)"
Write-Host "action   : $($t.Actions[0].Execute) $($t.Actions[0].Arguments)"
$t.Triggers | ForEach-Object { Write-Host "trigger  : $($_.CimClass.CimClassName) delay=$($_.Delay) rep=$($_.Repetition.Interval)" }
Write-Host "restart  : count=$($t.Settings.RestartCount) interval=$($t.Settings.RestartInterval)"
