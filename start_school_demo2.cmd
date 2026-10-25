@echo off
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_school_demo.ps1" -Page demo2_login
if errorlevel 1 pause
