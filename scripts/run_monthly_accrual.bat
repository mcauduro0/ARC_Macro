@echo off
REM Phase 7.3 — Windows wrapper for the monthly accrual cycle.
REM Runs scripts/monthly_accrual.py from the repo root and appends stdout+stderr to logs/monthly_accrual.log.
REM Wired into Task Scheduler (see docs/PHASE7_3_AUTONOMOUS_ACCRUAL_2026-06.md):
REM   schtasks /create /tn "ARC monthly accrual" /tr "<repo>\scripts\run_monthly_accrual.bat" /sc monthly /d 2 /st 06:00

setlocal

REM repo root = parent of this script's directory.
set "SCRIPT_DIR=%~dp0"
pushd "%SCRIPT_DIR%.."
set "REPO_ROOT=%CD%"

if not exist "%REPO_ROOT%\logs" mkdir "%REPO_ROOT%\logs"

echo ===== ARC monthly accrual run %DATE% %TIME% ===== >> "%REPO_ROOT%\logs\monthly_accrual.log"
python "%REPO_ROOT%\scripts\monthly_accrual.py" %* >> "%REPO_ROOT%\logs\monthly_accrual.log" 2>&1
set "RC=%ERRORLEVEL%"
echo ===== exit code %RC% ===== >> "%REPO_ROOT%\logs\monthly_accrual.log"

popd
endlocal & exit /b %RC%
