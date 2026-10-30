@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
REM 一键启动：本体服务(8700) + 本体前端(5173) + 模拟 DCS(8900) + Agent 服务(8800) + 零依赖演示页(8081)
REM 每个服务各开一个窗口，关掉窗口即停止该服务。
REM 本体服务目录用 ONTOLOGY_HOME 指定，默认与本目录同级的 6apa-ontology-demo。

where python >nul 2>nul
if %errorlevel%==0 (set "PY=python") else (set "PY=py -3")

REM ---- 版本自检：改了文件却没生效，多半是这一步没过 ----
echo [0/5] 版本自检（当前目录：%~dp0）
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

set "ONTO_STARTED="
if exist "%ONTOLOGY_HOME%\backend\main.py" (
  echo [1/5] 本体服务 :8700  ^(%ONTOLOGY_HOME%^)
  start "6APA 本体服务 8700" /d "%ONTOLOGY_HOME%" cmd /k %PY% -m uvicorn backend.main:app --host 127.0.0.1 --port 8700
  set "ONTO_STARTED=1"
) else (
  echo [1/5] 跳过本体服务：未找到 %ONTOLOGY_HOME%\backend\main.py
  echo       先 set ONTOLOGY_HOME=本体服务目录 再运行，或自行启动后在 .env 设置 ONTOLOGY_BASE_URL
)
if not defined ONTO_STARTED goto onto_ready

REM 模拟 DCS 启动时要从本体服务读点表，所以等本体服务就绪（最多约 40 秒）再往下走
where curl >nul 2>nul
if errorlevel 1 (
  timeout /t 10 /nobreak >nul
  goto onto_ready
)
set /a WAITED=0
:wait_onto
curl -s -o nul http://127.0.0.1:8700/api/health
if not errorlevel 1 goto onto_ready
set /a WAITED+=1
if %WAITED% geq 40 (
  echo       本体服务 40 秒内未就绪，继续启动其余服务；请查看“本体服务 8700”窗口的报错
  goto onto_ready
)
timeout /t 1 /nobreak >nul
goto wait_onto
:onto_ready

if exist "%ONTOLOGY_HOME%\run_frontend.bat" (
  echo [2/5] 本体前端 :5173  ^(资产本体导航，首次运行会先 npm install^)
  start "6APA 本体前端 5173" cmd /k "%ONTOLOGY_HOME%\run_frontend.bat"
) else (
  echo [2/5] 跳过本体前端：未找到 %ONTOLOGY_HOME%\run_frontend.bat
)

echo [3/5] 模拟 DCS 数据服务 :8900
start "6APA 模拟DCS 8900" cmd /k "%~dp0run_mock_dcs.bat"
timeout /t 3 /nobreak >nul

echo [4/5] Agent 服务 :8800
start "6APA Agent 8800" cmd /k "%~dp0run_backend.bat"
timeout /t 5 /nobreak >nul

echo [5/5] 演示页 :8081
start "6APA 演示页 8081" /d "%~dp0demo" cmd /k %PY% -m http.server 8081 --bind 127.0.0.1
timeout /t 2 /nobreak >nul

start "" "http://localhost:8081/index.html?api=http://localhost:8800"
echo 已全部启动。关闭对应窗口即可停止服务。
echo   本体前端（资产本体）：http://localhost:5173   ^(由“本体前端 5173”窗口自动打开浏览器^)
echo   Agent 演示页      ：http://localhost:8081/index.html?api=http://localhost:8800
