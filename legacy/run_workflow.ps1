param(
    [ValidateSet('W0','W1','W2','W3','W4','W5','W6','W7','W8','W9')]
    [string]$Stage,
    [switch]$CheckFormalInputs,
    [string]$PythonPath
)
$ErrorActionPreference = 'Stop'
$bundledPython = Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
if ($PythonPath) {
    $workflowPython = (Resolve-Path -LiteralPath $PythonPath).Path
} elseif (Test-Path -LiteralPath $bundledPython) {
    $workflowPython = $bundledPython
} else {
    $workflowPython = (Get-Command python -ErrorAction Stop).Source
}
$workflowArgs = @((Join-Path $PSScriptRoot 'scripts/workflow_status.py'))
if ($Stage) { $workflowArgs += @('--stage', $Stage) }
if ($CheckFormalInputs) { $workflowArgs += '--check-formal-inputs' }
& $workflowPython -B -X utf8 @workflowArgs
$workflowExitCode = $LASTEXITCODE
exit $workflowExitCode
