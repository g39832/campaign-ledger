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
  let casting = null; // { spell, chosen: Set of character ids, slot, busy, result } while the player picks who a spell is for

  try { const t = localStorage.getItem("player-theme"); if (t) document.documentElement.dataset.theme = t; } catch (e) { /* ignore */ }
  $("#theme-toggle-p").addEventListener("click", () => {
    const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("player-theme", next); } catch (e) { /* ignore */ }
  });

  const view = new MapView($("#stage"), {
    role: "player",
    imageUrl: (m) => m.image_url,
    canMove: (t) => t.movable && !casting,
    onSelect: (t) => { if (casting && t && t.character_id) pick(t.character_id); }, // tap a token to cast on them
    onPing: async (x, y) => {
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

  // ---- casting a healing or buff spell on someone in the party ------------------------------
  // Tap the spell, tap who it's for (here or their token on the map), then Cast. The server rolls it.
  const castable = (s) => L.spellHelps(s);
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
    if (!k || k.busy || !k.chosen.size) return;
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
      slots: slots && Object.keys(slots).length ? slots : null, slot: k.slot, allowFree: false,
      onToggle: (p) => pick(p.id), onSlot: (n) => { k.slot = n; }, onCast: castNow, onCancel: () => { casting = null; render(); } }),
      S.map && !k.result ? h("p", { class: "faint", style: "font-size:.84rem;margin:6px 0 0" }, "You can also tap their token on the map.") : null);
  }
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && casting) { casting = null; render(); } });

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
    if (m) {
      const ms = JSON.stringify(m) + JSON.stringify(S.mapTokens);
      if (ms !== mapStamp && !view.drag) { mapStamp = ms; view.setData(m, S.mapTokens); }
      const mine = S.mapTokens.find((t) => t.own);
      if (casting && !casting.result) $("#hint").textContent = "Casting " + casting.spell.name + ": tap who gets it, then Cast.";
      else if (view.tool === "select" && S.character && S.character.disengaged && mine) $("#hint").textContent = "Disengaged: drag your token away. No opportunity attacks this turn.";
      else if (view.tool === "select") $("#hint").textContent = (mine ? (mine.movable ? "Drag your token to move. " : "The DM has locked movement. ") : "Drag to look around. ") + "Double-tap to ping.";
    } else { view.map = null; view.draw(); $("#hint").textContent = ""; }

    const e = S.encounter;
    $("#turns").replaceChildren(h("h3", { class: "rule-head" }, e ? "Round " + e.round : "Turn order"),
      e ? h("ol", { class: "mini-order" }, e.order.map((o) => h("li", { class: (o.is_current ? "is-current" : "") + (o.status === "dead" || o.status === "defeated" ? " is-out" : "") },
        h("span", { class: "i" }, o.init ?? "—"), h("span", { class: "grow" }, o.name),
        o.hp != null ? h("span", { class: "faint num" }, o.hp + "/" + o.max_hp) : o.health ? h("span", { class: "tag is-bad", style: "font-size:.72rem" }, o.health) : null,
        o.status ? h("span", { class: "faint", style: "font-size:.8rem" }, o.status) : null)))
        : h("p", { class: "faint", style: "margin:0" }, "No fight right now."),
      e && e.current ? h("p", { style: "margin:8px 0 0;font-weight:700" }, e.order.some((o) => o.is_current && S.character && o.name === S.character.name) ? "It's your turn!" : e.current + "'s turn") : null);

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
        c.can.edit_hp ? hpControls(c) : null,
        extras(c),
        h("div", { class: "row", style: "margin-bottom:10px" },
          h("button", { type: "button", class: "btn btn-sm", onclick: (ev) => roll({ type: "initiative" }, ev) }, icon("dice-5", "sm"), " Initiative " + signed(d.initiative)),
          c.current_hp === 0 && !["dead", "stable"].includes(c.status) ? h("button", { type: "button", class: "btn btn-sm btn-primary",
            title: "10 or more is a success. A friend standing right next to you on the map gives you a bonus.", onclick: () => me("death-save", {}) }, icon("dice-5", "sm"), " Roll death save") : null,
          c.in_fight ? h("button", { type: "button", class: "btn btn-sm" + (c.disengaged ? " is-armed" : ""), disabled: c.disengaged,
            title: "Move away this turn without opportunity attacks", onclick: disengage }, icon("compass", "sm"), c.disengaged ? " Disengaged — move away" : " Disengage") : null,
          d.spell ? h("button", { type: "button", class: "btn btn-sm", onclick: (ev) => roll({ type: "spell_attack" }, ev) }, "Spell attack " + signed(d.spell.attack)) : null),
        h("div", { class: "stats" }, ABIL.map(([k, label]) => h("button", { type: "button", class: "stat", title: "Roll a " + label + " check", onclick: (ev) => roll({ type: "ability", key: k }, ev) },
          h("b", null, signed(d.mods[k])), h("span", null, label)))),
        c.attacks.length ? [h("h4", { class: "lbl", style: "margin:12px 0 4px" }, "Attacks"),
          c.my_turn === false ? h("p", { class: "faint", style: "margin:0 0 6px;font-size:.88rem" }, "Attacks unlock on your turn.") : null,
          ...c.attacks.map((a) => a.recharging ? h("div", { class: "roll-row", style: "align-items:center;margin-bottom:4px" },
          h("b", { class: "grow" }, a.name || "Attack"),
          h("span", { class: "tag" }, icon("hourglass", "sm"), (() => { const w = Math.max(0, a.recharging - (c.my_turn ? 1 : 0)); return w ? " recharging · ready in " + w + " turn" + (w === 1 ? "" : "s") : " recharging · ready next turn"; })()))
          : c.my_turn === false ? h("div", { class: "roll-row", style: "align-items:center;margin-bottom:4px" },
          h("b", { class: "grow" }, a.name || "Attack"), h("span", { class: "faint", style: "font-size:.85rem" }, "wait for your turn" + (a.cooldown ? " · " + a.cooldown + "-turn cooldown" : "")))
          : h("div", { class: "roll-row", style: "align-items:center;margin-bottom:4px" },
          h("b", { class: "grow" }, a.name || "Attack"),
          a.cooldown ? h("span", { class: "faint", style: "font-size:.8rem" }, a.cooldown + "-turn cooldown") : null,
          a.bonus ? h("button", { type: "button", class: "btn btn-sm", onclick: attackThen({ type: "attack", key: a.index }, a.damage && !a.heal ? { type: "damage", key: a.index } : null) }, "Hit " + a.bonus) : null,
          a.damage ? h("button", { type: "button", class: "btn btn-sm" + (a.heal ? " btn-heal" : ""), onclick: (ev) => roll({ type: "damage", key: a.index }, ev) }, a.heal ? "Heal" : "Dmg") : null))] : null,
        (c.spells || []).length ? [h("h4", { class: "lbl", style: "margin:12px 0 4px" }, "Spells"),
          casting ? castBox() : null,
          ...c.spells.map((s) => h("div", { class: "roll-row", style: "align-items:center;margin-bottom:4px" },
          h("b", { class: "grow" }, s.name),
          s.kind === "damage" && (s.hit === "attack" || c.roll_to_hit) && d.spell ? h("button", { type: "button", class: "btn btn-sm",
            onclick: attackThen({ type: "spell_attack" }, s.dice ? { type: "spell", key: s.index } : null) }, "Attack " + signed(d.spell.attack)) : null,
          s.kind === "damage" && s.dice ? h("button", { type: "button", class: "btn btn-sm", onclick: (ev) => roll({ type: "spell", key: s.index }, ev) }, "Dmg") : null,
          s.hit && s.hit !== "attack" && !c.roll_to_hit ? h("span", { class: "tag" }, s.hit.toUpperCase() + " save" + (d.spell ? " DC " + d.spell.dc : "")) : null,
          castable(s) && c.can.cast_spells !== false
            ? h("button", { type: "button", class: "btn btn-sm btn-heal" + (casting && casting.index === s.index ? " is-armed" : ""), title: "Then tap who gets it",
              onclick: () => startCast(s) }, icon(s.kind === "heal" ? "heart" : "shield-plus", "sm"), " Cast · " + (L.spellWhat(s) || s.name))
            : s.kind === "debuff" ? h("span", { class: "tag", title: "The DM casts this one" }, L.spellWhat(s) || "debuff") : null))] : null,
        h("h4", { class: "lbl", style: "margin:12px 0 4px" }, "Saving throws"),
        h("div", { class: "roll-grid" }, ABIL.map(([k, label]) => h("button", { type: "button", onclick: (ev) => roll({ type: "save", key: k }, ev) }, h("span", null, label), h("b", null, signed(d.saves[k]))))),
        h("h4", { class: "lbl", style: "margin:12px 0 4px" }, "Skills"),
        h("div", { class: "roll-grid" }, SKILLS.map(([k, label]) => h("button", { type: "button", onclick: (ev) => roll({ type: "skill", key: k }, ev) }, h("span", null, label), h("b", null, signed(d.skills[k]))))));
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
      let pings = [];
      if (d.map) { const { map, tokens } = d.map; pings = d.map.pings || []; d.map = map; d.mapTokens = tokens; }
      // pings first: they change every poll, so they're kept out of the "did anything change" check
      const fresh = pings.filter((p) => !view.seenPings.has(p.id) && p.by !== (S && S.me ? S.me.name : ""));
      view.setPings(pings);
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
