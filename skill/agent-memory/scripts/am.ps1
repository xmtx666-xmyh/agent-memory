# agent-memory CLI wrapper (ASCII only on purpose)
#
# WHY ASCII: Windows PowerShell 5.1 decodes .ps1 as ANSI(GBK) unless the file has
# a UTF-8 BOM. Chinese text in a BOM-less .ps1 turns into mojibake and breaks parsing.
# Keep this file pure ASCII; Chinese docs live in SKILL.md / references/*.md.
#
# Usage:
#   .\scripts\am.ps1 search "PageIndex" --trigram
#   .\scripts\am.ps1 topics --top 20
#   .\scripts\am.ps1 premises "<entity>" --top 5
#   .\scripts\am.ps1 inject "<entity>" --write "<project>\.agent-memory\context.md"
#
# Home resolution lives in _resolve.ps1 (env -> walk up for cli.py -> %USERPROFILE%\agent-memory).

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '_resolve.ps1')

$amHome = Resolve-AmHome
$py = Resolve-AmPython $amHome
$cli = Join-Path $amHome 'cli.py'

& $py $cli @args
exit $LASTEXITCODE
