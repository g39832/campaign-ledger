/* Battle map renderer + pointer interaction, shared by the DM editor and the
   player screen. It draws whatever data it is given; what a player receives
   has already been filtered by the server. */
(function () {
  "use strict";
  const TERRAIN = {
    floor: { fill: "#e9dfc8", label: "Floor" }, wall: { fill: "#3a332b", label: "Wall" }, water: { fill: "#5a87a6", label: "Water" },
    difficult: { fill: "#a68b5b", label: "Difficult", hatch: true }, pit: { fill: "#15110d", label: "Pit" },
    door: { fill: "#8a5a2b", label: "Door" }, foliage: { fill: "#5f7d45", label: "Foliage", hatch: true },
  };
  const KIND_COLOR = { pc: "#c7a25e", npc: "#6f8fae", enemy: "#b2402e", trap: "#7d4f8f", marker: "#8b8273", object: "#7a5a3a" };

  function initials(s) { return (s || "?").split(/\s+/).filter(Boolean).map((w) => w[0]).join("").slice(0, 2).toUpperCase(); }

  class MapView {
    constructor(stage, opts) {
      this.stage = stage;
      this.opts = opts || {};
      this.canvas = document.createElement("canvas");
      this.canvas.className = "map-canvas";
      stage.prepend(this.canvas);
      this.ctx = this.canvas.getContext("2d");
      this.view = { s: 1, tx: 0, ty: 0 };
      this.map = null; this.tokens = []; this.tool = "select"; this.brush = 1;
      this.images = {}; this.pointers = new Map(); this.drag = null; this.preview = new Set();
      this.selectedId = null; this.fitted = false;
      new ResizeObserver(() => this.resize()).observe(stage);
      this.bind();
      this.resize();
    }
    resize() {
      const r = this.stage.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
      this.w = r.width; this.h = r.height;
      this.canvas.width = Math.round(r.width * dpr); this.canvas.height = Math.round(r.height * dpr);
      this.draw();
    }
    setData(map, tokens) {
      const first = !this.map || this.map.id !== map.id;
      this.map = map; this.tokens = tokens;
      if (this.drag && this.drag.token) {
        const t = tokens.find((x) => x.id === this.drag.token.id);
        if (t) this.drag.token = t;
      }
      const url = this.opts.imageUrl ? this.opts.imageUrl(map) : null;
      if (url && (!this.bg || this.bg.src.indexOf(url) < 0)) {
        const img = new Image();
        img.onload = () => { this.bg = img; this.draw(); };
        img.src = url;
      } else if (!url) this.bg = null;
      if (first || !this.fitted) this.fit();
      this.draw();
    }
    worldSize() {
      const m = this.map;
      return { W: m.image_w ? Math.max(m.image_w, m.offset_x + m.cols * m.cell_px) : m.cols * m.cell_px,
        H: m.image_h ? Math.max(m.image_h, m.offset_y + m.rows * m.cell_px) : m.rows * m.cell_px };
    }
    fit() {
      if (!this.map || !this.w) return;
      const { W, H } = this.worldSize();
      const s = Math.min(this.w / W, this.h / H) * 0.94;
      this.view = { s, tx: (this.w - W * s) / 2, ty: (this.h - H * s) / 2 };
      this.fitted = true;
      this.draw();
    }
    zoom(f, cx, cy) {
      cx = cx ?? this.w / 2; cy = cy ?? this.h / 2;
      const s = Math.max(0.08, Math.min(8, this.view.s * f));
      const k = s / this.view.s;
      this.view = { s, tx: cx - (cx - this.view.tx) * k, ty: cy - (cy - this.view.ty) * k };
      this.draw();
    }
    toWorld(px, py) { return [(px - this.view.tx) / this.view.s, (py - this.view.ty) / this.view.s]; }
    toCell(px, py) {
      const [wx, wy] = this.toWorld(px, py), m = this.map;
      return [(wx - m.offset_x) / m.cell_px, (wy - m.offset_y) / m.cell_px];
    }
    tokenAt(px, py) {
      const [cx, cy] = this.toCell(px, py);
      for (let i = this.tokens.length - 1; i >= 0; i--) {
        const t = this.tokens[i];
        if (cx >= t.x && cx < t.x + t.size && cy >= t.y && cy < t.y + t.size) return t;
      }
      return null;
    }
    revealed(x, y) { const m = this.map; const i = y * m.cols + x; return m.revealed && m.revealed[i] === "1"; }

    // ---- drawing ----------------------------------------------------------------
    draw() {
      const ctx = this.ctx, m = this.map, dpr = window.devicePixelRatio || 1;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, this.w, this.h);
      if (!m) return;
      const { s, tx, ty } = this.view, cp = m.cell_px, ox = m.offset_x, oy = m.offset_y;
      ctx.setTransform(dpr * s, 0, 0, dpr * s, dpr * tx, dpr * ty);
      const gw = m.cols * cp, gh = m.rows * cp;
      if (this.bg) ctx.drawImage(this.bg, 0, 0);
      else { ctx.fillStyle = m.bg_color || "#d9ccae"; ctx.fillRect(ox, oy, gw, gh); }
      // terrain
      for (const [key, kind] of Object.entries(m.terrain || {})) {
        const [x, y] = key.split(",").map(Number), T = TERRAIN[kind];
        if (!T) continue;
        ctx.fillStyle = T.fill;
        ctx.globalAlpha = this.bg ? 0.7 : 1;
        ctx.fillRect(ox + x * cp, oy + y * cp, cp, cp);
        if (T.hatch) {
          ctx.strokeStyle = "rgba(0,0,0,.25)"; ctx.lineWidth = cp * 0.04;
          ctx.save(); ctx.beginPath(); ctx.rect(ox + x * cp, oy + y * cp, cp, cp); ctx.clip();
          ctx.beginPath(); for (let k = -1; k <= 1; k += 0.5) { ctx.moveTo(ox + (x + k) * cp, oy + (y + 1) * cp); ctx.lineTo(ox + (x + k + 1) * cp, oy + y * cp); }
          ctx.stroke(); ctx.restore();
        }
        ctx.globalAlpha = 1;
      }
      // grid
      if (m.show_grid) {
        ctx.strokeStyle = m.grid_color || "#000"; ctx.globalAlpha = (m.grid_opacity ?? 35) / 100;
        ctx.lineWidth = Math.max(1 / s, cp * 0.02);
        ctx.beginPath();
        for (let x = 0; x <= m.cols; x++) { ctx.moveTo(ox + x * cp, oy); ctx.lineTo(ox + x * cp, oy + gh); }
        for (let y = 0; y <= m.rows; y++) { ctx.moveTo(ox, oy + y * cp); ctx.lineTo(ox + gw, oy + y * cp); }
        ctx.stroke(); ctx.globalAlpha = 1;
      }
      // tokens
      for (const t of this.tokens) this.drawToken(t, cp, ox, oy);
      // fog
      if (m.fog_enabled) {
        const dm = this.opts.role === "dm";
        ctx.fillStyle = dm ? "rgba(10,8,6,.55)" : "#080706";
        for (let y = 0; y < m.rows; y++) for (let x = 0; x < m.cols; x++) {
          if (!this.revealed(x, y)) ctx.fillRect(ox + x * cp - 0.5, oy + y * cp - 0.5, cp + 1, cp + 1);
        }
      }
      // brush preview
      if (this.preview.size) {
        ctx.fillStyle = this.tool === "conceal" ? "rgba(10,8,6,.5)" : this.tool === "reveal" ? "rgba(255,240,200,.35)" : "rgba(199,162,94,.45)";
        for (const k of this.preview) { const [x, y] = k.split(",").map(Number); ctx.fillRect(ox + x * cp, oy + y * cp, cp, cp); }
      }
      // ruler
      if (this.ruler) {
        const [a, b] = this.ruler;
        const cells = Math.max(Math.abs(Math.round(b[0]) - Math.round(a[0])), Math.abs(Math.round(b[1]) - Math.round(a[1])));
        const p = (c) => [ox + (Math.floor(c[0]) + 0.5) * cp, oy + (Math.floor(c[1]) + 0.5) * cp];
        const [x1, y1] = p(a), [x2, y2] = p(b);
        ctx.strokeStyle = "#e0714f"; ctx.lineWidth = cp * 0.08; ctx.setLineDash([cp * 0.2, cp * 0.15]);
        ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke(); ctx.setLineDash([]);
        const label = cells * m.scale_value + " " + m.scale_unit;
        ctx.font = `700 ${cp * 0.42}px 'Alegreya Sans', sans-serif`;
        const w = ctx.measureText(label).width + cp * 0.3;
        ctx.fillStyle = "rgba(20,16,12,.85)"; ctx.fillRect(x2 + cp * 0.3, y2 - cp * 0.6, w, cp * 0.6);
        ctx.fillStyle = "#fff"; ctx.textBaseline = "middle"; ctx.fillText(label, x2 + cp * 0.45, y2 - cp * 0.3);
      }
    }
    drawToken(t, cp, ox, oy) {
      const ctx = this.ctx;
      const dragging = this.drag && this.drag.token && this.drag.token.id === t.id && this.drag.moved;
      const x = dragging ? this.drag.at[0] : t.x, y = dragging ? this.drag.at[1] : t.y;
      const cx = ox + (x + t.size / 2) * cp, cy = oy + (y + t.size / 2) * cp, r = t.size * cp * 0.42;
      const color = t.color || KIND_COLOR[t.kind] || "#888";
      ctx.save();
      if (t.hidden || t.combatant_hidden) ctx.globalAlpha = 0.55;
      if (t.is_current) { ctx.beginPath(); ctx.arc(cx, cy, r + cp * 0.1, 0, Math.PI * 2); ctx.fillStyle = "#e0714f"; ctx.fill(); }
      ctx.beginPath(); ctx.arc(cx, cy, r, 0, Math.PI * 2);
      ctx.fillStyle = color; ctx.fill();
      const img = t.portrait ? this.portrait(t.portrait) : null;
      if (img && img.complete && img.naturalWidth) {
        ctx.save(); ctx.beginPath(); ctx.arc(cx, cy, r * 0.86, 0, Math.PI * 2); ctx.clip();
        ctx.drawImage(img, cx - r, cy - r, r * 2, r * 2); ctx.restore();
      } else {
        ctx.fillStyle = t.kind === "pc" ? "#1d140a" : "#fff";
        ctx.font = `700 ${r * 0.8}px 'Alegreya SC', serif`; ctx.textAlign = "center"; ctx.textBaseline = "middle";
        ctx.fillText(initials(t.display), cx, cy + r * 0.05);
      }
      ctx.lineWidth = cp * 0.05;
      ctx.strokeStyle = this.selectedId === t.id ? "#f3d58a" : "rgba(0,0,0,.6)";
      if (t.hidden || t.combatant_hidden) ctx.setLineDash([cp * 0.12, cp * 0.08]);
      ctx.beginPath(); ctx.arc(cx, cy, r, 0, Math.PI * 2); ctx.stroke(); ctx.setLineDash([]);
      if (t.status === "dead" || t.status === "defeated" || t.health === "down") {
        ctx.strokeStyle = "rgba(20,0,0,.85)"; ctx.lineWidth = cp * 0.08;
        ctx.beginPath(); ctx.moveTo(cx - r * 0.6, cy - r * 0.6); ctx.lineTo(cx + r * 0.6, cy + r * 0.6);
        ctx.moveTo(cx + r * 0.6, cy - r * 0.6); ctx.lineTo(cx - r * 0.6, cy + r * 0.6); ctx.stroke();
      }
      if (t.hp != null && t.max_hp) {
        const w = r * 1.6, hgt = cp * 0.1, p = Math.max(0, Math.min(1, t.hp / t.max_hp));
        ctx.fillStyle = "rgba(0,0,0,.65)"; ctx.fillRect(cx - w / 2, cy + r + cp * 0.04, w, hgt);
        ctx.fillStyle = p > 0.5 ? "#7da05a" : p > 0.25 ? "#c9a03c" : "#d0603f";
        ctx.fillRect(cx - w / 2, cy + r + cp * 0.04, w * p, hgt);
      } else if (t.health === "bloodied") {
        ctx.fillStyle = "#b2402e"; ctx.beginPath(); ctx.arc(cx + r * 0.75, cy - r * 0.75, cp * 0.1, 0, Math.PI * 2); ctx.fill();
      }
      if (this.opts.showLabels !== false && this.view.s * cp > 34) {
        ctx.font = `600 ${cp * 0.26}px 'Alegreya Sans', sans-serif`; ctx.textAlign = "center"; ctx.textBaseline = "top";
        const label = t.display.length > 16 ? t.display.slice(0, 15) + "…" : t.display;
        const lw = ctx.measureText(label).width + cp * 0.16, ly = cy + r + cp * 0.18;
        ctx.fillStyle = "rgba(20,16,12,.75)"; ctx.fillRect(cx - lw / 2, ly, lw, cp * 0.32);
        ctx.fillStyle = "#f3ead6"; ctx.fillText(label, cx, ly + cp * 0.03);
      }
      ctx.restore();
    }
    portrait(name) {
      if (!this.images[name]) { const img = new Image(); img.onload = () => this.draw(); img.src = "/api/uploads/" + name; this.images[name] = img; }
      return this.images[name];
    }

    // ---- pointer handling ---------------------------------------------------------------
    pos(e) { const r = this.canvas.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; }
    brushCells(px, py) {
      const [cx, cy] = this.toCell(px, py).map(Math.floor), out = [], b = this.brush, half = Math.floor(b / 2);
      for (let dx = -half; dx < b - half; dx++) for (let dy = -half; dy < b - half; dy++) {
        const x = cx + dx, y = cy + dy;
        if (x >= 0 && y >= 0 && x < this.map.cols && y < this.map.rows) out.push(x + "," + y);
      }
      return out;
    }
    bind() {
      const c = this.canvas;
      c.addEventListener("wheel", (e) => { e.preventDefault(); const [x, y] = this.pos(e); this.zoom(e.deltaY < 0 ? 1.15 : 1 / 1.15, x, y); }, { passive: false });
      c.addEventListener("pointerdown", (e) => {
        if (!this.map) return;
        c.setPointerCapture(e.pointerId);
        const p = this.pos(e);
        this.pointers.set(e.pointerId, p);
        if (this.pointers.size === 2) { // pinch
          const [a, b] = [...this.pointers.values()];
          this.drag = { pinch: true, d0: Math.hypot(a[0] - b[0], a[1] - b[1]), s0: this.view.s, mid: [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2], view0: { ...this.view } };
          this.preview.clear(); this.ruler = null;
          return;
        }
        const tool = e.button === 1 || e.button === 2 ? "pan" : this.tool;
        if (tool === "select") {
          const t = this.tokenAt(...p);
          if (t) {
            this.selectedId = t.id;
            if (this.opts.onSelect) this.opts.onSelect(t);
            const canMove = this.opts.canMove ? this.opts.canMove(t) : true;
            if (canMove) { const [cx, cy] = this.toCell(...p); this.drag = { token: t, grab: [cx - t.x, cy - t.y], at: [t.x, t.y], moved: false }; this.draw(); return; }
          } else if (this.opts.onSelect) { this.selectedId = null; this.opts.onSelect(null); }
          this.drag = { pan: true, start: p, view0: { ...this.view } };
        } else if (tool === "pan") {
          this.drag = { pan: true, start: p, view0: { ...this.view } };
        } else if (tool === "measure") {
          const cell = this.toCell(...p); this.drag = { measure: true }; this.ruler = [cell, cell];
        } else if (tool === "place") {
          const [x, y] = this.toCell(...p).map(Math.floor);
          if (this.opts.onPlace && x >= 0 && y >= 0 && x < this.map.cols && y < this.map.rows) this.opts.onPlace(x, y);
        } else { // reveal / conceal / paint brushes
          this.drag = { brush: true };
          this.brushCells(...p).forEach((k) => this.preview.add(k));
        }
        this.draw();
      });
      c.addEventListener("pointermove", (e) => {
        if (!this.pointers.has(e.pointerId)) return;
        const p = this.pos(e);
        this.pointers.set(e.pointerId, p);
        const d = this.drag;
        if (!d) return;
        if (d.pinch && this.pointers.size === 2) {
          const [a, b] = [...this.pointers.values()];
          const dist = Math.hypot(a[0] - b[0], a[1] - b[1]), mid = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
          const s = Math.max(0.08, Math.min(8, d.s0 * dist / d.d0)), k = s / d.view0.s;
          this.view = { s, tx: mid[0] - (d.mid[0] - d.view0.tx) * k, ty: mid[1] - (d.mid[1] - d.view0.ty) * k };
        } else if (d.pan) {
          this.view = { ...d.view0, tx: d.view0.tx + p[0] - d.start[0], ty: d.view0.ty + p[1] - d.start[1] };
        } else if (d.token) {
          const [cx, cy] = this.toCell(...p);
          let nx = cx - d.grab[0], ny = cy - d.grab[1];
          if (this.map.snap) { nx = Math.round(nx); ny = Math.round(ny); }
          nx = Math.max(0, Math.min(this.map.cols - d.token.size, nx)); ny = Math.max(0, Math.min(this.map.rows - d.token.size, ny));
          d.moved = d.moved || Math.abs(nx - d.token.x) > 0.05 || Math.abs(ny - d.token.y) > 0.05;
          d.at = [nx, ny];
          if (d.moved) this.ruler = [[d.token.x + 0.01, d.token.y + 0.01], [nx + 0.01, ny + 0.01]];
        } else if (d.measure) {
          this.ruler[1] = this.toCell(...p);
        } else if (d.brush) {
          this.brushCells(...p).forEach((k) => this.preview.add(k));
        }
        this.draw();
      });
      const end = (e) => {
        if (!this.pointers.has(e.pointerId)) return;
        this.pointers.delete(e.pointerId);
        const d = this.drag;
        if (d && d.pinch) { if (!this.pointers.size) this.drag = null; return; }
        this.drag = null;
        if (d && d.token && d.moved && this.opts.onMove) {
          const tok = d.token; tok.x = d.at[0]; tok.y = d.at[1];
          this.opts.onMove(tok, d.at[0], d.at[1]);
        }
        if (d && d.brush && this.preview.size && this.opts.onBrush) {
          this.opts.onBrush(this.tool, [...this.preview].map((k) => k.split(",").map(Number)));
        }
        this.preview.clear();
        if (!(d && d.measure)) this.ruler = null;
        this.draw();
      };
      c.addEventListener("pointerup", end);
      c.addEventListener("pointercancel", end);
      c.addEventListener("contextmenu", (e) => e.preventDefault());
    }
  }
  window.MapView = MapView;
  window.MapView.TERRAIN = TERRAIN;
  window.MapView.KIND_COLOR = KIND_COLOR;
})();
