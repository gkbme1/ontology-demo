# 项目上下文（给新会话的交接说明）

本仓库是 6-APA 生产线工业本体 Demo + 工艺调查智能体（Agent）Demo，客户场景：国药威奇达 105 车间工艺调查智能体。
需求梳理见 `6apa-ontology-demo/docs/威奇达工艺调查_需求梳理.md`（UR 用户需求 → ON 本体 / KB 知识库 / AG Agent 需求）。

## 工作约定

- 用中文汇报。用户只想澄清时会说"不需要修改代码 / 先澄清 / 只分析"，此时不改代码；否则认可的方案直接实现。
- 开发分支：`claude/focused-albattani-6velst`；提交后推送，不主动建 PR。提交信息、代码里不写模型名称。
- 总原则：**定义在本体，执行在 Agent，原文在知识库，数据在外部系统**。全程留痕、审计属于 Agent。
- 数据源都是 `6apa-ontology-demo/data/source/*.xlsx`，由 `backend/tools/build_*.py` 生成预填版：已存在时不覆盖（`--force` 才覆盖），
  预填条目标「草案·待工艺确认」/「待确认」，不编造现场数据。新增数据源要登记到 `backend/ontology/indexes.py` 的 data_sources。
- 模拟数据必须声明是模拟的（接口带 `dataSource.simulated`，回答里说明）。

## 两个工程

| 工程 | 端口 | 说明 |
| --- | --- | --- |
| `6apa-ontology-demo` | 8700 | 本体服务（FastAPI，内存 OntologyStore，加载 Excel）；前端 Vue（`frontend/`，vite 5173，`/api`→8700、`/agent-api`→8800） |
| `6apa-agent-demo` | 8800 | Agent 服务；工具 = `ToolSpec`，`handler` 非空即固定程序；`/api/tools` 给工具清单 |
| `6apa-agent-demo/mock_dcs` | 8900 | 模拟 DCS（实时 / 历史）+ 模拟 EBR、MOM、LIMS、DCS 操作日志；值是 (种子, 位号, 时间) 的纯函数 |

启动顺序：**本体 8700 → 模拟 DCS 8900（启动时从本体拉点表）→ Agent 8800 → vite**。改了本体代码或数据表要重启 8700；
改 mock 要重启 8900。注意：`pkill -f` 会匹配到调用它的 shell，停进程请用 `pgrep` 查 PID 后单独 `kill`。

## 关键设计（已实现）

- 本体三层：类（设备类型）/ 设备组 / 实例；组间拓扑按连接方式落到实例（`6APA_实例连接.xlsx`）。
- 能力登记（`6APA_能力.xlsx`）：能力描述 + 调用契约 + 本对象参数绑定；已登记 7 项（实时、历史、罐批次 EBR、班次 MOM、化验查询 / 录入 LIMS、操作记录）。
- 处置卡（`6APA_处置规程.xlsx`），S11 有 10 张。
- 第 1 步「时段与上下文」：`6APA_工序与阶段.xlsx`（8 道工序、水解 5 个阶段的 EBR 阶段名 / DCS 识别条件 / 对应限值操作模式）；
  本体代调 `/{id}/batches`、`/batches/{批号}`、`/{id}/context`、`/shifts`、`/{id}/stage-rules`；历史 / 实时接口支持 `unit=` 只取某一台。
  Agent：`get_batch_context`；分析工具支持 `unit / batchNo / phase`，时间窗换算成批次阶段（EBR 优先，DCS 推断兜底），结果带 `windowBasis`。
- 第 2 步「分析能力」：`6APA_调查知识.xlsx`（人机料法环分类与权重、化验项目、判定规则、漂移口径）、
  `6APA_限值版本.xlsx`（条件化限值、在线修改 = POST 追加版本、按时刻查生效限值）。
  Agent：`check_measurement_deviation`、`detect_drift`、`analyze_operations`；异常溯源输出 Top 3～5 候选方向（人机料法环、证据×权重、低分转人工）；
  越限 / 溯源 / 影响验证逐点按"当时生效"的限值（阶段过滤 × 版本 × 换酶后批次数，见 `backend/tools/limit_context.py`）。
- 点表台号后缀跳过 I：水解罐I/J/K 的位号多写成 J/K/L（个别点例外），氨水计量罐同样（水解罐K ↔ 氨水计量罐L）。
  模板 `{x}` 一律按本台实际登记的位号匹配（`process_context.resolve_template` / `unit_scope`），不要按设备名字母替换。

## 后续计划

- 第 3 步「调查记录与可视化」：调查记录持久化（可按罐、时间检索）、全程审计日志、问数画图（多罐趋势对比、统计表）、调查向导页面
  （定范围 → 定阶段 → 化验佐证 → 候选方向 → 排查清单 → 回填 → 报告素材）。
- 第 4 步「闭环」：排查清单、现场回填、报告素材导出（Word）、案例沉淀与相似检索。

## 已知问题 / 待现场确认

- `6apa-agent-demo/tests/test_examples` 有 2 项此前就存在的失败：「釜内反应温度」关系从 7 条增至 20 条后返回体被裁剪。
- 关系表没有"确认状态"字段，候选方向暂未对未确认关系降权。
- 阈值与权重都是草案：漂移 15% 正常区间宽度、差值扩大 0.02/天是对着模拟数据调的，需工艺标定。
- 模拟数据里 C 罐 pH 电极 1 每 14 天校准、持续漂移（演示在线—化验差值扩大、限值内漂移）；各罐有随机的人为改设定值。

## 回归测试

本体（在 `6apa-ontology-demo` 下，需 8700 / 8900 在跑）：
`python3 -m tests.<名>`：test_v2_refactor、test_limits、test_timeseries、test_asset_model、test_equipment_merge、test_equipment_split、
test_capabilities、test_procedures、test_instance_links、test_process_context、test_investigation。

Agent（在 `6apa-agent-demo` 下）：verify_tools、test_analysis_tools、test_calculations、test_context_tools、test_investigation_tools、
test_agent_loop、test_tool_catalog、test_examples；`MOCK_DCS_URL=http://localhost:8900 python3 -m tests.test_mock_dcs`。
改了工具后用 `python3 -m tests.dump_tools_json > docs/agent-tools.json` 重新生成工具清单。
