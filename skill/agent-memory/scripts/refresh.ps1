# agent-memory daily refresh (ASCII only on purpose)
#
# Runs: ingest -> topics --build -> regenerate each project's .agent-memory\context.md
#
# WHY ASCII: PowerShell 5.1 decodes BOM-less .ps1 as ANSI(GBK); Chinese in this file
# would turn into mojibake and break parsing. Chinese lives in targets.json (read as UTF-8).
#
# Manual run:
#   powershell -NoProfile -ExecutionPolicy Bypass -File <skill>\scripts\refresh.ps1
#
# Register (daily 06:30) -- NOT done automatically; review then run:
#   schtasks /Create /TN "agent-memory-daily" /SC DAILY /ST 06:30 ^
#       /TR "powershell -NoProfile -ExecutionPolicy Bypass -File \"<skill>\scripts\refresh.ps1\"" /F

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '_resolve.ps1')

$amHome = Resolve-AmHome
$py  = Resolve-AmPython $amHome
$cli = Join-Path $amHome 'cli.py'
$log = Join-Path $amHome 'index\daily-refresh.log'
# targets live in the DATA dir (per-machine), NOT in the skill dir:
#   <home>\index\targets.json
# Rationale: which projects exist differs per machine; the skill must stay generic.
$targetsFile = Join-Path $amHome 'index\targets.json'

if (-not (Test-Path $py))  { throw "interpreter not found: $py" }
if (-not (Test-Path $cli)) { throw "cli.py not found: $cli" }

function Write-Log($msg) {
    $line = "{0}  {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg
    $dir = Split-Path $log -Parent
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    Add-Content -Path $log -Value $line -Encoding UTF8
    Write-Host $line
}

# read targets as UTF-8 (do not use Get-Content default encoding here)
$targets = @()
if (Test-Path $targetsFile) {
    $json = [System.IO.File]::ReadAllText($targetsFile, [System.Text.Encoding]::UTF8)
    $targets = ($json | ConvertFrom-Json).targets
} else {
    Write-Log "WARN: targets.json not found, only ingest+topics will run"
}

Write-Log "=== start ==="
$t0 = Get-Date
try {
    & $py $cli ingest         | Out-Null ; Write-Log "ingest ok"
    & $py $cli topics --build | Out-Null ; Write-Log "topics ok"
} catch {
    Write-Log ("**ingest/topics FAILED**: " + $_.Exception.Message)
    exit 1
}

foreach ($t in $targets) {
    $outDir = Split-Path $t.out -Parent
    if (-not (Test-Path $outDir)) { New-Item -ItemType Directory -Force -Path $outDir | Out-Null }
    & $py $cli inject $t.entity --write $t.out | Out-Null
    if (Test-Path $t.out) {
        $size = (Get-Item $t.out).Length
        Write-Log ("inject ok: {0} -> {1} ({2} bytes)" -f $t.entity, $t.out, $size)
    } else {
        Write-Log ("**inject FAILED**: " + $t.out)
    }
}
Write-Log ("=== done in {0:N0}s ===" -f ((Get-Date) - $t0).TotalSeconds)
