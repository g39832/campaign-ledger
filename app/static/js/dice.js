/* Dice: a small 3D polyhedron renderer on <canvas>, the rolling animation,
   and the dice dock (tray, controls, roll history).

   The server decides every result. The animation is built backwards from it:
   each die's final orientation is computed so the face carrying the saved
   value points at the viewer, and the tumble is a rotation that winds down to
   exactly that orientation. Skip and replay only re-draw a saved roll. */
(function () {
  "use strict";
  const { h, icon, $, $$, api, toast, uid, fmtTime, signed } = L;

  // ---- vector / quaternion helpers -----------------------------------------
  const V = {
    add: (a, b) => [a[0] + b[0], a[1] + b[1], a[2] + b[2]],
    sub: (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]],
    mul: (a, k) => [a[0] * k, a[1] * k, a[2] * k],
    dot: (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2],
    cross: (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]],
    len: (a) => Math.hypot(a[0], a[1], a[2]),
    norm: (a) => { const l = Math.hypot(a[0], a[1], a[2]) || 1; return [a[0] / l, a[1] / l, a[2] / l]; },
  };
  const Q = {
    axis: (ax, ang) => { const s = Math.sin(ang / 2), n = V.norm(ax); return [Math.cos(ang / 2), n[0] * s, n[1] * s, n[2] * s]; },
    mul: (a, b) => [
      a[0] * b[0] - a[1] * b[1] - a[2] * b[2] - a[3] * b[3],
      a[0] * b[1] + a[1] * b[0] + a[2] * b[3] - a[3] * b[2],
      a[0] * b[2] - a[1] * b[3] + a[2] * b[0] + a[3] * b[1],
      a[0] * b[3] + a[1] * b[2] - a[2] * b[1] + a[3] * b[0]],
    rot: (q, v) => {
      const [w, x, y, z] = q;
      const ix = w * v[0] + y * v[2] - z * v[1], iy = w * v[1] + z * v[0] - x * v[2];
      const iz = w * v[2] + x * v[1] - y * v[0], iw = -x * v[0] - y * v[1] - z * v[2];
      return [ix * w + iw * -x + iy * -z - iz * -y, iy * w + iw * -y + iz * -x - ix * -z, iz * w + iw * -z + ix * -y - iy * -x];
    },
    between: (a, b) => { // shortest rotation taking unit vector a onto b
      const d = V.dot(a, b);
      if (d > 0.999999) return [1, 0, 0, 0];
      if (d < -0.999999) { let p = V.cross([1, 0, 0], a); if (V.len(p) < 1e-6) p = V.cross([0, 1, 0], a); return Q.axis(p, Math.PI); }
      const c = V.cross(a, b);
      const q = [1 + d, c[0], c[1], c[2]], l = Math.hypot(...q);
      return q.map((x) => x / l);
    },
  };

  // ---- solids ----------------------------------------------------------------
  const PHI = (1 + Math.sqrt(5)) / 2;
  // Faces of a convex solid: every plane through three vertices that has all
  // other vertices on one side, with the coplanar vertices ordered around it.
  function hullFaces(verts) {
    const seen = new Set(), faces = [], n = verts.length;
    for (let i = 0; i < n; i++) for (let j = i + 1; j < n; j++) for (let k = j + 1; k < n; k++) {
      let nrm = V.cross(V.sub(verts[j], verts[i]), V.sub(verts[k], verts[i]));
      if (V.len(nrm) < 1e-9) continue;
      nrm = V.norm(nrm);
      const d = V.dot(nrm, verts[i]);
      let above = 0, below = 0;
      const on = [];
      verts.forEach((v, m) => { const t = V.dot(nrm, v) - d; if (t > 1e-6) above++; else if (t < -1e-6) below++; else on.push(m); });
      if (above && below) continue;
      const key = on.join(",");
      if (seen.has(key)) continue;
      seen.add(key);
      faces.push(orderAround(verts, on, above ? V.mul(nrm, -1) : nrm));
    }
    return faces;
  }
  function orderAround(verts, idx, n) {
    const c = V.mul(idx.reduce((s, i) => V.add(s, verts[i]), [0, 0, 0]), 1 / idx.length);
    const ref = V.norm(V.sub(verts[idx[0]], c)), ref2 = V.cross(n, ref);
    return idx.map((i) => { const d = V.sub(verts[i], c); return [Math.atan2(V.dot(d, ref2), V.dot(d, ref)), i]; })
      .sort((a, b) => a[0] - b[0]).map(([, i]) => i);
  }
  function signs(vals) { // all sign combinations of a template like [1, 1, 1]
    let out = [[]];
    for (const v of vals) out = out.flatMap((p) => (v === 0 ? [[...p, 0]] : [[...p, v], [...p, -v]]));
    return out;
  }
  function build(sides) {
    let verts, faces;
    if (sides === 4) {
      verts = [[1, 1, 1], [1, -1, -1], [-1, 1, -1], [-1, -1, 1]];
    } else if (sides === 6) {
      verts = signs([1, 1, 1]);
    } else if (sides === 8) {
      verts = [[1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0], [0, 0, 1], [0, 0, -1]];
    } else if (sides === 20) {
      verts = [...signs([0, 1, PHI]), ...signs([1, PHI, 0]), ...signs([PHI, 0, 1])];
    } else if (sides === 12) {
      verts = [...signs([1, 1, 1]), ...signs([0, 1 / PHI, PHI]), ...signs([1 / PHI, PHI, 0]), ...signs([PHI, 0, 1 / PHI])];
    } else { // d10: pentagonal trapezohedron with planar kites
      const ring = (hgt) => Array.from({ length: 10 }, (_, i) => [Math.cos(i * Math.PI / 5), Math.sin(i * Math.PI / 5), i % 2 ? -hgt : hgt]);
      const off = (hgt) => { const r = ring(hgt), T = [0, 0, 1]; const n = V.cross(V.sub(r[0], T), V.sub(r[2], T)); return V.dot(n, V.sub(r[1], T)); };
      let lo = 0.001, hi = 0.9;
      for (let k = 0; k < 60; k++) { const mid = (lo + hi) / 2; (off(lo) * off(mid) <= 0) ? (hi = mid) : (lo = mid); }
      const r = ring((lo + hi) / 2);
      verts = [[0, 0, 1], [0, 0, -1], ...r];
      faces = [];
      for (let k = 0; k < 5; k++) {
        faces.push([0, 2 + 2 * k, 2 + ((2 * k + 1) % 10), 2 + ((2 * k + 2) % 10)]);
        faces.push([1, 2 + ((2 * k + 1) % 10), 2 + ((2 * k + 2) % 10), 2 + ((2 * k + 3) % 10)]);
      }
    }
    if (!faces) faces = hullFaces(verts);
    if (faces.length !== sides) throw new Error("d" + sides + " built with " + faces.length + " faces");
    const rmax = Math.max(...verts.map(V.len));
    verts = verts.map((v) => V.mul(v, 1 / rmax));
    const F = faces.map((idx) => {
      const c = V.mul(idx.reduce((s, i) => V.add(s, verts[i]), [0, 0, 0]), 1 / idx.length);
      let n = V.norm(V.cross(V.sub(verts[idx[1]], verts[idx[0]]), V.sub(verts[idx[2]], verts[idx[0]])));
      if (V.dot(n, c) < 0) { n = V.mul(n, -1); idx = idx.slice().reverse(); }
      // Label "up" points at a vertex for triangles/kites, at an edge midpoint otherwise.
      let up;
      if (sides === 10) up = V.norm(V.sub(verts[idx[0]], c));
      else if (idx.length === 3) up = V.norm(V.sub(verts[idx[0]], c));
      else up = V.norm(V.sub(V.mul(V.add(verts[idx[0]], verts[idx[1]]), 0.5), c));
      const inr = Math.min(...idx.map((i, k) => { // inradius-ish: distance from centre to nearest edge
        const a = verts[i], b = verts[idx[(k + 1) % idx.length]];
        const ab = V.sub(b, a), t = Math.max(0, Math.min(1, V.dot(V.sub(c, a), ab) / V.dot(ab, ab)));
        return V.len(V.sub(c, V.add(a, V.mul(ab, t))));
      }));
      return { idx, n, c, up, inr };
    });
    // Number faces so opposite faces add up to sides + 1, like real dice.
    const labels = new Array(F.length).fill(0);
    let next = 1;
    F.forEach((f, i) => {
      if (labels[i]) return;
      labels[i] = next;
      const opp = F.findIndex((g, j) => j !== i && !labels[j] && V.dot(g.n, f.n) < -0.99);
      if (opp >= 0) labels[opp] = sides + 1 - next;
      next++;
      while (labels.includes(next)) next++;
    });
    F.forEach((f, i) => { f.value = labels[i]; });
    return { sides, verts, faces: F };
  }
  const SOLIDS = {};
  [4, 6, 8, 10, 12, 20].forEach((s) => { SOLIDS[s] = build(s); });

  const STYLE = {
    4: { body: "#b98f45", ink: "#1d140a" }, 6: { body: "#e8dcc2", ink: "#231a12" }, 8: { body: "#4d6c8c", ink: "#f3ead6" },
    10: { body: "#3f6a4b", ink: "#f3ead6" }, 12: { body: "#6a4766", ink: "#f3ead6" }, 20: { body: "#a5382a", ink: "#fbf1de" },
    pct: { body: "#2c2621", ink: "#f0e4cc" },
  };
  const SIZE_K = { 4: 1.08, 6: 0.9, 8: 1, 10: 1, 12: 1, 20: 1.04 };

  function shade(hex, k) {
    const n = parseInt(hex.slice(1), 16);
    const f = (c) => Math.max(0, Math.min(255, Math.round(c * k)));
    return `rgb(${f(n >> 16)},${f((n >> 8) & 255)},${f(n & 255)})`;
  }

  // Each displayed die: which solid, which face must end on top, and how it is labelled.
  function diceFromRoll(roll) {
    const out = [];
    for (const t of roll.result.terms) {
      if (t.type !== "dice") continue;
      t.rolls.forEach((r) => {
        if (t.sides === 100) {
          const tens = Math.floor((r.value % 100) / 10), units = r.value % 10;
          out.push({ sides: 10, face: tens === 0 ? 10 : tens, text: (f) => String((f % 10) * 10).padStart(2, "0"), shown: String(tens * 10).padStart(2, "0"), kept: r.kept, style: "pct", value: r.value, group: 100 });
          out.push({ sides: 10, face: units === 0 ? 10 : units, text: (f) => String(f % 10), shown: String(units), kept: r.kept, style: 10, value: r.value, group: 100 });
        } else if ([4, 6, 8, 10, 12, 20].includes(t.sides)) {
          out.push({ sides: t.sides, face: r.value, text: (f) => String(f), shown: String(r.value), kept: r.kept, style: t.sides, value: r.value });
        } else { // d2/d3: shown on a d6 with the number painted on
          out.push({ sides: 6, face: r.value, text: (f) => (f <= t.sides ? String(f) : String(((f - 1) % t.sides) + 1)), shown: String(r.value), kept: r.kept, style: 6, value: r.value });
        }
      });
    }
    return out;
  }

  // ---- the tray: animation + drawing ------------------------------------------
  class Tray {
    constructor(canvas) {
      this.canvas = canvas;
      this.ctx = canvas.getContext("2d");
      this.dice = [];
      this.raf = null;
      this.lastSettled = [];
      this.resize();
      window.addEventListener("resize", () => { this.resize(); this.draw(); });
    }
    resize() {
      const r = this.canvas.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
      this.w = Math.max(1, r.width); this.h = Math.max(1, r.height);
      this.canvas.width = Math.round(this.w * dpr); this.canvas.height = Math.round(this.h * dpr);
      this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }
    /* specs from diceFromRoll(); opts.duration in ms (0 = no motion). */
    play(specs, opts) {
      opts = opts || {};
      this.resize();
      cancelAnimationFrame(this.raf);
      if (this._resolve) { const prev = this._resolve; this._resolve = null; prev(null); }
      const n = specs.length;
      const R = Math.max(14, Math.min(opts.size || 40, (this.w / Math.max(2.5, n + 0.6)) * 0.42, this.h * 0.24));
      const cols = Math.max(1, Math.min(n, Math.floor((this.w - R) / (R * 2.5)) || 1));
      const rowsN = Math.ceil(n / cols);
      const fromLeft = Math.random() < 0.5;
      this.dice = specs.map((s, i) => {
        const col = i % cols, row = Math.floor(i / cols);
        const spanX = this.w / cols, spanY = Math.min(R * 2.6, (this.h - R) / rowsN);
        const end = [spanX * (col + 0.5) + (Math.random() - 0.5) * spanX * 0.25,
          this.h / 2 + (row - (rowsN - 1) / 2) * spanY + (Math.random() - 0.5) * R * 0.5];
        const start = [fromLeft ? -R * (1.5 + Math.random() * 2) : this.w + R * (1.5 + Math.random() * 2),
          this.h * (0.15 + Math.random() * 0.7)];
        const ctrl = [(start[0] + end[0]) / 2 + (Math.random() - 0.5) * this.w * 0.2, (start[1] + end[1]) / 2 + (Math.random() - 0.5) * this.h * 0.8];
        const solid = SOLIDS[s.sides];
        const face = solid.faces.find((f) => f.value === s.face);
        // Final orientation: result face toward the viewer (+z), its label upright.
        const qa = Q.between(face.n, [0, 0, 1]);
        const up = Q.rot(qa, face.up);
        const yaw = Math.PI / 2 - Math.atan2(up[1], up[0]) + (Math.random() - 0.5) * 0.5;
        // A slight resting tilt shows the sides so the die reads as solid; 0.25 rad is well
        // under half the angle between neighbouring faces on every die, so the result stays on top.
        const tiltAxis = [Math.cos(i * 2.4 + 0.7), Math.sin(i * 2.4 + 0.7), 0];
        const qFinal = Q.mul(Q.axis(tiltAxis, 0.25), Q.mul(Q.axis([0, 0, 1], yaw), qa));
        // Roll about the horizontal axis perpendicular to travel (screen y is flipped in model space).
        const dir = [end[0] - start[0], -(end[1] - start[1])];
        const dist = Math.hypot(dir[0], dir[1]) * 1.15;
        return {
          s, solid, start, ctrl, end, qFinal, R: R * (SIZE_K[s.sides] || 1),
          axis: V.norm([-dir[1], dir[0], 0.25 * (Math.random() - 0.5)]),
          roll: dist / (R * 0.9), spin: (Math.random() - 0.5) * 6, delay: i * 40 + Math.random() * 60,
          bounces: 2.6 + Math.random() * 1.2, height: R * (2 + Math.random()),
        };
      });
      this.duration = opts.duration ?? 1500;
      this.t0 = performance.now();
      return new Promise((resolve) => {
        this._resolve = resolve;
        if (!this.duration) { this.finish(); return; }
        const step = (now) => {
          const done = this.draw(now - this.t0);
          if (done) this.finish(); else this.raf = requestAnimationFrame(step);
        };
        this.raf = requestAnimationFrame(step);
      });
    }
    skip() { if (this._resolve) { cancelAnimationFrame(this.raf); this.finish(); } }
    finish() {
      cancelAnimationFrame(this.raf);
      this.draw(Infinity);
      // Read back which face actually ended on top — this is what the user sees.
      this.lastSettled = this.dice.map((d) => {
        const q = this.orient(d, 1);
        let best = null, bz = -2;
        d.solid.faces.forEach((f) => { const z = Q.rot(q, f.n)[2]; if (z > bz) { bz = z; best = f; } });
        return { sides: d.s.sides, expected: d.s.shown, shown: d.s.text(best.value), value: d.s.value };
      });
      const r = this._resolve; this._resolve = null;
      if (r) r(this.lastSettled);
    }
    orient(d, p) {
      const left = 1 - p;
      const qRoll = Q.axis(d.axis, -d.roll * Math.pow(left, 2.2));
      const qSpin = Q.axis([0, 0, 1], d.spin * left * left);
      return Q.mul(qSpin, Q.mul(qRoll, d.qFinal));
    }
    place(d, p) {
      const e = 1 - Math.pow(1 - p, 2.4);
      const a = (1 - e) * (1 - e), b = 2 * (1 - e) * e, c = e * e;
      const x = a * d.start[0] + b * d.ctrl[0] + c * d.end[0];
      const y = a * d.start[1] + b * d.ctrl[1] + c * d.end[1];
      const z = p >= 1 ? 0 : d.height * Math.pow(1 - p, 1.6) * Math.abs(Math.sin(Math.PI * d.bounces * p));
      return [x, y, z];
    }
    draw(elapsed) {
      const ctx = this.ctx;
      ctx.clearRect(0, 0, this.w, this.h);
      let done = true;
      const items = this.dice.map((d) => {
        const p = elapsed === Infinity ? 1 : Math.max(0, Math.min(1, (elapsed - d.delay) / this.duration));
        if (p < 1) done = false;
        return { d, p, pos: this.place(d, p) };
      }).sort((a, b) => a.pos[2] - b.pos[2]);
      for (const { d, p, pos } of items) {
        const [x, y, z] = pos;
        // shadow on the felt
        ctx.save();
        ctx.globalAlpha = 0.28 * (1 - Math.min(0.8, z / (d.R * 4)));
        ctx.fillStyle = "#000";
        ctx.beginPath();
        ctx.ellipse(x + z * 0.25, y + d.R * 0.55 + z * 0.15, d.R * (0.95 - z / (d.R * 12)), d.R * 0.42, 0, 0, Math.PI * 2);
        ctx.fill();
        ctx.restore();
        const dim = p >= 1 && !d.s.kept;
        this.drawDie(d, this.orient(d, p), x, y - z * 0.55, d.R * (1 + z / (d.R * 9)), dim);
      }
      return done;
    }
    drawDie(d, q, cx, cy, s, dim) {
      const ctx = this.ctx, st = STYLE[d.s.style];
      const L0 = V.norm([-0.45, 0.55, 0.8]);
      const rv = d.solid.verts.map((v) => Q.rot(q, v));
      const faces = d.solid.faces.map((f) => ({ f, n: Q.rot(q, f.n), c: Q.rot(q, f.c) }))
        .filter((x) => x.n[2] > 0.0001).sort((a, b) => a.c[2] - b.c[2]);
      ctx.save();
      if (dim) ctx.globalAlpha = 0.38;
      ctx.lineJoin = "round";
      for (const { f, n, c } of faces) {
        ctx.beginPath();
        f.idx.forEach((i, k) => { const v = rv[i]; const px = cx + s * v[0], py = cy - s * v[1]; k ? ctx.lineTo(px, py) : ctx.moveTo(px, py); });
        ctx.closePath();
        const light = 0.55 + 0.6 * Math.max(0, V.dot(n, L0));
        ctx.fillStyle = shade(st.body, light);
        ctx.fill();
        ctx.strokeStyle = shade(st.body, 0.45);
        ctx.lineWidth = Math.max(1, s * 0.035);
        ctx.stroke();
        // number, drawn in the face's own plane so it foreshortens with it
        if (n[2] > 0.25) {
          const up = Q.rot(q, f.up), right = V.cross(up, n);
          const k = f.inr * s * (d.solid.faces.length >= 12 ? 1.05 : 0.95);
          ctx.save();
          const dpr = window.devicePixelRatio || 1;
          ctx.setTransform(dpr * right[0] * k / 20, -dpr * right[1] * k / 20, -dpr * up[0] * k / 20, dpr * up[1] * k / 20,
            dpr * (cx + s * c[0]), dpr * (cy - s * c[1]));
          ctx.fillStyle = st.ink;
          ctx.globalAlpha = (dim ? 0.38 : 1) * Math.min(1, (n[2] - 0.25) * 3);
          ctx.font = "700 22px 'Alegreya Sans', sans-serif";
          ctx.textAlign = "center";
          ctx.textBaseline = "middle";
          const label = d.s.text(f.value);
          ctx.fillText(label, 0, 1);
          if (label === "6" || label === "9") ctx.fillRect(-7, 11, 14, 2.2); // underline to tell 6 from 9
          ctx.restore();
        }
      }
      ctx.restore();
    }
  }

  // ---- dock: controls, history, integration --------------------------------------
  const prefsKey = "dice-prefs";
  let prefs = { speed: "normal", visibility: "public", overMap: true };
  try { Object.assign(prefs, JSON.parse(localStorage.getItem(prefsKey) || "{}")); } catch (e) { /* storage unavailable */ }
  const reduceMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (reduceMotion && !localStorage.getItem(prefsKey)) prefs.speed = "none";
  const savePrefs = () => { try { localStorage.setItem(prefsKey, JSON.stringify(prefs)); } catch (e) { /* ignore */ } };
  const DURATION = { fast: 650, normal: 1500, dramatic: 2600, none: 0 };

  const role = document.body.dataset.role || "dm";
  const Dice = {
    tray: null, mode: "normal", history: [], lastId: 0, current: null, actions: null, overlayHost: null,
    playing: false, queue: [],

    init() {
      this.dock = $("#dice-dock");
      if (!this.dock) return;
      this.tray = new Tray($("#dice-canvas"));
      this.drama = new Tray($("#dice-drama-canvas"));
      this.bindControls();
      this.loadHistory();
      setInterval(() => this.poll(), 3000);
      document.addEventListener("keydown", (e) => {
        const t = e.target;
        if (e.ctrlKey || e.metaKey || e.altKey || (t && /INPUT|TEXTAREA|SELECT/.test(t.tagName))) return;
        if (e.key === "d" || e.key === "D") { e.preventDefault(); this.toggle(); }
        if (e.key === "Escape" && this.isOpen()) this.toggle(false);
      });
      $$("[data-dice-open]").forEach((b) => b.addEventListener("click", () => this.toggle()));
    },
    isOpen() { return this.dock.classList.contains("is-open"); },
    toggle(force) {
      const open = force ?? !this.isOpen();
      this.dock.classList.toggle("is-open", open);
      $$("[data-dice-open]").forEach((b) => b.setAttribute("aria-expanded", open));
      if (open) { requestAnimationFrame(() => {
        this.tray.resize();
        if (!this.playing && this.current) this.tray.play(diceFromRoll(this.current), { duration: 0, size: 40 }); // show the last result at rest
        else this.tray.draw(Infinity);
      }); $("#dice-expr").focus({ preventScroll: true }); this.badge(0); }
    },
    badge(n) { $$(".dice-badge").forEach((b) => { b.hidden = !n; b.textContent = n; }); },

    bindControls() {
      const expr = $("#dice-expr");
      $$("[data-die]", this.dock).forEach((b) => b.addEventListener("click", (e) => {
        const die = "d" + b.dataset.die;
        if (e.shiftKey || !expr.value.trim()) { expr.value = "1" + die; }
        else {
          const re = new RegExp("(^|[+])(\\d+)" + die + "(?![0-9])");
          const m = expr.value.match(re);
          expr.value = m ? expr.value.replace(re, (all, pre, n) => pre + (Number(n) + 1) + die) : expr.value + "+1" + die;
        }
        expr.focus();
      }));
      $("#dice-form").addEventListener("submit", (e) => {
        e.preventDefault();
        const v = expr.value.trim();
        if (!v) { expr.focus(); return; }
        this.roll({ expression: v, label: "" });
      });
      $("#dice-clear").addEventListener("click", () => { expr.value = ""; expr.focus(); });
      $$("[data-mode]", this.dock).forEach((b) => b.addEventListener("click", () => this.setMode(b.dataset.mode)));
      const vis = $("#dice-vis"); vis.value = prefs.visibility;
      vis.addEventListener("change", () => { prefs.visibility = vis.value; savePrefs(); });
      const sp = $("#dice-speed"); sp.value = prefs.speed;
      sp.addEventListener("change", () => { prefs.speed = sp.value; savePrefs(); });
      const om = $("#dice-overmap");
      if (om) { om.checked = prefs.overMap; om.addEventListener("change", () => { prefs.overMap = om.checked; savePrefs(); }); }
      $("#dice-skip").addEventListener("click", () => this.skip());
      $("#dice-replay").addEventListener("click", () => { if (this.current) this.animate(this.current, { replay: true }); });
      $("#dice-close").addEventListener("click", () => this.toggle(false));
      $("#dice-drama").addEventListener("click", () => this.skip());
      this.setMode("normal");
    },
    setMode(m) {
      this.mode = m;
      $$("[data-mode]", this.dock).forEach((b) => { b.classList.toggle("is-on", b.dataset.mode === m); b.setAttribute("aria-pressed", b.dataset.mode === m); });
      $$(".dice-mode-flag").forEach((f) => { f.hidden = m === "normal"; f.textContent = m === "advantage" ? "ADV" : "DIS"; });
    },

    /* Roll on the server. req: {expression | check, label, kind, crit, encounter_id, apply_initiative}.
       Shift-click = advantage, Ctrl/Alt-click = disadvantage for that one roll. */
    roll(req, ev, opts) {
      opts = opts || {};
      let mode = this.mode;
      if (ev && ev.shiftKey) mode = "advantage";
      if (ev && (ev.ctrlKey || ev.altKey || ev.metaKey)) mode = "disadvantage";
      const body = Object.assign({ mode, visibility: prefs.visibility, op_id: uid() }, req);
      if (document.body.dataset.campaign) body.campaign_id = Number(document.body.dataset.campaign);
      if (!this.isOpen() && prefs.speed !== "dramatic" && !this.mapOverlayActive()) this.toggle(true);
      return new Promise((resolve) => {
        L.Save.push({
          run: () => api("POST", "/api/rolls", body),
          done: (d) => {
            this.addHistory([d.roll]);
            if (this.mode !== "normal" && !(ev && (ev.shiftKey || ev.ctrlKey || ev.altKey))) this.setMode("normal");
            const run = this.animate(d.roll);
            if (!opts.wait) { resolve(d.roll); return; }
            let done = false;
            const go = () => { if (!done) { done = true; resolve(d.roll); } };
            run.then(go);
            setTimeout(go, (DURATION[prefs.speed] || 0) + 1200); // never leave an attack hanging
          },
          fail: (err) => { toast(err.message, "error"); resolve(null); },
        });
      });
    },
    // a roll the server made (death saves, hit dice): add it to the history and roll it on screen
    show(roll) { if (!roll) return; this.addHistory([roll]); this.animate(roll); if (!this.isOpen() && prefs.speed !== "dramatic" && !this.mapOverlayActive()) this.toggle(true); },
    // every roll a spell made (attack, damage, each save): into the history, then rolled one after another
    async showAll(rolls) {
      rolls = (rolls || []).filter(Boolean);
      if (!rolls.length || !this.dock) return;
      this.addHistory(rolls);
      if (!this.isOpen() && prefs.speed !== "dramatic" && !this.mapOverlayActive()) this.toggle(true);
      for (const r of rolls) {
        await Promise.race([this.animate(r, { quiet: r !== rolls[0] && r.kind !== "attack" }), new Promise((ok) => setTimeout(ok, (DURATION[prefs.speed] || 0) + 1200))]);
      }
    },
    mapOverlayActive() { return !!(this.overlayHost && prefs.overMap); },
    animate(roll, opts) {
      opts = opts || {};
      this.current = roll;
      this.showResult(roll, true);
      const specs = diceFromRoll(roll);
      const speed = prefs.speed;
      let tray = this.tray;
      const drama = $("#dice-drama");
      drama.hidden = true;
      if (speed === "dramatic") { drama.hidden = false; tray = this.drama; }
      else if (this.mapOverlayActive()) { tray = this.overlayTray(); }
      this.activeTray = tray;
      this.playing = true;
      $("#dice-skip").disabled = false;
      const run = tray.play(specs, { duration: DURATION[speed], size: speed === "dramatic" ? 72 : (tray === this.tray ? 40 : 44) });
      if (window.FX && !opts.quiet) FX.sound("roll");
      run.then((settled) => {
        this.playing = false;
        $("#dice-skip").disabled = true;
        this.showResult(roll, false);
        const nat = roll.result && roll.result.natural;
        if (window.FX && !opts.quiet && (nat === 20 || nat === 1)) {
          const who = roll.subject ? roll.subject + " · " : "";
          if (nat === 20 && roll.kind === "attack") { FX.banner("CRITICAL HIT!", who + "Natural 20 · double damage dice!", "crit"); FX.burst(null, "crit", 90); FX.sound("crit"); }
          else if (nat === 20) { FX.banner("Natural 20!", who + (roll.label || "Critical"), "crit"); FX.burst(null, "crit"); FX.sound("crit"); }
          else { FX.banner("Natural 1…", who + (roll.label || "Fumble"), "fumble"); FX.burst(null, "fumble", 30); FX.sound("fumble"); }
        }
        if (window.FX && !opts.quiet && roll.kind === "damage" && /critical/i.test(roll.label || "")) {
          FX.banner(roll.total + " damage!", (roll.subject ? roll.subject + " · " : "") + "Critical hit — double dice", "crit");
          FX.burst(null, "crit", 60); FX.sound("crit");
        }
        this.dock.dataset.settled = JSON.stringify(settled);
        if (speed === "dramatic") setTimeout(() => { if (!this.playing) drama.hidden = true; }, 1400);
        if (tray !== this.tray) {
          this.tray.play(specs, { duration: 0 }); // keep the dock's tray in step with the result
          if (tray === this._overlay) setTimeout(() => { if (!this.playing) { tray.dice = []; tray.draw(Infinity); } }, 2500);
        }
      });
      return run;
    },
    skip() { if (this.activeTray) this.activeTray.skip(); $("#dice-drama").hidden = true; },
    overlayTray() {
      if (!this._overlay) {
        const c = h("canvas", { class: "dice-overlay", "aria-hidden": "true" });
        this.overlayHost.append(c);
        this._overlay = new Tray(c);
      }
      return this._overlay;
    },

    // ---- result + history ----
    describe(roll) {
      const parts = [];
      for (const t of roll.result.terms) {
        if (t.type === "mod") { parts.push(h("span", { class: "dr-mod" }, signed(t.value))); continue; }
        parts.push(h("span", { class: "dr-group" }, t.sign < 0 ? "− " : "", t.rolls.map((r) =>
          h("span", { class: "dr-die" + (r.kept ? "" : " is-dropped") + (t.sides === 20 && r.kept && (r.value === 20 || r.value === 1) ? " is-nat" : ""), title: "d" + t.sides }, r.value))));
      }
      return parts;
    },
    showResult(roll, pending) {
      const box = $("#dice-result");
      box.classList.toggle("is-pending", pending);
      box.replaceChildren(
        h("div", { class: "dr-head" }, h("span", { class: "dr-label" }, [roll.subject, roll.label].filter(Boolean).join(" — ") || "Roll"),
          h("span", { class: "dr-expr" }, roll.expression + (roll.mode !== "normal" ? " · " + roll.mode : ""))),
        h("div", { class: "dr-line" }, h("span", { class: "dr-dice" }, this.describe(roll)), h("span", { class: "dr-total", "aria-live": "polite" }, pending ? "…" : roll.total)),
        roll.outcome && !pending ? h("div", { class: "dr-outcome" }, roll.outcome) : null);
    },
    addHistory(rolls) {
      let added = false;
      for (const r of rolls) {
        if (this.history.some((x) => x.id === r.id)) continue;
        this.history.push(r); added = true;
        this.lastId = Math.max(this.lastId, r.id);
      }
      if (!added) return;
      this.history.sort((a, b) => b.id - a.id);
      this.history = this.history.slice(0, 80);
      this.renderHistory();
    },
    renderHistory() {
      const ul = $("#dice-history");
      const visLabel = { public: null, dm: role === "dm" ? "DM only" : "to DM", private: "private" };
      ul.replaceChildren(...(this.history.length ? this.history.map((r) => h("li", { class: r.id === (this.current && this.current.id) ? "is-on" : "" },
        h("button", { type: "button", class: "dh-main", title: "Show this roll again (no reroll)", onclick: () => this.animate(r, { replay: true }) },
          h("span", { class: "dh-who" }, r.roller_name + (r.subject && r.subject !== r.roller_name ? " · " + r.subject : ""),
            visLabel[r.visibility] ? h("span", { class: "tag", style: "margin-left:6px;font-size:.72rem;padding:1px 5px" }, visLabel[r.visibility]) : null),
          h("span", { class: "dh-label" }, r.label || r.expression),
          h("span", { class: "dh-dice" }, this.describe(r)),
          h("span", { class: "dh-total" }, r.total),
          h("span", { class: "dh-meta" }, (r.outcome ? r.outcome + " · " : "") + r.expression + " · " + fmtTime(r.created_at))),
        this.actions ? this.actions(r) : null)) : [h("li", { class: "faint", style: "padding:10px" }, "No rolls yet. Pick dice above or click any bonus on a character sheet.")]));
    },
    async loadHistory() {
      try {
        const d = await api("GET", "/api/rolls?limit=40" + (document.body.dataset.campaign ? "&campaign_id=" + document.body.dataset.campaign : ""));
        this.addHistory(d.rolls);
        if (!this.history.length) this.renderHistory();
        else this.showResult(this.history[0], false);
        if (this.history[0]) this.current = this.history[0];
      } catch (e) { /* the save indicator covers outages */ }
    },
    async poll() {
      if (document.hidden) return;
      try {
        const d = await api("GET", "/api/rolls?after_id=" + this.lastId + (document.body.dataset.campaign ? "&campaign_id=" + document.body.dataset.campaign : ""));
        const others = d.rolls.filter((r) => !r.mine && !this.history.some((x) => x.id === r.id));
        this.addHistory(d.rolls);
        if (others.length) {
          const newest = others.sort((a, b) => b.id - a.id)[0];
          if (this.isOpen() || this.mapOverlayActive()) { if (!this.playing) this.animate(newest); }
          else this.badge(others.length);
          toast(`${newest.roller_name} rolled ${newest.label || newest.expression}: ${newest.total}`, null, { ms: 3500 });
        }
      } catch (e) { /* ignore */ }
    },
  };

  window.Dice = Dice;
  window.DiceInternals = { SOLIDS, diceFromRoll, Tray, Q, V };
  document.addEventListener("DOMContentLoaded", () => Dice.init());
})();
