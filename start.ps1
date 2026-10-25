param([int]$Port = 8000)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$ProjectPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $ProjectPython)) {
    throw 'Create the .venv and install requirements first. See README.md.'
}
& $ProjectPython manage.py migrate
if ($LASTEXITCODE -ne 0) { throw 'Database migration failed.' }
$LogFolder = Join-Path $PSScriptRoot 'artifacts'
New-Item -ItemType Directory -Force -Path $LogFolder | Out-Null
$Watcher = Start-Process -FilePath $ProjectPython -ArgumentList '-u manage.py check_expiry --watch --interval 60' -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $LogFolder 'expiry-watcher.log') -RedirectStandardError (Join-Path $LogFolder 'expiry-watcher-errors.log')
$PredictionWatcher = Start-Process -FilePath $ProjectPython -ArgumentList '-u manage.py run_predictions --watch --interval 86400' -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $LogFolder 'prediction-watcher.log') -RedirectStandardError (Join-Path $LogFolder 'prediction-watcher-errors.log')
try {
    Write-Host "FoodBridge: http://127.0.0.1:$Port/"
    Write-Host 'Expiry alerts refresh every 60 seconds; predictions refresh daily. Press Ctrl+C to stop.'
    & $ProjectPython manage.py runserver "127.0.0.1:$Port" --noreload
} finally {
    if (-not $Watcher.HasExited) { Stop-Process -Id $Watcher.Id -ErrorAction SilentlyContinue }
    if (-not $PredictionWatcher.HasExited) { Stop-Process -Id $PredictionWatcher.Id -ErrorAction SilentlyContinue }
}
