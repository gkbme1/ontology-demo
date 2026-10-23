/*
 * 6-APA 生产线工业本体 Demo · 视图层
 *
 * 所有数据均通过 OntologyApi 获取（static 快照或 live REST），
 * 页面不内置任何设备、点位、关系或规则数据。
 */
(function (global) {
  'use strict';

  var api = global.OntologyApi;
  var $ = function (sel, root) { return (root || document).querySelector(sel); };

  // ------------------------------------------------------------ 工具

  function esc(v) {
    if (v === null || v === undefined) return '';
    return String(v).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function n(v) { return (v === null || v === undefined) ? '—' : Number(v).toLocaleString('zh-CN'); }
  function dash(v) { return (v === null || v === undefined || v === '') ? '—' : esc(v); }

  var NODE_COLORS = {};
  var CATEGORIES = [];
  var CORE = [];
  var EDGE_STYLES = [];

  function colorFor(type) { return NODE_COLORS[type] || '#6b7a90'; }

  function matchPill(status, label) {
    var cls = status === 'MATCHED' ? 'pill-ok' : 'pill-mute';
    return '<span class="tag-pill ' + cls + '">' + esc(label || (status === 'MATCHED' ? '已匹配本体实例' : '未匹配DCS实例')) + '</span>';
  }

  function typePill(type) {
    var c = colorFor(type);
    return '<span class="tag-pill pill-plain"><i class="swatch" style="background:' + c + '"></i>' + esc(type || '未标注') + '</span>';
  }

  function sourceBox(title, source, sourceType) {
    if (!source) return '';
    var rows = [];
    if (source.file) rows.push(['文件', source.file]);
    if (source.sheet) rows.push(['Sheet', source.sheet]);
    if (source.row) rows.push(['行号', source.row]);
    if (source.field) rows.push(['原始字段', source.field]);
    if (source.value) rows.push(['原始值', source.value]);
    if (sourceType) rows.unshift(['sourceType', sourceType]);
    return '<div class="source-box"><div class="hd">' + esc(title || '数据来源') + '</div><dl class="kv">' +
      rows.map(function (r) {
        return '<dt>' + esc(r[0]) + '</dt><dd class="mono">' + esc(r[1]) + '</dd>';
      }).join('') + '</dl></div>';
  }

  function emptyState(title, body) {
    return '<div class="empty"><strong>' + esc(title) + '</strong>' + esc(body || '') + '</div>';
  }

  // ------------------------------------------------------------ 状态

  var S = {
    view: 'overview',
    areaId: null,
    equipmentId: null,
    parameterId: null,
    entityId: null,
    relationId: null,
    categoryKey: null,
    depth: 1,
    showDcs: false,
    graphFilters: {},
    relFilters: {},
    inspector: null,
    crumbs: []
  };

  var graph = null;

  function go(patch) {
    Object.assign(S, patch);
    render();
    var canvas = $('#canvas');
    if (canvas) canvas.scrollTop = 0;
  }

  // ------------------------------------------------------------ 导航

  function railHtml() {
    function item(view, label, count, opts) {
      opts = opts || {};
      var active = (opts.activeWhen ? opts.activeWhen() : S.view === view);
      return '<button class="rail-item' + (active ? ' is-active' : '') + (opts.core ? ' is-core' : '') +
        '" data-nav="' + esc(view) + '"' + (opts.categoryKey ? ' data-cat="' + esc(opts.categoryKey) + '"' : '') + '>' +
        (opts.idx ? '<span class="idx">' + esc(opts.idx) + '</span>' : '') +
        '<span>' + esc(label) + '</span>' +
        (count != null ? '<span class="count">' + n(count) + '</span>' : '') +
        '</button>';
    }

    var nav = [
      '<div class="rail-group"><div class="rail-title">生产线</div>',
      item('overview', '本体总览'),
      item('areas', '工段与设备', null, {
        activeWhen: function () { return ['areas', 'area', 'equipment', 'parameter'].indexOf(S.view) >= 0; }
      }),
      item('graph', '关系图谱', null, {
        activeWhen: function () { return S.view === 'graph' || S.view === 'entity'; }
      }),
      item('relations', '关系清单'),
      item('entities', '关系对象'),
      '</div>'
    ].join('');

    var cats = ['<div class="rail-group"><div class="rail-title">本体分类 · 12 项</div>'];
    CATEGORIES.forEach(function (c) {
      cats.push(
        '<button class="rail-item' + (S.view === 'category' && S.categoryKey === c.key ? ' is-active' : '') +
        (c.core ? ' is-core' : '') + '" data-nav="category" data-cat="' + esc(c.key) + '">' +
        '<span class="idx">' + String(c.index) + '</span>' +
        '<span>' + esc(c.name) + '</span>' +
        '<span class="count">' + n(c.count) + '</span></button>'
      );
    });
    cats.push('</div>');

    var gov = [
      '<div class="rail-group"><div class="rail-title">数据治理</div>',
      item('sources', '数据源管理'),
      item('quality', '数据质量'),
      item('api', 'API 接口'),
      '</div>'
    ].join('');

    return nav + cats.join('') + gov;
  }

  function crumbsHtml() {
    if (!S.crumbs.length) return '';
    var parts = S.crumbs.map(function (c, i) {
      var last = i === S.crumbs.length - 1;
      if (last) return '<span class="now">' + esc(c.label) + '</span>';
      return '<button data-crumb="' + i + '">' + esc(c.label) + '</button><span class="sep">/</span>';
    });
    return '<nav class="crumbs">' + parts.join('') + '</nav>';
  }

  // ------------------------------------------------------------ 视图：总览

  function viewOverview(done) {
    Promise.all([api.getOverview(), api.getProcessAreas(), api.getRelations({}), api.getDataSources()])
      .then(function (r) {
        var o = r[0], areas = r[1].items, rels = r[2].items, sources = r[3];
        var byCat = {};
        rels.forEach(function (x) { byCat[x.category] = (byCat[x.category] || 0) + 1; });

        var stats = [
          ['生产工段', o.processAreaCount, '', 'is-accent'],
          ['控制站', o.controlStationCount, '', ''],
          ['设备 / 装置', o.equipmentCount, '', ''],
          ['参数语义', o.parameterCount, '', ''],
          ['DCS 点位', o.tagCount, '', 'is-accent'],
          ['工业关系', o.relationCount, '', ''],
          ['关系对象', o.relationObjectCount, '', ''],
          ['测量锚点', o.measurementAnchorCount, '', '']
        ].map(function (s) {
          return '<div class="stat ' + s[3] + '"><div class="k">' + esc(s[0]) + '</div>' +
            '<div class="v">' + n(s[1]) + '<span class="u">' + esc(s[2]) + '</span></div></div>';
        }).join('');

        var t = o.tagStats;
        var tagStats = [
          ['过程测量 PV', t.pv, '#35c4d7'], ['控制输出 OP', t.op, '#4c8dff'],
          ['电机控制 MOT', t.mot, '#ff9f45'], ['阀门控制 VAL', t.val, '#b07cff'],
          ['开关/状态 DI·DO', t.dido, '#6f819e']
        ];
        var maxTag = Math.max.apply(null, tagStats.map(function (x) { return x[1]; }));
        var tagBars = tagStats.map(function (x) {
          return '<tr><td>' + esc(x[0]) + '</td><td class="num mono">' + n(x[1]) + '</td>' +
            '<td style="width:44%"><div class="bar"><i style="width:' +
            (100 * x[1] / maxTag).toFixed(1) + '%;background:' + x[2] + '"></i></div></td></tr>';
        }).join('');

        var areaRows = areas.map(function (a) {
          return '<tr data-area="' + esc(a.id) + '">' +
            '<td><strong>' + esc(a.nameZh) + '</strong><div class="mono" style="color:var(--muted);font-size:11px">' +
            esc(a.nameEn || '') + '</div></td>' +
            '<td class="mono">' + esc(a.stations.join('、')) + '</td>' +
            '<td class="num mono">' + n(a.equipmentCount) + '</td>' +
            '<td class="num mono">' + n(a.parameterCount) + '</td>' +
            '<td class="num mono">' + n(a.tagCount) + '</td>' +
            '<td class="num mono">' + (a.relationCount ? n(a.relationCount) : '<span style="color:var(--muted)">—</span>') + '</td>' +
            '</tr>';
        }).join('');

        var catRows = Object.keys(byCat).sort(function (a, b) { return byCat[b] - byCat[a]; }).map(function (k) {
          var style = EDGE_STYLES.filter(function (s) { return s.category === k; })[0] || {};
          return '<tr data-relcat="' + esc(k) + '"><td><span class="tag-pill pill-plain">' +
            '<i class="swatch" style="background:' + (style.color || '#8fa6c4') + '"></i>' + esc(k) + '</span></td>' +
            '<td class="num mono">' + n(byCat[k]) + '</td>' +
            '<td style="width:52%"><div class="bar"><i style="width:' +
            (100 * byCat[k] / rels.length).toFixed(1) + '%;background:' + (style.color || '#8fa6c4') + '"></i></div></td></tr>';
        }).join('');

        var srcCards = sources.sources.map(function (s) {
          var sheets = (s.sheets || []).map(function (sh) {
            return '<li><span class="mono">' + esc(sh.sheet) + '</span>' +
              '<span style="color:var(--muted);float:right" class="mono">' + n(sh.rows) + ' 行</span></li>';
          }).join('');
          return '<div class="panel" style="margin:0">' +
            '<div class="panel-head"><h3>' + esc(s.sourceTypeLabel) + '</h3>' +
            '<div class="right">' + (s.available
              ? '<span class="tag-pill pill-ok">已加载</span>'
              : '<span class="tag-pill pill-mute">未提供</span>') + '</div></div>' +
            '<div class="panel-body"><div class="mono" style="margin-bottom:6px">' + esc(s.file) + '</div>' +
            '<p class="note-line">' + esc(s.note || '') + '</p>' +
            (sheets ? '<ul class="list-plain">' + sheets + '</ul>' : '') + '</div></div>';
        }).join('');

        done(
          '<div class="view-head"><h2>6-APA 生产线工业本体</h2>' +
          '<p>以下全部数字由现场 DCS 点表与工业关系 Excel 实时统计得出，' +
          '不含任何示例或 Mock 数据。数据加载时间 ' + esc(o.loadedAt) + '。</p></div>' +
          '<div class="stat-row">' + stats + '</div>' +

          '<div class="panel"><div class="panel-head"><h3>生产工段</h3>' +
          '<span class="note">点击进入工段 → 设备 → 参数 → DCS 点</span></div>' +
          '<div class="panel-body flush"><div class="tbl-wrap"><table class="tbl"><thead><tr>' +
          '<th>工段</th><th>控制站</th><th class="num">设备</th><th class="num">参数语义</th>' +
          '<th class="num">DCS 点</th><th class="num">关系</th></tr></thead><tbody>' + areaRows +
          '</tbody></table></div></div></div>' +

          '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:18px;margin-bottom:18px">' +
          '<div class="panel" style="margin:0"><div class="panel-head"><h3>DCS 点位构成</h3>' +
          '<span class="note">共 ' + n(o.tagCount) + ' 点</span></div><div class="panel-body flush">' +
          '<table class="tbl"><tbody>' + tagBars + '</tbody></table></div></div>' +
          '<div class="panel" style="margin:0"><div class="panel-head"><h3>关系大类分布</h3>' +
          '<span class="note">共 ' + n(rels.length) + ' 条关系</span></div><div class="panel-body flush">' +
          '<table class="tbl"><tbody>' + catRows + '</tbody></table></div></div>' +
          '</div>' +

          '<div class="panel-head" style="background:none;border:0;padding:0 0 10px"><h3>数据源</h3>' +
          '<span class="note">DCS 事实 / 关系事实 / 对象对齐 / 推理规则 四类数据源相互独立</span></div>' +
          '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(272px,1fr));gap:14px">' +
          srcCards + '</div>'
        );
      });
  }

  // ------------------------------------------------------------ 视图：工段

  function viewAreas(done) {
    api.getProcessAreas().then(function (res) {
      var rows = res.items.map(function (a) {
        return '<tr data-area="' + esc(a.id) + '">' +
          '<td><strong>' + esc(a.nameZh) + '</strong></td>' +
          '<td class="mono" style="color:var(--muted)">' + esc(a.nameEn || '') + '</td>' +
          '<td class="mono">' + esc(a.stations.join('、')) + '</td>' +
          '<td class="num mono">' + n(a.equipmentCount) + '</td>' +
          '<td class="num mono">' + n(a.tagCount) + '</td>' +
          '<td class="num mono">' + (a.relationCount || '—') + '</td></tr>';
      }).join('');
      done('<div class="view-head"><h2>生产工段</h2><p>工段实例来自 DCS 点表「所属工段」字段，' +
        '共 ' + res.total + ' 个工段。关系列统计的是工业关系 Excel 中经对象映射对齐到该工段的关系数。</p></div>' +
        '<div class="panel"><div class="panel-body flush"><div class="tbl-wrap"><table class="tbl"><thead><tr>' +
        '<th>工段</th><th>英文名</th><th>控制站</th><th class="num">设备</th>' +
        '<th class="num">DCS 点</th><th class="num">关系</th></tr></thead><tbody>' + rows +
        '</tbody></table></div></div></div>');
    });
  }

  function viewArea(done) {
    Promise.all([api.getProcessArea(S.areaId), api.getRelationEntities({})]).then(function (r) {
      var a = r[0], allEntities = r[1].items;
      if (!a) return done(emptyState('未找到该工段', ''));

      var relNames = a.relationAreaNames || [];
      var entities = allEntities.filter(function (e) {
        return e.areas.some(function (x) { return relNames.indexOf(x) >= 0; });
      });

      var equipRows = a.equipment.slice(0, 400).map(function (e) {
        var s = e.stats;
        return '<tr data-equip="' + esc(e.id) + '">' +
          '<td><strong>' + esc(e.name) + '</strong></td>' +
          '<td class="mono" style="color:var(--muted);font-size:11px">' + esc(e.owlSubject) + '</td>' +
          '<td class="num mono">' + n(e.tagCount) + '</td>' +
          '<td class="num mono">' + n(e.parameterCount) + '</td>' +
          '<td class="num mono">' + n(s.pv) + '</td><td class="num mono">' + n(s.op) + '</td>' +
          '<td class="num mono">' + n(s.val) + '</td><td class="num mono">' + n(s.dido) + '</td></tr>';
      }).join('');

      var catCounts = a.relationCategoryCounts || {};
      var catChips = Object.keys(catCounts).map(function (k) {
        var st = EDGE_STYLES.filter(function (s) { return s.category === k; })[0] || {};
        return '<span class="tag-pill pill-plain"><i class="swatch" style="background:' +
          (st.color || '#8fa6c4') + '"></i>' + esc(k) + ' · ' + catCounts[k] + '</span>';
      }).join(' ');

      var entRows = entities.map(function (e) {
        return '<tr data-entity="' + esc(e.id) + '">' +
          '<td><strong>' + esc(e.name) + '</strong></td>' +
          '<td>' + typePill(e.type) + '</td>' +
          '<td class="num mono">' + n(e.relationCount) + '</td>' +
          '<td>' + matchPill(e.matchStatus, e.matchStatusLabel) + '</td>' +
          '<td class="num mono">' + (e.tagCount ? n(e.tagCount) : '—') + '</td></tr>';
      }).join('');

      done(
        '<div class="view-head"><h2>' + esc(a.nameZh) + '</h2>' +
        '<p class="mono" style="color:var(--muted)">' + esc(a.name) + '</p></div>' +
        '<div class="stat-row">' +
        '<div class="stat"><div class="k">控制站</div><div class="v">' + esc(a.stations.join('、')) + '</div></div>' +
        '<div class="stat"><div class="k">设备 / 装置</div><div class="v">' + n(a.equipmentCount) + '</div></div>' +
        '<div class="stat"><div class="k">参数语义</div><div class="v">' + n(a.parameterCount) + '</div></div>' +
        '<div class="stat is-accent"><div class="k">DCS 点位</div><div class="v">' + n(a.tagCount) + '</div></div>' +
        '<div class="stat"><div class="k">工业关系</div><div class="v">' + n(a.relationCount || 0) + '</div></div>' +
        '</div>' +

        (entities.length
          ? '<div class="panel"><div class="panel-head"><h3>工艺对象</h3>' +
            '<span class="note">来自工业关系 Excel · ' + esc(relNames.join('、')) + '</span>' +
            '<div class="right">' + catChips + '</div></div>' +
            '<div class="panel-body flush"><div class="tbl-wrap"><table class="tbl"><thead><tr>' +
            '<th>对象语义名称</th><th>对象类型</th><th class="num">关系数</th><th>匹配状态</th>' +
            '<th class="num">测点</th></tr></thead><tbody>' + entRows + '</tbody></table></div></div></div>'
          : '<div class="panel"><div class="panel-head"><h3>工艺对象</h3></div><div class="panel-body">' +
            emptyState('该工段暂无工业关系数据', '当前工业关系 Excel 覆盖水解工段、萃取工段与跨工段协同三个范围。') +
            '</div></div>') +

        '<div class="panel"><div class="panel-head"><h3>设备 / 装置</h3>' +
        '<span class="note">来自 DCS 点表 · 按点位数排序' +
        (a.equipment.length > 400 ? '（显示前 400 台，共 ' + n(a.equipment.length) + ' 台）' : '') + '</span></div>' +
        '<div class="panel-body flush"><div class="tbl-wrap scroll-y"><table class="tbl"><thead><tr>' +
        '<th>设备名称</th><th>OWL Subject</th><th class="num">点位</th><th class="num">参数</th>' +
        '<th class="num">PV</th><th class="num">OP</th><th class="num">VAL</th><th class="num">DI/DO</th>' +
        '</tr></thead><tbody>' + equipRows + '</tbody></table></div></div></div>'
      );
    });
  }

  // ------------------------------------------------------------ 视图：设备

  function viewEquipment(done) {
    api.getEquipmentDetail(S.equipmentId).then(function (e) {
      if (!e) return done(emptyState('未找到该设备', ''));
      var s = e.stats, s1 = e.statsFromSheet1 || {};

      var paramRows = e.parameters.map(function (p) {
        var tags = e.tags.filter(function (t) { return t.parameterId === p.id; });
        return '<tr data-param="' + esc(p.id) + '">' +
          '<td><strong>' + esc(p.name) + '</strong></td>' +
          '<td>' + (p.categories || []).map(function (c) {
            return '<span class="tag-pill pill-plain">' + esc(c) + '</span>';
          }).join(' ') + '</td>' +
          '<td class="mono">' + dash((p.units || []).join('、')) + '</td>' +
          '<td class="mono">' + dash((p.blockTypes || []).join('、')) + '</td>' +
          '<td class="mono">' + tags.map(function (t) { return esc(t.name); }).join('、') + '</td></tr>';
      }).join('');

      var relRows = e.relations.length ? e.relations.map(function (r) {
        return '<tr data-rel="' + esc(r.id) + '">' +
          '<td>' + esc(r.subjectEntity) + '</td>' +
          '<td><span class="tag-pill pill-info">' + esc(r.predicate) + '</span></td>' +
          '<td>' + esc(r.objectEntity) + '</td>' +
          '<td>' + esc(r.category) + '</td>' +
          '<td style="color:var(--text-2)">' + esc(r.domainDescription) + '</td></tr>';
      }).join('') : '';

      var mismatch = (s1.totalPoints != null && s1.totalPoints !== s.total)
        ? '<div class="warn-line"><span>⚠</span><div>Sheet1「设备统计」声明 <b>' + n(s1.totalPoints) +
          '</b> 点，Sheet2「DCS点位明细」实际 <b>' + n(s.total) + '</b> 点，已记入数据质量报告，未做任何修正。</div></div>'
        : '';

      done(
        '<div class="view-head"><h2>' + esc(e.name) + '</h2>' +
        '<p>所属工段 ' + esc((e.area || {}).nameZh || '') + ' · 控制站 ' + esc(e.station) +
        ' · <span class="mono">' + esc(e.owlSubject) + '</span></p></div>' +
        mismatch +
        '<div class="stat-row">' +
        '<div class="stat is-accent"><div class="k">总点位</div><div class="v">' + n(s.total) + '</div></div>' +
        '<div class="stat"><div class="k">过程测量 PV</div><div class="v">' + n(s.pv) + '</div></div>' +
        '<div class="stat"><div class="k">控制输出 OP</div><div class="v">' + n(s.op) + '</div></div>' +
        '<div class="stat"><div class="k">电机控制 MOT</div><div class="v">' + n(s.mot) + '</div></div>' +
        '<div class="stat"><div class="k">阀门控制 VAL</div><div class="v">' + n(s.val) + '</div></div>' +
        '<div class="stat"><div class="k">开关反馈 DI/DO</div><div class="v">' + n(s.dido) + '</div></div>' +
        '<div class="stat"><div class="k">参数语义</div><div class="v">' + n(e.parameterCount) + '</div></div>' +
        '</div>' +

        (e.overview ? '<p class="note-line"><b style="color:var(--text-2)">核心参数/测点概览：</b>' + esc(e.overview) + '</p>' : '') +

        '<div class="panel"><div class="panel-head"><h3>设备参数 → DCS 点</h3>' +
        '<span class="note">设备 / 参数语义 / DCS 点三层语义模型</span>' +
        '<div class="right"><button class="ctl" data-graph-equip="' + esc(e.id) + '">查看关系图</button></div></div>' +
        '<div class="panel-body flush"><div class="tbl-wrap scroll-y"><table class="tbl"><thead><tr>' +
        '<th>参数语义名称</th><th>参数分类</th><th>工程单位</th><th>DCS 块</th><th>DCS 点名</th>' +
        '</tr></thead><tbody>' + paramRows + '</tbody></table></div></div></div>' +

        '<div class="panel"><div class="panel-head"><h3>设备关系</h3>' +
        '<span class="note">经对象映射对齐到本设备的工业关系</span></div>' +
        '<div class="panel-body' + (relRows ? ' flush' : '') + '">' +
        (relRows
          ? '<div class="tbl-wrap"><table class="tbl"><thead><tr><th>起始对象</th><th>关系谓词</th>' +
            '<th>目标对象</th><th>关系大类</th><th>工艺机理与业务因果说明</th></tr></thead><tbody>' +
            relRows + '</tbody></table></div>'
          : emptyState('该设备当前无关联工业关系',
              '工业关系 Excel 覆盖水解工段与萃取工段的核心工艺对象；关系不会根据设备名称自动推断。')) +
        '</div></div>' +

        '<div class="panel"><div class="panel-head"><h3>关联规则</h3></div><div class="panel-body">' +
        (e.rules && e.rules.length ? '' : emptyState('当前暂无规则数据源',
          '规则必须来自独立规则 Excel / 规则文件，系统不会根据参数名称自动生成生产判断规则。')) +
        '</div></div>'
      );
    });
  }

  // ------------------------------------------------------------ 视图：参数

  function viewParameter(done) {
    api.getParameterDetail(S.parameterId).then(function (p) {
      if (!p) return done(emptyState('未找到该参数', ''));

      var anchors = p.measurementAnchors.map(function (a) {
        return '<div class="chain">' +
          '<div class="chain-node"><span class="lbl">工业语义</span><span class="val">' + esc(a.semanticName) + '</span>' +
          '<span class="tag-pill pill-plain" style="margin-left:auto">' + esc(a.parameterType || '') + '</span></div>' +
          '<div class="chain-arrow"></div>' +
          '<div class="chain-node"><span class="lbl">DCS Tag</span><span class="val mono">' + esc(a.tagName) + '</span>' +
          '<span style="margin-left:auto;color:var(--muted)">' + esc(a.rawDescription || '') + '</span></div>' +
          '<div class="chain-arrow"></div>' +
          '<div class="chain-node"><span class="lbl">DCS 块</span><span class="val mono">' + esc(a.blockType) + '</span>' +
          '<span style="margin-left:auto;color:var(--muted)">工程单位 ' + dash(a.unit) + ' · 控制站 ' + esc(a.station) + '</span></div>' +
          '</div>';
      }).join('<div style="height:14px"></div>');

      var entRows = p.relationEntities.length ? p.relationEntities.map(function (e) {
        return '<tr data-entity="' + esc(e.id) + '"><td><strong>' + esc(e.name) + '</strong></td>' +
          '<td>' + typePill(e.type) + '</td><td class="num mono">' + n(e.relationCount) + '</td>' +
          '<td>' + esc(e.matchStrategyLabel || '') + '</td></tr>';
      }).join('') : '';

      done(
        '<div class="view-head"><h2>' + esc(p.name) + '</h2>' +
        '<p>所属设备 ' + esc(p.equipmentName) + ' · 工段 ' + esc(p.areaName || '') +
        ' · <span class="mono">' + esc(p.owlSubject) + '</span></p></div>' +

        '<div class="panel"><div class="panel-head"><h3>参数语义</h3></div><div class="panel-body">' +
        '<dl class="kv" style="grid-template-columns:120px 1fr">' +
        '<dt>名称</dt><dd>' + esc(p.name) + '</dd>' +
        '<dt>参数分类</dt><dd>' + (p.categories || []).join('、') + '</dd>' +
        '<dt>工程单位</dt><dd class="mono">' + dash((p.units || []).join('、')) + '</dd>' +
        '<dt>DCS 块类型</dt><dd class="mono">' + dash((p.blockTypes || []).join('、')) + '</dd>' +
        '<dt>所属设备</dt><dd>' + esc(p.equipmentName) + '</dd>' +
        '<dt>OWL Subject</dt><dd class="mono">' + esc(p.owlSubject) + '</dd>' +
        '<dt>绑定 DCS 点</dt><dd class="mono">' + p.tags.map(function (t) { return esc(t.name); }).join('、') + '</dd>' +
        '</dl></div></div>' +

        '<div class="panel"><div class="panel-head"><h3>测量锚点</h3>' +
        '<span class="note">工业语义 → DCS Tag → DCS 块</span></div>' +
        '<div class="panel-body">' + (anchors || emptyState('当前暂无对应 DCS 测点', '')) + '</div></div>' +

        '<div class="panel"><div class="panel-head"><h3>关联工艺对象</h3>' +
        '<span class="note">哪些关系对象以本参数作为测量锚点</span></div>' +
        '<div class="panel-body' + (entRows ? ' flush' : '') + '">' +
        (entRows
          ? '<div class="tbl-wrap"><table class="tbl"><thead><tr><th>对象语义名称</th><th>对象类型</th>' +
            '<th class="num">关系数</th><th>匹配方式</th></tr></thead><tbody>' + entRows + '</tbody></table></div>'
          : emptyState('本参数暂未被工业关系 Excel 引用', '')) +
        '</div></div>'
      );
    });
  }

  // ------------------------------------------------------------ 视图：关系对象 / 关系图

  function graphToolbar(rootLabel) {
    var depths = [1, 2, 3].map(function (d) {
      return '<button class="ctl' + (S.depth === d ? ' is-on' : '') + '" data-depth="' + d + '">' + d + ' 跳</button>';
    }).join('');
    return '<div class="graph-depth">' + depths +
      '<button class="ctl' + (S.showDcs ? ' is-on' : '') + '" data-showdcs="1">DCS 实例</button></div>' +
      '<div class="graph-hint">滚轮缩放 · 拖拽平移 · 点击节点或关系边查看详情' +
      (rootLabel ? ' · 当前中心：' + esc(rootLabel) : '') + '</div>';
  }

  function legendHtml() {
    var nodes = (CORE_STYLES.nodes || []).map(function (s) {
      return '<span><i style="background:' + s.color + '"></i>' + esc(s.type) + '</span>';
    }).join('');
    return '<div class="graph-legend">' + nodes +
      '<span><i style="background:transparent;border:1px dashed var(--unmatched)"></i>未匹配 DCS 实例</span></div>';
  }

  var CORE_STYLES = { nodes: [], edges: [] };

  function viewEntity(done) {
    Promise.all([api.getRelationEntityDetail(S.entityId), api.getRelations({ entityId: S.entityId })])
      .then(function (r) {
        var e = r[0], rels = r[1].items;
        if (!e) return done(emptyState('未找到该关系对象', ''));

        var parts = e.outgoingRelations.filter(function (x) { return x.objectType === '设备部件'; });
        var props = e.outgoingRelations.filter(function (x) { return x.objectType === '工艺属性'; });

        function relTable(list, empty) {
          if (!list.length) return emptyState(empty, '');
          return '<div class="tbl-wrap"><table class="tbl"><thead><tr><th>关系谓词</th><th>对象</th>' +
            '<th>类型</th><th>子场景</th><th class="num">权重</th><th>工艺机理与业务因果说明</th>' +
            '</tr></thead><tbody>' + list.map(function (x) {
              var other = x.subject.id === S.entityId ? x.object : x.subject;
              return '<tr data-rel="' + esc(x.id) + '">' +
                '<td><span class="tag-pill pill-info">' + esc(x.predicate) + '</span></td>' +
                '<td data-entity-jump="' + esc(other.id) + '"><strong>' + esc(other.entity) + '</strong></td>' +
                '<td>' + typePill(other.type) + '</td>' +
                '<td>' + esc(x.scenario) + '</td>' +
                '<td class="num mono">' + esc(x.weight) + '</td>' +
                '<td style="color:var(--text-2)">' + esc(x.domainDescription) + '</td></tr>';
            }).join('') + '</tbody></table></div>';
        }

        var matchRows = e.matches.length ? e.matches.map(function (m) {
          return '<tr' + (m.objectType === 'equipment' ? ' data-equip="' + esc(m.id) + '"' :
            m.objectType === 'parameter' ? ' data-param="' + esc(m.id) + '"' : '') + '>' +
            '<td><strong>' + esc(m.name) + '</strong></td>' +
            '<td>' + esc({ equipment: '设备', parameter: '参数', area: '工段' }[m.objectType] || m.objectType) + '</td>' +
            '<td class="mono" style="font-size:11px">' + esc(m.owlSubject || m.equipmentName || '') + '</td>' +
            '<td>' + esc(m.strategyLabel) + '</td>' +
            '<td>' + (m.confidence
              ? '<span class="tag-pill ' + (m.confidence === '高' ? 'pill-ok' : m.confidence === '中' ? 'pill-warn' : 'pill-err') +
                '">' + esc(m.confidence) + '</span>' : '—') + '</td>' +
            '<td>' + (m.status ? '<span class="tag-pill pill-warn">' + esc(m.status) + '</span>' : '—') + '</td>' +
            '<td style="color:var(--text-2)">' + esc(m.note || '') + '</td></tr>';
        }).join('') : '';

        var anchorRows = e.measurementAnchors.length ? e.measurementAnchors.map(function (a) {
          return '<tr data-param="' + esc(a.parameterId) + '">' +
            '<td>' + esc(a.equipmentName) + '</td><td>' + esc(a.semanticName) + '</td>' +
            '<td class="mono">' + esc(a.tagName) + '</td><td class="mono">' + esc(a.blockType) + '</td>' +
            '<td class="mono">' + dash(a.unit) + '</td>' +
            '<td style="color:var(--text-2)">' + esc(a.rawDescription) + '</td></tr>';
        }).join('') : '';

        done(
          '<div class="view-head"><h2>' + esc(e.name) + '</h2>' +
          '<p>' + typePill(e.type) + ' ' + matchPill(e.matchStatus, e.matchStatusLabel) +
          (e.pendingConfirmation ? ' <span class="tag-pill pill-warn">映射待现场确认</span>' : '') +
          ' · 关系 ' + e.relationCount + ' 条 · 工段 ' + esc(e.areas.join('、')) + '</p></div>' +

          '<div class="panel"><div class="panel-head"><h3>局部语义图</h3>' +
          '<span class="note">默认展开一跳，可继续展开到二跳、三跳</span></div>' +
          '<div class="panel-body flush"><div class="graph-shell"><div id="graph-host" style="position:absolute;inset:0"></div>' +
          graphToolbar(e.name) + legendHtml() + '</div></div></div>' +

          '<div class="panel"><div class="panel-head"><h3>设备部件</h3>' +
          '<span class="note">predicate = 具有部件</span></div>' +
          '<div class="panel-body' + (parts.length ? ' flush' : '') + '">' +
          relTable(parts, '本对象无部件关系') + '</div></div>' +

          '<div class="panel"><div class="panel-head"><h3>工艺属性</h3>' +
          '<span class="note">predicate = 具有属性</span></div>' +
          '<div class="panel-body' + (props.length ? ' flush' : '') + '">' +
          relTable(props, '本对象无属性关系') + '</div></div>' +

          '<div class="panel"><div class="panel-head"><h3>全部关系</h3>' +
          '<span class="note">' + e.outgoingCount + ' 条出边 · ' + e.incomingCount + ' 条入边</span></div>' +
          '<div class="panel-body flush">' + relTable(rels, '无关系') + '</div></div>' +

          '<div class="panel"><div class="panel-head"><h3>匹配的本体实例</h3>' +
          '<span class="note">关系对象 → DCS 本体对象</span></div>' +
          '<div class="panel-body' + (matchRows ? ' flush' : '') + '">' +
          (matchRows
            ? '<div class="tbl-wrap scroll-y"><table class="tbl"><thead><tr><th>本体对象</th><th>类型</th>' +
              '<th>标识</th><th>匹配方式</th><th>置信度</th><th>确认状态</th><th>映射说明</th>' +
              '</tr></thead><tbody>' + matchRows + '</tbody></table></div>'
            : emptyState('未匹配 DCS 实例',
                '该关系对象已加载并保留为外部关系对象，未在 DCS 点表或对象映射表中找到对应实例，关系数据不会被丢弃。')) +
          '</div></div>' +

          '<div class="panel"><div class="panel-head"><h3>测量锚点</h3></div>' +
          '<div class="panel-body' + (anchorRows ? ' flush' : '') + '">' +
          (anchorRows
            ? '<div class="tbl-wrap scroll-y"><table class="tbl"><thead><tr><th>设备</th><th>参数语义</th>' +
              '<th>DCS 点名</th><th>DCS 块</th><th>单位</th><th>原点描述</th></tr></thead><tbody>' +
              anchorRows + '</tbody></table></div>'
            : emptyState('关系对象已加载，当前暂无对应 DCS 测点', '不虚构任何 DCS 点。')) +
          '</div></div>'
        );

        setTimeout(function () { mountGraph({ rootId: S.entityId, depth: S.depth }); }, 0);
      });
  }

  function viewGraph(done) {
    Promise.all([api.getRelations({}), api.getRelationEntities({})]).then(function (r) {
      var rels = r[0].items, entities = r[1].items;
      var f = S.graphFilters;

      function opts(values, current) {
        return ['<option value="">全部</option>'].concat(values.map(function (v) {
          return '<option value="' + esc(v) + '"' + (current === v ? ' selected' : '') + '>' + esc(v) + '</option>';
        })).join('');
      }
      function uniq(list, key) {
        var out = [];
        list.forEach(function (x) { if (x[key] && out.indexOf(x[key]) < 0) out.push(x[key]); });
        return out.sort();
      }

      var rootOpts = ['<option value="">（不指定中心，显示全部筛选结果）</option>'].concat(
        entities.map(function (e) {
          return '<option value="' + esc(e.id) + '"' + (f.rootId === e.id ? ' selected' : '') + '>' +
            esc(e.name) + ' · ' + esc(e.type) + '</option>';
        })).join('');

      done(
        '<div class="view-head"><h2>关系图谱</h2>' +
        '<p>关系边全部来自工业关系 Excel。系统不根据设备名称、编号或参数名称推断任何关系。</p></div>' +
        '<div class="panel"><div class="filters">' +
        '<label>中心对象<select class="ctl" data-gf="rootId" style="min-width:220px">' + rootOpts + '</select></label>' +
        '<label>工段<select class="ctl" data-gf="area">' + opts(uniq(rels, 'area'), f.area) + '</select></label>' +
        '<label>关系大类<select class="ctl" data-gf="category">' + opts(uniq(rels, 'category'), f.category) + '</select></label>' +
        '<label>关系谓词<select class="ctl" data-gf="predicate">' + opts(uniq(rels, 'predicate'), f.predicate) + '</select></label>' +
        '<label>起始对象类型<select class="ctl" data-gf="subjectType">' + opts(uniq(rels, 'subjectType'), f.subjectType) + '</select></label>' +
        '<label>目标对象类型<select class="ctl" data-gf="objectType">' + opts(uniq(rels, 'objectType'), f.objectType) + '</select></label>' +
        '<label>子场景<select class="ctl" data-gf="scenario">' + opts(uniq(rels, 'scenario'), f.scenario) + '</select></label>' +
        '<label>最小权重<input class="ctl" data-gf="minWeight" type="number" step="0.5" style="width:78px" value="' +
        esc(f.minWeight || '') + '"></label>' +
        '<label>最大权重<input class="ctl" data-gf="maxWeight" type="number" step="0.5" style="width:78px" value="' +
        esc(f.maxWeight || '') + '"></label>' +
        '<label>匹配状态<select class="ctl" data-gf="matched">' +
        '<option value="">全部</option>' +
        '<option value="1"' + (f.matched === true ? ' selected' : '') + '>仅已匹配 DCS 实例</option>' +
        '<option value="0"' + (f.matched === false ? ' selected' : '') + '>仅未匹配</option></select></label>' +
        '<label>&nbsp;<button class="ctl" data-gf-reset="1">重置筛选</button></label>' +
        '</div>' +
        '<div class="panel-body flush"><div class="graph-shell" style="height:640px">' +
        '<div id="graph-host" style="position:absolute;inset:0"></div>' +
        graphToolbar(null) + legendHtml() + '</div></div></div>'
      );

      setTimeout(function () {
        mountGraph(Object.assign({ depth: S.depth }, S.graphFilters));
      }, 0);
    });
  }

  function mountGraph(q) {
    var host = document.getElementById('graph-host');
    if (!host) return;
    q = Object.assign({ includeDcs: S.showDcs }, q);
    api.getGraph(q).then(function (g) {
      if (graph) graph.destroy();
      graph = new global.RelationGraph(host, {
        onNodeClick: function (node) { inspectNode(node); },
        onEdgeClick: function (edge) {
          if (edge.edgeKind === 'relation') return inspectRelation(edge.id);
          inspectStructuralEdge(edge);
        }
      });
      graph.render(g);
      var hint = host.parentElement.querySelector('.graph-hint');
      if (hint) {
        hint.innerHTML = '节点 ' + g.nodeCount + ' · 边 ' + g.edgeCount +
          (g.truncated ? ' · <span style="color:var(--warn)">已截断，请收紧筛选</span>' : '') +
          ' · 滚轮缩放 / 拖拽平移 / 点击查看详情';
      }
    });
  }

  function inspectNode(node) {
    if (node.nodeKind === 'relationEntity') { inspectEntity(node.id); return; }
    var id = String(node.id).replace(/^dcs::/, '');
    if (node.nodeKind === 'equipment') { inspectEquipment(id); return; }
    if (node.nodeKind === 'parameter') { inspectParameter(id); return; }
    if (node.nodeKind === 'tag') { inspectTag(id, node); return; }
    if (node.nodeKind === 'area') { go({ view: 'area', areaId: id }); }
  }

  // ------------------------------------------------------------ 视图：关系清单 / 关系对象

  function viewRelations(done) {
    api.getRelations({}).then(function (all) {
      var f = S.relFilters;
      api.getRelations(f).then(function (res) {
        function uniq(key) {
          var out = [];
          all.items.forEach(function (x) { if (x[key] && out.indexOf(x[key]) < 0) out.push(x[key]); });
          return out.sort();
        }
        function opts(values, current) {
          return ['<option value="">全部</option>'].concat(values.map(function (v) {
            return '<option value="' + esc(v) + '"' + (current === v ? ' selected' : '') + '>' + esc(v) + '</option>';
          })).join('');
        }

        var rows = res.items.map(function (r) {
          var st = EDGE_STYLES.filter(function (s) { return s.category === r.category; })[0] || {};
          return '<tr data-rel="' + esc(r.id) + '">' +
            '<td>' + esc(r.area) + '</td>' +
            '<td><span class="tag-pill pill-plain"><i class="swatch" style="background:' +
            (st.color || '#8fa6c4') + '"></i>' + esc(r.category) + '</span></td>' +
            '<td data-entity-jump="' + esc(r.subject.id) + '"><strong>' + esc(r.subjectEntity) + '</strong>' +
            '<div style="color:var(--muted);font-size:11px">' + esc(r.subjectType) + '</div></td>' +
            '<td><span class="tag-pill pill-info">' + esc(r.predicate) + '</span></td>' +
            '<td data-entity-jump="' + esc(r.object.id) + '"><strong>' + esc(r.objectEntity) + '</strong>' +
            '<div style="color:var(--muted);font-size:11px">' + esc(r.objectType) + '</div></td>' +
            '<td>' + esc(r.scenario) + '</td>' +
            '<td class="num mono">' + esc(r.weight) + '</td>' +
            '<td style="color:var(--text-2);max-width:260px">' + esc(r.domainDescription) + '</td>' +
            '<td>' + matchPill(r.matchStatus === 'MATCHED' ? 'MATCHED' : 'UNMATCHED',
              r.matchStatus === 'MATCHED' ? '双端已匹配' : r.matchStatus === 'PARTIAL' ? '单端已匹配' : '双端未匹配') + '</td>' +
            '<td class="mono" style="font-size:11px;color:var(--muted)">第 ' + esc(r.source.row) + ' 行</td></tr>';
        }).join('');

        done(
          '<div class="view-head"><h2>关系清单</h2>' +
          '<p>共 ' + all.total + ' 条关系，全部来自 <span class="mono">6APA_工业关系.xlsx</span> 的「关系明细」Sheet。' +
          '当前筛选命中 ' + res.total + ' 条。</p></div>' +
          '<div class="panel"><div class="filters">' +
          '<label>工段<select class="ctl" data-rf="area">' + opts(uniq('area'), f.area) + '</select></label>' +
          '<label>关系大类<select class="ctl" data-rf="category">' + opts(uniq('category'), f.category) + '</select></label>' +
          '<label>关系谓词<select class="ctl" data-rf="predicate">' + opts(uniq('predicate'), f.predicate) + '</select></label>' +
          '<label>起始对象类型<select class="ctl" data-rf="subjectType">' + opts(uniq('subjectType'), f.subjectType) + '</select></label>' +
          '<label>目标对象类型<select class="ctl" data-rf="objectType">' + opts(uniq('objectType'), f.objectType) + '</select></label>' +
          '<label>子场景<select class="ctl" data-rf="scenario">' + opts(uniq('scenario'), f.scenario) + '</select></label>' +
          '<label>最小权重<input class="ctl" data-rf="minWeight" type="number" step="0.5" style="width:78px" value="' +
          esc(f.minWeight || '') + '"></label>' +
          '<label>最大权重<input class="ctl" data-rf="maxWeight" type="number" step="0.5" style="width:78px" value="' +
          esc(f.maxWeight || '') + '"></label>' +
          '<label>关键词<input class="ctl" data-rf="keyword" placeholder="对象 / 谓词 / 机理说明" value="' +
          esc(f.keyword || '') + '"></label>' +
          '<label>&nbsp;<button class="ctl" data-rf-reset="1">重置</button></label>' +
          '</div><div class="panel-body flush"><div class="tbl-wrap"><table class="tbl"><thead><tr>' +
          '<th>工段</th><th>关系大类</th><th>起始对象</th><th>谓词</th><th>目标对象</th>' +
          '<th>子场景</th><th class="num">权重</th><th>工艺机理与业务因果说明</th><th>匹配</th><th>来源</th>' +
          '</tr></thead><tbody>' + rows + '</tbody></table></div></div></div>'
        );
      });
    });
  }

  function viewEntities(done) {
    api.getRelationEntities({}).then(function (res) {
      var byType = {};
      res.items.forEach(function (e) {
        (byType[e.type || '未标注'] = byType[e.type || '未标注'] || []).push(e);
      });
      var matched = res.items.filter(function (e) { return e.matchStatus === 'MATCHED'; }).length;

      var blocks = Object.keys(byType).map(function (t) {
        var rows = byType[t].map(function (e) {
          return '<tr data-entity="' + esc(e.id) + '">' +
            '<td><strong>' + esc(e.name) + '</strong></td>' +
            '<td class="num mono">' + n(e.relationCount) + '</td>' +
            '<td class="mono">' + e.outgoingCount + ' / ' + e.incomingCount + '</td>' +
            '<td>' + matchPill(e.matchStatus, e.matchStatusLabel) + '</td>' +
            '<td>' + esc(e.matchStrategyLabel) + '</td>' +
            '<td class="num mono">' + (e.matchCount || '—') + '</td>' +
            '<td class="num mono">' + (e.tagCount || '—') + '</td>' +
            '<td>' + (e.pendingConfirmation ? '<span class="tag-pill pill-warn">待现场确认</span>' : '—') + '</td></tr>';
        }).join('');
        return '<div class="panel"><div class="panel-head"><h3>' + typePill(t) + '</h3>' +
          '<span class="note">' + byType[t].length + ' 个对象</span></div>' +
          '<div class="panel-body flush"><div class="tbl-wrap"><table class="tbl"><thead><tr>' +
          '<th>对象语义名称</th><th class="num">关系数</th><th>出/入边</th><th>匹配状态</th>' +
          '<th>匹配方式</th><th class="num">实例</th><th class="num">测点</th><th>确认</th>' +
          '</tr></thead><tbody>' + rows + '</tbody></table></div></div></div>';
      }).join('');

      done(
        '<div class="view-head"><h2>关系对象</h2>' +
        '<p>关系 Excel 中出现的全部工业对象共 ' + res.total + ' 个，其中 ' + matched +
        ' 个已匹配到 DCS 本体实例，' + (res.total - matched) + ' 个保留为外部关系对象并标记“未匹配DCS实例”。' +
        '关系 Excel 使用工艺抽象名称、DCS 点表使用现场位号命名，两者精确匹配数为 0，' +
        '已匹配项全部经由人工对象映射表建立，状态为“待现场确认”。</p></div>' + blocks
      );
    });
  }

  // ------------------------------------------------------------ 视图：12 分类

  function viewCategory(done) {
    var cat = CATEGORIES.filter(function (c) { return c.key === S.categoryKey; })[0];
    if (!cat) return done(emptyState('未知分类', ''));
    var head = '<div class="view-head"><h2>' + esc(cat.name) + ' · ' + esc(cat.nameEn) + '</h2>' +
      '<p>' + esc(cat.description) + '　<span class="mono" style="color:var(--muted)">' + esc(cat.endpoint) + '</span></p></div>';

    var K = S.categoryKey;

    if (K === 'class') {
      api.getClasses().then(function (res) {
        var rows = res.items.map(function (c) {
          return '<tr><td class="mono">' + dash(c.uri) + '</td><td><strong>' + esc(c.label) + '</strong></td>' +
            '<td>' + esc(c.kind) + '</td><td class="num mono">' + n(c.instanceCount) + '</td>' +
            '<td class="mono" style="font-size:11px;color:var(--text-2)">' + dash(c.example) + '</td>' +
            '<td class="mono" style="font-size:11px;color:var(--muted)">' + esc(c.sourceType) + '</td></tr>';
        }).join('');
        done(head + '<div class="panel"><div class="panel-body flush"><div class="tbl-wrap"><table class="tbl"><thead><tr>' +
          '<th>URI</th><th>中文语义</th><th>建模要素</th><th class="num">实例数</th><th>三元组示例</th><th>来源</th>' +
          '</tr></thead><tbody>' + rows + '</tbody></table></div></div></div>');
      });

    } else if (K === 'instance') {
      api.getEquipment({ limit: 300 }).then(function (res) {
        var rows = res.items.map(function (e) {
          return '<tr data-equip="' + esc(e.id) + '"><td><strong>' + esc(e.name) + '</strong></td>' +
            '<td class="mono" style="font-size:11px">' + esc(e.owlSubject) + '</td>' +
            '<td>' + esc(e.areaName || '') + '</td><td class="mono">' + esc(e.station) + '</td>' +
            '<td class="num mono">' + n(e.parameterCount) + '</td><td class="num mono">' + n(e.tagCount) + '</td></tr>';
        }).join('');
        done(head + '<div class="panel"><div class="panel-head"><h3>设备实例</h3>' +
          '<span class="note">按点位数排序，显示前 300 台，共 ' + n(res.total) + ' 台</span></div>' +
          '<div class="panel-body flush"><div class="tbl-wrap scroll-y"><table class="tbl"><thead><tr>' +
          '<th>设备</th><th>OWL Subject</th><th>工段</th><th>控制站</th>' +
          '<th class="num">参数</th><th class="num">点位</th></tr></thead><tbody>' + rows +
          '</tbody></table></div></div></div>');
      });

    } else if (K === 'property') {
      api.getProperties().then(function (res) {
        var groups = {};
        res.items.forEach(function (p) { (groups[p.kind] = groups[p.kind] || []).push(p); });
        var blocks = Object.keys(groups).map(function (k) {
          var rows = groups[k].map(function (p) {
            return '<tr><td class="mono">' + esc(p.name) + '</td><td>' + dash(p.label) + '</td>' +
              '<td class="mono" style="font-size:11px">' + dash(p.domain) + '</td>' +
              '<td class="mono" style="font-size:11px">' + dash(p.range) + '</td>' +
              '<td class="mono" style="font-size:11px;color:var(--muted)">' + esc(p.sourceType) + '</td></tr>';
          }).join('');
          return '<div class="panel"><div class="panel-head"><h3>' + esc(k) + '</h3>' +
            '<span class="note">' + groups[k].length + ' 项</span></div><div class="panel-body flush">' +
            '<div class="tbl-wrap"><table class="tbl"><thead><tr><th>属性名 / 字段</th><th>中文语义</th>' +
            '<th>Domain</th><th>Range</th><th>来源</th></tr></thead><tbody>' + rows +
            '</tbody></table></div></div></div>';
        }).join('');
        done(head + blocks);
      });

    } else if (K === 'relation') {
      api.getPredicates().then(function (res) {
        var rows = res.items.map(function (p) {
          return '<tr' + (p.count ? ' data-predicate="' + esc(p.predicate) + '"' : '') + '>' +
            '<td class="mono">' + esc(p.predicate) + '</td><td>' + dash(p.label) + '</td>' +
            '<td>' + (p.categories || []).map(function (c) {
              return '<span class="tag-pill pill-plain">' + esc(c) + '</span>';
            }).join(' ') + '</td>' +
            '<td class="num mono">' + (p.count == null ? '—' : n(p.count)) + '</td>' +
            '<td class="mono" style="font-size:11px;color:var(--muted)">' + esc(p.sourceType) + '</td></tr>';
        }).join('');
        done(head + '<div class="panel"><div class="panel-head"><h3>关系谓词</h3>' +
          '<span class="note">Schema 定义的对象属性 + 关系 Excel 中实际出现的谓词；点击可跳转到关系清单</span></div>' +
          '<div class="panel-body flush"><div class="tbl-wrap"><table class="tbl"><thead><tr>' +
          '<th>谓词 / 边类型</th><th>中文语义</th><th>所属关系大类</th><th class="num">出现次数</th><th>来源</th>' +
          '</tr></thead><tbody>' + rows + '</tbody></table></div></div></div>');
      });

    } else if (K === 'constraint' || K === 'capability' || K === 'modelRegistry') {
      var fn = K === 'constraint' ? api.getConstraints : K === 'capability' ? api.getCapabilities : api.getModelRegistry;
      fn().then(function (res) {
        done(head + '<div class="panel"><div class="panel-body">' +
          emptyState(res.emptyReason, '期望数据源：' + (res.expectedSource || '')) + '</div></div>');
      });

    } else if (K === 'rule') {
      api.getRules().then(function (res) {
        if (res.total) {
          var rows = res.items.map(function (r) {
            return '<tr><td class="mono">' + esc(r.ruleId) + '</td><td><strong>' + esc(r.name) + '</strong></td>' +
              '<td>' + dash(r.appliesTo) + '</td><td>' + dash(r.condition) + '</td>' +
              '<td>' + dash(r.conclusion) + '</td><td>' + dash(r.severity) + '</td>' +
              '<td class="mono" style="font-size:11px;color:var(--muted)">' + esc(r.sourceType) + '</td></tr>';
          }).join('');
          return done(head + '<div class="panel"><div class="panel-body flush"><div class="tbl-wrap">' +
            '<table class="tbl"><thead><tr><th>规则编号</th><th>规则名称</th><th>适用对象</th>' +
            '<th>条件</th><th>推理结论</th><th>严重程度</th><th>来源</th></tr></thead><tbody>' + rows +
            '</tbody></table></div></div></div>');
        }
        var cols = (res.templateColumns || []).map(function (c) {
          return '<li class="mono">' + esc(c) + '</li>';
        }).join('');
        done(head +
          '<div class="panel"><div class="panel-head"><h3>规则数据源</h3>' +
          '<div class="right"><span class="tag-pill pill-mute">未提供</span></div></div>' +
          '<div class="panel-body">' + emptyState(res.emptyReason, '') +
          '<div style="margin-top:16px"><p class="note-line">规则文件就位后即自动加载，' +
          '期望文件名 <span class="mono">' + esc(res.expectedSource) + '</span>，' +
          'Sheet「规则明细」字段如下（仓库内已提供空表模板 <span class="mono">6APA_规则.模板.xlsx</span>）：</p>' +
          '<ul class="list-plain" style="columns:2;column-gap:28px">' + cols + '</ul></div>' +
          '</div></div>');
      });

    } else if (K === 'semantic') {
      api.getSemantics({ limit: 150 }).then(function (res) {
        var rows = res.dcsSemantics.map(function (x) {
          return '<tr data-param="' + esc(x.parameterId) + '">' +
            '<td style="color:var(--text-2)">' + esc(x.rawDescription) + '</td>' +
            '<td><strong>' + esc(x.parameterSemantic) + '</strong></td>' +
            '<td>' + esc(x.industrialObject) + '</td>' +
            '<td class="mono" style="font-size:11px">' + esc(x.owlSubject) + '</td>' +
            '<td class="mono">' + esc(x.tagName) + '</td></tr>';
        }).join('');
        var relRows = res.relationSemantics.slice(0, 80).map(function (x) {
          return '<tr data-rel="' + esc(x.id) + '"><td><strong>' + esc(x.subjectEntity) + '</strong></td>' +
            '<td><span class="tag-pill pill-info">' + esc(x.predicate) + '</span></td>' +
            '<td>' + esc(x.objectEntity) + '</td>' +
            '<td style="color:var(--text-2)">' + esc(x.domainDescription) + '</td></tr>';
        }).join('');
        done(head +
          '<div class="panel"><div class="panel-head"><h3>DCS 语义提升</h3>' +
          '<span class="note">DCS 原始描述 → 参数语义 → 工业对象 · 显示前 150 条，共 ' + n(res.dcsSemanticTotal) + ' 条</span></div>' +
          '<div class="panel-body flush"><div class="tbl-wrap scroll-y"><table class="tbl"><thead><tr>' +
          '<th>DCS 原始描述</th><th>参数语义</th><th>工业对象</th><th>OWL Subject</th><th>DCS 点名</th>' +
          '</tr></thead><tbody>' + rows + '</tbody></table></div></div></div>' +
          '<div class="panel"><div class="panel-head"><h3>关系语义</h3>' +
          '<span class="note">起始对象 → 谓词 → 目标对象 → 工艺机理说明</span></div>' +
          '<div class="panel-body flush"><div class="tbl-wrap scroll-y"><table class="tbl"><thead><tr>' +
          '<th>起始对象</th><th>谓词</th><th>目标对象</th><th>工艺机理与业务因果说明</th>' +
          '</tr></thead><tbody>' + relRows + '</tbody></table></div></div></div>');
      });

    } else if (K === 'measurementAnchor') {
      api.getMeasurementAnchors({}).then(function (res) {
        var rows = res.items.map(function (a) {
          return '<tr data-param="' + esc(a.parameterId) + '">' +
            '<td><strong>' + esc(a.relationEntityName || a.semanticName) + '</strong></td>' +
            '<td>' + esc(a.equipmentName) + '</td><td>' + esc(a.semanticName) + '</td>' +
            '<td class="mono">' + esc(a.tagName) + '</td><td class="mono">' + esc(a.blockType) + '</td>' +
            '<td class="mono">' + dash(a.unit) + '</td><td class="mono">' + esc(a.station) + '</td>' +
            '<td style="color:var(--text-2)">' + esc(a.rawDescription) + '</td></tr>';
        }).join('');
        var un = res.unanchoredEntities.map(function (e) {
          return '<tr data-entity="' + esc(e.id) + '"><td><strong>' + esc(e.name) + '</strong></td>' +
            '<td>' + typePill(e.type) + '</td><td>' + matchPill(e.matchStatus, e.matchStatusLabel) + '</td>' +
            '<td class="num mono">' + n(e.relationCount) + '</td></tr>';
        }).join('');
        done(head +
          '<div class="panel"><div class="panel-head"><h3>已建立的测量锚点</h3>' +
          '<span class="note">工业语义 → DCS Tag → DCS 块，共 ' + n(res.total) + ' 条</span></div>' +
          '<div class="panel-body flush"><div class="tbl-wrap scroll-y"><table class="tbl"><thead><tr>' +
          '<th>关系对象</th><th>设备</th><th>参数语义</th><th>DCS 点名</th><th>DCS 块</th>' +
          '<th>单位</th><th>控制站</th><th>原点描述</th></tr></thead><tbody>' + rows +
          '</tbody></table></div></div></div>' +
          '<div class="panel"><div class="panel-head"><h3>暂无 DCS 测量锚点的关系对象</h3>' +
          '<span class="note">' + res.unanchoredEntities.length + ' 个 · 关系数据已加载，不虚构 DCS 点</span></div>' +
          '<div class="panel-body flush"><div class="tbl-wrap scroll-y"><table class="tbl"><thead><tr>' +
          '<th>对象</th><th>类型</th><th>匹配状态</th><th class="num">关系数</th></tr></thead><tbody>' + un +
          '</tbody></table></div></div></div>');
      });

    } else if (K === 'causal') {
      api.getCausalRelations().then(function (res) {
        var rows = res.items.map(function (r) {
          var st = EDGE_STYLES.filter(function (s) { return s.category === r.category; })[0] || {};
          return '<tr data-rel="' + esc(r.id) + '">' +
            '<td>' + esc(r.area) + '</td>' +
            '<td><span class="tag-pill pill-plain"><i class="swatch" style="background:' +
            (st.color || '#f2557a') + '"></i>' + esc(r.category) + '</span></td>' +
            '<td data-entity-jump="' + esc(r.subject.id) + '"><strong>' + esc(r.subjectEntity) + '</strong></td>' +
            '<td><span class="tag-pill ' + (String(r.predicate).indexOf('负向') >= 0 ? 'pill-err' : 'pill-ok') + '">' +
            esc(r.predicate) + '</span></td>' +
            '<td data-entity-jump="' + esc(r.object.id) + '"><strong>' + esc(r.objectEntity) + '</strong></td>' +
            '<td class="num mono">' + esc(r.weight) + '</td>' +
            '<td style="color:var(--text-2)">' + esc(r.domainDescription) + '</td></tr>';
        }).join('');
        done(head + '<div class="panel"><div class="panel-head"><h3>因果 / 影响 / 质量关系</h3>' +
          '<span class="note">共 ' + res.total + ' 条，直接来自关系 Excel，不重新推断</span></div>' +
          '<div class="panel-body flush"><div class="tbl-wrap"><table class="tbl"><thead><tr>' +
          '<th>工段</th><th>关系大类</th><th>原因对象</th><th>影响方向</th><th>结果对象</th>' +
          '<th class="num">权重</th><th>工艺机理与业务因果说明</th></tr></thead><tbody>' + rows +
          '</tbody></table></div></div></div>');
      });

    } else if (K === 'provenance') {
      viewSources(function (html) { done(head + html); }, true);
    } else {
      done(head + emptyState('该分类暂无数据', ''));
    }
  }

  // ------------------------------------------------------------ 视图：数据源 / 质量 / API

  function viewSources(done, bare) {
    Promise.all([api.getDataSources(), api.getMeta()]).then(function (r) {
      var ds = r[0];
      var cards = ds.sources.map(function (s) {
        var sheets = (s.sheets || []).map(function (sh) {
          return '<tr><td class="mono">' + esc(sh.sheet) + '</td>' +
            '<td class="num mono">' + n(sh.rows) + '</td>' +
            '<td class="num mono">' + n(sh.validRows) + '</td>' +
            '<td class="num mono">' + (sh.errorRows ? '<span style="color:var(--err)">' + n(sh.errorRows) + '</span>' : '0') + '</td></tr>';
        }).join('');
        var stats = Object.keys(s.stats || {}).map(function (k) {
          return '<dt>' + esc(k) + '</dt><dd class="mono">' + n(s.stats[k]) + '</dd>';
        }).join('');
        return '<div class="panel"><div class="panel-head"><h3>' + esc(s.sourceTypeLabel) + '</h3>' +
          '<span class="note mono">' + esc(s.sourceType) + '</span>' +
          '<div class="right">' + (s.available ? '<span class="tag-pill pill-ok">已加载</span>' :
            '<span class="tag-pill pill-mute">未提供</span>') + '</div></div>' +
          '<div class="panel-body">' +
          '<dl class="kv"><dt>文件</dt><dd class="mono">' + esc(s.file) + '</dd>' +
          '<dt>加载时间</dt><dd class="mono">' + dash(s.loadedAt) + '</dd>' + stats + '</dl>' +
          '<p class="note-line" style="margin-top:10px">' + esc(s.note || '') + '</p>' +
          (sheets ? '<div class="tbl-wrap" style="margin-top:8px"><table class="tbl"><thead><tr>' +
            '<th>Sheet</th><th class="num">数据行数</th><th class="num">有效行数</th><th class="num">异常行数</th>' +
            '</tr></thead><tbody>' + sheets + '</tbody></table></div>' : '') +
          '</div></div>';
      }).join('');

      var boundary = Object.keys(ds.boundary).map(function (k) {
        return '<tr><td class="mono">' + esc(k) + '</td><td>' + esc(ds.boundary[k]) + '</td></tr>';
      }).join('');

      var html = (bare ? '' : '<div class="view-head"><h2>数据源管理</h2>' +
        '<p>现场 DCS 数据、工业关系 Excel、对象映射与规则数据源相互独立，' +
        'API 返回体以 <span class="mono">sourceType</span> 字段区分来源。</p></div>') +
        cards +
        '<div class="panel"><div class="panel-head"><h3>数据边界</h3>' +
        '<span class="note">四类数据源各自回答什么问题</span></div>' +
        '<div class="panel-body flush"><table class="tbl"><thead><tr><th>sourceType</th><th>职责</th>' +
        '</tr></thead><tbody>' + boundary + '</tbody></table></div></div>';
      done(html);
    });
  }

  function viewQuality(done) {
    api.getDataQuality().then(function (q) {
      var s = q.summary;
      var checkRows = q.checks.map(function (c) {
        return '<tr data-check="' + esc(c.check) + '">' +
          '<td>' + esc(c.group) + '</td><td><strong>' + esc(c.check) + '</strong></td>' +
          '<td style="color:var(--text-2)">' + esc(c.description) + '</td>' +
          '<td>' + (c.passed ? '<span class="tag-pill pill-ok">通过</span>' :
            '<span class="tag-pill ' + (c.severity === 'error' ? 'pill-err' : c.severity === 'warning' ? 'pill-warn' : 'pill-info') +
            '">' + n(c.issueCount) + ' 项</span>') + '</td></tr>';
      }).join('');

      var shown = q.issues.slice(0, 200);
      var issueRows = shown.map(function (i) {
        var cls = i.severity === 'error' ? 'pill-err' : i.severity === 'warning' ? 'pill-warn' : 'pill-info';
        return '<tr><td><span class="tag-pill ' + cls + '">' + esc(i.severity) + '</span></td>' +
          '<td>' + esc(i.check) + '</td><td style="color:var(--text-2)">' + esc(i.detail) + '</td>' +
          '<td class="mono" style="font-size:11px;color:var(--muted)">' +
          (i.source ? esc((i.source.sheet || '') + (i.source.row ? ' 第 ' + i.source.row + ' 行' : '')) : '—') +
          '</td></tr>';
      }).join('');

      done('<div class="view-head"><h2>数据质量报告</h2>' +
        '<p>导入 Excel 时自动执行一致性校验。检查只报告问题，不修改任何原始数据。</p></div>' +
        '<div class="stat-row">' +
        '<div class="stat"><div class="k">检查项</div><div class="v">' + n(s.checkCount) + '</div></div>' +
        '<div class="stat"><div class="k">通过</div><div class="v" style="color:var(--ok)">' + n(s.passedCount) + '</div></div>' +
        '<div class="stat"><div class="k">错误</div><div class="v" style="color:var(--err)">' + n(s.errorCount) + '</div></div>' +
        '<div class="stat is-warn"><div class="k">告警</div><div class="v">' + n(s.warningCount) + '</div></div>' +
        '<div class="stat"><div class="k">提示</div><div class="v" style="color:var(--info)">' + n(s.infoCount) + '</div></div>' +
        '</div>' +
        '<div class="panel"><div class="panel-head"><h3>检查项</h3></div><div class="panel-body flush">' +
        '<div class="tbl-wrap"><table class="tbl"><thead><tr><th>分组</th><th>检查项</th><th>说明</th><th>结果</th>' +
        '</tr></thead><tbody>' + checkRows + '</tbody></table></div></div></div>' +
        '<div class="panel"><div class="panel-head"><h3>问题明细</h3>' +
        '<span class="note">共 ' + n(s.issueCount) + ' 项，显示前 ' + shown.length + ' 项</span></div>' +
        '<div class="panel-body flush"><div class="tbl-wrap scroll-y"><table class="tbl"><thead><tr>' +
        '<th>级别</th><th>检查项</th><th>问题描述</th><th>来源</th></tr></thead><tbody>' + issueRows +
        '</tbody></table></div></div></div>');
    });
  }

  function viewApi(done) {
    var rows = api.endpoints.map(function (p) {
      return '<tr><td class="mono">GET</td><td class="mono">' + esc(p) + '</td></tr>';
    }).join('');
    done('<div class="view-head"><h2>API 接口</h2>' +
      '<p>前端全部数据经由下列 REST 接口获取。当前运行模式：<b>' +
      (api.mode === 'live' ? '连接本体服务（' + esc(api.baseUrl) + '）' : '静态 API 快照（离线演示）') +
      '</b>。静态模式下由前端 API 适配层按同一份契约在浏览器内合成响应体，' +
      '页面代码路径与连接后端时完全一致。</p></div>' +
      '<div class="panel"><div class="panel-head"><h3>REST 接口清单</h3>' +
      '<span class="note">' + api.endpoints.length + ' 个接口</span></div>' +
      '<div class="panel-body flush"><table class="tbl"><thead><tr><th style="width:70px">方法</th><th>路径</th>' +
      '</tr></thead><tbody>' + rows + '</tbody></table></div></div>' +
      '<div class="panel"><div class="panel-head"><h3>启动本体服务</h3></div><div class="panel-body">' +
      '<p class="note-line">在仓库根目录执行：</p>' +
      '<pre class="mono" style="background:var(--panel-2);border:1px solid var(--line);border-radius:7px;' +
      'padding:12px;overflow-x:auto;margin:0">pip install -r requirements.txt\n' +
      'uvicorn backend.main:app --reload --port 8700</pre>' +
      '<p class="note-line" style="margin-top:10px">随后在本页面地址后追加 ' +
      '<span class="mono">?api=http://localhost:8700</span> 即可切换为实时后端模式。</p></div></div>');
  }

  // ------------------------------------------------------------ 右栏

  function inspectorHtml() {
    var i = S.inspector;
    if (!i) {
      return '<div class="insp-kicker">对象详情</div>' +
        '<div class="insp-title">未选择对象</div>' +
        '<p class="note-line">在左侧列表、表格行或关系图中点击任意对象或关系边，' +
        '此处显示其属性、关系、测量锚点与数据来源。</p>' +
        '<div class="insp-section"><h4>数据边界</h4>' +
        '<dl class="kv"><dt>DCS_EXCEL</dt><dd>工段 / 设备 / 参数 / DCS 点</dd>' +
        '<dt>RELATION_EXCEL</dt><dd>关系 / 部件 / 属性 / 因果</dd>' +
        '<dt>MAPPING_FILE</dt><dd>抽象对象与现场位号对齐</dd>' +
        '<dt>RULE_FILE</dt><dd>条件 → 推理结论</dd></dl></div>';
    }
    return i.html;
  }

  function setInspector(html) {
    S.inspector = { html: html };
    var el = $('#inspector');
    if (el) el.innerHTML = html;
  }

  function inspectRelation(relationId) {
    api.getRelationDetail(relationId).then(function (r) {
      if (!r) return;
      var st = EDGE_STYLES.filter(function (s) { return s.category === r.category; })[0] || {};
      setInspector(
        '<div class="insp-kicker">关系详情</div>' +
        '<div class="insp-title">' + esc(r.subjectEntity) + ' → ' + esc(r.objectEntity) + '</div>' +
        '<div style="margin-bottom:12px"><span class="tag-pill pill-plain">' +
        '<i class="swatch" style="background:' + (st.color || '#8fa6c4') + '"></i>' + esc(r.category) + '</span> ' +
        '<span class="tag-pill pill-info">' + esc(r.predicate) + '</span></div>' +

        '<div class="insp-section"><h4>关系三元组</h4>' +
        '<div class="chain">' +
        '<div class="chain-node"><span class="lbl">起始对象</span><span class="val">' + esc(r.subjectEntity) +
        '</span><span style="margin-left:auto">' + typePill(r.subjectType) + '</span></div>' +
        '<div class="chain-arrow"></div>' +
        '<div class="chain-node"><span class="lbl">关系谓词</span><span class="val">' + esc(r.predicate) + '</span></div>' +
        '<div class="chain-arrow"></div>' +
        '<div class="chain-node"><span class="lbl">目标对象</span><span class="val">' + esc(r.objectEntity) +
        '</span><span style="margin-left:auto">' + typePill(r.objectType) + '</span></div>' +
        '</div></div>' +

        '<div class="insp-section"><h4>关系元数据</h4><dl class="kv">' +
        '<dt>工段</dt><dd>' + esc(r.area) + '</dd>' +
        '<dt>子场景</dt><dd>' + esc(r.scenario) + '</dd>' +
        '<dt>权重</dt><dd class="mono">' + esc(r.weight) + '</dd>' +
        '<dt>关系标识</dt><dd class="mono" style="font-size:11px">' + esc(r.id) + '</dd>' +
        '<dt>稳定键</dt><dd class="mono" style="font-size:10.5px;word-break:break-all">' + esc(r.stableKey) + '</dd>' +
        '<dt>对象匹配</dt><dd>' + (r.matchStatus === 'MATCHED' ? '双端已匹配' :
          r.matchStatus === 'PARTIAL' ? '单端已匹配' : '双端未匹配 DCS 实例') + '</dd>' +
        '</dl></div>' +

        '<div class="insp-section"><h4>工艺机理与业务因果说明</h4>' +
        '<p style="margin:0;color:var(--text-2)">' + esc(r.domainDescription) + '</p></div>' +

        '<div class="insp-section"><h4>数据来源</h4>' + sourceBox('', r.source, r.sourceType) + '</div>' +

        '<div class="insp-section"><h4>操作</h4>' +
        '<div style="display:flex;flex-wrap:wrap;gap:7px">' +
        '<button class="ctl" data-entity-jump="' + esc(r.subject.id) + '">查看起始对象</button>' +
        '<button class="ctl" data-entity-jump="' + esc(r.object.id) + '">查看目标对象</button>' +
        '<button class="ctl" data-rel-filter-cat="' + esc(r.category) + '">同类关系 ' + r.sameCategoryRelationIds.length + ' 条</button>' +
        '<button class="ctl" data-rel-filter-area="' + esc(r.area) + '">同工段关系 ' + r.sameAreaRelationIds.length + ' 条</button>' +
        '</div></div>'
      );
    });
  }

  function inspectStructuralEdge(edge) {
    var kinds = {
      mapping: ['对象映射边', '关系对象 → DCS 本体实例，来自人工对象映射表，状态为“待现场确认”。',
        'MAPPING_FILE', { file: '6APA_对象映射.xlsx', sheet: '对象映射' }],
      anchor: ['测量锚点边', '工业语义 → DCS 参数语义，据此绑定到现场测点。',
        'MAPPING_FILE', { file: '6APA_对象映射.xlsx', sheet: '对象映射' }],
      tag: ['boundToTag', '参数语义 → DCS Tag，来自 DCS 点表。',
        'DCS_EXCEL', { file: '6APA_DCS.xlsx', sheet: 'DCS点位明细' }],
      structure: ['本体结构边', '工段 hasEquipment 设备、设备 hasParameter 参数，来自 DCS 点表层级。',
        'DCS_EXCEL', { file: '6APA_DCS.xlsx', sheet: 'DCS点位明细' }]
    };
    var k = kinds[edge.edgeKind] || ['结构边', '', edge.sourceType, null];
    setInspector(
      '<div class="insp-kicker">' + esc(k[0]) + '</div>' +
      '<div class="insp-title">' + esc(edge.label) + '</div>' +
      '<p class="note-line">' + esc(k[1]) + '</p>' +
      '<div class="insp-section"><h4>说明</h4>' +
      '<p style="margin:0;color:var(--text-2)">本边不是工业关系 Excel 中的关系记录，' +
      '而是本体内部的结构连接，用于把关系对象与现场 DCS 实例、测点串起来。' +
      '工业关系只在关系图中以彩色实线 / 虚线绘制，点击即可查看其工艺机理说明与行号。</p></div>' +
      '<div class="insp-section"><h4>数据来源</h4>' + sourceBox('', k[3], k[2]) + '</div>'
    );
  }

  function inspectEntity(entityId) {
    api.getRelationEntityDetail(entityId).then(function (e) {
      if (!e) return;
      var matches = e.matches.slice(0, 6).map(function (m) {
        return '<li><strong>' + esc(m.name) + '</strong> ' +
          '<span style="color:var(--muted)">' + esc(m.strategyLabel) + '</span>' +
          (m.confidence ? ' <span class="tag-pill ' + (m.confidence === '高' ? 'pill-ok' :
            m.confidence === '中' ? 'pill-warn' : 'pill-err') + '">置信度 ' + esc(m.confidence) + '</span>' : '') +
          (m.note ? '<div style="color:var(--text-2);font-size:11.5px">' + esc(m.note) + '</div>' : '') + '</li>';
      }).join('');
      var anchors = e.measurementAnchors.slice(0, 6).map(function (a) {
        return '<li><span class="mono">' + esc(a.tagName) + '</span> · ' + esc(a.blockType) +
          ' · ' + dash(a.unit) + '<div style="color:var(--muted);font-size:11.5px">' + esc(a.rawDescription) + '</div></li>';
      }).join('');

      setInspector(
        '<div class="insp-kicker">关系对象</div>' +
        '<div class="insp-title">' + esc(e.name) + '</div>' +
        '<div style="margin-bottom:12px">' + typePill(e.type) + ' ' + matchPill(e.matchStatus, e.matchStatusLabel) + '</div>' +
        '<div class="insp-section"><h4>基本信息</h4><dl class="kv">' +
        '<dt>对象类型</dt><dd>' + esc(e.type) + '</dd>' +
        '<dt>适用工段</dt><dd>' + esc(e.areas.join('、')) + '</dd>' +
        '<dt>关系数</dt><dd class="mono">' + e.relationCount + '（出 ' + e.outgoingCount + ' / 入 ' + e.incomingCount + '）</dd>' +
        '<dt>匹配方式</dt><dd>' + esc(e.matchStrategyLabel) + '</dd>' +
        '<dt>本体实例</dt><dd class="mono">' + e.matchCount + '</dd>' +
        '<dt>测量锚点</dt><dd class="mono">' + e.tagCount + '</dd>' +
        '</dl></div>' +
        (matches ? '<div class="insp-section"><h4>匹配的本体实例</h4><ul class="list-plain">' + matches + '</ul></div>' : '') +
        (anchors ? '<div class="insp-section"><h4>测量锚点</h4><ul class="list-plain">' + anchors + '</ul></div>'
          : '<div class="insp-section"><h4>测量锚点</h4>' +
            emptyState('当前关系对象暂无 DCS 测量锚点', '') + '</div>') +
        '<div class="insp-section"><h4>数据来源</h4>' +
        sourceBox('', { file: '6APA_工业关系.xlsx', sheet: '关系明细' }, 'RELATION_EXCEL') + '</div>' +
        '<div class="insp-section"><h4>操作</h4>' +
        '<div style="display:flex;gap:7px;flex-wrap:wrap">' +
        '<button class="ctl" data-entity="' + esc(e.id) + '">打开对象详情页</button>' +
        '<button class="ctl" data-graph-root="' + esc(e.id) + '">以此为中心绘图</button></div></div>'
      );
    });
  }

  function inspectEquipment(equipmentId) {
    api.getEquipmentDetail(equipmentId).then(function (e) {
      if (!e) return;
      var s = e.stats;
      setInspector(
        '<div class="insp-kicker">设备实例 · DCS_EXCEL</div>' +
        '<div class="insp-title">' + esc(e.name) + '</div>' +
        '<div class="insp-section"><h4>属性</h4><dl class="kv">' +
        '<dt>OWL Subject</dt><dd class="mono" style="font-size:11px">' + esc(e.owlSubject) + '</dd>' +
        '<dt>所属工段</dt><dd>' + esc((e.area || {}).nameZh || '') + '</dd>' +
        '<dt>控制站</dt><dd class="mono">' + esc(e.station) + '</dd>' +
        '<dt>总点位</dt><dd class="mono">' + n(s.total) + '</dd>' +
        '<dt>参数语义</dt><dd class="mono">' + n(e.parameterCount) + '</dd>' +
        '<dt>PV / OP</dt><dd class="mono">' + s.pv + ' / ' + s.op + '</dd>' +
        '<dt>VAL / DI·DO</dt><dd class="mono">' + s.val + ' / ' + s.dido + '</dd>' +
        '</dl></div>' +
        (e.relationEntities.length
          ? '<div class="insp-section"><h4>关联工艺对象</h4><ul class="list-plain">' +
            e.relationEntities.map(function (x) {
              return '<li><button class="ctl" data-entity="' + esc(x.id) + '">' + esc(x.name) + '</button></li>';
            }).join('') + '</ul></div>'
          : '') +
        '<div class="insp-section"><h4>数据来源</h4>' + sourceBox('', e.source, e.sourceType) +
        (e.statsSource ? '<div style="height:8px"></div>' + sourceBox('设备统计来源', e.statsSource, e.sourceType) : '') +
        '</div>' +
        '<div class="insp-section"><h4>操作</h4><div style="display:flex;gap:7px;flex-wrap:wrap">' +
        '<button class="ctl" data-equip="' + esc(e.id) + '">打开设备详情页</button>' +
        '<button class="ctl" data-graph-equip="' + esc(e.id) + '">查看关系图</button></div></div>'
      );
    });
  }

  function inspectParameter(parameterId) {
    api.getParameterDetail(parameterId).then(function (p) {
      if (!p) return;
      var anchors = p.measurementAnchors.map(function (a) {
        return '<li><span class="mono">' + esc(a.tagName) + '</span> · ' + esc(a.blockType) + ' · ' + dash(a.unit) +
          '<div style="color:var(--muted);font-size:11.5px">' + esc(a.rawDescription) + '</div></li>';
      }).join('');
      setInspector(
        '<div class="insp-kicker">参数语义 · DCS_EXCEL</div>' +
        '<div class="insp-title">' + esc(p.name) + '</div>' +
        '<div class="insp-section"><h4>属性</h4><dl class="kv">' +
        '<dt>参数分类</dt><dd>' + (p.categories || []).join('、') + '</dd>' +
        '<dt>工程单位</dt><dd class="mono">' + dash((p.units || []).join('、')) + '</dd>' +
        '<dt>DCS 块类型</dt><dd class="mono">' + dash((p.blockTypes || []).join('、')) + '</dd>' +
        '<dt>所属设备</dt><dd>' + esc(p.equipmentName) + '</dd>' +
        '<dt>OWL Subject</dt><dd class="mono" style="font-size:11px">' + esc(p.owlSubject) + '</dd>' +
        '</dl></div>' +
        '<div class="insp-section"><h4>测量锚点</h4><ul class="list-plain">' + anchors + '</ul></div>' +
        '<div class="insp-section"><h4>数据来源</h4>' + sourceBox('', p.source, p.sourceType) + '</div>' +
        '<div class="insp-section"><h4>操作</h4><div style="display:flex;gap:7px;flex-wrap:wrap">' +
        '<button class="ctl" data-param="' + esc(p.id) + '">打开参数详情页</button>' +
        '<button class="ctl" data-equip="' + esc(p.equipmentId) + '">查看所属设备</button></div></div>'
      );
    });
  }

  function inspectTag(tagId, node) {
    api.getTags({}).then(function (res) {
      var t = res.items.filter(function (x) { return x.id === tagId; })[0];
      if (!t) return;
      setInspector(
        '<div class="insp-kicker">DCS 点 · DCS_EXCEL</div>' +
        '<div class="insp-title mono">' + esc(t.name) + '</div>' +
        '<div class="insp-section"><h4>属性</h4><dl class="kv">' +
        '<dt>原点描述</dt><dd>' + esc(t.rawDescription) + '</dd>' +
        '<dt>参数语义</dt><dd>' + esc(t.parameterName) + '</dd>' +
        '<dt>参数分类</dt><dd>' + esc(t.parameterType) + '</dd>' +
        '<dt>DCS 块类型</dt><dd class="mono">' + esc(t.blockType) + '</dd>' +
        '<dt>工程单位</dt><dd class="mono">' + dash(t.unit) + '</dd>' +
        '<dt>控制站</dt><dd class="mono">' + esc(t.station) + '</dd>' +
        '<dt>所属设备</dt><dd>' + esc(t.equipmentName) + '</dd>' +
        '<dt>OWL Subject</dt><dd class="mono" style="font-size:11px">' + esc(t.owlSubject) + '</dd>' +
        '</dl></div>' +
        '<div class="insp-section"><h4>数据来源</h4>' + sourceBox('', t.source, t.sourceType) + '</div>' +
        '<div class="insp-section"><h4>操作</h4><div style="display:flex;gap:7px;flex-wrap:wrap">' +
        '<button class="ctl" data-param="' + esc(t.parameterId) + '">查看参数语义</button>' +
        '<button class="ctl" data-equip="' + esc(t.equipmentId) + '">查看所属设备</button></div></div>'
      );
    });
  }

  // ------------------------------------------------------------ 渲染

  var VIEWS = {
    overview: viewOverview,
    areas: viewAreas,
    area: viewArea,
    equipment: viewEquipment,
    parameter: viewParameter,
    entity: viewEntity,
    entities: viewEntities,
    graph: viewGraph,
    relations: viewRelations,
    category: viewCategory,
    sources: viewSources,
    quality: viewQuality,
    api: viewApi
  };

  function buildCrumbs(cb) {
    var c = [{ label: '6-APA 生产线', view: 'overview' }];
    function push(label, patch) { c.push(Object.assign({ label: label }, patch)); }
    if (S.view === 'areas') { push('工段与设备', { view: 'areas' }); return cb(c); }
    if (['area', 'equipment', 'parameter'].indexOf(S.view) >= 0) {
      push('工段与设备', { view: 'areas' });
      var tasks = [];
      if (S.areaId) tasks.push(api.getProcessAreas());
      Promise.all(tasks).then(function (r) {
        if (S.areaId && r[0]) {
          var a = r[0].items.filter(function (x) { return x.id === S.areaId; })[0];
          if (a) push(a.nameZh, { view: 'area', areaId: a.id });
        }
        var more = [];
        if (S.equipmentId) more.push(api.getEquipmentDetail(S.equipmentId));
        if (S.parameterId) more.push(api.getParameterDetail(S.parameterId));
        Promise.all(more).then(function (m) {
          m.forEach(function (x) {
            if (!x) return;
            if (x.owlSubject && x.tagCount != null && x.parameterCount != null) {
              push(x.name, { view: 'equipment', equipmentId: x.id, areaId: x.areaId });
            } else if (x.equipmentId) {
              push(x.name, { view: 'parameter', parameterId: x.id, equipmentId: x.equipmentId, areaId: x.areaId });
            }
          });
          cb(c);
        });
      });
      return;
    }
    if (S.view === 'entity') {
      push('关系图谱', { view: 'graph' });
      api.getRelationEntityDetail(S.entityId).then(function (e) {
        if (e) push(e.name, { view: 'entity', entityId: e.id });
        cb(c);
      });
      return;
    }
    if (S.view === 'category') {
      var cat = CATEGORIES.filter(function (x) { return x.key === S.categoryKey; })[0];
      push('本体分类', { view: 'overview' });
      if (cat) push(cat.name, { view: 'category', categoryKey: cat.key });
      return cb(c);
    }
    var names = { graph: '关系图谱', relations: '关系清单', entities: '关系对象', sources: '数据源管理', quality: '数据质量', api: 'API 接口' };
    if (names[S.view]) push(names[S.view], { view: S.view });
    cb(c);
  }

  function render() {
    $('#rail').innerHTML = railHtml();
    $('#inspector').innerHTML = inspectorHtml();
    var canvas = $('#canvas');
    canvas.innerHTML = '<div class="loading">正在加载…</div>';

    buildCrumbs(function (crumbs) {
      S.crumbs = crumbs;
      var fn = VIEWS[S.view] || viewOverview;
      fn(function (html) {
        canvas.innerHTML = crumbsHtml() + html;
      });
    });
  }

  // ------------------------------------------------------------ 事件委托

  function bind() {
    document.addEventListener('click', function (ev) {
      var t = ev.target;

      var nav = t.closest('[data-nav]');
      if (nav) {
        var view = nav.getAttribute('data-nav');
        var cat = nav.getAttribute('data-cat');
        return go({ view: view, categoryKey: cat || null });
      }

      var crumb = t.closest('[data-crumb]');
      if (crumb) {
        var c = S.crumbs[+crumb.getAttribute('data-crumb')];
        if (c) return go(Object.assign({ view: c.view }, c));
      }

      var jump = t.closest('[data-entity-jump]');
      if (jump && jump.getAttribute('data-entity-jump')) {
        ev.stopPropagation();
        return go({ view: 'entity', entityId: jump.getAttribute('data-entity-jump'), depth: 1 });
      }

      var ent = t.closest('[data-entity]');
      if (ent) return go({ view: 'entity', entityId: ent.getAttribute('data-entity'), depth: 1 });

      var eq = t.closest('[data-equip]');
      if (eq) return go({ view: 'equipment', equipmentId: eq.getAttribute('data-equip') });

      var pm = t.closest('[data-param]');
      if (pm) return go({ view: 'parameter', parameterId: pm.getAttribute('data-param') });

      var ar = t.closest('[data-area]');
      if (ar) return go({ view: 'area', areaId: ar.getAttribute('data-area') });

      var rel = t.closest('[data-rel]');
      if (rel) return inspectRelation(rel.getAttribute('data-rel'));

      var relcat = t.closest('[data-relcat]');
      if (relcat) return go({ view: 'relations', relFilters: { category: relcat.getAttribute('data-relcat') } });

      var pred = t.closest('[data-predicate]');
      if (pred) return go({ view: 'relations', relFilters: { predicate: pred.getAttribute('data-predicate') } });

      var rfc = t.closest('[data-rel-filter-cat]');
      if (rfc) return go({ view: 'relations', relFilters: { category: rfc.getAttribute('data-rel-filter-cat') } });

      var rfa = t.closest('[data-rel-filter-area]');
      if (rfa) return go({ view: 'relations', relFilters: { area: rfa.getAttribute('data-rel-filter-area') } });

      var groot = t.closest('[data-graph-root]');
      if (groot) return go({ view: 'graph', graphFilters: { rootId: groot.getAttribute('data-graph-root') }, depth: 1 });

      var gequip = t.closest('[data-graph-equip]');
      if (gequip) {
        ev.stopPropagation();
        return go({ view: 'graph', graphFilters: { rootId: gequip.getAttribute('data-graph-equip') }, depth: 2 });
      }

      var depth = t.closest('[data-depth]');
      if (depth) {
        S.depth = +depth.getAttribute('data-depth');
        document.querySelectorAll('[data-depth]').forEach(function (b) {
          b.classList.toggle('is-on', +b.getAttribute('data-depth') === S.depth);
        });
        var q = S.view === 'entity'
          ? { rootId: S.entityId, depth: S.depth }
          : Object.assign({ depth: S.depth }, S.graphFilters);
        return mountGraph(q);
      }

      var sd = t.closest('[data-showdcs]');
      if (sd) {
        S.showDcs = !S.showDcs;
        sd.classList.toggle('is-on', S.showDcs);
        return mountGraph(S.view === 'entity'
          ? { rootId: S.entityId, depth: S.depth }
          : Object.assign({ depth: S.depth }, S.graphFilters));
      }

      if (t.closest('[data-gf-reset]')) return go({ graphFilters: {} });
      if (t.closest('[data-rf-reset]')) return go({ relFilters: {} });
    });

    document.addEventListener('change', function (ev) {
      var gf = ev.target.closest('[data-gf]');
      if (gf) {
        var key = gf.getAttribute('data-gf');
        var v = gf.value;
        var patch = {};
        if (key === 'matched') patch.matched = v === '' ? undefined : v === '1';
        else patch[key] = v || undefined;
        S.graphFilters = Object.assign({}, S.graphFilters, patch);
        if (key === 'rootId') return go({});
        return mountGraph(Object.assign({ depth: S.depth }, S.graphFilters));
      }
      var rf = ev.target.closest('[data-rf]');
      if (rf) {
        var k = rf.getAttribute('data-rf');
        var patch2 = {};
        patch2[k] = rf.value || undefined;
        return go({ relFilters: Object.assign({}, S.relFilters, patch2) });
      }
    });

    var timer = null;
    document.addEventListener('input', function (ev) {
      var rf = ev.target.closest('[data-rf="keyword"]');
      if (!rf) return;
      clearTimeout(timer);
      var v = rf.value;
      timer = setTimeout(function () {
        var pos = v.length;
        S.relFilters = Object.assign({}, S.relFilters, { keyword: v || undefined });
        render();
        setTimeout(function () {
          var box = document.querySelector('[data-rf="keyword"]');
          if (box) { box.focus(); box.setSelectionRange(pos, pos); }
        }, 0);
      }, 260);
    });
  }

  // ------------------------------------------------------------ 启动

  function boot() {
    var params = new URLSearchParams(location.search);
    var apiBase = params.get('api');
    if (apiBase && !global.__API_BASE__) {
      global.__API_BASE__ = apiBase;
      location.search = '';
      return;
    }

    api.getCategories().then(function (c) {
      CATEGORIES = c.categories;
      CORE = c.coreContents;
      EDGE_STYLES = c.edgeStyles || [];
      (c.nodeStyles || []).forEach(function (s) { NODE_COLORS[s.type] = s.color; });
      CORE_STYLES.nodes = (c.nodeStyles || []).filter(function (s) {
        return ['生产工段', '生产设备', '设备部件', '工艺属性', '参数', 'DCS点', '物料流股',
          '控制仪表', '执行机构', '质量指标', '业务指标'].indexOf(s.type) >= 0;
      });
      return api.getDataSources();
    }).then(function (ds) {
      $('#src-chips').innerHTML = ds.sources.map(function (s) {
        return '<span class="chip' + (s.available ? '' : ' is-missing') + '">' +
          '<span class="tick">' + (s.available ? '✓' : '○') + '</span>' + esc(s.file) + '</span>';
      }).join('');
      $('#svc-label').textContent = api.mode === 'live' ? '本体服务 · 实时' : '本体服务 · 静态快照';
      bind();
      render();
    });
  }

  global.OntologyApp = { boot: boot, state: S };
})(window);
