@echo off
REM Daily View 시작 스크립트 (docs/05_setup.md 5.6)
REM 더블클릭 또는 NSSM 서비스 명령으로 실행.

cd /d "%~dp0\.."

if not exist ".venv\Scripts\activate.bat" (
    echo [run.bat] .venv 가 없습니다. 먼저 다음을 실행하세요:
    echo     py -3.12 -m venv .venv
    echo     .venv\Scripts\activate
    echo     pip install -r requirements.txt
    pause
    exit /b 1
)

call .venv\Scripts\activate.bat

streamlit run app.py ^
    --server.address 0.0.0.0 ^
    --server.port 8501 ^
    --server.headless true ^
    --server.maxUploadSize 50

echo.
echo [run.bat] Streamlit 종료 (exit code %ERRORLEVEL%).
pause
exit /b %ERRORLEVEL%
