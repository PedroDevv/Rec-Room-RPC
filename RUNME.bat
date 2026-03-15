@echo off
title Rec Room Discord Rich Presence

echo.
echo  Rec Room Discord Rich Presence
echo  --------------------------------
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo  Python is not installed or not in PATH.
    echo  Download it from https://www.python.org/downloads/
    echo  Make sure to check "Add Python to PATH" during install.
    echo.
    pause
    exit /b 1
)

echo  Installing dependencies...
echo.
pip install pypresence requests playwright curl_cffi psutil pystray pillow --quiet --disable-pip-version-check
if errorlevel 1 (
    echo.
    echo  Failed to install dependencies. Check your internet connection.
    echo.
    pause
    exit /b 1
)

echo.
echo  Setting up browser...
echo.
python -m playwright install chromium
if errorlevel 1 (
    echo.
    echo  Failed to install Chromium. Check your internet connection.
    echo.
    pause
    exit /b 1
)

echo.
echo  Starting...
echo.
start pythonw main.py
