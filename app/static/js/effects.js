/* Table effects: hit and heal flashes, floating numbers, turn banners, crit
   bursts and little sounds. Purely for show — nothing here changes game data.
   Each device chooses its own settings (Settings → Effects & sounds). Sounds are
   made in the browser with the Web Audio API, so there are no files to download.
   Motion is toned down when the device asks for reduced motion. */
(function () {
  "use strict";
  const KEY = "cl-fx";
  const DEFAULTS = { effects: true, sounds: true, volume: 0.5 };
  let prefs = Object.assign({}, DEFAULTS);
  try { Object.assign(prefs, JSON.parse(localStorage.getItem(KEY) || "{}")); } catch (e) { /* storage unavailable */ }
  const calm = () => window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function save() { try { localStorage.setItem(KEY, JSON.stringify(prefs)); } catch (e) { /* ignore */ } }

  // ---- overlay for floating text, banners and particles -------------------------------
  let layer, canvas, ctx, parts = [], raf = 0;
  function ensureLayer() {
    if (layer) return;
    layer = document.createElement("div");
    layer.className = "fx-layer";
    layer.setAttribute("aria-hidden", "true");
    canvas = document.createElement("canvas");
    canvas.className = "fx-canvas";
    layer.append(canvas);
    document.body.append(layer);
    ctx = canvas.getContext("2d");
    const size = () => { const d = window.devicePixelRatio || 1; canvas.width = innerWidth * d; canvas.height = innerHeight * d; };
    size(); addEventListener("resize", size);
  }

  function centerOf(target) {
    if (!target) return [innerWidth / 2, innerHeight / 3];
    if (Array.isArray(target)) return target;
    const r = target.getBoundingClientRect();
    return [r.left + r.width / 2, r.top + Math.min(r.height / 2, 40)];
  }

  const KIND_CLASS = { dmg: "fx-dmg", heal: "fx-heal", crit: "fx-crit", fumble: "fx-fumble", info: "fx-info", temp: "fx-temp", down: "fx-down", ac: "fx-ac" };

  /** Floating number or word rising from an element (or [x, y] on screen). */
  function float(target, text, kind) {
    if (!prefs.effects) return;
    ensureLayer();
    const [x, y] = centerOf(target);
    const el = document.createElement("div");
    el.className = "fx-float " + (KIND_CLASS[kind] || "fx-info");
    el.textContent = text;
    el.style.left = x + "px"; el.style.top = y + "px";
    el.style.setProperty("--drift", (Math.random() * 40 - 20).toFixed(0) + "px");
    layer.append(el);
    setTimeout(() => el.remove(), 1600);
  }

  /** Flash an element: "hit" (red shake), "heal" (green glow), "turn", "down", "ac". */
  function flash(el, kind) {
    if (!prefs.effects || !el) return;
    const cls = "fx-flash-" + kind;
    el.classList.remove(cls); void el.offsetWidth; el.classList.add(cls);
    setTimeout(() => el.classList.remove(cls), 900);
  }

  /** Big banner across the top: turns, crits, start and end of combat. */
  let bannerTimer = 0;
  function banner(title, sub, kind) {
    if (!prefs.effects) return;
    ensureLayer();
    let el = layer.querySelector(".fx-banner");
    if (el) el.remove();
    el = document.createElement("div");
    el.className = "fx-banner " + (KIND_CLASS[kind] || "fx-info");
    const t = document.createElement("div"); t.className = "fx-banner-title"; t.textContent = title;
    el.append(t);
    if (sub) { const s = document.createElement("div"); s.className = "fx-banner-sub"; s.textContent = sub; el.append(s); }
    layer.append(el);
    clearTimeout(bannerTimer);
    bannerTimer = setTimeout(() => { el.classList.add("is-out"); setTimeout(() => el.remove(), 400); }, kind === "crit" || kind === "fumble" ? 2200 : 1700);
  }

  /** Particle burst at an element or point. */
  const COLORS = { crit: ["#f3d58a", "#ffb347", "#fff4d0", "#e0714f"], heal: ["#9fdc7a", "#d7f5b8", "#7da05a"],
    dmg: ["#e0714f", "#ff9b7a", "#b2402e"], fumble: ["#8b8273", "#5a5048", "#b9ab92"], ping: ["#8fd3ff", "#f3d58a"] };
  function burst(target, kind, count) {
    if (!prefs.effects || calm()) return;
    ensureLayer();
    const [x, y] = centerOf(target), colors = COLORS[kind] || COLORS.crit;
    const n = count || (kind === "crit" ? 70 : 28);
    for (let i = 0; i < n; i++) {
      const a = Math.random() * Math.PI * 2, sp = (kind === "crit" ? 4 : 2.5) + Math.random() * 4;
      parts.push({ x, y, vx: Math.cos(a) * sp, vy: Math.sin(a) * sp - 2, life: 1, decay: 0.012 + Math.random() * 0.02,
        size: 2 + Math.random() * 4, color: colors[i % colors.length], spin: Math.random() * 6 });
    }
    if (!raf) raf = requestAnimationFrame(tick);
  }
  function tick() {
    const d = window.devicePixelRatio || 1;
    ctx.setTransform(d, 0, 0, d, 0, 0);
    ctx.clearRect(0, 0, innerWidth, innerHeight);
    parts = parts.filter((p) => p.life > 0);
    for (const p of parts) {
      p.x += p.vx; p.y += p.vy; p.vy += 0.12; p.vx *= 0.99; p.life -= p.decay; p.spin += 0.2;
      ctx.globalAlpha = Math.max(0, p.life);
      ctx.fillStyle = p.color;
      ctx.save(); ctx.translate(p.x, p.y); ctx.rotate(p.spin);
      ctx.fillRect(-p.size / 2, -p.size / 2, p.size, p.size * 0.6);
      ctx.restore();
    }
    ctx.globalAlpha = 1;
    raf = parts.length ? requestAnimationFrame(tick) : 0;
  }

  // ---- sounds (synthesised, no files) --------------------------------------------------
  let audio = null;
  function ac() {
    if (!audio) {
      const A = window.AudioContext || window.webkitAudioContext;
      if (!A) return null;
      audio = new A();
    }
    if (audio.state === "suspended") audio.resume();
    return audio;
  }
  // Browsers only allow sound after the person has clicked or tapped once.
  addEventListener("pointerdown", () => { if (prefs.sounds) ac(); }, { once: true, capture: true });

  function tone(a, { type = "sine", from = 440, to = from, dur = 0.15, vol = 0.3, delay = 0 }) {
    const t0 = a.currentTime + delay, o = a.createOscillator(), g = a.createGain();
    o.type = type; o.frequency.setValueAtTime(from, t0); o.frequency.exponentialRampToValueAtTime(Math.max(20, to), t0 + dur);
    g.gain.setValueAtTime(0.0001, t0); g.gain.exponentialRampToValueAtTime(vol * prefs.volume, t0 + 0.01);
    g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
    o.connect(g).connect(a.destination); o.start(t0); o.stop(t0 + dur + 0.05);
  }
  function noise(a, { dur = 0.12, vol = 0.25, freq = 900, delay = 0 }) {
    const t0 = a.currentTime + delay, len = Math.floor(a.sampleRate * dur), buf = a.createBuffer(1, len, a.sampleRate), data = buf.getChannelData(0);
    for (let i = 0; i < len; i++) data[i] = (Math.random() * 2 - 1) * (1 - i / len);
    const src = a.createBufferSource(), f = a.createBiquadFilter(), g = a.createGain();
    src.buffer = buf; f.type = "bandpass"; f.frequency.value = freq; g.gain.value = vol * prefs.volume;
    src.connect(f).connect(g).connect(a.destination); src.start(t0);
  }
  const SOUNDS = {
    hit: (a) => { noise(a, { dur: 0.14, vol: 0.5, freq: 700 }); tone(a, { type: "triangle", from: 180, to: 70, dur: 0.18, vol: 0.35 }); },
    heal: (a) => { [523, 659, 784].forEach((f, i) => tone(a, { type: "sine", from: f, dur: 0.35, vol: 0.18, delay: i * 0.07 })); },
    crit: (a) => { [392, 523, 659, 784, 1047].forEach((f, i) => tone(a, { type: "triangle", from: f, dur: 0.3, vol: 0.22, delay: i * 0.06 })); noise(a, { dur: 0.3, vol: 0.15, freq: 3000, delay: 0.2 }); },
    fumble: (a) => { tone(a, { type: "sawtooth", from: 220, to: 80, dur: 0.5, vol: 0.18 }); tone(a, { type: "sawtooth", from: 165, to: 60, dur: 0.6, vol: 0.12, delay: 0.1 }); },
    turn: (a) => { tone(a, { type: "sine", from: 660, dur: 0.12, vol: 0.18 }); tone(a, { type: "sine", from: 880, dur: 0.18, vol: 0.16, delay: 0.1 }); },
    yourturn: (a) => { [523, 784, 1047].forEach((f, i) => tone(a, { type: "triangle", from: f, dur: 0.22, vol: 0.22, delay: i * 0.09 })); },
    down: (a) => { tone(a, { type: "sine", from: 300, to: 60, dur: 0.8, vol: 0.3 }); noise(a, { dur: 0.3, vol: 0.2, freq: 300 }); },
    ping: (a) => { tone(a, { type: "sine", from: 1200, to: 900, dur: 0.25, vol: 0.15 }); },
    roll: (a) => { for (let i = 0; i < 4; i++) noise(a, { dur: 0.04, vol: 0.2, freq: 1800 + i * 300, delay: i * 0.05 }); },
    start: (a) => { [196, 262, 330].forEach((f, i) => tone(a, { type: "square", from: f, dur: 0.25, vol: 0.08, delay: i * 0.12 })); },
    ac: (a) => { tone(a, { type: "triangle", from: 440, to: 880, dur: 0.25, vol: 0.18 }); },
  };
  function sound(name) {
    if (!prefs.sounds || !SOUNDS[name]) return;
    const a = ac();
    if (!a || a.state !== "running") return;
    try { SOUNDS[name](a); } catch (e) { /* audio is a nicety */ }
  }

  window.FX = {
    float, flash, banner, burst, sound,
    get prefs() { return Object.assign({}, prefs); },
    set(k, v) { prefs[k] = v; save(); if (k === "sounds" && v) { ac(); sound("ping"); } },
  };
})();
