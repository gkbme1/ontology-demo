@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
REM 启动模拟 DCS 数据服务（实时值/历史值，返回模拟数据）。端口取 MOCK_DCS_PORT，默认 8900。

where python >nul 2>nul
if %errorlevel%==0 (set "PY=python") else (set "PY=py -3")

%PY% -m mock_dcs.main %*
