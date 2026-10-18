param([string]$PythonPath)
$ErrorActionPreference = 'Stop'
$verifiedBundledPython = Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
if ($PythonPath) {
    $verifiedPython = (Resolve-Path -LiteralPath $PythonPath).Path
} elseif (Test-Path -LiteralPath $verifiedBundledPython) {
    $verifiedPython = $verifiedBundledPython
} else {
    $verifiedPython = (Get-Command python -ErrorAction Stop).Source
}
# Check evidence before regenerating the scoped assessments.
& $verifiedPython -B -X utf8 (Join-Path $PSScriptRoot 'scripts/workflow_status.py') --check-formal-inputs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
foreach ($verifiedScript in @('build_verified_assessment.py', 'build_energy_assessment.py', 'build_gas_assessment.py', 'build_four_dimension_assessment.py', 'build_electricity_inputs.py', 'run_demand_hindcast.py', 'run_asset_lifecycle_case.py', 'build_data_catalog.py', 'build_history_readiness.py')) {
    & $verifiedPython -B -X utf8 (Join-Path $PSScriptRoot "scripts/$verifiedScript")
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
exit 0
