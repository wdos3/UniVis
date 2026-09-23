param(
    [switch]$Install
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonPath = Join-Path $ProjectRoot "backend\.venv\Scripts\python.exe"

if ($Install -or -not (Test-Path -LiteralPath $PythonPath)) {
    $PythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if (-not $PythonCommand -or $PythonCommand.Source -like "*WindowsApps*") {
        $PythonCommand = Get-Command "C:\Users\$env:USERNAME\anaconda3\python.exe" -ErrorAction SilentlyContinue
    }
    if (-not $PythonCommand) { throw "Python 3.11+ was not found. Install Python, then run this script again." }
    & $PythonCommand.Source -m venv (Join-Path $ProjectRoot "backend\.venv")
    & $PythonPath -m pip install -r (Join-Path $ProjectRoot "backend\requirements.txt")
    Push-Location (Join-Path $ProjectRoot "frontend")
    try { npm install } finally { Pop-Location }
}

$env:CORS_ORIGINS = "http://localhost:5174,http://127.0.0.1:5174"
$Backend = Start-Process -FilePath $PythonPath -ArgumentList "-m", "uvicorn", "app.main:app", "--reload", "--port", "8001" -WorkingDirectory (Join-Path $ProjectRoot "backend") -WindowStyle Hidden -PassThru
$Frontend = Start-Process -FilePath "npm.cmd" -ArgumentList "run", "dev", "--", "--port", "5174" -WorkingDirectory (Join-Path $ProjectRoot "frontend") -WindowStyle Hidden -PassThru

Write-Host "VisNotice - Version 2 is starting at http://localhost:5174"
Write-Host "Backend API documentation: http://localhost:8001/docs"
Write-Host "Press Ctrl+C to stop both processes."
try {
    Wait-Process -Id $Backend.Id, $Frontend.Id
} finally {
    Stop-Process -Id $Backend.Id, $Frontend.Id -ErrorAction SilentlyContinue
}
