param([string]$PythonPath)
$ErrorActionPreference = 'Stop'
$prototypeBundledPython = Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
if ($PythonPath) {
    $prototypePython = (Resolve-Path -LiteralPath $PythonPath).Path
} elseif (Test-Path -LiteralPath $prototypeBundledPython) {
    $prototypePython = $prototypeBundledPython
} else {
    $prototypePython = (Get-Command python -ErrorAction Stop).Source
}
& $prototypePython -B -X utf8 (Join-Path $PSScriptRoot 'scripts/run_agent_prototype.py')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $prototypePython -B -X utf8 (Join-Path $PSScriptRoot 'scripts/run_operation_windows.py')
exit $LASTEXITCODE
