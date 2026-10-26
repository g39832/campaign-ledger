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
    if ($("#ac-bonus")) renderAcBonus();
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
  $$("textarea.one-line").forEach((el) => L.wrapUp(el));
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
  function renderAcBonus() {
    const bonus = (model.conditions || []).reduce((n, x) => n + (x.expired ? 0 : Number(x.ac) || 0), 0);
    const el = $("#ac-bonus");
    el.hidden = !bonus;
    el.textContent = bonus ? "now " + ((Number(model.ac) || 0) + bonus) + " (" + signed(bonus) + ")" : "";
    el.title = bonus ? (model.conditions || []).filter((x) => x.ac && !x.expired).map((x) => x.name + " " + signed(Number(x.ac))).join(", ") : "";
  }
  function renderConds() {
    renderAcBonus();
    const wrap = $("#cond-chips");
    const list = model.conditions || [];
    wrap.replaceChildren(...list.map((c) => h("span", { class: "tag" + (c.expired ? " is-warn" : "") },
      c.name, c.ac && !c.expired ? " " + signed(Number(c.ac)) + " AC" : "", c.rounds_left != null ? " (" + c.rounds_left + ")" : "",
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
    // opts.fold: rows fold to one line (name and a summary); open one to edit it. Open rows are remembered on this device.
    const foldKey = opts.fold ? "sheet-" + field + "-open-" + char.id : null;
    let openRows = new Set();
    if (foldKey) { try { openRows = new Set(JSON.parse(localStorage.getItem(foldKey) || "[]")); } catch (e) { /* private window */ } }
    const saveRows = () => { if (foldKey) try { localStorage.setItem(foldKey, JSON.stringify([...openRows])); } catch (e) { /* ignore */ } };
    const flipRow = (i) => { openRows.has(i) ? openRows.delete(i) : openRows.add(i); saveRows(); render(); };
    function update(i, key, val) {
      const list = clone(model[field]) || [];
      list[i][key] = val;
      b.set(field, list);
      if (opts.after) opts.after();
    }
    function render() {
      const list = model[field] || [];
      const foldBtn = (i, open) => opts.fold ? h("button", { type: "button", class: "icon-btn sm row-fold", "aria-expanded": String(open),
        "aria-label": (open ? "Fold up " : "Open ") + ((list[i] || {}).name || "row"), title: open ? "Fold it up" : "Open it to edit", onclick: () => flipRow(i) },
        icon(open ? "chevron-down" : "chevron-right", "sm")) : null;
      const del = (i) => h("td", { class: "del" }, h("button", { type: "button", class: "icon-btn sm", "aria-label": "Remove row", title: "Remove",
        onclick: () => {
          const l = clone(model[field]); l.splice(i, 1); b.set(field, l, true);
          openRows = new Set([...openRows].filter((k) => k !== i).map((k) => (k > i ? k - 1 : k))); saveRows();
          render(); if (opts.after) opts.after();
        } }, icon("trash-2", "sm")));
      const anyOpen = !opts.fold || list.some((_, i) => openRows.has(i));
      const rows = list.map((row, i) => opts.fold && !openRows.has(i)
        ? h("tr", { class: "is-folded" },
          opts.rowActions ? h("td", { class: "acts-cell", "data-label": "Roll" }, opts.rowActions(i, row)) : null,
          h("td", { class: "fold-cell", colspan: cols.length },
            h("div", { class: "fold-line" }, foldBtn(i, false),
              h("button", { type: "button", class: "fold-text", onclick: () => flipRow(i), title: "Open it to edit" },
                h("b", null, (row.name || "").trim() || "Unnamed"), h("span", { class: "faint" }, opts.fold.summary(row))))),
          del(i))
        : h("tr", { class: opts.fold ? "is-open" : null },
        opts.rowActions ? h("td", { class: "acts-cell", "data-label": "Roll" }, opts.rowActions(i, row)) : null,
        cols.map((c) => {
          const box = c.type === "check"
            ? h("input", { type: "checkbox", checked: !!row[c.key], "aria-label": c.label, onchange: (e) => update(i, c.key, e.target.checked) })
            : c.type === "number"
              ? h("input", { type: "number", value: row[c.key] ?? "", placeholder: c.placeholder || "", "aria-label": c.label,
                oninput: (e) => update(i, c.key, e.target.value === "" ? null : Number(e.target.value)) })
              : L.wrapText({ value: row[c.key] ?? "", placeholder: c.placeholder || "", "aria-label": c.label,
                oninput: (e) => update(i, c.key, e.target.value) });
          // The arrow sits with the name, exactly where it is on a folded row, so folding back up
          // is always the same click.
          return h("td", { style: c.width ? "width:" + c.width : null, "data-label": c.label, class: "f-" + c.key },
            opts.fold && c.key === "name" ? h("div", { class: "open-name" }, foldBtn(i, true), box) : box);
        }),
        del(i)));
      const allOpen = list.length && list.every((_, i) => openRows.has(i));
      container.replaceChildren(
        list.length ? h("table", { class: "list-editor" + (opts.fold ? " foldable" : "") },
          anyOpen ? h("thead", null, h("tr", null, opts.rowActions ? h("th", null, "Roll") : null, cols.map((c) => h("th", null, c.label)), h("th"))) : null,
          h("tbody", null, rows)) : h("p", { class: "faint", style: "margin:4px 0" }, opts.empty || "Nothing yet."),
        opts.fold && list.length > 1 ? h("button", { type: "button", class: "btn btn-sm btn-quiet", onclick: () => {
          openRows = allOpen ? new Set() : new Set(list.map((_, i) => i)); saveRows(); render();
        } }, icon(allOpen ? "chevron-right" : "chevron-down", "sm"), allOpen ? " Fold all" : " Open all") : null,
        h("button", { type: "button", class: "btn btn-sm btn-quiet add-row", onclick: () => {
          b.set(field, (clone(model[field]) || []).concat([Object.assign({}, blank)]), true);
          if (opts.fold) { openRows.add((model[field] || []).length - 1); saveRows(); }
          if (opts.sort) model[field] = opts.sort(model[field]);
          render();
          const inputs = $$("tbody tr:last-child textarea, tbody tr:last-child input[type=text]", container);
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
    { key: "area", label: "Area (optional)", placeholder: "e.g. 10 ft cone, range 20" },
    { key: "cooldown", label: "Cooldown (turns)", type: "number", placeholder: "0" },
    { key: "condition", label: "On a hit, they're", placeholder: "e.g. Grappled" },
    { key: "extra_moves", label: "Extra moves", type: "number", placeholder: "0" },
    { key: "dmg_mult", label: "Damage ×", type: "number", placeholder: "1" },
  ], { name: "", bonus: "", damage: "", notes: "", area: "", cooldown: null, condition: "", extra_moves: null, dmg_mult: null }, {
    addLabel: "Add attack", empty: "No attacks recorded.",
    fold: { summary: attackSummary },
    // A row whose damage or notes say "heal" (Mend · 1d8 · Heal) rolls healing instead of an attack.
    // A move with nothing to roll (Reckless, Action Surge) is used in a fight, so it has no roll buttons.
    rowActions: (i, row) => !String(row.damage || "").trim() && !String(row.bonus || "").trim()
      ? h("span", { class: "roll-row" },
        h("button", { type: "button", class: "btn btn-sm btn-quiet", title: "It's really a spell: move it to Spells (everything on the row comes along)", onclick: () => moveToSpells(i) }, icon("wand-sparkles", "sm"), " To spells"))
      : L.isHealing(row)
      ? h("span", { class: "roll-row" },
        h("button", { type: "button", class: "btn btn-sm btn-heal", "data-roll": "damage:" + i, title: "Roll healing" }, icon("heart", "sm"), " Heal"),
        h("button", { type: "button", class: "btn btn-sm btn-quiet", title: "It's really a spell: move it to Spells (everything on the row comes along)", onclick: () => moveToSpells(i) }, icon("wand-sparkles", "sm"), " To spells"))
      : h("span", { class: "roll-row" },
        h("button", { type: "button", class: "btn btn-sm", "data-roll": "attack:" + i, title: "Roll to hit (shift = advantage)" }, "Hit"),
        h("button", { type: "button", class: "btn btn-sm", "data-roll": "damage:" + i, title: "Roll damage" }, "Dmg"),
        h("button", { type: "button", class: "btn btn-sm btn-quiet", "data-roll": "damage:" + i, "data-crit": "1", title: "Critical hit: double the damage dice" }, "Crit"),
        h("button", { type: "button", class: "btn btn-sm btn-quiet", title: "It's really a spell: move it to Spells (everything on the row comes along)", onclick: () => moveToSpells(i) }, icon("wand-sparkles", "sm"), " To spells")),
  });

  // One line for a folded attack: what it rolls and what's special about it.
  function attackSummary(r) {
    const n = (v) => Number(v) || 0;
    const noDice = !String(r.damage || "").trim();
    return [String(r.bonus || "").trim() ? "Atk " + String(r.bonus).trim() : "",
      String(r.damage || "").trim(),
      r.condition ? "on a hit: " + r.condition : "",
      n(r.extra_moves) ? "+" + n(r.extra_moves) + " extra moves" : "",
      n(r.dmg_mult) > 1 ? (noDice ? "your damage ×" + n(r.dmg_mult) + " this turn" : "×" + n(r.dmg_mult) + " damage on a hit") : "",
      n(r.cooldown) ? n(r.cooldown) + "-turn cooldown" : "",
      String(r.area || "").trim(),
      String(r.notes || "").trim().slice(0, 70)].filter(Boolean).join(" · ");
  }

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

  /* ---- folding sheet sections ----------------------------------------------------------
     There's a lot on a sheet, so each section folds: click its heading. The long ones
     you look at less in play start folded. What you fold is remembered on this device
     (for every sheet). A folded heading says what's inside. */
  const FOLD_KEY = "sheet-folds";
  const FOLD_DEFAULT = { saves: false, skills: true, attacks: false, spells: false, features: true, proficiencies: true, equipment: true, notes: true };
  let folds = {};
  try { folds = JSON.parse(localStorage.getItem(FOLD_KEY) || "{}") || {}; } catch (e) { /* private window */ }
  const isFolded = (k) => (k in folds ? folds[k] : !!FOLD_DEFAULT[k]);
  function foldHints() {
    const set = (k, text) => { const el = $("#" + k + "-hint"); if (el) el.textContent = text; };
    const profs = Object.values(model.skill_profs || {}).filter((v) => Number(v) > 0).length;
    set("skills", isFolded("skills") ? (profs ? profs + " proficient" : "") : "");
    const n = (list) => (list || []).filter((r) => r && (r.name || "").trim()).length;
    set("attacks", isFolded("attacks") ? n(model.attacks) + " attack" + (n(model.attacks) === 1 ? "" : "s") : "");
    set("spells", isFolded("spells") ? n(model.spells) + " spell" + (n(model.spells) === 1 ? "" : "s") : "");
    set("equipment", isFolded("equipment") ? n(model.equipment) + " item" + (n(model.equipment) === 1 ? "" : "s") : "");
    const lines = (t) => String(t || "").split(/\n+/).filter((x) => x.trim()).length;
    set("features", isFolded("features") && lines(model.features) ? lines(model.features) + " line" + (lines(model.features) === 1 ? "" : "s") : "");
    set("proficiencies", isFolded("proficiencies") && (model.proficiencies || "").trim() ? String(model.proficiencies).trim().slice(0, 60) : "");
    set("notes", isFolded("notes") && (model.notes || "").trim() ? "has notes" : "");
  }
  function applyFolds() {
    $$("[data-fold]").forEach((head) => {
      const k = head.dataset.fold, folded = isFolded(k);
      head.classList.toggle("is-folded", folded);
      head.setAttribute("aria-expanded", String(!folded));
      $$('[data-fold-body="' + k + '"]').forEach((b2) => { b2.hidden = folded; });
    });
    foldHints();
  }
  $$("[data-fold]").forEach((head) => {
    head.tabIndex = 0;
    head.setAttribute("role", "button");
    head.title = "Click to fold or open";
    head.prepend(h("span", { class: "fold-arrow", "aria-hidden": "true" }, icon("chevron-down", "sm")));
    const flip = (e) => {
      if (e.target.closest("button, a, input, select, textarea")) return; // Notes' Edit button
      folds[head.dataset.fold] = !isFolded(head.dataset.fold);
      try { localStorage.setItem(FOLD_KEY, JSON.stringify(folds)); } catch (err) { /* ignore */ }
      applyFolds();
    };
    head.addEventListener("click", flip);
    head.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); flip(e); } });
  });
  applyFolds();

  // ---- spells: notes, or damage, healing, a buff or a debuff, with everything it leaves behind ----
  const SPELL_DOES = [["", "Just notes"], ["damage", "Damage"], ["heal", "Healing"], ["buff", "Buff (helps)"], ["debuff", "Debuff (hinders)"]];
  const SPELL_ABIL = [["str", "Strength"], ["dex", "Dexterity"], ["con", "Constitution"], ["int", "Intelligence"], ["wis", "Wisdom"], ["cha", "Charisma"]];
  const SPELL_HIT = [["", "No roll — it just lands"], ["attack", "Spell attack roll"]].concat(SPELL_ABIL.map(([k, l]) => [k, l + " save"]));
  const DAMAGE_TYPES = ["", "acid", "bludgeoning", "cold", "fire", "force", "lightning", "necrotic", "piercing", "poison", "psychic", "radiant", "slashing", "thunder"];
  const ADV_PICK = [["", "No advantage change"], ["attacks_adv", "Its attacks have advantage"], ["attacks_dis", "Its attacks have disadvantage"],
    ["attacked_adv", "Attacks against it have advantage"], ["attacked_dis", "Attacks against it have disadvantage"]];
  const ONGOING_PICK = [["damage", "damage"], ["heal", "healing"], ["temp", "temp HP"]];
  const SPELL_BLANK = { prepared: false, level: 1, name: "", notes: "", effect: "", dice: "", hit: "", condition: "", rounds: null, ac: null };
  /* Spells fold up to one line (name, what it does, its roll buttons); click the arrow
     or the summary to open one and edit it. Which ones are open is remembered on this
     device. A spell that was just added opens by itself. */
  const OPEN_KEY = "sheet-spells-open-" + char.id;
  let openSpells = new Set();
  try { openSpells = new Set(JSON.parse(localStorage.getItem(OPEN_KEY) || "[]")); } catch (e) { /* private window */ }
  const saveOpen = () => { try { localStorage.setItem(OPEN_KEY, JSON.stringify([...openSpells])); } catch (e) { /* ignore */ } };
  const setOpen = (i, on) => { on ? openSpells.add(i) : openSpells.delete(i); saveOpen(); };
  const openNew = () => setOpen((model.spells || []).length - 1, true);
  function renderSpells() {
    const box = $("#spells");
    const list = model.spells || [];
    const set = (i, key, val, redraw) => {
      const l = clone(model.spells) || [];
      l[i] = Object.assign({}, SPELL_BLANK, l[i], { [key]: val });
      b.set("spells", l, !!redraw);
      if (redraw) renderSpells();
    };
    const sp = derived().spell;
    // Short fields (dice, condition with its suggestion list) stay inputs; names and notes wrap.
    const text = (i, key, attrs) => (attrs && attrs.list) || attrs && attrs.short
      ? h("input", Object.assign({ type: "text", value: list[i][key] ?? "", oninput: (e) => set(i, key, e.target.value) }, attrs, { short: null }))
      : L.wrapText(Object.assign({ value: list[i][key] ?? "", oninput: (e) => set(i, key, e.target.value) }, attrs));
    const pick = (i, key, options, attrs, value) => h("select", Object.assign({ onchange: (e) => set(i, key, e.target.value, true) }, attrs),
      options.map(([v, l]) => h("option", { value: v, selected: (value ?? (list[i][key] || "")) === v }, l)));
    const num = (i, key, attrs) => h("input", Object.assign({ type: "number", value: list[i][key] ?? "",
      oninput: (e) => set(i, key, e.target.value === "" ? null : Number(e.target.value)), onchange: () => renderSpells() }, attrs));
    const chk = (i, key, label, on, title) => h("label", { class: "check", style: "font-size:.88rem", title: title || null },
      h("input", { type: "checkbox", checked: on, onchange: (e) => set(i, key, e.target.checked, true) }), label);
    const field = (label, el, cls) => h("label", { class: "field" + (cls ? " " + cls : "") }, h("span", null, label), el);
    const cards = list.map((s, i) => {
      const v = L.spellView(s), does = v.kind;
      const rolls = [];
      if (does === "damage" && s.hit === "attack") rolls.push(h("button", { type: "button", class: "btn btn-sm", "data-roll": "spell_attack", title: "Roll a spell attack" }, "Attack" + (sp ? " " + signed(sp.atk) : "")));
      if (does === "damage" && s.dice) rolls.push(h("button", { type: "button", class: "btn btn-sm", "data-roll": "spell:" + i, title: "Roll damage" }, "Dmg"),
        s.hit === "attack" ? h("button", { type: "button", class: "btn btn-sm btn-quiet", "data-roll": "spell:" + i, "data-crit": "1", title: "Critical: double the dice" }, "Crit") : null);
      if (does === "heal" && s.dice) rolls.push(h("button", { type: "button", class: "btn btn-sm btn-heal", "data-roll": "spell:" + i, title: "Roll healing" }, icon("heart", "sm"), " Heal"));
      const save = s.hit && s.hit !== "attack" ? h("span", { class: "tag" }, (SPELL_ABIL.find(([k]) => k === s.hit) || [, ""])[1] + " save" + (sp ? " · DC " + sp.dc : "")) : null;
      const what = L.spellWhat(v);
      const summary = what && does !== "damage" && does !== "heal" ? h("span", { class: "tag" + (Number(s.ac) > 0 ? " ac-tag" : "") }, what) : null;
      const del = h("button", { type: "button", class: "icon-btn sm", "aria-label": "Remove spell", title: "Remove",
        onclick: () => {
          const l = clone(model.spells); l.splice(i, 1); b.set("spells", l, true);
          openSpells = new Set([...openSpells].filter((k) => k !== i).map((k) => (k > i ? k - 1 : k))); saveOpen();
          renderSpells();
        } }, icon("trash-2", "sm"));
      const back = s.from_attack ? h("button", { type: "button", class: "btn btn-sm btn-quiet", title: "Put it back in Attacks exactly as it was",
        onclick: () => {
          const l = clone(model.spells); const [row] = l.splice(i, 1);
          b.set("spells", l, true); b.set("attacks", (clone(model.attacks) || []).concat([row.from_attack]), true);
          openSpells = new Set([...openSpells].filter((k) => k !== i).map((k) => (k > i ? k - 1 : k))); saveOpen();
          renderSpells(); renderAttacks(); toast(row.name + " is back in Attacks.", "ok");
        } }, icon("undo-2", "sm"), " Back to attacks") : null;
      const harmful = does === "damage" || does === "debuff";
      const lasting = does === "buff" || does === "debuff" || (does === "damage" && (s.condition || s.ongoing));
      // the rarer effects, folded away until needed (open when one is set)
      const extras = [s.roll_mod, s.dmg_mod, s.adv, s.temp_hp, s.max_hp, s.ongoing, s.repeat_save, s.ac, s.terrain, s.summon, s.parry].some((x) => x != null && x !== "" && x !== false && x !== 0);
      const more = does ? h("details", { class: "spell-more", "data-key": "spell-more-" + i, open: extras ? true : null },
        h("summary", { class: "lbl" }, "More effects (bonus to rolls, advantage, temp HP, every turn, upcasting…)"),
        h("div", { class: "spell-fields" },
          does !== "damage" ? field("AC change", num(i, "ac", { min: -10, max: 30, placeholder: "e.g. +2", title: "Temporary AC while it lasts: +2 Shield of Faith, +5 Shield, −2 Slow" })) : null,
          does !== "heal" ? field(does === "debuff" ? "Penalty to attacks & saves" : "Bonus to attacks & saves", text(i, "roll_mod", { short: true, placeholder: does === "debuff" ? "-1d4" : "1d4", title: "Bless: 1d4 · Bane: -1d4" })) : null,
          does === "buff" ? field("Extra damage on hits", text(i, "dmg_mod", { short: true, placeholder: "1d4", title: "Divine Favor: 1d4" })) : null,
          does !== "heal" ? field("Advantage", pick(i, "adv", ADV_PICK)) : null,
          does === "buff" || does === "heal" ? field("Temp HP", text(i, "temp_hp", { short: true, placeholder: "1d4+4", title: "False Life: 1d4+4" })) : null,
          does === "buff" ? field("More max HP", num(i, "max_hp", { min: 0, max: 100, placeholder: "e.g. 5", title: "Aid: 5. It goes away again when the effect ends." })) : null,
          field("Every turn", h("div", { class: "row", style: "gap:4px;flex-wrap:nowrap" },
            text(i, "ongoing", { short: true, placeholder: "2d10", title: "Rolled at the start of the target's turn while it lasts (Moonbeam 2d10, Heroism mod, Regenerate 1)", style: "flex:1 1 60px;min-width:0" }),
            pick(i, "ongoing_kind", ONGOING_PICK, { style: "flex:0 1 auto;width:auto" }, s.ongoing_kind || (does === "heal" ? "heal" : "damage")))),
          s.ongoing && (s.ongoing_kind || "damage") === "damage" && s.hit && s.hit !== "attack" ? chk(i, "ongoing_save", "They save each turn for half", !!s.ongoing_save) : null,
          harmful && s.hit && s.hit !== "attack" && lasting ? chk(i, "repeat_save", "Save at the end of each turn to end it", !!s.repeat_save, "Hold Person: a Wisdom save at the end of each of its turns") : null,
          does === "damage" && s.hit && s.hit !== "attack" ? chk(i, "save_half", "Half damage on a save", v.save_half != null ? !!v.save_half : Number(s.level) > 0) : null,
          does === "damage" || does === "heal" || does === "buff" ? field("Upcast: per level above", text(i, "upcast", { short: true, placeholder: does === "heal" ? "1d8" : "1d6", title: "Extra dice for each slot level above the spell's level" })) : null,
          field("Reaches at most", num(i, "targets", { min: 1, max: 50, placeholder: "any", title: "Bless: 3 · Mass Healing Word: 6 · Shield: 1" })),
          field("Area", text(i, "area", { short: true, placeholder: "20 ft sphere", title: "Aim it on the battle map: 15 ft cone, 20 ft radius, 100 ft line" })),
          field("Summons (a creature from the library)", text(i, "summon", { short: true, placeholder: "e.g. Yamato clone", title: "It joins the fight on your side, next to you, and acts right after you" })),
          chk(i, "parry", "Parry: when hit, roll off d20 vs the DM — win and take half", !!s.parry, "A reaction: a Parry? button shows when they're hit"),
          field("Changes the map", pick(i, "terrain", [["", "No"], ["rock", "Raise solid rock (blocks movement)"], ["mend", "Mend the ground"]], { title: "Aim it on the battle map; it needs an Area" })),
          field("Cooldown (turns)", num(i, "cooldown", { min: 0, max: 20, placeholder: "0" })))) : null;
      const open = openSpells.has(i);
      const toggle = () => { setOpen(i, !open); renderSpells(); };
      const brief = [L.levelWord(v), L.spellWhat(v) || (does ? "" : "notes"), s.notes ? String(s.notes).slice(0, 80) : ""].filter(Boolean).join(" · ");
      return h("div", { class: "spell-card" + (does ? " does-" + does : "") + (open ? " is-open" : " is-folded") },
        h("div", { class: "spell-top" },
          h("button", { type: "button", class: "icon-btn sm spell-fold", "aria-expanded": String(open), "aria-label": (open ? "Fold up " : "Open ") + (s.name || "spell"),
            title: open ? "Fold it up" : "Open it to edit", onclick: toggle }, icon(open ? "chevron-down" : "chevron-right", "sm")),
          text(i, "name", { placeholder: "Spell name", "aria-label": "Spell name", class: "spell-name" }),
          h("div", { class: "spell-rolls roll-row" }, rolls, save, open ? summary : null, v.concentration ? h("span", { class: "tag" }, "Concentration") : null),
          back, del),
        open ? null : h("button", { type: "button", class: "spell-brief", onclick: toggle, title: "Open it to edit" }, brief || "Click to open"),
        open ? h("div", { class: "spell-fields" },
          field("Does", pick(i, "effect", SPELL_DOES, null, does)),
          field("Level", pick(i, "level", [["0", "Cantrip"]].concat([1, 2, 3, 4, 5, 6, 7, 8, 9].map((n) => [String(n), "Level " + n])), null, String(Number(s.level) || 0))),
          does === "damage" || does === "heal" ? field(does === "heal" ? "Healing dice" : "Damage dice",
            text(i, "dice", { short: true, placeholder: does === "heal" ? "1d8+mod" : "8d6", title: "Dice, like 2d6+3. Write mod for your spellcasting modifier.", onchange: () => renderSpells() })) : null,
          does === "damage" ? field("Damage type", pick(i, "damage_type", DAMAGE_TYPES.map((t) => [t, t ? t.charAt(0).toUpperCase() + t.slice(1) : "—"]))) : null,
          harmful ? field("Lands by", pick(i, "hit", SPELL_HIT)) : null,
          does && does !== "heal" ? field(does === "damage" ? "Also leaves (optional)" : "Condition / effect",
            text(i, "condition", { placeholder: does === "buff" ? "Blessed" : does === "debuff" ? "Frightened" : "e.g. Prone", list: "spell-conds", onchange: () => renderSpells() })) : null,
          does && does !== "heal" || s.ongoing ? field("Rounds", num(i, "rounds", { min: 1, max: 100000, placeholder: "—", title: "How many rounds it lasts (1 minute = 10, 1 hour = 600)" })) : null,
          does ? chk(i, "concentration", "Concentration", !!v.concentration, "Casting another concentration spell ends it, and taking damage can break it") : null,
          more,
          field("Time · range · notes", text(i, "notes", { placeholder: "1 action · 120 ft" }), "spell-notes")) : null);
    });
    const allOpen = list.length && list.every((_, i) => openSpells.has(i));
    box.replaceChildren(
      list.length ? h("div", { class: "spell-list" }, cards) : h("p", { class: "faint", style: "margin:4px 0" }, "No spells yet."),
      h("div", { class: "row", style: "gap:6px;margin-top:6px" },
        list.length > 1 ? h("button", { type: "button", class: "btn btn-sm btn-quiet", style: "margin:0", onclick: () => {
          openSpells = allOpen ? new Set() : new Set(list.map((_, i) => i)); saveOpen(); renderSpells();
        } }, icon(allOpen ? "chevron-right" : "chevron-down", "sm"), allOpen ? " Fold all" : " Open all") : null,
        h("button", { type: "button", class: "btn btn-sm btn-quiet add-row", style: "margin:0", onclick: () => {
          b.set("spells", (clone(model.spells) || []).concat([Object.assign({}, SPELL_BLANK)]), true);
          openNew();
          renderSpells();
          const names = $$(".spell-name", box); if (names.length) names[names.length - 1].focus();
        } }, icon("plus", "sm"), " Add spell"),
        h("button", { type: "button", class: "btn btn-sm", id: "sb-toggle", "aria-expanded": String(!$("#spell-book").hidden), onclick: () => {
          const panel = $("#spell-book"); panel.hidden = !panel.hidden;
          $("#sb-toggle").setAttribute("aria-expanded", String(!panel.hidden));
          if (!panel.hidden) { renderSpellBook(); $("#sb-q").focus(); }
        } }, icon("book-open", "sm"), " Add from spell list")));
    if (!$("#spell-book").hidden) renderSpellBook();
    L.restoreOpen(box);
  }

  /* An attack row that's really a spell (Mend 1d8 heal, Shield of faith +2 AC, Entangle: makes
     prone) moves to Spells with its best guess at what it does. Everything on the row comes
     along, and "Back to attacks" puts it back exactly as it was. */
  const COND_WORDS = ["Blinded", "Charmed", "Deafened", "Frightened", "Grappled", "Incapacitated", "Invisible", "Paralyzed", "Petrified", "Poisoned", "Prone", "Restrained", "Stunned", "Unconscious"];
  function attackToSpell(row) {
    const all = [row.name, row.bonus, row.damage, row.notes].filter(Boolean).join(" ");
    const dice = (String(row.damage || "").match(/\d*d\d+(?:\s*[+-]\s*\d+)?/i) || [""])[0].replace(/\s/g, "");
    const type = DAMAGE_TYPES.find((t) => t && new RegExp("\\b" + t + "\\b", "i").test(all)) || "";
    const ac = /([+-]\s*\d+)\s*(?:to\s+)?ac\b/i.exec(all);
    const cond = COND_WORDS.find((w) => new RegExp("\\b" + w.replace(/ed$/, "") + "(?:e|ed)?\\b", "i").test(all)) || "";
    const notes = [row.notes, row.bonus && !/^\s*(?:1?d20)?\s*[+-]?\s*\d*\s*$/i.test(row.bonus) ? "Atk/DC " + row.bonus : ""].filter(Boolean).join(" · ");
    const s = Object.assign({}, SPELL_BLANK, { name: (row.name || "Spell").trim(), notes, level: 0, area: row.area || "", cooldown: row.cooldown ?? null,
      from_attack: Object.assign({}, row) });
    if (L.isHealing(row) && dice) Object.assign(s, { effect: "heal", dice });
    else if (dice) Object.assign(s, { effect: "damage", dice, damage_type: type, hit: String(row.bonus || "").trim() ? "attack" : "", condition: cond });
    else if (ac) Object.assign(s, { effect: Number(ac[1].replace(/\s/g, "")) > 0 ? "buff" : "debuff", condition: s.name, ac: Number(ac[1].replace(/\s/g, "")) });
    else if (cond) Object.assign(s, { effect: "debuff", condition: cond, hit: "attack" });
    return s;
  }
  function moveToSpells(i) {
    const rows = clone(model.attacks) || [];
    const [row] = rows.splice(i, 1);
    if (!row) return;
    const s = attackToSpell(row);
    b.set("attacks", rows, true);
    b.set("spells", (clone(model.spells) || []).concat([s]), true);
    openNew();
    renderAttacks(); renderSpells();
    toast(s.name + " moved to Spells" + (s.effect ? " as " + ({ damage: "a damage", heal: "a healing", buff: "a buff", debuff: "a debuff" })[s.effect] + " spell" : "") + ". Check what it does there.", "ok", { ms: 7000 });
  }

  // ---- the spell list: common spells ready to add ---------------------------------------
  const BOOK = (window.SPELL_BOOK && window.SPELL_BOOK.spells) || [];
  const KIND_LABEL = { damage: "Damage", heal: "Healing", buff: "Buff", debuff: "Debuff" };
  function bookSummary(s) {
    const bits = [KIND_LABEL[s.effect], L.levelWord(s)];
    if (s.dice) bits.push(s.dice + (s.damage_type ? " " + s.damage_type : ""));
    if (s.hit === "attack") bits.push("spell attack");
    else if (s.hit) bits.push(s.hit.toUpperCase() + " save");
    const what = L.spellWhat(s).replace(/^[^·]*damage · |^heals [^·]* · ?/, "");
    if (what && s.effect !== "damage" && s.effect !== "heal") bits.push(what);
    else if (s.condition && s.condition !== s.name) bits.push(s.condition);
    if (s.concentration) bits.push("concentration");
    return bits.filter(Boolean).join(" · ");
  }
  function renderSpellBook() {
    const q = $("#sb-q").value.trim().toLowerCase(), kind = $("#sb-kind").value;
    const have = new Set((model.spells || []).map((s) => (s.name || "").trim().toLowerCase()));
    const items = BOOK.filter((s) => (!kind || s.effect === kind) && (!q || [s.name, s.notes, bookSummary(s)].join(" ").toLowerCase().includes(q)));
    $("#sb-credit").textContent = (window.SPELL_BOOK || {}).attribution || "";
    $("#sb-list").replaceChildren(...(items.length ? items.map((s) => h("li", { class: have.has(s.name.toLowerCase()) ? "is-added" : "" },
      h("span", { class: "sb-name" }, h("b", null, s.name), h("span", { class: "faint" }, bookSummary(s)), h("span", { class: "faint sb-notes" }, s.notes)),
      have.has(s.name.toLowerCase())
        ? h("span", { class: "book-done" }, icon("check", "sm"), " Added")
        : h("button", { type: "button", class: "btn btn-sm", onclick: () => {
          b.set("spells", (clone(model.spells) || []).concat([Object.assign({}, SPELL_BLANK, s)]), true);
          openNew();
          renderSpells();
          toast(s.name + " added.", "ok");
        } }, icon("plus", "sm"), " Add"))) : [h("li", { class: "faint" }, "No spells match.")]));
  }
  $("#sb-q").addEventListener("input", renderSpellBook);
  $("#sb-kind").addEventListener("change", renderSpellBook);
  renderSpells();
  $("[data-f='spellcasting_ability']").addEventListener("change", () => setTimeout(renderSpells, 0));

  // ---- spell slots ----------------------------------------------------------------
  function renderSlots() {
    if (!$("#slots")) return; // spell slots aren't shown; saved slot numbers are kept as they are
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
  if ($("#long-rest")) $("#long-rest").addEventListener("click", () => {
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
    foldHints();
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
    if (type === "death") { // rolled and marked by the server (allies beside them add a bonus)
      act("POST", "/api/characters/" + char.id + "/death-save", {}, (d) => { Dice.show(d.roll); b.refresh(d.character); renderPips(); derive(); });
      return;
    }
    Dice.roll({ check: { type, key, character_id: char.id }, crit: el.dataset.crit === "1" }, e, { wait: type === "attack" }).then((r) => {
      // homebrew: a natural 20 to hit rolls the damage with double dice
      if (type === "attack" && r && r.result && r.result.natural === 20 && (model.attacks || [])[key] && (model.attacks[key].damage || "").trim())
        Dice.roll({ check: { type: "damage", key, character_id: char.id }, crit: true });
    });
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
