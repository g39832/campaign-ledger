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
    bossintro: (a) => { // war drums, then a low horn
      for (let i = 0; i < 3; i++) { tone(a, { type: "sine", from: 90, to: 45, dur: 0.35, vol: 0.45, delay: i * 0.28 }); noise(a, { dur: 0.12, vol: 0.3, freq: 160, delay: i * 0.28 }); }
      tone(a, { type: "sawtooth", from: 110, to: 104, dur: 1.4, vol: 0.14, delay: 0.85 }); tone(a, { type: "sawtooth", from: 165, to: 156, dur: 1.4, vol: 0.09, delay: 0.85 }); },
    victory: (a) => { [523, 659, 784, 1047, 784, 1047].forEach((f, i) => tone(a, { type: "triangle", from: f, dur: i === 5 ? 0.7 : 0.18, vol: 0.22, delay: i * 0.13 })); },
    quake: (a) => { // a deep rumble that rolls on, with rocks cracking over it
      tone(a, { type: "sawtooth", from: 55, to: 32, dur: 1.8, vol: 0.32 }); tone(a, { type: "triangle", from: 70, to: 40, dur: 1.4, vol: 0.3, delay: 0.05 });
      for (let i = 0; i < 6; i++) noise(a, { dur: 0.35, vol: 0.4, freq: 120 + i * 25, delay: i * 0.22 });
      for (let i = 0; i < 4; i++) noise(a, { dur: 0.06, vol: 0.3, freq: 1500 + i * 400, delay: 0.15 + i * 0.3 }); },
    ac: (a) => { tone(a, { type: "triangle", from: 440, to: 880, dur: 0.25, vol: 0.18 }); },
    chest: (a) => { // a seal hisses, the lid clunks up, a bright chime
      noise(a, { dur: 0.35, vol: 0.28, freq: 4200 }); tone(a, { type: "square", from: 120, to: 70, dur: 0.12, vol: 0.18, delay: 0.3 });
      [784, 1175, 1568].forEach((f, i) => tone(a, { type: "sine", from: f, dur: 0.3, vol: 0.14, delay: 0.42 + i * 0.07 })); },
    drop: (a) => { noise(a, { dur: 0.08, vol: 0.3, freq: 900 }); tone(a, { type: "triangle", from: 660, to: 880, dur: 0.15, vol: 0.14, delay: 0.08 }); },
    door: (a) => { tone(a, { type: "sine", from: 880, to: 1320, dur: 0.12, vol: 0.14 }); noise(a, { dur: 0.6, vol: 0.22, freq: 300, delay: 0.12 });
      tone(a, { type: "sawtooth", from: 70, to: 55, dur: 0.6, vol: 0.12, delay: 0.12 }); },
    denied: (a) => { tone(a, { type: "square", from: 220, dur: 0.12, vol: 0.12 }); tone(a, { type: "square", from: 180, dur: 0.18, vol: 0.12, delay: 0.14 }); },
    descend: (a) => { // footsteps going down, then a low hum
      for (let i = 0; i < 6; i++) { tone(a, { type: "sine", from: 260 - i * 28, dur: 0.12, vol: 0.2, delay: i * 0.16 }); noise(a, { dur: 0.05, vol: 0.18, freq: 500 - i * 50, delay: i * 0.16 }); }
      tone(a, { type: "triangle", from: 98, to: 82, dur: 1.2, vol: 0.2, delay: 1.0 }); },
    // Steven Voss's Hollow Star Heart
    shardrise: (a) => { tone(a, { type: "sine", from: 330, to: 990, dur: 1.4, vol: 0.12 }); tone(a, { type: "sine", from: 495, to: 1485, dur: 1.4, vol: 0.06, delay: 0.05 }); },
    starheart: (a) => { // a heavy thud into the chest, a bright star chord, a low hum that stays
      tone(a, { type: "sine", from: 120, to: 40, dur: 0.6, vol: 0.5 }); noise(a, { dur: 0.4, vol: 0.4, freq: 240 });
      [523, 784, 1047, 1568].forEach((f, i) => tone(a, { type: "triangle", from: f, dur: 1.3, vol: 0.13, delay: 0.08 + i * 0.05 }));
      tone(a, { type: "sawtooth", from: 82, to: 78, dur: 2.2, vol: 0.1, delay: 0.2 }); },
    scrap: (a) => { for (let i = 0; i < 8; i++) noise(a, { dur: 0.05, vol: 0.18, freq: 2500 + Math.random() * 3000, delay: i * 0.11 + Math.random() * 0.05 }); },
    clank: (a) => { tone(a, { type: "square", from: 1400 + Math.random() * 600, to: 900, dur: 0.07, vol: 0.06 }); noise(a, { dur: 0.06, vol: 0.2, freq: 3200 }); },
    wingsweep: (a) => { // steel wings snap open: a rush of air and a ringing blade
      const t = a.currentTime, len = Math.floor(a.sampleRate * 0.8), buf = a.createBuffer(1, len, a.sampleRate), d = buf.getChannelData(0);
      for (let i = 0; i < len; i++) d[i] = (Math.random() * 2 - 1) * Math.sin(Math.PI * i / len);
      const src = a.createBufferSource(), f = a.createBiquadFilter(), g = a.createGain();
      src.buffer = buf; f.type = "bandpass"; f.frequency.setValueAtTime(300, t); f.frequency.exponentialRampToValueAtTime(2400, t + 0.6);
      g.gain.value = 0.45 * prefs.volume; src.connect(f).connect(g).connect(a.destination); src.start(t);
      [1760, 2637].forEach((fr, i) => tone(a, { type: "sine", from: fr, dur: 1.1, vol: 0.07, delay: 0.45 + i * 0.03 })); },
  };
  /** Going down to a new level (or a new map made): the screen sinks into darkness down a flight of
     steps, the level's name comes up, then it fades away. About two seconds; tap to skip. */
  function descend(title, sub) {
    if (!prefs.effects) { banner(title, sub, "crit"); return; }
    const el = document.createElement("div");
    el.className = "fx-descend" + (calm() ? " is-calm" : "");
    el.setAttribute("role", "status");
    const steps = document.createElement("div"); steps.className = "fx-steps";
    for (let i = 0; i < 7; i++) { const s = document.createElement("span"); s.style.setProperty("--i", i); steps.append(s); }
    const t = document.createElement("div"); t.className = "fx-descend-title"; t.textContent = title;
    el.append(steps, t);
    if (sub) { const s = document.createElement("div"); s.className = "fx-descend-sub"; s.textContent = sub; el.append(s); }
    const go = () => { el.classList.add("is-out"); setTimeout(() => el.remove(), 500); };
    el.addEventListener("click", go);
    document.body.append(el);
    sound("descend");
    setTimeout(go, calm() ? 1400 : 2400);
  }
  /** Steven Voss at half health ("Hollow Star Heart"): he lifts his shard of the Hollow Star and
     drives it into his chest, the star lights up inside him, scraps of metal flicker into being all
     round him, fly in and lock together into two folded steel wings, and the wings sweep open around
     him. About nine seconds; tap to skip. opts: {name, portrait (upload name)}. */
  const STAR = "50,4 61.2,34.6 93.7,35.8 68.1,55.9 77,87.2 50,69 23,87.2 31.9,55.9 6.3,35.8 38.8,34.6";
  const STAR_IN = "50,20 57.3,40 78.5,40.7 61.8,53.8 67.6,74.3 50,62.4 32.4,74.3 38.2,53.8 21.5,40.7 42.7,40";
  function starHeart(opts) {
    opts = opts || {};
    const old = document.querySelector(".fx-starheart"); if (old) old.remove();
    const mk = (tag, cls, html) => { const e = document.createElement(tag); if (cls) e.className = cls; if (html) e.innerHTML = html; return e; };
    const el = mk("div", "fx-starheart" + (calm() || !prefs.effects ? " is-calm" : ""));
    el.setAttribute("role", "status");
    el.setAttribute("aria-label", (opts.name || "Steven Voss") + " drives the Hollow Star shard into his chest and grows steel wings");
    const stage = mk("div", "sh-stage");
    const wings = mk("div", "sh-wings");
    const L = mk("div", "sh-wing is-left"), R = mk("div", "sh-wing is-right");
    wings.append(L, R);
    // three rows of steel feathers per wing: long blades at the back, shorter plates over them
    const TIERS = [{ n: 9, len: 0.52, h: 0.07, from: -78, to: 38 }, { n: 7, len: 0.36, h: 0.07, from: -66, to: 30 }, { n: 5, len: 0.2, h: 0.08, from: -50, to: 22 }];
    const plates = [];
    TIERS.forEach((t, ti) => {
      for (let k = 0; k < t.n; k++) {
        const f = k / (t.n - 1), a = t.from + (t.to - t.from) * f, len = t.len * (1 - 0.32 * f);
        [L, R].forEach((w) => {
          const p = mk("div", "sh-plate is-t" + ti);
          p.style.width = (len * 100) + "%"; p.style.height = (t.h * 100) + "%";
          w.append(p); plates.push({ p, a, ti, k, f });
        });
      }
    });
    const body = mk("div", "sh-body");
    if (opts.portrait) { const img = mk("img", "sh-pic"); img.src = "/api/uploads/" + opts.portrait; img.alt = ""; body.append(img); }
    else body.append(mk("div", "sh-pic sh-nopic", "SV"));
    const core = mk("div", "sh-core", `<svg viewBox="0 0 100 100" aria-hidden="true"><polygon points="${STAR}" class="sh-star"/><polygon points="${STAR_IN}" class="sh-star-in"/></svg>`);
    body.append(core);
    // the shard: one broken point of the Hollow Star
    const shard = mk("div", "sh-shard", `<svg viewBox="0 0 60 80" aria-hidden="true"><polygon points="30,2 44,44 38,48 33,41 27,52 21,45 14,49" class="sh-shard-out"/><polygon points="30,16 38,40 31,37 26,43 22,40" class="sh-shard-in"/></svg>`);
    const hand = mk("div", "sh-hand");
    const ring = mk("div", "sh-ring"), ring2 = mk("div", "sh-ring is-two"), flash = mk("div", "sh-flash");
    stage.append(wings, body, hand, shard, ring, ring2);
    const say = mk("div", "sh-words");
    const kicker = mk("div", "sh-kicker"); kicker.textContent = (opts.name || "Steven Voss") + " is at half health";
    const title = mk("div", "sh-title"); title.textContent = "Hollow Star Heart";
    const sub = mk("div", "sh-sub"); sub.textContent = "Phase 2 — steel wings, and the star burns in his chest";
    say.append(kicker, title, sub);
    el.append(flash, stage, say);
    document.body.append(el);
    let done = false;
    const timers = [];
    const later = (ms, fn) => timers.push(setTimeout(() => { if (!done) fn(); }, ms));
    ensureLayer(); layer.style.zIndex = "9700"; // the sparks go over the scene
    const go = () => { if (done) return; done = true; timers.forEach(clearTimeout); el.classList.add("is-out");
      setTimeout(() => { el.remove(); if (!document.querySelector(".fx-starheart")) layer.style.zIndex = ""; }, 600); };
    later(700, () => el.addEventListener("click", go));
    const finalT = (pl) => `translate(0px, 0px) rotate(${pl.a}deg) scale(1)`;
    if (el.classList.contains("is-calm")) { // no movement: the finished look, then the words
      plates.forEach((pl) => { pl.p.style.transform = finalT(pl); pl.p.style.opacity = 1; });
      el.classList.add("is-lit", "is-winged", "is-words");
      sound("starheart");
      later(4200, go);
      return { close: go };
    }
    const anim = (node, frames, o) => node.animate ? node.animate(frames, Object.assign({ fill: "forwards", easing: "ease-in-out" }, o)) : null;
    // 1) he lifts the shard (0.4 s - 1.9 s)
    sound("shardrise");
    anim(shard, [{ transform: "translate(-50%, 90%) scale(.5) rotate(-30deg)", opacity: 0 },
      { transform: "translate(-50%, 30%) scale(1.15) rotate(8deg)", opacity: 1, offset: 0.55 },
      { transform: "translate(-50%, 0%) scale(1.25) rotate(0deg)", opacity: 1 }], { duration: 1500, delay: 400, easing: "cubic-bezier(.2,.8,.3,1)" });
    anim(hand, [{ opacity: 0 }, { opacity: 1, offset: 0.3 }, { opacity: 1 }], { duration: 1500, delay: 400 });
    // 2) ... and drives it into his chest (2.2 s): a flash, rings, and the star lights inside him
    later(2200, () => {
      anim(shard, [{ transform: "translate(-50%, 0%) scale(1.25) rotate(0deg)", opacity: 1 },
        { transform: "translate(-50%, -40%) scale(1.5) rotate(0deg)", opacity: 1, offset: 0.35 },
        { transform: "translate(-50%, 155%) scale(.25) rotate(0deg)", opacity: 0 }], { duration: 520, easing: "cubic-bezier(.6,0,.9,.4)", fill: "forwards" });
      anim(hand, [{ opacity: 1 }, { opacity: 0 }], { duration: 400, delay: 300 });
    });
    later(2720, () => {
      el.classList.add("is-lit"); sound("starheart");
      anim(flash, [{ opacity: 0 }, { opacity: 0.95, offset: 0.12 }, { opacity: 0 }], { duration: 900, easing: "ease-out" });
      [ring, ring2].forEach((r, i) => anim(r, [{ transform: "translate(-50%,-50%) scale(.1)", opacity: 1 }, { transform: "translate(-50%,-50%) scale(3.4)", opacity: 0 }],
        { duration: 1100, delay: i * 180, easing: "cubic-bezier(.1,.7,.3,1)" }));
      anim(stage, [{ transform: "translate(0,0)" }, { transform: "translate(-6px,3px)" }, { transform: "translate(5px,-4px)" }, { transform: "translate(-3px,2px)" }, { transform: "translate(0,0)" }], { duration: 420 });
      burst(core, "crit", 46);
    });
    // 3) scraps of metal flicker into being all around him (3.3 s - 4.3 s) ...
    const W = stage.getBoundingClientRect().width || 400;
    plates.forEach((pl, i) => {
      const ang = Math.random() * Math.PI * 2, dist = W * (0.32 + Math.random() * 0.42);
      const dx = Math.cos(ang) * dist, dy = Math.sin(ang) * dist * 0.75, r0 = Math.round(Math.random() * 720 - 360);
      const start = `translate(${dx.toFixed(0)}px, ${dy.toFixed(0)}px) rotate(${r0}deg) scale(.55)`;
      const shown = 3300 + Math.random() * 1000;
      // ... then fly in and lock into place, the plates nearest his back first (4.5 s - 6.3 s)
      const fly = 4500 + pl.ti * 260 + pl.f * 900 + Math.random() * 160;
      pl.p.style.transform = start; pl.p.style.opacity = 0;
      anim(pl.p, [{ transform: start, opacity: 0, filter: "brightness(4)" }, { transform: start, opacity: 1, filter: "brightness(3)", offset: 0.35 },
        { transform: start, opacity: 0.25, offset: 0.55 }, { transform: start, opacity: 1, filter: "brightness(1.2)" }], { duration: 520, delay: shown, easing: "steps(6)" });
      anim(pl.p, [{ transform: start, opacity: 1, filter: "brightness(1.2)" },
        { transform: `translate(0px, 0px) rotate(${pl.a + 14}deg) scale(1.08)`, opacity: 1, filter: "brightness(2.2)", offset: 0.82 },
        { transform: finalT(pl), opacity: 1, filter: "brightness(1)" }], { duration: 760, delay: fly, easing: "cubic-bezier(.5,0,.2,1)" });
      if (i % 6 === 0) later(fly + 640, () => sound("clank"));
    });
    later(3300, () => sound("scrap"));
    // 4) the folded wings sweep open around him (6.5 s)
    later(6500, () => {
      el.classList.add("is-winged"); sound("wingsweep");
      anim(L, [{ transform: "scaleX(-1) rotate(62deg)" }, { transform: "scaleX(-1) rotate(-14deg)", offset: 0.6 }, { transform: "scaleX(-1) rotate(0deg)" }], { duration: 900, easing: "cubic-bezier(.3,1.3,.5,1)" });
      anim(R, [{ transform: "rotate(62deg)" }, { transform: "rotate(-14deg)", offset: 0.6 }, { transform: "rotate(0deg)" }], { duration: 900, easing: "cubic-bezier(.3,1.3,.5,1)" });
      anim(ring, [{ transform: "translate(-50%,-50%) scale(.6)", opacity: 0.8 }, { transform: "translate(-50%,-50%) scale(3)", opacity: 0 }], { duration: 900, easing: "ease-out" });
    });
    later(7000, () => el.classList.add("is-words"));
    later(11000, go);
    return { close: go };
  }

  function sound(name) {
    if (!prefs.sounds || !SOUNDS[name]) return;
    const a = ac();
    if (!a || a.state !== "running") return;
    try { SOUNDS[name](a); } catch (e) { /* audio is a nicety */ }
  }

  window.FX = {
    float, flash, banner, burst, sound, descend, starHeart,
    get prefs() { return Object.assign({}, prefs); },
    set(k, v) { prefs[k] = v; save(); if (k === "sounds" && v) { ac(); sound("ping"); } },
  };
})();
