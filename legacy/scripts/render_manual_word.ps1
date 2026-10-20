param(
    [Parameter(Mandatory=$true)][string]$InputPath,
    [Parameter(Mandatory=$true)][string]$OutputPath
)
# Use a separate hidden Word instance and close only the document opened here.
$ErrorActionPreference = 'Stop'
$manualWord = $null
$manualDocument = $null
$manualFalse = $false
$manualTrue = $true
$manualSaveChanges = 0
try {
    $manualWord = New-Object -ComObject Word.Application
    $manualWord.Visible = $false
    $manualWord.DisplayAlerts = 0
    $manualWord.AutomationSecurity = 3
    $manualDocument = $manualWord.Documents.Open([ref]$InputPath, [ref]$manualFalse,
        [ref]$manualTrue, [ref]$manualFalse)
    $manualDocument.ExportAsFixedFormat($OutputPath, 17)
} finally {
    if ($null -ne $manualDocument) {
        $manualDocument.Close([ref]$manualSaveChanges)
        [void][Runtime.InteropServices.Marshal]::ReleaseComObject($manualDocument)
    }
    if ($null -ne $manualWord) {
        $manualWord.Quit([ref]$manualSaveChanges)
        [void][Runtime.InteropServices.Marshal]::ReleaseComObject($manualWord)
    }
}
