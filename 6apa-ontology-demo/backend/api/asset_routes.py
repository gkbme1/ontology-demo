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
    GET /api/ontology/process-steps                 工序与工艺阶段定义
    GET /api/ontology/investigation-knowledge       调查知识：原因分类与权重、化验项目、判定规则、漂移口径
    GET /api/ontology/cause-profile?ids=&names=     候选原因的人机料法环分类与权重
    GET /api/ontology/{object_id}/judgement-rules   对象适用的判定规则与化验项目（{x} 换成本台罐号）
    GET /api/ontology/{object_id}/lab-results       设备的化验结果（LIMS + 人工录入）
    POST /api/ontology/{object_id}/lab-results      人工录入化验结果（写入 LIMS）
    GET /api/ontology/{object_id}/operations        设备的操作记录（DCS 操作日志，附班次）
    GET /api/ontology/process-limits/{id}/versions  限值版本；POST 追加版本（在线修改，必须写修改人与原因）
    GET /api/ontology/process-limits/{id}/effective?at=&unit=&enzymeBatchCount=  某时刻生效的限值
    GET /api/ontology/batches/{batch_no}            按批号查罐批次（EBR），落到设备实例
    GET /api/ontology/{object_id}/stage-rules       设备的阶段识别规则（{x} 换成罐号后的 DCS 位号）
    GET /api/ontology/{object_id}/batches           设备的罐批次（EBR）?startTime=&endTime=
    GET /api/ontology/{object_id}/context?at=       设备在某时刻的运行上下文（批次 / 阶段 / 换酶后批次数 / 班次）
    GET /api/ontology/shifts                        班次（MOM 排班）
                                                    object_id 支持 equip- / egrp- / robj- / area- / tag- 与 :Dev_ 形式

注意：本文件刻意不使用 `from __future__ import annotations`，
FastAPI 需要在运行时解析 endpoint 的 `request: Request` 注解。
"""
import json
from typing import Any, Callable, List, Optional, Tuple

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse

from backend.services import asset_model, investigation, limit_versions, procedure_model, process_context


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
    # 工序与阶段定义；罐批次 / 运行上下文 / 排班（经本体代调 EBR、MOM）
    ("/api/ontology/process-steps", lambda store, q: store.process.view(), "工序与工艺阶段", None),
    ("/api/ontology/shifts", lambda store, q: process_context.shifts(store, q), "班次（MOM 排班）", None),
    (
        "/api/ontology/batches/{batch_no}",
        lambda store, q, batch_no: process_context.batch_detail(store, batch_no),
        "按批号查罐批次（EBR）",
        "batch_no",
    ),
    (
        "/api/ontology/{object_id}/stage-rules",
        lambda store, q, object_id: process_context.stage_rules(store, object_id),
        "设备的阶段识别规则（DCS 位号）",
        "object_id",
    ),
    (
        "/api/ontology/{object_id}/batches",
        lambda store, q, object_id: process_context.batches(store, object_id, q),
        "设备的罐批次（EBR）",
        "object_id",
    ),
    (
        "/api/ontology/{object_id}/context",
        lambda store, q, object_id: process_context.context(store, object_id, q),
        "设备在某时刻的运行上下文",
        "object_id",
    ),
    # 调查知识（6APA_调查知识.xlsx）：原因分类与权重、化验项目、判定规则、漂移口径
    ("/api/ontology/investigation-knowledge", lambda store, q: store.investigation.view(), "调查知识", None),
    ("/api/ontology/cause-profile", lambda store, q: investigation.cause_profile(store, q), "候选原因的人机料法环分类与权重", None),
    (
        "/api/ontology/{object_id}/judgement-rules",
        lambda store, q, object_id: investigation.object_rules(store, object_id),
        "对象适用的判定规则与化验项目",
        "object_id",
    ),
    # 化验（LIMS / 人工录入）与操作记录（DCS 操作日志），经本体代调
    (
        "/api/ontology/{object_id}/lab-results",
        lambda store, q, object_id: process_context.lab_results(store, object_id, q),
        "设备的化验结果（LIMS）",
        "object_id",
    ),
    (
        "/api/ontology/{object_id}/operations",
        lambda store, q, object_id: process_context.operations(store, object_id, q),
        "设备的操作记录（DCS 操作日志）",
        "object_id",
    ),
    # 限值版本（6APA_限值版本.xlsx）：版本清单、某时刻生效限值
    (
        "/api/ontology/process-limits/{limit_id}/versions",
        lambda store, q, limit_id: limit_versions.versions(store, limit_id),
        "限值版本",
        "limit_id",
    ),
    (
        "/api/ontology/process-limits/{limit_id}/effective",
        lambda store, q, limit_id: limit_versions.effective(store, limit_id, q),
        "某时刻生效的限值",
        "limit_id",
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


# 写接口（POST，JSON 请求体）：handler(store, body, path_param)
_WRITE_SPECS: List[Tuple[str, Callable[..., Any], str, str]] = [
    (
        "/api/ontology/process-limits/{limit_id}/versions",
        lambda store, body, limit_id: limit_versions.add_version(store, limit_id, body),
        "在线修改限值（追加版本）",
        "limit_id",
    ),
    (
        "/api/ontology/{object_id}/lab-results",
        lambda store, body, object_id: process_context.submit_lab_result(store, object_id, body),
        "人工录入化验结果（写入 LIMS）",
        "object_id",
    ),
]


def _make_write_endpoint(handler: Callable[..., Any], param: str, get_store: Callable[[], Any]):
    async def endpoint(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"detail": "请求体必须是 JSON"}, status_code=400)
        try:
            result = await run_in_threadpool(handler, get_store(), body, request.path_params[param])
        except Exception as exc:
            status = getattr(exc, "status", 500)
            detail = getattr(exc, "detail", f"{type(exc).__name__}: {exc}")
            return JSONResponse({"detail": detail}, status_code=status)
        return JSONResponse(json.loads(json.dumps(result, ensure_ascii=False, default=str)))

    return endpoint


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

    for path, handler, name, param in _WRITE_SPECS:
        endpoint = _make_write_endpoint(handler, param, get_store)
        if hasattr(app, "add_api_route"):
            app.add_api_route(path, endpoint, methods=["POST"], name=name + "·POST", summary=name)
        else:
            app.add_route(path, endpoint, methods=["POST"], name=name + "·POST")

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
