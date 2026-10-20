param([switch]$NoPlots, [string]$PythonPath)
$ErrorActionPreference = 'Stop'
$bundledPython = Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
if ($PythonPath) {
    $studyPython = (Resolve-Path -LiteralPath $PythonPath).Path
} elseif (Test-Path -LiteralPath $bundledPython) {
    $studyPython = $bundledPython
} else {
    $studyPython = (Get-Command python -ErrorAction Stop).Source
}
$scriptPath = Join-Path $PSScriptRoot 'scripts/build_foundation.py'
if ($NoPlots) {
    & $studyPython -B -X utf8 $scriptPath --no-plots
} else {
    & $studyPython -B -X utf8 $scriptPath
}
if ($LASTEXITCODE -ne 0) {
    throw "Analysis failed with exit code $LASTEXITCODE"
}
