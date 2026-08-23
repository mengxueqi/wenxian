param(
    [string] $TaskName = "Literature Tracker Daily Update",
    [string] $DailyAt = "13:00"
)

$ErrorActionPreference = "Stop"

$ProjectRoot = $PSScriptRoot
$UpdateScript = Join-Path $ProjectRoot "run_literature_tracker_update.ps1"
$HiddenLauncher = Join-Path $ProjectRoot "run_literature_tracker_update_hidden.vbs"
if (-not (Test-Path $UpdateScript)) {
    throw "Update script not found: $UpdateScript"
}
if (-not (Test-Path $HiddenLauncher)) {
    throw "Hidden launcher not found: $HiddenLauncher"
}

$runAt = [DateTime]::ParseExact(
    $DailyAt,
    "HH:mm",
    [Globalization.CultureInfo]::InvariantCulture
)
$arguments = "//B //Nologo `"$HiddenLauncher`""
$action = New-ScheduledTaskAction -Execute "wscript.exe" -Argument $arguments
$trigger = New-ScheduledTaskTrigger -Daily -At $runAt
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Run the Literature Tracker crawl-to-report pipeline silently." `
    -Force | Out-Null

Write-Output "Installed scheduled task '$TaskName' at $DailyAt."
