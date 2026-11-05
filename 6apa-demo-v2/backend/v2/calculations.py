"""计算组态：派生量 / 指标的定义与试算。

一条计算组态 = 挂载对象 + 方法 + 输入绑定 + 输出单位。设备组上的组态对组内每台设备分别计算。
方法：
- formula            表达式，如 abs(a - b)、mean(t)。输入带 index 时取该属性的第 index 个测点（一维），
                     不带 index 时是「测点 × 时间」二维，用 mean / max / min / sum 沿测点方向合并；
- level_consumption  液位差消耗量：只累计液位下降量（上升视为补液，不抵扣），死区过滤仪表抖动，
                     按滑动时间窗折算速率（单位 / min）。算法复制自 Agent Demo 的 level_consumption；
- rate               滑动时间窗内的平均变化速率（单位 / min，正为上涨）。

计算组态的输出可在判定规则里作为条件主体引用（subject.kind = calc）。
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

ROOT = Path(__file__).resolve().parents[2]
SEED_FILE = ROOT / "data" / "seed" / "calculations.json"
STORE_FILE = Path(os.environ.get("V2_STORE_DIR") or ROOT / "data" / "store") / "calculations.json"
METHODS = {
    "formula": "表达式",
    "level_consumption": "液位差消耗量（只计下降，按时间窗折算速率）",
    "rate": "变化速率（时间窗内平均）",
}


class CalcError(ValueError):
    pass


def level_movements(values: list[float], deadband: float) -> dict[str, Any]:
    """按死区跟踪液位：返回累计下降量、累计上升量、补液（上升段）次数。（复制自 Agent Demo）"""
    anchor = values[0]
    dropped = risen = 0.0
    refills = 0
    rising = False
    for value in values[1:]:
        if value < anchor - deadband:
            dropped += anchor - value
            anchor = value
            rising = False
        elif value > anchor + deadband:
            if not rising:
                refills += 1
                rising = True
            risen += value - anchor
            anchor = value
    return {"dropped": dropped, "risen": risen, "refills": refills}


def _drops_per_step(values: np.ndarray, deadband: float) -> np.ndarray:
    """逐点版本的 level_movements：返回每一步计入的下降量，便于做滑动时间窗求和。"""
    out = np.zeros(len(values))
    anchor = float(values[0])
    for i in range(1, len(values)):
        v = float(values[i])
        if v < anchor - deadband:
            out[i] = anchor - v
            anchor = v
        elif v > anchor + deadband:
            anchor = v
    return out


def _rolling_sum(x: np.ndarray, window: int) -> np.ndarray:
    c = np.concatenate([[0.0], np.cumsum(x)])
    idx = np.arange(1, len(x) + 1)
    lo = np.maximum(0, idx - window)
    return c[idx] - c[lo]


def _safe_eval(expr: str, env: dict[str, Any]) -> np.ndarray:
    def agg(fn: Callable) -> Callable:
        return lambda x: fn(x, axis=0) if np.ndim(x) == 2 else x
    namespace = {
        "abs": np.abs, "mean": agg(np.mean), "max": agg(np.max), "min": agg(np.min), "sum": agg(np.sum),
        "sqrt": np.sqrt, "where": np.where, **env,
    }
    try:
        code = compile(expr, "<calc>", "eval")
    except SyntaxError as exc:
        raise CalcError(f"表达式语法错误：{exc.msg}")
    for name in code.co_names:
        if name not in namespace:
            raise CalcError(f"表达式里有未定义的名称：{name}")
    return np.asarray(eval(code, {"__builtins__": {}}, namespace), dtype=float)  # noqa: S307 名称已白名单校验


def compute(calc: dict[str, Any], resolve: Callable[[dict[str, Any]], list[tuple[str, np.ndarray]]],
            times: np.ndarray) -> dict[str, Any]:
    """resolve(subject) → [(位号, 序列)]。返回 {values, inputs, unresolved}。"""
    step_min = (times[1] - times[0]) / 60.0 if len(times) > 1 else 1.0
    inputs, unresolved = [], []
    env: dict[str, Any] = {}
    for inp in calc.get("inputs") or []:
        subject = inp.get("subject") or {}
        found = resolve(subject)
        index = subject.get("index")
        if index is not None:
            found = found[index:index + 1] if len(found) > index else []
        if not found:
            unresolved.append(inp.get("var"))
            continue
        inputs.append({"var": inp.get("var"), "tags": [n for n, _ in found]})
        mat = np.vstack([s for _, s in found])
        env[inp["var"]] = mat[0] if index is not None else mat
    if unresolved:
        return {"values": None, "inputs": inputs, "unresolved": unresolved}
    method = calc.get("method")
    params = calc.get("params") or {}
    window = max(1, int(round(float(params.get("windowMin", 10)) / step_min)))
    if method == "formula":
        values = _safe_eval(calc.get("expression") or "", env)
        if values.ndim == 2:
            values = values.mean(axis=0)
    elif method == "level_consumption":
        mat = np.atleast_2d(next(iter(env.values())))
        total = np.zeros(mat.shape[1])
        for row in mat:
            span = float(np.max(row) - np.min(row))
            deadband = span * float(params.get("deadbandRatio", 0.01)) if span > 0 else 0.0
            total += _rolling_sum(_drops_per_step(row, deadband), window)
        values = total / (window * step_min)
    elif method == "rate":
        row = np.atleast_2d(next(iter(env.values()))).mean(axis=0)
        shifted = np.concatenate([np.full(window, row[0]), row[:-window]])
        values = (row - shifted) / (window * step_min)
    else:
        raise CalcError(f"不支持的计算方法：{method}")
    if np.ndim(values) == 0:
        values = np.full(len(times), float(values))
    return {"values": values, "inputs": inputs, "unresolved": []}


class CalcStore:
    def __init__(self, seed_file: Path = SEED_FILE, store_file: Path = STORE_FILE) -> None:
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
        for key in ("name", "anchor", "method", "expression", "inputs", "params", "unit", "description", "basis", "status"):
            if key in body:
                data[key] = body[key]
        if not (data.get("name") or "").strip():
            raise CalcError("名称不能为空")
        if not (data.get("anchor") or {}).get("id"):
            raise CalcError("计算组态必须挂在一个本体对象上")
        if data.get("method") not in METHODS:
            raise CalcError(f"方法只能是：{'、'.join(METHODS)}")
        if not data.get("inputs"):
            raise CalcError("至少要绑定一个输入")
        if data["method"] == "formula":
            env = {i["var"]: np.zeros((1, 3)) for i in data["inputs"]}
            _safe_eval(data.get("expression") or "", env)
        data.setdefault("status", "草案·待工艺确认")
        return data

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
