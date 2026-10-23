"""工艺限值接口 + 限值展示页的挂载模块。

在 backend/main.py 创建 app 之后加一行：

    from backend.api.limits_routes import mount as _mount_limits
    _mount_limits(app, get_store)

接口：
    GET /api/ontology/process-limits            限值清单 ?area= ?appliesTo= ?status= ?keyword= ?hasValues=
    GET /api/ontology/{object_id}/limits        某对象适用的限值
    GET /api/ontology/{object_id}/limit-check   取实时值逐点判断是否越限（需实时历史接口补丁）
    GET /api/ontology/process-limits/{limit_id}/check  只检查一条限值
    GET /limits                                 限值展示页（可 iframe 嵌入）

注意：本文件刻意不使用 `from __future__ import annotations`，
FastAPI 需要在运行时解析 endpoint 的 `request: Request` 注解。
"""
import json
from pathlib import Path
from typing import Any, Callable, List, Optional, Tuple

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse

from backend.services import process_limits

PAGE = Path(__file__).resolve().parents[2] / "web" / "limits.html"

_SPECS: List[Tuple[str, Callable[..., Any], str, Optional[str]]] = [
    ("/api/ontology/process-limits", lambda store, q: process_limits.list_limits(store, q), "工艺限值清单", None),
    (
        "/api/ontology/{object_id}/limits",
        lambda store, q, object_id: process_limits.limits_for_object(store, object_id),
        "对象工艺限值",
        "object_id",
    ),
    (
        "/api/ontology/process-limits/{limit_id}/check",
        lambda store, q, limit_id: process_limits.check_limit(store, limit_id, q),
        "单条限值越限判断",
        "limit_id",
    ),
    (
        "/api/ontology/{object_id}/limit-check",
        lambda store, q, object_id: process_limits.check(store, object_id, q),
        "对象越限判断",
        "object_id",
    ),
]


def _make_endpoint(handler: Callable[..., Any], param: Optional[str], get_store: Callable[[], Any]):
    async def endpoint(request: Request) -> JSONResponse:
        query = dict(request.query_params)
        args = (get_store(), query, request.path_params[param]) if param else (get_store(), query)
        try:
            result = await run_in_threadpool(handler, *args)
        except Exception as exc:  # 上游（实时库）或参数问题，转成可读错误
            status = getattr(exc, "status", 500)
            detail = getattr(exc, "detail", f"{type(exc).__name__}: {exc}")
            return JSONResponse({"detail": detail}, status_code=status)
        return JSONResponse(json.loads(json.dumps(result, ensure_ascii=False, default=str)))

    return endpoint


def mount(app: Any, get_store: Callable[[], Any]) -> None:
    async def page(request: Request):
        if not PAGE.is_file():
            return JSONResponse({"detail": f"页面文件缺失：{PAGE}"}, status_code=500)
        return FileResponse(PAGE, media_type="text/html; charset=utf-8")

    routes = [(path, _make_endpoint(handler, param, get_store), name)
              for path, handler, name, param in _SPECS]
    routes += [("/limits", page, "工艺限值展示页"), ("/limits.html", page, "工艺限值展示页(别名)")]

    for path, endpoint, name in routes:
        if hasattr(app, "add_api_route"):  # FastAPI
            app.add_api_route(path, endpoint, methods=["GET"], name=name, summary=name,
                              include_in_schema=path.startswith("/api"))
        else:  # Starlette 回退模式
            app.add_route(path, endpoint, methods=["GET"], name=name)

    # 登记到路由清单，/api/health 的 endpoints 里能看到
    try:
        from backend.api.routes import ROUTES

        known = {r["path"] for r in ROUTES}
        for path, handler, name, param in _SPECS:
            if path not in known:
                entry = {"path": path, "handler": handler, "name": name, "snapshot": None}
                if param:
                    entry["param"] = param
                ROUTES.append(entry)
    except Exception:
        pass
