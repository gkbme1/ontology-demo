@echo off
rem 一键启动 6APA 本体 Demo v2（Windows）。浏览器打开 http://localhost:8710/
chcp 65001 >nul
cd /d %~dp0
python -c "import fastapi, uvicorn, pandas, openpyxl, numpy" 2>nul || pip install -r requirements.txt
if not exist "data\config\6APA_空间层级.xlsx" python -m backend.tools.build_config
if not exist "data\seed\phenomena.json" python -m backend.tools.build_seed
if not exist "frontend\dist\index.html" (
  pushd frontend
  if not exist node_modules call npm install
  call npm run build
  popd
)
echo 打开 http://localhost:8710/
python -m backend.main
