# 6-APA 本体接口速查（供 Agent 使用）

服务地址：`http://<host>:8700`　全部接口 **GET**，返回 JSON，UTF-8。
本体只暴露它真实拥有的数据；没有的就是没有，不要补。

---

## 一、ID 约定（最常见的错误来源）

| 前缀 | 含义 | 从哪来 |
|---|---|---|
| `area-xxxxxxxx` | 工段 | `/process-areas` |
| `equip-xxxxxxxx` | 设备 | `/equipment?keyword=` |
| `param-xxxxxxxx` | 参数语义 | `/parameters` |
| `tag-xxxxxxxx` | DCS 点位 | `/tags` |
| `robj-xxxxxxxx` | 关系对象（物料 / 工艺属性等） | `/relation-entities` |
| `relation-xxxxxxxx` | 一条工业关系 | `/relations` |

**详情类接口只认 ID，传中文名一律 404。** 用户说名称 → 先用列表接口
`keyword` 检索出 ID → 再查详情。
`{object_id}` 形式的接口额外接受 OWL Subject，如 `:Dev_13_水解罐A`。

---

## 二、按任务选接口

| 你要干什么 | 调这个 |
|---|---|
| 车间有多少设备 / 测点 / 关系（计数） | `GET /api/ontology/overview` |
| 本体里有哪几类知识 | `GET /api/ontology/categories` |
| 有哪些工段 | `GET /api/ontology/process-areas`，详情 `/process-areas/{area_id}` |
| 名称 → 设备 ID | `GET /api/ontology/equipment?keyword=&areaId=&limit=` |
| 某设备的全貌 | `GET /api/ontology/equipment/{equipment_id}` |
| 某设备有哪些参数 / 测点 | `/parameters?equipmentId=`、`/tags?equipmentId=` |
| 它和谁有关系（核心） | `GET /api/ontology/{object_id}/relations` |
| 关系检索 / 统计 | `GET /api/ontology/relations?area=&category=&predicate=&matched=` |
| 哪些对象关联最多 | `GET /api/ontology/relation-entities` |
| 画关系图 / 多跳邻居 | `GET /api/ontology/graph?rootId=&depth=1` |
| 抽象工艺量落到哪些位号 | `GET /api/ontology/measurement-anchors` |
| 调这个量会影响什么 | `GET /api/ontology/causal-relations` |
| **现在是多少（当前值）** | `GET /api/ontology/{object_id}/realtime` |
| **过去一段时间的走势** | `GET /api/ontology/{object_id}/history?startTime=` |
| **应该控制在多少（工艺限值）** | `/process-limits`、`/{object_id}/limits` |
| **现在超没超限** | `GET /api/ontology/{object_id}/limit-check` |
| 数据从哪来 / 为什么是空的 | `/data-sources`、`/data-quality` |
| 规则 / 能力 / 约束 / 模型 | `/rules`、`/capabilities`、`/constraints`、`/model-registry` |

---

## 三、三组关键接口的参数

### 实时值
```
GET /api/ontology/{object_id}/realtime?keyword=&type=&blockType=&limit=30&offset=0
GET /api/ontology/realtime?tagIds=tag-a,tag-b        # 或 equipmentId/parameterId/areaId/keyword 之一
```
返回：`scope`（对象是谁）+ `items[]`：`tagName / description / unit / value /
quality(1=好) / timeText` + 设备参数工段的名称。`serverTimeText` 是服务端当前时间。

### 历史值
```
GET /api/ontology/{object_id}/history?startTime=2026-09-24 08:00:00&endTime=&interval=60000&sampleMode=&limit=10
```
`startTime` 必填，支持 `YYYY-MM-DD HH:MM:SS` 或毫秒时间戳；`interval` 单位毫秒。
每个点返回采样序列 `values[]` 与统计 `stats{min,max,avg,first,last}`。
`limit` 是**测点个数**上限（默认 10），不是采样点数。

### 工艺限值与越限判断
```
GET /api/ontology/process-limits?keyword=&area=&status=&hasValues=true|false
GET /api/ontology/{object_id}/limits
GET /api/ontology/process-limits/{limit_id}/check
GET /api/ontology/{object_id}/limit-check?keyword=
```
限值四档 + 正常区间：`lowLow / low / normalLow~normalHigh / high / highHigh`，
每条带 `unit`、`operatingMode`（如「水解反应期」）、`basis`（工艺依据）、`source.row`（Excel 行号）。

`limit-check` 逐测点比对当前值，`results[].status` / `statusLabel`：

| status | 含义 |
|---|---|
| `NORMAL` | 正常 |
| `OUT_OF_NORMAL` | 超出正常区间（未到报警限） |
| `LOW` / `LOW_LOW` | 低于低限 / 低低限 |
| `HIGH` / `HIGH_HIGH` | 高于高限 / 高高限 |
| `UNKNOWN` | 无法判断（无值或该档限值为空） |

`summary` 是按 status 的计数，`deviation` 是偏离阈值的幅度。

---

## 四、读返回值的硬性规则

1. **`total` 才是总数**，不要用本次 `items` 的条数代替。
2. 出现 **`truncationNote` / `notes` 里的翻页提示** ⇒ 你只看到了样本。
   要么用 `limit`/`offset`/更细的过滤继续查，要么在回答里说明"基于样本"。
   不得把样本当全部。
3. **`available:false` 或 `emptyReason`** ⇒ 现场还没提供这类数据源。
   如实说"本体中暂无该类数据"，并说明期望的数据源。**绝不自行补一份。**
4. **`dataSource.simulated:true`** ⇒ 值来自模拟 DCS，回答中必须写明
   "当前为模拟数据，不是现场真实读数"。
5. 限值 **`status:"已确认"` 才是正式工艺依据**；`待现场确认` / `待现场提供`
   必须连同 `basis` 一起说明，并提示"仅供工艺调查参考"。
   **不得自行设定任何报警阈值**；查不到限值就说没有。
6. `matchStatus:"UNMATCHED"`、`unanchoredEntities` 是真实数据状态（该对象在 DCS 点表里没有实例），
   不是错误。
7. 相对时间（"今天""过去一小时""夜班"）以会话中的【当前时间】换算成具体时间再传。
8. 查询失败时读 `detail` / `hint`，换参数或换接口重试；连续失败就如实说哪部分查不到。

---

## 五、可视化页面（可直接给用户链接）

- 关系图：`/relations?rootId=equip-xxxxxxxx&depth=1&view=graph`
  （还支持 `rootType/area/category/predicate/scenario/subjectType/objectType/matched/includeDcs/keyword/embed/panel/theme/title`）
- 工艺限值：`/limits?keyword=温度`
