@echo off
REM Daily View daily backup script (docs/05_setup.md 5.8).
REM Recommended: run daily at 03:00 via Task Scheduler.
REM Backup root can be changed via BACKUP_ROOT env (default D:\Backups\DailyView).
REM Backups older than RETENTION_DAYS are auto-deleted.

setlocal EnableDelayedExpansion

REM ---- config ----
if "%BACKUP_ROOT%"=="" set "BACKUP_ROOT=D:\Backups\DailyView"
set "DATA_ROOT=%~dp0..\data"
set "RETENTION_DAYS=14"

REM ---- timestamp (YYYY-MM-DD_HH-MM-SS) via PowerShell (wmic is deprecated/removed) ----
for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd_HH-mm-ss"') do set "TS=%%I"

set "DEST=%BACKUP_ROOT%\%TS%"

echo [backup.bat] %TS% backup start
echo   src : %DATA_ROOT%
echo   dest: %DEST%

if not exist "%DATA_ROOT%" (
    echo [backup.bat] data folder not found: %DATA_ROOT%
    exit /b 1
)

if not exist "%BACKUP_ROOT%" mkdir "%BACKUP_ROOT%"

REM ---- robocopy: /MIR mirror, exclude .locks folder ----
REM Log via stdout redirect (/LOG: can fail to open before dest exists).
robocopy "%DATA_ROOT%" "%DEST%" /MIR /XD .locks /R:2 /W:3 /NFL /NDL /NP > "%BACKUP_ROOT%\%TS%.log" 2>&1

REM robocopy exit code: less than 8 means success
set "RC=%ERRORLEVEL%"
if %RC% GEQ 8 (
    echo [backup.bat] robocopy FAILED rc=%RC% - see log: %DEST%.log
    exit /b %RC%
)

echo [backup.bat] backup done (rc=%RC%)

REM ---- delete backup folders older than RETENTION_DAYS ----
echo [backup.bat] cleaning backups older than %RETENTION_DAYS% days...
forfiles /P "%BACKUP_ROOT%" /D -%RETENTION_DAYS% /C "cmd /c if @isdir==TRUE rd /s /q @path && echo   deleted: @path" 2>nul

REM also clean matching .log files
forfiles /P "%BACKUP_ROOT%" /M *.log /D -%RETENTION_DAYS% /C "cmd /c del @path && echo   deleted: @path" 2>nul

echo [backup.bat] complete.
exit /b 0
