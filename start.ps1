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
try {
    Write-Host "FoodBridge: http://127.0.0.1:$Port/"
    Write-Host 'Expiry alerts refresh every 60 seconds, even with the browser closed. Press Ctrl+C to stop.'
    & $ProjectPython manage.py runserver "127.0.0.1:$Port" --noreload
} finally {
    if (-not $Watcher.HasExited) { Stop-Process -Id $Watcher.Id -ErrorAction SilentlyContinue }
}
