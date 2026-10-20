param(
    [string]$PythonPath,
    [ValidateRange(1024, 65535)][int]$Port = 8501
)
$ErrorActionPreference = 'Stop'
$workbenchEnvironment = Join-Path $PSScriptRoot '.venv-workbench/Scripts/python.exe'
$workbenchBundledPython = Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
if ($PythonPath) {
    $workbenchPython = (Resolve-Path -LiteralPath $PythonPath).Path
} elseif (Test-Path -LiteralPath $workbenchEnvironment) {
    $workbenchPython = $workbenchEnvironment
} elseif (Test-Path -LiteralPath $workbenchBundledPython) {
    $workbenchPython = $workbenchBundledPython
} else {
    $workbenchPython = (Get-Command python -ErrorAction Stop).Source
}
& $workbenchPython -B -X utf8 -c 'import streamlit, pandas'
if ($LASTEXITCODE -ne 0) {
    throw 'Missing UI dependencies. Install requirements-workbench.txt in a project Python environment.'
}
Push-Location -LiteralPath $PSScriptRoot
try {
    & $workbenchPython -B -X utf8 -m streamlit run (Join-Path $PSScriptRoot 'apps/workbench.py') --server.address 127.0.0.1 --server.port $Port --server.headless true --browser.gatherUsageStats false --server.fileWatcherType none
    $workbenchExitCode = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $workbenchExitCode
