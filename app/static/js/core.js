/* Shared browser code: DOM helpers, the save queue and field binders.

   The save queue runs one request at a time, in order, so writes can never
   land out of sequence. Network failures and server errors keep the request
   at the head of the queue and retry with backoff; the indicator in the top
   bar only says "saved" once the server has confirmed every pending write. */
(function () {
  "use strict";

  // ---- DOM ------------------------------------------------------------------
  // replaceChildren() would print null as the text "null"; views pass optional
  // pieces (cond ? el : null) and arrays, so skip empties and flatten lists.
  const nativeReplace = Element.prototype.replaceChildren;
  Element.prototype.replaceChildren = function (...kids) {
    return nativeReplace.apply(this, kids.flat(Infinity).filter((k) => k !== null && k !== undefined && k !== false));
  };
  function h(tag, attrs, ...kids) {
    const el = document.createElement(tag);
    if (attrs) {
      for (const [k, v] of Object.entries(attrs)) {
        if (v === null || v === undefined || v === false) continue;
        if (k === "class") el.className = v;
        else if (k === "text") el.textContent = v;
        else if (k === "html") el.innerHTML = v;
        else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
        else if (k === "dataset") Object.assign(el.dataset, v);
        else if (k === "value") el.value = v;
        else if (v === true) el.setAttribute(k, "");
        else el.setAttribute(k, v);
      }
    }
    for (const kid of kids.flat(Infinity)) {
      if (kid === null || kid === undefined || kid === false) continue;
      el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
    }
    return el;
  }
  // A one-line text box that wraps and grows instead of hiding long text past its edge.
  // Enter doesn't add a line (it's still one value); pasted line breaks become spaces.
  const growObserver = window.ResizeObserver ? new ResizeObserver((entries) => entries.forEach((e) => grow(e.target))) : null;
  function grow(el) {
    if (!el.isConnected || !el.offsetWidth) return;
    el.style.height = "auto";
    el.style.height = el.scrollHeight + (el.offsetHeight - el.clientHeight) + "px";
  }
  // The same for a textarea that's already in the page (e.g. a fight's or a map's name).
  function wrapUp(el) {
    if (!el) return el;
    el.classList.add("wrap-input");
    el.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); el.blur(); } });
    el.addEventListener("input", () => {
      if (/[\r\n]/.test(el.value)) { const at = el.selectionStart; el.value = el.value.replace(/[\r\n]+/g, " "); el.setSelectionRange(at, at); }
      grow(el);
    }, true);
    if (growObserver) growObserver.observe(el);
    requestAnimationFrame(() => grow(el));
    return el;
  }
  function wrapText(attrs) {
    const a = Object.assign({}, attrs);
    a.class = ((a.class || "") + " wrap-input").trim();
    delete a.type;
    const el = h("textarea", Object.assign({ rows: 1 }, a));
    el.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); el.blur(); } });
    el.addEventListener("input", () => {
      if (/[\r\n]/.test(el.value)) { const at = el.selectionStart; el.value = el.value.replace(/[\r\n]+/g, " "); el.setSelectionRange(at, at); }
      grow(el);
    }, true);
    if (growObserver) growObserver.observe(el); else requestAnimationFrame(() => grow(el));
    return el;
  }
  // List tables stack into cards on phones; each cell is labelled with its column heading.
  function labelTables(root) {
    (root || document).querySelectorAll("table.ledger").forEach((t) => {
      const heads = [...t.querySelectorAll("thead th")].map((th) => th.textContent.trim());
      if (!heads.length) return;
      t.querySelectorAll("tbody tr").forEach((tr) => [...tr.children].forEach((td, i) => { if (heads[i] && !td.dataset.label) td.dataset.label = heads[i]; }));
    });
  }
  labelTables();
  if (window.MutationObserver) new MutationObserver(() => labelTables()).observe(document.body, { childList: true, subtree: true });

  // Sticky bars sit under the top bar, whose height changes when the menu wraps.
  const topbar = document.querySelector(".topbar");
  if (topbar && window.ResizeObserver) new ResizeObserver(() => document.documentElement.style.setProperty("--head-h", topbar.offsetHeight + "px")).observe(topbar);

  // Same rule as rules.is_healing on the server: a sheet attack row that restores HP.
  function isHealing(row) {
    return /\b(heal|heals|healing|cure|cures)\b/i.test([row && row.name, row && row.damage, row && row.notes].filter(Boolean).join(" "));
  }
  // ---- spells -----------------------------------------------------------------------------
  // Same rules as rules.spell_info / spell_helps on the server. Older sheet rows say "effect";
  // they're a buff when they need no save (or raise AC), otherwise a debuff.
  const HELP_EXCEPTIONS = { sleep: false, sanctuary: true };
  function spellKind(s) {
    if (!s) return "";
    if (s.kind) return s.kind;
    if (s.effect === "effect") {
      const k = String(s.name || "").toLowerCase();
      return (k in HELP_EXCEPTIONS ? HELP_EXCEPTIONS[k] : (Number(s.ac) > 0 || !s.hit)) ? "buff" : "debuff";
    }
    return s.effect || "";
  }
  const spellHelps = (s) => ["heal", "buff"].includes(spellKind(s));
  const KIND_WORD = { damage: "Damage", heal: "Healing", buff: "Buff", debuff: "Debuff" };
  const KIND_ICON = { damage: "wand-sparkles", heal: "heart", buff: "shield-plus", debuff: "zap" };
  const ADV_WORD = { attacks_adv: "advantage on its attacks", attacks_dis: "disadvantage on its attacks",
    attacked_adv: "attacks against it have advantage", attacked_dis: "attacks against it have disadvantage" };
  const ABIL_SHORT = { str: "Str", dex: "Dex", con: "Con", int: "Int", wis: "Wis", cha: "Cha" };
  function duration(r) {
    if (!r) return "";
    if (r >= 4800 && r % 600 === 0) return (r / 600) + " hr";
    if (r >= 600 && r % 600 === 0) return (r / 600) + " hr";
    if (r >= 10 && r % 10 === 0) return (r / 10) + " min";
    return r + (r === 1 ? " round" : " rounds");
  }
  // What a spell does to whoever it lands on, in a few words.
  function spellWhat(s, amount) {
    const k = spellKind(s), bits = [];
    if (k === "damage" && s.dice) bits.push((amount != null ? amount : s.dice) + (s.damage_type ? " " + s.damage_type : "") + " damage");
    if (k === "heal" && s.dice) bits.push("heals " + (amount != null ? amount : s.dice));
    if (s.temp_hp) bits.push(s.temp_hp + " temp HP");
    if (s.condition) bits.push(s.condition);
    if (Number(s.ac)) bits.push(signed(Number(s.ac)) + " AC");
    if (s.roll_mod) bits.push((/^[-+]/.test(s.roll_mod) ? s.roll_mod : "+" + s.roll_mod) + " to attacks & saves");
    if (s.dmg_mod) bits.push((/^[-+]/.test(s.dmg_mod) ? s.dmg_mod : "+" + s.dmg_mod) + " damage on hits");
    if (s.adv) bits.push(ADV_WORD[s.adv]);
    if (Number(s.max_hp)) bits.push("+" + s.max_hp + " max HP");
    if (s.ongoing) bits.push((s.ongoing_kind === "heal" ? "heals " + s.ongoing : s.ongoing_kind === "temp" ? s.ongoing + " temp HP" : s.ongoing + " " + (s.ongoing_type || s.damage_type || "") + " damage").replace("  ", " ") + " each turn");
    if (s.repeat_save && s.hit && s.hit !== "attack") bits.push(ABIL_SHORT[s.hit] + " save each turn to end it");
    if (s.rounds && (s.condition || Number(s.ac) || s.roll_mod || s.dmg_mod || s.adv || s.ongoing || Number(s.max_hp))) bits.push(duration(s.rounds));
    return bits.join(" · ");
  }
  // How it lands: "spell attack +7", "Dex save DC 15", or nothing for spells that just work.
  function spellLands(s, sc, rule) {
    if (spellHelps(s)) return "";
    const atk = sc && sc.attack != null ? " " + signed(sc.attack) : s.attack_bonus != null ? " " + signed(Number(s.attack_bonus)) : "";
    if (s.hit === "attack" || (rule && s.hit)) return "spell attack" + atk + (s.hit !== "attack" ? " (house rule)" : "");
    if (s.hit) return ABIL_SHORT[s.hit] + " save" + (s.dc ? " DC " + s.dc : sc && sc.dc ? " DC " + sc.dc : "") + (spellKind(s) === "damage" ? (s.save_half === false || (s.save_half == null && !s.level) ? "" : ", half on a save") : "");
    return spellKind(s) === "damage" ? "always hits" : "no save";
  }
  const levelWord = (s) => !Number(s.level) ? "Cantrip" : "Level " + s.level;
  // The spell list the server sent (sheet, combat, map). bookSpell("Hold person DC 13") -> Hold Person.
  function bookSpell(name) {
    const list = (window.SPELL_BOOK && window.SPELL_BOOK.spells) || [];
    const key = String(name || "").trim().toLowerCase();
    let hit = list.find((s) => s.name.toLowerCase() === key);
    if (!hit) hit = list.slice().sort((a, b) => b.name.length - a.name.length).find((s) => [" ", ":", "("].some((c) => key.startsWith(s.name.toLowerCase() + c)));
    return hit || null;
  }
  // Fill in what a spell row leaves out, close enough to the server's spell_info for showing it.
  function spellView(s) {
    const v = Object.assign({ level: 0, dice: "", hit: "", condition: "", rounds: null, ac: 0 }, s);
    v.kind = spellKind(s);
    v.level = Number(v.level) || 0;
    if (v.concentration == null) v.concentration = /\bconcentration\b/i.test(v.notes || "");
    if (!v.area) v.area = parseArea(v.notes || "");
    else if (typeof v.area === "string") v.area = parseArea(v.area);
    return v;
  }
  /* A monster's Spells box -> spells to cast. A line naming a book spell ("Fireball",
     "Hold person DC 13", "Cure wounds 2d8+3") gets the book's details, with the line's own
     dice, +to hit and DC on top. Other lines are read like attacks:
       "Fire bolt +5 2d10" · "Healing word heal 1d4+2" · "Web: Restrained 10 rounds" */
  function monsterSpells(text) {
    const out = [];
    String(text || "").split(/\n+/).forEach((raw) => {
      const line = raw.trim();
      if (!line) return;
      const p = parseAttack(line) || {};
      const book = bookSpell(line);
      const dc = /\bDC\s*(\d+)/i.exec(line);
      let spec;
      if (book) {
        spec = Object.assign({}, book);
        if (p.dmg && p.dmg !== book.dice) spec.dice = p.dmg;
        if (p.hit) { spec.hit = "attack"; spec.attack_bonus = Number(p.hit); }
      } else if (p.dmg || p.condition) {
        const kind = p.heal ? "heal" : p.dmg ? "damage" : "debuff";
        spec = { name: p.name, effect: kind, dice: p.dmg || "", hit: kind === "heal" ? "" : "attack", condition: p.condition || "", rounds: p.rounds || null,
          notes: line };
        if (p.hit) spec.attack_bonus = Number(p.hit);
      } else return;
      if (dc) spec.dc = Number(dc[1]);
      if (p.cooldown) spec.cooldown = p.cooldown;
      out.push(spellView(spec));
    });
    return out;
  }

  /* The one way to cast, on every screen: tap who it's on (tap again to take them off), pick
     the slot for a levelled spell, then Cast. The server rolls everything and applies it.
     people: [{ id, name, info, ally }] · chosen: Set of ids · slots: { "1": {max, used} } or null
     result: the server's cast result, shown underneath with an Undo for the HP. */
  function castPanel(o) {
    const s = o.spell, k = spellKind(s), helps = spellHelps(s), max = s.targets || null;
    const chip = (p) => {
      const on = o.chosen.has(p.id);
      return h("button", { type: "button", class: "cast-chip" + (on ? " is-done" : "") + (p.ally ? " is-ally" : " is-foe"), "aria-pressed": on ? "true" : "false",
        disabled: o.busy || (!on && max && o.chosen.size >= max), "aria-label": (on ? "Take off " : "Cast on ") + p.name, onclick: () => o.onToggle(p) },
        on ? icon("check", "sm") : null, h("b", null, p.name), p.info ? h("span", { class: "num" }, p.info) : null);
    };
    const groups = [["Your side", o.people.filter((p) => p.ally)], ["Other side", o.people.filter((p) => !p.ally)]];
    if (!helps) groups.reverse();
    const lvls = s.level && o.slots ? Object.keys(o.slots).map(Number).filter((n) => n >= s.level).sort((a, b) => a - b) : [];
    const slotPick = s.level ? h("div", { class: "cast-slot row" },
      lvls.length ? h("label", { class: "field", style: "flex:0 0 auto" }, h("span", null, "Spell slot"),
        h("select", { "aria-label": "Spell slot level", disabled: o.free, onchange: (e) => o.onSlot(Number(e.target.value)) },
          lvls.map((n) => { const v = o.slots[n] || o.slots[String(n)], left = v.max - v.used;
            return h("option", { value: n, selected: n === (o.slot || s.level) }, "Level " + n + " — " + left + " left" + (n > s.level ? " (upcast)" : "")); }))) : null,
      !lvls.length ? h("label", { class: "field", style: "flex:0 0 auto" }, h("span", null, "Cast at level"),
        h("select", { "aria-label": "Cast at level", onchange: (e) => o.onSlot(Number(e.target.value)) },
          [1, 2, 3, 4, 5, 6, 7, 8, 9].filter((n) => n >= s.level).map((n) => h("option", { value: n, selected: n === (o.slot || s.level) }, "Level " + n + (n > s.level ? " (upcast)" : ""))))) : null,
      o.allowFree && lvls.length ? h("label", { class: "check", style: "font-size:.9rem" }, h("input", { type: "checkbox", checked: !!o.free, onchange: (e) => o.onFree(e.target.checked) }), "Don't use a slot") : null) : null;
    const n = o.chosen.size;
    const res = o.result;
    return h("div", { class: "cast-picker is-" + (k === "heal" ? "heal" : helps ? "help" : "harm"), role: "group", "aria-label": "Cast " + s.name },
      h("div", { class: "cast-head" }, icon(KIND_ICON[k] || "zap", "sm"), h("b", null, s.name),
        h("span", { class: "tag" }, levelWord(s)), s.concentration ? h("span", { class: "tag", title: "Concentration: casting another concentration spell ends it, and damage can break it" }, "Concentration") : null,
        h("span", { class: "cast-what" }, [spellWhat(s), o.lands].filter(Boolean).join(" · "))),
      s.notes ? h("p", { class: "faint cast-notes" }, s.notes) : null,
      res ? castResult(res, o.onUndo) : null,
      res ? null : h("p", { class: "cast-ask" }, n ? "Casting on " + n + (max ? " of up to " + max : "") + ". Tap anyone else it reaches, then Cast." : max === 1 ? "Who is it on? Tap them." : "Who does it reach? Tap each one" + (max ? " (up to " + max + ")" : "") + "."),
      res ? null : groups.filter(([, list]) => list.length).map(([label, list]) => h("div", { class: "cast-group" },
        groups.filter(([, l]) => l.length).length > 1 ? h("div", { class: "lbl" }, label) : null,
        h("div", { class: "cast-chips" }, list.map(chip)))),
      res || o.people.length ? null : h("p", { class: "faint", style: "margin:0" }, "No one to cast it on."),
      res ? null : slotPick,
      h("div", { class: "row", style: "margin-top:10px;gap:8px" },
        res ? null : h("button", { type: "button", class: "btn cast-go " + (helps ? "btn-heal" : "btn-dmg"), disabled: o.busy || (!n && !s.concentration), onclick: o.onCast },
          icon(KIND_ICON[k] || "zap", "sm"), o.busy ? " Casting…" : " Cast" + (n ? " on " + n : "")),
        h("button", { type: "button", class: "btn btn-sm" + (res ? " btn-primary" : ""), onclick: o.onCancel }, res ? "Done" : "Cancel")));
  }
  const HOW_CLASS = { hit: "hits", crit: "hits", failed: "hits", auto: "hits", miss: "misses", saved: "misses" };
  function castResult(r, onUndo) {
    return h("div", { class: "cast-result", role: "status" },
      h("div", { class: "cast-res-head" }, h("b", null, r.caster + " cast " + r.spell), r.spent ? h("span", { class: "tag" }, "level " + r.slot + " slot used") : null),
      r.targets.length ? h("ul", { class: "cast-res-list" }, r.targets.map((t) => h("li", { class: HOW_CLASS[t.how] || "" }, t.text))) : h("p", { class: "faint", style: "margin:4px 0" }, "Concentrating on it."),
      onUndo && r.targets.some((t) => t.amount != null) ? h("button", { type: "button", class: "btn btn-sm btn-quiet", onclick: onUndo }, icon("undo-2", "sm"), " Undo last HP change") : null);
  }
  /* Send a cast to the server: { caster_id, spell | book, targets, slot, free }. done(response)
     after it lands (null if it didn't). Out of slots: the toast offers to cast it without one. */
  function castSpell(eid, body, done) {
    act("POST", "/api/encounters/" + eid + "/cast", body, (d) => {
      done(d);
      if (d && d.cast && window.Dice && Dice.showAll) Dice.showAll(d.cast.rolls || []);
    }, { onError: (err) => {
      done(null);
      toast(err.message, "error", err.data && err.data.needs_free
        ? { ms: 12000, action: { label: "Cast without a slot", run: () => castSpell(eid, Object.assign({}, body, { free: true, op_id: uid() }), done) } } : undefined);
    } });
  }
  /* One stat-block line -> something to roll. Understands the book style and quick shorthand:
       "Scimitar. Melee Weapon Attack: +4 to hit ... Hit: 5 (1d6 + 2)" -> { name, hit: "+4", dmg: "1d6+2" }
       "Bite 1d4" / "Snipe shot - 1d20 damage"                         -> { name, dmg }
       "Spread 1d20 must beat a 5" / "Entangle 1d20"                    -> { name, check: "1d20", beat: 5 }  (a roll, not damage)
       "can summon a mad mushroom"                                      -> { note }                          (no dice)
     and for spells:
       "Fire bolt +5 2d10"                                              -> { name, hit: "+5", dmg: "2d10" }
       "Healing word heal 1d4+2"                                        -> { name, heal: true, dmg: "1d4+2" }
       "Web: Restrained 10 rounds"                                      -> { name, condition: "Restrained", rounds: 10 } */
  const CONDITION_WORDS = ["Blinded", "Charmed", "Deafened", "Frightened", "Grappled", "Incapacitated", "Invisible",
    "Paralyzed", "Petrified", "Poisoned", "Prone", "Restrained", "Stunned", "Unconscious"];
  function parseAttack(raw) {
    const line = String(raw || "").trim();
    if (!line) return null;
    const hitM = line.match(/([+-]\s*\d+)\s*to hit/i) || line.match(/(?:^|\s)([+-]\d+)(?=\s+\d*d\d)/i);
    const diceM = line.match(/(\d*d\d+(?:\s*[+-]\s*\d+)?)/i);
    const cond = CONDITION_WORDS.find((w) => new RegExp("\\b" + w + "\\b", "i").test(line));
    const roundsM = line.match(/(\d+)\s*(?:rounds?|rds?)\b/i);
    if (!diceM && !hitM && !cond) return /[a-z]/i.test(line) ? { note: line } : null;
    let name = (line.match(/^\s*([^.:]{1,40})[.:]/) || [])[1] || line.split(/\s+[-–—:]\s*|\s*:\s*|\s*\d*d\d|\s*[+-]\s*\d/i)[0];
    name = name.replace(/\d*d\d+(?:\s*[+-]\s*\d+)?/gi, "").replace(/\bDC\s*\d+/gi, "").replace(/\d+\s*(?:rounds?|rds?)\b/gi, "");
    if (cond) name = name.replace(new RegExp("\\b" + cond + "\\b", "i"), "");
    name = name.replace(/[\s\-–—:,]+$/, "").trim();
    if (/\s/.test(name)) name = name.replace(/\s+heal(?:s|ing)?$/i, "");
    name = name || cond || "Attack";
    name = name.charAt(0).toUpperCase() + name.slice(1);
    const expr = diceM ? diceM[1].replace(/\s/g, "").replace(/^d/i, "1d") : null;
    const hit = hitM ? hitM[1].replace(/\s/g, "") : null;
    const heal = /\bheal(?:s|ing)?\b/i.test(line) && !!expr;
    if (expr && /^1d20([+-]\d+)?$/i.test(expr) && !hit && !heal && !cond && !/damage|dmg/i.test(line)) {
      const dc = line.match(/\b(?:beat|beats)\s+(?:a\s+)?(\d+)/i), dcM = line.match(/\bDC\s*(\d+)/i);
      return { name, check: expr, beat: dc ? Number(dc[1]) : null, dc: dcM ? Number(dcM[1]) : null };
    }
    // breath weapons and other areas reach several creatures
    const area = /\b(?:breath|cone|radius|cube|sphere|each creature|every creature|line that is)\b/i.test(line);
    const cd = /(\d+)\s*-?\s*(?:turns?|rounds?|rds?)\s*(?:of\s*)?cool\s*-?\s*down|cool\s*-?\s*down\s*(?:of\s*|:\s*)?(\d+)/i.exec(line);
    return { name, hit, dmg: expr, heal, condition: cond || "", rounds: roundsM && !cd ? Number(roundsM[1]) : null, area, aimArea: parseArea(line),
      cooldown: cd ? Math.min(20, Number(cd[1] || cd[2])) : 0 };
  }
  /* "15 ft cone", "20-foot radius", "10 ft cone, range 20" -> { kind, size, range } to aim on the map.
     Same rule as rules.parse_area on the server; without a range the area starts at the attacker. */
  const AREA_KINDS = { cone: "cone", line: "line", cube: "square", square: "square", radius: "circle", sphere: "circle",
    circle: "circle", cylinder: "circle", emanation: "circle" };
  function parseArea(text) {
    text = String(text || "");
    const m = /(\d+)\s*-?\s*(?:ft|foot|feet)\.?\s*(cone|line|cube|square|radius|sphere|circle|cylinder|emanation)\b/i.exec(text);
    if (!m) return null;
    const r = /\brange\s*(?:of\s*)?(\d+)/i.exec(text);
    let range = r ? Number(r[1]) : 0;
    if (!r) {
      const re = /(\d+)\s*-?\s*(?:ft|foot|feet)\b/gi;
      let f;
      while ((f = re.exec(text))) if (f.index < m.index || f.index >= m.index + m[0].length) { range = Number(f[1]); break; }
    }
    return { kind: AREA_KINDS[m[2].toLowerCase()], size: Math.max(5, Number(m[1])), range };
  }
  const attackLines = (text) => String(text || "").split(/\n+/).map(parseAttack).filter((a) => a && !a.note);
  const attackNotes = (text) => String(text || "").split(/\n+/).map(parseAttack).filter((a) => a && a.note).map((a) => a.note);
  // "Spread: 7 — beats 5" for a roll with a target number
  function checkVerdict(a, total) {
    if (a.beat != null) return total > a.beat ? "beats " + a.beat : "doesn't beat " + a.beat;
    if (a.dc != null) return total >= a.dc ? "makes DC " + a.dc : "fails DC " + a.dc;
    return "";
  }
  /* Panels that redraw when the game changes (the map's side panel, the combat details)
     would snap every folded section shut. Each <details> remembers whether it was open,
     by its data-key or its summary's text, and restoreOpen() puts it back after a redraw. */
  const openState = new Map();
  const detailsKey = (d) => d.dataset.key || ((d.querySelector(":scope > summary") || {}).textContent || "").trim();
  document.addEventListener("toggle", (e) => {
    const d = e.target;
    if (d && d.tagName === "DETAILS" && detailsKey(d)) openState.set(detailsKey(d), d.open);
  }, true);
  function restoreOpen(root) {
    root.querySelectorAll("details").forEach((d) => { const k = detailsKey(d); if (k && openState.has(k)) d.open = openState.get(k); });
  }
  // what's been typed in a monster's attacks & spells boxes but not saved yet, so a redraw doesn't lose it
  const drafts = new Map();
  const ATTACK_HELP = "One per line. Bite 1d6 · Claw +4 to hit 1d6+2 · Spread 1d20 must beat a 5";
  const SPELL_HELP = "One per line. Fire bolt +5 2d10 · Fireball 8d6 · Healing word heal 1d4+2 · Web: Restrained 10 rounds";
  /* Write an enemy's attacks and spells in the middle of a fight. With "all like it" ticked, every
     enemy of the same kind in the fight and the creature in the library change too. */
  function monsterEditor(c, onSaved) {
    const sb = c.statblock || {};
    const dk = (f) => c.id + ":" + f;
    const box = (f, label, placeholder) => h("textarea", { rows: 3, class: "prose", "aria-label": label, placeholder, "data-keep": "mon-" + dk(f),
      oninput: (e) => drafts.set(dk(f), e.target.value) }, drafts.has(dk(f)) ? drafts.get(dk(f)) : sb[f] || "");
    const atk = box("attacks", "Attacks", "Bite 1d6\nClaw +4 to hit 1d6+2");
    const spl = box("spells", "Spells", "Fire bolt +5 2d10\nWeb: Restrained 10 rounds");
    const base = sb.base_name || c.name;
    const all = h("input", { type: "checkbox", checked: true });
    const save = h("button", { type: "button", class: "btn btn-sm btn-primary" }, icon("check", "sm"), " Save attacks & spells");
    save.addEventListener("click", () => act("POST", "/api/combatants/" + c.id + "/statblock", { attacks: atk.value, spells: spl.value, all_like_it: all.checked },
      (d) => { drafts.delete(dk("attacks")); drafts.delete(dk("spells")); toast("Saved. The new buttons are ready.", "ok"); if (onSaved) onSaved(d); },
      { onError: (e) => toast(e.message, "error") }));
    return h("details", { class: "mon-edit", "data-key": "mon-edit-" + c.id, open: !(sb.attacks || sb.spells) || drafts.has(dk("attacks")) || drafts.has(dk("spells")) ? true : null },
      h("summary", { class: "lbl" }, (sb.attacks || sb.spells) ? "Change attacks & spells" : "Write attacks & spells"),
      h("label", { class: "field" }, h("span", null, "Attacks"), atk, h("small", { class: "faint" }, ATTACK_HELP)),
      h("label", { class: "field" }, h("span", null, "Spells"), spl, h("small", { class: "faint" }, SPELL_HELP)),
      h("label", { class: "check" }, all, "Every " + base + " in this fight" + (c.creature_id ? ", and in the creature library" : "")),
      save);
  }
  function icon(name, cls) {
    const ns = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(ns, "svg");
    svg.setAttribute("class", "ico " + (cls || ""));
    svg.setAttribute("aria-hidden", "true");
    const use = document.createElementNS(ns, "use");
    use.setAttribute("href", "#i-" + name);
    svg.append(use);
    return svg;
  }
  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));
  const signed = (n) => (n >= 0 ? "+" + n : "−" + Math.abs(n));
  const boot = (id) => JSON.parse(document.getElementById(id).textContent);
  const uid = () => (crypto.randomUUID ? crypto.randomUUID() : Date.now() + "-" + Math.random()).replace(/-/g, "");
  function debounce(fn, ms) {
    let t;
    const d = (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
    d.flush = (...a) => { clearTimeout(t); fn(...a); };
    return d;
  }
  function fmtTime(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  }
  function fmtDate(iso) {
    if (!iso) return "";
    const d = new Date(iso.length <= 10 ? iso + "T12:00:00" : iso);
    return d.toLocaleDateString([], { month: "short", day: "numeric", year: "numeric" });
  }
  function initials(name) {
    return (name || "?").split(/\s+/).filter(Boolean).map((w) => w[0]).join("").slice(0, 2).toUpperCase();
  }

  // ---- toasts ---------------------------------------------------------------
  function toast(message, kind, opts) {
    opts = opts || {};
    const box = h("div", { class: "toast" + (kind ? " is-" + kind : ""), role: kind === "error" ? "alert" : "status" },
      h("div", { class: "grow" }, message),
      opts.action ? h("button", { class: "link-btn", type: "button", onclick: () => { opts.action.run(); box.remove(); } }, opts.action.label) : null,
      h("button", { class: "icon-btn sm", type: "button", "aria-label": "Dismiss", onclick: () => box.remove() }, icon("x", "sm")));
    $("#toasts").append(box);
    setTimeout(() => box.remove(), opts.ms || (kind === "error" ? 9000 : 4500));
    return box;
  }

  // ---- HTTP -------------------------------------------------------------------
  class HttpError extends Error {
    constructor(status, data) {
      super((data && data.error) || "Request failed (" + status + ")");
      this.status = status;
      this.data = data || {};
      this.retryable = status >= 500 || status === 0 || status === 408 || status === 429;
    }
  }
  async function api(method, url, body, opts) {
    opts = opts || {};
    let resp;
    try {
      const init = { method, headers: {}, cache: "no-store", keepalive: !!opts.keepalive };
      if (body instanceof FormData) init.body = body;
      else if (body !== undefined) { init.headers["Content-Type"] = "application/json"; init.body = JSON.stringify(body); }
      resp = await fetch(url, init);
    } catch (e) {
      throw new HttpError(0, { error: "Can't reach the server. Is it still running?" });
    }
    let data = null;
    try { data = await resp.json(); } catch (e) { data = null; }
    if (!resp.ok) throw new HttpError(resp.status, data);
    return data;
  }

  // ---- save queue -------------------------------------------------------------
  const Save = {
    items: [],
    running: false,
    attempt: 0,
    timer: null,
    invalid: new Map(),   // key -> message
    conflicts: new Map(), // key -> message
    lastSaved: null,

    push(item) {
      // item: {key, run: async () => any}. Pending items with the same key coalesce.
      if (item.key && this.items.some((x, i) => x.key === item.key && !(i === 0 && this.running))) return;
      this.items.push(item);
      this.render();
      this.pump();
    },
    async pump() {
      if (this.running || !this.items.length) return;
      clearTimeout(this.timer);
      this.running = true;
      this.render();
      const item = this.items[0];
      try {
        const value = await item.run();
        this.items.shift();
        this.attempt = 0;
        this.lastSaved = new Date();
        // Follow-ups (like opening a page) run only once the queue no longer
        // counts this write as pending, so navigating away isn't blocked.
        if (item.done) { this.running = false; this.render(); try { item.done(value); } catch (e) { console.error(e); } }
      } catch (err) {
        if (err instanceof HttpError && err.retryable) {
          this.attempt += 1;
          const wait = [1, 2, 4, 8, 15, 30][Math.min(this.attempt - 1, 5)];
          this.retryAt = Date.now() + wait * 1000;
          this.lastError = err.message;
          this.running = false;
          this.render();
          this.timer = setTimeout(() => this.pump(), wait * 1000);
          this.tick();
          return;
        }
        // Not retryable: drop it; the item's own handler reports the problem.
        this.items.shift();
        this.attempt = 0;
        if (item.fail) item.fail(err);
        else toast(err.message, "error");
      }
      this.running = false;
      this.render();
      if (this.items.length) this.pump();
    },
    retryNow() { this.attempt = Math.max(0, this.attempt - 1); clearTimeout(this.timer); this.pump(); },
    tick() {
      clearInterval(this._tick);
      this._tick = setInterval(() => { if (!this.attempt) clearInterval(this._tick); this.render(); }, 1000);
    },
    busy() { return this.items.length > 0 || Binder.anyPending(); },
    render() {
      const el = $("#save-status");
      if (!el) return;
      const text = $(".save-text", el), retry = $(".save-retry", el);
      let state = "saved", msg = "All changes saved";
      if (this.attempt && this.items.length) {
        state = "error";
        const secs = Math.max(0, Math.ceil((this.retryAt - Date.now()) / 1000));
        msg = "Not saved — " + (this.lastError || "server unreachable") + (this.running ? " Retrying…" : " Retrying in " + secs + "s");
      } else if (this.conflicts.size) {
        state = "conflict"; msg = "Changed elsewhere — choose a version";
      } else if (this.invalid.size) {
        state = "invalid"; msg = "Not saved: " + Array.from(this.invalid.values())[0];
      } else if (this.items.length || Binder.anyPending()) {
        state = "saving"; msg = "Saving…";
      } else if (this.lastSaved) {
        msg = "All changes saved";
      }
      el.dataset.state = state;
      text.textContent = msg;
      el.title = msg;
      retry.hidden = state !== "error";
    },
  };
  window.addEventListener("beforeunload", (e) => {
    Binder.flushAll();
    if (Save.busy() || Save.invalid.size) { e.preventDefault(); e.returnValue = ""; }
  });
  window.addEventListener("online", () => Save.retryNow());

  // ---- binders: autosave for one record ------------------------------------
  /* A Binder owns a record's last *confirmed* server values (baseline) and
     the set of fields edited locally. Saving sends {field: {from: baseline,
     to: current}} so the server can refuse to overwrite a newer value. */
  const allBinders = new Set();
  class Binder {
    constructor(opts) {
      this.url = opts.url;
      this.model = opts.model;                 // live values the page edits
      this.baseline = JSON.parse(JSON.stringify(opts.model));
      this.pending = new Set();
      this.inflight = null;
      this.onSaved = opts.onSaved || (() => {});
      this.onRemote = opts.onRemote || (() => {});
      this.label = opts.label || ((f) => f.replace(/_/g, " "));
      this.extract = opts.extract || ((data) => data[Object.keys(data)[0]]);
      this.key = "binder:" + this.url;
      this.delay = opts.delay ?? 600;
      this.later = debounce(() => this.queue(), this.delay);
      this.inputs = new Map();
      allBinders.add(this);
    }
    static anyPending() { for (const b of allBinders) if (b.pending.size) return true; return false; }
    static flushAll() { for (const b of allBinders) if (b.pending.size) b.queue(); }

    set(field, value, immediate) {
      this.model[field] = value;
      if (JSON.stringify(value) === JSON.stringify(this.baseline[field])) this.pending.delete(field);
      else this.pending.add(field);
      Save.render();
      if (immediate) this.later.flush(); else this.later();
    }
    queue() {
      if (!this.pending.size) { Save.render(); return; }
      Save.push({ key: this.key, run: () => this.send() });
    }
    async send() {
      const fields = Array.from(this.pending).filter((f) => !Save.conflicts.has(this.key + ":" + f));
      if (!fields.length) return;
      const changes = {};
      const sent = {};
      for (const f of fields) {
        sent[f] = JSON.parse(JSON.stringify(this.model[f]));
        changes[f] = { from: this.baseline[f], to: sent[f] };
      }
      try {
        const data = await api("PATCH", this.url, { changes });
        const rec = this.extract(data);
        for (const f of fields) {
          this.baseline[f] = rec[f];
          Save.invalid.delete(this.key + ":" + f);
          this.mark(f, null);
          // Only clear "pending" if nothing new was typed while saving.
          if (JSON.stringify(this.model[f]) === JSON.stringify(sent[f])) {
            this.pending.delete(f);
            if (JSON.stringify(rec[f]) !== JSON.stringify(sent[f])) { this.model[f] = rec[f]; this.onRemote(f, rec[f]); }
          }
        }
        this.onSaved(rec, fields);
        if (this.pending.size) this.queue();
      } catch (err) {
        if (err.status === 409 && err.data.conflicts) {
          for (const [f, theirs] of Object.entries(err.data.conflicts)) this.conflict(f, theirs);
          // fields that did not conflict are retried on their own
          if (Array.from(this.pending).some((f) => !Save.conflicts.has(this.key + ":" + f))) this.queue();
          return;
        }
        if (err.status === 400) {
          const bad = fields.length === 1 ? fields[0] : guessField(err.message, fields);
          Save.invalid.set(this.key + ":" + bad, err.message);
          this.mark(bad, err.message);
          this.pending.delete(bad);
          for (const f of fields) if (f !== bad && this.pending.has(f)) { setTimeout(() => this.queue(), 0); break; }
          Save.render();
          return;
        }
        throw err;
      }
    }
    conflict(field, theirs) {
      const ckey = this.key + ":" + field;
      if (Save.conflicts.has(ckey)) return;
      const show = (v) => (v === null || v === undefined || v === "" ? "empty" : typeof v === "object" ? "a different version" : "“" + String(v).slice(0, 60) + "”");
      const box = h("div", { class: "conflict", role: "alert" },
        h("div", null, h("b", null, cap(this.label(field))), " was changed somewhere else (now ", show(theirs), "). Your version is ", show(this.model[field]), "."),
        h("div", { class: "row" },
          h("button", { class: "btn btn-sm", type: "button", onclick: () => { resolve(false); } }, "Use the other version"),
          h("button", { class: "btn btn-sm btn-primary", type: "button", onclick: () => { resolve(true); } }, "Keep mine")));
      const resolve = (keepMine) => {
        box.remove();
        Save.conflicts.delete(ckey);
        this.baseline[field] = theirs;
        if (keepMine) { this.pending.add(field); this.queue(); }
        else { this.model[field] = theirs; this.pending.delete(field); this.onRemote(field, theirs); }
        Save.render();
      };
      Save.conflicts.set(ckey, field);
      $("#conflicts").append(box);
      Save.render();
    }
    mark(field, message) {
      const el = this.inputs.get(field);
      if (!el) return;
      if (message) { el.setAttribute("aria-invalid", "true"); el.title = message; }
      else { el.removeAttribute("aria-invalid"); el.removeAttribute("title"); }
    }
    /* Merge a fresher server copy (from polling) without touching fields the
       user is editing or has not saved yet. */
    refresh(rec) {
      for (const [f, v] of Object.entries(rec)) {
        if (!(f in this.baseline)) continue;
        if (this.pending.has(f) || Save.conflicts.has(this.key + ":" + f)) continue;
        const el = this.inputs.get(f);
        if (el && document.activeElement === el) continue;
        if (JSON.stringify(v) !== JSON.stringify(this.baseline[f])) {
          this.baseline[f] = v;
          this.model[f] = JSON.parse(JSON.stringify(v));
          this.onRemote(f, v);
          if (el && el.classList && el.classList.contains("wrap-input")) requestAnimationFrame(() => grow(el));
        }
      }
    }
    /* Wire a plain input/select/textarea/checkbox to a scalar field. */
    bind(el, field, opts) {
      opts = opts || {};
      const kind = el.type === "checkbox" ? "bool" : (el.type === "number" || opts.int) ? "int" : "text";
      this.inputs.set(field, el);
      const write = (v) => {
        if (kind === "bool") el.checked = !!v; else el.value = v === null || v === undefined ? "" : v;
        if (el.classList && el.classList.contains("wrap-input")) requestAnimationFrame(() => grow(el));
      };
      write(this.model[field]);
      const read = () => {
        if (kind === "bool") return el.checked;
        if (kind === "int") {
          const t = el.value.trim();
          if (t === "") return opts.nullable ? null : el.value;
          const n = Number(t);
          return Number.isInteger(n) ? n : t;
        }
        return el.value;
      };
      const onInput = () => {
        if (Save.invalid.has(this.key + ":" + field)) { Save.invalid.delete(this.key + ":" + field); this.mark(field, null); }
        this.set(field, read());
        if (opts.onInput) opts.onInput(read());
      };
      el.addEventListener(kind === "bool" || el.tagName === "SELECT" ? "change" : "input", onInput);
      el.addEventListener("blur", () => { if (this.pending.has(field)) this.later.flush(); });
      el._write = write;
      return el;
    }
  }
  function guessField(msg, fields) {
    const m = String(msg).toLowerCase();
    return fields.find((f) => m.startsWith(f.toLowerCase())) || fields.find((f) => m.includes(f.replace(/_/g, " "))) || fields[0];
  }
  function cap(s) { return s.charAt(0).toUpperCase() + s.slice(1); }

  // Run an action through the queue (combat buttons, creating records...).
  // op_id makes a retried request safe if the first one actually succeeded.
  function act(method, url, body, onOk, opts) {
    opts = opts || {};
    body = Object.assign({ op_id: uid() }, body || {});
    return new Promise((resolve) => {
      Save.push({
        run: () => api(method, url, body),
        done: (d) => { if (onOk) onOk(d); resolve(d); },
        fail: (err) => { if (opts.onError) opts.onError(err); else toast(err.message, "error"); resolve(null); },
      });
    });
  }

  // Two-step destructive buttons: first click arms, second confirms.
  function armed(btn, run, label) {
    let t;
    const original = btn.innerHTML;
    btn.addEventListener("click", (e) => {
      e.preventDefault();
      if (btn.classList.contains("is-armed")) { clearTimeout(t); btn.classList.remove("is-armed"); btn.innerHTML = original; run(); return; }
      btn.classList.add("is-armed");
      btn.textContent = label || "Click again to confirm";
      t = setTimeout(() => { btn.classList.remove("is-armed"); btn.innerHTML = original; }, 3500);
    });
  }

  // ---- page chrome --------------------------------------------------------------
  document.addEventListener("DOMContentLoaded", () => {
    const retry = $("#save-status .save-retry");
    if (retry) retry.addEventListener("click", () => Save.retryNow());
    const tt = $("#theme-toggle");
    if (tt) tt.addEventListener("click", () => {
      const root = document.documentElement;
      const next = root.dataset.theme === "dark" ? "light" : "dark";
      root.dataset.theme = next;
      tt.setAttribute("aria-label", "Switch to " + (next === "dark" ? "light" : "dark") + " mode");
      Save.push({ key: "theme", run: () => api("PATCH", "/api/settings", { theme: next }) });
    });
    $$("[data-activate]").forEach((b) => b.addEventListener("click", async () => {
      try { await api("POST", "/api/campaigns/" + b.dataset.activate + "/activate"); location.href = "/"; }
      catch (e) { toast(e.message, "error"); }
    }));
    document.addEventListener("click", (e) => {
      $$("details[data-menu][open]").forEach((d) => { if (!d.contains(e.target)) d.removeAttribute("open"); });
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") $$("details[data-menu][open]").forEach((d) => d.removeAttribute("open"));
    });
    Save.render();
  });

  window.L = { h, icon, grow, wrapUp, isHealing, attackLines, attackNotes, checkVerdict, monsterEditor, restoreOpen, ATTACK_HELP, SPELL_HELP, spellHelps, spellKind, spellWhat, spellLands, spellView, levelWord, duration, bookSpell, monsterSpells, castPanel, castResult, castSpell, KIND_WORD, KIND_ICON, wrapText, $, $$, signed, boot, uid, debounce, fmtTime, fmtDate, initials, toast, api, HttpError, Save, Binder, act, armed };
})();
