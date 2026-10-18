@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    python -m venv .venv
    if errorlevel 1 goto failed
)
".venv\Scripts\python.exe" -c "from importlib.metadata import version; assert version('panda3d') == '1.10.16'; assert version('panda3d-simplepbr') == '0.13.1'" >nul 2>&1
if errorlevel 1 (
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 goto failed
)
".venv\Scripts\python.exe" run.py %*
if errorlevel 1 goto failed
exit /b 0
:failed
echo.
echo YTGears could not start. See the error above. Python 3.11+ is required.
pause
exit /b 1
