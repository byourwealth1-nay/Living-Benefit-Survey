@echo off
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel% EQU 0 (set PY=py) else (set PY=python)
if not exist data\living_benefits.sqlite3 (
  echo First-time setup: create an advisor account.
  %PY% server.py setup
  if errorlevel 1 goto done
)
%PY% server.py
:done
pause
