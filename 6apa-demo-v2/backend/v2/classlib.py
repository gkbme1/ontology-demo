"""开发态类库（需求 4.2，ONTO-SR-SW-001～015）：可编辑。

数据：data/seed/classlib.json（由 105 车间实例归纳生成，`python3 -m backend.tools.build_classlib`）→ data/store/classlib.json（在线编辑）。
内容：元类（元模型）、层级类型与层级模板、类（类树，单继承，抽象类）及其属性 / 参数模板 / 约束模板 / 现象与工况模板 /
根因模板 / 工艺影响模板 / 挂载能力、关系类型、映射规则、能力、类库版本。

- 继承：类的「生效视图」= 祖先类（从根到父）逐层合并 + 本类（同编码覆盖），每条标出来源（本类 / 继承：某类 / 覆盖：某类）；
- 版本：当前版本「编辑中」可改；发布后只读，修改须「基于已发布版本新建版本」；任意两版可对比；
- 开发态修改同步到工程态（类库更新 → 实例）不做（用户确认）。
"""
from __future__ import annotations

import copy
import json
import os
import re
import shutil
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SEED = ROOT / "data" / "seed" / "classlib.json"
PARTS = {"attrs": "属性", "params": "参数模板", "constraints": "约束模板", "phenomena": "现象 / 工况模板",
         "causes": "根因模板", "influences": "工艺影响模板"}
SECTIONS = {"metaclasses": "元类", "hierarchyTypes": "层级类型", "hierarchyTemplates": "层级模板", "relationTypes": "关系类型",
            "mappingRules": "映射规则", "capabilities": "能力"}
TABS = ["图纸位置与外观", "参数", "参数约束", "拓扑关系", "现象/工况定义", "根因影响关系", "工艺影响关系", "计算组态", "处置规程"]
DTYPES = ["文本", "整数", "实数", "布尔", "日期", "枚举", "对象引用", "列表"]
PARAM_CATS = ["测量值", "设定值", "阀位", "控制指令", "状态", "计算值", "设计值"]
CONS_TYPES = ["工艺限值", "安全限值", "设备限值", "质量限值"]
CONS_SOURCES = ["模板默认值", "取 XBase 报警限", "逻辑约束"]
STATUSES = ["草案", "生效", "停用"]


class ClassLibError(ValueError):
    pass


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


class ClassLibrary:
    def __init__(self) -> None:
        self.path = Path(os.environ.get("V2_STORE_DIR") or ROOT / "data" / "store") / "classlib.json"
        self._lock = threading.RLock()
        self.reload()

    # ---------------------------------------------------------- 持久化
    def reload(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if not self.path.exists():
                if not SEED.exists():
                    raise FileNotFoundError(f"缺少类库种子 {SEED}，先运行 python3 -m backend.tools.build_classlib")
                shutil.copyfile(SEED, self.path)
            self.data = json.loads(self.path.read_text("utf-8"))
            for v in self.data["versions"]:
                if v["status"] == "已发布" and not v.get("snapshot"):
                    v["snapshot"] = copy.deepcopy(self._content())

    def reset(self) -> None:
        with self._lock:
            shutil.copyfile(SEED, self.path)
            self.reload()

    def save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), "utf-8")
        tmp.replace(self.path)

    # ---------------------------------------------------------- 版本
    @property
    def current(self) -> dict[str, Any]:
        return self.data["versions"][-1]

    def editable(self) -> None:
        if self.current["status"] != "编辑中":
            raise ClassLibError(f"类库 {self.current['version']} 已发布，只读；请先「基于 {self.current['version']} 新建版本」再修改")

    def _content(self) -> dict[str, Any]:
        return {k: self.data[k] for k in ("metaclasses", "hierarchyTypes", "hierarchyTemplates", "classes", "relationTypes",
                                          "mappingRules", "capabilities")}

    def summary(self) -> dict[str, Any]:
        d = self.data
        return {"library": d["library"], "current": {k: v for k, v in self.current.items() if k != "snapshot"},
                "versions": [{k: v for k, v in x.items() if k != "snapshot"} for x in reversed(d["versions"])],
                "counts": {"metaclasses": len(d["metaclasses"]), "classes": len(d["classes"]), "relationTypes": len(d["relationTypes"]),
                           "mappingRules": len(d["mappingRules"]), "capabilities": len(d["capabilities"]),
                           "hierarchyTypes": len(d["hierarchyTypes"]), "hierarchyTemplates": len(d["hierarchyTemplates"])},
                "enums": {"dtypes": DTYPES, "paramCats": PARAM_CATS, "consTypes": CONS_TYPES, "consSources": CONS_SOURCES,
                          "statuses": STATUSES, "tabs": TABS}}

    def publish(self, note: str) -> dict[str, Any]:
        with self._lock:
            self.editable()
            v = self.current
            v.update(status="已发布", publishedAt=now(), note=note or v.get("note") or "", snapshot=copy.deepcopy(self._content()))
            self.save()
            return {k: x for k, x in v.items() if k != "snapshot"}

    def new_version(self, base: str | None = None) -> dict[str, Any]:
        with self._lock:
            if self.current["status"] == "编辑中":
                raise ClassLibError(f"{self.current['version']} 仍在编辑中，发布后才能新建版本")
            base_v = next((x for x in self.data["versions"] if x["version"] == (base or self.current["version"])), None)
            if not base_v or not base_v.get("snapshot"):
                raise ClassLibError(f"版本 {base} 不存在或没有快照")
            m = re.match(r"v(\d+)\.(\d+)", self.current["version"])
            nv = f"v{m.group(1)}.{int(m.group(2)) + 1}" if m else self.current["version"] + "+1"
            for k, val in copy.deepcopy(base_v["snapshot"]).items():
                self.data[k] = val
            for x in self.data["versions"]:
                if x["status"] == "已发布" and x["version"] != base_v["version"]:
                    pass
            self.data["versions"].append({"version": nv, "status": "编辑中", "createdAt": now(), "base": base_v["version"], "note": ""})
            self.save()
            return {"version": nv, "base": base_v["version"]}

    def version_content(self, version: str) -> dict[str, Any]:
        if version == "current":
            return self._content()
        v = next((x for x in self.data["versions"] if x["version"] == version), None)
        if not v:
            raise LookupError(version)
        return v.get("snapshot") or self._content()

    def diff(self, a: str, b: str) -> dict[str, Any]:
        """a → b：按对象类型列出新增 / 修改 / 删除（类展开到各模板条目）。"""
        def flatten(c: dict[str, Any]) -> dict[tuple[str, str], tuple[str, dict]]:
            out: dict[tuple[str, str], tuple[str, dict]] = {}
            for sec, label in SECTIONS.items():
                for x in c.get(sec) or []:
                    out[(label, x["code"])] = (x.get("name") or x["code"], x)
            for cls in c.get("classes") or []:
                base = {k: v for k, v in cls.items() if k not in PARTS and k not in ("caps", "updatedAt", "createdAt")}  # 时间戳不算变更
                out[("类", cls["id"])] = (cls["name"], {**base, "caps": cls.get("caps")})
                for part, label in PARTS.items():
                    for x in cls.get(part) or []:
                        out[(label, f"{cls['id']}/{x['code']}")] = (f"{cls['name']} › {x.get('name') or x['code']}", x)
            return out
        A, B = flatten(self.version_content(a)), flatten(self.version_content(b))
        rows = []
        for k in B:
            if k not in A:
                rows.append({"change": "新增", "type": k[0], "id": k[1], "name": B[k][0], "detail": ""})
            elif A[k][1] != B[k][1]:
                ch = [f for f in sorted(set(A[k][1]) | set(B[k][1])) if A[k][1].get(f) != B[k][1].get(f)]
                rows.append({"change": "修改", "type": k[0], "id": k[1], "name": B[k][0],
                             "detail": "；".join(f"{f}：{_short(A[k][1].get(f))} → {_short(B[k][1].get(f))}" for f in ch[:3])})
        for k in A:
            if k not in B:
                rows.append({"change": "删除", "type": k[0], "id": k[1], "name": A[k][0], "detail": ""})
        order = {"新增": 0, "修改": 1, "删除": 2}
        rows.sort(key=lambda r: (order[r["change"]], r["type"], r["id"]))
        return {"from": a, "to": b, "rows": rows, "counts": {c: sum(1 for r in rows if r["change"] == c) for c in order}}

    # ---------------------------------------------------------- 通用小节（元类、层级、关系类型、映射规则、能力）
    def section(self, sec: str) -> list[dict[str, Any]]:
        if sec not in SECTIONS:
            raise LookupError(sec)
        return self.data[sec]

    def upsert(self, sec: str, code: str, body: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self.editable()
            items = self.section(sec)
            body = {**body, "code": (body.get("code") or code).strip()}
            if not body["code"] or not str(body.get("name") or "").strip():
                raise ClassLibError("编码和名称不能为空")
            old = next((x for x in items if x["code"] == code), None)
            if body["code"] != code and any(x["code"] == body["code"] for x in items):
                raise ClassLibError(f"编码已存在：{body['code']}")
            if sec == "metaclasses" and old and old.get("preset"):
                body["preset"] = True  # 预置元类可改属性，不可删
            if sec == "relationTypes" and old and old.get("preset"):
                body["preset"] = True
            if sec == "mappingRules" and body.get("pattern"):
                try:
                    re.compile(body["pattern"])
                except re.error as exc:
                    raise ClassLibError(f"匹配表达式不合法：{exc}") from None
            if old:
                items[items.index(old)] = {**old, **body}
            else:
                body.setdefault("preset", False)
                items.append(body)
            self.save()
            return next(x for x in items if x["code"] == body["code"])

    def delete(self, sec: str, code: str) -> dict[str, Any]:
        with self._lock:
            self.editable()
            items = self.section(sec)
            old = next((x for x in items if x["code"] == code), None)
            if not old:
                raise LookupError(code)
            if old.get("preset") and sec in ("metaclasses", "relationTypes"):
                raise ClassLibError(f"预置{SECTIONS[sec]}不可删除")
            if sec == "metaclasses":
                refs = [c["name"] for c in self.data["classes"] if c.get("metaclass") == code]
                if refs:
                    raise ClassLibError(f"有类引用该元类，不能删除：{'、'.join(refs[:5])}")
            if sec == "hierarchyTypes":
                refs = [t["name"] for t in self.data["hierarchyTemplates"] if code in (t.get("levels") or [])]
                if refs:
                    raise ClassLibError(f"层级模板引用了该层级类型：{'、'.join(refs)}")
            if sec == "capabilities":
                for c in self.data["classes"]:
                    if code in (c.get("caps") or []):
                        c["caps"].remove(code)
            items.remove(old)
            self.save()
            return old

    # ---------------------------------------------------------- 类
    def cls(self, cid: str) -> dict[str, Any]:
        c = next((x for x in self.data["classes"] if x["id"] == cid), None)
        if not c:
            raise LookupError(cid)
        return c

    def chain(self, cid: str) -> list[dict[str, Any]]:
        out, seen = [], set()
        c: dict[str, Any] | None = self.cls(cid)
        while c and c["id"] not in seen:
            seen.add(c["id"])
            out.insert(0, c)
            c = self.cls(c["parent"]) if c.get("parent") else None
        return out

    def effective(self, cid: str, part: str) -> list[dict[str, Any]]:
        merged: dict[str, dict[str, Any]] = {}
        chain = self.chain(cid)
        for c in chain:
            own = c["id"] == cid
            for x in c.get(part) or []:
                prev = merged.get(x["code"])
                src = "本类" if own and not prev else (f"覆盖：{prev['_srcName']}" if prev and own else f"继承：{c['name']}")
                merged[x["code"]] = {**x, "_src": src, "_srcName": c["name"], "_own": own}
        return list(merged.values())

    def tree(self, instance_counts: dict[str, dict[str, int]]) -> list[dict[str, Any]]:
        kids: dict[str | None, list[dict[str, Any]]] = {}
        for c in self.data["classes"]:
            kids.setdefault(c.get("parent"), []).append(c)

        def node(c: dict[str, Any]) -> dict[str, Any]:
            ch = [node(k) for k in sorted(kids.get(c["id"], []), key=lambda k: k.get("order", 99))]
            own = instance_counts.get(c["id"], {})
            return {"id": c["id"], "name": c["name"], "code": c["code"], "abstract": c.get("abstract"), "status": c.get("status"),
                    "metaclass": c.get("metaclass"), "children": ch,
                    "instances": own.get("instances", 0) + sum(k["instances"] for k in ch)}
        return [node(c) for c in sorted(kids.get(None, []), key=lambda k: k.get("order", 99))]

    def upsert_class(self, cid: str | None, body: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self.editable()
            name = str(body.get("name") or "").strip()
            code = str(body.get("code") or "").strip()
            if not name or not code:
                raise ClassLibError("类编码和类名称不能为空")
            if any(c["code"] == code and c["id"] != cid for c in self.data["classes"]):
                raise ClassLibError(f"类编码已存在：{code}")
            parent = body.get("parent") or None
            if parent:
                self.cls(parent)
                if cid and cid in [c["id"] for c in self.chain(parent)]:
                    raise ClassLibError("父类不能是本类或本类的子类（单继承、不能成环）")
            if not any(m["code"] == body.get("metaclass") for m in self.data["metaclasses"]):
                raise ClassLibError("所属元类不存在")
            fields = ("code", "name", "metaclass", "parent", "abstract", "status", "icon", "desc", "tabs")
            if cid:
                c = self.cls(cid)
                c.update({k: body[k] for k in fields if k in body})
                c["parent"] = parent
            else:
                cid = "cls-" + re.sub(r"[^A-Za-z0-9-]", "", code).lower()
                if any(x["id"] == cid for x in self.data["classes"]):
                    cid += f"-{len(self.data['classes'])}"
                c = {"id": cid, **{k: body.get(k) for k in fields}, "parent": parent, "status": body.get("status") or "草案",
                     "attrs": [], "params": [], "constraints": [], "phenomena": [], "causes": [], "influences": [], "caps": [],
                     "createdAt": now()}
                self.data["classes"].append(c)
            c["updatedAt"] = now()
            self.save()
            return c

    def delete_class(self, cid: str, instances: int) -> dict[str, Any]:
        with self._lock:
            self.editable()
            c = self.cls(cid)
            kids = [x["name"] for x in self.data["classes"] if x.get("parent") == cid]
            if kids:
                raise ClassLibError(f"存在子类，不能删除：{'、'.join(kids[:6])}")
            if instances:
                raise ClassLibError(f"存在 {instances} 个实例，不能删除")
            self.data["classes"].remove(c)
            self.save()
            return c

    def upsert_item(self, cid: str, part: str, code: str, body: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self.editable()
            if part not in PARTS:
                raise LookupError(part)
            c = self.cls(cid)
            items = c.setdefault(part, [])
            body = {k: v for k, v in body.items() if not k.startswith("_")}
            body["code"] = (body.get("code") or code).strip()
            if not body["code"]:
                raise ClassLibError("编码不能为空")
            if part in ("attrs", "params", "phenomena") and not str(body.get("name") or "").strip():
                raise ClassLibError("名称不能为空")
            if part == "attrs":
                inherited = next((x for x in self.effective(cid, "attrs") if x["code"] == body["code"] and not x["_own"]), None)
                if inherited and body.get("dtype") and body["dtype"] != inherited.get("dtype"):
                    raise ClassLibError(f"属性 {body['code']} 继承自「{inherited['_srcName']}」，子类不可修改数据类型（{inherited.get('dtype')}）")
            if part == "constraints":
                vals = [body.get(k) for k in ("ll", "l", "nl", "nh", "h", "hh") if body.get(k) not in (None, "")]
                try:
                    vals = [float(v) for v in vals]
                except (TypeError, ValueError):
                    raise ClassLibError("限值要填数字") from None
                if vals != sorted(vals):
                    raise ClassLibError("限值要满足 低低 ≤ 低 ≤ 正常下 ≤ 正常上 ≤ 高 ≤ 高高")
                if body.get("source") == "逻辑约束" and not str(body.get("expr") or "").strip():
                    raise ClassLibError("逻辑约束要填写表达式，如 P_OUT > P_IN")
            if part == "causes":
                names = {p["name"] for p in self.effective(cid, "phenomena")}
                if body.get("cause") == body.get("effect"):
                    raise ClassLibError("原因和结果不能是同一个现象模板")
                if body.get("effect") not in names and body.get("cause") not in names:
                    raise ClassLibError("原因或结果至少有一个是本类（含继承）的现象模板")
            old = next((x for x in items if x["code"] == code), None)
            if old and body["code"] != code and any(x["code"] == body["code"] for x in items):
                raise ClassLibError(f"编码已存在：{body['code']}")
            if old:
                items[items.index(old)] = body
            else:
                if any(x["code"] == body["code"] for x in items):
                    raise ClassLibError(f"编码已存在：{body['code']}")
                items.append(body)
            c["updatedAt"] = now()
            self.save()
            return body

    def delete_item(self, cid: str, part: str, code: str) -> dict[str, Any]:
        with self._lock:
            self.editable()
            c = self.cls(cid)
            old = next((x for x in c.get(part) or [] if x["code"] == code), None)
            if not old:
                inherited = next((x for x in self.effective(cid, part) if x["code"] == code), None)
                raise ClassLibError(f"「{code}」继承自「{inherited['_srcName']}」，请在父类中删除，或在本类覆盖" if inherited else f"未找到 {code}")
            c[part].remove(old)
            self.save()
            return old

    def set_caps(self, cid: str, caps: list[str]) -> list[str]:
        with self._lock:
            self.editable()
            known = {x["code"] for x in self.data["capabilities"]}
            bad = [x for x in caps if x not in known]
            if bad:
                raise ClassLibError(f"能力不存在：{'、'.join(bad)}")
            self.cls(cid)["caps"] = caps
            self.save()
            return caps


# ------------------------------------------------------------------ 工程绑定的类库版本（演示：只看、不实际切换）
PART_LABELS = set(PARTS.values())
CONFLICT_TYPES = {"约束模板", "现象 / 工况模板", "根因模板"}


def binding(lib: ClassLibrary, project: str = "105车间") -> dict[str, Any]:
    """工程使用的类库版本：工程实例由 v0.1 归纳而来，固定绑定首个已发布版本（library.boundVersion 可指定）。
    类库发布只是升版，不会自动更新工程；工程在「发布与导出 · 类库版本」里手动切换（本 Demo 确认后不改数据）。"""
    vs = lib.data["versions"]
    bound = lib.data["library"].get("boundVersion") or next((v["version"] for v in vs if v["status"] == "已发布"), vs[0]["version"])
    idx = next((i for i, v in enumerate(vs) if v["version"] == bound), 0)
    strip = lambda v: {k: x for k, x in v.items() if k != "snapshot"}  # noqa: E731
    published = [strip(v) for v in vs if v["status"] == "已发布"]
    return {"project": project, "library": lib.data["library"]["name"], "bound": strip(vs[idx]),
            "newer": [strip(v) for v in vs[idx + 1:] if v["status"] == "已发布"],
            "published": published, "editing": next((strip(v) for v in vs if v["status"] == "编辑中"), None)}


def upgrade_impact(lib: ClassLibrary, to: str, instances_of: Any) -> dict[str, Any]:
    """升级影响分析（需求图 4-17）：工程绑定版本 → 目标版本的差异，按「可自动同步 / 冲突 / 需人工处理」分组，并列出受影响的实例。
    instances_of(cls) → 该类的直接实例（设备组）；抽象类的修改影响全部子类的实例。"""
    b = binding(lib)
    frm = b["bound"]["version"]
    if to == frm:
        raise ClassLibError("目标版本就是工程当前使用的版本")
    target = next((v for v in lib.data["versions"] if v["version"] == to), None)
    if not target or target["status"] != "已发布":
        raise ClassLibError("只能切换到已发布的类库版本")
    d = lib.diff(frm, to)
    classes = {c["id"]: c for c in lib.version_content(to)["classes"]} | {c["id"]: c for c in lib.version_content(frm)["classes"]}
    kids: dict[str, list[str]] = {}
    for c in classes.values():
        if c.get("parent"):
            kids.setdefault(c["parent"], []).append(c["id"])

    def insts(cid: str) -> list[dict[str, Any]]:
        out, stack = [], [cid]
        while stack:
            x = stack.pop()
            if x in classes:
                out += instances_of(classes[x])
            stack += kids.get(x, [])
        return out

    groups: dict[str, list[dict[str, Any]]] = {"auto": [], "conflict": [], "manual": []}
    affected: set[str] = set()
    for r in d["rows"]:
        cid = r["id"] if r["type"] == "类" else r["id"].split("/")[0] if r["type"] in PART_LABELS else None
        inst = insts(cid) if cid else []
        row = {**r, "className": classes.get(cid, {}).get("name") if cid else None,
               "instances": [{"id": i["id"], "name": i["name"], "members": i["members"]} for i in inst[:6]],
               "instanceCount": len(inst), "memberCount": sum(i["members"] for i in inst), "options": []}
        if not cid:
            g, row["reason"] = "auto", "全局定义变化（元模型 / 层级 / 关系类型 / 映射规则 / 能力），不直接改动实例数据"
        elif not inst:
            g, row["reason"] = "auto", "该类在本工程没有实例，不影响现有数据"
        elif r["change"] == "新增":
            g, row["reason"] = "auto", "新增项，本工程该类的实例将获得此项"
        elif r["change"] == "删除":
            g, row["reason"] = "manual", "类库删除了该项，本工程实例仍在使用"
            row["options"] = ["保留为本工程自有", "一并删除"]
        elif r["type"] == "属性" and "dtype" in (r.get("detail") or ""):
            g, row["reason"] = "manual", "属性数据类型变化，已有实例值需人工转换"
            row["options"] = ["人工确认后转换", "暂不升级此项"]
        elif r["type"] in CONFLICT_TYPES:
            g, row["reason"] = "conflict", "工程态可能已在设备组 / 设备上覆盖或调整，需选择保留哪一边"
            row["options"] = ["保留工程值", "采用类库值"]
        else:
            g, row["reason"] = "auto", "实例未单独覆盖时直接同步"
        if g != "auto" or cid:
            affected |= {i["id"] for i in inst}
        groups[g].append(row)
    return {"project": b["project"], "from": frm, "to": to, "groups": groups,
            "counts": {k: len(v) for k, v in groups.items()}, "affectedGroups": len(affected), "diffCounts": d["counts"]}


def _short(v: Any) -> str:
    s = json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else str(v)
    return s if len(s) <= 40 else s[:38] + "…"


# ------------------------------------------------------------------ 测试工具
def tag_match(template: dict[str, Any], tag: str, desc: str) -> dict[str, Any]:
    """参数模板的位号匹配试验：功能字母（位号前缀）+ 描述关键字。"""
    rule = template.get("tagRule") or {}
    funcs = [f.strip().upper() for f in re.split(r"[|/、,，\s]+", rule.get("funcs") or "") if f.strip()]
    kws = [k.strip() for k in re.split(r"[|/、,，\s]+", rule.get("keywords") or "") if k.strip()]
    prefix = re.match(r"[A-Za-z]+", tag or "")
    prefix = prefix.group(0).upper() if prefix else ""
    f_ok = bool(funcs) and prefix in funcs
    k_hit = [k for k in kws if k in (desc or "")]
    conf = round((0.55 if f_ok else 0) + (0.4 if k_hit else 0) + (0.04 if f_ok and len(k_hit) == len(kws) else 0), 2)
    dims = []
    for d in template.get("dims") or []:
        hit = next((v for v in d.get("values") or [] if v and v in (desc or "")), None)
        dims.append({"name": d.get("name"), "value": hit})
    return {"tag": tag, "desc": desc, "prefix": prefix, "funcOk": f_ok, "keywords": k_hit, "keywordsAll": kws, "funcs": funcs,
            "dims": dims, "confidence": conf, "matched": conf >= 0.55}


def run_mapping(rule: dict[str, Any], samples: list[dict[str, Any]], func_map: dict[str, str]) -> list[dict[str, Any]]:
    out = []
    try:
        rx = re.compile(rule.get("pattern") or "^$")
    except re.error as exc:
        raise ClassLibError(f"匹配表达式不合法：{exc}") from None
    segs = rule.get("segments") or []
    for s in samples:
        m = rx.match(s.get("tag") or "")
        if not m:
            out.append({**s, "matched": False, "parsed": [], "confidence": None})
            continue
        groups = list(m.groups())
        parsed = []
        for i, g in enumerate(groups):
            label = segs[i] if i < len(segs) else f"${i + 1}"
            meaning = func_map.get(g or "", "") if "功能" in label else ""
            parsed.append({"label": label, "value": g, "meaning": meaning})
        conf = 0.6 + (0.2 if any(p["meaning"] for p in parsed) else 0) + (0.15 if s.get("equipment") else 0)
        out.append({**s, "matched": True, "parsed": parsed, "confidence": round(min(conf, 0.98), 2)})
    return out
