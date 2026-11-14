"""跨平台启动器：检查环境 → 启动后端 → 等服务就绪 → 打开浏览器。

    python start_demo.py            # Windows 上 run_demo.bat 调的就是它
    python start_demo.py --no-browser

出错时给出中文原因和处理办法，不会一闪而过。
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PORT = int(os.environ.get("V2_PORT", "8710"))
URL = f"http://localhost:{PORT}/"
DEPS = ["fastapi", "uvicorn", "pandas", "openpyxl", "numpy"]


def say(msg: str) -> None:
    print(msg, flush=True)


def fail(msg: str) -> None:
    say("")
    say("【启动失败】" + msg)
    sys.exit(1)


def check_python() -> None:
    if sys.version_info < (3, 9):
        fail(f"Python 版本太低（{sys.version.split()[0]}），需要 3.9 或以上。请从 https://www.python.org 安装新版本，"
             "安装时勾选「Add python.exe to PATH」。")
    say(f"[1/5] Python {sys.version.split()[0]}：{sys.executable}")


def check_deps() -> None:
    missing = [m for m in DEPS if importlib.util.find_spec(m) is None]
    if not missing:
        say("[2/5] Python 依赖已安装")
        return
    say(f"[2/5] 缺少依赖 {', '.join(missing)}，正在安装（首次需要几分钟）…")
    cmd = [sys.executable, "-m", "pip", "install", "-r", str(ROOT / "requirements.txt")]
    if subprocess.call(cmd) != 0:
        fail("依赖安装失败。可以手动执行：\n    " + " ".join(f'"{c}"' if " " in c else c for c in cmd)
             + "\n公司网络访问不了 PyPI 时，可加镜像：-i https://pypi.tuna.tsinghua.edu.cn/simple")
    still = [m for m in DEPS if importlib.util.find_spec(m) is None]
    if still:
        fail(f"安装后仍找不到 {', '.join(still)}，可能装到了别的 Python 里。请用同一个 python 执行 pip install。")


def check_data() -> None:
    for rel in ("data/config/6APA_空间层级.xlsx", "data/seed/phenomena.json", "data/source/6APA_DCS.xlsx"):
        if not (ROOT / rel).exists():
            fail(f"缺少数据文件 {rel}。请确认拿到的是完整的 6apa-demo-v2 文件夹（git 拉取或完整解压）。")
    say("[3/5] 数据文件齐全")


def check_frontend() -> None:
    if (ROOT / "frontend" / "dist" / "index.html").exists():
        say("[4/5] 前端页面已就绪")
        return
    npm = shutil.which("npm")
    if not npm:
        fail("缺少前端页面 frontend/dist，且本机没有 Node.js 无法现场构建。请重新拉取最新代码（已包含构建好的页面），"
             "或安装 Node.js 18+ 后重试。")
    say("[4/5] 构建前端页面…")
    front = ROOT / "frontend"
    if not (front / "node_modules").exists() and subprocess.call([npm, "install"], cwd=front) != 0:
        fail("npm install 失败")
    if subprocess.call([npm, "run", "build"], cwd=front) != 0:
        fail("前端构建失败")


def port_busy() -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", PORT)) == 0


def healthy() -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/v2/health", timeout=2) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


def main() -> None:
    os.chdir(ROOT)
    check_python()
    check_deps()
    check_data()
    check_frontend()
    if port_busy():
        if healthy():
            say(f"[5/5] Demo 已经在运行，直接打开 {URL}")
            if "--no-browser" not in sys.argv:
                webbrowser.open(URL)
            return
        fail(f"端口 {PORT} 被其他程序占用。可以关掉占用的程序，或换端口：set V2_PORT=8711 后再运行。")

    say(f"[5/5] 启动后端（加载 Excel 约 10～30 秒）…")
    env = {**os.environ, "V2_PORT": str(PORT), "PYTHONIOENCODING": "utf-8"}
    proc = subprocess.Popen([sys.executable, "-m", "backend.main"], cwd=ROOT, env=env)
    for _ in range(180):
        if proc.poll() is not None:
            fail("后端启动时出错退出，错误信息见上方。把上面的报错截图发给开发即可定位。")
        if healthy():
            break
        time.sleep(1)
    else:
        proc.terminate()
        fail("等了 3 分钟后端仍未就绪，错误信息见上方。")
    say("")
    say(f"  已启动：{URL}")
    say("  关闭本窗口即停止 Demo。")
    say("")
    if "--no-browser" not in sys.argv:
        webbrowser.open(URL)
    try:
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()


if __name__ == "__main__":
    main()
