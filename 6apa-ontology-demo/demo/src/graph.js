/*
 * 局部语义图渲染器（零依赖 SVG 力导向布局）。
 *
 * 只负责把 /api/ontology/graph 返回的 nodes / edges 画出来，
 * 节点颜色、边样式、线型与边宽全部取自接口返回的 style 字段，
 * 不在此处推断任何语义。
 */
(function (global) {
  'use strict';

  var NS = 'http://www.w3.org/2000/svg';

  function el(name, attrs) {
    var node = document.createElementNS(NS, name);
    if (attrs) Object.keys(attrs).forEach(function (k) { node.setAttribute(k, attrs[k]); });
    return node;
  }

  function dashFor(lineStyle) {
    if (lineStyle === 'dashed') return '7 5';
    if (lineStyle === 'dotted') return '2 4';
    return null;
  }

  function radiusFor(node) {
    if (node.isRoot) return 26;
    if (node.nodeKind === 'tag') return 11;
    if (node.nodeKind === 'area') return 20;
    return 15;
  }

  function RelationGraph(container, options) {
    this.container = container;
    this.options = options || {};
    this.onNodeClick = this.options.onNodeClick || function () {};
    this.onEdgeClick = this.options.onEdgeClick || function () {};
    this.transform = { x: 0, y: 0, k: 1 };
    this.selected = null;
    this._raf = null;
    this._build();
  }

  RelationGraph.prototype._build = function () {
    var self = this;
    this.container.innerHTML = '';
    this.svg = el('svg', { class: 'graph-svg', width: '100%', height: '100%' });
    var defs = el('defs');
    ['#8FA6C4', '#4C8DFF', '#5FD0A8', '#3FCF8E', '#FFB86B', '#F2557A', '#E77CC0', '#6B7A90', '#F2C744', '#35C4D7']
      .forEach(function (color) {
        var m = el('marker', {
          id: 'arrow-' + color.slice(1), viewBox: '0 0 10 10', refX: 10, refY: 5,
          markerWidth: 6, markerHeight: 6, orient: 'auto-start-reverse'
        });
        m.appendChild(el('path', { d: 'M 0 0 L 10 5 L 0 10 z', fill: color }));
        defs.appendChild(m);
      });
    this.svg.appendChild(defs);

    this.viewport = el('g', { class: 'graph-viewport' });
    this.edgeLayer = el('g', { class: 'graph-edges' });
    this.edgeLabelLayer = el('g', { class: 'graph-edge-labels' });
    this.nodeLayer = el('g', { class: 'graph-nodes' });
    this.viewport.appendChild(this.edgeLayer);
    this.viewport.appendChild(this.edgeLabelLayer);
    this.viewport.appendChild(this.nodeLayer);
    this.svg.appendChild(this.viewport);
    this.container.appendChild(this.svg);

    this.svg.addEventListener('wheel', function (e) {
      e.preventDefault();
      var factor = e.deltaY < 0 ? 1.12 : 1 / 1.12;
      var next = Math.max(0.3, Math.min(3, self.transform.k * factor));
      var rect = self.svg.getBoundingClientRect();
      var mx = e.clientX - rect.left, my = e.clientY - rect.top;
      self.transform.x = mx - (mx - self.transform.x) * (next / self.transform.k);
      self.transform.y = my - (my - self.transform.y) * (next / self.transform.k);
      self.transform.k = next;
      self._applyTransform();
    }, { passive: false });

    var dragging = false, last = null;
    this.svg.addEventListener('pointerdown', function (e) {
      // 命中节点或关系边时不启动平移：setPointerCapture 会把随后的 click
      // 事件改派给 svg 本身，导致节点/边的点击回调收不到事件。
      if (e.target.closest('.graph-node, .graph-edge, .graph-edge-label')) return;
      dragging = true; last = { x: e.clientX, y: e.clientY };
      self.svg.setPointerCapture(e.pointerId);
      self.svg.style.cursor = 'grabbing';
    });
    this.svg.addEventListener('pointermove', function (e) {
      if (!dragging) return;
      self.transform.x += e.clientX - last.x;
      self.transform.y += e.clientY - last.y;
      last = { x: e.clientX, y: e.clientY };
      self._applyTransform();
    });
    ['pointerup', 'pointercancel'].forEach(function (ev) {
      self.svg.addEventListener(ev, function () { dragging = false; self.svg.style.cursor = ''; });
    });
  };

  RelationGraph.prototype._applyTransform = function () {
    var t = this.transform;
    this.viewport.setAttribute('transform', 'translate(' + t.x + ',' + t.y + ') scale(' + t.k + ')');
  };

  RelationGraph.prototype.render = function (graph) {
    var self = this;
    this.graph = graph;
    var rect = this.container.getBoundingClientRect();
    var W = Math.max(360, rect.width), H = Math.max(320, rect.height);

    var nodes = graph.nodes.map(function (n) { return Object.assign({}, n); });
    var byId = {};
    nodes.forEach(function (n) { byId[n.id] = n; });
    var edges = graph.edges.filter(function (e) { return byId[e.source] && byId[e.target]; });

    var degree = {};
    edges.forEach(function (e) {
      degree[e.source] = (degree[e.source] || 0) + 1;
      degree[e.target] = (degree[e.target] || 0) + 1;
    });

    // 初始位置：根节点居中，其余按度数分环排布，布局更快收敛
    var ring = nodes.filter(function (n) { return !n.isRoot; });
    nodes.forEach(function (n, i) {
      if (n.isRoot) { n.x = W / 2; n.y = H / 2; n.fixed = true; return; }
      var k = ring.indexOf(n);
      var angle = (k / Math.max(1, ring.length)) * Math.PI * 2;
      var r = Math.min(W, H) * (n.nodeKind === 'tag' ? 0.40 : 0.34) + (i % 5) * 22;
      n.x = W / 2 + Math.cos(angle) * r;
      n.y = H / 2 + Math.sin(angle) * r;
    });

    this._simulate(nodes, edges, W, H, degree);
    this._draw(nodes, edges, byId);

    // 适配视口
    var xs = nodes.map(function (n) { return n.x; }), ys = nodes.map(function (n) { return n.y; });
    var pad = 74;
    var minX = Math.min.apply(null, xs) - pad, maxX = Math.max.apply(null, xs) + pad;
    var minY = Math.min.apply(null, ys) - pad, maxY = Math.max.apply(null, ys) + pad;
    // 下限 0.62：全局图谱铺得很开时宁可留给用户平移，也不缩到标签不可读
    var k = Math.max(0.62, Math.min(W / Math.max(1, maxX - minX), H / Math.max(1, maxY - minY), 1.4));
    this.transform.k = k;
    this.transform.x = (W - (maxX - minX) * k) / 2 - minX * k;
    this.transform.y = (H - (maxY - minY) * k) / 2 - minY * k;
    this._applyTransform();
    return self;
  };

  RelationGraph.prototype._simulate = function (nodes, edges, W, H, degree) {
    // 无中心对象时是全局图谱，需要更大的斥力与更弱的向心力才能铺开
    var noRoot = !nodes.some(function (x) { return x.isRoot; });
    var iterations = nodes.length > 120 ? 220 : nodes.length > 60 ? 320 : 420;
    var linkDist = noRoot ? 128 : nodes.length > 60 ? 88 : 116;
    var charge = noRoot ? 10500 : nodes.length > 60 ? 5200 : 7200;
    var gravity = noRoot ? 0.0016 : 0.006;

    // 预解析边两端的节点引用，避免在迭代内做线性查找
    var byId = {};
    nodes.forEach(function (n) { byId[n.id] = n; });
    var links = [];
    edges.forEach(function (e) {
      var s = byId[e.source], t = byId[e.target];
      if (s && t) links.push({ s: s, t: t, want: e.edgeKind === 'tag' ? linkDist * 0.55 : linkDist });
    });

    for (var it = 0; it < iterations; it++) {
      var alpha = 1 - it / iterations;
      // 斥力
      for (var i = 0; i < nodes.length; i++) {
        var a = nodes[i];
        a.vx = a.vx || 0; a.vy = a.vy || 0;
        for (var j = i + 1; j < nodes.length; j++) {
          var b = nodes[j];
          var dx = a.x - b.x, dy = a.y - b.y;
          var d2 = dx * dx + dy * dy || 0.01;
          var d = Math.sqrt(d2);
          var f = charge / d2;
          var fx = (dx / d) * f, fy = (dy / d) * f;
          a.vx += fx; a.vy += fy;
          b.vx -= fx; b.vy -= fy;
        }
      }
      // 弹簧
      for (var L = 0; L < links.length; L++) {
        var lk = links[L], s = lk.s, t = lk.t;
        var ldx = t.x - s.x, ldy = t.y - s.y;
        var ld = Math.sqrt(ldx * ldx + ldy * ldy) || 0.01;
        var lf = (ld - lk.want) * 0.055;
        var lfx = (ldx / ld) * lf, lfy = (ldy / ld) * lf;
        s.vx += lfx; s.vy += lfy;
        t.vx -= lfx; t.vy -= lfy;
      }
      // 向心 + 阻尼
      nodes.forEach(function (n) {
        if (n.fixed) { n.vx = 0; n.vy = 0; return; }
        n.vx += (W / 2 - n.x) * gravity * (1 + 1 / (1 + (degree[n.id] || 0)));
        n.vy += (H / 2 - n.y) * gravity * (1 + 1 / (1 + (degree[n.id] || 0)));
        var damp = 0.62 * alpha + 0.12;
        n.x += Math.max(-24, Math.min(24, n.vx * damp));
        n.y += Math.max(-24, Math.min(24, n.vy * damp));
        n.vx *= 0.5; n.vy *= 0.5;
      });
    }
  };

  RelationGraph.prototype._draw = function (nodes, edges, byId) {
    var self = this;
    this.edgeLayer.innerHTML = '';
    this.edgeLabelLayer.innerHTML = '';
    this.nodeLayer.innerHTML = '';
    this._edgeEls = {};
    this._nodeEls = {};

    edges.forEach(function (e) {
      var s = byId[e.source], t = byId[e.target];
      var style = e.style || {};
      var r = radiusFor(t) + 7;
      var dx = t.x - s.x, dy = t.y - s.y;
      var d = Math.sqrt(dx * dx + dy * dy) || 1;
      var x2 = t.x - (dx / d) * r, y2 = t.y - (dy / d) * r;
      var rs = radiusFor(s) + 3;
      var x1 = s.x + (dx / d) * rs, y1 = s.y + (dy / d) * rs;

      var g = el('g', { class: 'graph-edge', 'data-id': e.id });
      var hit = el('line', { x1: x1, y1: y1, x2: x2, y2: y2, stroke: 'transparent', 'stroke-width': 14 });
      var line = el('line', {
        x1: x1, y1: y1, x2: x2, y2: y2,
        stroke: style.color || '#8FA6C4',
        'stroke-width': style.width || 1.5,
        'stroke-opacity': style.opacity == null ? 0.8 : style.opacity,
        'stroke-linecap': 'round',
        'marker-end': 'url(#arrow-' + String(style.color || '#8FA6C4').slice(1) + ')'
      });
      var dash = dashFor(style.lineStyle);
      if (dash) line.setAttribute('stroke-dasharray', dash);
      g.appendChild(line); g.appendChild(hit);
      g.addEventListener('click', function (ev) { ev.stopPropagation(); self.onEdgeClick(e); self.select(e.id); });
      self.edgeLayer.appendChild(g);
      self._edgeEls[e.id] = { g: g, line: line };

      // 对象映射边数量可能很多（一个工艺抽象对象对应多台现场设备），
      // 重复标签会淹没关系谓词，故只为其余边绘制标签。
      if (e.label && e.edgeKind !== 'mapping') {
        var mx = (x1 + x2) / 2, my = (y1 + y2) / 2;
        var label = el('text', {
          x: mx, y: my - 4, class: 'graph-edge-label',
          'text-anchor': 'middle', fill: style.color || '#8FA6C4'
        });
        label.textContent = e.label;
        label.addEventListener('click', function (ev) { ev.stopPropagation(); self.onEdgeClick(e); self.select(e.id); });
        self.edgeLabelLayer.appendChild(label);
      }
    });

    nodes.forEach(function (n) {
      var style = n.style || {};
      var r = radiusFor(n);
      var g = el('g', {
        class: 'graph-node' + (n.isRoot ? ' is-root' : ''),
        transform: 'translate(' + n.x + ',' + n.y + ')',
        'data-id': n.id
      });
      var unmatched = n.matchStatus === 'UNMATCHED';
      var shape;
      if (style.shape === 'roundRect') {
        shape = el('rect', { x: -r - 6, y: -r * 0.72, width: (r + 6) * 2, height: r * 1.44, rx: 6 });
      } else if (style.shape === 'diamond') {
        shape = el('path', { d: 'M0,' + -r + 'L' + r + ',0L0,' + r + 'L' + -r + ',0Z' });
      } else {
        shape = el('circle', { r: r });
      }
      shape.setAttribute('fill', unmatched ? 'transparent' : style.color || '#6B7A90');
      shape.setAttribute('fill-opacity', unmatched ? '0' : n.isRoot ? '1' : '0.86');
      shape.setAttribute('stroke', style.color || '#6B7A90');
      shape.setAttribute('stroke-width', n.isRoot ? 3 : 1.6);
      if (unmatched) shape.setAttribute('stroke-dasharray', '5 4');
      g.appendChild(shape);

      var label = el('text', {
        y: r + 15, class: 'graph-node-label', 'text-anchor': 'middle'
      });
      label.textContent = n.label && n.label.length > 14 ? n.label.slice(0, 13) + '…' : n.label;
      g.appendChild(label);

      var title = el('title');
      title.textContent = [n.label, n.type, n.matchStatusLabel || '', n.owlSubject || '']
        .filter(Boolean).join(' · ');
      g.appendChild(title);

      g.addEventListener('click', function (ev) { ev.stopPropagation(); self.onNodeClick(n); self.select(n.id); });
      self.nodeLayer.appendChild(g);
      self._nodeEls[n.id] = g;
    });
  };

  RelationGraph.prototype.select = function (id) {
    this.selected = id;
    Object.keys(this._nodeEls || {}).forEach(function (k) {
      this._nodeEls[k].classList.toggle('is-selected', k === id);
    }, this);
    Object.keys(this._edgeEls || {}).forEach(function (k) {
      this._edgeEls[k].g.classList.toggle('is-selected', k === id);
    }, this);
  };

  RelationGraph.prototype.destroy = function () {
    if (this._raf) cancelAnimationFrame(this._raf);
    this.container.innerHTML = '';
  };

  global.RelationGraph = RelationGraph;
})(window);
