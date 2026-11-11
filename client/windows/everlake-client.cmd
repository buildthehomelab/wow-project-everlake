@echo off
setlocal
if "%~1"=="" goto window
if /i "%~1"=="era-maps" goto maps
if /i "%~1"=="era-maps-status" goto maps
echo Usage: %~nx0 era-maps^|era-maps-status [path-to-everlake-era]
exit /b 2

:maps
set "era_dir=%~2"
if not defined era_dir set "era_dir=%EVERLAKE_ERA_DIR%"
if not defined era_dir if exist "%CD%\profiles\targets.json" set "era_dir=%CD%"
if not defined era_dir set "era_dir=%~dp0..\..\..\everlake-era"
if not exist "%era_dir%\profiles\targets.json" (
    echo Pass the everlake-era checkout path as the second argument.
    exit /b 2
)
set "status="
if /i "%~1"=="era-maps-status" set "status=--status"
where py.exe >nul 2>&1
if errorlevel 1 goto python
py -3 "%~dp0..\..\tools\era\maps\map_catalog.py" "%era_dir%" %status%
exit /b %errorlevel%

:python
python "%~dp0..\..\tools\era\maps\map_catalog.py" "%era_dir%" %status%
exit /b %errorlevel%

:window
powershell.exe -NoProfile -STA -File "%~dp0era-content.ps1"
exit /b %errorlevel%
