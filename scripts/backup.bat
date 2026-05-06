@echo off
REM Daily View 일일 백업 스크립트 (docs/05_setup.md 5.8).
REM 작업 스케줄러로 매일 새벽 3시에 실행 권장.
REM
REM 백업 위치는 환경변수 BACKUP_ROOT 로 변경 가능 (기본 D:\Backups\DailyView).
REM 14일 이상 된 백업은 자동 삭제.

setlocal EnableDelayedExpansion

REM ---- 설정 ----
if "%BACKUP_ROOT%"=="" set "BACKUP_ROOT=D:\Backups\DailyView"
set "DATA_ROOT=%~dp0..\data"
set "RETENTION_DAYS=14"

REM ---- 타임스탬프 (YYYY-MM-DD_HH-MM-SS) ----
for /f "tokens=2 delims==" %%I in ('wmic os get localdatetime /value ^| find "="') do set LDT=%%I
set "TS=%LDT:~0,4%-%LDT:~4,2%-%LDT:~6,2%_%LDT:~8,2%-%LDT:~10,2%-%LDT:~12,2%"

set "DEST=%BACKUP_ROOT%\%TS%"

echo [backup.bat] %TS% 백업 시작
echo   src : %DATA_ROOT%
echo   dest: %DEST%

if not exist "%DATA_ROOT%" (
    echo [backup.bat] 데이터 폴더가 없습니다: %DATA_ROOT%
    exit /b 1
)

if not exist "%BACKUP_ROOT%" mkdir "%BACKUP_ROOT%"

REM ---- robocopy: /MIR 미러링, .locks 폴더는 제외 ----
robocopy "%DATA_ROOT%" "%DEST%" /MIR /XD .locks /R:2 /W:3 /NFL /NDL /NP /LOG:"%DEST%.log"

REM robocopy 종료코드: <8 이면 성공
set "RC=%ERRORLEVEL%"
if %RC% GEQ 8 (
    echo [backup.bat] robocopy 실패 (exit %RC%) — 로그: %DEST%.log
    exit /b %RC%
)

echo [backup.bat] 백업 완료 (rc=%RC%)

REM ---- 14일 지난 백업 폴더 삭제 ----
echo [backup.bat] %RETENTION_DAYS% 일 지난 백업 정리...
forfiles /P "%BACKUP_ROOT%" /D -%RETENTION_DAYS% /C "cmd /c if @isdir==TRUE rd /s /q @path && echo   삭제: @path" 2>nul

REM 동시에 .log 파일도 함께 정리
forfiles /P "%BACKUP_ROOT%" /M *.log /D -%RETENTION_DAYS% /C "cmd /c del @path && echo   삭제: @path" 2>nul

echo [backup.bat] 완료.
exit /b 0
