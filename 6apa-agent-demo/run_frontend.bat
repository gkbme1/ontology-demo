@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0frontend"
REM 启动 Vue 前端开发服务器。首次运行会自动 npm install。

if not exist .env copy /y .env.example .env >nul
if not exist node_modules (
  call npm install || exit /b 1
)
call npm run dev
