@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0launcher.ps1"
if errorlevel 1 (
 echo.
 echo Startup failed. See error above and launcher.log.
 pause
)
endlocal
