@echo off
REM Daily View start script (docs/05_setup.md 5.6)
REM Run by double-click or via NSSM service command.

cd /d "%~dp0\.."

if not exist ".venv\Scripts\activate.bat" (
    echo [run.bat] .venv not found. Run these first:
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
echo [run.bat] Streamlit stopped (exit code %ERRORLEVEL%).
pause
exit /b %ERRORLEVEL%
