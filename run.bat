@echo off
cd /d "%~dp0"
"C:\Users\user1\anaconda3\envs\py312\python.exe" harness_gui.py
if errorlevel 1 (
    echo.
    echo Failed to start. Check Python environment.
    pause
)
