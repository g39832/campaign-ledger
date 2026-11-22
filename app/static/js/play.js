/* Player screen: the shared map, turn order, own character with roll
   buttons, and the party. Everything comes from /api/play/state, which the
   server has already stripped of anything players shouldn't see. */
(function () {
  "use strict";
  const { h, icon, $, api, toast, signed } = L;
  const ABIL = [["str", "Strength"], ["dex", "Dexterity"], ["con", "Constitution"], ["int", "Intelligence"], ["wis", "Wisdom"], ["cha", "Charisma"]];
  const SKILLS = [["acrobatics", "Acrobatics"], ["animal_handling", "Animal Handling"], ["arcana", "Arcana"], ["athletics", "Athletics"], ["deception", "Deception"],
    ["history", "History"], ["insight", "Insight"], ["intimidation", "Intimidation"], ["investigation", "Investigation"], ["medicine", "Medicine"],
    ["nature", "Nature"], ["perception", "Perception"], ["performance", "Performance"], ["persuasion", "Persuasion"], ["religion", "Religion"],
    ["sleight_of_hand", "Sleight of Hand"], ["stealth", "Stealth"], ["survival", "Survival"]];
  let S = null, stamp = "", mapStamp = "";
  const PING_COOLDOWN_MS = 5000;
  let lastPing = 0;
  let casting = null;
  let using = null; // { what: "attack" | "spell", index, name, single, max, chosen: Set of combatant ids, busy, result } while aiming at enemies // { spell, chosen: Set of character ids, slot, busy, result } while the player picks who a spell is for

  try { const t = localStorage.getItem("player-theme"); if (t) document.documentElement.dataset.theme = t; } catch (e) { /* ignore */ }
  $("#theme-toggle-p").addEventListener("click", () => {
    const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("player-theme", next); } catch (e) { /* ignore */ }
  });

  let movesPending = 0, dragMissed = false, loadSeq = 0, loadDone = 0; // keeps the map's updates in order (see load)
  const view = new MapView($("#stage"), {
    role: "player",
    imageUrl: (m) => m.image_url,
    canMove: (t) => t.movable && !casting && !using,
    reach: (t) => {
      const k = t.pet && acting(), mv = k && k.id === t.combatant_id ? k.move : t.own && S && S.character && S.character.move;
      if (t.roam && !(mv && mv.my_turn)) return { budget: (S.map && S.map.scale_unit !== "m" && Number(S.map.scale_value)) || 5, from: [t.x, t.y] }; // exploring: one square
      return mv && mv.my_turn ? { budget: mv.held ? 0 : mv.budget, from: mv.from } : null;
    },
    onSelect: (t) => { // tap a token to cast on them, or to aim an attack at an enemy
      if (casting && t && t.character_id) pick(t.character_id);
      else if (using && !using.aim && t) pickFoe(t.combatant_id, t.display);
    },
    onAim: () => { if (using && using.aim) { caughtByAim(); render(); } }, // the cone was turned: who's in it now
    onChest: (c) => { // tap a chest: open it if your hero is next to it
      const t = myToken();
      if (t && nextTo(t, c.x, c.y)) openChest(c);
      else toast(c.name + (c.opened ? " (open)" : c.locked_by ? " — locked, needs a " + c.locked_by : "") + ". Walk up next to it to open it.", "ok");
    },
    onPlace: (x, y) => { // a clone: the square it appears on
      if (!casting || !casting.spell.summon || casting.busy || casting.result) return;
      const on = (S.mapTokens || []).find((t) => !["marker", "trap"].includes(t.kind) && !["dead", "defeated"].includes(t.status) && x >= t.x && x < t.x + t.size && y >= t.y && y < t.y + t.size);
      if (on) { toast(on.display + " is already standing there — pick an empty square.", "error"); return; }
      const m = S.map;
      if (m && m.fog_enabled && (m.revealed || "")[y * m.cols + x] !== "1") { toast("You can't see that square — pick one you can see.", "error"); return; }
      if (casting.busy) return;
      casting.at = [x, y]; view.mark = [x, y]; view.draw();
      castNow(); // it appears there straight away (Take it back if that was a misclick)
    },
    onPing: async (x, y) => {
      // one ping every few seconds (the server keeps the same cooldown)
      const wait = Math.ceil((lastPing + PING_COOLDOWN_MS - Date.now()) / 1000);
      if (wait > 0) { toast("Wait " + wait + " s before pinging again.", "error"); return; }
      lastPing = Date.now();
      try { const d = await api("POST", "/api/play/ping", { x, y }); view.setPings(d.pings); if (window.FX) FX.sound("ping"); }
      catch (e) { toast(e.message, "error"); }
    },
    onMove: async (t, x, y) => {
      movesPending++;
      try {
        const r = await api("POST", "/api/play/tokens/" + t.id + "/move", { x, y });
        if (r && r.next_level && r.next_level.blocked) toast(r.next_level.why + ".", "error");
      } catch (e) { toast(e.message, "error"); }
      movesPending--;
      loadDone = ++loadSeq; // anything fetched before the move landed would put the token back
      // the token was put down where the finger let go before the server answered: always redraw
      // from the server's copy (a refused move goes back; "nothing changed" mustn't skip that)
      dragMissed = false; stamp = null; mapStamp = null;
      load(true);
    },
    onDragEnd: () => {
      if (!dragMissed || movesPending) return; // (a move in flight reloads when it lands)
      dragMissed = false; stamp = null; load(true);
    },
  });
  /* Free roam: outside a fight the hero walks one square at a time — the arrow pad (hold to keep
     walking), the arrow keys or W A S D, or dragging one square. One step is sent at a time. */
  let stepBusy = false, holdDir = null;
  async function step(dx, dy) {
    const t = myToken();
    if (!t || !t.roam || !t.movable || stepBusy || casting || using || !S.map) return false;
    const x = t.x + dx, y = t.y + dy;
    if (x < 0 || y < 0 || x + t.size > S.map.cols || y + t.size > S.map.rows) return false;
    stepBusy = true; movesPending++;
    let ok = true;
    try {
      const r = await api("POST", "/api/play/tokens/" + t.id + "/move", { x, y });
      if (r && r.next_level && r.next_level.blocked) toast(r.next_level.why + ".", "error");
    } catch (e) { toast(e.message, "error"); ok = false; holdDir = null; }
    movesPending--; stepBusy = false;
    loadDone = ++loadSeq; dragMissed = false; stamp = null; mapStamp = null;
    await load(true);
    return ok;
  }
  async function walk() { // keeps stepping while the arrow is held
    while (holdDir) {
      const [dx, dy] = holdDir;
      if (!(await step(dx, dy))) break;
      await new Promise((r) => setTimeout(r, 110));
    }
  }
  document.querySelectorAll("#roam-pad [data-step]").forEach((b) => {
    const [dx, dy] = b.dataset.step.split(",").map(Number);
    const stop = () => { holdDir = null; b.classList.remove("is-on"); };
    b.addEventListener("pointerdown", (e) => { e.preventDefault(); b.classList.add("is-on"); if (holdDir) return; holdDir = [dx, dy]; walk(); });
    ["pointerup", "pointerleave", "pointercancel"].forEach((k) => b.addEventListener(k, stop));
    b.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); step(dx, dy); } });
    b.addEventListener("contextmenu", (e) => e.preventDefault());
  });
  const KEY_STEP = { ArrowUp: [0, -1], ArrowDown: [0, 1], ArrowLeft: [-1, 0], ArrowRight: [1, 0], w: [0, -1], s: [0, 1], a: [-1, 0], d: [1, 0] };
  document.addEventListener("keydown", (e) => {
    if (e.ctrlKey || e.metaKey || e.altKey || $("#roam-pad").hidden) return;
    const tag = (e.target && e.target.tagName) || "";
    if (/^(INPUT|TEXTAREA|SELECT)$/.test(tag) || (e.target && e.target.isContentEditable)) return;
    const d = KEY_STEP[e.key.length === 1 ? e.key.toLowerCase() : e.key];
    if (!d) return;
    e.preventDefault();
    step(d[0], d[1]);
  });
  // tools: move, measure, ping
  const PHINT = { select: null, measure: "Drag to measure. Diagonals count as one square.", ping: "Tap a spot to ping it. Everyone sees it for a few seconds." };
  function setPTool(t) {
    view.tool = t;
    document.querySelectorAll("[data-ptool]").forEach((b) => { b.classList.toggle("is-on", b.dataset.ptool === t); b.setAttribute("aria-pressed", b.dataset.ptool === t); });
    if (PHINT[t]) $("#hint").textContent = PHINT[t]; else if (S) render();
  }
  document.querySelectorAll("[data-ptool]").forEach((b) => b.addEventListener("click", () => setPTool(b.dataset.ptool)));
  setPTool("select");
  // sounds on/off for this device
  function soundIcon() {
    const on = !window.FX || FX.prefs.sounds;
    $("#sound-toggle-p").replaceChildren(icon(on ? "zap" : "x", "sm"));
    $("#sound-toggle-p").title = on ? "Sounds on — click to mute" : "Sounds off — click to turn on";
  }
  $("#sound-toggle-p").addEventListener("click", () => { if (window.FX) FX.set("sounds", !FX.prefs.sounds); soundIcon(); });
  soundIcon();
  $("#zoom-in").addEventListener("click", () => view.zoom(1.25));
  $("#zoom-out").addEventListener("click", () => view.zoom(0.8));
  $("#zoom-fit").addEventListener("click", () => view.fit());
  // turning the phone or tablet (or a big resize): fit the map to its new shape
  let lastShape = innerWidth + "x" + innerHeight;
  window.addEventListener("resize", L.debounce(() => {
    const shape = innerWidth + "x" + innerHeight, [w0, h0] = lastShape.split("x").map(Number);
    if (Math.abs(innerWidth - w0) > 120 || Math.abs(innerHeight - h0) > 120) view.fit();
    lastShape = shape;
  }, 250));
  // on a phone the map stays at the top while the rest scrolls under it; this picks how tall it is
  const SIZES = ["small", "medium", "large"];
  let mapSize = "medium";
  try { mapSize = SIZES.includes(localStorage.getItem("play-map-size")) ? localStorage.getItem("play-map-size") : "medium"; } catch (e) { /* ignore */ }
  const setSize = (s) => { mapSize = s; document.body.dataset.mapSize = s; $("#map-size").title = "Map size: " + s + " — tap to change"; };
  setSize(mapSize);
  $("#map-size").addEventListener("click", () => {
    setSize(SIZES[(SIZES.indexOf(mapSize) + 1) % SIZES.length]);
    try { localStorage.setItem("play-map-size", mapSize); } catch (e) { /* ignore */ }
    setTimeout(() => view.fit(), 50);
  });
  let rollsOpen = !window.matchMedia("(max-width: 1100px)").matches; // saving throws and skills: folded on phones
  let diceOpen = false; // the dice colors picker, folded away until they open it
  if (window.Dice) Dice.overlayHost = $("#stage");

  const roll = (check, e, crit) => Dice.roll({ check: Object.assign({ character_id: S.character.id }, check), crit: !!crit }, e, { wait: true });
  // Homebrew crit: a natural 20 to hit rolls the damage with double dice, right after the d20 lands.
  const attackThen = (check, dmgCheck) => (e) => roll(check, e).then((r) => {
    if (r && r.result && r.result.natural === 20 && dmgCheck) roll(dmgCheck, null, true);
  });
  let amtValue = "";
  async function me(path, body) {
    try {
      const d = await api("POST", "/api/play/me/" + path, Object.assign({ op_id: L.uid() }, body));
      if (d.roll && window.Dice) { Dice.addHistory([d.roll]); Dice.animate(d.roll); if (!Dice.isOpen()) Dice.toggle(true); }
      load(true);
      return d;
    } catch (e) { toast(e.message, "error"); return null; }
  }
  function hpControls(c) {
    const amt = h("input", { type: "number", min: 0, placeholder: "0", value: amtValue, "aria-label": "Amount", "data-keep": "me-amt", inputmode: "numeric",
      style: "width:5.5ch;text-align:center", oninput: (e) => { amtValue = e.target.value; },
      onkeydown: (e) => { if (e.key === "Enter") { e.preventDefault(); go(e.shiftKey ? "heal" : "damage"); } } });
    const go = (op) => {
      const n = Number(amt.value);
      if (!amt.value || !Number.isFinite(n) || n < 0) { amt.focus(); return; }
      amtValue = ""; me("hp", { op, amount: Math.trunc(n) });
    };
    const fix = (n) => me("hp", { op: "set", hp: Math.max(0, Math.min(c.max_hp || Infinity, c.current_hp + n)) });
    return h("div", { style: "display:grid;gap:6px;margin-bottom:10px" },
      h("div", { class: "roll-row", style: "align-items:center" }, amt,
        h("button", { type: "button", class: "btn btn-sm btn-dmg", onclick: () => go("damage") }, "Damage"),
        h("button", { type: "button", class: "btn btn-sm btn-heal", onclick: () => go("heal") }, "Heal"),
        h("button", { type: "button", class: "btn btn-sm btn-temp", onclick: () => go("temp") }, "Temp")),
      h("div", { class: "hp-fix" }, h("span", { class: "lbl" }, "Fix HP"),
        [-5, -1, 1, 5].map((n) => h("button", { type: "button", class: "btn btn-sm", onclick: () => fix(n) }, n > 0 ? "+" + n : "−" + Math.abs(n)))));
  }
  function extras(c) {
    const out = [];
    if (c.can.edit_hp && (c.current_hp === 0 || c.death_successes || c.death_failures)) {
      const pips = (field, cls) => h("span", { class: "pips " + cls }, [0, 1, 2].map((i) => h("button", {
        type: "button", class: "pip" + (i < c[field] ? " on" : ""), "aria-label": field.replace("_", " ") + " " + (i + 1),
        onclick: () => me("death", { field, value: c[field] === i + 1 ? i : i + 1 }) })));
      out.push(h("div", { class: "row", style: "align-items:center;margin-bottom:8px" }, h("span", { class: "lbl" }, "Death saves"),
        pips("death_successes", ""), pips("death_failures", "fail")));
    }
    const levels = Object.entries(c.spell_slots || {}).filter(([, v]) => v && v.max > 0);
    if (levels.length) {
      out.push(h("h4", { class: "lbl", style: "margin:4px 0" }, "Spell slots" + (c.can.spend_slots ? " — tap to spend or regain" : "")),
        h("div", { class: "roll-row", style: "margin-bottom:8px" }, levels.map(([lv, v]) => h("span", { class: "slot-row", style: "padding:3px 6px" },
          h("span", { class: "lvl" }, lv),
          h("span", { class: "pips" }, Array.from({ length: v.max }, (_, i) => h("button", {
            type: "button", class: "pip slot" + (i < v.max - v.used ? " on" : ""), disabled: !c.can.spend_slots,
            "aria-label": "Level " + lv + " slot " + (i + 1) + (i < v.max - v.used ? " (available)" : " (spent)"),
            onclick: () => me("slot", { level: lv, used: i < v.max - v.used ? v.used + 1 : v.used - 1 }) })))))));
    }
    if (c.can.hit_dice && c.hit_dice_total) {
      const left = c.hit_dice_total - c.hit_dice_used;
      out.push(h("div", { class: "roll-row", style: "align-items:center;margin-bottom:8px" },
        c.hit_dice_sizes.map((sd) => h("button", { type: "button", class: "btn btn-sm", disabled: left <= 0,
          title: "Short rest: roll a hit die + Constitution and heal", onclick: () => me("hit-die", { sides: sd }) }, "Spend hit die (d" + sd + ")")),
        h("span", { class: "faint", style: "font-size:.85rem" }, left + " of " + c.hit_dice_total + " left")));
    }
    return out;
  }

  // ---- attacks and harmful spells on enemies, like the DM's map ------------------------------
  // Tap Use, then tap an enemy (on the map or in the list). The server rolls to hit, the damage
  // and any effect, and says what happened. Never at yourself or your party.
  const foes = () => ((S.encounter && S.encounter.order) || []).filter((o) => o.kind === "enemy" && !["dead", "defeated", "fled"].includes(o.status));
  // friendly fire: teammates (and allies like Yamato's clone) can be hit too, never yourself
  const myCb = () => { const k = acting(); if (k) return k.id; const e = S.encounter, me = S.character; return e && me ? (e.order.find((o) => o.character_id === me.id) || {}).id : null; };
  const teammates = () => ((S.encounter && S.encounter.order) || []).filter((o) => o.kind !== "enemy" && o.id !== myCb() && !["dead", "defeated", "fled"].includes(o.status));
  // their clone, when it's the clone's turn: they run it (move it, its attacks, end its turn)
  const acting = () => (S && S.character && (S.character.clones || []).find((k) => k.my_turn)) || null;
  const actorToken = () => { const k = acting(), toks = (S && S.mapTokens) || []; return k ? toks.find((t) => t.combatant_id === k.id) : toks.find((t) => t.own); };
  function startUse(what, index, name, single, max, reach) {
    casting = null;
    using = { what, index, name, single, max: max || 0, reach: reach || null, chosen: new Set(), busy: false, result: null, as: acting() ? acting().id : null };
    render();
    const box = $("#use-box");
    if (box) box.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }
  function startHelp(a) {
    startUse("attack", a.index, a.name || "Heal", true, 0, null);
    using.help = true; render();
  }
  const mySide = () => ((S.encounter && S.encounter.order) || []).filter((o) => o.kind !== "enemy" && !["dead", "defeated", "fled"].includes(o.status));
  function pickFoe(cbId, label) {
    if (!using || using.busy || using.result) return;
    if (using.help) { // healing or a boost: anyone on your side, you too
      if (!mySide().some((o) => o.id === cbId)) { toast(using.name + " is for your side — pick a teammate or yourself.", "error"); return; }
      using.chosen = new Set([cbId]); useNow(); return;
    }
    if (cbId === myCb()) { toast("You can't attack yourself.", "error"); return; }
    const mate = teammates().find((o) => o.id === cbId);
    if (!mate && !foes().some((o) => o.id === cbId)) { toast((label || "That") + " isn't in the fight.", "error"); return; }
    if (mate && !using.chosen.has(cbId) && using.armedMate !== cbId) { // a teammate: tap twice so nobody hits a friend by accident
      using.armedMate = cbId; render(); toast(mate.name + " is on your side! Tap again if you really mean to hit them.", "error"); return;
    }
    using.armedMate = null;
    const far = tooFar(cbId);
    if (far) { toast((label || "They") + " is " + far + " ft away — " + using.name + " only reaches " + using.reach + " ft. Move next to them first.", "error"); return; }
    if (using.single) { using.chosen = new Set([cbId]); useNow(); return; }
    const c = using.chosen;
    if (c.has(cbId)) c.delete(cbId);
    else if (using.max && c.size >= using.max) { toast(using.name + " reaches at most " + using.max + ".", "error"); return; }
    else c.add(cbId);
    render();
  }
  // a physical move reaches enemies right next to you: feet to them on the map (null: can't tell, no map)
  function feetTo(cbId) {
    const toks = (S && S.mapTokens) || [], me = actorToken(), them = toks.find((t) => t.combatant_id === cbId);
    if (!me || !them || !S.map) return null;
    const gx = Math.max(0, them.x - (me.x + me.size), me.x - (them.x + them.size)), gy = Math.max(0, them.y - (me.y + me.size), me.y - (them.y + them.size));
    const per = !S.map.scale_unit || S.map.scale_unit === "ft" ? Number(S.map.scale_value) || 5 : 5;
    return (Math.ceil(Math.max(gx, gy) - 1e-6) + 1) * per;
  }
  const tooFar = (cbId) => { if (!using || !using.reach) return 0; const d = feetTo(cbId); return d != null && d > using.reach ? d : 0; };
  async function useNow() {
    const k = using;
    if (!k || k.busy || (!k.chosen.size && !k.cells)) return;
    k.busy = true; render();
    try {
      const d = await api("POST", "/api/play/me/use", Object.assign({ what: k.what, index: k.index, targets: [...k.chosen], op_id: L.uid() },
        k.as ? { as: k.as } : {}, k.cells ? { cells: k.cells } : {}));
      if (d.cast && window.Dice && Dice.showAll) await Dice.showAll(d.cast.rolls || []); // hit or miss once the dice land
      k.result = d.cast || null;
      const hows = d.cast ? d.cast.targets.map((t) => t.how) : [];
      const missed = hows.length && hows.every((x) => x === "miss" || x === "saved");
      if (window.FX) { FX.banner(missed ? "Missed" : hows.includes("crit") ? "Critical hit!" : "Hit!", k.name, missed ? "dmg" : "crit"); FX.sound(missed ? "miss" : "hit"); }
      actionsLeftToast(d.character, k.as);
    } catch (e) { toast(e.message, "error"); k.busy = false; k.chosen.clear(); render(); return; }
    k.busy = false;
    render(); // the result, now that the dice have landed (the refresh below may have nothing new to draw)
    load(true);
  }
  // after a move on your turn: how many actions are left (so nobody has to count)
  function actionsLeftToast(ch, as) {
    const a = as ? (((ch && ch.clones) || []).find((x) => x.id === as) || {}).actions : ch && ch.actions;
    if (!a) return;
    toast(a.left ? (as ? "It has " : "You have ") + a.left + " of " + a.limit + " action" + (a.limit === 1 ? "" : "s") + " left this turn."
      : "That was the last action this turn — tap End turn when you're done.", a.left ? "ok" : "error", { ms: 5000 });
  }
  function useBox() {
    const k = using;
    if (k.result) return h("div", { id: "use-box", class: "fight-aim" },
      h("div", { class: "fa-head" }, icon("swords", "sm"), h("b", null, k.name)),
      k.result.targets.length ? k.result.targets.map((t) => h("p", { style: "margin:4px 0" }, t.text))
        : h("p", { style: "margin:4px 0" }, (k.result.summary || "").split(": ").slice(1).join(": ") || "Done."),
      h("div", { class: "row", style: "gap:8px" },
        h("button", { type: "button", class: "btn btn-sm", onclick: () => { using = null; render(); } }, "Done"),
        k.result.undo ? h("button", { type: "button", class: "btn btn-sm btn-quiet take-back", title: "A misclick? Undo it all", onclick: () => takeBack(k.result.undo) }, icon("undo-2", "sm"), " Take it back") : null));
    if (k.aim && k.ground) return h("div", { id: "use-box", class: "fight-aim" },
      h("div", { class: "fa-head" }, icon("castle", "sm"), h("b", null, k.name)),
      h("p", { class: "fa-ask" }, "Drag on the map to move the square, then Cast it there."),
      h("div", { class: "row" },
        h("button", { type: "button", class: "btn btn-sm btn-primary", disabled: k.busy, onclick: () => {
          k.cells = MapView.shapeCells(view.aim.shape, S.map); stopAimUse(); k.aim = false; useNow(); } }, k.busy ? "Casting…" : "Cast it here"),
        h("button", { type: "button", class: "btn btn-sm", disabled: k.busy, onclick: () => { stopAimUse(); using = null; render(); } }, "Cancel")));
    if (k.aim) {
      const order = (S.encounter && S.encounter.order) || [], inside = (k.inside || []).map((id) => order.find((o) => o.id === id)).filter(Boolean);
      return h("div", { id: "use-box", class: "fight-aim" },
        h("div", { class: "fa-head" }, icon("swords", "sm"), h("b", null, k.name)),
        h("p", { class: "fa-ask" }, "Drag on the map to point it. Everyone in it is hit — teammates too, so tap them to spare them."),
        inside.length ? h("div", { class: "roll-row", style: "margin-bottom:8px" }, inside.map((o) => {
          const mate = o.kind !== "enemy", spared = k.spared.has(o.id);
          return h("button", { type: "button", class: "btn btn-sm" + (spared ? "" : " is-armed"), disabled: k.busy, style: spared ? "text-decoration:line-through;opacity:.6" : null,
            onclick: () => { spared ? k.spared.delete(o.id) : k.spared.add(o.id); caughtByAim(); render(); } },
            (mate && !spared ? "⚠ " : "") + o.name, mate ? h("span", { class: "tag is-bad", style: "font-size:.72rem;margin-left:4px" }, "ally") : null);
        })) : h("p", { class: "faint" }, "Nobody's in it yet — drag on the map to point it."),
        h("div", { class: "row" },
          h("button", { type: "button", class: "btn btn-sm btn-primary", disabled: k.busy || !k.chosen.size, onclick: () => { stopAimUse(); k.aim = false; useNow(); } },
            k.busy ? "Rolling…" : "Use on " + k.chosen.size),
          h("button", { type: "button", class: "btn btn-sm", disabled: k.busy, onclick: () => { stopAimUse(); using = null; render(); } }, "Cancel")));
    }
    if (k.help) return h("div", { id: "use-box", class: "fight-aim" },
      h("div", { class: "fa-head" }, icon("heart", "sm"), h("b", null, k.name)),
      h("p", { class: "fa-ask" }, "Tap who it's for — on the map or here."),
      h("div", { class: "roll-row", style: "margin-bottom:8px" }, mySide().map((o) => h("button", { type: "button", class: "btn btn-sm", disabled: k.busy,
        onclick: () => pickFoe(o.id, o.name) }, o.id === myCb() ? o.name + " (you)" : o.name, o.hp != null ? h("span", { class: "faint num", style: "margin-left:4px" }, o.hp + "/" + o.max_hp) : null))),
      h("div", { class: "row" }, h("button", { type: "button", class: "btn btn-sm", disabled: k.busy, onclick: () => { using = null; render(); } }, k.busy ? "Rolling…" : "Cancel")));
    const list = foes();
    return h("div", { id: "use-box", class: "fight-aim" },
      h("div", { class: "fa-head" }, icon("swords", "sm"), h("b", null, k.name)),
      h("p", { class: "fa-ask" }, (k.single ? "Tap the enemy it's aimed at — on the map or here." : "Tap each enemy it reaches, then Use.")
        + (k.reach ? " It reaches " + k.reach + " ft: enemies right next to you." : "")),
      list.length ? h("div", { class: "roll-row", style: "margin-bottom:8px" }, list.concat(teammates()).map((o) => { const far = tooFar(o.id), mate = o.kind !== "enemy"; return h("button", { type: "button", disabled: k.busy || !!far,
        class: "btn btn-sm" + (k.chosen.has(o.id) ? " is-armed" : ""), "aria-pressed": String(k.chosen.has(o.id)), title: far ? far + " ft away — out of reach" : null, onclick: () => pickFoe(o.id, o.name) },
        (mate ? "⚠ " : "") + o.name, mate ? h("span", { class: "tag is-bad", style: "font-size:.72rem;margin-left:4px" }, k.armedMate === o.id ? "tap again!" : "ally") : null,
        o.health ? h("span", { class: "tag is-bad", style: "font-size:.72rem;margin-left:4px" }, o.health) : null,
        far ? h("span", { class: "faint", style: "font-size:.72rem;margin-left:4px" }, far + " ft") : null); }))
        : h("p", { class: "faint" }, "No enemies to aim at."),
      h("div", { class: "row" },
        k.single ? null : h("button", { type: "button", class: "btn btn-sm btn-primary", disabled: k.busy || !k.chosen.size, onclick: useNow },
          k.busy ? "Rolling…" : "Use on " + k.chosen.size),
        h("button", { type: "button", class: "btn btn-sm", disabled: k.busy, onclick: () => { using = null; render(); } }, "Cancel")));
  }
  async function useZone(s) {
    using = { what: "spell", index: s.index, name: s.name, single: false, chosen: new Set(), busy: true, result: null };
    render();
    try {
      const d = await api("POST", "/api/play/me/use", { what: "spell", index: s.index, targets: [], op_id: L.uid() });
      if (d.cast && window.Dice && Dice.showAll) await Dice.showAll(d.cast.rolls || []);
      using.result = d.cast || null;
      if (window.FX) { FX.banner(s.name + "!", d.cast && d.cast.targets.length ? d.cast.targets.length + " caught in it" : "no enemies in it yet", "crit"); FX.sound("crit"); }
    } catch (e) { toast(e.message, "error"); using = null; }
    if (using) using.busy = false;
    render();
    load(true);
  }
  // Take it back: a misclick undone (until anything else happens in the fight)
  async function takeBack(castId) {
    try {
      const d = await api("POST", "/api/play/me/casts/" + castId + "/undo", { op_id: L.uid() });
      toast(d.taken_back + " was taken back.", "ok");
      using = null; casting = null;
    } catch (e) { toast(e.message, "error"); }
    load(true);
  }
  /* An area (Wide Slash's cone): it comes out of your token; drag on the map to turn it, see who
     it catches (teammates too: friendly fire, tap them to spare them), then Use. */
  function startAimUse(s) {
    const me = (S.mapTokens || []).find((t) => t.own), ar = L.spellView(s).area;
    if (!S.map || !me || !ar) { startUse("spell", s.index, s.name, false, s.targets); return; }
    casting = null;
    const from = [me.x + me.size / 2, me.y + me.size / 2], fromR = me.size / 2;
    const foes = (S.mapTokens || []).filter((t) => t.combatant_id && !t.own && foes_ids().has(t.combatant_id));
    const near = foes.sort((p, q) => Math.hypot(p.x - me.x, p.y - me.y) - Math.hypot(q.x - me.x, q.y - me.y))[0];
    const to = near ? [near.x + near.size / 2, near.y + near.size / 2] : [from[0] + 1, from[1]];
    const ang = Math.atan2(to[1] - from[1], to[0] - from[0]);
    const shape = { kind: ar.kind, size: ar.size, width: 5, dir: Math.round(ang * 180 / Math.PI / 5) * 5, label: s.name };
    if (ar.kind === "cone" || ar.kind === "line") { const r = shape.dir * Math.PI / 180; shape.x = from[0] + Math.cos(r) * fromR; shape.y = from[1] + Math.sin(r) * fromR; }
    else { shape.x = to[0]; shape.y = to[1]; }
    view.aim = { shape, from, fromR, range: ar.range || 0, hits: new Set() };
    if (ar.kind !== "cone" && ar.kind !== "line") [shape.x, shape.y] = view.clampAim(shape.x, shape.y);
    view.aim.hits = new Set(MapView.tokensInShape(shape, S.map, S.mapTokens).map((t) => t.id));
    view.tool = "aim";
    using = { what: "spell", index: s.index, name: s.name, single: false, aim: true, spared: new Set(), chosen: new Set(), busy: false, result: null, ground: !!s.terrain };
    caughtByAim();
    render();
    $("#hint").textContent = s.name + ": drag on the map to point it" + (ar.kind === "cone" || ar.kind === "line" ? " (it comes out of you)" : "") + ", then Use.";
    view.draw();
    const box = $("#use-box");
    if (box) box.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }
  const foes_ids = () => new Set(foes().map((o) => o.id));
  function caughtByAim() {
    const u = using, mine = myCb();
    if (!u || !view.aim) return;
    const ids = [...view.aim.hits].map((id) => (S.mapTokens || []).find((t) => t.id === id)).filter((t) => t && t.combatant_id && t.combatant_id !== mine)
      .map((t) => t.combatant_id);
    u.inside = ids;
    u.chosen = new Set(ids.filter((id) => !u.spared.has(id)));
  }
  function stopAimUse() { view.aim = null; view.tool = "select"; view.draw(); }
  const useBtn = (what, index, name, single, max, reach) => h("button", { type: "button", class: "btn btn-sm btn-primary" + (using && using.what === what && using.index === index ? " is-armed" : ""),
    disabled: !!(S.character && S.character.actions && !S.character.actions.left),
    title: "Then tap an enemy", onclick: () => startUse(what, index, name, single, max, reach) }, icon("swords", "sm"), " Use");
  const aimsAtFoes = (s) => (s.kind === "damage" || s.kind === "debuff") && !s.terrain && !s.aura && !s.summon && !L.spellHelps(s);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && using && !using.busy) { if (using.aim) stopAimUse(); using = null; render(); } });

  // ---- casting a healing or buff spell on someone in the party ------------------------------
  // Tap the spell, tap who it's for (here or their token on the map), then Cast. The server rolls it.
  const castable = (s) => L.spellHelps(s) && !s.terrain; // map-changing spells are aimed by the DM
  function startCast(s) {
    const mine = S.character, chosen = new Set();
    if (s.targets === 1 && /\bself\b/i.test(s.notes || "") && mine) chosen.add(mine.id);
    casting = { spell: L.spellView(s), index: s.index, chosen, slot: s.level || null, busy: false, result: null, at: null };
    if (s.summon && S.map) { view.tool = "place"; view.mark = null; } // tap the map where it appears
    render();
    if (s.summon && S.map) { // bring the map into view: the next tap on it is where the clone appears
      $("#hint").textContent = s.name + ": tap the square on the map where " + s.summon + " appears.";
      const st = $("#stage").getBoundingClientRect();
      if (st.top < 0 || st.bottom > innerHeight) $("#stage").scrollIntoView({ block: "start", behavior: "smooth" });
      if (window.FX) FX.float($("#stage"), "Tap where " + s.summon + " appears", "ac");
      return;
    }
    const box = $("#cast-box");
    if (box) box.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }
  function pick(charId) {
    if (!casting || casting.busy || casting.result) return;
    if (!S.party.some((p) => p.id === charId)) { toast("You can only cast this on people in your party.", "error"); return; }
    const c = casting.chosen, max = casting.spell.targets;
    if (c.has(charId)) c.delete(charId);
    else if (max && c.size >= max) { toast(casting.spell.name + " reaches at most " + max + ".", "error"); return; }
    else c.add(charId);
    render();
  }
  async function castNow() {
    const k = casting;
    if (!k || k.busy || (!k.chosen.size && !k.spell.summon)) return;
    k.busy = true; render();
    try {
      const d = await api("POST", "/api/play/cast", Object.assign({ spell: k.index, targets: [...k.chosen], slot: k.slot, op_id: L.uid() },
        k.at && S.map ? { at: { map_id: S.map.id, x: k.at[0], y: k.at[1] } } : {}));
      if (k.spell.summon) placeDone();
      if (d.cast && window.Dice && Dice.showAll) await Dice.showAll(d.cast.rolls || []);
      k.result = d.cast || null;
      const healing = k.spell.kind === "heal";
      if (window.FX) { FX.float($("#party"), healing && d.roll ? "+" + d.roll.total : "✦", healing ? "heal" : "ac"); FX.sound(healing ? "heal" : "ac"); }
      actionsLeftToast(d.character);
    } catch (e) { toast(e.message, "error"); }
    k.busy = false;
    render();
    load(true);
  }
  function castBox() {
    const mine = S.character, k = casting;
    const people = S.party.map((p) => ({ id: p.id, ally: true,
      name: p.id === (mine && mine.id) ? p.name + " (you)" : p.name, info: p.current_hp + "/" + p.max_hp + " HP" }));
    const slots = mine && Object.fromEntries(Object.entries(mine.spell_slots || {}).filter(([, v]) => v && v.max > 0));
    return h("div", { id: "cast-box" }, L.castPanel({ spell: k.spell, people, chosen: k.chosen, busy: k.busy, result: k.result,
      slots: slots && Object.keys(slots).length ? slots : null, slot: k.slot, allowFree: false, casterName: mine && mine.name, place: !!(k.spell.summon && S.map),
      onToggle: (p) => pick(p.id), onSlot: (n) => { k.slot = n; }, onCast: castNow, onCancel: () => { placeDone(); casting = null; render(); },
      onTakeBack: (r) => takeBack(r.undo) }),
      k.spell.summon ? null : S.map && !k.result ? h("p", { class: "faint", style: "font-size:.84rem;margin:6px 0 0" }, "You can also tap their token on the map.") : null);
  }
  window.appBusy = () => !!((using && !using.result) || (casting && !casting.result) || (window.Dice && Dice.isOpen && Dice.rolling && Dice.rolling()));
  function placeDone() { view.mark = null; if (view.tool === "place") view.tool = "select"; view.draw(); }
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && casting) { placeDone(); casting = null; render(); } });

  // in a fight: your own turn only, as far as your speed
  function moveHint(mine, mv) {
    if (mv && !mv.my_turn) return "Wait for your turn to move. ";
    if (mv && mv.held) return "You're " + mv.held + " — you can't move. ";
    if (mv && mine.movable) return "Drag your token to move: " + mv.left + " of " + mv.budget + " ft left" + (mv.used ? " (you can still readjust)" : "") + ". ";
    if (mv && !mv.left) return "No movement left this turn" + (mv.dash ? ". " : " (Dash for more). ");
    if (mine.held) return "Hold still: the DM will let you know when you can explore. ";
    if (mine.movable && mine.roam) return "Exploring: walk one square at a time with the arrows" + (matchMedia("(pointer: fine)").matches ? " (or arrow keys / W A S D)" : "") + ". ";
    return mine.movable ? "Drag your token to move. " : "The DM has locked movement. ";
  }
  // your moves, shown like the DM's move cards on the map: what each one does, then its buttons
  /* Time Reversal (Lux's ring): right after a creature ends its turn, send it back to the start of it. */
  function useRewind() {
    return me("rewind", {}).then((d) => {
      const r = d && d.rewind; if (!r) return;
      toast(r.name + "! " + r.target + " goes back to the start of its turn and takes it again.", "ok", { ms: 7000 });
      if (window.FX) { FX.banner(r.name + "!", r.target + " takes its turn again", "crit"); FX.sound("crit"); }
    });
  }
  function rewindBtn(c) {
    const r = c.rewind;
    if (!r) return null;
    if (!r.ok) return h("span", { class: "faint", style: "font-size:.85rem" }, r.why);
    return h("button", { type: "button", class: "btn btn-sm btn-primary", title: "Undo " + r.target + "'s whole turn: it goes back to where it started and takes the turn again",
      onclick: useRewind }, icon("history", "sm"), " Rewind " + r.target + "'s turn");
  }
  function rewindBox(c) { // shown off your turn the moment it can be used
    const r = c.rewind;
    if (!r || !r.ok || r.target_id == null) return null;
    return h("div", { class: "parry-box" }, icon("history", "sm"),
      h("span", { class: "grow" }, h("b", null, r.target + " just ended its turn."), " " + r.name + ": make it take that turn again from the start?"),
      h("button", { type: "button", class: "btn btn-primary", onclick: useRewind }, "Rewind it"));
  }
  /* Echo Teleport (Yamato): pick a clone and he teleports to its spot (they swap places). No action; 15 ft of movement. */
  function teleportTo(s, k) {
    return me("teleport", { spell: s.index, clone: k.id }).then((d) => {
      if (!d || !d.teleport) return;
      toast(s.name + ": you swap places with " + k.name + ".", "ok");
      if (window.FX) { FX.float($("#stage"), s.name, "ac"); FX.sound("ac"); }
    });
  }
  function teleportBtns(s, c) {
    const ks = c.clones || [];
    if (!c.my_turn) return [h("span", { class: "faint", style: "font-size:.85rem" }, "on your turn, with a clone out")];
    if (!ks.length) return [h("span", { class: "faint", style: "font-size:.85rem" }, "summon a clone first")];
    const low = !!(c.move && c.move.left < 15);
    return ks.map((k) => h("button", { type: "button", class: "btn btn-sm btn-primary", disabled: low || !!s.recharging,
      title: low ? "Teleporting costs 15 ft of movement" : "Teleport to " + k.name + "'s spot (you swap places)", onclick: () => teleportTo(s, k) },
      icon("wand-sparkles", "sm"), " Teleport to " + k.name));
  }
  function moveCard(ic, name, info, ...kids) {
    return h("div", { class: "fight-act move-card" }, icon(ic, "sm"), h("b", null, name),
      info ? h("span", { class: "faint move-info" }, info) : null, h("div", { class: "move-btns" }, kids));
  }
  const attackInfo = (a) => [a.bonus ? "attack roll " + a.bonus : "", a.damage, a.extra_moves ? "+" + a.extra_moves + " extra moves this turn" : "",
    a.stance > 1 ? (a.stance === 2 ? "double damage" : "×" + a.stance + " damage") + " this turn" : "", a.stance_hit ? (a.stance_hit ? (a.stance_hit > 0 ? "+" : "") + a.stance_hit + " to hit" : "") + " this turn" : ""].filter(Boolean).join(" · ");
  const spellInfo = (s, c, d) => { const v = L.spellView(s), ar = v.area && v.area.size && !v.zone ? v.area : null;
    return [v.aura ? "" : L.levelWord(v), ar ? ar.size + " ft " + (ar.kind || "") + (ar.range ? " · range " + ar.range + " ft" : "") : "", L.spellWhat(v),
      L.spellLands(v, d.spell || (v.dc ? { dc: v.dc } : null), c.roll_to_hit), v.cooldown ? v.cooldown + "-turn cooldown" : ""].filter(Boolean).join(" · "); };

  // End turn: tap once to arm, again to end it (so a stray tap doesn't skip a turn)
  let endArmed = false, endTimer = null;
  function endTurnBtn(k) {
    return h("button", { type: "button", class: "btn btn-primary end-turn-btn" + (endArmed ? " is-armed" : ""),
      title: "Hand the turn on to whoever's next", onclick: async () => {
        clearTimeout(endTimer); // an old countdown must not cancel the next turn's first tap (a clone's turn comes right after)
        if (!endArmed) { endArmed = true; render(); endTimer = setTimeout(() => { endArmed = false; render(); }, 4000); return; }
        endArmed = false; using = null; casting = null;
        const d = await me("end-turn", k ? { as: k.id } : {});
        if (d) { toast((k ? k.name + "'s turn" : "Turn") + " ended.", "ok"); if (window.FX) FX.sound("ac"); }
      } }, icon("check", "sm"), endArmed ? (k ? " Tap again to end " + k.name + "'s turn" : " Tap again to end your turn") : k ? " End " + k.name + "'s turn" : " End my turn");
  }
  // the clone's moves on its turn: just its own attacks (Yamato's clone: Slash)
  function cloneMoves(k) {
    const noActs = !!(k.actions && !k.actions.left);
    const out = (k.attacks || []).map((a) => h("button", { type: "button", class: "fight-act", disabled: noActs,
      onclick: () => startUse("attack", a.index, a.name, true, 0, a.reach) }, icon("swords", "sm"), h("b", null, a.name),
      h("span", { class: "faint" }, a.damage + " · reaches " + a.reach + " ft")));
    const dismiss = L.twoTapBtn("dismiss:" + k.id, { class: "btn btn-sm btn-quiet", title: "Send " + k.name + " away (no burst)" },
      () => [icon("x", "sm"), " Dismiss " + k.name], "Tap again to dismiss " + k.name,
      () => me("dismiss", { as: k.id }).then((d) => { if (d) toast(k.name + " is gone.", "ok"); }));
    return h("div", { class: "fight-acts your-moves", style: "margin-top:10px" },
      L.turnStrip({ actions: k.actions, move: k.move, reaction: { ready: k.reaction_ready } }, { big: true, title: k.name + "'s turn" }),
      h("div", { class: "lbl" }, noActs ? "No actions left this turn" : k.name + "'s moves — tap one, then tap who"),
      out.length ? out : h("p", { class: "faint" }, k.name + " has no attacks."), h("div", { style: "margin-top:6px" }, dismiss));
  }
  /* On their turn: every move they can use right now, as cards like the DM's map panel. Tap one,
     then tap who on the map (or in the list that opens right here). */
  function yourMoves(c) {
    const out = [], noActs = !!(c.actions && !c.actions.left);
    const card = (ic, name, info, run, opts) => h("button", { type: "button", class: "fight-act" + (opts && opts.heal ? " is-heal" : ""),
      disabled: noActs && !(opts && opts.free), onclick: run }, icon(ic, "sm"), h("b", null, name), info ? h("span", { class: "faint" }, info) : null);
    (c.attacks || []).forEach((a) => {
      if (a.recharging) return;
      if (a.extra_moves || a.stance > 1 || a.stance_hit) out.push(card("zap", a.name || "Action Surge", [a.extra_moves ? "+" + a.extra_moves + " moves" : "", a.stance > 1 ? "damage ×" + a.stance : "", (a.stance_hit ? (a.stance_hit > 0 ? "+" : "") + a.stance_hit + " to hit" : "")].filter(Boolean).join(" · ") + " this turn",
        () => me("surge", { index: a.index }).then((d) => { if (d) toast((a.name || "Action Surge") + "!", "ok"); }), { free: true }));
      else if (a.damage && !a.heal) out.push(card("swords", a.name || "Attack", attackInfo(a) + (a.reach ? " · reaches " + a.reach + " ft" : ""),
        () => startUse("attack", a.index, a.name || "Attack", !a.area, 0, a.reach)));
      else if (a.heal || a.ac > 0) out.push(card(a.heal ? "heart" : "shield", a.name || "Heal", a.heal ? "heals " + a.damage.trim() + " · on you or a teammate"
        : "+" + a.ac + " AC · on you or a teammate", () => startHelp(a), { heal: true }));
    });
    ((c.reaction && c.reaction.prime) || []).forEach((r) => { // cast ahead, set off by a hit later (Moni's Absorb Elements)
      out.push(card("flame", r.name, "Cast it now · when you're hit, use your reaction for +" + (r.bonus || "1d12") + " on your next hit",
        () => me("react", { kind: "prime", name: r.name }).then((d) => L.reactionDone(d && d.reaction, c.name, true))));
    });
    (c.surges || []).forEach((g) => { // a spell row with extra actions (Yamato's Action surge)
      if (g.recharging) return;
      out.push(card("zap", g.name, "+" + g.extra_moves + " action" + (g.extra_moves === 1 ? "" : "s") + " this turn" + (g.cooldown ? " · " + g.cooldown + "-turn cooldown" : ""),
        () => me("surge", { spell: g.index }).then((d) => { if (d) { toast(g.name + "! +" + g.extra_moves + " action" + (g.extra_moves === 1 ? "" : "s") + ".", "ok"); if (window.FX) { FX.banner(g.name + "!", "+" + g.extra_moves + " this turn", "crit"); FX.sound("crit"); } } }), { free: true }));
    });
    (c.spells || []).forEach((s) => {
      if (s.recharging) return;
      if (s.clone_swap) { // one card per clone: tap it and you're there
        (c.clones || []).forEach((k) => out.push(card("wand-sparkles", s.name + ": " + k.name, "teleport to its spot · you swap places · 15 ft of movement, no action",
          () => teleportTo(s, k), { free: true })));
        return;
      }
      const info = spellInfo(s, c, c.derived || {});
      if (s.aura) return; // switched on and off from the spells below
      if (s.zone) out.push(card("sun", s.name, info, () => (S.map ? useZone(s) : startUse("spell", s.index, s.name, false, s.targets))));
      else if (aimsAtFoes(s) && s.area && S.map) out.push(card(L.KIND_ICON[s.kind] || "zap", s.name, info, () => startAimUse(s)));
      else if (aimsAtFoes(s)) out.push(card(L.KIND_ICON[s.kind] || "zap", s.name, info, () => startUse("spell", s.index, s.name, s.targets === 1 || !s.area, s.targets)));
      else if (s.terrain && S.map) out.push(card("castle", s.name, info, () => startAimUse(s)));
      else if ((castable(s) || s.summon) && c.can.cast_spells !== false) out.push(card(L.KIND_ICON[s.kind] || "heart", s.name, info, () => startCast(s), { heal: true }));
    });
    if (!out.length) return null;
    return h("div", { class: "fight-acts your-moves", style: "margin-top:10px" },
      h("div", { class: "lbl" }, noActs ? "No actions left this turn" : "Your moves — tap one, then tap who"), out);
  }
  async function dash() {
    const d = await me("dash", {});
    if (!d) return;
    toast("Dashed: you can move " + d.character.move.left + " ft this turn.", "ok");
    if (window.FX) { FX.float($("#me"), "Dash", "ac"); FX.sound("ac"); }
    setPTool("select");
  }

  async function disengage() {
    const d = await me("disengage", {});
    if (!d) return;
    casting = null;
    toast("Disengaged: drag your token away. No opportunity attacks until your turn ends.", "ok");
    if (window.FX) { FX.float($("#me"), "Disengage", "ac"); FX.sound("ac"); }
    setPTool("select");
    const mine = S && S.mapTokens.find((t) => t.own);
    if (mine) { view.selectedId = mine.id; view.draw(); }
  }

  function render() {
    if (L.pressing()) { L.whenUp(render); return; } // not while a button is being pressed
    const a = document.activeElement, keep = a && a.dataset && a.dataset.keep;
    const m = S.map;
    $("#no-map").hidden = !!m;
    if (!m && S.campaign) $("#no-map-title").textContent = S.campaign.replace(/\b\w/g, (x) => x.toUpperCase()); // "The hollow star" -> "The Hollow Star"
    document.body.classList.toggle("no-live-map", !m); // no map shared: the map box shrinks out of the way
    if (m) {
      const ms = JSON.stringify(m) + JSON.stringify(S.mapTokens);
      if (ms !== mapStamp) { if (view.drag) dragMissed = true; else { mapStamp = ms; view.setData(m, S.mapTokens); } }
      const mine = S.mapTokens.find((t) => t.own), k = acting(), pet = k && S.mapTokens.find((t) => t.combatant_id === k.id);
      if (k && view.tool === "select" && !using) $("#hint").textContent = (pet ? (k.move && k.move.held ? k.name + " can't move. " : pet.movable
        ? "Drag " + k.name + " to move it: " + k.move.left + " of " + k.move.budget + " ft left. " : k.name + " has no movement left. ") : "") + "Double-tap to ping.";
      else if (casting && !casting.result && casting.spell.summon) $("#hint").textContent = casting.spell.name + ": tap the square on the map where " + casting.spell.summon + " appears.";
      else if (casting && !casting.result) $("#hint").textContent = "Casting " + casting.spell.name + ": tap who gets it, then Cast.";
      else if (view.tool === "select" && S.character && S.character.disengaged && mine) $("#hint").textContent = "Disengaged: drag your token away. No opportunity attacks this turn.";
      else if (view.tool === "select" && m.fight_starting) $("#hint").textContent = "Enemies! Hold still while the DM rolls initiative.";
      else if (view.tool === "select") $("#hint").textContent = (mine ? moveHint(mine, S.character && S.character.move) : "Drag to look around. ") + "Double-tap to ping.";
      const roaming = !!(mine && mine.roam && mine.movable && !mine.status);
      $("#roam-pad").hidden = !roaming;
      document.body.classList.toggle("roaming", roaming);
    } else { view.map = null; view.draw(); $("#hint").textContent = ""; }

    const e = S.encounter;
    const ch = S.character;
    const fs = m && m.fight_starting;
    $("#turns").replaceChildren(
      m && m.silo ? siloBox(m.silo) : null,
      fs ? h("div", { class: "room-fight" }, h("div", { class: "rf-head" }, icon("swords", "sm"), h("b", null, "Enemies in " + fs.room + "!")),
        h("p", { style: "margin:4px 0 0" }, (fs.what || fs.by + " walked in on them") + ". Hold still: the DM is rolling initiative.")) : null,
      ch && ch.in_fight ? L.reactionBox(ch, (kind, body) => me("react", Object.assign({ kind }, body)), { you: true, burn: !ch.my_turn }) : null,
      ch && ch.in_fight && !ch.my_turn && ch.reaction ? L.turnStrip({ reaction: ch.reaction }, { title: "Off your turn" }) : null,
      h("h3", { class: "rule-head" }, e ? "Round " + e.round : "Turn order"),
      e ? h("ol", { class: "mini-order" }, e.order.map((o) => h("li", { class: (o.is_current ? "is-current" : "") + (o.status === "dead" || o.status === "defeated" ? " is-out" : "") },
        h("span", { class: "i" }, o.init ?? "—"), h("span", { class: "grow" }, o.name),
        o.hp != null ? h("span", { class: "faint num" }, o.hp + "/" + o.max_hp) : o.health ? h("span", { class: "tag is-bad", style: "font-size:.72rem" }, o.health) : null,
        o.status ? h("span", { class: "faint", style: "font-size:.8rem" }, o.status) : null)))
        : h("p", { class: "faint", style: "margin:0" }, "No fight right now."),
      e && e.current ? h("p", { style: "margin:8px 0 0;font-weight:700" }, e.order.some((o) => o.is_current && S.character && o.name === S.character.name) ? "It's your turn!"
        : acting() ? "It's " + acting().name + "'s turn — you control it!" : e.current + "'s turn") : null,
      S.character && S.character.my_turn ? L.turnStrip({ actions: S.character.actions, move: S.character.move, reaction: S.character.reaction }, { big: true, title: "You have" }) : null,
      S.character && S.character.my_turn ? h("div", { style: "margin-top:8px" }, endTurnBtn()) : null,
      S.character && S.character.my_turn ? yourMoves(S.character) : null,
      S.character && S.character.in_fight && S.character.techniques ? L.techniques(S.character.techniques, { key: "phone", run: (body) => me("technique", body) }) : null,

      acting() ? h("div", { style: "margin-top:8px" }, endTurnBtn(acting())) : null,
      acting() ? cloneMoves(acting()) : null,
      using ? useBox() : casting ? castBox() : null);

    const c = S.character;
    if (!c) {
      $("#me").replaceChildren(h("h3", { class: "rule-head" }, "Your character"), h("p", { class: "faint", style: "margin:0" }, "You haven't picked a character. Ask the DM to assign you one — you can still roll dice from the Dice tray."));
    } else {
      const d = c.derived;
      $("#me").replaceChildren(
        h("h3", { class: "rule-head" }, c.name),
        h("div", { class: "faint", style: "margin-top:-4px;margin-bottom:8px" }, [c.race, c.class_name, c.level ? "level " + c.level : ""].filter(Boolean).join(" ")),
        h("div", { class: "row", style: "align-items:baseline;margin-bottom:8px" },
          h("span", { style: "font:700 2rem var(--sans)" }, c.current_hp), h("span", { class: "muted" }, "/ " + c.max_hp + " HP"),
          c.temp_hp ? h("span", { class: "temp", style: "color:var(--temp);font-weight:700" }, "+" + c.temp_hp + " temp") : null,
          h("span", { class: "grow" }), h("span", { title: c.ac_bonus ? "Includes " + signed(c.ac_bonus) + " from effects" : null }, h("b", null, c.ac), " AC", c.ac_bonus ? h("small", { class: "ac-bonus" }, " " + signed(c.ac_bonus)) : null)),
        c.conditions.length ? h("div", { class: "c-conds", style: "margin-bottom:8px" }, c.conditions.map((x) => h("span", { class: "tag" }, x))) : null,
        handoutsPanel(),
        rewindBox(c),
        c.parry && c.parry.pending ? h("div", { class: "parry-box" }, icon("shield", "sm"),
          h("span", { class: "grow" }, h("b", null, "You were hit for " + c.parry.pending.amount + "!"), " " + c.parry.name + ": roll off against the DM. Win and you take " + Math.floor(c.parry.pending.amount / 2) + " instead."),
          h("button", { type: "button", class: "btn btn-primary", onclick: () => me("parry", {}).then((r) => {
            const p = r && r.parry; if (!p) return;
            toast(p.won ? "Parried! " + p.me + " vs " + p.dm + " — you take " + p.taken + " instead of " + p.amount + "." : "The DM wins " + p.dm + " vs " + p.me + " — you take the full " + p.amount + ".", p.won ? "ok" : "error", { ms: 7000 });
            if (window.FX) { FX.banner(p.won ? "Parried!" : "Parry failed", p.me + " vs " + p.dm, p.won ? "heal" : "dmg"); FX.sound(p.won ? "ac" : "hit"); }
            if (window.Dice && Dice.poll) Dice.poll();
          }) }, c.parry.name + "!")) : null,
        c.can.edit_hp ? hpControls(c) : null,
        extras(c),
        h("div", { class: "row", style: "margin-bottom:10px" },
          h("button", { type: "button", class: "btn btn-sm", onclick: (ev) => roll({ type: "initiative" }, ev) }, icon("dice-5", "sm"), " Initiative " + signed(d.initiative)),
          c.current_hp === 0 && !["dead", "stable"].includes(c.status) ? h("button", { type: "button", class: "btn btn-sm btn-primary",
            title: "10 or more is a success. A friend standing right next to you on the map gives you a bonus.", onclick: () => me("death-save", {}) }, icon("dice-5", "sm"), " Roll death save") : null,
          c.move && c.move.my_turn ? h("button", { type: "button", class: "btn btn-sm" + (c.move.dash ? " is-armed" : ""), disabled: c.move.dash,
            title: "Double your movement this turn", onclick: dash }, icon("zap", "sm"), c.move.dash ? " Dashed" : " Dash") : null,
          c.in_fight ? h("button", { type: "button", class: "btn btn-sm" + (c.disengaged ? " is-armed" : ""), disabled: c.disengaged,
            title: "Move away this turn without opportunity attacks", onclick: disengage }, icon("compass", "sm"), c.disengaged ? " Disengaged — move away" : " Disengage") : null,
          d.spell ? h("button", { type: "button", class: "btn btn-sm", onclick: (ev) => roll({ type: "spell_attack" }, ev) }, "Spell attack " + signed(d.spell.attack)) : null),
        h("div", { class: "stats" }, ABIL.map(([k, label]) => h("button", { type: "button", class: "stat", title: "Roll a " + label + " check", onclick: (ev) => roll({ type: "ability", key: k }, ev) },
          h("b", null, signed(d.mods[k])), h("span", null, label)))),
        c.attacks.length ? [h("h4", { class: "lbl", style: "margin:12px 0 4px" }, "Attacks"),
          c.my_turn === false ? h("p", { class: "faint", style: "margin:0 0 6px;font-size:.88rem" }, "Attacks unlock on your turn.") : null,

          c.my_turn ? h("div", { style: "margin:0 0 8px" }, endTurnBtn()) : null,
          c.actions ? h("p", { class: "actions-left" + (c.actions.left ? "" : " is-out"), style: "margin:0 0 6px;font-size:.88rem;font-weight:700" },
            c.actions.left ? "Actions left this turn: " + c.actions.left + " of " + c.actions.limit : "No actions left this turn" + (c.actions.extra ? "" : " (Action Surge gives more)")) : null,
          ...c.attacks.map((a) => a.recharging ? moveCard(a.heal ? "heart" : "swords", a.name || "Attack", attackInfo(a),
          h("span", { class: "tag" }, icon("hourglass", "sm"), (() => { const w = Math.max(0, a.recharging - (c.my_turn ? 1 : 0)); if (w > 500) return " used this fight · back next fight"; return w ? " recharging · ready in " + w + " turn" + (w === 1 ? "" : "s") : " recharging · ready next turn"; })()))
          : c.my_turn === false ? moveCard(a.heal ? "heart" : "swords", a.name || "Attack", attackInfo(a), h("span", { class: "faint", style: "font-size:.85rem" }, "wait for your turn" + (a.cooldown ? " · " + a.cooldown + "-turn cooldown" : "")))
          : moveCard(a.heal ? "heart" : "swords", a.name || "Attack", attackInfo(a),
          a.cooldown ? h("span", { class: "faint", style: "font-size:.8rem" }, a.cooldown + "-turn cooldown") : null,
          a.extra_moves || a.stance > 1 || a.stance_hit ? h("button", { type: "button", class: "btn btn-sm btn-primary", title: "On yourself, for the rest of your turn",
            onclick: () => me("surge", { index: a.index }).then((d) => {
              if (!d) return;
              const what = [a.extra_moves ? a.extra_moves + " extra moves" : "", a.stance > 1 ? "damage ×" + a.stance : ""].filter(Boolean).join(" and ");
              toast(a.name + ": " + what + " this turn!", "ok");
              if (window.FX) { FX.banner(a.name + "!", what, "crit"); FX.sound("crit"); }
            }) },
            icon("zap", "sm"), " " + (a.name || "Action Surge")) : null,
          c.my_turn && a.damage && !a.heal ? useBtn("attack", a.index, a.name || "Attack", !a.area, 0, a.reach) :
          a.bonus ? h("button", { type: "button", class: "btn btn-sm", onclick: attackThen({ type: "attack", key: a.index }, a.damage && !a.heal ? { type: "damage", key: a.index } : null) }, "Hit " + a.bonus) : null,
          a.damage && !(c.my_turn && !a.heal) ? h("button", { type: "button", class: "btn btn-sm" + (a.heal ? " btn-heal" : ""), onclick: (ev) => roll({ type: "damage", key: a.index }, ev) },
            a.heal ? "Heal" : a.dmg_mult > 1 ? "Dmg ×" + a.dmg_mult : "Dmg") : null))] : null,
        (c.spells || []).length ? [h("h4", { class: "lbl", style: "margin:12px 0 4px" }, "Spells"),

          ...c.spells.map((s) => s.rewind ? moveCard("history", s.name, [L.spellWhat(s)].filter(Boolean).join(" · "), rewindBtn(c))
          : s.clone_swap ? moveCard("wand-sparkles", s.name, "Teleport to one of your clones (you swap places) · 15 ft of movement, no action" + (s.cooldown ? " · " + s.cooldown + "-turn cooldown" : ""), ...teleportBtns(s, c)) : moveCard(L.KIND_ICON[s.kind] || "zap", s.name, spellInfo(s, c, d),
          c.my_turn && s.zone && !s.recharging ? h("button", { type: "button", class: "btn btn-sm btn-primary", disabled: !!(c.actions && !c.actions.left),
            title: "It rises around you: enemies in it are hit, and it stays up",
            onclick: () => (S.map ? useZone(s) : startUse("spell", s.index, s.name, false, s.targets)) }, icon("sun", "sm"), " Use") : // no map: tap who's in it
          c.my_turn && aimsAtFoes(s) && !s.recharging && s.area && S.map ? h("button", { type: "button", class: "btn btn-sm btn-primary", disabled: !!(c.actions && !c.actions.left),
            title: "Aim it on the map, then Use", onclick: () => startAimUse(s) }, icon("swords", "sm"), " Use") :
          c.my_turn && aimsAtFoes(s) && !s.recharging ? useBtn("spell", s.index, s.name, s.targets === 1 || !s.area, s.targets) :
          s.kind === "damage" && (s.hit === "attack" || c.roll_to_hit) && d.spell ? h("button", { type: "button", class: "btn btn-sm",
            onclick: attackThen({ type: "spell_attack" }, s.dice ? { type: "spell", key: s.index } : null) }, "Attack " + signed(d.spell.attack)) : null,
          s.kind === "damage" && s.dice && !(c.my_turn && aimsAtFoes(s)) ? h("button", { type: "button", class: "btn btn-sm", onclick: (ev) => roll({ type: "spell", key: s.index }, ev) }, "Dmg") : null,
          s.hit && s.hit !== "attack" && (!c.roll_to_hit || s.force_save) ? h("span", { class: "tag" }, s.hit.toUpperCase() + " save" + (s.dc ? " DC " + s.dc : d.spell ? " DC " + d.spell.dc : "")) : null,
          s.aura ? L.auraButton(s, "/api/play/me/aura", () => load(true))
          : s.terrain ? h("span", { class: "tag", title: "Ask the DM: it's aimed on the battle map" }, icon("map", "sm"), " the DM aims it on the map")
          : s.recharging ? h("span", { class: "tag" }, icon("hourglass", "sm"), (() => { const w = Math.max(0, s.recharging - (c.my_turn ? 1 : 0)); if (w > 50000) return " used · back after a long rest"; if (w > 500) return " used this fight · back next fight"; return w ? " recharging · ready in " + w + " turn" + (w === 1 ? "" : "s") : " recharging · ready next turn"; })())
          : castable(s) && c.can.cast_spells !== false
            ? h("button", { type: "button", class: "btn btn-sm btn-heal" + (casting && casting.index === s.index ? " is-armed" : ""), title: "Then tap who gets it",
              onclick: () => startCast(s) }, icon(s.kind === "heal" ? "heart" : "shield-plus", "sm"), " Cast · " + (L.spellWhat(s) || s.name))
            : s.kind === "debuff" && !c.my_turn ? h("span", { class: "tag", title: "On your turn" }, L.spellWhat(s) || "debuff") : null))] : null,
        !c.in_fight && c.techniques ? L.techniques(c.techniques, { key: "phone-sheet", run: (body) => me("technique", body) }) : null,
        inventoryBox(c.inventory),
        h("details", { class: "roll-fold", open: rollsOpen, ontoggle: (e) => { rollsOpen = e.target.open; } },
          h("summary", { class: "lbl" }, "Saving throws & skills"),
          h("h4", { class: "lbl", style: "margin:12px 0 4px" }, "Saving throws"),
          h("div", { class: "roll-grid" }, ABIL.map(([k, label]) => h("button", { type: "button", onclick: (ev) => roll({ type: "save", key: k }, ev) }, h("span", null, label), h("b", null, signed(d.saves[k]))))),
          h("h4", { class: "lbl", style: "margin:12px 0 4px" }, "Skills"),
          h("div", { class: "roll-grid" }, SKILLS.map(([k, label]) => h("button", { type: "button", onclick: (ev) => roll({ type: "skill", key: k }, ev) }, h("span", null, label), h("b", null, signed(d.skills[k])))))),
        h("details", { class: "dice-fold", open: diceOpen, ontoggle: (e) => { diceOpen = e.target.open; } },
          h("summary", { class: "lbl" }, "My dice colors"),
          h("p", { class: "faint", style: "margin:6px 0 8px;font-size:.88rem" }, "Everyone sees your rolls in these dice."),
          L.diceColors({ style: c.dice_style, onChange: async (style) => {
            try { await api("POST", "/api/play/me/dice", Object.assign({ op_id: L.uid() }, style || {})); toast("Dice colors saved.", "ok"); }
            catch (e) { toast(e.message, "error"); }
            load(true);
          } })));
    }
    if (keep) { const el = document.querySelector('[data-keep="' + keep + '"]'); if (el) el.focus(); }
    newHandouts();
    L.bossBar(e ? e.order.filter((o) => o.boss && o.status !== "fled")
      .map((o) => ({ id: o.id, name: o.name, frac: (o.quarters || 0) / 4, text: "", phase: o.phase, portrait: o.portrait,
        tagline: o.tagline || "", fresh: !!o.fresh, down: !o.quarters || ["dead", "defeated"].includes(o.status) })) : []);
    $("#party").replaceChildren(c ? "" : handoutsPanel() || "", h("h3", { class: "rule-head" }, "Party"),
      h("ul", { class: "stack-list" }, S.party.map((p) => h("li", null, h("div", { class: "row", style: "justify-content:space-between" },
        h("b", null, p.name), h("span", { class: "num" }, p.current_hp + "/" + p.max_hp + (p.temp_hp ? " +" + p.temp_hp : ""))),
        p.conditions.length || p.status !== "ok" ? h("div", { class: "faint", style: "font-size:.85rem" }, [p.status !== "ok" ? p.status : "", ...p.conditions].filter(Boolean).join(", ")) : null))));
  }

  /* Inventory: what the character carries (from their sheet), coins and weight. Read only here;
     the DM edits it on the sheet, and things taken from chests land in it. */
  let invOpen = (() => { try { return localStorage.getItem("inv-open") !== "0"; } catch (e) { return true; } })();
  async function useItem(it) { // a healing item (Stim injector, Med-gel patch): rolled by the server, on yourself
    const d = await me("item", { index: it.index });
    if (d && d.roll) { toast(it.name + ": " + (d.roll.outcome || "used") + ".", "ok"); if (window.FX) { FX.float($("#me"), "+" + Math.max(0, d.roll.total), "heal"); FX.sound("heal"); } }
  }
  function inventoryBox(inv) {
    if (!inv) return null;
    const items = inv.items || [], coins = Object.entries(inv.coins || {});
    const ORDER = ["pp", "gp", "ep", "sp", "cp"];
    coins.sort((a, b) => ORDER.indexOf(a[0]) - ORDER.indexOf(b[0]));
    const heavy = inv.capacity && inv.carried > inv.capacity * 0.8;
    return h("details", { class: "inv-fold", id: "inventory", open: invOpen,
      ontoggle: (e) => { invOpen = e.target.open; try { localStorage.setItem("inv-open", invOpen ? "1" : "0"); } catch (x) {} } },
      h("summary", { class: "lbl" }, "Inventory ", h("span", { class: "count" }, items.length + " item" + (items.length === 1 ? "" : "s"))),
      h("div", { class: "inv-meta" },
        h("span", { class: "inv-coins" }, icon("coins", "sm"), " ",
          coins.length ? coins.map(([k, n]) => h("span", { class: "coin-amt" }, h("b", null, n), " " + k)) : h("span", { class: "faint" }, "no coins")),
        inv.capacity ? h("span", { class: "inv-weight" + (heavy ? " is-heavy" : ""), title: "What you carry, of what you can carry (Strength × 15)" },
          inv.carried + " / " + inv.capacity + " lb") : null),
      items.length ? h("ul", { class: "inv-list" }, items.map((it) => {
        const r = it.rarity && L.RARITY[it.rarity];
        return h("li", { class: "inv-item" + (r ? " rarity-" + it.rarity : ""), style: r ? "--rarity:" + r[1] : null },
          h("div", { class: "inv-top" },
            h("b", { class: "inv-name" }, it.name + (it.qty > 1 ? " ×" + it.qty : "")),
            r ? h("span", { class: "tag inv-rarity" }, r[0]) : null,
            it.weight ? h("span", { class: "faint inv-lb" }, Math.round(it.weight * it.qty * 10) / 10 + " lb") : null),
          it.notes ? h("div", { class: "faint inv-notes" }, it.notes) : null,
          it.heal ? h("div", { class: "row inv-use", style: "gap:6px;align-items:center;margin-top:4px" },
            h("button", { type: "button", class: "btn btn-sm btn-heal", disabled: !!(it.heal.charges && !it.heal.charges.left),
              title: "Use it on yourself: heals " + it.heal.dice, onclick: () => useItem(it) }, icon("heart", "sm"), " Use · heals " + it.heal.dice),
            h("span", { class: "faint", style: "font-size:.8rem" }, [
              { action: "an action on your turn in a fight", bonus: "a bonus action on your turn in a fight", any: "" }[it.heal.when],
              it.heal.uses ? it.heal.uses.left + " of " + it.heal.uses.total + " uses left" : "",
              it.heal.charges ? it.heal.charges.left + " of " + it.heal.charges.total + " charges (back after a long rest)" : ""].filter(Boolean).join(" · "))) : null);
      })) : h("p", { class: "faint", style: "margin:6px 0" }, "Your pack is empty."));
  }

  /* Notes and handouts (DM letters, papers found on the map). The server remembers which ones this
     character has read, so it's the same on every phone and browser. Opening the game never pops
     anything up: unread ones are marked New in the list. Only a note that arrives while this page
     is open (a paper you just picked up, a letter the DM just sent) pops up, one at a time. */
  let handoutOpen = null;
  let handoutsAtLoad = null;   // uids already there when the page first loaded: these never pop up
  const handoutQueue = [];     // arrived while open and not read yet: shown one after another
  function markRead(x) {
    if (x.read) return;
    x.read = true;
    api("POST", "/api/play/handouts/" + x.id + "/read", { op_id: L.uid() }).catch(() => { x.read = false; });
  }
  function showHandout(x) {
    if (handoutOpen) handoutOpen.remove();
    markRead(x);
    const close = () => { ov.remove(); handoutOpen = null; refreshHandoutsPanel(); setTimeout(newHandouts, 300); };
    const ov = h("div", { class: "handout-pop", role: "dialog", "aria-modal": "true", "aria-label": x.title || "Handout", onclick: (e) => { if (e.target === ov) close(); } },
      h("div", { class: "handout-card" },
        h("div", { class: "handout-head" }, icon("scroll-text", "sm"), h("b", null, x.title || "A handout from the DM")),
        x.image ? h("img", { src: "/api/uploads/" + x.image, alt: x.title || "Handout picture" }) : null,
        x.body ? h("div", { class: "handout-text" }, x.body) : null,
        h("button", { type: "button", class: "btn btn-primary", onclick: close }, "Close")));
    document.body.append(ov);
    handoutOpen = ov;
    if (window.FX) FX.sound("ac");
  }
  let handoutsAll = false;     // the list shows the newest few until "Show all" is tapped
  const HANDOUTS_SHOWN = 5;
  function handoutsPanel() {
    const list = S.handouts || [];   // newest first
    if (!list.length) return null;
    const unread = list.filter((x) => !x.read).length;
    // unread ones first (so they're never hidden behind "Show all"), then the rest, newest first
    const ordered = list.filter((x) => !x.read).concat(list.filter((x) => x.read));
    const shown = handoutsAll ? ordered : ordered.slice(0, Math.max(HANDOUTS_SHOWN, unread));
    return h("div", { class: "handout-list", "data-handouts": "" },
      h("h3", { class: "rule-head" }, "Notes & handouts ", h("span", { class: "count" }, String(list.length)),
        unread ? h("span", { class: "tag handout-new" }, unread + " new") : null),
      h("ul", { class: "stack-list" }, shown.map((x) => h("li", null, h("button", { type: "button", class: "linkish" + (x.read ? "" : " handout-unread"), onclick: () => showHandout(x) },
        x.image ? icon("image", "sm") : icon("scroll-text", "sm"), " " + (x.title || "Handout"),
        x.read ? null : h("span", { class: "tag handout-new" }, "New"))))),
      shown.length < ordered.length ? h("button", { type: "button", class: "linkish faint", onclick: () => { handoutsAll = true; refreshHandoutsPanel(); } },
        "Show all " + ordered.length) : null);
  }
  function refreshHandoutsPanel() {
    const old = document.querySelector("[data-handouts]"), next = handoutsPanel();
    if (old && next) old.replaceWith(next);
  }
  function newHandouts() {
    const list = S.handouts || [];
    if (handoutsAtLoad === null) { handoutsAtLoad = new Set(list.map((x) => x.uid)); return; } // first load: no pop-ups
    for (const x of list.slice().reverse()) {          // oldest of the new ones first
      if (handoutsAtLoad.has(x.uid)) continue;
      handoutsAtLoad.add(x.uid);
      if (!x.read) handoutQueue.push(x.uid);
    }
    if (handoutOpen) return;
    while (handoutQueue.length) {
      const x = list.find((y) => y.uid === handoutQueue[0]);
      handoutQueue.shift();
      if (x && !x.read) { showHandout(x); return; }   // (read on another device meanwhile: skip it)
    }
  }
  /* ---- chests and sealed doors next to your hero ---------------------------------------------
     A chest opens from here (or by tapping it on the map) when your hero stands next to it; the loot
     pops up and each thing goes onto your sheet with Take. Sealed doors open with the right card. */
  let lootOpen = null; // the chest whose loot is showing
  const myToken = () => ((S && S.mapTokens) || []).find((t) => t.own && !t.pet);
  function nextTo(t, x, y) {
    const tx = Math.round(t.x), ty = Math.round(t.y);
    return Math.max(Math.max(0, x - (tx + t.size - 1), tx - x), Math.max(0, y - (ty + t.size - 1), ty - y)) <= 1;
  }
  const DOOR_WORD = { sealed: "Sealed door", panel: "A wall panel that looks loose" };
  function nearby() {
    const box = $("#nearby"), t = myToken(), m = S && S.map;
    if (!box) return;
    if (!t || !m) { box.hidden = true; return; }
    const chests = (m.chests || []).filter((c) => nextTo(t, c.x, c.y));
    const doors = Object.entries(m.terrain || {}).filter(([, v]) => DOOR_WORD[v]).map(([k, v]) => [k.split(",").map(Number), v])
      .filter(([[x, y]]) => nextTo(t, x, y));
    box.hidden = !chests.length && !doors.length;
    if (box.hidden) return;
    box.replaceChildren(h("h3", { class: "rule-head" }, "Next to you"),
      ...chests.map((c) => SILO_WORD[c.kind] ? siloRow(c) : h("div", { class: "nearby-row" }, icon(L.CHEST_ICON[c.kind] || "backpack", "sm"),
        h("span", { class: "grow" }, c.name, c.opened ? h("span", { class: "faint" }, c.loot && c.loot.length ? " · open" : " · empty")
          : c.locked_by ? h("span", { class: "chest-lock" }, " · needs a " + c.locked_by) : null),
        h("button", { type: "button", class: "btn btn-sm btn-primary", "data-chest": c.id, onclick: () => openChest(c) }, c.kind === "papers" ? "Read" : c.opened ? "Look inside" : "Open"))),
      ...doors.map(([[x, y], v]) => h("div", { class: "nearby-row" }, icon("key-round", "sm"), h("span", { class: "grow" }, DOOR_WORD[v]),
        h("button", { type: "button", class: "btn btn-sm", "data-door": x + "," + y, onclick: () => openDoor(x, y) }, v === "panel" ? "Push it" : "Use a card"))));
  }
  // the missile silo's launch bay: turn an abort key, or stop Steven at his lift (app/silo.py)
  const SILO_WORD = { abort: ["Turn the key", "Turned"], escape: ["Stop him!", "Reached"] };
  function siloRow(c) {
    const s = S.map && S.map.silo, over = !!(s && s.outcome), [go, done] = SILO_WORD[c.kind];
    return h("div", { class: "nearby-row" }, icon(L.CHEST_ICON[c.kind], "sm"),
      h("span", { class: "grow" }, c.kind === "escape" ? "Steven Voss's escape lift" : c.name,
        h("span", { class: "faint" }, c.opened ? " · " + done.toLowerCase() : c.kind === "escape" ? " · the missiles will launch" : "")),
      h("button", { type: "button", class: "btn btn-sm " + (c.kind === "escape" ? "btn-danger" : "btn-primary"), "data-chest": c.id, disabled: c.opened || over,
        onclick: async (ev) => {
          ev.currentTarget.disabled = true;
          try { await api("POST", "/api/play/chests/" + c.id + "/open", {}); if (window.FX) FX.sound(c.kind === "escape" ? "start" : "ac"); }
          catch (e) { toast(e.message, "error"); if (window.FX) FX.sound("denied"); }
          load(true);
        } }, c.opened ? done : go));
  }
  function siloBox(s) {
    if (!s) return null;
    const end = { aborted: "The missiles are down. Steven got away.", caught: "The missiles launched. You have Steven Voss.",
      timeout: "The missiles launched, and Steven got away." }[s.outcome];
    if (end) return h("div", { class: "room-fight silo-box is-over" }, h("div", { class: "rf-head" }, icon("flag", "sm"), h("b", null, end)));
    return h("div", { class: "room-fight silo-box" },
      h("div", { class: "rf-head" }, icon("flame", "sm"), h("b", null, s.rounds_left == null ? "Three missiles, ready to launch" : "LAUNCH IN " + s.rounds_left + " ROUND" + (s.rounds_left === 1 ? "" : "S"))),
      h("p", { style: "margin:4px 0 0" }, "Abort keys turned: " + s.keys + " of " + s.keys_total + ". Turn all of them to stop the launch, or reach Steven's escape lift to catch him."));
  }
  async function openChest(c) {
    if (!c.opened) {
      try { c = (await api("POST", "/api/play/chests/" + c.id + "/open", {})).chest; }
      catch (e) { toast(e.message, "error"); if (window.FX) FX.sound("denied"); return; }
    }
    if (c.kind === "papers") { // loose papers: you read them (a handout pops up); only anything clipped to them shows here
      if (!(c.loot || []).some((i) => i.type !== "note")) { load(true); return; }
    }
    lootOpen = c.id; showLoot(c); load(true);
  }
  function showLoot(c) {
    let pop = $("#loot-pop");
    if (!pop) {
      pop = h("div", { class: "loot-pop", id: "loot-pop", role: "dialog", "aria-modal": "true", "aria-label": "What's inside" });
      pop.addEventListener("click", (e) => { if (e.target === pop) closeLoot(); });
      document.body.append(pop);
    }
    const items = (c.loot || []).filter((i) => c.kind !== "papers" || i.type !== "note"); // the paper itself is a handout
    pop.dataset.stamp = JSON.stringify(items);
    const take = async (body, btn) => {
      if (btn) btn.disabled = true;
      try {
        const r = await api("POST", "/api/play/chests/" + c.id + "/take", body);
        if (r.took.length) { toast("On your sheet now: " + r.took.map((i) => i.name).join(", "), "ok"); if (window.FX) FX.sound("heal"); }
        if (r.why && r.why.length) toast(r.why[0], "error");
        showLoot(Object.assign({}, c, { loot: r.left })); load(true);
      } catch (e) { toast(e.message, "error"); if (btn) btn.disabled = false; load(true); }
    };
    pop.replaceChildren(h("div", { class: "loot-box" },
      h("h3", null, icon(L.CHEST_ICON[c.kind] || "backpack", "sm"), c.name),
      c.opened_by ? h("p", { class: "faint", style: "margin:0" }, "Opened by " + c.opened_by + ".") : null,
      L.lootList(items, { take: (it, btn) => take({ item: it.id }, btn), empty: "Nothing left inside." }),
      h("div", { class: "row", style: "gap:6px;margin-top:10px;justify-content:flex-end" },
        items.length > 1 ? h("button", { type: "button", class: "btn btn-primary", id: "take-all", onclick: (e) => take({ item: "all" }, e.currentTarget) }, "Take all") : null,
        h("button", { type: "button", class: "btn", id: "loot-close", onclick: closeLoot }, "Close"))));
  }
  function closeLoot() { lootOpen = null; const p = $("#loot-pop"); if (p) p.remove(); }
  function refreshLoot() { // someone else took something: keep the pop-up honest
    if (!lootOpen) return;
    const c = ((S.map && S.map.chests) || []).find((x) => x.id === lootOpen), pop = $("#loot-pop");
    if (!c || !pop) { closeLoot(); return; }
    if (pop.dataset.stamp !== JSON.stringify(c.loot || [])) showLoot(c);
  }
  async function openDoor(x, y) {
    try { const r = await api("POST", "/api/play/doors", { x, y }); toast("Open: " + r.opened, "ok"); if (window.FX) FX.sound("door"); load(true); }
    catch (e) { toast(e.message, "error"); if (window.FX) FX.sound("denied"); }
  }
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && lootOpen) closeLoot(); });

  async function load(force) {
    if (!force && document.hidden) return;
    if (!force && view.drag) { dragMissed = true; return; } // comes through when they let go
    const seq = ++loadSeq;
    try {
      const d = await api("GET", "/api/play/state");
      if (!force && window.Dice && Dice.settle) await Dice.settle(); // HP and results after the dice land
      if (seq < loadDone || movesPending) return; // something newer already showed: an old reply mustn't undo it
      loadDone = seq;
      d.mapTokens = [];
      let pings = [], zones = [];
      if (d.map) { const { map, tokens } = d.map; pings = d.map.pings || []; zones = d.map.zones || []; d.map = map; d.mapTokens = tokens; }
      // pings first: they change every poll, so they're kept out of the "did anything change" check
      const fresh = pings.filter((p) => !view.seenPings.has(p.id) && !p.fx && p.by !== (S && S.me ? S.me.name : ""));
      view.setPings(pings);
      view.setZones(zones);
      if (fresh.length && window.FX) FX.sound("ping");
      const s = JSON.stringify(d);
      setStatus(true);
      if (s === stamp) return;
      const before = S;
      stamp = s; S = d; render(); nearby(); refreshLoot();
      celebrate(before, d);
    } catch (e) {
      setStatus(false, e);
      if (e.status === 401) location.href = "/join";
    }
  }
  // effects when your HP changes or the turn comes round
  function celebrate(before, now) {
    if (!before || !window.FX) return;
    const a = before.character, b = now.character;
    if (a && b && a.id === b.id && a.current_hp !== b.current_hp) {
      const diff = b.current_hp - a.current_hp, box = $("#me");
      FX.float(box, (diff > 0 ? "+" : "−") + Math.abs(diff), diff > 0 ? "heal" : "dmg");
      FX.flash(box, diff > 0 ? "heal" : "hit");
      FX.sound(diff > 0 ? "heal" : "hit");
      if (b.current_hp === 0 && a.current_hp > 0) { FX.banner("You're down!", "Knocked prone · roll death saves on your turn", "down"); FX.sound("down"); }
    }
    if (a && b && (b.ac || 0) > (a.ac || 0)) { FX.float($("#me"), "+" + (b.ac - a.ac) + " AC", "ac"); FX.sound("ac"); }
    const key = (o) => o.kind + ":" + (o.vs || o.amount || "");
    const had = new Set((((a && a.reaction) || {}).offers || []).map(key));
    const fresh = (((b && b.reaction) || {}).offers || []).filter((o) => !had.has(key(o)) && o.kind !== "redirect");
    if (fresh.length) {
      const o = fresh[0];
      FX.banner("Reaction!", o.kind === "sentinel" ? o.vs_name + " attacked next to you — " + o.name + "?" : o.name + "?", "crit"); FX.sound("yourturn");
      toast(o.kind === "sentinel" ? o.vs_name + " attacked " + ((o.on || []).join(", ") || "someone") + " next to you." : "You were hit for " + o.amount + ".", "ok",
        { ms: 12000, action: { label: (o.kind === "sentinel" ? "Strike " + o.vs_name : o.name) + " (reaction)",
          run: () => me("react", { kind: o.kind }).then((d) => L.reactionDone(d && d.reaction, b.name, true)) } });
      const box = document.querySelector("#turns .react-box"); if (box) box.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
    const f0 = before.map && before.map.fight_starting, f1 = now.map && now.map.fight_starting;
    if (f1 && (!f0 || f0.at !== f1.at)) { FX.banner("Enemies!", f1.what || f1.by + " walks into " + f1.room, "dmg"); FX.sound("bossintro"); FX.flash($("#turns"), "hit"); }
    if (before.map && now.map && before.map.id !== now.map.id) { // down the stairs (or the DM showed another map)
      FX.descend(now.map.name || "A new map", "You arrive somewhere new");
    }
    const ea = before.encounter, eb = now.encounter;
    if (eb && eb.current && (!ea || ea.current !== eb.current || ea.round !== eb.round)) {
      const mine = b && eb.order.some((o) => o.is_current && o.name === b.name);
      if (mine) { FX.banner("Your turn!", "Round " + eb.round, "crit"); FX.sound("yourturn"); FX.flash($("#me"), "turn"); }
      else { FX.banner(eb.current + "'s turn", "Round " + eb.round, "info"); FX.sound("turn"); }
    }
  }
  function setStatus(ok, err) {
    const el = $("#save-status");
    if (!el) return;
    el.dataset.state = ok ? "saved" : "error";
    $(".save-text", el).textContent = ok ? "Connected" : "Lost connection — retrying";
  }
  $("#leave").addEventListener("click", async () => {
    if (!$("#leave").classList.contains("is-armed")) { $("#leave").classList.add("is-armed"); $("#leave").textContent = "Click again to leave"; return; }
    await api("POST", "/api/play/leave"); location.href = "/join";
  });
  load(true);
  const polled = {};
  setInterval(() => { if (L.live.due(polled)) load(); }, 1500); // a fallback check (instant updates do the rest)
  L.live.on(() => load());
  document.addEventListener("visibilitychange", () => { if (!document.hidden) load(); }); // back from a locked phone
})();
