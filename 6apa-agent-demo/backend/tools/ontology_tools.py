"""6-APA 本体 API 的 Tool 定义。

本文件是整个项目里唯一知道"本体有哪些接口"的地方，是纯声明式数据。
新增一个本体接口 = 在 ONTOLOGY_TOOLS 里加一条 ToolSpec，
Agent Runtime / Executor / 前端 一行都不用改。

参数名严格对齐本体服务真实的 query 参数（见本体服务 backend/api/routes.py），
不是按文档猜的。
"""

from __future__ import annotations

from dataclasses import replace

from .registry import EntityCapture, ToolParameter, ToolRegistry, ToolSpec

# 常用分页参数（本体服务的列表类接口统一支持 limit / offset）
_LIMIT = ToolParameter(
    "limit",
    "integer",
    "本次最多返回多少条。列表很大时务必收敛（建议 20~50）；返回体中的 total 始终是真实总数，不受 limit 影响。",
)
_OFFSET = ToolParameter("offset", "integer", "分页偏移量，从 0 开始。配合 limit 翻页。")

_EQUIP_ENTITY = EntityCapture(
    kind="equipment",
    label="设备",
    from_args=("equipment_id",),
    from_result_paths=("name", "objectName"),
)
_AREA_ENTITY = EntityCapture(
    kind="process_area",
    label="工段",
    from_args=("area_id",),
    from_result_paths=("name", "nameZh"),
)


ONTOLOGY_TOOLS: list[ToolSpec] = [
    # ---------------------------------------------------------------- 概览
    ToolSpec(
        name="query_ontology_overview",
        description=(
            "查询 6-APA 生产车间本体的整体规模概览。"
            "回答'有多少设备/多少工段/多少测点/多少关系/多少规则'这类计数问题时应优先使用本工具，"
            "不要靠翻列表去数。"
        ),
        path="/api/ontology/overview",
        group="core",
        summary="车间整体规模概览，回答各类计数问题",
        returns=(
            "工段数、控制站数、设备数、参数语义数、DCS 点数、关系数、关系对象数（含已匹配/未匹配）、"
            "测量锚点数、类数、分类数、规则数、约束数、能力数、因果关系数、映射条目数、"
            "DCS 点位类型分布 tagStats、数据质量问题数、数据加载时间。"
        ),
    ),
    # ---------------------------------------------------------------- 工段
    ToolSpec(
        name="query_process_areas",
        description=(
            "查询全部生产工段列表（按流程图工艺口径划分，共 24 个：S01–S23 与 S99 备用）。"
            "每个工段带工段编号 code、英文标识、工艺定位、涉及的控制站号、设备数、参数数、DCS 点数、"
            "标准设备组数、上下游工段。需要知道车间由哪些工段构成、或要拿到工段 ID 时使用。"
            "注意：工段不是控制站——一个控制站的点位会分到多个工艺工段，一个工艺工段也会跨多个控制站。"
        ),
        path="/api/ontology/process-areas",
        group="structure",
        summary="24 个工艺工段的列表，带控制站、上下游、工艺定位",
        returns="items[]：工段 id（area-S01 形式）、code（S01）、name、nameEn、uri、positioning（工艺定位）、stations（涉及控制站）、processScreens、upstream/downstream（上下游工段与衔接物料）、equipmentCount、parameterCount、tagCount、equipmentGroupCount、relationCount、数据来源。",
    ),
    ToolSpec(
        name="query_process_area_detail",
        description=(
            "查询单个工段的详情：该工段下的设备、标准设备组、上下游衔接、关联关系与分类计数。"
            "area_id 可以传 area-S01、S01 或工段全名（如 酶法水解），三种写法等价。"
        ),
        path="/api/ontology/process-areas/{area_id}",
        parameters=(
            ToolParameter(
                "area_id",
                "string",
                "工段 ID（area-S11）、工段编号（S11）或工段全名（酶法水解）均可。",
                required=True,
            ),
        ),
        group="structure",
        summary="单个工段详情：设备、设备组、上下游衔接、关系",
        returns="工段基本信息 + 下属设备 + 标准设备组 + flow（上下游衔接明细）+ 关系与分类计数。",
        entity_capture=_AREA_ENTITY,
        heavy=True,
    ),
    # ---------------------------------------------------------------- 设备
    ToolSpec(
        name="query_equipment_list",
        description=(
            "按条件检索设备列表。这是把'设备名称'换成'设备 ID'的主要手段："
            "用户说出设备名（如 一层排渣泵）时，先用 keyword 检索拿到 equip-xxxxxxxx，"
            "再用 query_equipment_detail 或 query_object_relations 深入。"
            "全车间设备超过一千台，不加过滤条件时请务必设置 limit。"
        ),
        path="/api/ontology/equipment",
        parameters=(
            ToolParameter("keyword", "string", "设备名称关键词，支持部分匹配，例如 排渣泵、反应釜、离心机。"),
            ToolParameter("processArea", "string", "按工段名称过滤（子串匹配，如 酶法水解）。"),
            ToolParameter("areaId", "string", "按工段过滤，可传 area-S11 / S11 / 酶法水解。一台设备的点位可能落在多个工段，按任一命中过滤。"),
            ToolParameter("sn", "string", "按控制站号过滤，例如 10、12。"),
            _LIMIT,
            _OFFSET,
        ),
        group="core",
        summary="按关键词/工段检索设备，把设备名换成 equip- ID",
        returns="items[]：设备 id（equip-xxxxxxxx）、owlSubject、name、areaId/areaCode/areaName（主工段）、areaCodes/areaSpan（实际覆盖的全部工段）、equipmentGroup（标准设备组）、confidence（归属置信度）、控制站、tagCount、parameterCount、点位类型分布、overview 摘要；total 为符合条件的真实总数。",
        defaults={"limit": 30},
        heavy=True,
    ),
    ToolSpec(
        name="query_equipment_detail",
        description=(
            "查询指定设备的完整本体信息。这是设备类问题的核心工具。"
            "equipment_id 必须是 equip-xxxxxxxx 形式的设备 ID —— 直接传设备名称会 404，"
            "只知道名称时先用 query_equipment_list 的 keyword 参数检索。"
        ),
        path="/api/ontology/equipment/{equipment_id}",
        parameters=(
            ToolParameter(
                "equipment_id",
                "string",
                "设备 ID，形如 equip-8170434d。来自 query_equipment_list 的 items[].id。",
                required=True,
            ),
        ),
        group="core",
        summary="单台设备的完整信息：参数、点位、关系、规则",
        returns=(
            "设备属性、所属工段与控制站、参数语义列表、DCS 点列表、关系、关联的关系对象、"
            "适用规则，以及每项数据的来源（Excel 文件 / Sheet / 行号）。"
        ),
        entity_capture=_EQUIP_ENTITY,
        heavy=True,
    ),
    # ---------------------------------------------------------------- 参数
    ToolSpec(
        name="query_parameters",
        description=(
            "查询参数语义（设备上的可测量/可控制量，如 启停指令、出口压力、釜内温度）。"
            "可按设备、工段、关键词、参数类别过滤。全车间一万余条，请务必收敛过滤条件或 limit。"
        ),
        path="/api/ontology/parameters",
        parameters=(
            ToolParameter("equipmentId", "string", "按设备 ID 过滤，形如 equip-8170434d。查某台设备有哪些参数时用这个。"),
            ToolParameter("areaId", "string", "按工段过滤，可传 area-S11 / S11 / 酶法水解。"),
            ToolParameter("keyword", "string", "参数名称关键词，例如 温度、压力、液位。"),
            ToolParameter("category", "string", "参数类别，取值来自本体数据本身（如 模拟量采集(PV)、开关控制(DO) 等），不确定时先不填。"),
            _LIMIT,
            _OFFSET,
        ),
        group="core",
        summary="查参数语义（设备上的可测量/可控制量）",
        returns="items[]：参数 id（param-xxxxxxxx）、name、所属设备、所属工段、categories、units、blockTypes、tagCount、tagIds；total 为真实总数。",
        defaults={"limit": 50},
        heavy=True,
    ),
    ToolSpec(
        name="query_parameter_detail",
        description="查询单条参数语义的详情，含其绑定的 DCS 点、测量锚点、关联关系与规则。",
        path="/api/ontology/parameters/{parameter_id}",
        parameters=(
            ToolParameter(
                "parameter_id",
                "string",
                "参数 ID，形如 param-5fc7af33。来自 query_parameters 的 items[].id。",
                required=True,
            ),
        ),
        group="core",
        summary="单条参数语义的详情，含绑定的 DCS 点与测量锚点",
        returns="参数基本信息、所属设备、DCS 点、测量锚点、关系对象、关系、规则。",
        heavy=True,
    ),
    # ---------------------------------------------------------------- DCS 点
    ToolSpec(
        name="query_tags",
        description=(
            "查询 DCS 点位（现场真实位号，如 P_PZ_DO、TI_1301J）。"
            "查某台设备有哪些测点时传 equipmentId。全车间一万余点，务必过滤或限制 limit。"
        ),
        path="/api/ontology/tags",
        parameters=(
            ToolParameter("equipmentId", "string", "按设备 ID 过滤，形如 equip-8170434d。"),
            ToolParameter("parameter", "string", "按参数 ID 过滤，形如 param-5fc7af33。"),
            ToolParameter("areaId", "string", "按工段过滤，可传 area-S11 / S11 / 酶法水解。"),
            ToolParameter("type", "string", "按参数类型过滤（对应点位的 parameterType），取值来自本体数据本身。"),
            ToolParameter("blockType", "string", "按 DCS 功能块类型过滤，取值来自本体数据本身（如 AI、DI、AO、DOV 等）。"),
            ToolParameter("keyword", "string", "位号或点位描述关键词。"),
            _LIMIT,
            _OFFSET,
        ),
        group="core",
        summary="查 DCS 点位（现场真实位号）",
        returns="items[]：点位 id、name（位号）、rawDescription（现场描述）、所属设备/参数/工段（含 areaCode）、equipmentGroup、variableCategory（变量类别）、standardUnit、processScreen（所在流程画面）、attributionBasis（归属依据）、confidence（归属置信度）、控制站、parameterType、unit、blockType、数据来源行号；total 为真实总数。",
        defaults={"limit": 50},
        heavy=True,
    ),
    # ------------------------------------------------------- 本体结构（元层）
    ToolSpec(
        name="query_ontology_categories",
        description=(
            "查询本体的顶层内容分类（本体里到底沉淀了哪几类知识）。"
            "回答'本体里有哪些类型的知识''本体覆盖了什么'这类开放问题时，这是第一个该用的工具。"
        ),
        path="/api/ontology/categories",
        group="meta",
        summary="本体的顶层内容分类",
        returns="items[]：分类 key、名称、说明、当前条目数、数据源状态（有数据 / 暂无数据源）。",
    ),
    ToolSpec(
        name="query_ontology_classes",
        description="查询本体的类定义（OWL Class 层）：车间里存在哪些概念类型及其层级。",
        path="/api/ontology/classes",
        group="meta",
        summary="本体的类定义（OWL Class 层）",
        returns="items[]：类 URI、中文名、父类、实例数、说明。",
    ),
    ToolSpec(
        name="query_ontology_properties",
        description="查询本体的属性定义（对象属性与数据属性）：类与类之间、类与数据之间允许有哪些关系。",
        path="/api/ontology/properties",
        group="meta",
        summary="本体的属性定义",
        returns="items[]：属性 URI、名称、定义域、值域、类型（ObjectProperty / DatatypeProperty）。",
    ),
    # ---------------------------------------------------------------- 关系
    ToolSpec(
        name="query_relations",
        description=(
            "查询工业关系（设备/物料/工艺属性/控制仪表之间的结构、拓扑、控制、影响、质量关系）。"
            "分析'哪些设备关联多''关系主要是什么类型''上下游如何串联'时使用。"
            "全车间 2252 条，务必带过滤条件；查某个对象的关系时传 entityId 并加 view=compact，否则返回体会被裁剪。"
            "过滤值必须与本体中的真实取值一致；不确定取值时先不带过滤调用一次观察 category / predicate / area 的实际取值。"
        ),
        path="/api/ontology/relations",
        parameters=(
            ToolParameter("view", "string", "取 compact 时返回精简视图（去掉追溯字段，一条约 300 字节而不是 1.8 KB）。遍历因果链、看某个对象有哪些关系时建议用 compact，需要来源行号与 URI 时再用默认视图。"),
            ToolParameter("area", "string", "按关系所属工段过滤，取值是工段全名（如 酶法水解、萃取与反萃（苯乙酸分离）），与 query_process_areas 的 name 一致。"),
            ToolParameter("category", "string", "关系分类，如 结构关系、控制关系、影响关系、物理拓扑关系、质量关系。"),
            ToolParameter("predicate", "string", "关系谓词，如 具有部件、流入、控制、正向影响。"),
            ToolParameter("subjectType", "string", "主体对象类型，如 生产设备、物料流股、工艺属性、控制仪表。"),
            ToolParameter("objectType", "string", "客体对象类型。"),
            ToolParameter("scenario", "string", "关系适用场景，如 常态、闭环调节、工段衔接。"),
            ToolParameter("entityId", "string", "只看与某个关系对象相关的关系，传 robj-xxxxxxxx。"),
            ToolParameter("keyword", "string", "在关系主客体名称与描述中做关键词匹配。"),
            ToolParameter("minWeight", "number", "关系权重下限。"),
            ToolParameter("maxWeight", "number", "关系权重上限。"),
            ToolParameter("matched", "boolean", "true 只看主客体已匹配到 DCS 实例的关系，false 只看未匹配的。"),
            _LIMIT,
            _OFFSET,
        ),
        group="core",
        summary="按条件检索工业关系；查某对象的因果链用 entityId + view=compact",
        returns=(
            "items[]：关系 id、area、category、predicate、subject/object（含 id、type、entity、匹配状态）、"
            "domainDescription 工艺依据、scenario、weight、isCausal、数据来源行号；total 为真实总数。"
        ),
        defaults={"limit": 40},
        heavy=True,
    ),
    ToolSpec(
        name="query_relation_detail",
        description="查询单条工业关系的完整信息，含主客体匹配到的 DCS 实例、工艺依据与来源行。",
        path="/api/ontology/relations/{relation_id}",
        parameters=(
            ToolParameter(
                "relation_id",
                "string",
                "关系 ID，形如 relation-69925769。来自 query_relations 的 items[].id。",
                required=True,
            ),
        ),
        group="structure",
        summary="单条关系的完整信息与来源行号",
        returns="关系全字段 + 主客体详情 + 匹配到的设备/参数实例 + 来源。",
        heavy=True,
    ),
    ToolSpec(
        name="query_relation_entities",
        description=(
            "查询关系对象清单（关系表里出现的主客体本身，如 水解反应釜、母液、釜内反应温度），全车间 1174 个。"
            "按关联关系数降序排列，因此'哪些对象关联最多'这类问题用它最直接；"
            "找某个具体工艺量时务必带 keyword，不然会被裁剪。"
            "注意：部分关系对象在 DCS 点表中没有对应实例（matchStatus=UNMATCHED），这是真实数据状态，不要当成错误。"
        ),
        path="/api/ontology/relation-entities",
        parameters=(
            ToolParameter("type", "string", "按对象类型过滤，如 生产设备、设备实例、设备部件、工艺属性、物料流股、质量指标、控制仪表、执行机构、公用介质、报警事件、业务指标、控制系统。"),
            ToolParameter("areaId", "string", "按工段过滤，可传 area-S11 / S11 / 酶法水解。"),
            ToolParameter("keyword", "string", "在对象名称、所属设备/流股、URI 中做子串匹配。找具体某个工艺量时用它最省事。"),
            ToolParameter("matched", "boolean", "true 只看已匹配 DCS 实例的对象，false 只看未匹配的。"),
            ToolParameter("limit", "integer", "返回条数上限。"),
            ToolParameter("offset", "integer", "跳过条数，与 limit 配合分页。"),
        ),
        defaults={"limit": 40},
        group="core",
        summary="查关系对象（工艺属性、物料流股等），带 keyword 精确找",
        returns="items[]：对象 id（robj-xxxxxxxx）、name、type、uri、owlClass、areaCode、belongsTo（所属设备/流股）、matchStatus、matchStrategies、matchCount、tagCount、relationCount；total 为真实总数（全车间 1174 个）。",
        heavy=True,
    ),
    ToolSpec(
        name="query_ontology_graph",
        description=(
            "以某个对象为根，按指定深度展开关系图，返回 nodes / edges。"
            "用户想'看看结构''画个关系图'，或需要一次拿到多跳邻居时使用。"
            "depth 越大返回越多，一般 1~2 足够。"
        ),
        path="/api/ontology/graph",
        parameters=(
            ToolParameter("rootId", "string", "根节点 ID：可用 robj-xxxxxxxx（关系对象）、equip-xxxxxxxx（设备）、area-S01（工段）。不传则返回全局关系图。"),
            ToolParameter("rootType", "string", "根节点类型提示，如 relationEntity、equipment、area。"),
            ToolParameter("depth", "integer", "展开深度，默认 1，建议不超过 2。"),
            ToolParameter("area", "string", "只保留某工段的关系。"),
            ToolParameter("category", "string", "只保留某类关系。"),
            ToolParameter("predicate", "string", "只保留某个谓词的关系。"),
            ToolParameter("scenario", "string", "只保留某场景的关系。"),
            ToolParameter("subjectType", "string", "按主体类型过滤。"),
            ToolParameter("objectType", "string", "按客体类型过滤。"),
            ToolParameter("minWeight", "number", "权重下限。"),
            ToolParameter("maxWeight", "number", "权重上限。"),
            ToolParameter("matched", "boolean", "true 只保留已匹配 DCS 实例的节点。"),
            ToolParameter("includeDcs", "boolean", "是否把匹配到的 DCS 设备实例也画进图里。"),
        ),
        group="structure",
        summary="以某对象为根展开关系图，返回 nodes/edges",
        returns="nodes[]（id、label、type、nodeKind、匹配状态、relationCount）、edges[]（source、target、predicate、category、weight）、nodeCount、edgeCount、truncated。",
        graph_keys=("nodes", "edges"),
        heavy=True,
    ),
    ToolSpec(
        name="query_object_relations",
        description=(
            "查询任意对象的全部关联信息——设备关系类问题的核心工具。"
            "支持四种 ID：equip-xxxxxxxx（设备）、param-xxxxxxxx（参数）、robj-xxxxxxxx（关系对象）、area-S01（工段），"
            "也接受 :Dev_xx_设备名 形式的 OWL Subject。"
            "问'它和哪些设备有关''它的上游是什么''它有哪些测点'时，这个工具一次就能拿到上下游、参数、DCS 点、关系与因果关系。"
        ),
        path="/api/ontology/{object_id}/relations",
        parameters=(
            ToolParameter(
                "object_id",
                "string",
                "对象 ID：equip- / param- / robj- / area- 前缀，或 :Dev_10_一层排渣泵 这样的 OWL Subject。",
                required=True,
            ),
        ),
        group="core",
        summary="任意对象的全部关联信息，设备关系类问题的核心工具",
        returns=(
            "objectKind、objectName，以及该对象的 parameters、tags（DCS 点）、relationEntities、"
            "relations（含上下游方向与谓词）、rules、causalRelations。"
        ),
        entity_capture=EntityCapture(
            kind="object",
            label="对象",
            from_args=("object_id",),
            from_result_paths=("objectName",),
        ),
        heavy=True,
    ),
    # ------------------------------------------------ 规则 / 能力 / 约束 / 语义
    ToolSpec(
        name="query_rules",
        description=(
            "查询生产规则（什么条件得出什么结论）。"
            "注意：规则必须来自独立的规则数据源，本体不会从参数名称自动生成规则；"
            "若返回 available=false / total=0，说明现场规则文件尚未提供，"
            "此时应如实告知用户'本体中暂无规则数据'，绝不可自行编造规则。"
        ),
        path="/api/ontology/rules",
        parameters=(
            ToolParameter("area", "string", "按工段过滤。"),
            ToolParameter("appliesTo", "string", "按适用对象过滤。"),
        ),
        group="rules",
        summary="生产规则（71 条，阈值多引用限值表）",
        returns="items[]、total、available、emptyReason（为空时说明原因）、expectedSource、templateColumns。",
    ),
    ToolSpec(
        name="query_capabilities",
        description="查询本体声明的项目能力清单。为空时返回 emptyReason，说明数据源未提供，不要编造。",
        path="/api/ontology/capabilities",
        group="rules",
        summary="本体声明的项目能力清单",
        returns="items[]、total、emptyReason、expectedSource。",
    ),
    ToolSpec(
        name="query_constraints",
        description="查询本体约束（边界与限制条件）。为空时返回 emptyReason，说明数据源未提供，不要编造。",
        path="/api/ontology/constraints",
        group="rules",
        summary="本体约束（边界与限制条件）",
        returns="items[]、total、emptyReason、expectedSource。",
    ),
    ToolSpec(
        name="query_model_registry",
        description="查询模型注册表（本体登记了哪些算法/机理模型）。为空时返回 emptyReason。",
        path="/api/ontology/model-registry",
        group="rules",
        summary="模型注册表",
        returns="items[]、total、emptyReason、expectedSource。",
    ),
    ToolSpec(
        name="query_semantics",
        description=(
            "查询语义层：参数语义与现场位号之间的语义绑定关系。"
            "用于回答'这个测点到底代表什么''语义是怎么对齐的'。数据量较大，建议配合 areaId 或 limit。"
        ),
        path="/api/ontology/semantics",
        parameters=(
            ToolParameter("areaId", "string", "按工段过滤，可传 area-S11 / S11 / 酶法水解。"),
            _LIMIT,
        ),
        group="meta",
        summary="参数语义与现场位号的语义绑定",
        returns="语义条目：参数语义、绑定位号、设备、工段、数据来源。",
        defaults={"limit": 40},
        heavy=True,
    ),
    ToolSpec(
        name="query_measurement_anchors",
        description=(
            "查询测量锚点：关系表里的抽象工艺量（如 釜内反应温度）落到哪些真实 DCS 位号上。"
            "分析'某个工艺量能不能被测到''靠哪个测点观测'时使用。"
            "返回里的 unanchoredEntities 是尚未落到任何测点的对象，属真实数据状态。"
        ),
        path="/api/ontology/measurement-anchors",
        parameters=(
            ToolParameter("areaId", "string", "按工段 ID 过滤。"),
            _LIMIT,
        ),
        group="structure",
        summary="抽象工艺量落到哪些真实 DCS 位号",
        returns="items[]：锚点对象、绑定的 DCS 点、设备、置信度、来源；unanchoredEntities[]：未锚定对象。",
        defaults={"limit": 40},
        heavy=True,
    ),
    ToolSpec(
        name="query_causal_relations",
        description=(
            "查询因果关系（正向影响 / 负向影响 / 影响一类的关系子集）。"
            "分析'调这个量会影响什么''收率受什么影响'时使用。"
        ),
        path="/api/ontology/causal-relations",
        group="structure",
        summary="因果/影响/质量关系子集",
        returns="items[]：因果关系的因、果、方向、权重、工艺依据、场景、来源。",
        heavy=True,
    ),
    # ------------------------------------------------------------ 数据来源
    ToolSpec(
        name="query_data_sources",
        description=(
            "查询本体各类内容分别来自哪个数据源文件，以及哪些内容当前没有数据源。"
            "回答'这个结论依据是什么''数据从哪来''为什么规则是空的'时使用。"
        ),
        path="/api/ontology/data-sources",
        group="meta",
        summary="各类内容分别来自哪个数据源文件",
        returns="每类内容的数据源文件、Sheet、条目数、状态。",
    ),
    ToolSpec(
        name="query_data_quality",
        description=(
            "查询数据质量检查结果：本体加载时发现的错误 / 告警 / 提示。"
            "用户质疑数据可信度、或需要说明已知问题时使用。"
        ),
        path="/api/ontology/data-quality",
        group="meta",
        summary="数据质量检查结果",
        returns="检查项列表、各级别问题数量与明细样例。",
        heavy=True,
    ),
    # ------------------------------------------------------------ 实时值 / 历史值
    # 本体服务作为语义网关转调外部实时库 / 历史库，需要本体服务已加装"实时历史接口补丁"
    ToolSpec(
        name="query_realtime_values",
        description=(
            "查询测点当前值（实时值）。本体按对象解析出 DCS 点，再从实时库取值，"
            "返回每个点的 value / quality / 时间，并附设备、参数、现场描述、单位。"
            "问'现在多少''当前是否在运行''目前温度/压力/液位'时使用。"
            "object_id 可以是设备 equip-、参数 param-、DCS点 tag-、关系对象 robj-、工段 area-，"
            "或 :Dev_13_水解罐A 这样的 OWL Subject。只想看某一类量时用 keyword（如 温度）或 type 缩小范围。"
            "返回的 dataSource.simulated 为 true 时，数值来自模拟数据服务，回答中必须说明不是现场真实读数。"
            "若返回 404 且 detail 为 Not Found，说明本体服务尚未启用实时值接口。"
        ),
        path="/api/ontology/{object_id}/realtime",
        parameters=(
            ToolParameter("object_id", "string", "本体对象 ID（equip- / param- / tag- / robj- / area-）或 OWL Subject。", required=True),
            ToolParameter("keyword", "string", "在该对象的测点里按位号或现场描述筛选，例如 温度、压力、运行。"),
            ToolParameter("type", "string", "按参数类型筛选，取值来自本体数据本身，如 过程测量(PV)、状态反馈(DI)。"),
            ToolParameter("blockType", "string", "按 DCS 功能块类型筛选，如 AI、DI。"),
            ToolParameter("limit", "integer", "最多返回多少个测点，默认 50，上限 200；返回体 total 为真实总数。"),
            ToolParameter("offset", "integer", "测点分页偏移。"),
        ),
        group="values",
        summary="取测点当前值",
        returns=(
            "scope（对象）、total、items[]（tagName、description、unit、equipmentName、parameterName、"
            "value、quality、qualityLabel、timeText）、dataSource（实时库地址、是否模拟）、notes（分页或映射待确认等说明）。"
        ),
        defaults={"limit": 30},
        heavy=True,
    ),
    ToolSpec(
        name="query_history_values",
        description=(
            "查询测点历史值（趋势）。本体按对象解析出 DCS 点，再从历史库取一段时间的数据，"
            "每个点返回采样序列 values 与统计 stats（min / max / avg / first / last）。"
            "问'过去一小时温度走势''今天泵启停了几次''夜班期间最高压力'时使用。"
            "startTime / endTime 用 yyyy-MM-dd HH:mm:ss（东八区），可根据会话上下文中的【当前时间】推算。"
            "看趋势优先读 stats，并把 interval 设得让每个点不超过约 60 个样本；"
            "看开关量何时变化用 sampleMode=raw（只返回变位点）。"
            "测点多时务必用 keyword / type 缩小范围。"
            "返回的 dataSource.simulated 为 true 时，数值来自模拟数据服务，回答中必须说明不是现场真实读数。"
        ),
        path="/api/ontology/{object_id}/history",
        parameters=(
            ToolParameter("object_id", "string", "本体对象 ID（equip- / param- / tag- / robj- / area-）或 OWL Subject。", required=True),
            ToolParameter("startTime", "string", "开始时间，yyyy-MM-dd HH:mm:ss（东八区）或毫秒时间戳。", required=True),
            ToolParameter("endTime", "string", "结束时间，格式同上，默认当前时刻。"),
            ToolParameter("interval", "integer", "采样间隔（毫秒，≥1000），例如 60000 为 1 分钟。不填由历史库自动选。"),
            ToolParameter(
                "sampleMode", "string", "interpolated 等间隔取值（默认）/ avg / max / min 按间隔统计 / raw 原始值（开关量只返回变位点）。",
                enum=("interpolated", "avg", "max", "min", "raw"),
            ),
            ToolParameter("keyword", "string", "在该对象的测点里按位号或现场描述筛选，例如 温度。"),
            ToolParameter("type", "string", "按参数类型筛选，如 过程测量(PV)。"),
            ToolParameter("limit", "integer", "最多返回多少个测点，默认 10。"),
        ),
        group="values",
        summary="取测点历史趋势与统计",
        returns=(
            "scope、startTimeText / endTimeText、interval、sampleMode、total、"
            "items[]（tagName、description、unit、equipmentName、count、values[{t,q,v}]、stats）、dataSource、notes。"
        ),
        defaults={"limit": 10},
        heavy=True,
    ),
    # ------------------------------------------------------------------ 工艺限值
    ToolSpec(
        name="query_equipment_groups",
        description=(
            "查询标准设备组（本体层面的设备归类，共 120 个：设备组 → 实例 → 部件 → 本体属性）。"
            "问'水解罐有哪几台''这类设备包括哪些实例''这组设备有什么部件和关键测点'时使用。"
            "注意区分：设备组是本体分类（如 水解反应釜组(水解罐A–K)），设备实例才是 DCS 点表里的具体设备（如 水解罐A）。"
        ),
        path="/api/ontology/equipment-groups",
        parameters=[
            ToolParameter("areaId", "string", "按工段过滤，可传 area-S11 / S11 / 酶法水解。"),
            ToolParameter("equipmentType", "string", "按设备类型过滤，如 储罐、泵、碟片离心机、管道混合器。"),
            ToolParameter("keyword", "string", "在设备组名称、URI、实例清单中做子串匹配。"),
            ToolParameter("limit", "integer", "返回条数上限。"),
            ToolParameter("offset", "integer", "跳过条数，与 limit 配合分页。"),
        ],
        defaults={"limit": 30},
        group="structure",
        summary="标准设备组清单（设备组→实例→部件→属性）",
        returns="items[]：设备组 id（egrp-xxxxxxxx）、uri、name、所属工段、equipmentType、instances（实例清单）、components（主要部件）、keyTags（画面关键测点）、properties（本体属性）、tagCount、equipmentCount；facets 给出可选的设备类型与工段编号。",
    ),
    ToolSpec(
        name="query_equipment_group_detail",
        description=(
            "查询单个标准设备组的详情：它包含哪些设备实例、挂了哪些 DCS 点、属于哪个工段。"
            "group_id 可以传 egrp-xxxxxxxx、设备组 URI（如 :FiltratePumpGroup）或设备组名称。"
        ),
        path="/api/ontology/equipment-groups/{group_id}",
        parameters=[
            ToolParameter("group_id", "string", "设备组 ID / URI / 名称。", required=True),
        ],
        group="structure",
        summary="单个设备组的实例、部件与关联点位",
        returns="设备组基本信息 + area（所属工段）+ equipment（设备实例列表）+ tags（关联点位，最多 200 条，超出部分由 tagsTruncated 说明）。",
    ),
    ToolSpec(
        name="query_area_flow",
        description=(
            "查询工段之间的上下游衔接（全流程 40 条，每条带衔接物料与位号说明）。"
            "问'上游停了会影响哪些工段''这个工段的物料从哪来、去哪里''全流程是怎么串起来的'时使用。"
            "不传 areaId 返回全部衔接；传 areaId 只返回该工段的进出。"
        ),
        path="/api/ontology/area-flow",
        parameters=[
            ToolParameter("areaId", "string", "工段 area-S11 / S11 / 酶法水解；不传则返回全流程。"),
        ],
        group="structure",
        summary="工段之间的上下游衔接与衔接物料",
        returns="不传 areaId 时返回 items[]（upstreamCode/upstreamName/material/downstreamCode/downstreamName/note/confidence）；传 areaId 时返回 upstream[] 与 downstream[] 两组。",
    ),
    ToolSpec(
        name="query_process_limits",
        description=(
            "查询工艺限值（参数的上下限与四档报警限：低低限 LL / 低限 L / 正常区间 / 高限 H / 高高限 HH）。"
            "问'水解温度应该控制在多少''pH 的上下限是多少''这个参数超没超标准'时使用。"
            "限值来自独立的工艺限值数据源，不是本体自动生成的。"
            "每条都带 status（待现场确认 / 待现场提供 / 已确认）、confidence 置信度与 basis 依据："
            "**只有 status 为「已确认」的才是正式工艺依据**，其余只能作为工艺调查的参考，回答时必须说明这一点；"
            "hasValues=false 的条目是「待现场提供」的空行，说明该参数的限值现场还没给，不要替它编数字。"
            "返回 available=false 时说明限值数据源尚未提供。"
        ),
        path="/api/ontology/process-limits",
        parameters=(
            ToolParameter("keyword", "string", "按对象名称、参数、依据文本搜索，如 温度、pH、水解。"),
            ToolParameter("area", "string", "按工段过滤，如 水解工段、结晶工段。"),
            ToolParameter("appliesToType", "string", "按适用对象类型过滤：工艺属性 / 质量指标 / 业务指标 / 设备 / 参数 / DCS点。"),
            ToolParameter("status", "string", "按确认状态过滤：待现场确认 / 待现场提供 / 已确认。"),
            ToolParameter("hasValues", "boolean", "true 只看已填数值的限值，false 只看待现场提供的空行。"),
        ),
        group="limits",
        summary="工艺限值清单（四档报警限 + 正常区间）",
        returns=(
            "items[]：适用对象、工况、参数、单位、lowLow/low/normalLow/normalHigh/high/highHigh、"
            "basis 依据、confidence 置信度、status 确认状态、targetCount 覆盖测点数、来源行号；"
            "statusSummary 统计；available / emptyReason。"
        ),
        heavy=True,
    ),
    ToolSpec(
        name="query_object_limits",
        description=(
            "查询某个本体对象适用哪些工艺限值。"
            "object_id 可以是设备 equip-、参数 param-、DCS点 tag-、关系对象 robj-、工段 area-，或 :Dev_13_水解罐A。"
            "问'水解罐A 的温度该控制在多少'时，先用 query_equipment_list 拿到设备 ID，再用本工具。"
        ),
        path="/api/ontology/{object_id}/limits",
        parameters=(
            ToolParameter("object_id", "string", "本体对象 ID 或 OWL Subject。", required=True),
        ),
        group="limits",
        summary="某个对象适用哪些工艺限值",
        returns="scope 对象、items[] 适用的限值（含 matchedTargetCount 落到本对象的测点数）、来源。",
        heavy=True,
    ),
    ToolSpec(
        name="query_limit_check",
        description=(
            "取对象的当前值，逐个测点与工艺限值比对，判断是否越限。"
            "问'现在有没有超温''这台罐子参数正常吗''哪几台罐超了'时使用。"
            "返回 summary 按状态计数，results 里每个测点带 value、statusLabel（正常 / 超出正常区间 / 高于高限 / 高于高高限 等）与偏差。"
            "需要本体服务已接入实时库；dataSource.simulated 为 true 时必须说明数值是模拟数据；"
            "限值 status 非「已确认」时，必须说明越限结论仅供参考、限值待现场确认。"
        ),
        path="/api/ontology/{object_id}/limit-check",
        parameters=(
            ToolParameter("object_id", "string", "本体对象 ID 或 OWL Subject。", required=True),
            ToolParameter("keyword", "string", "只看该对象下某类测点，如 温度。"),
        ),
        group="limits",
        summary="取当前值与限值比对，判断是否越限",
        returns="scope、limitCount、checked、summary（各状态计数）、results[]（测点、当前值、限值区间、判断、偏差）、dataSource。",
        heavy=True,
    ),
]


def build_ontology_registry(compact_relations: bool = False) -> ToolRegistry:
    """装配本体 Tool Registry。

    compact_relations=True 时，关系查询默认走精简视图——本地模型上下文紧张时用，
    一条关系约 300 字节而不是 1.8 KB。这只是改一个默认入参，不改工具集合。
    """
    from backend.tools.analysis_tools import ANALYSIS_TOOLS
    from backend.tools.calculations import CALCULATION_TOOLS
    from backend.tools.discovery import DISCOVERY_TOOL

    specs = list(ONTOLOGY_TOOLS) + list(ANALYSIS_TOOLS) + list(CALCULATION_TOOLS)
    if compact_relations:
        specs = [
            replace(spec, defaults={**spec.defaults, "view": "compact"})
            if spec.name == "query_relations"
            else spec
            for spec in specs
        ]
    return ToolRegistry(specs + [DISCOVERY_TOOL])
