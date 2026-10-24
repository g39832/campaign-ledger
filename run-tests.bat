@echo off
REM Runs the automated test suite (uses a temporary database, never your real data)
cd /d "%~dp0"
".venv\Scripts\python.exe" -m pytest -q
pause
