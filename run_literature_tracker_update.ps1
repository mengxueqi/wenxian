param(
    [string] $Source = "",
    [int] $Limit = 0
)

$ErrorActionPreference = "Stop"

$ProjectRoot = $PSScriptRoot
$DataDir = Join-Path $ProjectRoot "data"
$RunLog = Join-Path $DataDir "scheduled_update.log"

function Resolve-ProjectPython {
    $venvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    if (Test-Path $venvPython) {
        return $venvPython
    }

    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCommand) {
        return $pythonCommand.Source
    }

    throw "Python was not found. Create .venv or activate the literature-tracker environment."
}

New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
Set-Location $ProjectRoot
$Python = Resolve-ProjectPython
$Arguments = @("-m", "literature_tracker.cli", "run-all")
if ($Source) {
    $Arguments += @("--source", $Source)
}
if ($Limit -gt 0) {
    $Arguments += @("--limit", "$Limit")
}

$startedAt = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Add-Content -Path $RunLog -Value "[$startedAt] update started" -Encoding UTF8
& $Python @Arguments 2>&1 | Out-File -FilePath $RunLog -Append -Encoding UTF8
$exitCode = $LASTEXITCODE
$completedAt = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Add-Content -Path $RunLog -Value "[$completedAt] update finished with exit code $exitCode" -Encoding UTF8
exit $exitCode
