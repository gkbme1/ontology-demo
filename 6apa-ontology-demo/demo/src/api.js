/*
 * 本体 API 客户端。
 *
 * 两种模式，对外接口完全一致：
 *   · live   —— window.__API_BASE__ 指向 FastAPI 本体服务，走真实 REST 请求
 *   · static —— 读取由 backend/tools/build_static_demo_data.py 导出的 API 快照，
 *               在浏览器内按同一份契约合成响应体
 *
 * 页面组件只调用本模块，不直接触碰任何数据表，
 * 满足“前端只能通过 API 获取本体数据和关系数据”的要求。
 */
(function (global) {
  'use strict';

  var D = global.__ONTO__ || {};
  var BASE = global.__API_BASE__ || null;
  var MODE = BASE ? 'live' : 'static';

  // ------------------------------------------------------------- 索引

  var idx = {
    areaById: {},
    equipById: {},
    paramById: {},
    tagById: {},
    relById: {},
    entityById: {},
    paramsByEquip: {},
    tagsByParam: {},
    tagsByEquip: {},
    equipByArea: {}
  };

  function buildIndexes() {
    (D.areas || []).forEach(function (a) { idx.areaById[a.id] = a; });
    (D.equipment || []).forEach(function (e) {
      idx.equipById[e.id] = e;
      (idx.equipByArea[e.a] = idx.equipByArea[e.a] || []).push(e);
    });
    (D.parameters || []).forEach(function (p) {
      idx.paramById[p.id] = p;
      (idx.paramsByEquip[p.e] = idx.paramsByEquip[p.e] || []).push(p);
    });
    (D.tags || []).forEach(function (t) {
      idx.tagById[t.id] = t;
      (idx.tagsByParam[t.p] = idx.tagsByParam[t.p] || []).push(t);
      (idx.tagsByEquip[t.e] = idx.tagsByEquip[t.e] || []).push(t);
    });
    (D.relations || []).forEach(function (r) { idx.relById[r.id] = r; });
    (D.relationEntities || []).forEach(function (e) { idx.entityById[e.id] = e; });
  }

  // ------------------------------------------------------------- 展开器
  // 紧凑表 → 与 REST 响应体一致的对象

  var DCS_FILE = (D.meta && D.meta.sourceFiles && D.meta.sourceFiles[0]) || '6APA_DCS.xlsx';
  var SHEET_TAGS = 'DCS点位明细';
  var SHEET_STATS = '设备统计';

  function equipOut(e) {
    if (!e) return null;
    var area = idx.areaById[e.a] || {};
    return {
      id: e.id, owlSubject: e.o, name: e.n,
      areaId: e.a, areaName: area.name, station: e.sn,
      tagCount: e.tc, parameterCount: e.pc,
      stats: e.s, statsFromSheet1: e.s1, overview: e.ov,
      sourceType: 'DCS_EXCEL',
      source: { file: DCS_FILE, sheet: SHEET_TAGS, row: e.r, field: '生产设备/装置 (Equipment Entity)', value: e.n },
      statsSource: e.r1 ? { file: DCS_FILE, sheet: SHEET_STATS, row: e.r1 } : null
    };
  }

  function paramOut(p) {
    if (!p) return null;
    var e = idx.equipById[p.e] || {};
    var area = idx.areaById[e.a] || {};
    return {
      id: p.id, name: p.n,
      equipmentId: p.e, equipmentName: e.n, owlSubject: e.o,
      areaId: e.a, areaName: area.name, station: e.sn,
      categories: p.c, units: p.u, blockTypes: p.b,
      tagCount: (p.t || []).length, tagIds: p.t,
      sourceType: 'DCS_EXCEL',
      source: { file: DCS_FILE, sheet: SHEET_TAGS, row: p.r, field: '参数语义名称 (Parameter Name)', value: p.n }
    };
  }

  function tagOut(t) {
    if (!t) return null;
    var e = idx.equipById[t.e] || {};
    var p = idx.paramById[t.p] || {};
    var area = idx.areaById[e.a] || {};
    return {
      id: t.id, name: t.n, rawDescription: t.d,
      station: e.sn, areaId: e.a, areaName: area.name,
      equipmentId: t.e, equipmentName: e.n,
      parameterId: t.p, parameterName: p.n,
      parameterType: t.pt, unit: t.u, blockType: t.b,
      owlSubject: e.o,
      sourceType: 'DCS_EXCEL',
      source: { file: DCS_FILE, sheet: SHEET_TAGS, row: t.r }
    };
  }

  function page(items, q) {
    var offset = +(q && q.offset) || 0;
    var limit = q && q.limit ? +q.limit : null;
    return {
      items: limit ? items.slice(offset, offset + limit) : items.slice(offset),
      total: items.length,
      offset: offset
    };
  }

  // ------------------------------------------------------------- 关系筛选

  function filterRelations(q) {
    q = q || {};
    var items = (D.relations || []).slice();
    function eq(field, key) {
      if (q[key]) items = items.filter(function (r) { return r[field] === q[key]; });
    }
    eq('area', 'area'); eq('category', 'category'); eq('predicate', 'predicate');
    eq('scenario', 'scenario'); eq('subjectType', 'subjectType'); eq('objectType', 'objectType');
    if (q.entityId) {
      items = items.filter(function (r) {
        return r.subject.id === q.entityId || r.object.id === q.entityId;
      });
    }
    if (q.minWeight != null && q.minWeight !== '') {
      items = items.filter(function (r) { return r.weight != null && r.weight >= +q.minWeight; });
    }
    if (q.maxWeight != null && q.maxWeight !== '') {
      items = items.filter(function (r) { return r.weight != null && r.weight <= +q.maxWeight; });
    }
    if (q.matched === true || q.matched === false) {
      items = items.filter(function (r) { return (r.matchStatus === 'MATCHED') === q.matched; });
    }
    if (q.causal) items = items.filter(function (r) { return r.isCausal; });
    if (q.keyword) {
      var k = q.keyword;
      items = items.filter(function (r) {
        return (r.subjectEntity || '').indexOf(k) >= 0 || (r.objectEntity || '').indexOf(k) >= 0 ||
          (r.predicate || '').indexOf(k) >= 0 || (r.domainDescription || '').indexOf(k) >= 0;
      });
    }
    return items;
  }

  // ------------------------------------------------------------- 关系图

  var MAX_NODES = 220;

  function styleFor(type, matched) {
    var list = (D.categories && D.categories.nodeStyles) || [];
    var found = null;
    for (var i = 0; i < list.length; i++) if (list[i].type === type) { found = list[i]; break; }
    var fallback = null;
    for (var j = 0; j < list.length; j++) if (list[j].type === '外部对象') { fallback = list[j]; break; }
    var s = found || fallback || { color: '#6B7A90', shape: 'circle' };
    return { color: matched ? s.color : (fallback ? fallback.color : '#6B7A90'), shape: s.shape };
  }

  function edgeStyleFor(category, matched, weight) {
    var list = (D.categories && D.categories.edgeStyles) || [];
    var s = null, un = null;
    for (var i = 0; i < list.length; i++) {
      if (list[i].category === category) s = list[i];
      if (list[i].category === '未匹配关系') un = list[i];
    }
    s = matched ? (s || list[0]) : (un || s || list[0]);
    if (!s) s = { color: '#8FA6C4', lineStyle: 'solid', width: 1.6 };
    var w = weight == null ? 1 : weight;
    return {
      color: s.color,
      lineStyle: s.lineStyle,
      width: +(s.width * (0.7 + 0.45 * w)).toFixed(2),
      opacity: +Math.min(1, 0.55 + 0.22 * w).toFixed(2)
    };
  }

  function entityNode(id, isRoot) {
    var e = idx.entityById[id];
    if (!e) return null;
    var matched = e.matchStatus === 'MATCHED';
    return {
      id: id, label: e.name, type: e.type, nodeKind: 'relationEntity',
      matchStatus: e.matchStatus, matchStatusLabel: e.matchStatusLabel,
      matchCount: e.matchCount, tagCount: e.tagCount, relationCount: e.relationCount,
      areas: e.areas, isRoot: !!isRoot, sourceType: 'RELATION_EXCEL',
      style: styleFor(e.type, matched)
    };
  }

  function equipNode(id, isRoot) {
    var e = idx.equipById[id];
    if (!e) return null;
    var area = idx.areaById[e.a] || {};
    return {
      id: id, label: e.n, type: '生产设备', nodeKind: 'equipment',
      owlSubject: e.o, areaName: area.name, station: e.sn, tagCount: e.tc,
      matchStatus: 'MATCHED', isRoot: !!isRoot, sourceType: 'DCS_EXCEL',
      style: styleFor('生产设备', true)
    };
  }

  function paramNode(id, isRoot) {
    var p = idx.paramById[id];
    if (!p) return null;
    var e = idx.equipById[p.e] || {};
    return {
      id: id, label: p.n, type: '参数', nodeKind: 'parameter',
      equipmentName: e.n, categories: p.c, units: p.u, tagCount: (p.t || []).length,
      matchStatus: 'MATCHED', isRoot: !!isRoot, sourceType: 'DCS_EXCEL',
      style: styleFor('参数', true)
    };
  }

  function tagNode(id) {
    var t = idx.tagById[id];
    if (!t) return null;
    return {
      id: id, label: t.n, type: 'DCS点', nodeKind: 'tag',
      rawDescription: t.d, blockType: t.b, unit: t.u,
      matchStatus: 'MATCHED', sourceType: 'DCS_EXCEL',
      style: styleFor('DCS点', true)
    };
  }

  function areaNode(id, isRoot) {
    var a = idx.areaById[id];
    if (!a) return null;
    return {
      id: id, label: a.nameZh, type: '生产工段', nodeKind: 'area',
      fullName: a.name, tagCount: a.tagCount,
      matchStatus: 'MATCHED', isRoot: !!isRoot, sourceType: 'DCS_EXCEL',
      style: styleFor('生产工段', true)
    };
  }

  function structEdge(id, source, target, label, kind, color) {
    return {
      id: id, source: source, target: target, label: label,
      category: '本体结构', edgeKind: kind, weight: 1, matchStatus: 'MATCHED',
      sourceType: 'DCS_EXCEL',
      style: { color: color, lineStyle: 'solid', width: 1.4, opacity: 0.75 }
    };
  }

  function addRelation(rel, nodes, edges) {
    var sid = rel.subject.id, oid = rel.object.id;
    if (!sid || !oid) return;
    [sid, oid].forEach(function (nid) {
      if (!nodes[nid]) { var n = entityNode(nid); if (n) nodes[nid] = n; }
    });
    edges[rel.id] = {
      id: rel.id, source: sid, target: oid, label: rel.predicate,
      category: rel.category, area: rel.area, scenario: rel.scenario,
      weight: rel.weight, domainDescription: rel.domainDescription,
      matchStatus: rel.matchStatus, edgeKind: 'relation',
      // source/target 已用于图的端点，来源信息放在 provenance 字段
      sourceType: rel.sourceType, provenance: rel.source,
      style: edgeStyleFor(rel.category, rel.matchStatus === 'MATCHED', rel.weight)
    };
  }

  function buildGraph(q) {
    q = q || {};
    var depth = Math.max(1, Math.min(3, +(q.depth || 1)));
    var pool = filterRelations(q);
    var nodes = {}, edges = {}, truncated = false;
    var rootId = q.rootId || null;

    if (rootId && rootId.indexOf('robj-') === 0) {
      var root = entityNode(rootId, true);
      if (root) {
        nodes[rootId] = root;
        var byEntity = {};
        pool.forEach(function (r) {
          ['subject', 'object'].forEach(function (side) {
            var eid = r[side].id;
            if (eid) (byEntity[eid] = byEntity[eid] || []).push(r);
          });
        });
        var frontier = [rootId];
        for (var d = 0; d < depth && !truncated; d++) {
          var next = {};
          frontier.forEach(function (eid) {
            (byEntity[eid] || []).forEach(function (rel) {
              if (edges[rel.id]) return;
              addRelation(rel, nodes, edges);
              ['subject', 'object'].forEach(function (side) {
                var other = rel[side].id;
                if (other && other !== eid) next[other] = 1;
              });
              if (Object.keys(nodes).length > MAX_NODES) truncated = true;
            });
          });
          frontier = Object.keys(next);
        }
        if (q.includeDcs) attachAnchors(rootId, nodes, edges);
      }
    } else if (rootId && rootId.indexOf('equip-') === 0) {
      truncated = expandEquipment(rootId, nodes, edges, pool, depth);
    } else if (rootId && rootId.indexOf('param-') === 0) {
      expandParameter(rootId, nodes, edges, pool);
    } else if (rootId && rootId.indexOf('area-') === 0) {
      truncated = expandArea(rootId, nodes, edges, pool);
    } else {
      for (var i = 0; i < pool.length; i++) {
        addRelation(pool[i], nodes, edges);
        if (Object.keys(nodes).length > MAX_NODES) { truncated = true; break; }
      }
    }

    return {
      rootId: rootId, rootType: q.rootType || null, depth: depth,
      nodes: Object.keys(nodes).map(function (k) { return nodes[k]; }),
      edges: Object.keys(edges).map(function (k) { return edges[k]; }),
      nodeCount: Object.keys(nodes).length,
      edgeCount: Object.keys(edges).length,
      truncated: truncated, maxNodes: MAX_NODES,
      nodeStyles: (D.categories || {}).nodeStyles,
      edgeStyles: (D.categories || {}).edgeStyles
    };
  }

  function attachAnchors(entityId, nodes, edges) {
    var detail = (D.entityDetails || {})[entityId];
    if (!detail) return;
    (detail.matches || []).slice(0, 8).forEach(function (m) {
      var nid, n;
      if (m.objectType === 'equipment') {
        n = equipNode(m.id);
        if (!n) return;
        nid = 'dcs::' + m.id; n.id = nid; nodes[nid] = n;
        edges['map::' + entityId + '::' + nid] =
          structEdge('map::' + entityId + '::' + nid, entityId, nid, '匹配本体实例', 'mapping', '#6B7A90');
      } else if (m.objectType === 'parameter') {
        n = paramNode(m.id);
        if (!n) return;
        nid = 'dcs::' + m.id; n.id = nid; nodes[nid] = n;
        edges['map::' + entityId + '::' + nid] =
          structEdge('map::' + entityId + '::' + nid, entityId, nid, '测量锚点', 'anchor', '#F2C744');
        (m.tagIds || []).slice(0, 3).forEach(function (tid) {
          var t = tagNode(tid);
          if (!t) return;
          var tnid = 'dcs::' + tid; t.id = tnid; nodes[tnid] = t;
          edges['tag::' + nid + '::' + tnid] =
            structEdge('tag::' + nid + '::' + tnid, nid, tnid, 'boundToTag', 'tag', '#F2C744');
        });
      }
    });
  }

  function expandEquipment(equipmentId, nodes, edges, pool, depth) {
    var e = idx.equipById[equipmentId];
    if (!e) return false;
    nodes[equipmentId] = equipNode(equipmentId, true);
    if (e.a) {
      var a = areaNode(e.a);
      if (a) {
        nodes[a.id] = a;
        edges['has::' + a.id + '::' + equipmentId] =
          structEdge('has::' + a.id + '::' + equipmentId, a.id, equipmentId, 'hasEquipment', 'structure', '#4C8DFF');
      }
    }
    var truncated = false;
    (e.p || []).forEach(function (pid) {
      if (Object.keys(nodes).length > MAX_NODES) { truncated = true; return; }
      var n = paramNode(pid);
      if (!n) return;
      nodes[pid] = n;
      edges['has::' + equipmentId + '::' + pid] =
        structEdge('has::' + equipmentId + '::' + pid, equipmentId, pid, 'hasParameter', 'structure', '#35C4D7');
      if (depth >= 2) {
        ((idx.paramById[pid] || {}).t || []).forEach(function (tid) {
          if (Object.keys(nodes).length > MAX_NODES) { truncated = true; return; }
          var t = tagNode(tid);
          if (!t) return;
          nodes[tid] = t;
          edges['tag::' + pid + '::' + tid] =
            structEdge('tag::' + pid + '::' + tid, pid, tid, 'boundToTag', 'tag', '#F2C744');
        });
      }
    });
    linkEntities(equipmentId, nodes, edges, pool, '匹配本体实例', 'mapping', '#6B7A90');
    return truncated;
  }

  function expandParameter(parameterId, nodes, edges, pool) {
    var p = idx.paramById[parameterId];
    if (!p) return false;
    nodes[parameterId] = paramNode(parameterId, true);
    if (p.e) {
      var e = equipNode(p.e);
      if (e) {
        nodes[e.id] = e;
        edges['has::' + e.id + '::' + parameterId] =
          structEdge('has::' + e.id + '::' + parameterId, e.id, parameterId, 'hasParameter', 'structure', '#35C4D7');
      }
    }
    (p.t || []).forEach(function (tid) {
      var t = tagNode(tid);
      if (!t) return;
      nodes[tid] = t;
      edges['tag::' + parameterId + '::' + tid] =
        structEdge('tag::' + parameterId + '::' + tid, parameterId, tid, 'boundToTag', 'tag', '#F2C744');
    });
    linkEntities(parameterId, nodes, edges, pool, '测量锚点', 'anchor', '#F2C744');
    return false;
  }

  function linkEntities(objectId, nodes, edges, pool, label, kind, color) {
    var entityIds = (D.matchIndex || {})[objectId] || [];
    var relIds = {};
    entityIds.forEach(function (eid) {
      var n = entityNode(eid);
      if (!n) return;
      nodes[eid] = n;
      edges['map::' + eid + '::' + objectId] =
        structEdge('map::' + eid + '::' + objectId, eid, objectId, label, kind, color);
      var detail = (D.entityDetails || {})[eid];
      if (detail) {
        (detail.outgoingRelations || []).concat(detail.incomingRelations || [])
          .forEach(function (r) { relIds[r.id] = 1; });
      }
    });
    pool.forEach(function (r) { if (relIds[r.id]) addRelation(r, nodes, edges); });
  }

  function expandArea(areaId, nodes, edges, pool) {
    var a = idx.areaById[areaId];
    if (!a) return false;
    nodes[areaId] = areaNode(areaId, true);
    var list = (idx.equipByArea[areaId] || []).slice()
      .sort(function (x, y) { return y.tc - x.tc; }).slice(0, 24);
    list.forEach(function (e) {
      var n = equipNode(e.id);
      if (!n) return;
      nodes[e.id] = n;
      edges['has::' + areaId + '::' + e.id] =
        structEdge('has::' + areaId + '::' + e.id, areaId, e.id, 'hasEquipment', 'structure', '#4C8DFF');
    });
    pool.forEach(function (r) { if (r.dcsAreaId === areaId) addRelation(r, nodes, edges); });
    return (idx.equipByArea[areaId] || []).length > list.length;
  }

  // ------------------------------------------------------------- 静态实现

  var staticApi = {
    getOverview: function () { return D.overview; },
    getCategories: function () { return D.categories; },
    getProcessAreas: function () { return { items: D.areas, total: (D.areas || []).length }; },

    getProcessArea: function (areaId) {
      var area = idx.areaById[areaId];
      if (!area) return null;
      var equipment = (idx.equipByArea[areaId] || []).slice()
        .sort(function (a, b) { return b.tc - a.tc; }).map(equipOut);
      var rels = (D.relations || []).filter(function (r) { return r.dcsAreaId === areaId; });
      var byCategory = {};
      rels.forEach(function (r) {
        var k = r.category || '未标注';
        byCategory[k] = (byCategory[k] || 0) + 1;
      });
      return Object.assign({}, area, {
        equipment: equipment,
        relations: rels,
        relationCategoryCounts: byCategory
      });
    },

    getEquipment: function (q) {
      q = q || {};
      var items = D.equipment || [];
      if (q.sn) items = items.filter(function (e) { return String(e.sn) === String(q.sn); });
      if (q.areaId) items = items.filter(function (e) { return e.a === q.areaId; });
      if (q.keyword) items = items.filter(function (e) {
        return e.n.indexOf(q.keyword) >= 0 || (e.o || '').indexOf(q.keyword) >= 0;
      });
      items = items.slice().sort(function (a, b) { return b.tc - a.tc; });
      var p = page(items, q);
      p.items = p.items.map(equipOut);
      return p;
    },

    getEquipmentDetail: function (equipmentId) {
      var e = idx.equipById[equipmentId];
      if (!e) return null;
      var out = equipOut(e);
      var entityIds = (D.matchIndex || {})[equipmentId] || [];
      var relIds = {}, entities = [];
      entityIds.forEach(function (eid) {
        var brief = idx.entityById[eid];
        if (brief) entities.push(brief);
        var detail = (D.entityDetails || {})[eid];
        if (detail) {
          (detail.outgoingRelations || []).concat(detail.incomingRelations || [])
            .forEach(function (r) { relIds[r.id] = 1; });
        }
      });
      out.area = idx.areaById[e.a] || null;
      out.parameters = (idx.paramsByEquip[equipmentId] || []).map(paramOut);
      out.tags = (idx.tagsByEquip[equipmentId] || []).map(tagOut);
      out.relationEntities = entities;
      out.relations = (D.relations || []).filter(function (r) { return relIds[r.id]; });
      out.rules = rulesFor(e.n);
      return out;
    },

    getParameters: function (q) {
      q = q || {};
      var items = D.parameters || [];
      if (q.equipmentId) items = items.filter(function (p) { return p.e === q.equipmentId; });
      if (q.areaId) items = items.filter(function (p) {
        var e = idx.equipById[p.e]; return e && e.a === q.areaId;
      });
      if (q.category) items = items.filter(function (p) { return (p.c || []).indexOf(q.category) >= 0; });
      if (q.keyword) items = items.filter(function (p) { return p.n.indexOf(q.keyword) >= 0; });
      var pg = page(items, q);
      pg.items = pg.items.map(paramOut);
      return pg;
    },

    getParameterDetail: function (parameterId) {
      var p = idx.paramById[parameterId];
      if (!p) return null;
      var out = paramOut(p);
      var tags = (idx.tagsByParam[parameterId] || []).map(tagOut);
      out.equipment = equipOut(idx.equipById[p.e]);
      out.tags = tags;
      out.measurementAnchors = tags.map(function (t) { return anchorFrom(out, t); });
      var entityIds = (D.matchIndex || {})[parameterId] || [];
      var relIds = {}, entities = [];
      entityIds.forEach(function (eid) {
        var brief = idx.entityById[eid];
        if (brief) entities.push(brief);
        var detail = (D.entityDetails || {})[eid];
        if (detail) {
          (detail.outgoingRelations || []).concat(detail.incomingRelations || [])
            .forEach(function (r) { relIds[r.id] = 1; });
        }
      });
      out.relationEntities = entities;
      out.relations = (D.relations || []).filter(function (r) { return relIds[r.id]; });
      out.rules = rulesFor(p.n);
      return out;
    },

    getTags: function (q) {
      q = q || {};
      var items = D.tags || [];
      if (q.equipmentId) items = idx.tagsByEquip[q.equipmentId] || [];
      if (q.parameter) items = idx.tagsByParam[q.parameter] || [];
      if (q.areaId) items = items.filter(function (t) {
        var e = idx.equipById[t.e]; return e && e.a === q.areaId;
      });
      if (q.type) items = items.filter(function (t) { return t.pt === q.type; });
      if (q.blockType) items = items.filter(function (t) { return t.b === q.blockType; });
      if (q.keyword) items = items.filter(function (t) {
        return t.n.indexOf(q.keyword) >= 0 || (t.d || '').indexOf(q.keyword) >= 0;
      });
      var pg = page(items, q);
      pg.items = pg.items.map(tagOut);
      return pg;
    },

    getClasses: function () { return { items: D.classes, total: (D.classes || []).length }; },
    getProperties: function () { return { items: D.properties, total: (D.properties || []).length }; },
    getPredicates: function () { return { items: D.predicates, total: (D.predicates || []).length }; },

    getRelations: function (q) { return page(filterRelations(q), q); },

    getRelationDetail: function (relationId) {
      var rel = idx.relById[relationId];
      if (!rel) return null;
      return Object.assign({}, rel, {
        subjectDetail: idx.entityById[rel.subject.id] || null,
        objectDetail: idx.entityById[rel.object.id] || null,
        sameCategoryRelationIds: (D.relations || [])
          .filter(function (r) { return r.category === rel.category && r.id !== relationId; })
          .map(function (r) { return r.id; }),
        sameAreaRelationIds: (D.relations || [])
          .filter(function (r) { return r.area === rel.area && r.id !== relationId; })
          .map(function (r) { return r.id; }),
        sourceTypeLabel: '工业关系 Excel'
      });
    },

    getRelationEntities: function (q) {
      q = q || {};
      var items = (D.relationEntities || []).slice();
      if (q.type) items = items.filter(function (e) { return e.type === q.type; });
      if (q.matched === true || q.matched === false) {
        var want = q.matched ? 'MATCHED' : 'UNMATCHED';
        items = items.filter(function (e) { return e.matchStatus === want; });
      }
      if (q.keyword) items = items.filter(function (e) { return e.name.indexOf(q.keyword) >= 0; });
      items.sort(function (a, b) { return b.relationCount - a.relationCount; });
      return { items: items, total: items.length };
    },

    getRelationEntityDetail: function (entityId) { return (D.entityDetails || {})[entityId] || null; },

    getGraph: function (q) { return buildGraph(q); },

    getRules: function () { return D.rules; },
    getConstraints: function () { return (D.emptySets || {}).constraints; },
    getCapabilities: function () { return (D.emptySets || {}).capabilities; },
    getModelRegistry: function () { return (D.emptySets || {}).modelRegistry; },

    getSemantics: function (q) {
      q = q || {};
      var tags = D.tags || [];
      if (q.areaId) tags = tags.filter(function (t) {
        var e = idx.equipById[t.e]; return e && e.a === q.areaId;
      });
      if (q.keyword) tags = tags.filter(function (t) { return (t.d || '').indexOf(q.keyword) >= 0; });
      var limit = q.limit ? +q.limit : 200;
      return {
        dcsSemantics: tags.slice(0, limit).map(function (t) {
          var full = tagOut(t);
          return {
            id: full.id, rawDescription: full.rawDescription,
            parameterSemantic: full.parameterName, parameterId: full.parameterId,
            industrialObject: full.equipmentName, equipmentId: full.equipmentId,
            owlSubject: full.owlSubject, areaName: full.areaName,
            tagName: full.name, blockType: full.blockType,
            kind: 'DCS语义提升', sourceType: 'DCS_EXCEL', source: full.source
          };
        }),
        dcsSemanticTotal: tags.length,
        relationSemantics: (D.relations || []).map(function (r) {
          return {
            id: r.id, subjectEntity: r.subjectEntity, subjectType: r.subjectType,
            predicate: r.predicate, objectEntity: r.objectEntity, objectType: r.objectType,
            domainDescription: r.domainDescription, kind: '关系语义',
            sourceType: 'RELATION_EXCEL', source: r.source
          };
        }),
        relationSemanticTotal: (D.relations || []).length
      };
    },

    getMeasurementAnchors: function (q) {
      q = q || {};
      var items = [];
      Object.keys(D.entityDetails || {}).forEach(function (eid) {
        (D.entityDetails[eid].measurementAnchors || []).forEach(function (a) {
          if (q.areaId && a.areaId !== q.areaId) return;
          items.push(a);
        });
      });
      if (q.keyword) items = items.filter(function (a) {
        return (a.semanticName || '').indexOf(q.keyword) >= 0 || (a.tagName || '').indexOf(q.keyword) >= 0;
      });
      return {
        items: q.limit ? items.slice(0, +q.limit) : items,
        total: items.length,
        unanchoredEntities: (D.relationEntities || []).filter(function (e) { return !e.tagCount; })
      };
    },

    getCausalRelations: function () {
      var items = (D.relations || []).filter(function (r) { return r.isCausal; });
      return { items: items, total: items.length, categories: ['因果关系', '影响关系', '质量关系'] };
    },

    getObjectRelations: function (objectId) {
      if (objectId.indexOf(':') === 0) {
        var hit = (D.equipment || []).filter(function (e) { return e.o === objectId; })[0];
        if (hit) objectId = hit.id;
      }
      if (objectId.indexOf('equip-') === 0) return staticApi.getEquipmentDetail(objectId);
      if (objectId.indexOf('param-') === 0) return staticApi.getParameterDetail(objectId);
      if (objectId.indexOf('robj-') === 0) return staticApi.getRelationEntityDetail(objectId);
      if (objectId.indexOf('area-') === 0) return staticApi.getProcessArea(objectId);
      return null;
    },

    getDataSources: function () { return D.dataSources; },
    getDataQuality: function () { return D.dataQuality; },
    getTurtle: function () { return D.turtle; },
    getRelationOverview: function () { return D.relationOverview; },
    getMeta: function () { return D.meta; }
  };

  function anchorFrom(param, tag) {
    return {
      id: 'anchor-' + tag.id.slice(4),
      semanticName: param.name, parameterId: param.id,
      equipmentId: param.equipmentId, equipmentName: param.equipmentName,
      owlSubject: param.owlSubject, areaId: param.areaId, areaName: param.areaName,
      parameterType: tag.parameterType, tagId: tag.id, tagName: tag.name,
      rawDescription: tag.rawDescription, blockType: tag.blockType,
      unit: tag.unit, station: tag.station,
      sourceType: 'DCS_EXCEL', source: tag.source
    };
  }

  function rulesFor(name) {
    var rules = (D.rules && D.rules.items) || [];
    if (!name) return [];
    return rules.filter(function (r) { return (r.appliesTo || '').indexOf(name) >= 0; });
  }

  // ------------------------------------------------------------- live 模式

  function qs(q) {
    if (!q) return '';
    var parts = [];
    Object.keys(q).forEach(function (k) {
      if (q[k] === null || q[k] === undefined || q[k] === '') return;
      parts.push(encodeURIComponent(k) + '=' + encodeURIComponent(q[k]));
    });
    return parts.length ? '?' + parts.join('&') : '';
  }

  function live(path, q) {
    return fetch(BASE + path + qs(q)).then(function (r) {
      return r.ok ? r.json() : null;
    });
  }

  var liveApi = {
    getOverview: function () { return live('/api/ontology/overview'); },
    getCategories: function () { return live('/api/ontology/categories'); },
    getProcessAreas: function () { return live('/api/ontology/process-areas'); },
    getProcessArea: function (id) { return live('/api/ontology/process-areas/' + id); },
    getEquipment: function (q) { return live('/api/ontology/equipment', q); },
    getEquipmentDetail: function (id) { return live('/api/ontology/equipment/' + id); },
    getParameters: function (q) { return live('/api/ontology/parameters', q); },
    getParameterDetail: function (id) { return live('/api/ontology/parameters/' + id); },
    getTags: function (q) { return live('/api/ontology/tags', q); },
    getClasses: function () { return live('/api/ontology/classes'); },
    getProperties: function () { return live('/api/ontology/properties'); },
    getPredicates: function () { return live('/api/ontology/properties'); },
    getRelations: function (q) { return live('/api/ontology/relations', q); },
    getRelationDetail: function (id) { return live('/api/ontology/relations/' + id); },
    getRelationEntities: function (q) { return live('/api/ontology/relation-entities', q); },
    getRelationEntityDetail: function (id) { return live('/api/ontology/relation-entities/' + id); },
    getGraph: function (q) { return live('/api/ontology/graph', q); },
    getRules: function (q) { return live('/api/ontology/rules', q); },
    getConstraints: function () { return live('/api/ontology/constraints'); },
    getCapabilities: function () { return live('/api/ontology/capabilities'); },
    getModelRegistry: function () { return live('/api/ontology/model-registry'); },
    getSemantics: function (q) { return live('/api/ontology/semantics', q); },
    getMeasurementAnchors: function (q) { return live('/api/ontology/measurement-anchors', q); },
    getCausalRelations: function () { return live('/api/ontology/causal-relations'); },
    getObjectRelations: function (id) { return live('/api/ontology/' + encodeURIComponent(id) + '/relations'); },
    getDataSources: function () { return live('/api/ontology/data-sources'); },
    getDataQuality: function () { return live('/api/ontology/data-quality'); },
    getTurtle: function () { return live('/api/ontology/turtle'); },
    getRelationOverview: function () { return live('/api/ontology/relations', { limit: 1 }); },
    getMeta: function () { return Promise.resolve({ generatedAt: null }); }
  };

  // 统一成 Promise 接口，页面代码在两种模式下写法一致
  function wrap(impl) {
    var out = {};
    Object.keys(impl).forEach(function (k) {
      out[k] = function () {
        var r = impl[k].apply(null, arguments);
        return (r && typeof r.then === 'function') ? r : Promise.resolve(r);
      };
    });
    return out;
  }

  buildIndexes();

  global.OntologyApi = Object.assign(wrap(MODE === 'live' ? liveApi : staticApi), {
    mode: MODE,
    baseUrl: BASE,
    endpoints: [
      '/api/ontology/overview', '/api/ontology/categories', '/api/ontology/process-areas',
      '/api/ontology/process-areas/{id}', '/api/ontology/equipment', '/api/ontology/equipment/{id}',
      '/api/ontology/parameters', '/api/ontology/parameters/{id}', '/api/ontology/tags',
      '/api/ontology/classes', '/api/ontology/properties', '/api/ontology/relations',
      '/api/ontology/relations/{id}', '/api/ontology/relation-entities',
      '/api/ontology/relation-entities/{id}', '/api/ontology/graph', '/api/ontology/rules',
      '/api/ontology/capabilities', '/api/ontology/constraints', '/api/ontology/model-registry',
      '/api/ontology/semantics', '/api/ontology/measurement-anchors',
      '/api/ontology/causal-relations', '/api/ontology/{id}/relations',
      '/api/ontology/data-sources', '/api/ontology/data-quality'
    ]
  });
})(window);
