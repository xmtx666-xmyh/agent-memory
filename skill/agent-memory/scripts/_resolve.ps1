# Shared home resolver for agent-memory scripts (ASCII only)
#
# Why a shared file: am.ps1 / refresh.ps1 both need "where is the project?".
# Resolution order (works for BOTH layouts):
#   1. $env:AGENT_MEMORY_HOME (explicit wins)
#   2. platform package layout: cli.py sits ONE level above scripts\  -> <skill>\cli.py
#   3. walk up from this script looking for cli.py  -> works when the skill sits
#      inside the project (<home>\skill\agent-memory\scripts)
#   4. $env:USERPROFILE\agent-memory                -> default install location
#   5. fail with a ACTIONABLE message + exit code 3 (never guess silently)
#
# WHY ASCII (again): Windows PowerShell 5.1 decodes a BOM-less .ps1 as ANSI(GBK);
# Chinese here would turn into mojibake and break parsing. So the failure text is
# English but it tells the caller exactly what to run.
#
# NOTE: the platform only allows ONE level of subdirectories inside a skill zip,
# so the engine lives at the package root next to SKILL.md (no scripts\engine\).
#
# NOTE: do NOT hardcode this machine's drive (e.g. F:\) as a fallback; that is
# exactly what made the skill non-portable.

#: exit code for "skill installed but the project (cli.py) was not found"
$script:AmExitNotInitialised = 3

function Get-AmSkillDir { return (Split-Path $PSScriptRoot -Parent) }

function Write-AmNotInitialised {
    $skill = Get-AmSkillDir
    $fallback = Join-Path $env:USERPROFILE 'agent-memory'
    $msg = @(
        "",
        "agent-memory is NOT initialised on this machine: no cli.py was found.",
        "",
        "  searched:",
        "    $skill\cli.py                     (packaged skill layout)",
        "    up to 6 parent folders of         $PSScriptRoot",
        "    `$env:USERPROFILE\agent-memory    ($fallback)",
        "",
        "  what it means: this skill only ships wrappers. The index database and the",
        "  Python venv live in a PROJECT folder, which does not exist here yet.",
        "",
        "  fix A (recommended, 1 line): point the resolver at the project folder",
        "    `$env:AGENT_MEMORY_HOME = '<folder containing cli.py>'",
        "    (or create a junction:  mklink /J `"$fallback`" '<project folder>')",
        "",
        "  fix B (fresh install from a git checkout): run install.ps1 in the project root",
        "  fix C (fresh install from the platform zip): run the bootstrap.ps1 shipped here",
        "    powershell -NoProfile -ExecutionPolicy Bypass -File `"$skill\scripts\bootstrap.ps1`"",
        "",
        "  More: see references/cli.md (install / troubleshooting).",
        ""
    ) -join [Environment]::NewLine
    [Console]::Error.WriteLine($msg)
    exit $script:AmExitNotInitialised
}

function Resolve-AmHome {
    if ($env:AGENT_MEMORY_HOME) {
        $p = Join-Path $env:AGENT_MEMORY_HOME 'cli.py'
        if (Test-Path $p) { return (Resolve-Path $env:AGENT_MEMORY_HOME).Path }
    }
    # platform package layout: engine is at the skill root, one level up from scripts\
    $parent = Join-Path $PSScriptRoot '..'
    if (Test-Path (Join-Path $parent 'cli.py')) { return (Resolve-Path $parent).Path }

    $d = $PSScriptRoot
    for ($i = 0; $i -lt 6; $i++) {
        if (-not $d) { break }
        if (Test-Path (Join-Path $d 'cli.py')) { return $d }
        $d = Split-Path $d -Parent
    }
    $fallback = Join-Path $env:USERPROFILE 'agent-memory'
    if (Test-Path (Join-Path $fallback 'cli.py')) { return (Resolve-Path $fallback).Path }

    Write-AmNotInitialised
}

function Resolve-AmPython($amHome) {
    $exe = Join-Path $amHome '.venv\Scripts\python.exe'
    if (Test-Path $exe) { return $exe }
    $exe = Join-Path $amHome '.venv\bin\python'
    if (Test-Path $exe) { return $exe }
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    [Console]::Error.WriteLine(@(
        "",
        "python not found: expected $amHome\.venv\Scripts\python.exe",
        "  fix: run install.ps1 (git checkout) or scripts\bootstrap.ps1 (platform zip) once;",
        "       it creates the venv and installs zstandard/pyyaml.",
        ""
    ) -join [Environment]::NewLine)
    exit $script:AmExitNotInitialised
}
