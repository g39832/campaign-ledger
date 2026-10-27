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

  const view = new MapView($("#stage"), {
    role: "player",
    imageUrl: (m) => m.image_url,
    canMove: (t) => t.movable && !casting && !using,
    reach: (t) => (t.own && S && S.character && S.character.move && S.character.move.my_turn ? S.character.move.left : null),
    onSelect: (t) => { // tap a token to cast on them, or to aim an attack at an enemy
      if (casting && t && t.character_id) pick(t.character_id);
      else if (using && t) pickFoe(t.combatant_id, t.display);
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
      try { await api("POST", "/api/play/tokens/" + t.id + "/move", { x, y }); }
      catch (e) { toast(e.message, "error"); }
      load(true);
    },
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
  const myCb = () => { const e = S.encounter, me = S.character; return e && me ? (e.order.find((o) => o.character_id === me.id) || {}).id : null; };
  const teammates = () => ((S.encounter && S.encounter.order) || []).filter((o) => o.kind !== "enemy" && o.id !== myCb() && !["dead", "defeated", "fled"].includes(o.status));
  function startUse(what, index, name, single, max, reach) {
    casting = null;
    using = { what, index, name, single, max: max || 0, reach: reach || null, chosen: new Set(), busy: false, result: null };
    render();
    const box = $("#use-box");
    if (box) box.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }
  function pickFoe(cbId, label) {
    if (!using || using.busy || using.result) return;
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
    const toks = (S && S.mapTokens) || [], me = toks.find((t) => t.own), them = toks.find((t) => t.combatant_id === cbId);
    if (!me || !them || !S.map) return null;
    const gx = Math.max(0, them.x - (me.x + me.size), me.x - (them.x + them.size)), gy = Math.max(0, them.y - (me.y + me.size), me.y - (them.y + them.size));
    const per = !S.map.scale_unit || S.map.scale_unit === "ft" ? Number(S.map.scale_value) || 5 : 5;
    return (Math.ceil(Math.max(gx, gy) - 1e-6) + 1) * per;
  }
  const tooFar = (cbId) => { if (!using || !using.reach) return 0; const d = feetTo(cbId); return d != null && d > using.reach ? d : 0; };
  async function useNow() {
    const k = using;
    if (!k || k.busy || !k.chosen.size) return;
    k.busy = true; render();
    try {
      const d = await api("POST", "/api/play/me/use", { what: k.what, index: k.index, targets: [...k.chosen], op_id: L.uid() });
      k.result = d.cast || null;
      if (d.cast && window.Dice && Dice.showAll) Dice.showAll(d.cast.rolls || []);
      const hows = d.cast ? d.cast.targets.map((t) => t.how) : [];
      const missed = hows.length && hows.every((x) => x === "miss" || x === "saved");
      if (window.FX) { FX.banner(missed ? "Missed" : hows.includes("crit") ? "Critical hit!" : "Hit!", k.name, missed ? "dmg" : "crit"); FX.sound(missed ? "miss" : "hit"); }
    } catch (e) { toast(e.message, "error"); k.busy = false; k.chosen.clear(); render(); return; }
    k.busy = false;
    load(true);
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
      using.result = d.cast || null;
      if (d.cast && window.Dice && Dice.showAll) Dice.showAll(d.cast.rolls || []);
      if (window.FX) { FX.banner(s.name + "!", d.cast && d.cast.targets.length ? d.cast.targets.length + " caught in it" : "no enemies in it yet", "crit"); FX.sound("crit"); }
    } catch (e) { toast(e.message, "error"); using = null; }
    if (using) using.busy = false;
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
  const useBtn = (what, index, name, single, max, reach) => h("button", { type: "button", class: "btn btn-sm btn-primary" + (using && using.what === what && using.index === index ? " is-armed" : ""),
    disabled: !!(S.character && S.character.actions && !S.character.actions.left),
    title: "Then tap an enemy", onclick: () => startUse(what, index, name, single, max, reach) }, icon("swords", "sm"), " Use");
  const aimsAtFoes = (s) => (s.kind === "damage" || s.kind === "debuff") && !s.terrain && !s.aura && !s.summon && !L.spellHelps(s);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && using && !using.busy) { using = null; render(); } });

  // ---- casting a healing or buff spell on someone in the party ------------------------------
  // Tap the spell, tap who it's for (here or their token on the map), then Cast. The server rolls it.
  const castable = (s) => L.spellHelps(s) && !s.terrain; // map-changing spells are aimed by the DM
  function startCast(s) {
    const mine = S.character, chosen = new Set();
    if (s.targets === 1 && /\bself\b/i.test(s.notes || "") && mine) chosen.add(mine.id);
    casting = { spell: L.spellView(s), index: s.index, chosen, slot: s.level || null, busy: false, result: null };
    render();
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
      const d = await api("POST", "/api/play/cast", { spell: k.index, targets: [...k.chosen], slot: k.slot, op_id: L.uid() });
      k.result = d.cast || null;
      if (d.cast && window.Dice && Dice.showAll) Dice.showAll(d.cast.rolls || []);
      const healing = k.spell.kind === "heal";
      if (window.FX) { FX.float($("#party"), healing && d.roll ? "+" + d.roll.total : "✦", healing ? "heal" : "ac"); FX.sound(healing ? "heal" : "ac"); }
    } catch (e) { toast(e.message, "error"); }
    k.busy = false;
    load(true);
  }
  function castBox() {
    const mine = S.character, k = casting;
    const people = S.party.map((p) => ({ id: p.id, ally: true,
      name: p.id === (mine && mine.id) ? p.name + " (you)" : p.name, info: p.current_hp + "/" + p.max_hp + " HP" }));
    const slots = mine && Object.fromEntries(Object.entries(mine.spell_slots || {}).filter(([, v]) => v && v.max > 0));
    return h("div", { id: "cast-box" }, L.castPanel({ spell: k.spell, people, chosen: k.chosen, busy: k.busy, result: k.result,
      slots: slots && Object.keys(slots).length ? slots : null, slot: k.slot, allowFree: false, casterName: mine && mine.name,
      onToggle: (p) => pick(p.id), onSlot: (n) => { k.slot = n; }, onCast: castNow, onCancel: () => { casting = null; render(); },
      onTakeBack: (r) => takeBack(r.undo) }),
      S.map && !k.result ? h("p", { class: "faint", style: "font-size:.84rem;margin:6px 0 0" }, "You can also tap their token on the map.") : null);
  }
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && casting) { casting = null; render(); } });

  // in a fight: your own turn only, as far as your speed
  function moveHint(mine, mv) {
    if (mv && !mv.my_turn) return "Wait for your turn to move. ";
    if (mv && mv.held) return "You're " + mv.held + " — you can't move. ";
    if (mv && mine.movable) return "Drag your token to move: " + mv.left + " of " + mv.speed * (mv.dash ? 2 : 1) + " ft left. ";
    if (mv && !mv.left) return "No movement left this turn" + (mv.dash ? ". " : " (Dash for more). ");
    return mine.movable ? "Drag your token to move. " : "The DM has locked movement. ";
  }
  // your moves, shown like the DM's move cards on the map: what each one does, then its buttons
  function moveCard(ic, name, info, ...kids) {
    return h("div", { class: "fight-act move-card" }, icon(ic, "sm"), h("b", null, name),
      info ? h("span", { class: "faint move-info" }, info) : null, h("div", { class: "move-btns" }, kids));
  }
  const attackInfo = (a) => [a.bonus ? "attack roll " + a.bonus : "", a.damage, a.extra_moves ? "+" + a.extra_moves + " extra moves this turn" : "",
    a.stance > 1 ? (a.stance === 2 ? "double damage" : "×" + a.stance + " damage") + " this turn" : ""].filter(Boolean).join(" · ");
  const spellInfo = (s, c, d) => { const v = L.spellView(s), ar = v.area && v.area.size && !v.zone ? v.area : null;
    return [v.aura ? "" : L.levelWord(v), ar ? ar.size + " ft " + (ar.kind || "") + (ar.range ? " · range " + ar.range + " ft" : "") : "", L.spellWhat(v),
      L.spellLands(v, d.spell || (v.dc ? { dc: v.dc } : null), c.roll_to_hit), v.cooldown ? v.cooldown + "-turn cooldown" : ""].filter(Boolean).join(" · "); };

  // End turn: tap once to arm, again to end it (so a stray tap doesn't skip a turn)
  let endArmed = false;
  function endTurnBtn() {
    return h("button", { type: "button", class: "btn btn-primary end-turn-btn" + (endArmed ? " is-armed" : ""),
      title: "Hand the turn on to whoever's next", onclick: async () => {
        if (!endArmed) { endArmed = true; render(); setTimeout(() => { if (endArmed) { endArmed = false; render(); } }, 4000); return; }
        endArmed = false; using = null; casting = null;
        const d = await me("end-turn", {});
        if (d) { toast("Turn ended.", "ok"); if (window.FX) FX.sound("ac"); }
      } }, icon("check", "sm"), endArmed ? " Tap again to end your turn" : " End my turn");
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
    const a = document.activeElement, keep = a && a.dataset && a.dataset.keep;
    const m = S.map;
    $("#no-map").hidden = !!m;
    document.body.classList.toggle("no-live-map", !m); // no map shared: the map box shrinks out of the way
    if (m) {
      const ms = JSON.stringify(m) + JSON.stringify(S.mapTokens);
      if (ms !== mapStamp && !view.drag) { mapStamp = ms; view.setData(m, S.mapTokens); }
      const mine = S.mapTokens.find((t) => t.own);
      if (casting && !casting.result) $("#hint").textContent = "Casting " + casting.spell.name + ": tap who gets it, then Cast.";
      else if (view.tool === "select" && S.character && S.character.disengaged && mine) $("#hint").textContent = "Disengaged: drag your token away. No opportunity attacks this turn.";
      else if (view.tool === "select") $("#hint").textContent = (mine ? moveHint(mine, S.character && S.character.move) : "Drag to look around. ") + "Double-tap to ping.";
    } else { view.map = null; view.draw(); $("#hint").textContent = ""; }

    const e = S.encounter;
    $("#turns").replaceChildren(h("h3", { class: "rule-head" }, e ? "Round " + e.round : "Turn order"),
      e ? h("ol", { class: "mini-order" }, e.order.map((o) => h("li", { class: (o.is_current ? "is-current" : "") + (o.status === "dead" || o.status === "defeated" ? " is-out" : "") },
        h("span", { class: "i" }, o.init ?? "—"), h("span", { class: "grow" }, o.name),
        o.hp != null ? h("span", { class: "faint num" }, o.hp + "/" + o.max_hp) : o.health ? h("span", { class: "tag is-bad", style: "font-size:.72rem" }, o.health) : null,
        o.status ? h("span", { class: "faint", style: "font-size:.8rem" }, o.status) : null)))
        : h("p", { class: "faint", style: "margin:0" }, "No fight right now."),
      e && e.current ? h("p", { style: "margin:8px 0 0;font-weight:700" }, e.order.some((o) => o.is_current && S.character && o.name === S.character.name) ? "It's your turn!" : e.current + "'s turn") : null,
      S.character && S.character.my_turn ? h("div", { style: "margin-top:8px" }, endTurnBtn()) : null);

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
          using && using.what === "attack" ? useBox() : null,
          c.my_turn ? h("div", { style: "margin:0 0 8px" }, endTurnBtn()) : null,
          c.actions ? h("p", { class: "actions-left" + (c.actions.left ? "" : " is-out"), style: "margin:0 0 6px;font-size:.88rem;font-weight:700" },
            c.actions.left ? "Actions left this turn: " + c.actions.left + " of " + c.actions.limit : "No actions left this turn" + (c.actions.extra ? "" : " (Action Surge gives two more)")) : null,
          ...c.attacks.map((a) => a.recharging ? moveCard(a.heal ? "heart" : "swords", a.name || "Attack", attackInfo(a),
          h("span", { class: "tag" }, icon("hourglass", "sm"), (() => { const w = Math.max(0, a.recharging - (c.my_turn ? 1 : 0)); return w ? " recharging · ready in " + w + " turn" + (w === 1 ? "" : "s") : " recharging · ready next turn"; })()))
          : c.my_turn === false ? moveCard(a.heal ? "heart" : "swords", a.name || "Attack", attackInfo(a), h("span", { class: "faint", style: "font-size:.85rem" }, "wait for your turn" + (a.cooldown ? " · " + a.cooldown + "-turn cooldown" : "")))
          : moveCard(a.heal ? "heart" : "swords", a.name || "Attack", attackInfo(a),
          a.cooldown ? h("span", { class: "faint", style: "font-size:.8rem" }, a.cooldown + "-turn cooldown") : null,
          a.extra_moves || a.stance > 1 ? h("button", { type: "button", class: "btn btn-sm btn-primary", title: "On yourself, for the rest of your turn",
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
          casting ? castBox() : null,
          using && using.what === "spell" ? useBox() : null,
          ...c.spells.map((s) => moveCard(L.KIND_ICON[s.kind] || "zap", s.name, spellInfo(s, c, d),
          c.my_turn && s.zone && !s.recharging ? h("button", { type: "button", class: "btn btn-sm btn-primary", disabled: !!(c.actions && !c.actions.left),
            title: "It rises around you: enemies in it are hit, and it stays up", onclick: () => useZone(s) }, icon("sun", "sm"), " Use") :
          c.my_turn && aimsAtFoes(s) && !s.recharging ? useBtn("spell", s.index, s.name, s.targets === 1 || !s.area, s.targets) :
          s.kind === "damage" && (s.hit === "attack" || c.roll_to_hit) && d.spell ? h("button", { type: "button", class: "btn btn-sm",
            onclick: attackThen({ type: "spell_attack" }, s.dice ? { type: "spell", key: s.index } : null) }, "Attack " + signed(d.spell.attack)) : null,
          s.kind === "damage" && s.dice && !(c.my_turn && aimsAtFoes(s)) ? h("button", { type: "button", class: "btn btn-sm", onclick: (ev) => roll({ type: "spell", key: s.index }, ev) }, "Dmg") : null,
          s.hit && s.hit !== "attack" && !c.roll_to_hit ? h("span", { class: "tag" }, s.hit.toUpperCase() + " save" + (d.spell ? " DC " + d.spell.dc : "")) : null,
          s.aura ? L.auraButton(s, "/api/play/me/aura", () => load(true))
          : s.terrain ? h("span", { class: "tag", title: "Ask the DM: it's aimed on the battle map" }, icon("map", "sm"), " the DM aims it on the map")
          : s.recharging ? h("span", { class: "tag" }, icon("hourglass", "sm"), (() => { const w = Math.max(0, s.recharging - (c.my_turn ? 1 : 0)); return w ? " recharging · ready in " + w + " turn" + (w === 1 ? "" : "s") : " recharging · ready next turn"; })())
          : castable(s) && c.can.cast_spells !== false
            ? h("button", { type: "button", class: "btn btn-sm btn-heal" + (casting && casting.index === s.index ? " is-armed" : ""), title: "Then tap who gets it",
              onclick: () => startCast(s) }, icon(s.kind === "heal" ? "heart" : "shield-plus", "sm"), " Cast · " + (L.spellWhat(s) || s.name))
            : s.kind === "debuff" && !c.my_turn ? h("span", { class: "tag", title: "On your turn" }, L.spellWhat(s) || "debuff") : null))] : null,
        h("details", { class: "roll-fold", open: rollsOpen, ontoggle: (e) => { rollsOpen = e.target.open; } },
          h("summary", { class: "lbl" }, "Saving throws & skills"),
          h("h4", { class: "lbl", style: "margin:12px 0 4px" }, "Saving throws"),
          h("div", { class: "roll-grid" }, ABIL.map(([k, label]) => h("button", { type: "button", onclick: (ev) => roll({ type: "save", key: k }, ev) }, h("span", null, label), h("b", null, signed(d.saves[k]))))),
          h("h4", { class: "lbl", style: "margin:12px 0 4px" }, "Skills"),
          h("div", { class: "roll-grid" }, SKILLS.map(([k, label]) => h("button", { type: "button", onclick: (ev) => roll({ type: "skill", key: k }, ev) }, h("span", null, label), h("b", null, signed(d.skills[k])))))));
    }
    if (keep) { const el = document.querySelector('[data-keep="' + keep + '"]'); if (el) el.focus(); }
    $("#party").replaceChildren(h("h3", { class: "rule-head" }, "Party"),
      h("ul", { class: "stack-list" }, S.party.map((p) => h("li", null, h("div", { class: "row", style: "justify-content:space-between" },
        h("b", null, p.name), h("span", { class: "num" }, p.current_hp + "/" + p.max_hp + (p.temp_hp ? " +" + p.temp_hp : ""))),
        p.conditions.length || p.status !== "ok" ? h("div", { class: "faint", style: "font-size:.85rem" }, [p.status !== "ok" ? p.status : "", ...p.conditions].filter(Boolean).join(", ")) : null))));
  }

  async function load(force) {
    if (!force && (document.hidden || view.drag)) return;
    try {
      const d = await api("GET", "/api/play/state");
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
      stamp = s; S = d; render();
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
  setInterval(load, 1500);
})();
