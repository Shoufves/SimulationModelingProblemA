$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
$archiveRoot = Join-Path $repoRoot 'legacy'
$keepNames = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'keep.json') -Raw -Encoding utf8 | ConvertFrom-Json
$keepSet = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
foreach ($name in $keepNames) { [void]$keepSet.Add($name) }

function Move-ArchiveEntry([System.IO.FileSystemInfo]$entry, [string]$relative) {
    $source = [System.IO.Path]::GetFullPath($entry.FullName)
    $destination = [System.IO.Path]::GetFullPath((Join-Path $archiveRoot $relative))
    if (-not $source.StartsWith($repoRoot + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Source escapes workspace: $source"
    }
    if (-not $destination.StartsWith($archiveRoot + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Destination escapes archive: $destination"
    }
    if (Test-Path -LiteralPath $destination) { throw "Archive already exists: $destination" }
    [void][System.IO.Directory]::CreateDirectory([System.IO.Path]::GetDirectoryName($destination))
    Move-Item -LiteralPath $source -Destination $destination
}

function Visit-Entry([System.IO.FileSystemInfo]$entry, [string]$relative) {
    if ($keepSet.Contains($relative)) { return }
    $prefix = $relative + '/'
    $hasKeptChildren = $false
    foreach ($name in $keepNames) {
        if ($name.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
            $hasKeptChildren = $true
            break
        }
    }
    if (-not $hasKeptChildren) {
        Move-ArchiveEntry $entry $relative
        return
    }
    foreach ($child in Get-ChildItem -LiteralPath $entry.FullName -Force) {
        Visit-Entry $child ($relative + '/' + $child.Name)
    }
}

foreach ($entry in Get-ChildItem -LiteralPath $repoRoot -Force) {
    if ($entry.Name -in @('.git', 'legacy')) { continue }
    Visit-Entry $entry $entry.Name
}
Write-Output 'Archive moves completed. No original file was deleted.'
