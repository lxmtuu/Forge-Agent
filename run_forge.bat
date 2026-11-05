@echo off
setlocal
rem ============================================================
rem  forge-agent launcher (Windows) - double-click this file.
rem  Pure ASCII per research: cmd parses the file with the
rem  console codepage BEFORE any codepage change inside, so all
rem  localized text lives in scripts\launch.py (UTF-8 safe).
rem ============================================================
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY (
  echo [forge-agent] Python not found.
  echo Install Python 3.11+ from https://www.python.org/downloads/
  echo and CHECK "Add python.exe to PATH" during setup, then run this file again.
  pause
  exit /b 1
)
%PY% "%~dp0scripts\launch.py" %*
if errorlevel 1 pause
endlocal
