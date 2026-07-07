# Blinkit Budget Scheduler — Windows Task Scheduler setup
# Run once from backend/ to register the auto-scheduler:
#   powershell -ExecutionPolicy Bypass -File ad_campaigns\setup_task_scheduler.ps1

$TaskName   = "BlinkitBudgetScheduler"
$ScriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendDir = Split-Path -Parent $ScriptDir
$PythonExe  = Join-Path $BackendDir ".venv\Scripts\python.exe"
$BatchFile  = Join-Path $ScriptDir "run_scheduler.bat"

Write-Host ""
Write-Host "=== Blinkit Budget Scheduler Setup ===" -ForegroundColor Cyan
Write-Host "  Backend dir : $BackendDir"
Write-Host "  Python      : $PythonExe"
Write-Host ""

if (-not (Test-Path $PythonExe)) {
    Write-Host "[ERROR] .venv Python not found at: $PythonExe" -ForegroundColor Red
    exit 1
}

# Step 1 — write a .bat file that sets the working dir and runs the scheduler
$BatContent = "@echo off`r`ncd /d `"$BackendDir`"`r`n`"$PythonExe`" -m ad_campaigns.scheduler"
Set-Content -Path $BatchFile -Value $BatContent -Encoding ASCII
Write-Host "  Batch file  : $BatchFile" -ForegroundColor DarkGray

# Step 2 — remove existing task if present
schtasks /delete /tn $TaskName /f 2>$null

# Step 3 — register the batch file to run every 30 minutes
schtasks /create /tn $TaskName /tr $BatchFile /sc MINUTE /mo 30 /f

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "[OK] Task '$TaskName' registered successfully." -ForegroundColor Green
    Write-Host ""
    Write-Host "What happens now:" -ForegroundColor Yellow
    Write-Host "  - Windows runs the scheduler every 30 minutes automatically"
    Write-Host "  - Works even when this terminal is closed"
    Write-Host "  - Survives PC restarts"
    Write-Host ""
    Write-Host "Useful commands:" -ForegroundColor Yellow
    Write-Host "  See task    :  schtasks /query /tn $TaskName"
    Write-Host "  Run now     :  schtasks /run /tn $TaskName"
    Write-Host "  Remove task :  schtasks /delete /tn $TaskName /f"
} else {
    Write-Host "[ERROR] Task registration failed." -ForegroundColor Red
}
Write-Host ""
