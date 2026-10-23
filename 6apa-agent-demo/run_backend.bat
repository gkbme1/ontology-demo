@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
REM 启动 Agent 服务。端口取 .env 的 AGENT_PORT（默认 8800）。

if not exist .env (
  echo 未找到 .env，已从 .env.example 复制一份。
  copy /y .env.example .env >nul
  echo 请用记事本打开 .env 填入 LLM_API_KEY 后重新运行。
  pause
  exit /b 1
)

set "PORT=8800"
for /f "usebackq tokens=1,* delims==" %%a in (".env") do (
  if /i "%%a"=="AGENT_PORT" if not "%%b"=="" set "PORT=%%b"
)

where python >nul 2>nul
if %errorlevel%==0 (set "PY=python") else (set "PY=py -3")

echo Agent 服务启动中：http://localhost:%PORT%
%PY% -m uvicorn backend.main:app --host 0.0.0.0 --port %PORT% %*
