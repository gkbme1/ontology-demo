"""本体服务入口。

优先使用 FastAPI（需求文档第二十七章）；若运行环境中 FastAPI 不可用，
自动回退到 Starlette 装配同一份路由表，保证 API 契约完全一致。

启动：
    uvicorn backend.main:app --reload --port 8700
    python3 -m backend.main                      # 等价，端口取自 ONTOLOGY_PORT

端口与监听地址可用环境变量覆盖，无需改代码：
    ONTOLOGY_PORT=9100 ONTOLOGY_HOST=127.0.0.1 python3 -m backend.main
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from backend.api.routes import ROUTES, route_index
from backend.ontology.indexes import OntologyStore

# 必须在模块级导入：本文件启用了 `from __future__ import annotations`，
# 所有类型注解在运行时都是字符串，FastAPI 反射 handler 签名时会用
# 函数的 __globals__（也就是本模块的全局命名空间）去解析 "Request"。
# 若把它放在 _build_fastapi() 内部导入，FastAPI 解析不到这个名字，
# 会把 request 当成必填查询参数，导致每个接口都返回 422。
# FastAPI 的 Request 就是 Starlette 的 Request，二者等价。
from starlette.requests import Request

ROOT = Path(__file__).resolve().parents[1]

# 本体服务默认端口。改端口优先用环境变量，不要改这里的常量。
DEFAULT_PORT = int(os.environ.get("ONTOLOGY_PORT", "8700"))
DEFAULT_HOST = os.environ.get("ONTOLOGY_HOST", "0.0.0.0")


async def _probe(request: Request):  # pragma: no cover - 仅用于启动自检
    """签名与真实 endpoint 一致，供 _assert_request_annotation_resolvable 反射。"""
    return request


def _assert_request_annotation_resolvable() -> None:
    """启动自检：确保 "Request" 注解能从本模块全局解析。

    本文件启用了 PEP 563（`from __future__ import annotations`），注解在运行时
    是字符串。FastAPI 用 endpoint 的 __globals__ 解析它；一旦解析不到，就会把
    request 当成必填查询参数，导致所有接口返回 422 而不是报错。这里提前拦住。
    """
    import typing

    hints = typing.get_type_hints(_probe)
    if hints.get("request") is not Request:
        raise RuntimeError(
            "Request 注解无法从模块全局解析——请确认 `from starlette.requests import Request` "
            "位于 backend/main.py 的模块级，而不是某个函数内部。"
        )


_assert_request_annotation_resolvable()

_store: OntologyStore | None = None


def get_store() -> OntologyStore:
    global _store
    if _store is None:
        _store = OntologyStore()
    return _store


def reload_store() -> OntologyStore:
    global _store
    _store = OntologyStore()
    return _store


def dispatch(path_template: str, query: dict[str, Any], path_params: dict[str, str]) -> Any:
    store = get_store()
    route = next(r for r in ROUTES if r["path"] == path_template)
    if route.get("param"):
        return route["handler"](store, query, path_params[route["param"]])
    return route["handler"](store, query)


def _meta() -> dict[str, Any]:
    return {
        "service": "6-APA 生产线工业本体服务",
        "status": "ok",
        "port": DEFAULT_PORT,
        "endpoints": route_index(),
    }


# --------------------------------------------------------------- FastAPI

# v2 的数据量下，首次构建索引要十几秒。若不预热，第一个请求会顶着这十几秒，
# 调用方很容易误判为"服务没起来"。这里在进程启动时就把索引建好。
def _warm_up() -> None:  # pragma: no cover
    import logging
    import time

    started = time.time()
    store = get_store()
    logging.getLogger("uvicorn.error").info(
        "本体索引已就绪：%d 工段 / %d 设备 / %d 点位 / %d 关系，耗时 %.1fs",
        len(store.dcs.areas), len(store.dcs.equipment), len(store.dcs.tags),
        len(store.relations.relations), time.time() - started,
    )




from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app):
    _warm_up()          # 如果 _warm_up 是 async 函数,这里用 await _warm_up()
    yield
    # 这里可以放关闭时的清理逻辑

def _build_fastapi():
    from fastapi import FastAPI, HTTPException
    from fastapi.middleware.cors import CORSMiddleware

    app = FastAPI(title="6-APA 生产线工业本体服务", version="1.0.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health():
        return _meta()

    def make_endpoint(route):
        param = route.get("param")

        if param:
            async def endpoint(request: Request):
                value = request.path_params[param]
                result = route["handler"](get_store(), dict(request.query_params), value)
                if result is None:
                    raise HTTPException(status_code=404, detail=f"未找到对象：{value}")
                return result
        else:
            async def endpoint(request: Request):
                return route["handler"](get_store(), dict(request.query_params))

        return endpoint

    for route in ROUTES:
        app.add_api_route(route["path"], make_endpoint(route), methods=["GET"], name=route["name"], summary=route["name"])
    
    return app


# --------------------------------------------------------------- Starlette 回退

def _build_starlette():
    import contextlib

    from starlette.applications import Starlette
    from starlette.concurrency import run_in_threadpool
    from starlette.middleware import Middleware
    from starlette.middleware.cors import CORSMiddleware
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    def make_endpoint(route):
        param = route.get("param")

        async def endpoint(request: Request):
            query = dict(request.query_params)
            if param:
                value = request.path_params[param]
                result = route["handler"](get_store(), query, value)
                if result is None:
                    return JSONResponse({"detail": f"未找到对象：{value}"}, status_code=404)
            else:
                result = route["handler"](get_store(), query)
            return JSONResponse(json.loads(json.dumps(result, ensure_ascii=False, default=str)))

        return endpoint

    async def health(request: Request):
        return JSONResponse(_meta())

    @contextlib.asynccontextmanager
    async def lifespan(_app):
        await run_in_threadpool(_warm_up)
        yield

    routes = [Route("/api/health", health)]
    routes += [Route(r["path"], make_endpoint(r)) for r in ROUTES]
    return Starlette(
        routes=routes,
        lifespan=lifespan,
        middleware=[Middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"])],
    )


try:  # pragma: no cover
    app = _build_fastapi()
    FRAMEWORK = "fastapi"
except ImportError:  # pragma: no cover
    app = _build_starlette()
    FRAMEWORK = "starlette"

# 实时值 / 历史值：本体作为语义网关调用外部实时库 / 历史库（地址见 RTDB_BASE_URL 等环境变量）
from backend.api.timeseries_routes import mount as _mount_timeseries  # noqa: E402

_mount_timeseries(app, get_store)

# 独立关系展示页：/relations?rootId=…（可 iframe 嵌入）
from backend.api.relation_view import mount as _mount_relation_view # noqa: E402
_mount_relation_view(app)

# 工艺限值接口与限值展示页
from backend.api.limits_routes import mount as _mount_limits # noqa: E402
_mount_limits(app, get_store)

# 资产本体视图：资产导航树、搜索、对象本体档案（只新增接口）
from backend.api.asset_routes import mount as _mount_assets # noqa: E402
_mount_assets(app, get_store)

if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    print(f"本体服务启动（框架：{FRAMEWORK}）→ http://{DEFAULT_HOST}:{DEFAULT_PORT}")
    uvicorn.run(app, host=DEFAULT_HOST, port=DEFAULT_PORT)
