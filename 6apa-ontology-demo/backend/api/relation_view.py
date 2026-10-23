"""独立关系展示页的挂载模块。

把 web/relations.html 挂到本体服务上，别的系统可以直接用 URL 打开或 iframe 嵌入：

    http://localhost:8700/relations?rootId=robj-fbcbed39&depth=2
    http://localhost:8700/relations?rootId=equip-8170434d&view=table&embed=1&theme=light

在 backend/main.py 创建 app 之后加一行即可：

    from backend.api.relation_view import mount as _mount_relation_view
    _mount_relation_view(app)

页面本身零依赖，也可以脱离服务直接双击打开（用 ?api=http://localhost:8700 指定本体地址）。

注意：本文件刻意不使用 `from __future__ import annotations`，
FastAPI 需要在运行时解析 endpoint 的 `request: Request` 注解。
"""
from pathlib import Path
from typing import Any

from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse

PAGE = Path(__file__).resolve().parents[2] / "web" / "relations.html"

# 页面支持的 URL 参数，供 /api/relation-view/params 自描述，方便集成方对接
PARAMS = [
    {"name": "rootId", "desc": "根对象 ID：robj- 关系对象 / equip- 设备 / param- 参数 / area- 工段，或 :Dev_13_水解罐A。不传则展示全局关系"},
    {"name": "rootType", "desc": "根节点类型提示：relationEntity / equipment / area"},
    {"name": "depth", "desc": "关系展开深度 1~3，默认 1"},
    {"name": "view", "desc": "graph 关系图（默认）/ table 关系明细表"},
    {"name": "area", "desc": "只看某工段的关系，如 水解工段"},
    {"name": "category", "desc": "只看某类关系，如 控制关系 / 影响关系"},
    {"name": "predicate", "desc": "只看某个谓词，如 正向影响"},
    {"name": "scenario", "desc": "只看某个场景，如 闭环调节"},
    {"name": "subjectType", "desc": "按主体对象类型过滤，如 生产设备"},
    {"name": "objectType", "desc": "按客体对象类型过滤"},
    {"name": "matched", "desc": "true 只看已匹配 DCS 实例的关系，false 只看未匹配"},
    {"name": "includeDcs", "desc": "true 时把匹配到的 DCS 设备实例也画进图里"},
    {"name": "keyword", "desc": "关系明细表内的关键词搜索"},
    {"name": "embed", "desc": "1 隐藏顶部工具栏，适合被 iframe 嵌入"},
    {"name": "theme", "desc": "dark（默认）/ light"},
    {"name": "title", "desc": "自定义页面标题"},
    {"name": "api", "desc": "本体服务地址；同源访问时不用填，作为本地文件打开时需要"},
]


def mount(app: Any) -> None:
    """把关系展示页挂到 /relations（同时保留 /relations.html）。"""

    async def page(request: Request):
        if not PAGE.is_file():
            return JSONResponse({"detail": f"页面文件缺失：{PAGE}"}, status_code=500)
        return FileResponse(PAGE, media_type="text/html; charset=utf-8")

    async def params(request: Request):
        return JSONResponse({"page": "/relations", "params": PARAMS})

    routes = [
        ("/relations", page, "关系展示页"),
        ("/relations.html", page, "关系展示页(别名)"),
        ("/api/relation-view/params", params, "关系展示页参数说明"),
    ]
    for path, endpoint, name in routes:
        if hasattr(app, "add_api_route"):  # FastAPI
            app.add_api_route(path, endpoint, methods=["GET"], name=name, summary=name, include_in_schema=False)
        else:  # Starlette 回退模式
            app.add_route(path, endpoint, methods=["GET"], name=name)
