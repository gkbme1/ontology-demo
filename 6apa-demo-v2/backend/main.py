"""6APA 本体 Demo v2 服务入口。

    python3 -m backend.main                 # 默认 0.0.0.0:8710
    V2_PORT=9000 python3 -m backend.main

前端构建产物（frontend/dist）存在时一并托管，打开 http://localhost:8710/ 即可；
开发时用 vite（5180 端口，/api 代理到 8710）。
"""
from __future__ import annotations

import mimetypes
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.api.routes import router
from backend.v2.context import get_ctx

# Windows 上 Python 从注册表读 MIME 类型，不少机器把 .js 登记成 text/plain，
# 浏览器会拒绝执行 <script type="module">，页面一片空白。这里强制写对。
for _ext, _type in ((".js", "text/javascript"), (".mjs", "text/javascript"), (".css", "text/css"),
                    (".svg", "image/svg+xml"), (".json", "application/json"), (".png", "image/png"),
                    (".html", "text/html")):
    mimetypes.add_type(_type, _ext)

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "frontend" / "dist"
PORT = int(os.environ.get("V2_PORT", "8710"))
HOST = os.environ.get("V2_HOST", "0.0.0.0")

@asynccontextmanager
async def _lifespan(_app: FastAPI):  # noqa: ANN202
    get_ctx()  # 启动时加载本体，首个请求不用等
    yield


app = FastAPI(title="6APA 本体 Demo v2", version="0.1.0", lifespan=_lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(router)


if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):  # noqa: ANN201
        target = DIST / path
        if path and target.is_file():
            return FileResponse(target)
        return FileResponse(DIST / "index.html")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=HOST, port=PORT)
