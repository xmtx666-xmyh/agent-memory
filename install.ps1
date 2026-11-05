# agent-memory first-install / new-machine bootstrap (ASCII only)
#
# What it does:
#   1. create .venv if missing and install deps (zstandard, pyyaml, pytest)
#   2. ingest sessions from every supported agent (read-only on their data)
#   3. build topic labels
#   4. generate index/entities.json + index/targets.json for THIS machine
#   5. print this machine's entities so you know what to query
#
# WHY ASCII: PowerShell 5.1 decodes BOM-less .ps1 as ANSI(GBK).
#
# Usage:
#   powershell -NoProfile -ExecutionPolicy Bypass -File install.ps1
#   $env:AGENT_MEMORY_HOME = 'D:\tools\agent-memory'; powershell ... -File D:\tools\agent-memory\install.ps1

$ErrorActionPreference = 'Stop'
# force UTF-8 for python child processes: Windows console defaults to GBK(cp936)
# and printing non-GBK chars (e.g. warning sign) would abort the command.
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'

$here = if ($env:AGENT_MEMORY_HOME) { $env:AGENT_MEMORY_HOME } else { $PSScriptRoot }
Set-Location $here

Write-Host "== agent-memory bootstrap =="
Write-Host "home: $here"

# 1) venv + deps
$venvPy = Join-Path $here '.venv\Scripts\python.exe'
if (-not (Test-Path $venvPy)) {
    Write-Host "[1/6] creating .venv"
    $uv = Get-Command uv -ErrorAction SilentlyContinue
    if ($uv) {
        & uv venv --python 3.12 .venv | Out-Null
    } else {
        & python -m venv .venv
    }
    if (-not (Test-Path $venvPy)) { throw "failed to create .venv" }
} else {
    Write-Host "[1/6] .venv exists"
}

Write-Host "[2/6] installing deps"
$uvCmd = Get-Command uv -ErrorAction SilentlyContinue
if ($uvCmd) {
    & uv pip install --python $venvPy zstandard pyyaml pytest | Out-Null
} else {
    & $venvPy -m pip install --quiet zstandard pyyaml pytest
}

# 3) ingest
Write-Host "[3/6] ingesting sessions (about 45s on ~600 sessions)"
& $venvPy (Join-Path $here 'cli.py') ingest
if ($LASTEXITCODE -ne 0) { throw "ingest failed" }

# 4) topics
Write-Host "[4/6] building topic labels"
& $venvPy (Join-Path $here 'cli.py') topics --build
if ($LASTEXITCODE -ne 0) { throw "topics failed" }

# 5) init entities + targets for this machine
Write-Host "[5/6] generating this machine's entities/targets"
& $venvPy (Join-Path $here 'cli.py') init

Write-Host ""
Write-Host "== this machine's entities (use these in queries) =="
& $venvPy (Join-Path $here 'cli.py') topics --top 15 --pairs 0

# 6) install the DSH skill (copy into the skills catalog so DSH can trigger it)
Write-Host ""
Write-Host "[6/6] installing DSH skill"
$dshHome = if ($env:DSH_HOME) { $env:DSH_HOME } else { Join-Path $env:USERPROFILE '.dsh' }
$skillsDir = Join-Path $dshHome 'skills'
$skillSrc = Join-Path $here 'skill\agent-memory'
$skillDst = Join-Path $skillsDir 'agent-memory'
if (Test-Path $skillSrc) {
    if (-not (Test-Path $skillsDir)) { New-Item -ItemType Directory -Force -Path $skillsDir | Out-Null }
    if (Test-Path $skillDst) { Remove-Item $skillDst -Recurse -Force }
    Copy-Item $skillSrc $skillDst -Recurse -Force
    $n = (Get-ChildItem $skillDst -Recurse -File).Count
    Write-Host "  skill installed: $skillDst ($n files)"
    # sanity check: SKILL.md frontmatter must parse
    $ok = & $venvPy -c "import yaml,io,sys; d=yaml.safe_load(io.open(sys.argv[1],encoding='utf-8').read().split('---')[1]); print(d.get('name') or '')" (Join-Path $skillDst 'SKILL.md')
    if ($ok -eq 'agent-memory') {
        Write-Host "  SKILL.md frontmatter OK (name=agent-memory)"
    } else {
        Write-Host "  WARNING: SKILL.md frontmatter looks broken (parsed name: '$ok')"
    }
} else {
    Write-Host "  WARN: skill folder not found at $skillSrc (zip/git copy incomplete?)"
}

Write-Host ""
Write-Host "Next:"
Write-Host "  - review index\entities.json and merge historical renames (old-name -> new-name),"
Write-Host "    then RE-RUN: cli.py topics --build   (labels are frozen at build time)"
Write-Host "  - review index\targets.json and keep only the projects you actually want"
Write-Host "  - refresh the injected block: skill\agent-memory\scripts\refresh.ps1 (about 45s)"
Write-Host "  - read the skill doc: docs\skill-overview.md"

exit 0
