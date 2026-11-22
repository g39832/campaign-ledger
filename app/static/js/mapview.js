/* Battle map renderer + pointer interaction, shared by the DM editor and the
   player screen. It draws whatever data it is given; what a player receives
   has already been filtered by the server.

   On top of the map it animates short-lived effects: pings ("look here"),
   floating damage/heal numbers when a token's HP changes, and a pulse on the
   token whose turn it is. Spell areas (circle, cone, line, square) are drawn
   with the squares they cover highlighted. */
(function () {
  /* Steven Voss in phase 2 (half health or less, still up): his Hollow Star Heart gives him steel
     wings behind his token and the star glowing in his chest (effects.js FX.starHeart is the scene). */
  function starWinged(t) {
    if (!/^\s*steven\s+voss\b/i.test(String(t.display || t.name || ""))) return false;
    if (t.status === "dead" || t.status === "defeated" || t.health === "down") return false;
    if (t.hp != null && t.max_hp) return t.hp > 0 && t.hp * 2 <= t.max_hp;
    return t.health === "bloodied";
  }
  function drawSteelWings(ctx, cx, cy, r) {
    ctx.save();
    ctx.shadowColor = "rgba(120,210,255,.55)"; ctx.shadowBlur = r * 0.35;
    for (const side of [-1, 1]) {
      const px = cx + side * r * 0.35, py = cy - r * 0.15;
      [[9, 1.9, -80, 38, ["#f4f8fb", "#6d7884"]], [6, 1.25, -60, 28, ["#d8c08a", "#6b4e1e"]]].forEach(([n, len, a0, a1, cols]) => {
        for (let k = 0; k < n; k++) {
          const f = k / (n - 1), a = (a0 + (a1 - a0) * f) * Math.PI / 180, L = r * len * (1 - 0.32 * f), w = r * 0.15;
          ctx.save(); ctx.translate(px, py); ctx.scale(side, 1); ctx.rotate(a);
          const g = ctx.createLinearGradient(0, -w, 0, w); g.addColorStop(0, cols[0]); g.addColorStop(0.5, cols[1]); g.addColorStop(1, cols[0]);
          ctx.fillStyle = g; ctx.strokeStyle = "rgba(10,14,20,.7)"; ctx.lineWidth = Math.max(1, r * 0.025);
          ctx.beginPath(); ctx.moveTo(0, -w * 0.3); ctx.lineTo(L * 0.8, -w); ctx.lineTo(L, 0); ctx.lineTo(L * 0.8, w); ctx.lineTo(0, w * 0.3); ctx.closePath();
          ctx.fill(); ctx.stroke(); ctx.restore();
        }
      });
    }
    ctx.restore();
  }
  function drawChestStar(ctx, x, y, s) {
    ctx.save();
    ctx.shadowColor = "#bfeaff"; ctx.shadowBlur = s * 1.6;
    const star = (R, ri) => { ctx.beginPath(); for (let i = 0; i < 10; i++) { const a = -Math.PI / 2 + i * Math.PI / 5, rr = i % 2 ? ri : R; ctx.lineTo(x + Math.cos(a) * rr, y + Math.sin(a) * rr); } ctx.closePath(); };
    star(s, s * 0.42); ctx.fillStyle = "#fff6d8"; ctx.fill(); ctx.lineWidth = Math.max(1, s * 0.12); ctx.strokeStyle = "#f3d58a"; ctx.stroke();
    ctx.shadowBlur = 0; star(s * 0.55, s * 0.24); ctx.fillStyle = "#0e1a28"; ctx.fill();
    ctx.restore();
  }

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
    stairs: { fill: "#b9a67c", label: "Stairs down", stairs: true },
    // the abandoned (sci-fi) prison
    metal: { fill: "#5b6470", label: "Metal floor", plates: true }, grate: { fill: "#3e454e", label: "Floor grate", grate: true },
    bulkhead: { fill: "#22262d", label: "Steel wall", steel: true }, blastdoor: { fill: "#6b737e", label: "Blast door", blast: true },
    forcefield: { fill: "#24414f", label: "Force-field door", field: true },
    sealed: { fill: "#3a2626", label: "Sealed door (needs a card)", sealed: true }, panel: { fill: "#22262d", label: "Hidden wall panel", steel: true, seam: true },
    redlight: { fill: "#22262d", label: "Emergency light", steel: true, alarm: true }, camera: { fill: "#22262d", label: "Security camera", steel: true, camera: true },
    turret: { fill: "#2c3036", label: "Auto turret", turret: true }, terminal: { fill: "#2f3a44", label: "Security terminal", terminal: true },
    machinery: { fill: "#4a4f55", label: "Machinery", machine: true }, cryo: { fill: "#2c3e48", label: "Containment pod", cryo: true },
    // the missile silo: every block its own look (drawSilo)
    concrete: { fill: "#7b7973", label: "Concrete floor", silo: true, concrete: true },
    hazard: { fill: "#d8a422", label: "Hazard paint", silo: true, hazardpaint: true },
    catwalk: { fill: "#1d2024", label: "Mesh catwalk", silo: true, catwalk: true },
    cable: { fill: "#7b7973", label: "Cable run", silo: true, concrete: true, cables: true },
    coolant: { fill: "#7b7973", label: "Coolant spill", silo: true, concrete: true, coolant: true },
    silodoor: { fill: "#5d5b55", label: "Silo blast door", silo: true, silodoor: true },
    lift: { fill: "#45484c", label: "Freight lift (down)", silo: true, lift: true },
    pad: { fill: "#57595c", label: "Drone pad", silo: true, pad: true },
    escape: { fill: "#45484c", label: "Escape lift", silo: true, lift: true, escape: true },
    concretewall: { fill: "#3c3a36", label: "Concrete wall", silo: true, cwall: true },
    beacon: { fill: "#3c3a36", label: "Warning beacon", silo: true, cwall: true, beacon: true },
    shaft: { fill: "#060708", label: "Launch shaft (a long drop)", silo: true, shaft: true },
    missile: { fill: "#060708", label: "Missile", silo: true, missile: true },
    fueltank: { fill: "#7b7973", label: "Fuel tank", silo: true, concrete: true, tank: true },
    pipes: { fill: "#3c3a36", label: "Pipes", silo: true, pipes: true },
    reactor: { fill: "#1d2024", label: "Reactor core", silo: true, reactor: true },
    console: { fill: "#7b7973", label: "Launch console", silo: true, concrete: true, console: true },
    bunk: { fill: "#7b7973", label: "Bunk bed", silo: true, concrete: true, bunk: true },
    rack: { fill: "#7b7973", label: "Weapon rack", silo: true, concrete: true, rack: true },
    crate: { fill: "#7b7973", label: "Supply crates", silo: true, concrete: true, crate: true },
  };
  // How each kind of chest looks: body, stripe, light. (Rarity colours live in core.js L.RARITY.)
  const CHEST_LOOK = { supply: ["#6d6f62", "#e0b43a", "#9fdc7a"], military: ["#4e5a3c", "#d07a2a", "#e0b43a"], medical: ["#d8dde0", "#d23b3b", "#7fe0ff"],
    vault: ["#2d3442", "#3a7bd5", "#5fa8ff"], experimental: ["#3a2d4e", "#a34ff0", "#c78bff"], legendary: ["#2a2418", "#f0a43a", "#ffd36b"],
    drop: ["#555b63", "#8a9099", "#c9ced4"] };
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

  const GLIDE_FARTHEST = 24; // squares: farther than this a token just arrives (stairs, Party to start)
  class MapView {
    constructor(stage, opts) {
      this.stage = stage;
      this.opts = opts || {};
      this.canvas = document.createElement("canvas");
      this.canvas.className = "map-canvas";
      stage.prepend(this.canvas);
      this.ctx = this.canvas.getContext("2d");
      this.view = { s: 1, tx: 0, ty: 0 };
      this.map = null; this.tokens = []; this.glides = new Map(); this.tool = "select"; this.brush = 1;
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
      // squares just revealed fade in out of the dark (a room lighting up as a hero walks in)
      if (!first && map.fog_enabled && this.map.revealed && map.revealed && this.map.revealed !== map.revealed) {
        const was = this.map.revealed, fresh = new Set();
        for (let i = 0; i < map.revealed.length; i++) if (map.revealed[i] === "1" && was[i] !== "1") fresh.add(i);
        if (fresh.size) { this.fade = { cells: fresh, t0: performance.now() }; }
      }
      if (first) this.glides.clear(); else { this.startGlides(tokens); this.noticeChests(this.map, map); }
      this.map = map; this.tokens = tokens;
      // the ground (terrain, grid, lights, chests) and the fog are drawn once into pictures and reused
      // every frame; they're drawn again only when they change (this is what keeps tablets smooth)
      const ground = JSON.stringify([map.id, map.cols, map.rows, map.cell_px, map.bg_color, map.show_grid, map.grid_color, map.grid_opacity, map.terrain, map.chests]);
      if (ground !== this.groundKey) { this.groundKey = ground; this.layerDirty = true; }
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
    /** Someone moved: their token slides to the new square instead of jumping there. A token this
        screen already put there (its own drag) has nothing to do; a very long trip just arrives. */
    startGlides(next) {
      if (document.hidden || (window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches)) { this.glides.clear(); return; }
      const was = new Map(this.tokens.map((t) => [t.id, t])), now = performance.now();
      for (const t of next) {
        const old = was.get(t.id);
        if (!old || (old.x === t.x && old.y === t.y)) continue;
        if (this.drag && this.drag.token && this.drag.token.id === t.id) continue;
        const [x, y] = this.shownAt(old, now), dist = Math.hypot(t.x - x, t.y - y);
        if (dist > GLIDE_FARTHEST) { this.glides.delete(t.id); continue; }
        this.glides.set(t.id, { x, y, t0: now, ms: Math.min(480, 170 + dist * 45) });
      }
      if (this.glides.size && !this.raf) this.raf = requestAnimationFrame(() => this.loop());
    }
    /** Where a token is drawn right now, and how lifted it is (0 to 1) while it slides. */
    shownAt(t, now) {
      const g = this.glides.get(t.id);
      if (!g) return [t.x, t.y, 0];
      const k = ((now === undefined ? performance.now() : now) - g.t0) / g.ms;
      if (k >= 1) { this.glides.delete(t.id); return [t.x, t.y, 0]; }
      const e = k <= 0 ? 0 : 1 - Math.pow(1 - k, 3);
      return [g.x + (t.x - g.x) * e, g.y + (t.y - g.y) * e, Math.sin(Math.PI * Math.max(0, k))];
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
      // a look picked on the attack form wins over the guess from its name
      const LOOK = { slash: "slash", punch: "punch", bite: "bite", arrow: "arrow", flames: "fire", frost: "ice", sparks: "lightning",
        holy: "radiant", venom: "poison", arcane: "arcane", rock: "earth", quake: "earth", laser: "laser" };
      const style = LOOK[fx.style] || MapView.fxStyle(fx.name, fx.kind, fx.type), start = performance.now() - (age || 0) * 1000;
      const COLORS = { fire: "#ff7a2f", ice: "#8fdcff", lightning: "#fff27a", radiant: "#ffe9a3", poison: "#8fe36b", arcane: "#c08bff",
        arrow: "#e8d9b5", slash: "#ffffff", punch: "#ffd28a", bite: "#ffffff", earth: "#b98a55", heal: "#9fdc7a", shimmer: "#f3d58a", laser: "#ff3b30" };
      const color = COLORS[style] || "#ffffff", hows = fx.how || [];
      // Earth Shatter: an earth move with a radius shakes the map and splits the ground across all of it
      // (or any move given the Earthquake look: without a radius it shakes 10 ft around who it hits)
      const circle = fx.area && fx.area.kind === "circle";
      const quake = fx.style ? fx.style === "quake" : circle && (style === "earth" || /quake|tremor|seismic|fissure/i.test(fx.name || ""));
      const quakeAt = !quake ? null : circle ? fx.area.at || fx.from || (fx.to && fx.to[0]) : (fx.to && fx.to[0]) || fx.from;
      if (quakeAt) {
        const r = circle ? Math.max(1, (fx.area.squares || 3) * 5 / ((this.map && this.map.scale_value) || 5)) : 2;
        this.addFx({ type: "quake", x: quakeAt[0], y: quakeAt[1], r, cracks: MapView.cracks(r), ms: 2600, start });
        if (window.FX) FX.sound("quake");
      }
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
    /* Jagged cracks from the middle out to the edge of a radius r (in squares), with side branches.
       Each is a list of points; made once per quake so every frame draws the same cracks. */
    static cracks(r) {
      const out = [], n = Math.max(7, Math.min(16, Math.round(r * 1.2)));
      const walk = (x, y, ang, len, depth) => {
        const pts = [[x, y]], steps = Math.max(3, Math.round(len * 2));
        for (let i = 1; i <= steps; i++) {
          ang += (Math.random() - 0.5) * 0.7;
          x += Math.cos(ang) * len / steps; y += Math.sin(ang) * len / steps;
          if (Math.hypot(x, y) > r) break;
          pts.push([x, y]);
          if (depth < 2 && Math.random() < 0.18) walk(x, y, ang + (Math.random() < 0.5 ? -1 : 1) * (0.5 + Math.random() * 0.5), len * (0.3 + Math.random() * 0.25), depth + 1);
        }
        out.push({ pts, w: depth ? 0.05 : 0.11, at: Math.hypot(pts[0][0], pts[0][1]) / r });
      };
      for (let i = 0; i < n; i++) walk(0, 0, (i + Math.random() * 0.6) / n * Math.PI * 2, r * (0.75 + Math.random() * 0.25), 0);
      for (let i = 0; i < n * 2; i++) { // loose rocks thrown up
        const a = Math.random() * Math.PI * 2, d = Math.sqrt(Math.random()) * r;
        out.push({ rock: [Math.cos(a) * d, Math.sin(a) * d], size: 0.08 + Math.random() * 0.14, at: d / r });
      }
      return out;
    }
    quakeShake() {
      const now = performance.now();
      let amp = 0;
      for (const f of this.fx) if (f.type === "quake") {
        const k = (now - f.start) / f.ms;
        if (k >= 0 && k < 0.75) amp = Math.max(amp, (1 - k / 0.75) * Math.min(1, k * 8));
      }
      if (!amp) return [0, 0];
      const s = (this.view.s || 1) * (this.map ? this.map.cell_px : 50) * 0.16 * amp;
      return [Math.sin(now / 23) * s + (Math.random() - 0.5) * s * 0.6, Math.cos(now / 31) * s * 0.7 + (Math.random() - 0.5) * s * 0.5];
    }
    /** The ground splitting: dust rolling out to the edge, cracks tearing outward, rocks jumping. */
    drawQuakes(cp, ox, oy) {
      const ctx = this.ctx, now = performance.now();
      for (const f of this.fx) {
        if (f.type !== "quake") continue;
        const k = (now - f.start) / f.ms;
        if (k < 0 || k > 1) continue;
        const X = ox + f.x * cp, Y = oy + f.y * cp, R = f.r * cp, fade = k < 0.7 ? 1 : (1 - k) / 0.3;
        ctx.save();
        // the area darkens like churned earth
        const g = ctx.createRadialGradient(X, Y, 0, X, Y, R);
        g.addColorStop(0, `rgba(70,45,22,${0.38 * fade})`); g.addColorStop(0.85, `rgba(90,60,30,${0.22 * fade})`); g.addColorStop(1, "rgba(90,60,30,0)");
        ctx.fillStyle = g; ctx.beginPath(); ctx.arc(X, Y, R, 0, Math.PI * 2); ctx.fill();
        // shockwave rings of dust rolling out to the edge
        for (let i = 0; i < 2; i++) {
          const q = Math.min(1, Math.max(0, (k - i * 0.15) / 0.55));
          if (q <= 0 || q >= 1) continue;
          ctx.strokeStyle = `rgba(185,150,105,${(1 - q) * 0.85})`; ctx.lineWidth = cp * (0.5 - q * 0.3);
          ctx.beginPath(); ctx.arc(X, Y, R * q, 0, Math.PI * 2); ctx.stroke();
        }
        const grow = Math.min(1, k / 0.45); // cracks tear out from the middle
        ctx.lineCap = "round"; ctx.lineJoin = "round";
        for (const c of f.cracks) {
          if (c.rock) {
            const q = (k - c.at * 0.45) / 0.35;
            if (q <= 0 || q >= 1) continue;
            const hop = Math.sin(q * Math.PI) * cp * 0.5;
            ctx.globalAlpha = fade; ctx.fillStyle = "#6b4a2b"; ctx.strokeStyle = "rgba(20,12,6,.8)"; ctx.lineWidth = cp * 0.02;
            const s = c.size * cp, rx = X + c.rock[0] * cp, ry = Y + c.rock[1] * cp - hop;
            ctx.beginPath(); ctx.moveTo(rx - s, ry); ctx.lineTo(rx - s * 0.3, ry - s * 0.9); ctx.lineTo(rx + s, ry - s * 0.4); ctx.lineTo(rx + s * 0.6, ry + s * 0.7); ctx.closePath(); ctx.fill(); ctx.stroke();
            continue;
          }
          const show = (grow - c.at) / Math.max(0.05, 1 - c.at);
          if (show <= 0) continue;
          const upto = Math.max(1, Math.ceil(c.pts.length * Math.min(1, show)));
          ctx.globalAlpha = fade;
          for (const [w, col] of [[c.w * 2.2, "rgba(30,18,8,.55)"], [c.w, "#140b05"], [c.w * 0.35, "rgba(255,140,60,.55)"]]) {
            ctx.strokeStyle = col; ctx.lineWidth = cp * w;
            ctx.beginPath(); ctx.moveTo(X + c.pts[0][0] * cp, Y + c.pts[0][1] * cp);
            for (let i = 1; i < upto; i++) ctx.lineTo(X + c.pts[i][0] * cp, Y + c.pts[i][1] * cp);
            ctx.stroke();
          }
        }
        ctx.restore();
      }
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
      this.raf = this.fx.length || this.glides.size || (this.zones && this.zones.length) ? requestAnimationFrame(() => this.loop()) : 0;
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
        const [gx, gy] = this.shownAt(t), tx = dragging ? this.drag.at[0] : gx, ty = dragging ? this.drag.at[1] : gy;
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
      const { s } = this.view, cp = m.cell_px, ox = m.offset_x, oy = m.offset_y;
      let { tx, ty } = this.view;
      const [jx, jy] = this.quakeShake(); tx += jx; ty += jy;
      ctx.setTransform(dpr * s, 0, 0, dpr * s, dpr * tx, dpr * ty);
      const gw = m.cols * cp, gh = m.rows * cp;
      if (this.bg) ctx.drawImage(this.bg, 0, 0);
      const lk = this.layerScale(gw, gh, dpr * s);
      if (lk) { // the saved picture of the ground
        if (this.layerDirty || !this.layer || this.layerK !== lk || this.layerBg !== !!this.bg) this.buildLayer(lk);
        ctx.drawImage(this.layer, ox, oy, gw, gh);
      } else { // zoomed right in: draw just the squares on screen, sharp
        if (!this.bg) { ctx.fillStyle = m.bg_color || "#d9ccae"; ctx.fillRect(ox, oy, gw, gh); }
        const vx0 = Math.floor((-tx / s - ox) / cp) - 3, vx1 = Math.ceil(((this.w - tx) / s - ox) / cp) + 3;
        const vy0 = Math.floor((-ty / s - oy) / cp) - 3, vy1 = Math.ceil(((this.h - ty) / s - oy) / cp) + 3;
        this.drawGround(cp, ox, oy, [vx0, vy0, vx1, vy1]);
      }
      if (m.show_grid && !lk) {
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
      if (this.mark) { // a square picked on the map (where a summoned clone appears)
        const [mx, my] = this.mark;
        ctx.save();
        ctx.fillStyle = "rgba(140, 200, 255, .28)"; ctx.strokeStyle = "rgba(140, 200, 255, .95)"; ctx.lineWidth = cp * 0.08; ctx.setLineDash([cp * 0.18, cp * 0.1]);
        ctx.fillRect(ox + mx * cp, oy + my * cp, cp, cp); ctx.strokeRect(ox + mx * cp + cp * 0.04, oy + my * cp + cp * 0.04, cp * 0.92, cp * 0.92);
        ctx.restore();
      }
      this.drawChests(cp, ox, oy, lk ? "moving" : "all");
      this.drawZones(cp, ox, oy);
      this.drawQuakes(cp, ox, oy);
      if (this.drag && this.drag.token && this.drag.moved) this.drawReach(this.drag.token, cp, ox, oy);
      for (const t of this.tokens) this.drawToken(t, cp, ox, oy);
      if (this.drag && this.drag.token && this.drag.moved) this.drawStepLabel(this.drag.token, cp, ox, oy);
      if (this.aim && this.aim.hits) for (const t of this.tokens) if (this.aim.hits.has(t.id)) {
        const [gx, gy] = this.shownAt(t), r = t.size * cp * 0.5, X = ox + (gx + t.size / 2) * cp, Y = oy + (gy + t.size / 2) * cp;
        ctx.save(); ctx.strokeStyle = "#ffd36b"; ctx.lineWidth = cp * 0.1; ctx.shadowColor = "#ffb347"; ctx.shadowBlur = cp * 0.4;
        ctx.beginPath(); ctx.arc(X, Y, r, 0, Math.PI * 2); ctx.stroke(); ctx.restore();
      }
      if (m.fog_enabled) {
        const dm = this.opts.role === "dm";
        // the dark (and, on a made-up map, the dimmed squares seen before but out of sight now):
        // one pixel per square, scaled up with hard edges
        ctx.save(); ctx.imageSmoothingEnabled = false;
        ctx.drawImage(this.fogPicture(dm), ox - 0.25, oy - 0.25, gw + 0.5, gh + 0.5);
        ctx.restore();
        const f = this.fade, age = f ? (performance.now() - f.t0) / 900 : 1;
        if (f && age < 1) { // the dark lifting off newly revealed squares, with a warm glow at the edge
          ctx.save(); ctx.globalAlpha = (1 - age) * (dm ? 0.55 : 1); ctx.fillStyle = dm ? "rgba(10,8,6,1)" : "#080706";
          for (const i of f.cells) ctx.fillRect(ox + (i % m.cols) * cp - 0.5, oy + Math.floor(i / m.cols) * cp - 0.5, cp + 1, cp + 1);
          ctx.globalAlpha = Math.sin(age * Math.PI) * 0.35; ctx.fillStyle = "#ffd98a";
          for (const i of f.cells) ctx.fillRect(ox + (i % m.cols) * cp, oy + Math.floor(i / m.cols) * cp, cp, cp);
          ctx.restore();
          if (!this.fadeRaf) this.fadeRaf = requestAnimationFrame(() => { this.fadeRaf = 0; this.draw(); });
        } else if (f) this.fade = null;
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
      if (T.stairs) { // steps going down, darker as they go
        for (let i = 0; i < 4; i++) { ctx.fillStyle = "rgba(30,20,10," + (0.12 + i * 0.16) + ")"; ctx.fillRect(X + cp * 0.1, Y + cp * (0.1 + i * 0.2), cp * 0.8, cp * 0.16); }
      }
      if (T.plates || T.grate || T.steel || T.blast || T.field || T.sealed || T.turret || T.terminal || T.machine || T.cryo) this.drawSciFi(T, x, y, X, Y, cp);
      if (T.silo) this.drawSilo(kind, T, x, y, X, Y, cp);
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
    /* How sharp the saved ground picture is: a power of two at or above the screen's own (for zoom
       and sharp displays), but never a picture too big for a phone (8 million pixels). 0: zoomed in
       too far for that, so the ground is drawn straight onto the screen (just the squares in view). */
    layerScale(gw, gh, want) {
      const cap = Math.min(4096 / Math.max(gw, gh), Math.sqrt(8e6 / (gw * gh)));
      let k = Math.pow(2, Math.ceil(Math.log2(Math.max(0.25, want))));
      if (k > cap) k = want <= cap ? cap : 0;
      return k;
    }
    /** Terrain, emergency light, grid and still chests, in squares x0..x1, y0..y1 (all of them if none). */
    drawGround(cp, ox, oy, box, grid) {
      const m = this.map;
      let alarms = false;
      for (const [key, kind] of Object.entries(m.terrain || {})) {
        const c = key.indexOf(","), x = +key.slice(0, c), y = +key.slice(c + 1);
        if (kind === "redlight" || kind === "beacon") alarms = true;
        if (box && (x < box[0] || x > box[2] || y < box[1] || y > box[3])) continue;
        this.drawTerrain(kind, x, y, cp, ox, oy);
      }
      if (alarms) this.drawAlarmGlow(cp, ox, oy, box);
      if (grid && m.show_grid) {
        const ctx = this.ctx, gw = m.cols * cp, gh = m.rows * cp;
        ctx.strokeStyle = m.grid_color || "#000"; ctx.globalAlpha = (m.grid_opacity ?? 35) / 100;
        ctx.lineWidth = Math.max(1 / this.layerK, cp * 0.02);
        ctx.beginPath();
        for (let x = 0; x <= m.cols; x++) { ctx.moveTo(ox + x * cp, oy); ctx.lineTo(ox + x * cp, oy + gh); }
        for (let y = 0; y <= m.rows; y++) { ctx.moveTo(ox, oy + y * cp); ctx.lineTo(ox + gw, oy + y * cp); }
        ctx.stroke(); ctx.globalAlpha = 1;
      }
      if (grid) this.drawChests(cp, ox, oy, "still");
    }
    buildLayer(k) {
      const m = this.map, cp = m.cell_px, W = Math.max(1, Math.ceil(m.cols * cp * k)), H = Math.max(1, Math.ceil(m.rows * cp * k));
      if (!this.layer) this.layer = document.createElement("canvas");
      const L = this.layer;
      if (L.width !== W) L.width = W;
      if (L.height !== H) L.height = H;
      const lc = L.getContext("2d"), main = this.ctx;
      lc.setTransform(1, 0, 0, 1, 0, 0); lc.clearRect(0, 0, W, H); lc.setTransform(k, 0, 0, k, 0, 0);
      this.layerK = k;
      this.ctx = lc;
      try {
        if (!this.bg) { lc.fillStyle = m.bg_color || "#d9ccae"; lc.fillRect(0, 0, m.cols * cp, m.rows * cp); }
        this.drawGround(cp, 0, 0, null, true);
      } finally { this.ctx = main; }
      this.layerDirty = false; this.layerBg = !!this.bg;
    }
    /** The fog as a tiny picture, one pixel per square, remade only when what's revealed or seen changes. */
    fogPicture(dm) {
      const m = this.map, key = [m.cols, m.rows, dm, m.revealed, dm ? "" : m.visible].join("|");
      if (this.fogKey === key && this.fogCanvas) return this.fogCanvas;
      const c = this.fogCanvas || (this.fogCanvas = document.createElement("canvas"));
      c.width = m.cols; c.height = m.rows;
      const g = c.getContext("2d"), img = g.createImageData(m.cols, m.rows), d = img.data, rev = m.revealed || "", vis = !dm && m.visible;
      for (let i = 0; i < m.cols * m.rows; i++) {
        let a = 0, r = 8, gg = 7, b = 6;
        if (rev[i] !== "1") { a = dm ? 140 : 255; if (dm) { r = 10; gg = 8; b = 6; } }
        else if (vis && vis[i] !== "1") a = 158; // seen before, out of sight now
        d[i * 4] = r; d[i * 4 + 1] = gg; d[i * 4 + 2] = b; d[i * 4 + 3] = a;
      }
      g.putImageData(img, 0, 0);
      this.fogKey = key;
      return c;
    }
    /* The abandoned prison: steel plates and rivets, grates, bulkheads, doors, lights and machines. */
    drawSciFi(T, x, y, X, Y, cp) {
      const ctx = this.ctx, lw = cp * 0.03;
      const dot = (a, b, r, c) => { ctx.fillStyle = c; ctx.beginPath(); ctx.arc(X + a * cp, Y + b * cp, r * cp, 0, Math.PI * 2); ctx.fill(); };
      if (T.plates) {
        ctx.strokeStyle = "rgba(0,0,0,.35)"; ctx.lineWidth = lw; ctx.strokeRect(X + lw, Y + lw, cp - 2 * lw, cp - 2 * lw);
        ctx.strokeStyle = "rgba(255,255,255,.07)"; ctx.beginPath(); ctx.moveTo(X + cp * 0.06, Y + cp * 0.5); ctx.lineTo(X + cp * 0.94, Y + cp * 0.5); ctx.stroke();
        if (hash(x, y) > 0.82) dot(hash(y, x), hash(x + 3, y), 0.18, "rgba(20,10,5,.25)"); // grime
        for (const [a, b] of [[0.12, 0.12], [0.88, 0.12], [0.12, 0.88], [0.88, 0.88]]) dot(a, b, 0.035, "rgba(0,0,0,.4)");
        const v = hash(x * 3 + 1, y * 5 + 2); // a few kinds of plate, so the floor isn't all one tile
        ctx.fillStyle = v < 0.5 ? "rgba(255,255,255," + (0.02 + v * 0.06).toFixed(3) + ")" : "rgba(0,0,0," + ((v - 0.5) * 0.12).toFixed(3) + ")";
        ctx.fillRect(X, Y, cp, cp);
        if (v < 0.22) { // diamond tread
          ctx.strokeStyle = "rgba(255,255,255,.12)"; ctx.lineWidth = cp * 0.025; ctx.beginPath();
          for (let i = 0; i < 4; i++) for (let j = 0; j < 4; j++) { const a = X + cp * (0.18 + i * 0.21), b = Y + cp * (0.18 + j * 0.21), o = (i + j) % 2 ? 1 : -1;
            ctx.moveTo(a - cp * 0.05, b - o * cp * 0.04); ctx.lineTo(a + cp * 0.05, b + o * cp * 0.04); }
          ctx.stroke();
        } else if (v < 0.32) { // a vent
          ctx.fillStyle = "rgba(0,0,0,.45)"; for (let i = 0; i < 4; i++) ctx.fillRect(X + cp * 0.25, Y + cp * (0.28 + i * 0.13), cp * 0.5, cp * 0.06);
        } else if (v > 0.95) { // a painted floor number
          ctx.fillStyle = "rgba(230,200,90,.35)"; ctx.font = "bold " + Math.round(cp * 0.32) + "px sans-serif"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
          ctx.fillText(String(1 + Math.floor(hash(x, y + 9) * 9)), X + cp / 2, Y + cp / 2);
        }
      }
      if (T.grate) {
        ctx.strokeStyle = "rgba(0,0,0,.55)"; ctx.lineWidth = cp * 0.05;
        ctx.beginPath(); for (let i = 1; i < 6; i++) { ctx.moveTo(X + cp * 0.12, Y + i * cp / 6); ctx.lineTo(X + cp * 0.88, Y + i * cp / 6); } ctx.stroke();
        ctx.strokeStyle = "rgba(160,170,180,.35)"; ctx.lineWidth = lw; ctx.strokeRect(X + cp * 0.1, Y + cp * 0.1, cp * 0.8, cp * 0.8);
      }
      if (T.steel) {
        const g = ctx.createLinearGradient(X, Y, X + cp, Y + cp); g.addColorStop(0, "rgba(255,255,255,.06)"); g.addColorStop(1, "rgba(0,0,0,.25)");
        ctx.fillStyle = g; ctx.fillRect(X, Y, cp, cp);
        ctx.strokeStyle = "rgba(0,0,0,.5)"; ctx.lineWidth = lw; ctx.strokeRect(X + lw / 2, Y + lw / 2, cp - lw, cp - lw);
        const w = hash(x * 7 + 3, y * 2 + 1); // ribbed, panelled or plain wall sections
        if (!T.alarm && !T.camera && !T.seam) {
          if (w < 0.3) { ctx.strokeStyle = "rgba(255,255,255,.06)"; ctx.lineWidth = cp * 0.05; ctx.beginPath(); for (let i = 1; i < 4; i++) { ctx.moveTo(X + i * cp / 4, Y + cp * 0.1); ctx.lineTo(X + i * cp / 4, Y + cp * 0.9); } ctx.stroke(); }
          else if (w < 0.5) { ctx.strokeStyle = "rgba(0,0,0,.35)"; ctx.lineWidth = lw; ctx.strokeRect(X + cp * 0.18, Y + cp * 0.18, cp * 0.64, cp * 0.64); dot(0.25, 0.25, 0.03, "rgba(255,255,255,.12)"); dot(0.75, 0.75, 0.03, "rgba(255,255,255,.12)"); }
          else if (w > 0.93) { ctx.fillStyle = "rgba(224,180,58,.5)"; ctx.fillRect(X + cp * 0.1, Y + cp * 0.42, cp * 0.8, cp * 0.08); }
        }
        if (T.seam) { ctx.strokeStyle = "rgba(160,190,210,.18)"; ctx.setLineDash([cp * 0.08, cp * 0.06]); ctx.strokeRect(X + cp * 0.2, Y + cp * 0.15, cp * 0.6, cp * 0.7); ctx.setLineDash([]); }
        if (T.alarm) { ctx.shadowColor = "#ff3b30"; ctx.shadowBlur = cp * 0.5; dot(0.5, 0.5, 0.16, "#ff3b30"); ctx.shadowBlur = 0; }
        if (T.camera) {
          ctx.fillStyle = "#9aa3ad"; ctx.fillRect(X + cp * 0.25, Y + cp * 0.38, cp * 0.42, cp * 0.24);
          dot(0.7, 0.5, 0.1, "#14171b"); dot(0.32, 0.44, 0.04, "#ff3b30");
        }
      }
      if (T.blast) {
        ctx.fillStyle = "rgba(0,0,0,.3)"; ctx.fillRect(X + cp * 0.47, Y, cp * 0.06, cp);
        ctx.fillStyle = "#e0b43a";
        for (let i = 0; i < 4; i++) { const yy = Y + i * cp / 4; ctx.beginPath(); ctx.moveTo(X, yy); ctx.lineTo(X + cp * 0.12, yy); ctx.lineTo(X, yy + cp * 0.12); ctx.fill(); }
        dot(0.82, 0.2, 0.05, "#5fdc7a");
      }
      if (T.field) {
        ctx.strokeStyle = "rgba(110,220,255,.85)"; ctx.lineWidth = cp * 0.05; ctx.shadowColor = "#6edcff"; ctx.shadowBlur = cp * 0.3;
        ctx.beginPath(); for (let i = 1; i < 4; i++) { ctx.moveTo(X + i * cp / 4, Y + cp * 0.05); ctx.lineTo(X + i * cp / 4, Y + cp * 0.95); } ctx.stroke(); ctx.shadowBlur = 0;
      }
      if (T.sealed) {
        ctx.fillStyle = "#555c66"; ctx.fillRect(X + cp * 0.08, Y + cp * 0.08, cp * 0.84, cp * 0.84);
        ctx.fillStyle = "#d23b3b"; ctx.fillRect(X + cp * 0.08, Y + cp * 0.42, cp * 0.84, cp * 0.16);
        ctx.fillStyle = "#ff5a4f"; ctx.shadowColor = "#ff3b30"; ctx.shadowBlur = cp * 0.4; ctx.fillRect(X + cp * 0.38, Y + cp * 0.2, cp * 0.24, cp * 0.14); ctx.shadowBlur = 0;
      }
      if (T.turret) {
        dot(0.5, 0.5, 0.34, "#555c66");
        ctx.strokeStyle = "#1a1d21"; ctx.lineWidth = cp * 0.12; ctx.beginPath(); ctx.moveTo(X + cp / 2, Y + cp / 2); ctx.lineTo(X + cp * 0.95, Y + cp * 0.5); ctx.stroke();
        dot(0.5, 0.5, 0.08, "#ff3b30");
      }
      if (T.terminal) {
        ctx.fillStyle = "#1a2229"; ctx.fillRect(X + cp * 0.12, Y + cp * 0.15, cp * 0.76, cp * 0.5);
        ctx.fillStyle = "rgba(90,220,255,.85)"; for (let i = 0; i < 3; i++) ctx.fillRect(X + cp * 0.18, Y + cp * (0.22 + i * 0.13), cp * (0.3 + hash(x + i, y) * 0.32), cp * 0.05);
        ctx.fillStyle = "#3a444e"; ctx.fillRect(X + cp * 0.2, Y + cp * 0.7, cp * 0.6, cp * 0.14);
      }
      if (T.machine) {
        ctx.strokeStyle = "rgba(0,0,0,.5)"; ctx.lineWidth = lw * 2; ctx.strokeRect(X + cp * 0.1, Y + cp * 0.1, cp * 0.8, cp * 0.8);
        ctx.strokeStyle = "#8a9099"; ctx.lineWidth = cp * 0.06; ctx.beginPath(); ctx.arc(X + cp * 0.5, Y + cp * 0.5, cp * 0.22, 0, Math.PI * 2); ctx.stroke();
        ctx.fillStyle = "#e0b43a"; ctx.fillRect(X + cp * 0.1, Y + cp * 0.82, cp * 0.8, cp * 0.08);
      }
      if (T.cryo) {
        ctx.fillStyle = "rgba(120,220,255,.35)"; ctx.strokeStyle = "#9fe6ff"; ctx.lineWidth = cp * 0.05;
        ctx.beginPath(); ctx.ellipse(X + cp / 2, Y + cp / 2, cp * 0.3, cp * 0.42, 0, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
        dot(0.5, 0.4, 0.1, "rgba(30,50,60,.6)"); // someone inside
      }
    }
    /* The missile silo. Concrete that varies square to square (pour joints, cracks, stains, painted
       numbers), hazard paint, mesh catwalks, the open shaft, the missiles (one picture across their
       3x3 block), and the furniture: tanks, pipes, reactor, consoles, bunks, racks, crates, cables. */
    drawSilo(kind, T, x, y, X, Y, cp) {
      const ctx = this.ctx, ter = (this.map && this.map.terrain) || {}, at = (a, b) => ter[a + "," + b];
      const dot = (a, b, r, c) => { ctx.fillStyle = c; ctx.beginPath(); ctx.arc(X + a * cp, Y + b * cp, r * cp, 0, Math.PI * 2); ctx.fill(); };
      const rr = (a, b, w, h, r, fill, stroke) => { ctx.beginPath(); ctx.roundRect(X + a * cp, Y + b * cp, w * cp, h * cp, r * cp); if (fill) { ctx.fillStyle = fill; ctx.fill(); } if (stroke) { ctx.strokeStyle = stroke; ctx.lineWidth = cp * 0.03; ctx.stroke(); } };
      const hv = hash(x * 13 + 5, y * 7 + 3);
      if (T.concrete) {
        ctx.fillStyle = hv < 0.5 ? "rgba(255,255,255," + (hv * 0.08).toFixed(3) + ")" : "rgba(0,0,0," + ((hv - 0.5) * 0.14).toFixed(3) + ")";
        ctx.fillRect(X, Y, cp, cp);
        ctx.strokeStyle = "rgba(0,0,0,.22)"; ctx.lineWidth = cp * 0.025; ctx.beginPath();
        if (x % 3 === 0) { ctx.moveTo(X, Y); ctx.lineTo(X, Y + cp); }   // pour joints every three squares
        if (y % 3 === 0) { ctx.moveTo(X, Y); ctx.lineTo(X + cp, Y); }
        ctx.stroke();
        const k = hash(y * 11 + 2, x * 17 + 9);
        if (k < 0.16) { // a crack
          ctx.strokeStyle = "rgba(30,28,24,.5)"; ctx.lineWidth = cp * 0.022; ctx.beginPath();
          let px = X + cp * (0.1 + hash(x, y + 1) * 0.3), py = Y + cp * (0.1 + hash(x + 1, y) * 0.8);
          ctx.moveTo(px, py);
          for (let i = 0; i < 4; i++) { px += cp * (0.12 + hash(x + i, y) * 0.1); py += cp * (hash(y, x + i) - 0.5) * 0.3; ctx.lineTo(px, py); }
          ctx.stroke();
        } else if (k < 0.26) { // an oil stain
          ctx.fillStyle = "rgba(25,22,18,.22)"; ctx.beginPath();
          ctx.ellipse(X + cp * (0.3 + hv * 0.4), Y + cp * (0.3 + k * 1.5), cp * 0.22, cp * 0.14, hv * 3, 0, Math.PI * 2); ctx.fill();
        } else if (k > 0.97 && !T.crate && !T.tank && !T.console && !T.bunk && !T.rack) { // a stencilled level marking
          ctx.fillStyle = "rgba(225,170,40,.45)"; ctx.font = "bold " + Math.round(cp * 0.3) + "px monospace"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
          ctx.fillText("S" + (1 + Math.floor(hv * 9)), X + cp / 2, Y + cp / 2);
        }
      }
      if (T.hazardpaint) {
        ctx.fillStyle = "#1a1a1a";
        for (let i = -1; i < 4; i++) { ctx.beginPath(); const o = ((x + y) % 2) * 0.25; ctx.moveTo(X + (i * 0.5 + o) * cp, Y + cp); ctx.lineTo(X + (i * 0.5 + 0.25 + o) * cp, Y + cp);
          ctx.lineTo(X + (i * 0.5 + 0.75 + o) * cp, Y); ctx.lineTo(X + (i * 0.5 + 0.5 + o) * cp, Y); ctx.fill(); }
        ctx.fillStyle = "rgba(120,110,95," + (0.15 + hv * 0.35).toFixed(3) + ")"; // scuffed by boots
        ctx.beginPath(); ctx.ellipse(X + cp * (0.3 + hv * 0.4), Y + cp * 0.5, cp * 0.3, cp * 0.2, hv * 2, 0, Math.PI * 2); ctx.fill();
      }
      if (T.catwalk) {
        ctx.strokeStyle = "#5d636b"; ctx.lineWidth = cp * 0.035; ctx.beginPath();
        for (let i = 0; i <= 5; i++) { ctx.moveTo(X + i * cp / 5, Y); ctx.lineTo(X + i * cp / 5, Y + cp); ctx.moveTo(X, Y + i * cp / 5); ctx.lineTo(X + cp, Y + i * cp / 5); }
        ctx.stroke();
        ctx.strokeStyle = "#8b9199"; ctx.lineWidth = cp * 0.07; ctx.beginPath(); // a rail along any side that drops into the shaft
        if (at(x - 1, y) === "shaft") { ctx.moveTo(X + cp * 0.04, Y); ctx.lineTo(X + cp * 0.04, Y + cp); }
        if (at(x + 1, y) === "shaft") { ctx.moveTo(X + cp * 0.96, Y); ctx.lineTo(X + cp * 0.96, Y + cp); }
        if (at(x, y - 1) === "shaft") { ctx.moveTo(X, Y + cp * 0.04); ctx.lineTo(X + cp, Y + cp * 0.04); }
        if (at(x, y + 1) === "shaft") { ctx.moveTo(X, Y + cp * 0.96); ctx.lineTo(X + cp, Y + cp * 0.96); }
        ctx.stroke();
      }
      if (T.shaft || T.missile) { // the drop: black, with a lit lip where the floor ends
        const g = ctx.createRadialGradient(X + cp / 2, Y + cp / 2, 0, X + cp / 2, Y + cp / 2, cp * 0.8);
        g.addColorStop(0, "rgba(40,60,80," + (0.08 + hv * 0.1).toFixed(3) + ")"); g.addColorStop(1, "rgba(0,0,0,0)");
        ctx.fillStyle = g; ctx.fillRect(X, Y, cp, cp);
        if (T.shaft) {
          ctx.fillStyle = "rgba(255,255,255,.05)"; if (hv > 0.6) ctx.fillRect(X + cp * 0.45, Y, cp * 0.06, cp); // ladder rail far below
          ctx.fillStyle = "rgba(170,160,140,.55)";
          const lip = (o) => o !== "shaft" && o !== "missile" && o !== undefined;
          if (lip(at(x - 1, y))) ctx.fillRect(X, Y, cp * 0.07, cp);
          if (lip(at(x + 1, y))) ctx.fillRect(X + cp * 0.93, Y, cp * 0.07, cp);
          if (lip(at(x, y - 1))) ctx.fillRect(X, Y, cp, cp * 0.07);
          if (lip(at(x, y + 1))) ctx.fillRect(X, Y + cp * 0.93, cp, cp * 0.07);
        }
      }
      if (T.missile) { // one missile seen from above, drawn across its whole block (each square shows its part)
        let x0 = x, y0 = y, x1 = x, y1 = y;
        while (at(x0 - 1, y) === "missile") x0--;
        while (at(x, y0 - 1) === "missile") y0--;
        while (at(x1 + 1, y) === "missile") x1++;
        while (at(x, y1 + 1) === "missile") y1++;
        const cx = (x0 + x1 + 1) / 2, cy = (y0 + y1 + 1) / 2, R = Math.min(x1 - x0 + 1, y1 - y0 + 1) / 2;
        const PX = X + (cx - x) * cp, PY = Y + (cy - y) * cp, r = (k) => R * k * cp;
        ctx.fillStyle = "#2b2f35"; // four fins
        for (let i = 0; i < 4; i++) { ctx.save(); ctx.translate(PX, PY); ctx.rotate(Math.PI / 4 + i * Math.PI / 2);
          ctx.beginPath(); ctx.moveTo(-r(0.12), 0); ctx.lineTo(r(0.12), 0); ctx.lineTo(r(0.05), r(0.98)); ctx.lineTo(-r(0.05), r(0.98)); ctx.fill(); ctx.restore(); }
        const body = ctx.createRadialGradient(PX - r(0.25), PY - r(0.25), r(0.05), PX, PY, r(0.72));
        body.addColorStop(0, "#f4f4f0"); body.addColorStop(1, "#9ea3a8");
        ctx.fillStyle = body; ctx.beginPath(); ctx.arc(PX, PY, r(0.7), 0, Math.PI * 2); ctx.fill();
        ctx.strokeStyle = "rgba(0,0,0,.35)"; ctx.lineWidth = cp * 0.04;
        for (const k of [0.7, 0.5]) { ctx.beginPath(); ctx.arc(PX, PY, r(k), 0, Math.PI * 2); ctx.stroke(); }
        ctx.fillStyle = "#c0392b"; ctx.beginPath(); ctx.arc(PX, PY, r(0.28), 0, Math.PI * 2); ctx.fill(); // the red nose cone
        ctx.fillStyle = "rgba(255,255,255,.55)"; ctx.beginPath(); ctx.arc(PX - r(0.09), PY - r(0.09), r(0.08), 0, Math.PI * 2); ctx.fill();
        ctx.fillStyle = "#1d1d1d"; ctx.font = "bold " + Math.round(r(0.16)) + "px monospace"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
        ctx.fillText("VOSS", PX, PY + r(0.6));
      }
      if (T.cables) {
        const cols = ["#151515", "#b33a2a", "#2a5fa8"];
        for (let i = 0; i < 3; i++) {
          ctx.strokeStyle = cols[i]; ctx.lineWidth = cp * 0.06; ctx.beginPath();
          const off = (i - 1) * 0.18 + (hv - 0.5) * 0.1;
          ctx.moveTo(X, Y + cp * (0.5 + off)); ctx.bezierCurveTo(X + cp * 0.35, Y + cp * (0.5 + off + 0.15), X + cp * 0.65, Y + cp * (0.5 + off - 0.15), X + cp, Y + cp * (0.5 + off));
          ctx.stroke();
        }
      }
      if (T.coolant) {
        ctx.shadowColor = "#5ff2e0"; ctx.shadowBlur = cp * 0.3;
        ctx.fillStyle = "rgba(80,230,210,.55)"; ctx.beginPath();
        ctx.ellipse(X + cp * 0.5, Y + cp * 0.5, cp * (0.32 + hv * 0.12), cp * (0.24 + hv * 0.1), hv * 3, 0, Math.PI * 2); ctx.fill();
        ctx.shadowBlur = 0; dot(0.3 + hv * 0.2, 0.25, 0.07, "rgba(80,230,210,.5)"); dot(0.78, 0.72, 0.05, "rgba(80,230,210,.45)");
      }
      if (T.silodoor) {
        const horiz = at(x - 1, y) === "concretewall" || at(x + 1, y) === "concretewall" || at(x - 1, y) === "beacon" || at(x + 1, y) === "pipes"; // set in a wall running left-right
        ctx.save(); ctx.translate(X + cp / 2, Y + cp / 2); if (!horiz) ctx.rotate(Math.PI / 2); ctx.translate(-cp / 2, -cp / 2);
        ctx.fillStyle = "#6e6c66"; ctx.fillRect(0, cp * 0.2, cp, cp * 0.6);
        ctx.fillStyle = "#e0a822"; ctx.fillRect(0, cp * 0.2, cp, cp * 0.1); ctx.fillRect(0, cp * 0.7, cp, cp * 0.1);
        ctx.fillStyle = "#1a1a1a"; for (let i = 0; i < 5; i++) { ctx.fillRect(i * cp / 5, cp * 0.2, cp / 10, cp * 0.1); ctx.fillRect(i * cp / 5 + cp / 10, cp * 0.7, cp / 10, cp * 0.1); }
        ctx.fillStyle = "rgba(0,0,0,.5)"; ctx.fillRect(cp * 0.48, cp * 0.3, cp * 0.04, cp * 0.4);
        ctx.restore();
        dot(0.5, 0.5, 0.11, "#3a3936"); dot(0.5, 0.5, 0.05, "#9a978f");
      }
      if (T.lift) {
        ctx.fillStyle = "#5a5e63"; ctx.fillRect(X + cp * 0.06, Y + cp * 0.06, cp * 0.88, cp * 0.88);
        ctx.strokeStyle = "#e0a822"; ctx.lineWidth = cp * 0.06; ctx.strokeRect(X + cp * 0.09, Y + cp * 0.09, cp * 0.82, cp * 0.82);
        ctx.fillStyle = T.escape ? "#ff9f1a" : "#d9dde2"; ctx.beginPath(); // an arrow: down for the freight lift, up for Steven's
        const up = T.escape ? -1 : 1;
        ctx.moveTo(X + cp * 0.3, Y + cp * (0.5 - 0.15 * up)); ctx.lineTo(X + cp * 0.7, Y + cp * (0.5 - 0.15 * up)); ctx.lineTo(X + cp * 0.5, Y + cp * (0.5 + 0.2 * up)); ctx.fill();
        if (T.escape) { ctx.shadowColor = "#ff3b30"; ctx.shadowBlur = cp * 0.4; dot(0.85, 0.15, 0.06, "#ff3b30"); ctx.shadowBlur = 0; }
      }
      if (T.pad) {
        ctx.strokeStyle = "#e0e3e7"; ctx.lineWidth = cp * 0.05; ctx.beginPath(); ctx.arc(X + cp / 2, Y + cp / 2, cp * 0.36, 0, Math.PI * 2); ctx.stroke();
        ctx.fillStyle = "#e0e3e7"; ctx.fillRect(X + cp * 0.36, Y + cp * 0.3, cp * 0.07, cp * 0.4); ctx.fillRect(X + cp * 0.57, Y + cp * 0.3, cp * 0.07, cp * 0.4); ctx.fillRect(X + cp * 0.36, Y + cp * 0.47, cp * 0.28, cp * 0.06);
      }
      if (T.cwall) { // cinder blocks, staggered, a different wear on each
        const g = ctx.createLinearGradient(X, Y, X, Y + cp); g.addColorStop(0, "rgba(255,255,255,.07)"); g.addColorStop(1, "rgba(0,0,0,.2)");
        ctx.fillStyle = g; ctx.fillRect(X, Y, cp, cp);
        ctx.strokeStyle = "rgba(0,0,0,.4)"; ctx.lineWidth = cp * 0.03; ctx.beginPath();
        ctx.moveTo(X, Y + cp * 0.5); ctx.lineTo(X + cp, Y + cp * 0.5);
        const o = y % 2 ? 0.25 : 0.75; ctx.moveTo(X + o * cp, Y); ctx.lineTo(X + o * cp, Y + cp * 0.5); ctx.moveTo(X + (1.25 - o) % 1 * cp, Y + cp * 0.5); ctx.lineTo(X + (1.25 - o) % 1 * cp, Y + cp);
        ctx.stroke();
        if (hv > 0.85) { ctx.fillStyle = "rgba(0,0,0,.25)"; ctx.fillRect(X + cp * 0.1, Y + cp * 0.55, cp * 0.3, cp * 0.15); } // a chipped block
        if (T.beacon) {
          dot(0.5, 0.5, 0.2, "#2a2926"); ctx.shadowColor = "#ffaa1e"; ctx.shadowBlur = cp * 0.5; dot(0.5, 0.5, 0.13, "#ffb030"); ctx.shadowBlur = 0;
          ctx.strokeStyle = "rgba(0,0,0,.5)"; ctx.lineWidth = cp * 0.02; ctx.beginPath(); ctx.moveTo(X + cp * 0.37, Y + cp * 0.5); ctx.lineTo(X + cp * 0.63, Y + cp * 0.5); ctx.stroke();
        }
      }
      if (T.pipes) { // three pipes with flanges, running along the wall
        const along = at(x - 1, y) === "pipes" || at(x + 1, y) === "pipes" || at(x, y - 1) === "missile" || at(x, y + 1) === "missile" ||
          !(at(x, y - 1) === "pipes" || at(x, y + 1) === "pipes");
        ctx.save(); ctx.translate(X + cp / 2, Y + cp / 2); if (!along) ctx.rotate(Math.PI / 2); ctx.translate(-cp / 2, -cp / 2);
        [["#8a8f96", 0.22], ["#a84a32", 0.5], ["#4c7a4a", 0.78]].forEach(([c, yy]) => {
          ctx.fillStyle = c; ctx.fillRect(0, cp * (yy - 0.09), cp, cp * 0.18);
          ctx.fillStyle = "rgba(255,255,255,.25)"; ctx.fillRect(0, cp * (yy - 0.07), cp, cp * 0.04);
          ctx.fillStyle = "rgba(0,0,0,.4)"; ctx.fillRect(cp * (0.3 + hv * 0.3), cp * (yy - 0.12), cp * 0.07, cp * 0.24);
        });
        ctx.restore();
      }
      if (T.tank) {
        ctx.shadowColor = "rgba(0,0,0,.5)"; ctx.shadowBlur = cp * 0.12;
        dot(0.5, 0.5, 0.44, "#b9bcbf"); ctx.shadowBlur = 0;
        ctx.strokeStyle = "#6c7075"; ctx.lineWidth = cp * 0.04; ctx.beginPath(); ctx.arc(X + cp / 2, Y + cp / 2, cp * 0.33, 0, Math.PI * 2); ctx.stroke();
        ctx.fillStyle = "#d23b2b"; ctx.save(); ctx.translate(X + cp / 2, Y + cp / 2); ctx.rotate(Math.PI / 4); ctx.fillRect(-cp * 0.12, -cp * 0.12, cp * 0.24, cp * 0.24); ctx.restore();
        ctx.fillStyle = "#fff"; ctx.font = "bold " + Math.round(cp * 0.16) + "px sans-serif"; ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillText("!", X + cp / 2, Y + cp / 2);
      }
      if (T.reactor) {
        const g = ctx.createRadialGradient(X + cp / 2, Y + cp / 2, cp * 0.05, X + cp / 2, Y + cp / 2, cp * 0.5);
        g.addColorStop(0, "#d6fff4"); g.addColorStop(0.35, "#38e0b0"); g.addColorStop(1, "rgba(20,60,50,0)");
        ctx.fillStyle = g; ctx.fillRect(X, Y, cp, cp);
        ctx.strokeStyle = "#6a7078"; ctx.lineWidth = cp * 0.06; ctx.beginPath(); ctx.arc(X + cp / 2, Y + cp / 2, cp * 0.38, 0, Math.PI * 2); ctx.stroke();
        for (let i = 0; i < 4; i++) { const a = i * Math.PI / 2 + Math.PI / 4; dot(0.5 + Math.cos(a) * 0.38, 0.5 + Math.sin(a) * 0.38, 0.06, "#3a3f45"); }
      }
      if (T.console) {
        rr(0.08, 0.2, 0.84, 0.62, 0.06, "#33373c", "rgba(0,0,0,.6)");
        rr(0.16, 0.27, 0.68, 0.24, 0.03, "#0e1a14");
        ctx.fillStyle = "rgba(110,255,150,.8)"; for (let i = 0; i < 2; i++) ctx.fillRect(X + cp * 0.2, Y + cp * (0.31 + i * 0.09), cp * (0.25 + hash(x + i, y) * 0.3), cp * 0.04);
        dot(0.28, 0.66, 0.06, "#e0a822"); dot(0.45, 0.66, 0.06, "#4a90d9"); dot(0.7, 0.65, 0.09, "#d23b2b");
      }
      if (T.bunk) {
        rr(0.1, 0.08, 0.8, 0.84, 0.05, "#55604a", "rgba(0,0,0,.5)");
        rr(0.18, 0.13, 0.64, 0.18, 0.05, "#e6e2d6");
        ctx.fillStyle = "#6c7a5c"; ctx.fillRect(X + cp * 0.12, Y + cp * 0.45, cp * 0.76, cp * 0.45);
        ctx.strokeStyle = "rgba(0,0,0,.3)"; ctx.lineWidth = cp * 0.025; ctx.beginPath(); ctx.moveTo(X + cp * 0.12, Y + cp * 0.6); ctx.lineTo(X + cp * 0.88, Y + cp * 0.6); ctx.stroke();
      }
      if (T.rack) {
        rr(0.06, 0.12, 0.88, 0.76, 0.03, "#2f3236", "rgba(0,0,0,.6)");
        ctx.strokeStyle = "#15171a"; ctx.lineWidth = cp * 0.06; ctx.beginPath();
        for (let i = 0; i < 3; i++) { const a = X + cp * (0.24 + i * 0.26); ctx.moveTo(a, Y + cp * 0.2); ctx.lineTo(a, Y + cp * 0.8); }
        ctx.stroke();
        ctx.fillStyle = "#6b4a2c"; for (let i = 0; i < 3; i++) ctx.fillRect(X + cp * (0.2 + i * 0.26), Y + cp * 0.62, cp * 0.08, cp * 0.16); // stocks
      }
      if (T.crate) {
        const two = hv > 0.5, draw1 = (a, b, s, c) => {
          rr(a, b, s, s, 0.03, c, "rgba(0,0,0,.6)");
          ctx.strokeStyle = "rgba(0,0,0,.35)"; ctx.lineWidth = cp * 0.03; ctx.beginPath();
          ctx.moveTo(X + a * cp, Y + b * cp); ctx.lineTo(X + (a + s) * cp, Y + (b + s) * cp); ctx.moveTo(X + (a + s) * cp, Y + b * cp); ctx.lineTo(X + a * cp, Y + (b + s) * cp); ctx.stroke();
          ctx.fillStyle = "rgba(240,200,90,.6)"; ctx.fillRect(X + (a + 0.05) * cp, Y + (b + 0.05) * cp, s * 0.3 * cp, cp * 0.05);
        };
        ctx.shadowColor = "rgba(0,0,0,.45)"; ctx.shadowBlur = cp * 0.1;
        if (two) { draw1(0.06, 0.08, 0.5, "#5b6440"); draw1(0.44, 0.42, 0.5, "#6a5a3a"); }
        else draw1(0.12, 0.12, 0.76, hv < 0.25 ? "#5b6440" : "#6a5a3a");
        ctx.shadowBlur = 0;
      }
    }
    /* Red emergency light spilling onto the floor around each alarm lamp (drawn with the map: no extra animation loop). */
    drawAlarmGlow(cp, ox, oy, box) {
      const ctx = this.ctx;
      ctx.save();
      for (const [k, v] of Object.entries(this.map.terrain || {})) {
        if (v !== "redlight" && v !== "beacon") continue;
        const [x, y] = k.split(",").map(Number), X = ox + (x + 0.5) * cp, Y = oy + (y + 0.5) * cp;
        if (box && (x < box[0] - 3 || x > box[2] + 3 || y < box[1] - 3 || y > box[3] + 3)) continue;
        const g = ctx.createRadialGradient(X, Y, cp * 0.1, X, Y, cp * 2.6), c = v === "beacon" ? "255,170,30" : "255,40,30";
        g.addColorStop(0, "rgba(" + c + ",.28)"); g.addColorStop(1, "rgba(" + c + ",0)");
        ctx.fillStyle = g; ctx.fillRect(X - cp * 2.6, Y - cp * 2.6, cp * 5.2, cp * 5.2);
      }
      ctx.restore();
    }
    /* Chests: futuristic containers, each kind with its own colours and marks. The light on the lid is red
       when it's locked, green when it isn't; an opened one has its lid up, dark inside, light off. */
    drawChests(cp, ox, oy, which) {
      const list = (this.map && this.map.chests) || [], ctx = this.ctx, now = performance.now();
      for (const c of list) {
        const moving = !!(this.chestAnim && this.chestAnim.has(c.id));
        if ((which === "still" && moving) || (which === "moving" && !moving)) continue;
        if (c.kind === "papers") { this.drawPapers(c, cp, ox, oy); continue; }
        if (c.kind === "abort" || c.kind === "escape") { this.drawSiloControl(c, cp, ox, oy); continue; }
        const [body, stripe, light] = CHEST_LOOK[c.kind] || CHEST_LOOK.supply;
        const small = c.kind === "drop", big = c.kind === "legendary" || c.kind === "vault";
        const w = cp * (small ? 0.56 : big ? 0.86 : 0.76), hgt = cp * (small ? 0.38 : 0.5);
        const X = ox + c.x * cp + (cp - w) / 2, Y = oy + c.y * cp + cp * 0.32;
        const t0 = this.chestAnim && this.chestAnim.get(c.id), k = t0 ? Math.min(1, (now - t0) / 700) : 1;
        if (t0 && k >= 1) { this.chestAnim.delete(c.id); this.layerDirty = true; } // done: back into the saved ground
        const open = c.opened ? k : 0, empty = c.opened && Array.isArray(c.loot) && !c.loot.length;
        ctx.save();
        if (c.hidden) ctx.globalAlpha = 0.5;
        if (empty) ctx.globalAlpha *= 0.6;
        ctx.shadowColor = "rgba(0,0,0,.5)"; ctx.shadowBlur = cp * 0.12; ctx.shadowOffsetY = cp * 0.05;
        ctx.fillStyle = body; ctx.fillRect(X, Y, w, hgt);
        ctx.shadowColor = "transparent";
        ctx.fillStyle = "rgba(0,0,0,.25)"; ctx.fillRect(X, Y + hgt * 0.72, w, hgt * 0.28);
        ctx.fillStyle = stripe; ctx.fillRect(X + w * 0.08, Y + hgt * 0.3, w * 0.84, hgt * 0.16);
        if (c.kind === "medical") ctx.fillRect(X + w * 0.44, Y + hgt * 0.12, w * 0.12, hgt * 0.56); // a red cross
        if (c.kind === "military" || c.kind === "supply") { ctx.fillStyle = "rgba(0,0,0,.4)"; for (let i = 0; i < 4; i++) ctx.fillRect(X + w * (0.12 + i * 0.22), Y + hgt * 0.3, w * 0.06, hgt * 0.16); }
        if (c.kind === "vault") { ctx.fillStyle = "#9aa3ad"; ctx.beginPath(); ctx.arc(X + w / 2, Y + hgt * 0.62, cp * 0.09, 0, Math.PI * 2); ctx.fill(); } // the dial
        if (c.kind === "experimental" || c.kind === "legendary") { // a glowing core
          ctx.fillStyle = light; ctx.shadowColor = light; ctx.shadowBlur = cp * (c.opened ? 0.15 : 0.45);
          ctx.beginPath(); ctx.arc(X + w / 2, Y + hgt * 0.62, cp * 0.08, 0, Math.PI * 2); ctx.fill(); ctx.shadowBlur = 0;
        }
        ctx.strokeStyle = "rgba(0,0,0,.55)"; ctx.lineWidth = cp * 0.03; ctx.strokeRect(X, Y, w, hgt);
        const lidH = hgt * 0.32, lift = open * hgt * 0.55;
        if (open > 0) { ctx.fillStyle = "#0d0f12"; ctx.fillRect(X + w * 0.06, Y - lidH * 0.2, w * 0.88, lidH * 0.6); }
        ctx.fillStyle = body; ctx.fillRect(X - cp * 0.02, Y - lidH - lift, w + cp * 0.04, lidH * (1 - open * 0.5));
        ctx.strokeStyle = "rgba(0,0,0,.6)"; ctx.strokeRect(X - cp * 0.02, Y - lidH - lift, w + cp * 0.04, lidH * (1 - open * 0.5));
        if (!c.opened) {
          const col = c.locked_by ? "#ff3b30" : "#5fdc7a";
          ctx.fillStyle = col; ctx.shadowColor = col; ctx.shadowBlur = cp * 0.25;
          ctx.beginPath(); ctx.arc(X + w * 0.86, Y - lidH * 0.5, cp * 0.05, 0, Math.PI * 2); ctx.fill(); ctx.shadowBlur = 0;
        } else if (t0 && k < 1) { // light bursting out as it opens
          const g = ctx.createRadialGradient(X + w / 2, Y, 0, X + w / 2, Y, cp * 1.2);
          g.addColorStop(0, "rgba(255,240,180," + (0.65 * (1 - k)).toFixed(3) + ")"); g.addColorStop(1, "rgba(255,240,180,0)");
          ctx.fillStyle = g; ctx.fillRect(X - cp, Y - cp * 1.2, w + cp * 2, cp * 2.4);
        }
        ctx.restore();
      }
    }
    /** The launch bay: an abort key on its pedestal (red until it's turned, then green), and Steven's
        lift lever (amber until someone reaches it). */
    drawSiloControl(c, cp, ox, oy) {
      const ctx = this.ctx, X = ox + c.x * cp, Y = oy + c.y * cp;
      ctx.save();
      if (c.hidden) ctx.globalAlpha = 0.5;
      ctx.shadowColor = "rgba(0,0,0,.5)"; ctx.shadowBlur = cp * 0.12;
      if (c.kind === "abort") {
        ctx.fillStyle = "#2f3236"; ctx.fillRect(X + cp * 0.16, Y + cp * 0.16, cp * 0.68, cp * 0.68); ctx.shadowBlur = 0;
        ctx.fillStyle = "#e0a822"; ctx.fillRect(X + cp * 0.16, Y + cp * 0.16, cp * 0.68, cp * 0.1);
        const col = c.opened ? "#5fdc7a" : "#ff3b30";
        ctx.fillStyle = col; ctx.shadowColor = col; ctx.shadowBlur = cp * 0.45;
        ctx.beginPath(); ctx.arc(X + cp * 0.5, Y + cp * 0.55, cp * 0.17, 0, Math.PI * 2); ctx.fill(); ctx.shadowBlur = 0;
        ctx.strokeStyle = "#e9ecef"; ctx.lineWidth = cp * 0.07; ctx.beginPath(); // the key, upright, or turned flat once it's done
        const a = c.opened ? 0 : -Math.PI / 2;
        ctx.moveTo(X + cp * 0.5, Y + cp * 0.55); ctx.lineTo(X + cp * (0.5 + Math.cos(a) * 0.2), Y + cp * (0.55 + Math.sin(a) * 0.2)); ctx.stroke();
      } else {
        ctx.fillStyle = "#3a3d42"; ctx.fillRect(X + cp * 0.3, Y + cp * 0.12, cp * 0.4, cp * 0.76); ctx.shadowBlur = 0;
        const col = c.opened ? "#7d8288" : "#ff9f1a";
        ctx.fillStyle = col; ctx.shadowColor = col; ctx.shadowBlur = c.opened ? 0 : cp * 0.4;
        ctx.fillRect(X + cp * 0.42, Y + cp * 0.22, cp * 0.16, cp * 0.3); ctx.shadowBlur = 0;
        ctx.strokeStyle = "#c9ced4"; ctx.lineWidth = cp * 0.06; ctx.beginPath();
        ctx.moveTo(X + cp * 0.5, Y + cp * 0.7); ctx.lineTo(X + cp * (c.opened ? 0.72 : 0.5), Y + cp * (c.opened ? 0.58 : 0.5)); ctx.stroke();
      }
      ctx.restore();
    }
    /** Loose papers: a few sheets scattered on the floor, read ones a little greyed. */
    drawPapers(c, cp, ox, oy) {
      const ctx = this.ctx, cx = ox + c.x * cp + cp / 2, cy = oy + c.y * cp + cp / 2;
      ctx.save();
      if (c.hidden) ctx.globalAlpha = 0.5;
      if (c.opened) ctx.globalAlpha *= 0.65;
      [[-0.14, -0.08, -0.35], [0.12, 0.06, 0.28], [0, 0.02, 0.05]].forEach(([dx, dy, rot], i) => {
        ctx.save();
        ctx.translate(cx + dx * cp, cy + dy * cp); ctx.rotate(rot + (hash(c.x + i, c.y) - 0.5) * 0.3);
        const w = cp * 0.38, hh = cp * 0.5;
        ctx.shadowColor = "rgba(0,0,0,.45)"; ctx.shadowBlur = cp * 0.08; ctx.shadowOffsetY = cp * 0.03;
        ctx.fillStyle = i === 2 ? "#f3ecd8" : "#ddd5bf"; ctx.fillRect(-w / 2, -hh / 2, w, hh);
        ctx.shadowColor = "transparent";
        ctx.fillStyle = "rgba(40,40,60,.55)";
        for (let k = 0; k < 4; k++) ctx.fillRect(-w * 0.36, -hh * 0.32 + k * hh * 0.17, w * (k === 3 ? 0.4 : 0.72), cp * 0.022);
        ctx.restore();
      });
      if (!c.opened) { // a faint glint so they're noticed
        ctx.fillStyle = "#ffe9a8"; ctx.shadowColor = "#ffe9a8"; ctx.shadowBlur = cp * 0.25;
        ctx.beginPath(); ctx.arc(cx + cp * 0.3, cy - cp * 0.28, cp * 0.04, 0, Math.PI * 2); ctx.fill();
      }
      ctx.restore();
    }
    chestAt(px, py) {
      const [cx, cy] = this.toCell(px, py), list = (this.map && this.map.chests) || [];
      return list.find((c) => Math.floor(cx) === c.x && Math.floor(cy) === c.y) || null;
    }
    /** A chest that just opened plays its lid animation (and sound) on every screen showing it. */
    noticeChests(prev, next) {
      if (!prev || prev.id !== next.id) return;
      const was = new Map((prev.chests || []).map((c) => [c.id, c]));
      this.chestAnim = this.chestAnim || new Map();
      for (const c of next.chests || []) {
        const p = was.get(c.id);
        if (p && !p.opened && c.opened) {
          this.chestAnim.set(c.id, performance.now());
          this.layerDirty = true;
          this.addFx({ type: "word", x: c.x + 0.5, y: c.y, text: "Opened!", color: "#ffd36b", ms: 1500 });
          if (window.FX) FX.sound("chest");
        } else if (!p && c.kind === "drop") {
          this.addFx({ type: "word", x: c.x + 0.5, y: c.y, text: "Loot!", color: "#e6eaee", ms: 1400 });
          if (window.FX) FX.sound("drop");
        }
      }
      if (this.chestAnim.size) this.addFx({ type: "chest", ms: 750 }); // keeps the animation loop running while the lid lifts
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
      const [gx, gy, lift] = this.shownAt(t);
      const x = dragging ? this.drag.at[0] : gx, y = dragging ? this.drag.at[1] : gy;
      const cx = ox + (x + t.size / 2) * cp, cy = oy + (y + t.size / 2) * cp, r = t.size * cp * 0.42 * (1 + (dragging ? 0 : lift) * 0.07);
      const color = t.color || KIND_COLOR[t.kind] || "#888";
      ctx.save();
      if (t.hidden || t.combatant_hidden) ctx.globalAlpha = 0.55;
      const winged = starWinged(t);
      if (winged) drawSteelWings(ctx, cx, cy, r);
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
      if (winged) drawChestStar(ctx, cx, cy + r * 0.5, r * 0.26);
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
          const [gx, gy] = this.shownAt(tok), X = ox + (gx + tok.size / 2) * cp, Y = oy + gy * cp - k * cp * 1.1;
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
          const [gx, gy] = this.shownAt(tok), X = ox + (gx + tok.size / 2) * cp, Y = oy + (gy + tok.size / 2) * cp, r = tok.size * cp * 0.42;
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
      if (f.style === "laser" && f.from && f.to) { // a beam, there at once, then fading; a miss goes wide
        const [fx, fy] = P(f.from), ex = miss ? tx + cp * 0.9 : tx, ey = miss ? ty - cp * 0.7 : ty, fade = k < 0.25 ? 1 : Math.max(0, (1 - k) / 0.75);
        ctx.globalAlpha = fade; ctx.lineCap = "round"; ctx.shadowColor = f.color; ctx.shadowBlur = cp * 0.6;
        ctx.strokeStyle = f.color; ctx.lineWidth = cp * 0.16 * big; ctx.beginPath(); ctx.moveTo(fx, fy); ctx.lineTo(ex, ey); ctx.stroke();
        ctx.strokeStyle = "#ffffff"; ctx.lineWidth = cp * 0.05 * big; ctx.beginPath(); ctx.moveTo(fx, fy); ctx.lineTo(ex, ey); ctx.stroke();
        if (!miss) { ctx.fillStyle = "#ffd0c8"; ctx.beginPath(); ctx.arc(tx, ty, cp * 0.3 * big * (1 - k * 0.5), 0, Math.PI * 2); ctx.fill(); }
        return;
      }
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
      if (!this.images[name]) { const img = new Image(); img.onload = () => this.draw(); img.src = "/api/uploads/" + name + "?w=128"; this.images[name] = img; }
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
          this.pingTap = null;
          const [a, b] = [...this.pointers.values()];
          this.drag = { pinch: true, d0: Math.hypot(a[0] - b[0], a[1] - b[1]), s0: this.view.s, mid: [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2], view0: { ...this.view } };
          this.preview.clear(); this.ruler = null; this.areaDraft = null;
          return;
        }
        // a quick second tap on a phone or tablet counts as a double-click (a ping), but only if the
        // finger lifts without moving: tap a token, then drag it, and it just moves
        const now = performance.now();
        this.pingTap = null;
        if (e.pointerType === "touch" && this.lastTap && now - this.lastTap.t < 320 && Math.hypot(p[0] - this.lastTap.p[0], p[1] - this.lastTap.p[1]) < 24 && this.tool !== "area" && this.tool !== "aim" && this.tool !== "place") {
          this.lastTap = null; this.pingTap = p;
        } else this.lastTap = { t: now, p };
        const tool = e.button === 1 || e.button === 2 ? "pan" : this.tool;
        if (tool === "select") {
          const t = this.tokenAt(...p);
          if (t) {
            this.selectedId = t.id;
            if (this.opts.onSelect) this.opts.onSelect(t);
            const canMove = this.opts.canMove ? this.opts.canMove(t) : true;
            if (canMove) { const [cx, cy] = this.toCell(...p); this.drag = { token: t, grab: [cx - t.x, cy - t.y], at: [t.x, t.y], moved: false }; this.draw(); return; }
          } else {
            const ch = this.opts.onChest ? this.chestAt(...p) : null; // a tap on a chest opens its panel (dragging still pans)
            if (ch) { this.opts.onChest(ch); this.drag = { pan: true, start: p, view0: { ...this.view } }; this.draw(); return; }
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
          // a line with a range (Steven Voss's steel wall): press where it starts, inside the ring, then drag to point it
          const anchor = s.kind === "line" && this.aim.range > 0;
          if (anchor) { const [x, y] = this.clampAim(Math.floor(cx) + 0.5, Math.floor(cy) + 0.5); s.x = x; s.y = y; }
          else if (s.kind === "cone" || s.kind === "line") this.pointAim(cx, cy); // it stays on the caster and turns to face the click
          else { const [x, y] = this.clampAim(...snapOrigin(s.kind, cx, cy, s.size, per)); s.x = x; s.y = y; }
          this.drag = { aim: true, anchor };
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
        if (this.pingTap && Math.hypot(p[0] - this.pingTap[0], p[1] - this.pingTap[1]) > 10) this.pingTap = null;
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
          if (d.anchor) { if (Math.hypot(cx - s.x, cy - s.y) > 0.3) s.dir = Math.round(Math.atan2(cy - s.y, cx - s.x) * 180 / Math.PI / 5) * 5; }
          else if (s.kind === "cone" || s.kind === "line") this.pointAim(cx, cy);
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
        const released = () => { if (this.opts.onDragEnd) setTimeout(() => this.opts.onDragEnd(), 0); }; // anything held back meanwhile can come through now
        if (d && d.pinch) { if (!this.pointers.size) { this.drag = null; released(); } return; }
        this.drag = null;
        released();
        const pingAt = this.pingTap; this.pingTap = null;
        if (pingAt && !(d && d.moved)) { if (d && d.pan) this.view = d.view0; this.preview.clear(); this.ruler = null; this.ping(...pingAt); this.draw(); return; }
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
