"""把 demo/template.html + demo/src/* 组装成可直接打开的 demo/index.html。

CSS 与应用脚本内联进页面，数据包保持为 demo/data/*.js 外部文件
（4 MB 级，内联会拖慢首屏解析）。
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEMO = ROOT / "demo"
SRC = DEMO / "src"
DATA = DEMO / "data"

# 数据包加载顺序：api.js 在模块初始化时即建立索引，必须先于它加载
DATA_ORDER = [
    "meta", "overview", "categories", "areas", "classes", "properties", "predicates",
    "relationOverview", "relations", "relationEntities", "entityDetails", "matchIndex",
    "dataSources", "dataQuality", "rules", "emptySets", "turtle",
    "equipment", "parameters", "tags",
]

JS_ORDER = ["api.js", "graph.js", "app.js"]


def main() -> int:
    template = (DEMO / "template.html").read_text(encoding="utf-8")
    css = (SRC / "app.css").read_text(encoding="utf-8")

    missing = [n for n in DATA_ORDER if not (DATA / f"{n}.js").exists()]
    if missing:
        print("✗ 缺少数据包：" + "、".join(missing))
        print("  请先运行：python3 -m backend.tools.build_static_demo_data")
        return 1

    data_tags = "\n".join(f'<script src="data/{name}.js"></script>' for name in DATA_ORDER)
    js = "\n\n".join(
        f"/* ===== {name} ===== */\n" + (SRC / name).read_text(encoding="utf-8") for name in JS_ORDER
    )

    html = (
        template
        .replace("/*{{CSS}}*/", css)
        .replace("<!--{{DATA}}-->", data_tags)
        .replace("/*{{JS}}*/", js)
    )
    out = DEMO / "index.html"
    out.write_text(html, encoding="utf-8")

    data_bytes = sum((DATA / f"{n}.js").stat().st_size for n in DATA_ORDER)
    print(f"✓ {out.relative_to(ROOT)}  {out.stat().st_size/1024:.1f} KB")
    print(f"  data/*.js  {len(DATA_ORDER)} 个文件，{data_bytes/1024/1024:.2f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
