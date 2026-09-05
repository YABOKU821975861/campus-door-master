@echo off
setlocal

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Virtual environment not found.
    echo Please run init.bat first.
    pause
    exit /b 1
)

call ".venv\Scripts\activate.bat"

echo Starting Campus Door Master...
python main.py

echo.
echo Service stopped.
pause
endlocal
