@echo off
cd /d "%~dp0"
set PYTHONPATH=src
python -m pytest tests -q --import-mode=importlib
pause
