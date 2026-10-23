@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
REM 启动本体服务（默认 8700）。实时库 / 历史库地址用 RTDB_BASE_URL / HISTORIAN_BASE_URL 覆盖，默认 http://localhost:8900
if "%ONTOLOGY_PORT%"=="" set "ONTOLOGY_PORT=8700"
where python >nul 2>nul
if %errorlevel%==0 (set "PY=python") else (set "PY=py -3")
echo 本体服务启动中：http://localhost:%ONTOLOGY_PORT%
%PY% -m uvicorn backend.main:app --host 0.0.0.0 --port %ONTOLOGY_PORT%
