@echo off
REM run-manual.bat - Run devbox-connect manually (not as a service)
REM
REM Usage:
REM   run-manual.bat                     - Uses tunnels.yaml in current directory
REM   run-manual.bat C:\path\to\config   - Uses specified config file

setlocal

set CONFIG=%1
if "%CONFIG%"=="" set CONFIG=tunnels.yaml

echo Starting devbox-connect with config: %CONFIG%
echo Press Ctrl+C to stop
echo.

devbox-connect -c "%CONFIG%" start

pause
