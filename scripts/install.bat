@echo off
cd /d "%~dp0.."

echo ==========================================
echo  Starting Blog Automation Environment Setup
echo ==========================================

:: 1. Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo Python is not installed. Please install Python 3.11 or higher.
    pause
    exit /b
)

:: 2. Create Virtual Environment
if not exist .venv (
    echo Creating virtual environment...
    python -m venv .venv
) else (
    echo Virtual environment already exists. Reusing it.
)

:: 3. Install Requirements
echo Installing required packages...
.venv\Scripts\python.exe -m pip install --upgrade pip
if exist requirements.txt (
    .venv\Scripts\python.exe -m pip install -r requirements.txt
) else (
    echo requirements.txt not found!
)


pause
