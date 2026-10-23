"""实时值 / 历史值接口的挂载模块。

设计成"自带路由、一行挂载"，不改动 routes.py 的路由表，避免与其他版本的 routes.py 冲突。
在 backend/main.py 创建 app 之后加一行即可：

    from backend.api.timeseries_routes import mount as _mount_timeseries
    _mount_timeseries(app, get_store)

FastAPI 与 Starlette 回退模式都适用。
这里的 handler 会调用外部实时库 / 历史库，统一放进线程池执行，不阻塞事件循环。

注意：本文件刻意不使用 `from __future__ import annotations`，
FastAPI 需要在运行时解析 endpoint 的 `request: Request` 注解。
"""
import json
from typing import Any, Callable, List, Optional, Tuple

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse

from backend.services import timeseries
from backend.services.timeseries import ApiError

# (路径, 处理函数, 名称, 路径参数名)
_SPECS: List[Tuple[str, Callable[..., Any], str, Optional[str]]] = [
    ("/api/ontology/realtime", lambda store, q: timeseries.realtime(store, q), "实时值查询", None),
    ("/api/ontology/history", lambda store, q: timeseries.history(store, q), "历史值查询", None),
    ("/api/ontology/timeseries/status", lambda store, q: timeseries.status(), "实时库 / 历史库连接状态", None),
    (
        "/api/ontology/{object_id}/realtime",
        lambda store, q, object_id: timeseries.realtime(store, q, object_id),
        "对象实时值",
        "object_id",
    ),
    (
        "/api/ontology/{object_id}/history",
        lambda store, q, object_id: timeseries.history(store, q, object_id),
        "对象历史值",
        "object_id",
    ),
]


def _make_endpoint(handler: Callable[..., Any], param: Optional[str], get_store: Callable[[], Any]):
    async def endpoint(request: Request) -> JSONResponse:
        query = dict(request.query_params)
        args = (get_store(), query, request.path_params[param]) if param else (get_store(), query)
        try:
            result = await run_in_threadpool(handler, *args)
        except ApiError as exc:
            return JSONResponse({"detail": exc.detail}, status_code=exc.status)
        return JSONResponse(json.loads(json.dumps(result, ensure_ascii=False, default=str)))

    return endpoint


def mount(app: Any, get_store: Callable[[], Any]) -> None:
    """把 5 个接口挂到已创建好的 app 上，并登记到路由清单（/api/health 的 endpoints 能看到）。"""
    for path, handler, name, param in _SPECS:
        endpoint = _make_endpoint(handler, param, get_store)
        if hasattr(app, "add_api_route"):  # FastAPI：出现在 /docs 里
            app.add_api_route(path, endpoint, methods=["GET"], name=name, summary=name)
        else:  # Starlette 回退模式
            app.add_route(path, endpoint, methods=["GET"], name=name)

    # 登记到路由表，只用于 /api/health 的接口清单展示；snapshot=None，不进静态快照
    try:
        from backend.api.routes import ROUTES

        known = {route["path"] for route in ROUTES}
        for path, handler, name, param in _SPECS:
            if path not in known:
                entry = {"path": path, "handler": handler, "name": name, "snapshot": None}
                if param:
                    entry["param"] = param
                ROUTES.append(entry)
    except Exception:  # 登记失败不影响接口本身
        pass
