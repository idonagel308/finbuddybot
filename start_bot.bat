@echo off
chcp 65001 >nul
title FinTechBot
echo ==============================
echo    Starting FinTechBot...
echo ==============================
echo.

REM Navigate to the folder where this .bat file lives
cd /d "%~dp0"

REM Check if venv exists
if not exist "venv\Scripts\python.exe" (
    echo ERROR: Virtual environment not found!
    echo Please create it first with: python -m venv venv
    pause
    exit /b 1
)

REM Install dependencies silently
echo Checking dependencies...
"venv\Scripts\python.exe" -m pip install -r requirements.txt -q
echo Dependencies OK.
echo.

echo ==============================
echo    Bot is running!
echo    Press Ctrl+C to stop.
echo ==============================
echo.

REM Run the bot
"venv\Scripts\python.exe" bot.py

echo.
echo Bot stopped. Press any key to close...
pause >nul
