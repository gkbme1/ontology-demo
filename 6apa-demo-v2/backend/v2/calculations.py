"""计算组态：引用算法库里的算法，把算法的每个输入参数绑定到本体。

一条计算组态 = 作用范围（设备 / 设备组 / 工艺段）+ 引用的算法（algorithmId）+ 参数绑定（bindings）+ 输出单位。
计算组态里不写算法本身：算法的调用方式与参数定义登记在算法库（data/config/6APA_算法库.json，
backend/v2/algorithms.py），本体只定义「传哪个参数」。

参数绑定 bindings = {算法输入名: 绑定}，绑定形式：
- {"kind": "parameter", "name": "反应体系pH", "index": 0}   本对象的属性（设备组上的组态对组内每台分别计算）；
                                                            index 取该属性的第 n 个测点
- {"kind": "groupParameter", "groupId": "egrp-…", "name": "釜内反应温度"}  设备组全部成员的该属性（跨装置统计）
- {"kind": "tag", "tag": "TI_1303"}                        直接指定 DCS 位号
- {"kind": "calc", "calcId": "CALC-…"}                     另一条计算组态的输出
- {"kind": "const", "value": 10}                           常量（算法的配置参数，如时间窗）

计算组态的输出可在判定规则里作为条件主体引用（subject.kind = calc）。

执行设置（需求 SW-050 / SW-074）：
  execution = {"mode": "周期" | "事件触发" | "按需", "periodSec": 60, "trigger": "事件说明 / 现象 ID",
               "timeoutSec": 30, "onFailure": "重试" | "跳过", "retries": 1, "disableAfter": 3}
  output    = {"tag": "XBase 输出计算测点位号", "writeBack": bool}   计算结果写入 XBase 指定测点，本体通过读测点获得结果
本 Demo 没有调度器：执行设置只登记，试算按需运行一次并记入运行记录。
"""
from __future__ import annotations

import copy
import json
import os
import shutil
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import numpy as np

from backend.v2.algorithms import AlgorithmError, AlgorithmLibrary

ROOT = Path(__file__).resolve().parents[2]
SEED_FILE = ROOT / "data" / "seed" / "calculations.json"
STORE_FILE = Path(os.environ.get("V2_STORE_DIR") or ROOT / "data" / "store") / "calculations.json"
BINDING_KINDS = {"parameter": "本对象参数", "groupParameter": "设备组全部成员的参数", "tag": "DCS 位号",
                 "calc": "计算组态输出", "const": "常量"}
EXEC_MODES = ["周期", "事件触发", "按需"]
FAILURE_MODES = ["重试", "跳过"]
DEFAULT_EXECUTION = {"mode": "按需", "periodSec": 60, "trigger": "", "timeoutSec": 30, "onFailure": "跳过", "retries": 0, "disableAfter": 3}
DEFAULT_OUTPUT = {"tag": "", "writeBack": False}


class CalcError(ValueError):
    pass


def binding_text(b: dict[str, Any], names: dict[str, str] | None = None) -> str:
    kind = b.get("kind")
    if kind == "parameter":
        idx = b.get("index")
        return f"本对象.{b.get('name')}" + (f"[第 {idx + 1} 个测点]" if idx is not None else "")
    if kind == "groupParameter":
        return f"设备组「{(names or {}).get(b.get('groupId') or '', b.get('groupId'))}」全部成员.{b.get('name')}"
    if kind == "tag":
        return f"位号 {b.get('tag')}"
    if kind == "calc":
        return f"计算组态 {(names or {}).get(b.get('calcId') or '', b.get('calcId'))}"
    if kind == "const":
        return f"常量 {b.get('value')}"
    return "?"


def compute(calc: dict[str, Any], resolve: Callable[[dict[str, Any]], list[tuple[str, np.ndarray]]],
            times: np.ndarray, algos: AlgorithmLibrary) -> dict[str, Any]:
    """resolve(绑定) → [(位号, 序列)]。按绑定取数后调用算法。返回 {values, inputs, unresolved}。"""
    step_min = (times[1] - times[0]) / 60.0 if len(times) > 1 else 1.0
    try:
        algo = algos.get(calc.get("algorithmId") or "")
    except AlgorithmError as exc:
        raise CalcError(str(exc))
    bindings = calc.get("bindings") or {}
    args: dict[str, Any] = {}
    inputs, unresolved = [], []
    for inp in algo["inputs"]:
        b = bindings.get(inp["name"])
        if b is None:
            if inp.get("required"):
                unresolved.append(inp["name"])
            continue
        if b.get("kind") == "const":
            args[inp["name"]] = b.get("value")
            inputs.append({"var": inp["name"], "tags": [], "const": b.get("value")})
            continue
        found = resolve(b)
        idx = b.get("index")
        if idx is not None:
            found = found[idx:idx + 1] if len(found) > idx else []
        if not found:
            unresolved.append(inp["name"])
            continue
        inputs.append({"var": inp["name"], "tags": [n for n, _ in found]})
        args[inp["name"]] = np.vstack([s for _, s in found])
    if unresolved:
        return {"values": None, "inputs": inputs, "unresolved": unresolved}
    try:
        values = algos.invoke(algo["id"], args, step_min)
    except AlgorithmError as exc:
        raise CalcError(str(exc))
    if np.ndim(values) == 0:
        values = np.full(len(times), float(values))
    return {"values": values, "inputs": inputs, "unresolved": []}


class CalcStore:
    def __init__(self, algos: AlgorithmLibrary, seed_file: Path = SEED_FILE, store_file: Path = STORE_FILE) -> None:
        self.algos = algos
        self.seed_file, self.store_file = seed_file, store_file
        self._lock = threading.RLock()
        self.reload()

    def reload(self) -> None:
        with self._lock:
            self.store_file.parent.mkdir(parents=True, exist_ok=True)
            if not self.store_file.exists():
                shutil.copyfile(self.seed_file, self.store_file)
            self.items = {c["id"]: c for c in json.loads(self.store_file.read_text("utf-8"))["items"]}

    def reset_to_seed(self) -> None:
        with self._lock:
            shutil.copyfile(self.seed_file, self.store_file)
            self.reload()

    def _save(self) -> None:
        tmp = self.store_file.with_suffix(".tmp")
        tmp.write_text(json.dumps({"updatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                   "items": list(self.items.values())}, ensure_ascii=False, indent=1), "utf-8")
        tmp.replace(self.store_file)

    def get(self, cid: str) -> dict[str, Any]:
        if cid not in self.items:
            raise LookupError(cid)
        return self.items[cid]

    def _clean(self, body: dict[str, Any], current: dict[str, Any] | None = None) -> dict[str, Any]:
        data = copy.deepcopy(current) if current else {}
        for key in ("name", "anchor", "algorithmId", "bindings", "unit", "description", "basis", "status", "execution", "output"):
            if key in body:
                data[key] = body[key]
        if not (data.get("name") or "").strip():
            raise CalcError("名称不能为空")
        if not (data.get("anchor") or {}).get("id"):
            raise CalcError("计算组态必须有作用范围（设备 / 设备组 / 工艺段）")
        try:
            algo = self.algos.get(data.get("algorithmId") or "")
        except AlgorithmError as exc:
            raise CalcError(str(exc))
        bindings = data.get("bindings") or {}
        for inp in algo["inputs"]:
            if inp.get("required") and inp["name"] not in bindings:
                raise CalcError(f"算法「{algo['name']}」的参数「{inp['label']}」必须绑定")
        for name, b in bindings.items():
            if name not in {i["name"] for i in algo["inputs"]}:
                raise CalcError(f"算法「{algo['name']}」没有参数 {name}")
            if b.get("kind") not in BINDING_KINDS:
                raise CalcError(f"参数 {name} 的绑定类型只能是：{'、'.join(BINDING_KINDS)}")
            inp = next(i for i in algo["inputs"] if i["name"] == name)
            # 类型匹配：时序输入不能绑常量，常量输入只能绑常量
            if inp.get("type") == "常量" and b.get("kind") != "const":
                raise CalcError(f"参数「{inp['label']}」是常量，只能绑定常量")
            if inp.get("type") != "常量" and b.get("kind") == "const":
                raise CalcError(f"参数「{inp['label']}」是{inp.get('type') or '时序'}，不能绑定常量")
            if b.get("kind") == "const":
                try:
                    float(b.get("value"))
                except (TypeError, ValueError):
                    raise CalcError(f"参数「{inp['label']}」的常量不是数字") from None
            if b.get("kind") in ("parameter", "groupParameter") and not b.get("name"):
                raise CalcError(f"参数「{inp['label']}」要选择本体参数")
            if b.get("kind") == "tag" and not b.get("tag"):
                raise CalcError(f"参数「{inp['label']}」要填写位号")
            if b.get("kind") == "calc":
                if not b.get("calcId") or b.get("calcId") not in self.items:
                    raise CalcError(f"参数「{inp['label']}」引用的计算组态不存在")
                if b.get("calcId") == data.get("id"):
                    raise CalcError("计算组态不能引用自己的输出")
        ex = {**DEFAULT_EXECUTION, **(data.get("execution") or {})}
        if ex["mode"] not in EXEC_MODES:
            raise CalcError(f"执行方式只能是：{'、'.join(EXEC_MODES)}")
        if ex["onFailure"] not in FAILURE_MODES:
            raise CalcError(f"失败处理只能是：{'、'.join(FAILURE_MODES)}")
        try:
            for k in ("periodSec", "timeoutSec", "retries", "disableAfter"):
                ex[k] = int(float(ex[k] or 0))
        except (TypeError, ValueError):
            raise CalcError("周期、超时、重试次数要填数字") from None
        if ex["mode"] == "周期" and ex["periodSec"] < 10:
            raise CalcError("周期执行的周期不能小于 10 秒")
        if ex["timeoutSec"] <= 0:
            raise CalcError("超时时间要大于 0")
        if ex["mode"] == "事件触发" and not str(ex.get("trigger") or "").strip():
            raise CalcError("事件触发要填写触发事件（如某现象成立、批次开始）")
        data["execution"] = ex
        data["output"] = {**DEFAULT_OUTPUT, **(data.get("output") or {})}
        if data["output"].get("writeBack") and not str(data["output"].get("tag") or "").strip():
            raise CalcError("写回 XBase 时要指定输出计算测点位号")
        data.setdefault("status", "草案·待工艺确认")
        return data

    def log_run(self, cid: str, entry: dict[str, Any]) -> None:
        """试算 / 执行记录（需求 SW-074 第 4 条）：时间、耗时、对象数、状态、错误；只保留最近 20 次（内存）。"""
        runs = self.__dict__.setdefault("runs", {})
        runs.setdefault(cid, []).insert(0, entry)
        del runs[cid][20:]

    def last_run(self, cid: str) -> dict[str, Any] | None:
        return (self.__dict__.get("runs") or {}).get(cid, [None])[0]

    def create(self, body: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            data = self._clean(body)
            nums = [int(k.rsplit("-", 1)[-1]) for k in self.items if k.startswith("CALC-U-")]
            data["id"] = f"CALC-U-{(max(nums) + 1 if nums else 1):04d}"
            self.items[data["id"]] = data
            self._save()
            return data

    def update(self, cid: str, body: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            data = self._clean(body, self.get(cid))
            self.items[cid] = data
            self._save()
            return data

    def delete(self, cid: str) -> dict[str, Any]:
        with self._lock:
            self.get(cid)
            del self.items[cid]
            self._save()
            return {"deleted": cid}
