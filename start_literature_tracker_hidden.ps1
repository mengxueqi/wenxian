$ErrorActionPreference = "Stop"

$ProjectRoot = $PSScriptRoot
$Port = 18517
$Url = "http://127.0.0.1:$Port"

$DataDir = Join-Path $ProjectRoot "data"
$StartupLog = Join-Path $DataDir "startup.log"

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

function Write-StartupLog {
    param([string] $Message)

    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path $StartupLog -Value "[$timestamp] $Message" -Encoding UTF8
}

function Test-PortOpen {
    param([int] $LocalPort)

    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $connect = $client.BeginConnect("127.0.0.1", $LocalPort, $null, $null)
        $success = $connect.AsyncWaitHandle.WaitOne(500, $false)
        if ($success) {
            $client.EndConnect($connect)
        }
        return $success
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

try {
    Set-Location $ProjectRoot
    $Python = Resolve-ProjectPython

    New-Item -ItemType Directory -Force -Path $DataDir | Out-Null

    $OutLog = Join-Path $DataDir "streamlit.out.log"
    $ErrLog = Join-Path $DataDir "streamlit.err.log"
    $UiApp = Join-Path $ProjectRoot "ui_app.py"

    $env:PYTHONPATH = $ProjectRoot
    $env:STREAMLIT_BROWSER_GATHER_USAGE_STATS = "false"
    $env:STREAMLIT_GLOBAL_DEVELOPMENT_MODE = "false"

    if (-not (Test-PortOpen -LocalPort $Port)) {
        $Arguments = @(
            "-m",
            "streamlit",
            "run",
            $UiApp,
            "--server.headless",
            "true",
            "--server.address",
            "127.0.0.1",
            "--server.port",
            "$Port"
        )

        Write-StartupLog "Starting Literature Tracker on $Url"
        $process = Start-Process `
            -FilePath $Python `
            -ArgumentList $Arguments `
            -WorkingDirectory $ProjectRoot `
            -WindowStyle Hidden `
            -RedirectStandardOutput $OutLog `
            -RedirectStandardError $ErrLog `
            -PassThru
        Write-StartupLog "Started process $($process.Id)"
    } else {
        Write-StartupLog "Port $Port is already open"
    }

    $deadline = (Get-Date).AddSeconds(20)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 2
            if ($response.StatusCode -eq 200) {
                Write-StartupLog "Application responded with HTTP 200"
                break
            }
        } catch {
            Start-Sleep -Milliseconds 500
        }
    }

    try {
        Start-Process $Url
    } catch {
        Write-StartupLog "Could not open browser automatically: $($_.Exception.Message)"
    }
} catch {
    New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
    Write-StartupLog "Startup failed: $($_.Exception.Message)"
}
