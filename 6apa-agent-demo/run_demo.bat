@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
REM 一键启动：本体服务(8700) + 模拟 DCS(8900) + Agent 服务(8800) + 零依赖演示页(8081)
REM 每个服务各开一个窗口，关掉窗口即停止该服务。
REM 本体服务目录用 ONTOLOGY_HOME 指定，默认与本目录同级的 6apa-ontology-demo。

where python >nul 2>nul
if %errorlevel%==0 (set "PY=python") else (set "PY=py -3")

REM ---- 版本自检：改了文件却没生效，多半是这一步没过 ----
echo [0/4] 版本自检（当前目录：%~dp0）
set "STALE="
findstr /C:"/api/examples" "%~dp0backend\main.py" >nul 2>nul
if errorlevel 1 (echo     [旧] backend\main.py 缺少 /api/examples 路由 & set "STALE=1") else (echo     [新] backend\main.py)
if exist "%~dp0backend\data\examples.json" (echo     [新] backend\data\examples.json) else (echo     [缺] backend\data\examples.json & set "STALE=1")
findstr /C:"api/examples" "%~dp0demo\index.html" >nul 2>nul
if errorlevel 1 (echo     [旧] demo\index.html 还是旧版演示页 & set "STALE=1") else (echo     [新] demo\index.html)
if defined STALE (
  echo.
  echo     ^>^> 上面标记为 [旧]/[缺] 的文件没有被新包覆盖，工艺调查案例不会出现。
  echo     ^>^> 请用新 zip 整目录覆盖后重新运行本脚本（backend\data\ 是新增目录，别跳过）。
  echo.
  pause
)

if "%ONTOLOGY_HOME%"=="" set "ONTOLOGY_HOME=%~dp0..\6apa-ontology-demo"

if exist "%ONTOLOGY_HOME%\backend\main.py" (
  echo [1/4] 本体服务 :8700  ^(%ONTOLOGY_HOME%^)
  start "6APA 本体服务 8700" /d "%ONTOLOGY_HOME%" cmd /k %PY% -m uvicorn backend.main:app --host 127.0.0.1 --port 8700
  timeout /t 5 /nobreak >nul
) else (
  echo [1/4] 跳过本体服务：未找到 %ONTOLOGY_HOME%\backend\main.py
  echo       先 set ONTOLOGY_HOME=本体服务目录 再运行，或自行启动后在 .env 设置 ONTOLOGY_BASE_URL
)

echo [2/4] 模拟 DCS 数据服务 :8900
start "6APA 模拟DCS 8900" cmd /k "%~dp0run_mock_dcs.bat"
timeout /t 3 /nobreak >nul

echo [3/4] Agent 服务 :8800
start "6APA Agent 8800" cmd /k "%~dp0run_backend.bat"
timeout /t 5 /nobreak >nul

echo [4/4] 演示页 :8081
start "6APA 演示页 8081" /d "%~dp0demo" cmd /k %PY% -m http.server 8081 --bind 127.0.0.1
timeout /t 2 /nobreak >nul

start "" "http://localhost:8081/index.html?api=http://localhost:8800"
echo 已全部启动。关闭对应窗口即可停止服务。
