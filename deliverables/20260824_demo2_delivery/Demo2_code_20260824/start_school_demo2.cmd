@echo off
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_school_demo.ps1" -Page seewo_student_demo2
if errorlevel 1 pause
