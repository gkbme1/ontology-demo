"""实时值 / 历史值：本体作为语义网关访问实时库与历史库。

职责边界：
- 本体**不存储**任何实时值或历史值，也**不生成**任何数值；
- 本体只负责把"本体对象"（设备 / 参数 / DCS 点 / 关系对象 / 工段）解析成现场位号，
  按实时库的 nodeId 规则拼出 nodeId，调用外部实时库 / 历史库拿值，
  再把值和本体语义（设备、参数、单位、现场描述、数据来源）拼在一起返回。

外部接口（地址全部走环境变量，可直接切到真实实时库 / 时序库）：
    实时库  POST {RTDB_BASE_URL}{RTDB_REALTIME_PATH}      body: {"nodeIds": [...]}
    历史库  POST {HISTORIAN_BASE_URL}{HISTORIAN_PATH}     body: {"nodeIds": [...], "startTime", "endTime", ...}

只用标准库 urllib，不给本体服务新增依赖。
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any

# ------------------------------------------------------------------- 配置

RTDB_BASE_URL = os.environ.get("RTDB_BASE_URL", "http://localhost:8900").rstrip("/")
RTDB_REALTIME_PATH = os.environ.get("RTDB_REALTIME_PATH", "/api/hsm-db-rtserver/v1/rtdata/node/read")
HISTORIAN_BASE_URL = os.environ.get("HISTORIAN_BASE_URL", RTDB_BASE_URL).rstrip("/")
HISTORIAN_PATH = os.environ.get("HISTORIAN_PATH", "/api/timing-svc/v1/history/findAll")
# 本体 DCS 点 → 实时库 nodeId 的拼接规则；可用字段：station / name / id
NODE_ID_TEMPLATE = os.environ.get("RTDB_NODE_ID_TEMPLATE", "{station}:{name}.PV")
TIMEOUT = float(os.environ.get("RTDB_TIMEOUT", "15"))
MAX_TAGS = int(os.environ.get("RTDB_MAX_TAGS", "200"))  # 单次最多查询多少个 DCS 点
DEFAULT_TAGS = 50  # 对象下的点很多时，默认先取这么多
UPSTREAM_BATCH = 500  # 每次调用实时库 / 历史库最多带多少个 nodeId
TZ = timezone(timedelta(hours=int(os.environ.get("RTDB_TZ_OFFSET", "8"))))

SAMPLE_MODES = ("interpolated", "raw", "avg", "max", "min")


class ApiError(Exception):
    """带 HTTP 状态码的业务错误，由 main.py 统一转成 {"detail": ...} 响应。"""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


# ------------------------------------------------------------------- 工具


def node_id_for(tag: dict[str, Any]) -> str:
    return NODE_ID_TEMPLATE.format(station=tag.get("station") or "", name=tag.get("name") or "", id=tag.get("id"))


def fmt_time(ms: int | None) -> str | None:
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000, TZ).strftime("%Y-%m-%d %H:%M:%S")


def parse_time(value: Any, field: str) -> int:
    """毫秒 / 秒时间戳、"yyyy-MM-dd HH:mm:ss"、ISO 8601；字符串按东八区解析。"""
    text = str(value).strip()
    if text.lstrip("-").isdigit():
        number = int(text)
        return number * 1000 if abs(number) < 10_000_000_000 else number
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y/%m/%d %H:%M:%S"):
        try:
            return int(datetime.strptime(text, fmt).replace(tzinfo=TZ).timestamp() * 1000)
        except ValueError:
            pass
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=TZ)
        return int(parsed.timestamp() * 1000)
    except ValueError:
        raise ApiError(400, f"{field} 格式无法识别：{value!r}（支持毫秒时间戳或 yyyy-MM-dd HH:mm:ss）") from None


def _int(q: dict, key: str, default: int, lo: int, hi: int) -> int:
    raw = q.get(key)
    if raw in (None, ""):
        return default
    try:
        return max(lo, min(hi, int(raw)))
    except (TypeError, ValueError):
        raise ApiError(400, f"{key} 必须是整数") from None


def _post(url: str, body: dict[str, Any]) -> dict[str, Any]:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise ApiError(502, f"上游接口 {url} 返回 HTTP {exc.code}") from None
    except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
        reason = getattr(exc, "reason", exc)
        raise ApiError(502, f"无法连接上游接口 {url}：{reason}") from None
    except ValueError:
        raise ApiError(502, f"上游接口 {url} 返回的不是合法 JSON") from None
    if not isinstance(payload, dict):
        raise ApiError(502, f"上游接口 {url} 返回格式异常")
    if payload.get("code", 0) != 0:
        raise ApiError(502, f"上游接口返回错误 code={payload.get('code')}：{payload.get('message')}")
    return payload


# 上游是否为模拟服务：读它的 /api/health，缓存 60 秒。真实实时库没有这个接口时视为非模拟。
_sim_cache: dict[str, tuple[float, bool | None]] = {}
_sim_lock = threading.Lock()


def _upstream_simulated(base_url: str) -> bool | None:
    with _sim_lock:
        cached = _sim_cache.get(base_url)
        if cached and time.time() - cached[0] < 60:
            return cached[1]
    value: bool | None = None
    try:
        with urllib.request.urlopen(f"{base_url}/api/health", timeout=3) as response:
            value = bool(json.loads(response.read().decode("utf-8")).get("simulated", False))
    except Exception:
        value = None
    with _sim_lock:
        _sim_cache[base_url] = (time.time(), value)
    return value


def _data_source(kind: str) -> dict[str, Any]:
    base, path, label = (
        (RTDB_BASE_URL, RTDB_REALTIME_PATH, "实时库")
        if kind == "RTDB"
        else (HISTORIAN_BASE_URL, HISTORIAN_PATH, "历史库")
    )
    simulated = _upstream_simulated(base)
    source = {"sourceType": kind, "sourceTypeLabel": label, "endpoint": f"{base}{path}", "simulated": simulated}
    if simulated:
        source["notice"] = "当前接入的是模拟数据服务，数值按测点合理性生成，不是现场真实读数。"
    return source


# ------------------------------------------------------------------- 对象 → DCS 点


def _tag_semantics(tag: dict[str, Any]) -> dict[str, Any]:
    return {
        "tagId": tag["id"],
        "tagName": tag["name"],
        "nodeId": node_id_for(tag),
        "description": tag.get("rawDescription"),
        "unit": tag.get("unit"),
        "parameterType": tag.get("parameterType"),
        "blockType": tag.get("blockType"),
        "parameterId": tag.get("parameterId"),
        "parameterName": tag.get("parameterName"),
        "equipmentId": tag.get("equipmentId"),
        "equipmentName": tag.get("equipmentName"),
        "areaId": tag.get("areaId"),
        "areaName": tag.get("areaName"),
        "station": tag.get("station"),
    }


def _filter(tags: list[dict[str, Any]], q: dict) -> list[dict[str, Any]]:
    if q.get("type"):
        tags = [t for t in tags if t.get("parameterType") == q["type"]]
    if q.get("blockType"):
        tags = [t for t in tags if t.get("blockType") == q["blockType"]]
    if q.get("keyword"):
        kw = q["keyword"]
        tags = [t for t in tags if kw in (t.get("name") or "") or kw in (t.get("rawDescription") or "")]
    return tags


def resolve_object(store, object_id: str) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    """本体对象 → (scope 描述, DCS 点列表, 说明)。对象不存在抛 404。"""
    dcs = store.dcs
    notes: list[str] = []

    if object_id.startswith(":"):
        equip = dcs.equipment_by_owl(object_id)
        if not equip:
            raise ApiError(404, f"未找到对象：{object_id}")
        object_id = equip["id"]

    if object_id.startswith("tag-"):
        tag = dcs.tags.get(object_id)
        if not tag:
            raise ApiError(404, f"未找到对象：{object_id}")
        return {"objectId": object_id, "objectKind": "tag", "objectName": tag["name"]}, [tag], notes

    if object_id.startswith("param-"):
        param = dcs.parameters.get(object_id)
        if not param:
            raise ApiError(404, f"未找到对象：{object_id}")
        tags = [dcs.tags[t] for t in param["tagIds"] if t in dcs.tags]
        scope = {"objectId": object_id, "objectKind": "parameter", "objectName": param["name"],
                 "equipmentName": param["equipmentName"]}
        return scope, tags, notes

    if object_id.startswith("equip-"):
        equip = dcs.equipment.get(object_id)
        if not equip:
            raise ApiError(404, f"未找到对象：{object_id}")
        tags = [dcs.tags[t] for t in equip["tagIds"] if t in dcs.tags]
        scope = {"objectId": equip["id"], "objectKind": "equipment", "objectName": equip["name"],
                 "owlSubject": equip.get("owlSubject"), "areaName": equip.get("areaName")}
        return scope, tags, notes

    if object_id.startswith("area-"):
        area = next((a for a in store.areas() if a["id"] == object_id), None)
        if not area:
            raise ApiError(404, f"未找到对象：{object_id}")
        tags = [t for t in dcs.tags.values() if t.get("areaId") == object_id]
        return {"objectId": object_id, "objectKind": "area", "objectName": area["name"]}, tags, notes

    if object_id.startswith("robj-"):
        entity = store.relations.entities.get(object_id)
        if not entity:
            raise ApiError(404, f"未找到对象：{object_id}")
        match = entity["match"]
        seen: set[str] = set()
        tags = []
        for m in match["matches"]:
            if m["objectType"] == "parameter":
                ids = (dcs.parameters.get(m["id"]) or {}).get("tagIds", [])
            elif m["objectType"] == "equipment":
                ids = (dcs.equipment.get(m["id"]) or {}).get("tagIds", [])
            else:
                ids = []
            for tid in ids:
                if tid in dcs.tags and tid not in seen:
                    seen.add(tid)
                    tags.append(dcs.tags[tid])
        brief = store.entity_brief(entity)
        scope = {"objectId": object_id, "objectKind": "relationEntity", "objectName": entity["name"],
                 "objectType": entity["type"], "matchStatus": brief.get("matchStatus")}
        if not tags:
            notes.append("该关系对象在 DCS 点表中没有匹配到测点（未匹配 DCS 实例），无法查询实时 / 历史值。")
        elif brief.get("pendingConfirmation"):
            notes.append("该关系对象到现场测点的对应来自人工映射表，映射条目「待现场确认」。")
        return scope, tags, notes

    raise ApiError(404, f"未找到对象：{object_id}（支持 equip- / param- / tag- / robj- / area- 前缀或 :Dev_ 形式的 OWL Subject）")


def resolve_query(store, q: dict) -> tuple[dict[str, Any] | None, list[dict[str, Any]], list[str]]:
    """集合接口：按 tagIds / equipmentId / parameterId / areaId / keyword 选点。"""
    dcs = store.dcs
    tag_ids = [t.strip() for t in (q.get("tagIds") or "").split(",") if t.strip()]
    if tag_ids:
        missing = [t for t in tag_ids if t not in dcs.tags]
        if missing:
            raise ApiError(404, f"未找到 DCS 点：{', '.join(missing[:10])}")
        return None, [dcs.tags[t] for t in tag_ids], []

    scope_filters = ("equipmentId", "parameterId", "areaId", "keyword")
    if not any(q.get(k) for k in scope_filters):
        raise ApiError(400, "请至少提供 tagIds / equipmentId / parameterId / areaId / keyword 之一，避免一次查询全厂测点")
    result = store.tags(
        equipment_id=q.get("equipmentId") or None,
        parameter_id=q.get("parameterId") or None,
        area_id=q.get("areaId") or None,
        parameter_type=q.get("type") or None,
        block_type=q.get("blockType") or None,
        keyword=q.get("keyword") or None,
    )
    return None, result["items"], []


def _select(store, q: dict, object_id: str | None):
    if object_id is not None:
        scope, tags, notes = resolve_object(store, object_id)
        tags = _filter(tags, q)
    else:
        scope, tags, notes = resolve_query(store, q)
    # 备用点（未接线）排到最后，默认返回的前 N 个点才有看头；其余顺序保持点表原样
    tags = sorted(tags, key=lambda t: (t.get("rawDescription") or "").strip().startswith("备用"))
    total = len(tags)
    limit = _int(q, "limit", DEFAULT_TAGS, 1, MAX_TAGS)
    offset = _int(q, "offset", 0, 0, 10**9)
    window = tags[offset : offset + limit]
    if total > offset + len(window):
        notes.append(
            f"共 {total} 个 DCS 点，本次返回第 {offset + 1}~{offset + len(window)} 个；"
            "可用 limit / offset 翻页，或用 type / blockType / keyword 缩小范围。"
        )
    return scope, window, total, offset, notes


def _batched(items: list[str]):
    for i in range(0, len(items), UPSTREAM_BATCH):
        yield items[i : i + UPSTREAM_BATCH]


# ------------------------------------------------------------------- 实时值


def realtime(store, q: dict, object_id: str | None = None) -> dict[str, Any]:
    scope, tags, total, offset, notes = _select(store, q, object_id)
    node_ids = [node_id_for(t) for t in tags]
    values: dict[str, dict[str, Any]] = {}
    server_time = None
    url = f"{RTDB_BASE_URL}{RTDB_REALTIME_PATH}"
    for batch in _batched(node_ids):
        payload = _post(url, {"nodeIds": batch})
        for item in payload.get("data") or []:
            values[item.get("nodeId")] = item
            server_time = item.get("st") or server_time

    items = []
    for tag, node_id in zip(tags, node_ids):
        item = values.get(node_id) or {}
        quality = item.get("q")
        items.append(
            {
                **_tag_semantics(tag),
                "value": item.get("v"),
                "quality": quality,
                "qualityLabel": {1: "好", 0: "坏"}.get(quality, "无数据" if not item else str(quality)),
                "timestamp": item.get("t"),
                "timeText": fmt_time(item.get("t")),
            }
        )
    return {
        "scope": scope,
        "total": total,
        "offset": offset,
        "returned": len(items),
        "serverTime": server_time,
        "serverTimeText": fmt_time(server_time),
        "items": items,
        "dataSource": _data_source("RTDB"),
        "notes": notes,
    }


# ------------------------------------------------------------------- 历史值


def _series_stats(values: list[dict[str, Any]]) -> dict[str, Any] | None:
    good = [v for v in values if v.get("q") == 1 and isinstance(v.get("v"), (int, float))]
    if not good:
        return None
    nums = [v["v"] for v in good]
    return {
        "min": min(nums),
        "max": max(nums),
        "avg": round(sum(nums) / len(nums), 4),
        "first": good[0]["v"],
        "last": good[-1]["v"],
        "goodCount": len(good),
    }


def history(store, q: dict, object_id: str | None = None) -> dict[str, Any]:
    if not q.get("startTime"):
        raise ApiError(400, "startTime 必填（毫秒时间戳或 yyyy-MM-dd HH:mm:ss）")
    start = parse_time(q["startTime"], "startTime")
    end = parse_time(q["endTime"], "endTime") if q.get("endTime") else int(time.time() * 1000)
    if start >= end:
        raise ApiError(400, "startTime 必须早于 endTime")
    mode = (q.get("sampleMode") or "interpolated").lower()
    if mode not in SAMPLE_MODES:
        raise ApiError(400, f"sampleMode 只能取 {', '.join(SAMPLE_MODES)}")

    scope, tags, total, offset, notes = _select(store, q, object_id)
    node_ids = [node_id_for(t) for t in tags]

    body: dict[str, Any] = {"startTime": start, "endTime": end, "sampleMode": mode}
    if q.get("interval"):
        body["interval"] = _int(q, "interval", 60_000, 1000, 86_400_000 * 30)
    if q.get("maxPoints"):
        body["limit"] = _int(q, "maxPoints", 10_000, 1, 10_000_000)

    series: dict[str, dict[str, Any]] = {}
    url = f"{HISTORIAN_BASE_URL}{HISTORIAN_PATH}"
    for batch in _batched(node_ids):
        payload = _post(url, {**body, "nodeIds": batch})
        for item in payload.get("data") or []:
            series[item.get("nodeId")] = item

    items = []
    for tag, node_id in zip(tags, node_ids):
        item = series.get(node_id) or {}
        values = item.get("values") or []
        entry = {
            **_tag_semantics(tag),
            "count": len(values),
            "values": values,
            "stats": _series_stats(values),
        }
        if item.get("hasMore"):
            entry["hasMore"] = True
        if item.get("error"):
            entry["error"] = item["error"]
        items.append(entry)

    return {
        "scope": scope,
        "startTime": start,
        "endTime": end,
        "startTimeText": fmt_time(start),
        "endTimeText": fmt_time(end),
        "interval": body.get("interval"),
        "sampleMode": mode,
        "total": total,
        "offset": offset,
        "returned": len(items),
        "items": items,
        "dataSource": _data_source("HISTORIAN"),
        "notes": notes,
    }


# ------------------------------------------------------------------- 状态 / 数据源登记


def status() -> dict[str, Any]:
    out = {}
    for kind, base in (("RTDB", RTDB_BASE_URL), ("HISTORIAN", HISTORIAN_BASE_URL)):
        reachable = True
        try:
            urllib.request.urlopen(f"{base}/api/health", timeout=3).close()
        except urllib.error.HTTPError:
            reachable = True  # 有响应即可达，真实实时库可能没有 /api/health
        except Exception:
            reachable = False
        out[kind] = {**_data_source(kind), "reachable": reachable}
    return {"nodeIdTemplate": NODE_ID_TEMPLATE, "maxTagsPerQuery": MAX_TAGS, "upstreams": out}
