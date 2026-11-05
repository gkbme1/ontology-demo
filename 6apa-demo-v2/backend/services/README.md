# backend/ontology、backend/services：复制来的本体加载代码

这两个目录**原样复制**自 `6apa-ontology-demo/backend/ontology` 与 `6apa-ontology-demo/backend/services`
（分支 `claude/focused-albattani-6velst` 的 27ca5a3），只删除了本 Demo 用不到的 `graph_builder.py`。

- 读 `data/source/*.xlsx`（同样是复制来的），构建内存本体 `OntologyStore`：点表、设备归并 / 拆分、设备组、实例连接、
  工业关系、工艺限值 / 限值版本、规则、处置卡、能力登记；
- `asset_model.py` 生成对象档案（属性、关系、约束、处置卡），v2 的 10 个页签由它重新组织；
- `timeseries.py` / `process_context.py` 里调用模拟 DCS（8900）的函数本 Demo 不调用，保留是因为被懒加载引用。

改这里的代码前先想清楚：v2 自己的逻辑都在 `backend/v2/`，尽量不要动复制来的加载器，方便日后与原 Demo 对照。
