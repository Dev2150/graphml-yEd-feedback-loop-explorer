@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
    echo Error: Python is not installed or not in PATH.
    exit /b 1
)

python -c "import openpyxl" >nul 2>&1
if errorlevel 1 (
    echo Installing openpyxl...
    python -m pip install openpyxl
    if errorlevel 1 (
        echo Error: Failed to install openpyxl.
        exit /b 1
    )
)

python -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
    echo Installing PyInstaller...
    python -m pip install pyinstaller
    if errorlevel 1 (
        echo Error: Failed to install PyInstaller.
        exit /b 1
    )
)

echo Building GraphML executables...
python -m PyInstaller --clean --noconfirm main.spec
if errorlevel 1 (
    echo.
    echo Build failed!
    exit /b 1
)

endlocal