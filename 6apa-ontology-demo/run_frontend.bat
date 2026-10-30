@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0frontend"
REM 启动本体前端（Vite 开发服务器，默认 5173；/api 代理到本体服务 8700，见 frontend\.env）
REM 需要 Node.js 18+。首次运行会自动 npm install。
where npm >nul 2>nul
if errorlevel 1 (
  echo 未找到 npm：请先安装 Node.js 18 或以上版本 ^(https://nodejs.org^)，安装后重新打开命令行窗口。
  pause
  exit /b 1
)
if not exist "node_modules\.bin\vite.cmd" (
  echo 首次运行，安装前端依赖……
  call npm install --no-audit --no-fund
  if errorlevel 1 (
    echo npm install 失败。package-lock.json 使用 npmmirror 镜像，网络不通时可改用：
    echo     npm install --registry=https://registry.npmjs.org/
    pause
    exit /b 1
  )
)
echo 本体前端：http://localhost:5173
call npm run dev -- --host 127.0.0.1 --open
