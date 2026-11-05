@echo off
rem Start 6APA ontology demo v2 on Windows. Keep this file ASCII-only with CRLF line endings.
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
set PY=
rem "python" may be the Microsoft Store stub, so actually run it before trusting it
python -c "import sys" >nul 2>nul && set PY=python
if not defined PY py -3 -c "import sys" >nul 2>nul && set PY=py -3
if not defined PY (
  echo [ERROR] Python not found. Install Python 3.9+ from https://www.python.org and tick "Add python.exe to PATH".
  pause
  exit /b 1
)
%PY% start_demo.py
echo.
pause
