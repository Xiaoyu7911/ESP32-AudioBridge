@echo off
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"
if not exist ".venv\Scripts\python.exe" (
  echo Project Python environment missing. See docs\BUILD_AND_RECOVERY.md
  exit /b 2
)
".venv\Scripts\python.exe" -m host.sender %*
exit /b %errorlevel%
