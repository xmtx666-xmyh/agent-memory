# One-time setup for the agent-memory skill package (ASCII only).
#
# WHY ASCII: PowerShell 5.1 decodes a BOM-less .ps1 as ANSI(GBK); non-ASCII
# characters turn into mojibake and break parsing.
#
# Layout of the package (the platform allows only ONE level of subdirectories):
#   <skill>\SKILL.md, requirements.txt, cli.py, collectors\, scripts\, ...
# So the engine (cli.py) sits at the skill ROOT, one level above this script.
#
# Creates <skill>\.venv, installs requirements, then runs the first ingest of
# THIS machine's agent sessions (read-only on their data).
#
# Usage:
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\bootstrap.ps1
#
# Interpreter discovery order: uv -> py launcher -> python on PATH ->
# well-known install dirs. Nothing here is bound to a drive or project path.

$ErrorActionPreference = 'Stop'
# Absolute: with '-File scripts\bootstrap.ps1' PowerShell would otherwise keep a
# relative $PSScriptRoot, and every derived path (venv, engine, data) would be
# relative to whatever cwd the caller happened to use.
$here = (Resolve-Path $PSScriptRoot).Path
$root = Split-Path $here -Parent
$cli  = Join-Path $root 'cli.py'
$req  = Join-Path $root 'requirements.txt'

if (-not (Test-Path $cli)) {
    throw "cli.py not found: $cli  (bootstrap.ps1 is for the packaged skill layout: cli.py at the skill root; in a git checkout run install.ps1 from the project root)"
}

# Python children print Chinese; keep them UTF-8 whatever the console codepage is.
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'

function Find-PythonExe {
    # returns @{ Path = <exe>; Launcher = <bool> } or $null
    $c = Get-Command python -ErrorAction SilentlyContinue
    if ($c) { return @{ Path = $c.Source; Launcher = $false } }
    $c = Get-Command py -ErrorAction SilentlyContinue
    if ($c) { return @{ Path = $c.Source; Launcher = $true } }
    foreach ($p in @(
            (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python313\python.exe'),
            (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'),
            (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python311\python.exe'),
            'C:\Python313\python.exe',
            'C:\Python312\python.exe',
            'C:\Python311\python.exe')) {
        if ($p -and (Test-Path $p)) { return @{ Path = $p; Launcher = $false } }
    }
    return $null
}

$venvPy = Join-Path $root '.venv\Scripts\python.exe'
$uv = Get-Command uv -ErrorAction SilentlyContinue

if (-not (Test-Path $venvPy)) {
    Write-Host "creating venv at $root\.venv"
    if ($uv) {
        & $uv.Source venv --python 3.12 (Join-Path $root '.venv') | Out-Null
    } else {
        $py = Find-PythonExe
        if (-not $py) { throw "no Python found: install Python 3.11+ (or uv), then rerun" }
        Write-Host "using interpreter: $($py.Path)"
        if ($py.Launcher) {
            & $py.Path -3 -m venv (Join-Path $root '.venv')
        } else {
            & $py.Path -m venv (Join-Path $root '.venv')
        }
    }
    if (-not (Test-Path $venvPy)) { throw "venv creation failed (see messages above)" }
}

Write-Host "installing requirements (first run needs network)"
if ($uv) {
    # uv-created venvs ship without pip, so install through uv's pip front-end.
    & $uv.Source pip install --python $venvPy --quiet -r $req
} else {
    & $venvPy -m pip install --quiet --disable-pip-version-check -r $req
}
if ($LASTEXITCODE -ne 0) { throw "dependency install failed" }

Write-Host "first ingest (about 45s, reads this machine's sessions only)"
& $venvPy $cli ingest
if ($LASTEXITCODE -ne 0) { throw "ingest failed" }

Write-Host "building topic labels"
& $venvPy $cli topics --build
if ($LASTEXITCODE -ne 0) { throw "topics failed" }

Write-Host "generating this machine's entities/targets"
& $venvPy $cli init
if ($LASTEXITCODE -ne 0) { throw "init failed" }

Write-Host ""
Write-Host "== this machine's entities =="
& $venvPy $cli topics --top 15 --pairs 0
Write-Host ""
Write-Host "done. try: powershell -NoProfile -ExecutionPolicy Bypass -File scripts\am.ps1 search <keyword> --trigram"
exit 0
