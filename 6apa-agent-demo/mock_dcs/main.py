"""模拟 DCS 数据服务：实时值 + 历史值。

⚠️ 这里返回的全部是按测点合理性"制造"出来的模拟数据，不是现场真实读数。
   接真实实时库 / 时序库时，把调用方的地址指过去即可，本服务整体丢弃。

接口：
    POST /api/hsm-db-rtserver/v1/rtdata/node/read     实时值（格式按现场实时库接口）
    POST /api/timing-svc/v1/history/findAll          历史值（格式为暂定设计，待对齐真实时序库）
    GET  /api/health                                 服务状态、点表加载情况
    GET  /api/mock/nodes?keyword=&station=&limit=&offset=  按关键词找 nodeId（调试用）
    GET  /api/mock/profile?nodeId=                   解释某个点的模拟规则（调试用）

启动：
    python3 -m mock_dcs.main            # 端口取 MOCK_DCS_PORT，默认 8900
"""

from __future__ import annotations

import logging
import math
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse

from .catalog import Catalog, node_id_of, parse_node_id
from .config import settings
from .profiles import classify
from .signals import Signal

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s | %(message)s")
logger = logging.getLogger("mock_dcs")

# 业务错误码（HTTP 恒为 200，与实时库接口的 code/message 包装保持一致）
OK = 0
E_BAD_PARAM = 40001
E_TOO_MANY_NODES = 40002
E_BAD_TIME_RANGE = 40003
E_TOO_MANY_POINTS = 40004
E_BAD_JSON = 40000

SAMPLE_MODES = ("interpolated", "raw", "avg", "max", "min")
DEFAULT_TARGET_POINTS = 360  # 未指定 interval 时，每个点大约返回这么多个样本

catalog = Catalog(settings.ontology_base_url)
_signals: dict[str, tuple[Signal, bool]] = {}
_stats = {"realtimeRequests": 0, "historyRequests": 0, "startedAt": int(time.time() * 1000)}


# --------------------------------------------------------------------- 工具


def now_ms() -> int:
    return int(time.time() * 1000)


def envelope(data: Any = None, code: int = OK, message: str = "success") -> JSONResponse:
    return JSONResponse({"code": code, "message": message, "data": data})


def fail(code: int, message: str) -> JSONResponse:
    return envelope(None, code, message)


async def read_json(request: Request) -> dict | None:
    try:
        body = await request.json()
    except Exception:
        return None
    return body if isinstance(body, dict) else None


def pick(body: dict, *names: str) -> Any:
    """兼容几种常见字段写法，真实格式未定时少踩坑。"""
    for name in names:
        if name in body and body[name] not in (None, ""):
            return body[name]
    return None


def signal_for(node_id: str) -> tuple[Signal | None, bool]:
    """返回 (信号, 是否来自点表)。严格模式下点表里没有的点返回 None。"""
    cached = _signals.get(node_id)
    if cached:
        return cached
    ref = parse_node_id(node_id)
    if ref is None:
        return None, False
    meta = catalog.lookup(ref)
    from_catalog = meta is not None
    if meta is None:
        if settings.strict_nodes:
            return None, False
        meta = catalog.guess(ref)
    signal = Signal(meta, classify(meta), settings.seed)
    # 点表还没加载好时不要缓存：否则这段时间按位号名推断出的画像会被永久固化，
    # 等点表加载完也不会再按真实单位/描述重算（本体服务比本服务晚起时就会踩到）
    if catalog.loaded:
        _signals[node_id] = (signal, from_catalog)
    return signal, from_catalog


def parse_time(value: Any, field: str) -> int:
    """支持毫秒时间戳、秒时间戳、"yyyy-MM-dd HH:mm:ss"、ISO 8601。"""
    if isinstance(value, bool):
        raise ValueError(f"{field} 不能是布尔值")
    if isinstance(value, (int, float)):
        number = int(value)
        return number * 1000 if number < 10_000_000_000 else number  # 10 位视为秒
    if isinstance(value, str):
        text = value.strip()
        if text.isdigit():
            return parse_time(int(text), field)
        tz = timezone(timedelta(hours=settings.tz_offset_hours))
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y/%m/%d %H:%M:%S"):
            try:
                return int(datetime.strptime(text, fmt).replace(tzinfo=tz).timestamp() * 1000)
            except ValueError:
                pass
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=tz)
            return int(parsed.timestamp() * 1000)
        except ValueError:
            pass
    raise ValueError(f"{field} 格式无法识别：{value!r}（支持毫秒时间戳或 yyyy-MM-dd HH:mm:ss）")


def validate_node_ids(body: dict) -> tuple[list[str] | None, JSONResponse | None]:
    node_ids = pick(body, "nodeIds", "nodeIdList", "ids")
    if not isinstance(node_ids, list) or not node_ids:
        return None, fail(E_BAD_PARAM, "nodeIds 必须是非空数组")
    if not all(isinstance(item, str) and item.strip() for item in node_ids):
        return None, fail(E_BAD_PARAM, "nodeIds 中每一项都必须是非空字符串")
    if len(node_ids) > settings.max_nodes_per_request:
        return None, fail(
            E_TOO_MANY_NODES, f"单次最多查询 {settings.max_nodes_per_request} 个点，本次 {len(node_ids)} 个"
        )
    return [item.strip() for item in node_ids], None


# --------------------------------------------------------------------- 实时值


async def rtdata_read(request: Request) -> JSONResponse:
    await run_in_threadpool(catalog.ensure_loaded)
    body = await read_json(request)
    if body is None:
        return fail(E_BAD_JSON, "请求体必须是 JSON 对象")
    node_ids, error = validate_node_ids(body)
    if error:
        return error

    _stats["realtimeRequests"] += 1
    st = now_ms()
    data = []
    for node_id in node_ids:
        signal, _ = signal_for(node_id)
        if signal is None:
            data.append({"nodeId": node_id, "st": st, "t": None, "q": 0, "v": None})
            continue
        sample = signal.realtime(st)
        data.append({"nodeId": node_id, "st": st, "t": sample.t, "q": sample.q, "v": sample.v})
    return envelope(data)


# --------------------------------------------------------------------- 历史值


async def history_find_all(request: Request) -> JSONResponse:
    await run_in_threadpool(catalog.ensure_loaded)
    body = await read_json(request)
    if body is None:
        return fail(E_BAD_JSON, "请求体必须是 JSON 对象")
    node_ids, error = validate_node_ids(body)
    if error:
        return error

    raw_start = pick(body, "startTime", "beginTime", "start")
    raw_end = pick(body, "endTime", "end")
    if raw_start is None:
        return fail(E_BAD_PARAM, "startTime 必填")
    try:
        start = parse_time(raw_start, "startTime")
        end = parse_time(raw_end, "endTime") if raw_end is not None else now_ms()
    except ValueError as exc:
        return fail(E_BAD_PARAM, str(exc))
    if start >= end:
        return fail(E_BAD_TIME_RANGE, "startTime 必须早于 endTime")

    mode = str(pick(body, "sampleMode", "mode", "type") or "interpolated").lower()
    if mode not in SAMPLE_MODES:
        return fail(E_BAD_PARAM, f"sampleMode 只能取 {', '.join(SAMPLE_MODES)}")

    limit_raw = pick(body, "limit", "maxCount")
    try:
        limit = int(limit_raw) if limit_raw is not None else settings.max_points_per_node
    except (TypeError, ValueError):
        return fail(E_BAD_PARAM, "limit 必须是整数")
    limit = max(1, min(limit, settings.max_points_per_node))

    # 历史只存在于过去：结束时间超过当前时刻就截到当前时刻
    current = now_ms()
    effective_end = min(end, current)

    interval_raw = pick(body, "interval", "step", "period")
    if mode != "raw":
        if interval_raw is None:
            span = max(0, effective_end - start)
            interval = max(1000, math.ceil(span / DEFAULT_TARGET_POINTS / 1000) * 1000)
        else:
            try:
                interval = int(interval_raw)
            except (TypeError, ValueError):
                return fail(E_BAD_PARAM, "interval 必须是整数毫秒")
            if interval < 1000:
                return fail(E_BAD_PARAM, "interval 不能小于 1000 毫秒")
        expected = (effective_end - start) // interval + 1 if effective_end >= start else 0
        if expected > limit:
            return fail(
                E_TOO_MANY_POINTS,
                f"每个点预计返回 {expected} 个样本，超过上限 {limit}。请加大 interval 或缩短时间范围。",
            )
    else:
        interval = None

    _stats["historyRequests"] += 1
    data = []
    for node_id in node_ids:
        signal, _ = signal_for(node_id)
        if signal is None:
            data.append({"nodeId": node_id, "count": 0, "values": [], "error": "节点不存在"})
            continue
        if effective_end < start:
            data.append({"nodeId": node_id, "count": 0, "values": []})
            continue

        has_more = False
        if mode == "raw":
            samples = signal.raw(start, effective_end, limit + 1)
            has_more = len(samples) > limit
            samples = samples[:limit]
        elif mode == "interpolated":
            samples = [signal.value_at(t) for t in range(start, effective_end + 1, interval)]
        else:
            samples = [
                signal.aggregate(t, min(t + interval, effective_end), mode)
                for t in range(start, effective_end + 1, interval)
            ]

        item: dict[str, Any] = {
            "nodeId": node_id,
            "count": len(samples),
            "values": [{"t": s.t, "q": s.q, "v": s.v} for s in samples],
        }
        if has_more:
            item["hasMore"] = True
        data.append(item)

    return envelope(data)


# --------------------------------------------------------------------- 调试接口


async def health(request: Request) -> JSONResponse:
    await run_in_threadpool(catalog.ensure_loaded)
    return JSONResponse(
        {
            "service": "6-APA 模拟 DCS 数据服务",
            "status": "ok",
            "simulated": True,
            "notice": "本服务返回的是按测点合理性生成的模拟数据，不是现场真实读数。",
            "framework": FRAMEWORK,
            "seed": settings.seed,
            "strictNodes": settings.strict_nodes,
            "catalog": catalog.status(),
            "limits": {
                "maxNodesPerRequest": settings.max_nodes_per_request,
                "maxPointsPerNode": settings.max_points_per_node,
            },
            "stats": _stats,
            "serverTime": now_ms(),
        }
    )


async def mock_nodes(request: Request) -> JSONResponse:
    await run_in_threadpool(catalog.ensure_loaded)
    query = request.query_params
    try:
        limit = max(1, min(500, int(query.get("limit") or 50)))
        offset = max(0, int(query.get("offset") or 0))
    except ValueError:
        limit, offset = 50, 0
    total, metas = catalog.search(query.get("keyword") or "", query.get("station") or "", limit, offset)
    items = []
    for meta in metas:
        profile = classify(meta)
        items.append(
            {
                "nodeId": node_id_of(meta),
                "description": meta.description,
                "equipment": meta.equipment,
                "unit": meta.unit,
                "parameterType": meta.parameter_type,
                "profile": profile.describe(),
            }
        )
    return envelope({"total": total, "items": items})


async def mock_profile(request: Request) -> JSONResponse:
    await run_in_threadpool(catalog.ensure_loaded)
    node_id = (request.query_params.get("nodeId") or "").strip()
    if not node_id:
        return fail(E_BAD_PARAM, "nodeId 必填")
    signal, from_catalog = signal_for(node_id)
    if signal is None:
        return fail(E_BAD_PARAM, f"节点不存在：{node_id}")
    meta = signal.meta
    return envelope(
        {
            "nodeId": node_id,
            "fromCatalog": from_catalog,
            "tag": {
                "station": meta.station,
                "name": meta.name,
                "description": meta.description,
                "unit": meta.unit,
                "parameterType": meta.parameter_type,
                "blockType": meta.block_type,
                "equipment": meta.equipment,
            },
            "profile": signal.profile.describe(),
            "deviceKey": signal.dev_key,
            "realtime": signal.realtime(now_ms()).__dict__,
        }
    )


# --------------------------------------------------------------------- 装配

ROUTES = [
    ("/api/hsm-db-rtserver/v1/rtdata/node/read", ["POST"], rtdata_read, "实时值读取"),
    ("/api/timing-svc/v1/history/findAll", ["POST"], history_find_all, "历史值查询"),
    ("/api/health", ["GET"], health, "健康检查"),
    ("/api/mock/nodes", ["GET"], mock_nodes, "查找测点"),
    ("/api/mock/profile", ["GET"], mock_profile, "测点模拟规则"),
]


def _build_fastapi():
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware

    app = FastAPI(title="6-APA 模拟 DCS 数据服务", version="1.0.0")
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
    for path, methods, handler, name in ROUTES:
        app.add_api_route(path, handler, methods=methods, name=name, summary=name)
    return app


def _build_starlette():
    from starlette.applications import Starlette
    from starlette.middleware import Middleware
    from starlette.middleware.cors import CORSMiddleware
    from starlette.routing import Route

    return Starlette(
        routes=[Route(path, handler, methods=methods, name=name) for path, methods, handler, name in ROUTES],
        middleware=[Middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])],
    )


try:  # pragma: no cover
    app = _build_fastapi()
    FRAMEWORK = "fastapi"
except ImportError:  # pragma: no cover
    app = _build_starlette()
    FRAMEWORK = "starlette"


def main() -> None:  # pragma: no cover
    import uvicorn

    logger.info("模拟 DCS 服务启动：port=%s 点表来源=%s", settings.port, settings.ontology_base_url)
    catalog.ensure_loaded()  # 启动时预热点表，首个请求不用等
    uvicorn.run(app, host=settings.host, port=settings.port)


if __name__ == "__main__":  # pragma: no cover
    main()
