@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
title FinTechBot Premium Control Center

:: ANSI Color Codes
set "ESC="
set "G=%ESC%[92m"
set "B=%ESC%[94m"
set "C=%ESC%[96m"
set "Y=%ESC%[93m"
set "R=%ESC%[91m"
set "W=%ESC%[0m"

echo %B%================================================================%W%
echo %C%            FinTechBot Premium Wealth Manager Engine            %W%
echo %B%================================================================%W%
echo.

:: Navigate to project root
cd /d "%~dp0"

:: 1. Environment Verification
if not exist ".venv\Scripts\python.exe" (
    echo %R%[!] CRITICAL ERROR: Virtual environment not found.%W%
    echo Please initialize with: %Y%python -m venv .venv%W%
    pause
    exit /b 1
)

:: 2. Smart Dependency Check (Speed Optimization)
if exist ".agent\.deps_installed" (
    echo %G%[✔] Dependencies previously satisfied. Skipping deep scan.%W%
) else (
    echo %Y%[*] Initializing first-run dependency synchronization...%W%
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt -q
    if !errorlevel! equ 0 (
        if not exist ".agent" mkdir ".agent"
        echo %date% %time% > ".agent\.deps_installed"
        echo %G%[✔] synchronization complete.%W%
    ) else (
        echo %R%[!] Deployment failed. Check your internet connection.%W%
        pause
        exit /b 1
    )
)
echo.

:: 3. Launch Full Stack
echo %G%[+] Initializing API Intelligence Layer (main.py)...%W%
start "FinTechBot API Layer" /min ".venv\Scripts\python.exe" main.py

echo %G%[+] Initializing Telegram Interface (bot.py)...%W%
echo.
echo %B%----------------------------------------------------------------%W%
echo %C%    Bot is now active. Monitoring financial events...          %W%
echo %C%    Press CTRL+C in this window to terminate the session.     %W%
echo %B%----------------------------------------------------------------%W%
echo.

:: Run the bot in foreground
".venv\Scripts\python.exe" bot.py

echo.
echo %Y%[!] Bot process terminated.%W%
echo Press any key to exit Control Center...
pause >nul

