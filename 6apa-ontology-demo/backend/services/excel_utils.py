"""Excel 读取的公共小工具。

v2 的几张 Sheet 在原有列后面追加了新列，如果继续按"列序号 → 字段名"读，
一旦现场再调整列序就会整体错位。所以统一改成**按表头文字取列**，
并对表头做容错（全角/半角括号、空格、大小写）。
"""
from __future__ import annotations

import math
import re
from typing import Any, Iterable

import pandas as pd

_WS = re.compile(r"\s+")
_PAREN = str.maketrans({"（": "(", "）": ")", "／": "/", "：": ":"})


def clean(value: Any) -> str | None:
    """单元格 → 去空白的字符串；空值统一成 None。"""
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    text = str(value).strip()
    if text in ("", "nan", "NaT", "None"):
        return None
    return text


def to_int(value: Any) -> int | None:
    text = clean(value)
    if text is None:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def to_float(value: Any) -> float | None:
    text = clean(value)
    if text is None:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def norm_header(value: Any) -> str:
    """表头归一：去空白、全角括号转半角、小写。"""
    text = clean(value) or ""
    return _WS.sub("", text.translate(_PAREN)).lower()


class HeaderMap:
    """把一行表头变成「字段名 → 列位置」的映射。

    用法：
        hm = HeaderMap(raw.columns)
        hm.bind("tagName", "DCS点名 (Tag PN)")
        hm.get(row, "tagName")

    绑定时可以给多个候选写法；一个都没命中就记进 missing，
    调用方自己决定是报错还是按缺列降级。
    """

    def __init__(self, headers: Iterable[Any]) -> None:
        self.headers = [clean(h) for h in headers]
        self._index = {}
        for position, header in enumerate(self.headers):
            key = norm_header(header)
            if key and key not in self._index:
                self._index[key] = position
        self.fields: dict[str, int] = {}
        self.missing: list[str] = []

    def bind(self, field: str, *candidates: str) -> int | None:
        for candidate in candidates:
            position = self._index.get(norm_header(candidate))
            if position is not None:
                self.fields[field] = position
                return position
        self.missing.append(f"{field}({candidates[0] if candidates else ''})")
        return None

    def bind_all(self, spec: dict[str, tuple[str, ...]]) -> None:
        for field, candidates in spec.items():
            self.bind(field, *candidates)

    def has(self, field: str) -> bool:
        return field in self.fields

    def get(self, row: Any, field: str) -> Any:
        position = self.fields.get(field)
        if position is None:
            return None
        try:
            return row[position]
        except (IndexError, KeyError):
            return None

    def text(self, row: Any, field: str) -> str | None:
        return clean(self.get(row, field))

    def label(self, field: str) -> str | None:
        position = self.fields.get(field)
        return self.headers[position] if position is not None else None


_BOOKS: dict[tuple[str, float], "pd.ExcelFile"] = {}


def open_book(path):
    """打开工作簿并缓存。

    pandas 每调一次 read_excel(path, sheet_name=...) 都会把整个工作簿重新解析一遍，
    共享字符串表尤其贵。v2 的点表有一万多行、十几张 Sheet，逐张读会让索引构建
    从几秒涨到几十秒。这里按 (路径, 修改时间) 缓存 ExcelFile，整本只解析一次；
    文件被替换后 mtime 变化，缓存自然失效。
    """
    from pathlib import Path as _Path

    file = _Path(path)
    key = (str(file.resolve()), file.stat().st_mtime)
    book = _BOOKS.get(key)
    if book is None:
        for stale in [k for k in _BOOKS if k[0] == key[0]]:
            try:
                _BOOKS.pop(stale).close()
            except Exception:
                _BOOKS.pop(stale, None)
        book = pd.ExcelFile(file)
        _BOOKS[key] = book
    return book


def read_sheet(path, sheet_name: str, header=0):
    """读一张 Sheet；工作簿只解析一次。Sheet 不存在时抛 ValueError，与 pandas 一致。"""
    return pd.read_excel(open_book(path), sheet_name=sheet_name, header=header)


def sheet_names(path) -> list[str]:
    return list(open_book(path).sheet_names)


def read_rows(path, sheet_name: str, spec: dict[str, tuple[str, ...]]):
    """读一张有表头的 Sheet，返回 (HeaderMap, 行迭代器, 起始行号)。

    行号从 2 开始（1 是表头），与 Provenance.row 的口径一致。
    """
    raw = read_sheet(path, sheet_name, header=0)
    header_map = HeaderMap(raw.columns)
    header_map.bind_all(spec)
    return header_map, list(raw.itertuples(index=False, name=None)), 2


def find_header_row(raw: pd.DataFrame, marker: str, column: int = 0, limit: int = 20) -> int | None:
    """有标题说明的 Sheet：往下找第一行以 marker 开头的表头，返回行下标。"""
    target = norm_header(marker)
    for i in range(min(limit, len(raw))):
        if norm_header(raw.iloc[i, column]) == target:
            return i
    return None


def split_tags(value: Any) -> list[str]:
    """「关联DCS位号」这类单元格：顿号/逗号/分号分隔，顺带去掉截断省略号。"""
    text = clean(value)
    if not text:
        return []
    parts = re.split(r"[、,;；\s]+", text)
    return [p.strip() for p in parts if p.strip()]
