# Build the platform-publishable skill package (ASCII only).
#
# PLATFORM RULE (learned the hard way, 2026-11-04 upload rejected):
#   "directory nesting too deep - Skill package only supports two levels
#    (root / second-level dir / file); remove nested directories"
#   (original Chinese error text archived in docs/pack-platform-cleanroom.md)
#   i.e. files may sit at the zip root or ONE level below it, and nowhere deeper.
#   So the Python engine (cli.py + collectors\) MUST live at the zip root; it cannot
#   stay in scripts\engine\ (that is two levels).
#
# Layout produced:
#   agent-memory.zip
#   |-- SKILL.md                 <- at zip ROOT
#   |-- requirements.txt
#   |-- cli.py, paths.py, store.py, topics.py, topic_build.py,
#   |   premises.py, inject.py, timeline.py, init_cmd.py     <- engine, at ROOT
#   |-- collectors\             <- one level (root\collectors\base.py)
#   |-- references\, templates\ <- one level
#   `-- scripts\                <- the .ps1 wrappers, one level
#
# The package tree must stay a pure copy: no file is rewritten at pack time, so
# what is tested in a clean directory is exactly what gets uploaded.

$ErrorActionPreference = 'Stop'
$h = $PSScriptRoot
$stage = Join-Path $h 'dist\stage'
$zip = Join-Path $h 'dist\agent-memory.zip'

# ---- 1) stage: root files + one-level dirs ----
if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory -Force -Path $stage | Out-Null

$skillDir = Join-Path $h 'skill\agent-memory'
Copy-Item (Join-Path $skillDir 'SKILL.md') (Join-Path $stage 'SKILL.md') -Force
Copy-Item (Join-Path $skillDir 'references') (Join-Path $stage 'references') -Recurse -Force
Copy-Item (Join-Path $skillDir 'templates') (Join-Path $stage 'templates') -Recurse -Force
New-Item -ItemType Directory -Force -Path (Join-Path $stage 'scripts') | Out-Null
Copy-Item (Join-Path $skillDir 'scripts\*.ps1') (Join-Path $stage 'scripts') -Force

$engFiles = @('cli.py', 'paths.py', 'init_cmd.py', 'store.py', 'topics.py', 'topic_build.py',
              'premises.py', 'inject.py', 'timeline.py', 'peers.py')
foreach ($f in $engFiles) {
    $src = Join-Path $h $f
    if (-not (Test-Path $src)) { throw "engine file missing: $f" }
    Copy-Item $src (Join-Path $stage $f) -Force
}
Copy-Item (Join-Path $h 'collectors') (Join-Path $stage 'collectors') -Recurse -Force
Get-ChildItem $stage -Recurse -Directory -Filter '__pycache__' |
    ForEach-Object { Remove-Item $_.FullName -Recurse -Force }

# ---- 2) requirements.txt (only what the engine imports at run time) ----
$req = "zstandard>=0.22`npyyaml>=6.0`n"
[System.IO.File]::WriteAllText((Join-Path $stage 'requirements.txt'), $req)

if (-not (Test-Path (Join-Path $stage 'scripts\bootstrap.ps1'))) {
    throw "bootstrap.ps1 missing: expected skill\agent-memory\scripts\bootstrap.ps1"
}

# ---- 2a) private-term scan: never ship real client/project names again ----
# Why: the 2026-11-04 uploads (v1.4.0 / v1.5.0) carried real client project names and
# internal absolute paths in 14 of 28 files. The rule only exists if it is machine-checked.
# Term list lives in .private-terms.txt (gitignored: it must NOT ship, not even in the repo).
$py = Join-Path $h '.venv\Scripts\python.exe'
if (-not (Test-Path $py)) {
    Remove-Item $stage -Recurse -Force
    throw "venv python missing: $py (run install.ps1 first) - cannot verify private terms"
}
& $py (Join-Path $h 'tools\check_private_terms.py')
if ($LASTEXITCODE -ne 0) {
    Remove-Item $stage -Recurse -Force
    throw "PACK FAIL: private terms found in the package (see list above)"
}

# ---- 2b) version guard: the SAME version must not carry DIFFERENT content ----
# Lesson (2026-11-04): version 1.4.0 ended up covering two different packages
# (ebc8019 set the number, aa5ebbb then changed code). The platform shows only one
# 1.4.0, so rollback / diff / "which build do users have" all lose their evidence.
# Rule: if the content hash changes while SKILL.md version stays the same, refuse.
# NOTE: this file must stay ASCII-only (PowerShell 5.1 reads BOM-less .ps1 as GBK;
# Chinese inside string literals breaks parsing - learned the hard way twice).
function Get-StageHash([string]$dir) {
    $lines = Get-ChildItem $dir -Recurse -File | Sort-Object FullName | ForEach-Object {
        $rel = $_.FullName.Substring($dir.Length + 1) -replace '\\', '/'
        $h = (Get-FileHash $_.FullName -Algorithm SHA256).Hash
        "$rel $h"
    }
    $bytes = [System.Text.Encoding]::UTF8.GetBytes(($lines -join "`n"))
    $sha = [System.Security.Cryptography.SHA256]::Create().ComputeHash($bytes)
    return (([BitConverter]::ToString($sha)) -replace '-', '').ToLower()
}

$stampFile = Join-Path $h 'dist\.last-package.json'
$skillMd = Join-Path $h 'skill\agent-memory\SKILL.md'
$verMatch = Select-String -Path $skillMd -Pattern '^version:\s*"([^"]+)"' | Select-Object -First 1
$version = if ($verMatch) { $verMatch.Matches[0].Groups[1].Value } else { throw "SKILL.md missing version: `"x.y.z`"" }
$contentHash = Get-StageHash $stage
Write-Host ("version: {0} | content: {1}" -f $version, $contentHash.Substring(0, 12))
if (Test-Path $stampFile) {
    $last = Get-Content $stampFile -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($last.version -eq $version -and $last.content_sha256 -ne $contentHash) {
        Remove-Item $stage -Recurse -Force
        throw ("version unchanged but content changed ({0}): bump SKILL.md version before packing." -f $version)
    }
}

# ---- 3) zip ----
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path (Join-Path $stage '*') -DestinationPath $zip -Force

# ---- 4) verify ----
Add-Type -AssemblyName System.IO.Compression.FileSystem
$a = [System.IO.Compression.ZipFile]::OpenRead($zip)
Write-Host ""
Write-Host ("zip: {0}  ({1:N1} KB, {2} entries)" -f $zip, ((Get-Item $zip).Length/1KB), $a.Entries.Count)
Write-Host "top-level entries:"
$a.Entries | ForEach-Object { ($_.FullName -split '[\\/]')[0] } | Sort-Object -Unique |
    ForEach-Object { Write-Host "  $_" }

$hasSkillRoot = ($a.Entries.FullName -contains 'SKILL.md')
Write-Host "SKILL.md at root: $hasSkillRoot"
$hasBootstrap = (@($a.Entries | Where-Object { $_.FullName -match '(^|[\\/])bootstrap\.ps1$' }).Count -gt 0)
Write-Host "bootstrap.ps1 present: $hasBootstrap"

# depth: file entries may be "name.ext" (root) or "dir/name.ext" (one level) only
$tooDeep = @($a.Entries | Where-Object {
        -not $_.FullName.EndsWith('/') -and
        -not $_.FullName.EndsWith('\') -and
        (($_.FullName -split '[\\/]').Count -gt 2)
    })
Write-Host ("entries deeper than one level: {0}" -f $tooDeep.Count)
foreach ($e in $tooDeep) { Write-Host ("  TOO DEEP: {0}" -f $e.FullName) }

$bad = @($a.Entries | Where-Object { $_.FullName -match '(\.venv|/index/|\\index\\|\.git/|sessions\.db)' })
Write-Host ("forbidden entries (venv/index/git/db): {0}" -f $bad.Count)
$a.Dispose()

Remove-Item $stage -Recurse -Force
if (-not $hasSkillRoot) { throw "SKILL.md is not at zip root" }
if (-not $hasBootstrap) { throw "bootstrap.ps1 missing from the package" }
if ($tooDeep.Count -gt 0) { throw "platform rejects nested directories: keep everything at root or one level below" }
if ($bad.Count -gt 0) { throw "forbidden files leaked into the package" }

# Record (version + content hash + zip hash): a same-version content change is
# rejected by the guard above on the next run.
$stamp = [ordered]@{
    version      = $version
    content_sha256 = $contentHash
    zip_sha256   = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
    built_at     = (Get-Date).ToString('yyyy-MM-ddTHH:mm:ssK')
}
[System.IO.File]::WriteAllText($stampFile, ($stamp | ConvertTo-Json), (New-Object System.Text.UTF8Encoding($false)))
Write-Host "stamp -> dist\.last-package.json"
Write-Host "PACK OK"
