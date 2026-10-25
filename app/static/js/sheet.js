/* Character sheet: binds every field to autosave and keeps derived numbers
   (modifiers, saves, skills, passives, spell DC) current while typing.
   Formulas mirror app/rules.py. */
(function () {
  "use strict";
  const { h, icon, $, $$, signed, boot, Binder, act, api, toast, armed } = L;
  const char = boot("boot");
  const SKILLS = boot("boot-skills");
  const ABS = ["str", "dex", "con", "int", "wis", "cha"];
  const NULLABLE = new Set(["prof_override", "initiative_override"]);

  const model = Object.assign({}, char);
  delete model.derived;
  const b = new Binder({
    url: "/api/characters/" + char.id,
    model,
    label: (f) => ({ current_hp: "current HP", max_hp: "max HP", temp_hp: "temp HP", ac: "AC", xp: "XP" }[f] || f.replace(/_/g, " ")),
    onRemote: (f) => { renderField(f); derive(); },
  });

  // ---- rules ------------------------------------------------------------------
  const mod = (s) => Math.floor(((Number(s) || 0) - 10) / 2);
  function derived() {
    const ab = model.abilities || {};
    const mods = Object.fromEntries(ABS.map((a) => [a, mod(ab[a] ?? 10)]));
    const lvl = Math.max(1, Math.min(20, Number(model.level) || 1));
    const prof = Number.isInteger(model.prof_override) ? model.prof_override : 2 + Math.floor((lvl - 1) / 4);
    const sp = new Set(model.save_profs || []), sb = model.save_bonus || {};
    const saves = Object.fromEntries(ABS.map((a) => [a, mods[a] + (sp.has(a) ? prof : 0) + (Number(sb[a]) || 0)]));
    const kp = model.skill_profs || {}, kb = model.skill_bonus || {};
    const skills = Object.fromEntries(SKILLS.map(([k, , a]) => [k, mods[a] + prof * (Number(kp[k]) || 0) + (Number(kb[k]) || 0)]));
    const init = Number.isInteger(model.initiative_override) ? model.initiative_override : mods.dex + (Number(model.initiative_bonus) || 0);
    const sa = model.spellcasting_ability;
    return { mods, prof, saves, skills, init, spell: ABS.includes(sa) ? { dc: 8 + prof + mods[sa], atk: prof + mods[sa] } : null };
  }
  function derive() {
    const d = derived();
    ABS.forEach((a) => { $("#mod-" + a).textContent = signed(d.mods[a]); $("#save-" + a).textContent = signed(d.saves[a]); });
    SKILLS.forEach(([k]) => { $("#skill-" + k).textContent = signed(d.skills[k]); });
    $("#d-init").textContent = signed(d.init);
    $("#d-init-hint").textContent = Number.isInteger(model.initiative_override) ? "override" : (model.initiative_bonus ? "Dex " + signed(d.mods.dex) + ", bonus " + signed(model.initiative_bonus) : "Dex");
    $("#d-prof").textContent = signed(d.prof);
    $("#pp").textContent = 10 + d.skills.perception;
    $("#pi").textContent = 10 + d.skills.insight;
    $("#pv").textContent = 10 + d.skills.investigation;
    $("#spell-dc").textContent = d.spell ? d.spell.dc : "—";
    $("#spell-atk").textContent = d.spell ? signed(d.spell.atk) : "—";
    const max = Number(model.max_hp) || 0, cur = Number(model.current_hp) || 0;
    const pct = max ? Math.min(100, Math.floor((cur / max) * 100)) : 0;
    const bar = $("#hpbar");
    bar.dataset.level = cur <= 0 ? "dead" : pct <= 25 ? "low" : pct <= 50 ? "mid" : "high";
    $(".hpbar-fill", bar).style.width = pct + "%";
    document.title = (model.name || "Character") + " · Campaign Ledger";
  }

  // ---- simple fields ------------------------------------------------------------
  $$("[data-f]").forEach((el) => {
    const f = el.dataset.f;
    const isInt = el.type === "number" || f === "exhaustion";
    b.bind(el, f, { int: isInt, nullable: NULLABLE.has(f), onInput: derive });
  });

  // ---- nested JSON fields ---------------------------------------------------------
  const clone = (o) => JSON.parse(JSON.stringify(o ?? null));
  function setIn(field, key, value) {
    const obj = clone(model[field]) || {};
    if (value === null || value === "" || value === undefined) delete obj[key]; else obj[key] = value;
    b.set(field, obj);
    derive();
  }
  const intOr = (v, dflt) => { const n = Number(v); return v === "" || !Number.isFinite(n) ? dflt : Math.trunc(n); };

  $$("[data-ab]").forEach((el) => el.addEventListener("input", () => setIn("abilities", el.dataset.ab, intOr(el.value, 10))));
  $$("[data-savebonus]").forEach((el) => el.addEventListener("input", () => setIn("save_bonus", el.dataset.savebonus, el.value === "" ? null : intOr(el.value, 0))));
  $$("[data-skillbonus]").forEach((el) => el.addEventListener("input", () => setIn("skill_bonus", el.dataset.skillbonus, el.value === "" ? null : intOr(el.value, 0))));
  $$("[data-coin]").forEach((el) => el.addEventListener("input", () => setIn("currency", el.dataset.coin, Math.max(0, intOr(el.value, 0)))));
  $$("[data-save]").forEach((btn) => btn.addEventListener("click", () => {
    const s = new Set(model.save_profs || []);
    s.has(btn.dataset.save) ? s.delete(btn.dataset.save) : s.add(btn.dataset.save);
    b.set("save_profs", ABS.filter((a) => s.has(a)));
    renderProfs(); derive();
  }));
  $$("[data-skill]").forEach((btn) => btn.addEventListener("click", () => {
    const cur = Number((model.skill_profs || {})[btn.dataset.skill]) || 0;
    setIn("skill_profs", btn.dataset.skill, cur >= 2 ? null : cur + 1);
    renderProfs();
  }));
  function renderProfs() {
    const sp = new Set(model.save_profs || []);
    $$("[data-save]").forEach((btn) => { btn.dataset.level = sp.has(btn.dataset.save) ? 1 : 0; btn.setAttribute("aria-pressed", sp.has(btn.dataset.save)); });
    $$("[data-skill]").forEach((btn) => {
      const lv = Number((model.skill_profs || {})[btn.dataset.skill]) || 0;
      btn.dataset.level = lv;
      btn.title = ["Not proficient", "Proficient", "Expertise"][lv];
    });
  }
  function renderNested() {
    $$("[data-ab]").forEach((el) => { if (document.activeElement !== el) el.value = (model.abilities || {})[el.dataset.ab] ?? 10; });
    $$("[data-savebonus]").forEach((el) => { if (document.activeElement !== el) el.value = (model.save_bonus || {})[el.dataset.savebonus] ?? ""; });
    $$("[data-skillbonus]").forEach((el) => { if (document.activeElement !== el) el.value = (model.skill_bonus || {})[el.dataset.skillbonus] ?? ""; });
    $$("[data-coin]").forEach((el) => { if (document.activeElement !== el) el.value = (model.currency || {})[el.dataset.coin] ?? 0; });
  }

  // ---- death saves ------------------------------------------------------------
  function renderPips() {
    $$("[data-pips]").forEach((wrap) => {
      const f = wrap.dataset.pips, v = Number(model[f]) || 0;
      wrap.replaceChildren(...[0, 1, 2].map((i) => h("button", {
        type: "button", class: "pip" + (i < v ? " on" : ""), "aria-label": (f === "death_successes" ? "Success " : "Failure ") + (i + 1),
        "aria-pressed": i < v ? "true" : "false",
        onclick: () => { b.set(f, v === i + 1 ? i : i + 1, true); renderPips(); },
      })));
    });
  }

  // ---- HP: damage / heal / fix, all applied by the server ----------------------
  // Going through the server keeps the same rules as combat, and if this
  // character is in a running fight the change is logged there and undoable.
  function hpAction(body, after) {
    b.later.flush();
    act("POST", "/api/characters/" + char.id + "/hp", body, (d) => { b.refresh(d.character); renderPips(); derive(); if (after) after(); });
  }
  $$("[data-hp]").forEach((btn) => btn.addEventListener("click", () => {
    const amtEl = $("#hp-amt");
    const amt = Math.max(0, intOr(amtEl.value, 0));
    if (!amt) { amtEl.focus(); return; }
    hpAction({ op: btn.dataset.hp, amount: amt }, () => { amtEl.value = ""; });
  }));
  $("#hp-amt").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); $("[data-hp='damage']").click(); } });
  $$("[data-hpfix]").forEach((btn) => btn.addEventListener("click", () => {
    const max = Number(model.max_hp) || 0;
    const next = Math.max(0, (Number(model.current_hp) || 0) + Number(btn.dataset.hpfix));
    hpAction({ op: "set", hp: max ? Math.min(max, next) : next });
  }));

  // ---- rests ---------------------------------------------------------------------
  function renderRest() {
    const box = $("#rest-btns");
    const pools = [...String(model.hit_dice || "").matchAll(/(\d+)\s*d\s*(\d+)/gi)].map((m) => [Number(m[1]), Number(m[2])]).filter(([n, sd]) => n > 0 && [6, 8, 10, 12].includes(sd));
    const total = pools.reduce((t, [n]) => t + n, 0), left = Math.max(0, total - (Number(model.hit_dice_used) || 0));
    const long = h("button", { type: "button", class: "btn btn-sm", title: "All HP, all spell slots, half your hit dice, one less exhaustion" }, icon("moon", "sm"), " Long rest");
    armed(long, () => act("POST", "/api/characters/" + char.id + "/long-rest", {}, (d) => { b.refresh(d.character); renderSlots(); renderPips(); derive(); renderRest(); toast(model.name + " finished a long rest.", "ok"); }), "Long rest? Click again");
    box.replaceChildren(
      total ? [...new Set(pools.map(([, sd]) => sd))].map((sd) => h("button", { type: "button", class: "btn btn-sm", disabled: !left,
        title: "Short rest: roll a hit die plus Constitution and heal that much",
        onclick: () => {
          b.later.flush();
          act("POST", "/api/characters/" + char.id + "/hit-die", { sides: sd }, (d) => {
            b.refresh(d.character); derive(); renderRest();
            if (window.Dice) { Dice.addHistory([d.roll]); Dice.animate(d.roll); if (!Dice.isOpen()) Dice.toggle(true); }
          });
        } }, icon("dice-5", "sm"), " Spend d" + sd)) : h("span", { class: "faint", style: "font-size:.85rem" }, "Set hit dice (like 5d10) to spend them"),
      total ? h("span", { class: "faint", style: "font-size:.85rem" }, left + " of " + total + " left") : null,
      long);
  }

  // ---- conditions -------------------------------------------------------------
  function renderConds() {
    const wrap = $("#cond-chips");
    const list = model.conditions || [];
    wrap.replaceChildren(...list.map((c) => h("span", { class: "tag" + (c.expired ? " is-warn" : "") },
      c.name, c.rounds_left != null ? " (" + c.rounds_left + ")" : "",
      h("button", { type: "button", "aria-label": "Remove " + c.name, onclick: () => {
        b.set("conditions", (model.conditions || []).filter((x) => x.id !== c.id), true); renderConds();
      } }, icon("x", "sm")))));
    if (!list.length) wrap.append(h("span", { class: "faint" }, "None"));
  }
  const condSel = $("#cond-add");
  condSel.addEventListener("change", () => {
    let name = condSel.value;
    if (!name) return;
    if (name === "__custom") {
      const inp = h("input", { type: "text", placeholder: "Condition or effect", style: "width:16ch;min-height:28px;padding:2px 6px" });
      condSel.replaceWith(inp); inp.focus();
      const done = (save) => {
        const v = inp.value.trim();
        inp.replaceWith(condSel); condSel.value = "";
        if (save && v) addCond(v);
      };
      inp.addEventListener("keydown", (e) => { if (e.key === "Enter") done(true); if (e.key === "Escape") done(false); });
      inp.addEventListener("blur", () => done(true));
      return;
    }
    condSel.value = "";
    addCond(name);
  });
  function addCond(name) {
    if ((model.conditions || []).some((c) => c.name.toLowerCase() === name.toLowerCase())) return;
    b.set("conditions", (model.conditions || []).concat([{ id: L.uid().slice(0, 12), name, note: "", rounds_left: null, expired: false }]), true);
    renderConds();
  }

  // ---- list editors -------------------------------------------------------------
  function listEditor(container, field, cols, blank, opts) {
    opts = opts || {};
    function update(i, key, val) {
      const list = clone(model[field]) || [];
      list[i][key] = val;
      b.set(field, list);
      if (opts.after) opts.after();
    }
    function render() {
      const list = model[field] || [];
      const rows = list.map((row, i) => h("tr", null,
        opts.rowActions ? h("td", { class: "acts-cell" }, opts.rowActions(i, row)) : null,
        cols.map((c) => h("td", { style: c.width ? "width:" + c.width : null },
          c.type === "check"
            ? h("input", { type: "checkbox", checked: !!row[c.key], "aria-label": c.label, onchange: (e) => update(i, c.key, e.target.checked) })
            : h("input", { type: c.type === "number" ? "number" : "text", value: row[c.key] ?? "", placeholder: c.placeholder || "", "aria-label": c.label,
                oninput: (e) => update(i, c.key, c.type === "number" ? (e.target.value === "" ? null : Number(e.target.value)) : e.target.value) }))),
        h("td", { class: "del" }, h("button", { type: "button", class: "icon-btn sm", "aria-label": "Remove row", title: "Remove",
          onclick: () => { const l = clone(model[field]); l.splice(i, 1); b.set(field, l, true); render(); if (opts.after) opts.after(); } }, icon("trash-2", "sm")))));
      container.replaceChildren(
        list.length ? h("table", { class: "list-editor" },
          h("thead", null, h("tr", null, opts.rowActions ? h("th", null, "Roll") : null, cols.map((c) => h("th", null, c.label)), h("th"))),
          h("tbody", null, rows)) : h("p", { class: "faint", style: "margin:4px 0" }, opts.empty || "Nothing yet."),
        h("button", { type: "button", class: "btn btn-sm btn-quiet add-row", onclick: () => {
          b.set(field, (clone(model[field]) || []).concat([Object.assign({}, blank)]), true);
          if (opts.sort) model[field] = opts.sort(model[field]);
          render();
          const inputs = $$("tbody tr:last-child input[type=text]", container);
          if (inputs[0]) inputs[0].focus();
        } }, icon("plus", "sm"), " ", opts.addLabel || "Add"));
      if (opts.after) opts.after();
    }
    render();
    return render;
  }
  const renderAttacks = listEditor($("#attacks"), "attacks", [
    { key: "name", label: "Name", placeholder: "Longsword" },
    { key: "bonus", label: "Atk / DC", placeholder: "+5", width: "80px" },
    { key: "damage", label: "Damage & type", placeholder: "1d8+3 slashing" },
    { key: "notes", label: "Notes", placeholder: "Versatile (1d10)" },
  ], { name: "", bonus: "", damage: "", notes: "" }, {
    addLabel: "Add attack", empty: "No attacks recorded.",
    rowActions: (i) => h("span", { class: "roll-row" },
      h("button", { type: "button", class: "btn btn-sm", "data-roll": "attack:" + i, title: "Roll to hit (shift = advantage)" }, "Hit"),
      h("button", { type: "button", class: "btn btn-sm", "data-roll": "damage:" + i, title: "Roll damage" }, "Dmg"),
      h("button", { type: "button", class: "btn btn-sm btn-quiet", "data-roll": "damage:" + i, "data-crit": "1", title: "Critical hit: double the damage dice" }, "Crit")),
  });

  function eqWeight() {
    const w = (model.equipment || []).reduce((s, r) => s + (Number(r.weight) || 0) * (Number(r.qty) || 1), 0);
    $("#eq-weight").textContent = w ? Math.round(w * 10) / 10 + " lb" : "";
  }
  const renderEquipment = listEditor($("#equipment"), "equipment", [
    { key: "qty", label: "Qty", type: "number", width: "64px" },
    { key: "name", label: "Item", placeholder: "Rope, hempen (50 ft)" },
    { key: "weight", label: "Lb", type: "number", width: "64px" },
    { key: "notes", label: "Notes" },
  ], { qty: 1, name: "", weight: null, notes: "" }, { addLabel: "Add item", empty: "Pack is empty.", after: eqWeight });

  const renderSpells = listEditor($("#spells"), "spells", [
    { key: "prepared", label: "Prep", type: "check", width: "46px" },
    { key: "level", label: "Lvl", type: "number", width: "60px" },
    { key: "name", label: "Spell", placeholder: "Magic Missile" },
    { key: "notes", label: "Time · range · notes", placeholder: "1 action · 120 ft" },
  ], { prepared: false, level: 1, name: "", notes: "" }, { addLabel: "Add spell", empty: "No spells recorded." });

  // ---- spell slots ----------------------------------------------------------------
  function renderSlots() {
    const slots = model.spell_slots || {};
    $("#slots").replaceChildren(...[1, 2, 3, 4, 5, 6, 7, 8, 9].map((lv) => {
      const s = slots[lv] || { max: 0, used: 0 };
      const maxIn = h("input", { type: "number", min: 0, max: 9, value: s.max, "aria-label": "Level " + lv + " slots",
        oninput: () => {
          const all = clone(model.spell_slots) || {};
          const m = Math.max(0, Math.min(9, intOr(maxIn.value, 0)));
          all[lv] = { max: m, used: Math.min((all[lv] || {}).used || 0, m) };
          b.set("spell_slots", all);
          drawPips();
        } });
      const pipWrap = h("span", { class: "pips" });
      function drawPips() {
        const cur = (model.spell_slots || {})[lv] || { max: 0, used: 0 };
        pipWrap.replaceChildren(...Array.from({ length: cur.max }, (_, i) => h("button", {
          type: "button", class: "pip slot" + (i < cur.max - cur.used ? " on" : ""), title: i < cur.max - cur.used ? "Available — click to spend" : "Spent — click to regain",
          onclick: () => {
            const all = clone(model.spell_slots) || {};
            const c = all[lv] || { max: 0, used: 0 };
            const avail = c.max - c.used;
            c.used = i < avail ? c.used + 1 : Math.max(0, c.used - 1);
            all[lv] = c; b.set("spell_slots", all, true); drawPips();
          } })));
      }
      drawPips();
      return h("div", { class: "slot-row" }, h("span", { class: "lvl" }, lv), maxIn, pipWrap);
    }));
  }
  $("#long-rest").addEventListener("click", () => {
    const all = clone(model.spell_slots) || {};
    Object.values(all).forEach((s) => { s.used = 0; });
    b.set("spell_slots", all, true); renderSlots();
    toast("All spell slots restored.", "ok");
  });

  // Notes are written on the Notes tab but shown on the main sheet too, so they're never out of sight.
  function renderNotes() {
    const text = (model.notes || "").trim();
    $("#notes-preview").textContent = text || "No notes yet.";
    $("#notes-preview").classList.toggle("is-empty", !text);
    $("#notes-dot").hidden = !text;
  }
  $("[data-f='notes']").addEventListener("input", renderNotes);
  $("#edit-notes").addEventListener("click", () => { showTab("notes"); $("[data-f='notes']").focus(); });
  renderNotes();

  // ---- re-render after remote change -----------------------------------------------
  function renderField(f) {
    const el = b.inputs.get(f);
    if (el && el._write) el._write(model[f]);
    if (["abilities", "save_bonus", "skill_bonus", "currency"].includes(f)) renderNested();
    if (f === "save_profs" || f === "skill_profs") renderProfs();
    if (f === "death_successes" || f === "death_failures") renderPips();
    if (f === "conditions") renderConds();
    if (f === "attacks") renderAttacks();
    if (f === "equipment") renderEquipment();
    if (f === "spells") renderSpells();
    if (f === "spell_slots") renderSlots();
    if (f === "hit_dice" || f === "hit_dice_used") renderRest();
    if (f === "notes") renderNotes();
  }

  // ---- tabs ----------------------------------------------------------------------
  function showTab(name) {
    $$(".tabs [data-tab]").forEach((t) => { t.classList.toggle("is-on", t.dataset.tab === name); t.setAttribute("aria-selected", t.dataset.tab === name); });
    $$("[data-pane]").forEach((p) => { p.hidden = p.dataset.pane !== name; });
    try { localStorage.setItem("sheet-tab", name); } catch (e) { /* storage unavailable */ }
    if (name === "notes") loadBacklinks();
  }
  $$(".tabs [data-tab]").forEach((t) => t.addEventListener("click", () => showTab(t.dataset.tab)));
  try { const t = localStorage.getItem("sheet-tab"); if (t && $("[data-tab='" + t + "']")) showTab(t); } catch (e) { /* ignore */ }

  async function loadBacklinks() {
    try {
      const d = await api("GET", "/api/links/character/" + char.id);
      const ul = $("#backlinks");
      ul.replaceChildren(...(d.entries.length ? d.entries.map((e) => h("li", null, h("span", { class: "kind" }, e.kind), " ",
        h("a", { href: "/journal?entry=" + e.id }, e.title))) : [h("li", { class: "faint" }, "No journal entries link to this character yet.")]));
    } catch (e) { /* non-critical */ }
  }

  // ---- portrait / archive -------------------------------------------------------------
  $("#portrait-file").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const fd = new FormData(); fd.append("file", file);
    try {
      const d = await api("POST", "/api/characters/" + char.id + "/portrait", fd);
      const box = $(".portrait");
      $$("img, span:not(.portrait-edit)", box).forEach((n) => n.remove());
      box.prepend(h("img", { src: "/api/uploads/" + d.character.portrait, alt: "Portrait" }));
      toast("Portrait saved.", "ok");
    } catch (err) { toast(err.message, "error"); }
  });
  $("#archive-btn").addEventListener("click", () => {
    const to = !model.archived;
    act("PATCH", "/api/characters/" + char.id, { changes: { archived: { from: model.archived, to } } }, () => location.reload());
  });

  // ---- dice: every roll uses the saved sheet, so flush edits first -----------------------
  document.addEventListener("click", (e) => {
    const el = e.target.closest("[data-roll]");
    if (!el || !window.Dice) return;
    e.preventDefault();
    const [type, key] = el.dataset.roll.split(":");
    b.later.flush();
    Dice.roll({ check: { type, key, character_id: char.id }, crit: el.dataset.crit === "1" }, e);
  });

  // ---- keep in sync with combat and other tabs -----------------------------------------
  setInterval(async () => {
    if (document.hidden) return;
    try {
      const d = await api("GET", "/api/characters/" + char.id);
      b.refresh(d.character);
    } catch (e) { /* offline; the save indicator already reports it */ }
  }, 4000);

  renderNested(); renderProfs(); renderPips(); renderConds(); renderSlots(); renderRest(); derive();
  $("[data-f='hit_dice']").addEventListener("input", renderRest);
  $("[data-f='hit_dice_used']").addEventListener("input", renderRest);
})();
