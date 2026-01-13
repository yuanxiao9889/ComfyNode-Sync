@echo off
echo Starting ComfyNode Sync...

echo 1. Checking Python...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Python not found! Please install Python.
    pause
    exit /b
)

echo 2. Setting up environment...
set "NEED_VENV=1"
if exist "venv\Scripts\python.exe" (
    venv\Scripts\python.exe --version >nul 2>&1
    if not errorlevel 1 set "NEED_VENV=0"
)

if "%NEED_VENV%"=="1" (
    if exist "venv" (
        echo Cleaning up invalid environment...
        rmdir /s /q "venv"
    )
    echo Creating venv...
    python -m venv venv
)

echo 3. Installing dependencies...
venv\Scripts\python.exe -m pip install --upgrade pip >nul 2>&1
venv\Scripts\python.exe -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple >nul 2>&1

echo 4. Starting GUI...
start "" /B venv\Scripts\pythonw.exe gui.py
exit

