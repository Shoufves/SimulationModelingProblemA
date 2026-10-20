param([string]$PythonPath)
$ErrorActionPreference = 'Stop'
$attachmentPython = if ($PythonPath) { (Resolve-Path -LiteralPath $PythonPath).Path } else { Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' }
& $attachmentPython -B -X utf8 (Join-Path $PSScriptRoot 'scripts/build_attachments.py')
exit $LASTEXITCODE
