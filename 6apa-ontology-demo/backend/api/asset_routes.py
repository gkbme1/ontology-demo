"""资产本体视图接口的挂载模块（只新增接口，不改动任何原有接口）。

在 backend/main.py 创建 app 之后加一行：

    from backend.api.asset_routes import mount as _mount_assets
    _mount_assets(app, get_store)

接口：
    GET /api/ontology/asset-tree                    资产导航树根节点（本体域）
    GET /api/ontology/asset-tree?parent=<节点id>     某个节点的子节点（按需展开）
    GET /api/ontology/asset-tree/search?keyword=    搜索设备 / 设备组 / 工段 / 工艺对象 / 位号，返回在树中的完整路径
    GET /api/ontology/asset-profile/{object_id}     对象本体档案：类与层级、属性（含数据关联）、关系、能力、约束、规则、处置卡
    GET /api/ontology/procedures?keyword=&areaId=   报警处置卡列表
    GET /api/ontology/procedures/{card_id}          单张处置卡（触发、可能原因、处置步骤、禁止操作，含本体锚定）
    GET /api/ontology/{object_id}/procedures        与某对象相关的处置卡
                                                    object_id 支持 equip- / egrp- / robj- / area- / tag- 与 :Dev_ 形式

注意：本文件刻意不使用 `from __future__ import annotations`，
FastAPI 需要在运行时解析 endpoint 的 `request: Request` 注解。
"""
import json
from typing import Any, Callable, List, Optional, Tuple

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse

from backend.services import asset_model, procedure_model


def _procedure(store: Any, card_id: str) -> dict:
    card = store.procedures.cards.get(card_id)
    if not card:
        raise asset_model.ProfileNotFound(card_id)
    return card


def _object_procedures(store: Any, object_id: str) -> dict:
    items = asset_model.profile(store, object_id)["procedures"]
    return {"objectId": object_id, "items": items, "total": len(items)}


def _limit(q: dict) -> int:
    try:
        return max(1, min(100, int(q.get("limit") or 30)))
    except ValueError:
        return 30


_SPECS: List[Tuple[str, Callable[..., Any], str, Optional[str]]] = [
    ("/api/ontology/asset-tree", lambda store, q: asset_model.tree(store, q.get("parent")), "资产导航树", None),
    (
        "/api/ontology/asset-tree/search",
        lambda store, q: asset_model.search(store, q.get("keyword") or "", _limit(q)),
        "资产导航搜索",
        None,
    ),
    (
        "/api/ontology/asset-profile/{object_id}",
        lambda store, q, object_id: asset_model.profile(store, object_id),
        "对象本体档案",
        "object_id",
    ),
    # 报警处置规程（6APA_处置规程.xlsx）：处置卡列表、单张卡、某对象相关的卡
    ("/api/ontology/procedures", lambda store, q: procedure_model.search(store.procedures, q), "报警处置卡", None),
    ("/api/ontology/procedures/{card_id}", lambda store, q, card_id: _procedure(store, card_id), "报警处置卡详情", "card_id"),
    (
        "/api/ontology/{object_id}/procedures",
        lambda store, q, object_id: _object_procedures(store, object_id),
        "对象相关的报警处置卡",
        "object_id",
    ),
]


def _make_endpoint(handler: Callable[..., Any], param: Optional[str], get_store: Callable[[], Any]):
    async def endpoint(request: Request) -> JSONResponse:
        query = dict(request.query_params)
        args = (get_store(), query, request.path_params[param]) if param else (get_store(), query)
        try:
            result = await run_in_threadpool(handler, *args)
        except Exception as exc:
            status = getattr(exc, "status", 500)
            detail = getattr(exc, "detail", f"{type(exc).__name__}: {exc}")
            return JSONResponse({"detail": detail}, status_code=status)
        return JSONResponse(json.loads(json.dumps(result, ensure_ascii=False, default=str)))

    return endpoint


def mount(app: Any, get_store: Callable[[], Any]) -> None:
    for path, handler, name, param in _SPECS:
        endpoint = _make_endpoint(handler, param, get_store)
        if hasattr(app, "add_api_route"):  # FastAPI
            app.add_api_route(path, endpoint, methods=["GET"], name=name, summary=name)
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
