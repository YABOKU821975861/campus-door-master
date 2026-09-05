@echo off
setlocal

cd /d "%~dp0"

echo [1/4] Checking Python...
where python >nul 2>nul
if errorlevel 1 (
    echo Python was not found. Please install Python 3.10+ and add it to PATH.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo [2/4] Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo Failed to create virtual environment.
        pause
        exit /b 1
    )
) else (
    echo [2/4] Virtual environment already exists.
)

call ".venv\Scripts\activate.bat"

echo [3/4] Upgrading pip...
python -m pip install --upgrade pip
if errorlevel 1 (
    echo Failed to upgrade pip.
    pause
    exit /b 1
)

echo [4/4] Installing project dependencies...
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo Failed to install dependencies.
    pause
    exit /b 1
)

echo.
echo Initialization completed successfully.
echo You can now run start.bat or execute: python main.py
pause
endlocal
