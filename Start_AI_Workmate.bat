@echo off
title AI Workmate Launcher
cd /d "%~dp0"
where python >nul 2>&1
if not errorlevel 1 (
    python launch_ai_workmate.py
    goto finish
)
where py >nul 2>&1
if not errorlevel 1 (
    py -3 launch_ai_workmate.py
    goto finish
)
echo Python 3.8 or newer is required.
echo Please install Python and try again.
pause
:finish
