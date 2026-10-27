/* Battle map renderer + pointer interaction, shared by the DM editor and the
   player screen. It draws whatever data it is given; what a player receives
   has already been filtered by the server.

   On top of the map it animates short-lived effects: pings ("look here"),
   floating damage/heal numbers when a token's HP changes, and a pulse on the
   token whose turn it is. Spell areas (circle, cone, line, square) are drawn
   with the squares they cover highlighted. */
(function () {
  "use strict";
  const TERRAIN = {
    floor: { fill: "#e9dfc8", label: "Floor" }, wall: { fill: "#3a332b", label: "Wall" }, water: { fill: "#5a87a6", label: "Water", ripple: true },
    difficult: { fill: "#a68b5b", label: "Difficult", hatch: true }, pit: { fill: "#15110d", label: "Pit", pit: true },
    door: { fill: "#8a5a2b", label: "Door", door: true }, foliage: { fill: "#5f7d45", label: "Bushes", hatch: true },
    grass: { fill: "#7e9c5a", label: "Grass", speckle: "#6c8a4a" }, sand: { fill: "#d8c28a", label: "Sand / dirt", speckle: "#c4ac72" },
    stone: { fill: "#9a9184", label: "Stone floor", tiles: true }, wood: { fill: "#a0743f", label: "Wood planks", planks: true },
    lava: { fill: "#d0502a", label: "Lava / fire", glow: true }, ice: { fill: "#cfe6ef", label: "Ice", shine: true },
    rubble: { fill: "#8a7f70", label: "Rubble / crates", rubble: true }, tree: { fill: "#6f8f4e", label: "Tree", tree: true },
    table: { fill: "#7a5a3a", label: "Table / furniture", table: true },
    rock: { fill: "#5d5449", label: "Raised rock (blocks)", rock: true },
  };
  const KIND_COLOR = { pc: "#c7a25e", npc: "#6f8fae", enemy: "#b2402e", trap: "#7d4f8f", marker: "#8b8273", object: "#7a5a3a" };
  const COND_COLOR = { Blinded: "#555", Charmed: "#d36fb0", Deafened: "#777", Frightened: "#9b6fd3", Grappled: "#b08a3e", Incapacitated: "#8a8a8a",
    Invisible: "#9fd3e6", Paralyzed: "#e0c040", Petrified: "#9a9184", Poisoned: "#6fae4e", Prone: "#c78a4e", Restrained: "#b0603e",
    Stunned: "#f0d060", Unconscious: "#444" };
  const CONE_HALF = Math.atan(0.5); // a 5e cone is as wide as it is long

  function initials(s) { return (s || "?").split(/\s+/).filter(Boolean).map((w) => w[0]).join("").slice(0, 2).toUpperCase(); }
  function hash(x, y) { let h = (x * 374761393 + y * 668265263) ^ 0x5bd1e995; h = (h ^ (h >>> 13)) * 1274126177; return ((h ^ (h >>> 16)) >>> 0) / 4294967295; }
  function rgba(hex, a) {
    const n = parseInt((hex || "#e0714f").slice(1), 16);
    return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
  }

  // ---- spell area geometry (in squares; the map's scale turns feet into squares) ----------
  function shapeCells(s, m) {
    const per = m.scale_value || 5, L = s.size / per, out = [];
    const rad = (s.dir || 0) * Math.PI / 180, ux = Math.cos(rad), uy = Math.sin(rad), half = (s.width || per) / per / 2;
    const reach = Math.ceil(L + 2);
    const x0 = Math.max(0, Math.floor(s.x - reach)), x1 = Math.min(m.cols - 1, Math.ceil(s.x + reach));
    const y0 = Math.max(0, Math.floor(s.y - reach)), y1 = Math.min(m.rows - 1, Math.ceil(s.y + reach));
    for (let y = y0; y <= y1; y++) for (let x = x0; x <= x1; x++) {
      const dx = x + 0.5 - s.x, dy = y + 0.5 - s.y, d = Math.hypot(dx, dy);
      let inside = false;
      if (s.kind === "circle") inside = d <= L + 1e-6;
      else if (s.kind === "square") inside = Math.abs(dx) <= L / 2 + 1e-6 && Math.abs(dy) <= L / 2 + 1e-6;
      else if (s.kind === "cone") {
        const along = dx * ux + dy * uy;
        inside = d > 0.01 && along > 0 && along <= L + 1e-6 && Math.abs(Math.atan2(-dx * uy + dy * ux, along)) <= CONE_HALF + 0.02;
      } else if (s.kind === "line") {
        const along = dx * ux + dy * uy, across = Math.abs(-dx * uy + dy * ux);
        inside = along >= 0 && along <= L + 1e-6 && across <= half + 1e-6;
      }
      if (inside) out.push([x, y]);
    }
    return out;
  }
  function tokensInShape(s, m, tokens) {
    const cells = new Set(shapeCells(s, m).map(([x, y]) => x + "," + y));
    return tokens.filter((t) => {
      const x0 = Math.round(t.x), y0 = Math.round(t.y);
      for (let dx = 0; dx < t.size; dx++) for (let dy = 0; dy < t.size; dy++) if (cells.has((x0 + dx) + "," + (y0 + dy))) return true;
      return false;
    });
  }
  /** Where a new area's origin lands: circles on grid corners, odd-sized squares on square centres. */
  function snapOrigin(kind, cx, cy, size, per) {
    if (kind === "circle") return [Math.round(cx), Math.round(cy)];
    if (kind === "square") {
      const n = Math.round(size / per);
      return n % 2 ? [Math.floor(cx) + 0.5, Math.floor(cy) + 0.5] : [Math.round(cx), Math.round(cy)];
    }
    return [Math.round(cx * 2) / 2, Math.round(cy * 2) / 2];
  }

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
      this.selectedId = null; this.selectedShape = null; this.fitted = false;
      this.fx = []; this.seenPings = new Set(); this.lastHp = null; this.lastCurrent = null; this.raf = 0;
      this.areaSpec = { kind: "circle", size: 20, width: 5, color: "#e0714f", label: "", hidden: false };
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
      this.noticeChanges(first);
      const url = this.opts.imageUrl ? this.opts.imageUrl(map) : null;
      if (url && (!this.bg || this.bg.src.indexOf(url) < 0)) {
        const img = new Image();
        img.onload = () => { this.bg = img; this.draw(); };
        img.src = url;
      } else if (!url) this.bg = null;
      if (first || !this.fitted) this.fit();
      this.draw();
    }
    /** Floating numbers when HP changes, and a pulse when the turn moves on. */
    noticeChanges(first) {
      const hp = new Map(this.tokens.filter((t) => t.hp != null).map((t) => [t.id, t.hp]));
      const cur = (this.tokens.find((t) => t.is_current) || {}).id || null;
      if (!first && this.lastHp) {
        for (const t of this.tokens) {
          const was = this.lastHp.get(t.id);
          if (was == null || t.hp == null || was === t.hp) continue;
          const diff = t.hp - was;
          this.addFx({ type: "float", token: t.id, text: (diff > 0 ? "+" : "−") + Math.abs(diff), color: diff > 0 ? "#9fdc7a" : "#ff7a5c", ms: 1600 });
          if (t.hp === 0 && was > 0) this.addFx({ type: "float", token: t.id, text: "Down!", color: "#f3ead6", ms: 2000, delay: 300 });
        }
        if (cur && cur !== this.lastCurrent) this.addFx({ type: "pulse", token: cur, ms: 2400 });
      }
      this.lastHp = hp; this.lastCurrent = cur;
    }
    /** New pings from the server (or this device) become ripples. */
    setPings(pings, onNew) {
      for (const p of pings || []) {
        if (this.seenPings.has(p.id)) continue;
        this.seenPings.add(p.id);
        if (p.fx) { if (p.age < 4) this.attackFx(p.fx, p.age); continue; }
        if (p.age > 4) continue;
        this.addFx({ type: "ping", x: p.x, y: p.y, by: p.by, color: p.color || "#f3d58a", ms: 3600, start: performance.now() - p.age * 1000 });
        if (onNew) onNew(p);
      }
    }
    /* An attack's look comes from its name and damage type: a slash for blades, an impact for
       fists and maces, jaws for a bite, an arrow for bows, a bolt that bursts for fire, ice,
       lightning, poison and magic, spirits for radiant, rock for earth, sparkles for heals. */
    static fxStyle(name, kind, type) {
      const t = (String(name || "") + " " + String(type || "")).toLowerCase();
      if (kind === "heal") return "heal";
      if (kind === "buff") return "shimmer";
      if (/bite|fang|jaw|chomp|maw/.test(t)) return "bite";
      if (/\b(bow|arrow|crossbow|dart|sling|javelin|shot|shoot)/.test(t)) return "arrow";
      if (/fire|flame|burn|scorch|inferno|ember/.test(t)) return "fire";
      if (/cold|ice|frost|snow|freez/.test(t)) return "ice";
      if (/lightning|thunder|shock|storm|spark/.test(t)) return "lightning";
      if (/radiant|holy|sacred|spirit|divine|smite|guardian|light/.test(t)) return "radiant";
      if (/necrotic|poison|acid|venom|toxic|rot/.test(t)) return "poison";
      if (/entangle|vine|root|earth|rock|stone|mend|mold/.test(t)) return "earth";
      if (/slash|sword|axe|blade|claw|scimitar|dagger|knife|cut|cleave|scythe|sickle|rapier|glaive/.test(t)) return "slash";
      if (/punch|fist|kick|slam|club|mace|hammer|staff|bludgeon|headbutt|grapple|shove|smash|pierc|spear|stab/.test(t)) return "punch";
      if (/psychic|force|magic|phantas|arcane|eldritch|missile|hex/.test(t)) return "arcane";
      return kind === "damage" && /piercing|slashing|bludgeoning/.test(t) ? "punch" : kind === "damage" ? "slash" : "arcane";
    }
    attackFx(fx, age) {
      const style = MapView.fxStyle(fx.name, fx.kind, fx.type), start = performance.now() - (age || 0) * 1000;
      const COLORS = { fire: "#ff7a2f", ice: "#8fdcff", lightning: "#fff27a", radiant: "#ffe9a3", poison: "#8fe36b", arcane: "#c08bff",
        arrow: "#e8d9b5", slash: "#ffffff", punch: "#ffd28a", bite: "#ffffff", earth: "#b98a55", heal: "#9fdc7a", shimmer: "#f3d58a" };
      const color = COLORS[style] || "#ffffff", hows = fx.how || [];
      const sweep = style === "slash" && fx.area && fx.area.kind === "cone" && fx.from && fx.to && fx.to.length;
      if (sweep) { // Wide Slash: one wide slash the full length of the cone, pointed at the ones it reaches
        const cx = fx.to.reduce((s, p) => s + p[0], 0) / fx.to.length, cy = fx.to.reduce((s, p) => s + p[1], 0) / fx.to.length;
        const crit = hows.includes("crit");
        this.addFx({ type: "attack", style: "cone", color, from: fx.from, dir: Math.atan2(cy - fx.from[1], cx - fx.from[0]),
          len: Math.max(1.5, fx.area.squares || 3), how: crit ? "crit" : hows.every((h) => h === "miss") ? "miss" : "hit", ms: 1100, start });
      }
      (fx.to && fx.to.length ? fx.to : [fx.from]).forEach((to, i) => {
        const how = hows[i] || "hit", missed = how === "miss" || how === "saved";
        if (!sweep) this.addFx({ type: "attack", style, color, from: fx.from, to, how, ms: 1300, start: start + i * 120 });
        const word = how === "crit" ? "CRIT!" : how === "miss" ? "Miss" : how === "saved" ? "Saved" : "";
        if (word && to) this.addFx({ type: "word", x: to[0], y: to[1], text: word, color: how === "crit" ? "#ffd36b" : "#d8d2c4", ms: 1500, start: start + 500 + i * 120 });
        if (i === 0 && window.FX) FX.sound(fx.kind === "heal" || fx.kind === "buff" ? "heal" : how === "crit" ? "crit" : missed ? "fumble" : "hit");
      });
    }
    addFx(f) {
      f.start = f.start || performance.now() + (f.delay || 0);
      this.fx.push(f);
      if (!this.raf) this.raf = requestAnimationFrame(() => this.loop());
    }
    loop() {
      const now = performance.now();
      this.fx = this.fx.filter((f) => now - f.start < f.ms);
      this.draw();
      this.raf = this.fx.length || (this.zones && this.zones.length) ? requestAnimationFrame(() => this.loop()) : 0;
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
    shapeAt(px, py) {
      if (!this.opts.canEditShapes) return null;
      const [cx, cy] = this.toCell(px, py), shapes = (this.map && this.map.shapes) || [];
      for (let i = shapes.length - 1; i >= 0; i--) {
        if (Math.hypot(cx - shapes[i].x, cy - shapes[i].y) < 0.6) return shapes[i]; // grab it by its origin dot
        if (shapeCells(shapes[i], this.map).some(([x, y]) => Math.floor(cx) === x && Math.floor(cy) === y)) return shapes[i];
      }
      return null;
    }
    revealed(x, y) { const m = this.map; const i = y * m.cols + x; return m.revealed && m.revealed[i] === "1"; }

    // ---- drawing ----------------------------------------------------------------
    /** Zones that stay up (Spirit Guardians): a square of light shining down around the caster.
        They follow the caster's token, and shimmer while they're up. */
    setZones(zones) {
      this.zones = zones || [];
      if (this.zones.length && !this.raf) this.raf = requestAnimationFrame(() => this.loop());
    }
    drawZones(cp, ox, oy) {
      if (!this.zones || !this.zones.length) return;
      const ctx = this.ctx, now = performance.now() / 1000;
      for (const z of this.zones) {
        const t = this.tokens.find((x) => x.id === z.token);
        if (!t) continue;
        const dragging = this.drag && this.drag.token && this.drag.token.id === t.id && this.drag.moved;
        const tx = dragging ? this.drag.at[0] : t.x, ty = dragging ? this.drag.at[1] : t.y;
        const x0 = ox + (tx - z.half) * cp, y0 = oy + (ty - z.half) * cp, w = (t.size + z.half * 2) * cp;
        ctx.save();
        const glow = ctx.createRadialGradient(x0 + w / 2, y0 + w / 2, w * 0.1, x0 + w / 2, y0 + w / 2, w * 0.75);
        glow.addColorStop(0, "rgba(255, 236, 150, .55)"); glow.addColorStop(1, "rgba(255, 210, 90, .22)");
        ctx.fillStyle = glow; ctx.fillRect(x0, y0, w, w);
        // shafts of light coming down
        ctx.beginPath(); ctx.rect(x0, y0, w, w); ctx.clip();
        for (let i = 0; i < 7; i++) {
          const sx = x0 + ((i + 0.5) / 7) * w + Math.sin(now * 0.8 + i * 1.7) * cp * 0.25, a = 0.22 + 0.12 * Math.sin(now * 2 + i);
          const g = ctx.createLinearGradient(sx, y0, sx, y0 + w);
          g.addColorStop(0, "rgba(255, 252, 230, " + (a + 0.25) + ")"); g.addColorStop(1, "rgba(255, 236, 160, 0.04)");
          ctx.fillStyle = g; ctx.beginPath();
          ctx.moveTo(sx - cp * 0.15, y0); ctx.lineTo(sx + cp * 0.15, y0); ctx.lineTo(sx + cp * 0.55, y0 + w); ctx.lineTo(sx - cp * 0.55, y0 + w); ctx.closePath(); ctx.fill();
        }
        for (let i = 0; i < 10; i++) { // little motes drifting down
          const px = x0 + ((i * 0.37 + 0.1) % 1) * w, py = y0 + ((now * 0.15 + i * 0.23) % 1) * w;
          ctx.fillStyle = "rgba(255, 255, 240, .95)"; ctx.shadowColor = "#fff6c8"; ctx.shadowBlur = cp * 0.3; ctx.beginPath(); ctx.arc(px, py, cp * 0.07, 0, Math.PI * 2); ctx.fill();
        }
        ctx.restore();
        ctx.save();
        ctx.strokeStyle = "rgba(230, 180, 40, .95)"; ctx.lineWidth = cp * 0.09; ctx.shadowColor = "#ffd75a"; ctx.shadowBlur = cp * 0.6;
        ctx.strokeRect(x0, y0, w, w);
        ctx.font = `700 ${cp * 0.3}px 'Alegreya Sans', sans-serif`; ctx.textAlign = "left"; ctx.textBaseline = "top";
        ctx.fillStyle = "rgba(60, 45, 10, .85)"; const label = z.name; const lw = ctx.measureText(label).width + cp * 0.2;
        ctx.fillRect(x0 + cp * 0.1, y0 + cp * 0.1, lw, cp * 0.38); ctx.fillStyle = "#ffe9a3"; ctx.fillText(label, x0 + cp * 0.2, y0 + cp * 0.14);
        ctx.restore();
      }
    }
    /** While a token is dragged in a fight: the squares it can still reach (its movement left). */
    // reach(t) -> { budget: ft this turn, from: [x, y] where they started it (null: where they stand) }
    reachOf(t) {
      const r = this.opts.reach ? this.opts.reach(t) : null;
      if (r == null || !this.map) return null;
      const per = this.map.scale_unit === "ft" || !this.map.scale_unit ? (Number(this.map.scale_value) || 5) : 5;
      const from = r.from || [t.x, t.y];
      return { ft: r.budget, per, squares: Math.floor(r.budget / per), ox: from[0], oy: from[1] };
    }
    drawReach(t, cp, ox, oy) {
      const r = this.reachOf(t);
      if (!r) return;
      const m = this.map, ctx = this.ctx;
      const x0 = Math.max(0, r.ox - r.squares), y0 = Math.max(0, r.oy - r.squares);
      const x1 = Math.min(m.cols, r.ox + t.size + r.squares), y1 = Math.min(m.rows, r.oy + t.size + r.squares);
      ctx.save();
      ctx.fillStyle = "rgba(120, 200, 140, .16)"; ctx.strokeStyle = "rgba(120, 220, 150, .9)"; ctx.lineWidth = cp * 0.06;
      ctx.setLineDash([cp * 0.2, cp * 0.12]);
      ctx.fillRect(ox + x0 * cp, oy + y0 * cp, (x1 - x0) * cp, (y1 - y0) * cp);
      ctx.strokeRect(ox + x0 * cp, oy + y0 * cp, (x1 - x0) * cp, (y1 - y0) * cp);
      ctx.restore();
    }
    drawStepLabel(t, cp, ox, oy) {
      const r = this.reachOf(t);
      if (!r) return;
      const [ax, ay] = this.drag.at, sq = Math.ceil(Math.max(Math.abs(ax - r.ox), Math.abs(ay - r.oy)) - 1e-6), ft = sq * r.per;
      const too = ft > r.ft, ctx = this.ctx, X = ox + (ax + t.size / 2) * cp, Y = oy + ay * cp - cp * 0.25;
      const text = ft + " / " + r.ft + " ft" + (too ? " — too far" : "");
      ctx.save();
      ctx.font = "700 " + Math.round(cp * 0.36) + "px sans-serif"; ctx.textAlign = "center"; ctx.textBaseline = "bottom";
      const w = ctx.measureText(text).width + cp * 0.3;
      ctx.fillStyle = too ? "rgba(170, 40, 30, .92)" : "rgba(20, 60, 30, .9)";
      ctx.fillRect(X - w / 2, Y - cp * 0.5, w, cp * 0.5);
      ctx.fillStyle = "#fff"; ctx.fillText(text, X, Y - cp * 0.06);
      ctx.restore();
    }
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
      for (const [key, kind] of Object.entries(m.terrain || {})) {
        const [x, y] = key.split(",").map(Number);
        this.drawTerrain(kind, x, y, cp, ox, oy);
      }
      if (m.show_grid) {
        ctx.strokeStyle = m.grid_color || "#000"; ctx.globalAlpha = (m.grid_opacity ?? 35) / 100;
        ctx.lineWidth = Math.max(1 / s, cp * 0.02);
        ctx.beginPath();
        for (let x = 0; x <= m.cols; x++) { ctx.moveTo(ox + x * cp, oy); ctx.lineTo(ox + x * cp, oy + gh); }
        for (let y = 0; y <= m.rows; y++) { ctx.moveTo(ox, oy + y * cp); ctx.lineTo(ox + gw, oy + y * cp); }
        ctx.stroke(); ctx.globalAlpha = 1;
      }
      const shapes = (m.shapes || []).map((sh) => (this.drag && this.drag.shape && this.drag.shape.id === sh.id ? Object.assign({}, sh, { x: this.drag.at[0], y: this.drag.at[1] }) : sh));
      for (const sh of shapes) this.drawShape(sh, cp, ox, oy, false);
      if (this.areaDraft) this.drawShape(this.areaDraft, cp, ox, oy, true);
      if (this.aim) this.drawAim(cp, ox, oy);
      this.drawZones(cp, ox, oy);
      if (this.drag && this.drag.token && this.drag.moved) this.drawReach(this.drag.token, cp, ox, oy);
      for (const t of this.tokens) this.drawToken(t, cp, ox, oy);
      if (this.drag && this.drag.token && this.drag.moved) this.drawStepLabel(this.drag.token, cp, ox, oy);
      if (this.aim && this.aim.hits) for (const t of this.tokens) if (this.aim.hits.has(t.id)) {
        const r = t.size * cp * 0.5, X = ox + (t.x + t.size / 2) * cp, Y = oy + (t.y + t.size / 2) * cp;
        ctx.save(); ctx.strokeStyle = "#ffd36b"; ctx.lineWidth = cp * 0.1; ctx.shadowColor = "#ffb347"; ctx.shadowBlur = cp * 0.4;
        ctx.beginPath(); ctx.arc(X, Y, r, 0, Math.PI * 2); ctx.stroke(); ctx.restore();
      }
      if (m.fog_enabled) {
        const dm = this.opts.role === "dm";
        ctx.fillStyle = dm ? "rgba(10,8,6,.55)" : "#080706";
        for (let y = 0; y < m.rows; y++) for (let x = 0; x < m.cols; x++) {
          if (!this.revealed(x, y)) ctx.fillRect(ox + x * cp - 0.5, oy + y * cp - 0.5, cp + 1, cp + 1);
        }
      }
      if (this.preview.size) {
        ctx.fillStyle = this.tool === "conceal" ? "rgba(10,8,6,.5)" : this.tool === "reveal" ? "rgba(255,240,200,.35)" : "rgba(199,162,94,.45)";
        for (const k of this.preview) { const [x, y] = k.split(",").map(Number); ctx.fillRect(ox + x * cp, oy + y * cp, cp, cp); }
      }
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
        ctx.fillStyle = "#fff"; ctx.textBaseline = "middle"; ctx.textAlign = "left"; ctx.fillText(label, x2 + cp * 0.45, y2 - cp * 0.3);
      }
      this.drawFx(cp, ox, oy);
    }
    drawTerrain(kind, x, y, cp, ox, oy) {
      const T = TERRAIN[kind], ctx = this.ctx;
      if (!T) return;
      const X = ox + x * cp, Y = oy + y * cp;
      ctx.globalAlpha = this.bg ? 0.7 : 1;
      ctx.fillStyle = T.fill; ctx.fillRect(X, Y, cp, cp);
      ctx.save(); ctx.beginPath(); ctx.rect(X, Y, cp, cp); ctx.clip();
      if (T.hatch) {
        ctx.strokeStyle = "rgba(0,0,0,.25)"; ctx.lineWidth = cp * 0.04;
        ctx.beginPath(); for (let k = -1; k <= 1; k += 0.5) { ctx.moveTo(X + k * cp, Y + cp); ctx.lineTo(X + (k + 1) * cp, Y); }
        ctx.stroke();
      }
      if (T.speckle) {
        ctx.fillStyle = T.speckle;
        for (let i = 0; i < 5; i++) ctx.fillRect(X + hash(x * 7 + i, y) * cp, Y + hash(x, y * 7 + i) * cp, cp * 0.06, cp * 0.06);
      }
      if (T.tiles) {
        ctx.strokeStyle = "rgba(0,0,0,.18)"; ctx.lineWidth = cp * 0.03;
        ctx.strokeRect(X + cp * 0.04, Y + cp * 0.04, cp * 0.92, cp * 0.92);
      }
      if (T.planks) {
        ctx.strokeStyle = "rgba(40,20,5,.35)"; ctx.lineWidth = cp * 0.03;
        ctx.beginPath(); for (let k = 1; k < 3; k++) { ctx.moveTo(X, Y + k * cp / 3); ctx.lineTo(X + cp, Y + k * cp / 3); }
        const off = hash(x, y) > 0.5 ? 0.3 : 0.7; ctx.moveTo(X + off * cp, Y); ctx.lineTo(X + off * cp, Y + cp / 3); ctx.stroke();
      }
      if (T.ripple) {
        ctx.strokeStyle = "rgba(255,255,255,.25)"; ctx.lineWidth = cp * 0.03;
        ctx.beginPath(); const yy = Y + cp * (0.3 + hash(x, y) * 0.4);
        ctx.moveTo(X + cp * 0.15, yy); ctx.quadraticCurveTo(X + cp * 0.35, yy - cp * 0.08, X + cp * 0.55, yy); ctx.quadraticCurveTo(X + cp * 0.75, yy + cp * 0.08, X + cp * 0.9, yy);
        ctx.stroke();
      }
      if (T.glow) {
        const g = ctx.createRadialGradient(X + cp / 2, Y + cp / 2, cp * 0.05, X + cp / 2, Y + cp / 2, cp * 0.7);
        g.addColorStop(0, "rgba(255,220,120,.85)"); g.addColorStop(1, "rgba(208,80,42,0)");
        ctx.fillStyle = g; ctx.fillRect(X, Y, cp, cp);
      }
      if (T.shine) {
        ctx.strokeStyle = "rgba(255,255,255,.7)"; ctx.lineWidth = cp * 0.04;
        ctx.beginPath(); ctx.moveTo(X + cp * 0.2, Y + cp * 0.7); ctx.lineTo(X + cp * 0.45, Y + cp * 0.3); ctx.stroke();
      }
      if (T.rubble) {
        ctx.fillStyle = "rgba(60,50,40,.55)";
        for (let i = 0; i < 4; i++) { ctx.beginPath(); ctx.arc(X + (0.2 + hash(i, x) * 0.6) * cp, Y + (0.2 + hash(y, i) * 0.6) * cp, cp * (0.08 + hash(x + i, y) * 0.08), 0, Math.PI * 2); ctx.fill(); }
      }
      if (T.rock) { // a jagged boulder, so raised rock reads as solid, not as floor
        ctx.fillStyle = "#3c352d";
        ctx.beginPath(); ctx.moveTo(X + cp * 0.12, Y + cp * 0.85); ctx.lineTo(X + cp * 0.3, Y + cp * 0.25); ctx.lineTo(X + cp * 0.55, Y + cp * 0.12);
        ctx.lineTo(X + cp * 0.85, Y + cp * 0.4); ctx.lineTo(X + cp * 0.88, Y + cp * 0.85); ctx.closePath(); ctx.fill();
        ctx.strokeStyle = "rgba(255,255,255,.18)"; ctx.lineWidth = cp * 0.04;
        ctx.beginPath(); ctx.moveTo(X + cp * 0.32, Y + cp * 0.3); ctx.lineTo(X + cp * 0.55, Y + cp * 0.18); ctx.lineTo(X + cp * 0.78, Y + cp * 0.42); ctx.stroke();
      }
      if (T.pit) {
        ctx.strokeStyle = "rgba(255,255,255,.12)"; ctx.lineWidth = cp * 0.04;
        ctx.strokeRect(X + cp * 0.12, Y + cp * 0.12, cp * 0.76, cp * 0.76);
      }
      if (T.door) {
        ctx.fillStyle = "rgba(255,230,180,.5)"; ctx.beginPath(); ctx.arc(X + cp * 0.75, Y + cp * 0.5, cp * 0.06, 0, Math.PI * 2); ctx.fill();
      }
      ctx.restore();
      if (T.tree) {
        ctx.fillStyle = "#3f5f2e"; ctx.beginPath(); ctx.arc(X + cp / 2, Y + cp / 2, cp * 0.62, 0, Math.PI * 2); ctx.fill();
        ctx.fillStyle = "#56783d"; ctx.beginPath(); ctx.arc(X + cp * 0.42, Y + cp * 0.42, cp * 0.32, 0, Math.PI * 2); ctx.fill();
      }
      if (T.table) {
        ctx.strokeStyle = "#3e2a16"; ctx.lineWidth = cp * 0.06;
        ctx.strokeRect(X + cp * 0.08, Y + cp * 0.08, cp * 0.84, cp * 0.84);
      }
      ctx.globalAlpha = 1;
    }
    // An area attack being aimed: the dotted range ring around the attacker, then the area itself.
    drawAim(cp, ox, oy) {
      const a = this.aim, ctx = this.ctx, per = this.map.scale_value || 5;
      if (a.range > 0 && a.shape.kind !== "cone" && a.shape.kind !== "line") {
        ctx.save();
        ctx.strokeStyle = "rgba(255,211,107,.85)"; ctx.fillStyle = "rgba(255,211,107,.07)"; ctx.lineWidth = cp * 0.05; ctx.setLineDash([cp * 0.2, cp * 0.14]);
        ctx.beginPath(); ctx.arc(ox + a.from[0] * cp, oy + a.from[1] * cp, (a.range / per + a.fromR) * cp, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
        ctx.restore();
      }
      this.drawShape(Object.assign({ color: "#ffb347" }, a.shape), cp, ox, oy, true);
    }
    // Cones and lines come out of the caster: the start stays on the edge of their token and
    // only the direction follows the pointer.
    pointAim(cx, cy) {
      const a = this.aim, s = a.shape, dx = cx - a.from[0], dy = cy - a.from[1];
      if (Math.hypot(dx, dy) < 0.3) return;
      const deg = Math.round(Math.atan2(dy, dx) * 180 / Math.PI / 5) * 5, rad = deg * Math.PI / 180;
      s.dir = deg;
      s.x = a.from[0] + Math.cos(rad) * a.fromR;
      s.y = a.from[1] + Math.sin(rad) * a.fromR;
    }
    // keep the area's origin within range of the attacker (measured from the edge of their token)
    clampAim(x, y) {
      const a = this.aim, per = this.map.scale_value || 5, max = a.range / per + a.fromR;
      const dx = x - a.from[0], dy = y - a.from[1], d = Math.hypot(dx, dy);
      if (d <= max || d === 0) return [x, y];
      return [a.from[0] + dx / d * max, a.from[1] + dy / d * max];
    }
    drawShape(sh, cp, ox, oy, draft) {
      const ctx = this.ctx, m = this.map, per = m.scale_value || 5, L = sh.size / per;
      const col = sh.color || "#e0714f", sel = !draft && this.selectedShape === sh.id;
      ctx.save();
      ctx.fillStyle = rgba(col, draft ? 0.3 : 0.26);
      for (const [x, y] of shapeCells(sh, m)) ctx.fillRect(ox + x * cp, oy + y * cp, cp, cp);
      const X = ox + sh.x * cp, Y = oy + sh.y * cp, rad = (sh.dir || 0) * Math.PI / 180;
      ctx.strokeStyle = rgba(col, 0.95); ctx.lineWidth = cp * (sel ? 0.09 : 0.06);
      if (sh.hidden || draft) ctx.setLineDash([cp * 0.18, cp * 0.12]);
      ctx.beginPath();
      if (sh.kind === "circle") ctx.arc(X, Y, L * cp, 0, Math.PI * 2);
      else if (sh.kind === "square") ctx.rect(X - L * cp / 2, Y - L * cp / 2, L * cp, L * cp);
      else {
        ctx.translate(X, Y); ctx.rotate(rad);
        if (sh.kind === "cone") { ctx.moveTo(0, 0); ctx.lineTo(L * cp, -L * cp / 2); ctx.lineTo(L * cp, L * cp / 2); ctx.closePath(); }
        else { const hw = (sh.width || per) / per * cp / 2; ctx.rect(0, -hw, L * cp, hw * 2); }
      }
      ctx.stroke();
      ctx.restore();
      ctx.save();
      ctx.fillStyle = rgba(col, 1); ctx.beginPath(); ctx.arc(X, Y, cp * 0.12, 0, Math.PI * 2); ctx.fill();
      const label = (sh.label ? sh.label + " · " : "") + sh.size + " ft" + (sh.kind === "line" ? " line" : sh.kind === "cone" ? " cone" : sh.kind === "square" ? " cube" : "");
      ctx.font = `700 ${cp * 0.3}px 'Alegreya Sans', sans-serif`; ctx.textAlign = "center"; ctx.textBaseline = "bottom";
      const lw = ctx.measureText(label).width + cp * 0.2;
      ctx.fillStyle = "rgba(20,16,12,.8)"; ctx.fillRect(X - lw / 2, Y - cp * 0.55, lw, cp * 0.38);
      ctx.fillStyle = "#fff"; ctx.fillText(label, X, Y - cp * 0.2);
      ctx.restore();
    }
    drawToken(t, cp, ox, oy) {
      const ctx = this.ctx;
      const dragging = this.drag && this.drag.token && this.drag.token.id === t.id && this.drag.moved;
      const x = dragging ? this.drag.at[0] : t.x, y = dragging ? this.drag.at[1] : t.y;
      const cx = ox + (x + t.size / 2) * cp, cy = oy + (y + t.size / 2) * cp, r = t.size * cp * 0.42;
      const color = t.color || KIND_COLOR[t.kind] || "#888";
      ctx.save();
      if (t.hidden || t.combatant_hidden) ctx.globalAlpha = 0.55;
      ctx.shadowColor = "rgba(0,0,0,.45)"; ctx.shadowBlur = cp * 0.12; ctx.shadowOffsetY = cp * 0.04;
      if (t.is_current) { ctx.beginPath(); ctx.arc(cx, cy, r + cp * 0.12, 0, Math.PI * 2); ctx.fillStyle = "#e0714f"; ctx.fill(); }
      ctx.beginPath(); ctx.arc(cx, cy, r, 0, Math.PI * 2);
      ctx.fillStyle = color; ctx.fill();
      ctx.shadowColor = "transparent";
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
      // conditions: little coloured badges round the top of the token
      const conds = (t.conditions || []).map((c) => String(c).replace(/\s+[+−-]\d+\s*AC$/, ""));
      conds.slice(0, 4).forEach((c, i) => {
        const a = -Math.PI / 2 + (i - (Math.min(conds.length, 4) - 1) / 2) * 0.55, bx = cx + Math.cos(a) * r, by = cy + Math.sin(a) * r, br = cp * 0.13;
        ctx.fillStyle = COND_COLOR[c] || "#c7a25e"; ctx.strokeStyle = "rgba(0,0,0,.7)"; ctx.lineWidth = cp * 0.025;
        ctx.beginPath(); ctx.arc(bx, by, br, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
        ctx.fillStyle = "#fff"; ctx.font = `700 ${br * 1.3}px 'Alegreya Sans', sans-serif`; ctx.textAlign = "center"; ctx.textBaseline = "middle";
        ctx.fillText(i === 3 && conds.length > 4 ? "+" : c[0].toUpperCase(), bx, by + br * 0.05);
      });
      if (this.opts.showLabels !== false && this.view.s * cp > 34) {
        ctx.font = `600 ${cp * 0.26}px 'Alegreya Sans', sans-serif`; ctx.textAlign = "center"; ctx.textBaseline = "top";
        // Whole name, wrapped by word onto as many lines as it needs (about two squares wide).
        const maxW = cp * 2.2 * Math.max(1, t.size || 1), lines = [];
        for (const word of String(t.display).split(/\s+/)) {
          const tryLine = lines.length ? lines[lines.length - 1] + " " + word : word;
          if (lines.length && ctx.measureText(tryLine).width <= maxW) lines[lines.length - 1] = tryLine; else lines.push(word);
        }
        const lh = cp * 0.3, ly = cy + r + cp * 0.18;
        lines.forEach((line, n) => {
          const lw = ctx.measureText(line).width + cp * 0.16;
          ctx.fillStyle = "rgba(20,16,12,.75)"; ctx.fillRect(cx - lw / 2, ly + n * lh, lw, lh + cp * 0.02);
          ctx.fillStyle = "#f3ead6"; ctx.fillText(line, cx, ly + n * lh + cp * 0.03);
        });
      }
      ctx.restore();
    }
    drawFx(cp, ox, oy) {
      if (!this.fx.length) return;
      const ctx = this.ctx, now = performance.now();
      for (const f of this.fx) {
        const k = (now - f.start) / f.ms;
        if (k < 0 || k > 1) continue;
        const tok = f.token ? this.tokens.find((t) => t.id === f.token) : null;
        if (f.token && !tok) continue;
        ctx.save();
        if (f.type === "ping") {
          const X = ox + f.x * cp, Y = oy + f.y * cp;
          for (let i = 0; i < 3; i++) {
            const kk = (k * 3 - i * 0.35) % 1;
            if (k * 3 - i * 0.35 < 0 || k > 0.92) continue;
            ctx.strokeStyle = rgba(f.color, 1 - kk); ctx.lineWidth = cp * 0.08;
            ctx.beginPath(); ctx.arc(X, Y, cp * (0.2 + kk * 1.6), 0, Math.PI * 2); ctx.stroke();
          }
          ctx.fillStyle = rgba(f.color, 1 - k * 0.6); ctx.beginPath(); ctx.arc(X, Y, cp * 0.16, 0, Math.PI * 2); ctx.fill();
          if (f.by) {
            ctx.font = `700 ${cp * 0.32}px 'Alegreya Sans', sans-serif`; ctx.textAlign = "center"; ctx.textBaseline = "bottom";
            const lw = ctx.measureText(f.by).width + cp * 0.2;
            ctx.globalAlpha = Math.min(1, (1 - k) * 2);
            ctx.fillStyle = "rgba(20,16,12,.85)"; ctx.fillRect(X - lw / 2, Y - cp * 0.95, lw, cp * 0.4);
            ctx.fillStyle = "#fff"; ctx.fillText(f.by, X, Y - cp * 0.58);
          }
        } else if (f.type === "float" && tok) {
          const X = ox + (tok.x + tok.size / 2) * cp, Y = oy + tok.y * cp - k * cp * 1.1;
          ctx.globalAlpha = k < 0.75 ? 1 : (1 - k) * 4;
          ctx.font = `800 ${cp * (0.5 + 0.15 * Math.sin(Math.min(1, k * 4) * Math.PI))}px 'Alegreya Sans', sans-serif`;
          ctx.textAlign = "center"; ctx.textBaseline = "middle";
          ctx.lineWidth = cp * 0.1; ctx.strokeStyle = "rgba(0,0,0,.8)"; ctx.strokeText(f.text, X, Y);
          ctx.fillStyle = f.color; ctx.fillText(f.text, X, Y);
        } else if (f.type === "attack") {
          this.drawAttack(f, k, cp, ox, oy);
        } else if (f.type === "word") {
          const X = ox + f.x * cp, Y = oy + f.y * cp - cp * 0.6 - k * cp * 0.7;
          ctx.globalAlpha = k < 0.7 ? 1 : (1 - k) / 0.3;
          ctx.font = `800 ${cp * (f.text === "CRIT!" ? 0.62 : 0.46)}px 'Alegreya Sans', sans-serif`; ctx.textAlign = "center"; ctx.textBaseline = "middle";
          ctx.lineWidth = cp * 0.1; ctx.strokeStyle = "rgba(0,0,0,.85)"; ctx.strokeText(f.text, X, Y);
          ctx.fillStyle = f.color; ctx.fillText(f.text, X, Y);
        } else if (f.type === "pulse" && tok) {
          const X = ox + (tok.x + tok.size / 2) * cp, Y = oy + (tok.y + tok.size / 2) * cp, r = tok.size * cp * 0.42;
          const kk = (k * 2.4) % 1;
          ctx.strokeStyle = rgba("#f3d58a", 1 - kk); ctx.lineWidth = cp * 0.1;
          ctx.beginPath(); ctx.arc(X, Y, r + cp * (0.1 + kk * 0.9), 0, Math.PI * 2); ctx.stroke();
        }
        ctx.restore();
      }
    }
    /** One attack's animation, k from 0 to 1. Projectiles fly from the attacker first. */
    drawAttack(f, k, cp, ox, oy) {
      const ctx = this.ctx, big = f.how === "crit" ? 1.5 : 1, miss = f.how === "miss" || f.how === "saved";
      const P = (pt) => [ox + pt[0] * cp, oy + pt[1] * cp];
      const [tx, ty] = f.to ? P(f.to) : P(f.from);
      const fly = ["arrow", "fire", "ice", "lightning", "poison", "arcane"].includes(f.style) && f.from && f.to;
      const travel = fly ? 0.38 : 0;
      if (fly && k < travel) { // the shot on its way
        const [fx, fy] = P(f.from), q = k / travel, ex = miss ? tx + cp * 0.9 : tx, ey = miss ? ty - cp * 0.7 : ty;
        const hx = fx + (ex - fx) * q, hy = fy + (ey - fy) * q;
        if (f.style === "lightning") {
          ctx.strokeStyle = rgba(f.color, 0.95); ctx.lineWidth = cp * 0.09; ctx.shadowColor = f.color; ctx.shadowBlur = cp * 0.5;
          ctx.beginPath(); ctx.moveTo(fx, fy);
          for (let i = 1; i <= 7; i++) { const s = i / 7 * q; ctx.lineTo(fx + (ex - fx) * s + (Math.random() - 0.5) * cp * 0.5, fy + (ey - fy) * s + (Math.random() - 0.5) * cp * 0.5); }
          ctx.stroke(); return;
        }
        const g = ctx.createLinearGradient(fx, fy, hx, hy);
        g.addColorStop(0, rgba(f.color, 0)); g.addColorStop(1, rgba(f.color, 0.95));
        ctx.strokeStyle = g; ctx.lineWidth = cp * (f.style === "arrow" ? 0.07 : 0.18); ctx.lineCap = "round";
        ctx.beginPath(); ctx.moveTo(hx - (hx - fx) * 0.5, hy - (hy - fy) * 0.5); ctx.lineTo(hx, hy); ctx.stroke();
        ctx.fillStyle = f.color; ctx.shadowColor = f.color; ctx.shadowBlur = cp * 0.6;
        ctx.beginPath(); ctx.arc(hx, hy, cp * (f.style === "arrow" ? 0.08 : 0.2), 0, Math.PI * 2); ctx.fill();
        return;
      }
      const q = fly ? (k - travel) / (1 - travel) : k, fade = q < 0.6 ? 1 : (1 - q) / 0.4;
      ctx.globalAlpha = Math.max(0, fade) * (miss ? 0.55 : 1);
      const R = cp * 0.9 * big;
      if (f.style === "cone") { // the long sweep: a wide crescent across the cone's full length
        const [fx0, fy0] = P(f.from), L = f.len * cp, span = 1.0, sweep = Math.min(1, q / 0.45);
        const a0 = f.dir - span / 2, a1 = a0 + span * sweep;
        ctx.globalAlpha = Math.max(0, fade) * (miss ? 0.5 : 1);
        for (const [r, wdt, col] of [[L * 0.98, cp * 0.34 * big, miss ? "rgba(220,220,220,.7)" : "#ff5a3c"], [L * 0.98, cp * 0.16 * big, "#ffffff"], [L * 0.7, cp * 0.08, "rgba(255,255,255,.75)"], [L * 0.42, cp * 0.05, "rgba(255,255,255,.5)"]]) {
          ctx.strokeStyle = col; ctx.lineWidth = wdt; ctx.lineCap = "round"; ctx.shadowColor = "#ff5a3c"; ctx.shadowBlur = miss ? 0 : cp * 0.5;
          ctx.beginPath(); ctx.arc(fx0, fy0, r, a0, a1); ctx.stroke();
        }
        if (sweep < 1) { // the blade's bright edge at the front of the sweep
          ctx.fillStyle = "#ffffff"; ctx.shadowBlur = cp * 0.8;
          ctx.beginPath(); ctx.arc(fx0 + Math.cos(a1) * L * 0.98, fy0 + Math.sin(a1) * L * 0.98, cp * 0.22 * big, 0, Math.PI * 2); ctx.fill();
        }
      } else if (f.style === "slash") {
        for (let i = 0; i < 3; i++) {
          const s = Math.min(1, Math.max(0, q * 3 - i * 0.35));
          if (!s) continue;
          const a0 = -2.4 + i * 0.25, a1 = a0 + 2.2 * s, off = (i - 1) * cp * 0.16;
          ctx.strokeStyle = miss ? "rgba(220,220,220,.8)" : i === 1 ? "#ff5a3c" : "#ffffff"; ctx.lineWidth = cp * 0.13 * big; ctx.lineCap = "round";
          ctx.shadowColor = "#ff5a3c"; ctx.shadowBlur = miss ? 0 : cp * 0.3;
          ctx.beginPath(); ctx.arc(tx + off, ty - off, R * 1.15, a0, a1); ctx.stroke();
        }
      } else if (f.style === "punch" || f.style === "earth") {
        const n = f.style === "earth" ? 9 : 10, r1 = R * (0.35 + q * 1.1);
        ctx.fillStyle = f.color; ctx.strokeStyle = f.color; ctx.lineWidth = cp * 0.1; ctx.shadowColor = "#ff9a3c"; ctx.shadowBlur = cp * 0.3;
        for (let i = 0; i < n; i++) {
          const a = i / n * Math.PI * 2 + 0.3;
          if (f.style === "earth") { ctx.fillRect(tx + Math.cos(a) * r1 - cp * 0.07, ty + Math.sin(a) * r1 - cp * 0.07, cp * 0.14, cp * 0.14); continue; }
          ctx.beginPath(); ctx.moveTo(tx + Math.cos(a) * r1 * 0.5, ty + Math.sin(a) * r1 * 0.5); ctx.lineTo(tx + Math.cos(a) * r1, ty + Math.sin(a) * r1); ctx.stroke();
        }
        ctx.beginPath(); ctx.arc(tx, ty, R * (0.2 + q * 0.9), 0, Math.PI * 2); ctx.stroke();
      } else if (f.style === "bite") {
        const close = Math.min(1, q * 2.2), gap = R * (1 - close) * 0.9 + cp * 0.04;
        ctx.fillStyle = miss ? "#ddd" : "#fff"; ctx.strokeStyle = "rgba(120,0,0,.8)"; ctx.lineWidth = cp * 0.03;
        for (const dir of [-1, 1]) for (let i = 0; i < 4; i++) {
          const x = tx - R * 0.75 + i * R * 0.5, y = ty + dir * gap;
          ctx.beginPath(); ctx.moveTo(x - R * 0.2, y + dir * R * 0.35); ctx.lineTo(x + R * 0.2, y + dir * R * 0.35); ctx.lineTo(x, y); ctx.closePath(); ctx.fill(); ctx.stroke();
        }
        if (close >= 1 && !miss) { ctx.fillStyle = "rgba(190,20,20,.7)"; ctx.beginPath(); ctx.arc(tx, ty + R * 0.5, cp * 0.08 * (1 + q), 0, Math.PI * 2); ctx.fill(); }
      } else if (f.style === "radiant") {
        for (let i = 0; i < 6; i++) {
          const a = q * 5 + i / 6 * Math.PI * 2, r = R * (0.9 + 0.2 * Math.sin(q * 9 + i));
          ctx.fillStyle = f.color; ctx.shadowColor = "#fff6c8"; ctx.shadowBlur = cp * 0.5;
          ctx.beginPath(); ctx.arc(tx + Math.cos(a) * r, ty + Math.sin(a) * r, cp * 0.15, 0, Math.PI * 2); ctx.fill();
        }
        ctx.strokeStyle = rgba(f.color, 0.8); ctx.lineWidth = cp * 0.05; ctx.beginPath(); ctx.arc(tx, ty, R * (0.5 + q * 0.6), 0, Math.PI * 2); ctx.stroke();
      } else if (f.style === "heal" || f.style === "shimmer") {
        for (let i = 0; i < 7; i++) {
          const x = tx + Math.sin(i * 2.1) * R * 0.8, y = ty + R * 0.6 - q * R * 1.6 - (i % 3) * cp * 0.12, sz = 1.6;
          ctx.fillStyle = f.color; ctx.shadowColor = f.color; ctx.shadowBlur = cp * 0.3;
          if (f.style === "heal") { ctx.fillRect(x - cp * 0.03 * sz, y - cp * 0.1 * sz, cp * 0.06 * sz, cp * 0.2 * sz); ctx.fillRect(x - cp * 0.1 * sz, y - cp * 0.03 * sz, cp * 0.2 * sz, cp * 0.06 * sz); }
          else { ctx.beginPath(); ctx.arc(x, y, cp * 0.08, 0, Math.PI * 2); ctx.fill(); }
        }
        ctx.strokeStyle = rgba(f.color, 0.7); ctx.lineWidth = cp * 0.05; ctx.beginPath(); ctx.arc(tx, ty, R * (0.7 + q * 0.3), 0, Math.PI * 2); ctx.stroke();
      } else { // a burst where the shot lands: fire, ice, lightning, poison, magic, arrow
        const r = R * (0.35 + q * (f.style === "arrow" ? 0.7 : 1.4));
        const g = ctx.createRadialGradient(tx, ty, 0, tx, ty, r);
        g.addColorStop(0, rgba("#ffffff", 0.95)); g.addColorStop(0.3, rgba(f.color, 0.95)); g.addColorStop(0.7, rgba(f.color, 0.55)); g.addColorStop(1, rgba(f.color, 0));
        ctx.fillStyle = g; ctx.beginPath(); ctx.arc(tx, ty, r, 0, Math.PI * 2); ctx.fill();
        if (f.style === "ice" || f.style === "arrow") {
          ctx.strokeStyle = f.color; ctx.lineWidth = cp * 0.05;
          for (let i = 0; i < 6; i++) { const a = i / 6 * Math.PI * 2; ctx.beginPath(); ctx.moveTo(tx, ty); ctx.lineTo(tx + Math.cos(a) * r * 0.9, ty + Math.sin(a) * r * 0.9); ctx.stroke(); }
        }
      }
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
    ping(px, py) {
      const [cx, cy] = this.toCell(px, py);
      if (this.opts.onPing && cx >= 0 && cy >= 0 && cx <= this.map.cols && cy <= this.map.rows) this.opts.onPing(cx, cy);
    }
    bind() {
      const c = this.canvas;
      c.addEventListener("wheel", (e) => { e.preventDefault(); const [x, y] = this.pos(e); this.zoom(e.deltaY < 0 ? 1.15 : 1 / 1.15, x, y); }, { passive: false });
      c.addEventListener("dblclick", (e) => { if (this.map && this.tool !== "area" && this.tool !== "aim") this.ping(...this.pos(e)); });
      c.addEventListener("pointerdown", (e) => {
        if (!this.map) return;
        try { c.setPointerCapture(e.pointerId); } catch (err) { /* capture is a nicety; drawing works without it */ }
        const p = this.pos(e);
        this.pointers.set(e.pointerId, p);
        if (this.pointers.size === 2) { // pinch
          const [a, b] = [...this.pointers.values()];
          this.drag = { pinch: true, d0: Math.hypot(a[0] - b[0], a[1] - b[1]), s0: this.view.s, mid: [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2], view0: { ...this.view } };
          this.preview.clear(); this.ruler = null; this.areaDraft = null;
          return;
        }
        // a quick second tap on a phone counts as a double-click
        const now = performance.now();
        if (e.pointerType === "touch" && this.lastTap && now - this.lastTap.t < 320 && Math.hypot(p[0] - this.lastTap.p[0], p[1] - this.lastTap.p[1]) < 24 && this.tool !== "area" && this.tool !== "aim") {
          this.lastTap = null; this.ping(...p); return;
        }
        this.lastTap = { t: now, p };
        const tool = e.button === 1 || e.button === 2 ? "pan" : this.tool;
        if (tool === "select") {
          const t = this.tokenAt(...p);
          if (t) {
            this.selectedId = t.id;
            if (this.opts.onSelect) this.opts.onSelect(t);
            const canMove = this.opts.canMove ? this.opts.canMove(t) : true;
            if (canMove) { const [cx, cy] = this.toCell(...p); this.drag = { token: t, grab: [cx - t.x, cy - t.y], at: [t.x, t.y], moved: false }; this.draw(); return; }
          } else {
            const sh = this.shapeAt(...p);
            if (sh) {
              this.selectedShape = sh.id;
              if (this.opts.onSelectShape) this.opts.onSelectShape(sh);
              const [cx, cy] = this.toCell(...p);
              this.drag = { shape: sh, grab: [cx - sh.x, cy - sh.y], at: [sh.x, sh.y], moved: false };
              this.draw(); return;
            }
            if (this.opts.onSelect) { this.selectedId = null; this.opts.onSelect(null); }
          }
          this.drag = { pan: true, start: p, view0: { ...this.view } };
        } else if (tool === "pan") {
          this.drag = { pan: true, start: p, view0: { ...this.view } };
        } else if (tool === "measure") {
          const cell = this.toCell(...p); this.drag = { measure: true }; this.ruler = [cell, cell];
        } else if (tool === "ping") {
          this.ping(...p);
        } else if (tool === "aim" && this.aim) {
          const [cx, cy] = this.toCell(...p), s = this.aim.shape, per = this.map.scale_value || 5;
          if (s.kind === "cone" || s.kind === "line") this.pointAim(cx, cy); // it stays on the caster and turns to face the click
          else { const [x, y] = this.clampAim(...snapOrigin(s.kind, cx, cy, s.size, per)); s.x = x; s.y = y; }
          this.drag = { aim: true };
          this.draw();
        } else if (tool === "area") {
          const [cx, cy] = this.toCell(...p), a = this.areaSpec, per = this.map.scale_value || 5;
          const [x, y] = snapOrigin(a.kind, cx, cy, a.size, per);
          this.areaDraft = Object.assign({}, a, { x, y, dir: a.dir || 0 });
          this.drag = { area: true };
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
          const r = this.reachOf(d.token); // in a fight: it stops at the edge of the movement box
          if (r) {
            nx = Math.max(r.ox - r.squares, Math.min(r.ox + r.squares, nx));
            ny = Math.max(r.oy - r.squares, Math.min(r.oy + r.squares, ny));
          }
          d.moved = d.moved || Math.abs(nx - d.token.x) > 0.05 || Math.abs(ny - d.token.y) > 0.05;
          d.at = [nx, ny];
          if (d.moved) this.ruler = [[d.token.x + 0.01, d.token.y + 0.01], [nx + 0.01, ny + 0.01]];
        } else if (d.shape) {
          const [cx, cy] = this.toCell(...p), per = this.map.scale_value || 5;
          const [nx, ny] = snapOrigin(d.shape.kind, cx - d.grab[0], cy - d.grab[1], d.shape.size, per);
          d.moved = d.moved || nx !== d.shape.x || ny !== d.shape.y;
          d.at = [nx, ny];
        } else if (d.aim && this.aim) {
          const [cx, cy] = this.toCell(...p), s = this.aim.shape;
          if (s.kind === "cone" || s.kind === "line") this.pointAim(cx, cy);
          else {
            const [x, y] = this.clampAim(...snapOrigin(s.kind, cx, cy, s.size, this.map.scale_value || 5)); s.x = x; s.y = y;
          }
          this.aim.hits = new Set(tokensInShape(s, this.map, this.tokens).map((t) => t.id));
        } else if (d.area && this.areaDraft) {
          const [cx, cy] = this.toCell(...p), a = this.areaDraft;
          if (a.kind === "cone" || a.kind === "line") {
            if (Math.hypot(cx - a.x, cy - a.y) > 0.3) a.dir = Math.round(Math.atan2(cy - a.y, cx - a.x) * 180 / Math.PI / 5) * 5;
          } else {
            const [x, y] = snapOrigin(a.kind, cx, cy, a.size, this.map.scale_value || 5); a.x = x; a.y = y;
          }
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
        if (d && d.shape && d.moved && this.opts.onShapeMove) {
          d.shape.x = d.at[0]; d.shape.y = d.at[1];
          this.opts.onShapeMove(d.shape, d.at[0], d.at[1]);
        }
        if (d && d.aim && this.aim && this.opts.onAim) {
          this.aim.hits = new Set(tokensInShape(this.aim.shape, this.map, this.tokens).map((t) => t.id));
          this.opts.onAim(this.aim);
        }
        if (d && d.area && this.areaDraft && this.opts.onArea) {
          const a = this.areaDraft; this.areaDraft = null;
          this.opts.onArea(a);
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
  window.MapView.shapeCells = shapeCells;
  window.MapView.KIND_COLOR = KIND_COLOR;
  window.MapView.shapeCells = shapeCells;
  window.MapView.tokensInShape = tokensInShape;
})();
