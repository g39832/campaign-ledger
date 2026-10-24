@echo off
REM Campaign Ledger - double-click to start
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo First run: setting up Python environment...
  python -m venv .venv
  if errorlevel 1 (
    echo Could not create the environment. Is Python 3.10+ installed and on PATH?
    pause
    exit /b 1
  )
)
REM Install packages on first run, and again whenever requirements.txt changes.
fc /b requirements.txt ".venv\requirements.installed" >nul 2>&1
if errorlevel 1 (
  echo Installing required packages...
  ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt
  if errorlevel 1 (
    echo Package install failed. Check your internet connection and try again.
    pause
    exit /b 1
  )
  copy /y requirements.txt ".venv\requirements.installed" >nul
)
".venv\Scripts\python.exe" run.py %*
if errorlevel 1 pause
