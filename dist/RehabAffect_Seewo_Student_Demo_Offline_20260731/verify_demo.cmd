@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" tools\smoke_test.py
) else (
  python tools\smoke_test.py
)
if errorlevel 1 pause
