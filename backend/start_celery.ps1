[CmdletBinding()]
param(
    [string]$EnabledMarkets = $env:ENABLED_MARKETS,
    [string]$Pool = $(if ($env:CELERY_POOL) { $env:CELERY_POOL } else { "solo" })
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$Python = Join-Path $PSScriptRoot "venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    throw "Backend virtual environment not found at $Python. Complete the backend setup first."
}

$SupportedCsv = & $Python -c "from app.tasks.market_queues import SUPPORTED_MARKETS; print(','.join(SUPPORTED_MARKETS))"
if ($LASTEXITCODE -ne 0) {
    throw "Unable to read the supported markets from the backend market catalog."
}
$SupportedMarkets = @($SupportedCsv.Split(",") | ForEach-Object { $_.Trim().ToUpperInvariant() })

if ([string]::IsNullOrWhiteSpace($EnabledMarkets)) {
    $EnabledMarkets = & $Python -c "from app.config import settings; print(settings.enabled_markets)"
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to read ENABLED_MARKETS from backend\.env."
    }
}

$Markets = @(
    $EnabledMarkets.Split(",") |
        ForEach-Object { $_.Trim().ToUpperInvariant() } |
        Where-Object { $_ } |
        Select-Object -Unique
)

if ($Markets.Count -eq 0) {
    throw "ENABLED_MARKETS must contain at least one market code."
}

foreach ($Market in $Markets) {
    if ($Market -notin $SupportedMarkets) {
        throw "Unsupported market '$Market'. Supported markets: $SupportedCsv"
    }
}

$MarketCsv = $Markets -join ","
$DataFetchQueues = & $Python -c "import sys; from app.tasks.market_queues import all_data_fetch_queues; print(','.join(all_data_fetch_queues(sys.argv[1].split(','))))" $MarketCsv
if ($LASTEXITCODE -ne 0) {
    throw "Unable to derive data-fetch queues for $MarketCsv."
}

function Start-CeleryWorker {
    param(
        [Parameter(Mandatory = $true)][string]$Queues,
        [Parameter(Mandatory = $true)][string]$NodeName,
        [switch]$SingleConcurrency
    )

    $Arguments = @(
        "-m", "celery",
        "-A", "app.celery_app",
        "worker",
        "--loglevel=info",
        "--pool=$Pool",
        "-Q", $Queues,
        "-n", $NodeName
    )
    if ($SingleConcurrency) {
        $Arguments += "--concurrency=1"
    }

    Write-Host "Starting $NodeName for $Queues"
    Start-Process -FilePath $Python -ArgumentList $Arguments -NoNewWindow -PassThru
}

$Workers = @()
$Workers += Start-CeleryWorker -Queues "celery" -NodeName "general@%h"
$Workers += Start-CeleryWorker -Queues $DataFetchQueues -NodeName "datafetch-global@%h" -SingleConcurrency
$Workers += Start-CeleryWorker -Queues "user_scans_shared" -NodeName "userscans-shared@%h"

foreach ($Market in $Markets) {
    $marketLower = $Market.ToLowerInvariant()
    $Workers += Start-CeleryWorker -Queues "market_jobs_$marketLower" -NodeName "marketjobs-$marketLower@%h"
    $Workers += Start-CeleryWorker -Queues "user_scans_$marketLower" -NodeName "userscans-$marketLower@%h"
}

Write-Host "Celery workers are running for: $MarketCsv"
Write-Host "Press Ctrl+C to stop all workers started by this script."

try {
    while ($true) {
        $ExitedWorker = $Workers | Where-Object { $_.HasExited } | Select-Object -First 1
        if ($ExitedWorker) {
            throw "Celery worker process $($ExitedWorker.Id) exited with code $($ExitedWorker.ExitCode)."
        }
        Start-Sleep -Seconds 2
    }
}
finally {
    foreach ($Worker in $Workers) {
        if (-not $Worker.HasExited) {
            Stop-Process -Id $Worker.Id
        }
    }
}
