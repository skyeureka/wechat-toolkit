# ensure-webui.ps1 - keep the ChatTrace Web UI listening on 127.0.0.1:8714.
#
# Idempotent by design: the port is the single source of truth, so an overlapping run
# (or a boot that already started it) exits 0 without spawning a second instance.
# Exit code is honest, so the scheduled task can retry a real failure.
$ErrorActionPreference = 'Stop'

$Port   = 8714
$Root   = 'T:\wx4win\wechat-toolkit'
$Python = Join-Path $Root 'venv\Scripts\python.exe'
$LogDir = Join-Path $PSScriptRoot 'logs'
$Log    = Join-Path $LogDir 'ensure-webui.log'

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

# A hidden run has no console, so [Console]::OutputEncoding does nothing here; write
# through .NET with an explicit encoding (no BOM) to keep the log legible.
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
function Write-Log([string]$Message) {
    $line = '{0} {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message
    [System.IO.File]::AppendAllText($Log, $line + [Environment]::NewLine, $Utf8NoBom)
}

function Test-PortUp {
    $l = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    return [bool]$l
}

if (Test-PortUp) {
    Write-Log "already listening on $Port - no action (exit 0)"
    exit 0
}

if (-not (Test-Path $Python)) {
    Write-Log "ERROR python interpreter missing: $Python (exit 1)"
    exit 1
}

Write-Log "starting: $Python -m chattrace webui --host 127.0.0.1 --port $Port"
try {
    Start-Process -FilePath $Python `
        -ArgumentList '-m', 'chattrace', 'webui', '--host', '127.0.0.1', '--port', "$Port", '--no-browser' `
        -WorkingDirectory $Root -WindowStyle Hidden -ErrorAction Stop
} catch {
    Write-Log "ERROR failed to spawn: $($_.Exception.Message) (exit 1)"
    exit 1
}

# Wait for the artifact the service owns (its port), not the child's exit code: the
# spawn returns immediately and says nothing about whether it came up.
$deadline = (Get-Date).AddSeconds(60)
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 2
    if (Test-PortUp) {
        Write-Log "listening on $Port after start (exit 0)"
        exit 0
    }
}

Write-Log "ERROR did not come up within 60s (exit 1)"
exit 1
