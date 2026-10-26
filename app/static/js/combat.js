/* Combat screen. The server owns all combat state; every action goes through
   the save queue and the response (the full encounter state) is rendered.
   Nothing about the fight lives only in the browser. */
(function () {
  "use strict";
  const { h, icon, $, $$, signed, boot, act, api, toast, Save, Binder, armed, fmtTime, initials } = L;
  let S = boot("boot-state");
  const chars = boot("boot-chars");
  let creatures = boot("boot-creatures");
  const CONDITIONS = boot("boot-conditions");
  const EID = S.encounter.id;
  const OUT = new Set(["dead", "defeated", "fled"]);
  const STATUS_LABEL = { ok: "Fighting", unconscious: "Unconscious", stable: "Stable", incapacitated: "Incapacitated", defeated: "Defeated", dead: "Dead", fled: "Fled" };
  let selected = null;
  try { selected = Number(localStorage.getItem("combat-sel-" + EID)) || null; } catch (e) { /* ignore */ }

  const byId = (id) => S.combatants.find((c) => c.id === id);
  const current = () => byId(S.encounter.current_id);

  function onErr(err) {
    toast(err.message, "error");
    if (err.status === 409) refresh(true);
  }
  function run(method, url, body, after) {
    return act(method, url, body, (d) => { if (d && d.encounter) apply(d); if (after) after(d); }, { onError: onErr });
  }
  const hpLevel = (c) => {
    if (c.hp <= 0) return "dead";
    const p = c.max_hp ? (c.hp / c.max_hp) * 100 : 0;
    return p <= 25 ? "low" : p <= 50 ? "mid" : "high";
  };
  const hpbar = (c) => h("span", { class: "hpbar", "data-level": hpLevel(c) },
    h("span", { class: "hpbar-fill", style: "width:" + (c.max_hp ? Math.min(100, Math.floor((c.hp / c.max_hp) * 100)) : 0) + "%" }),
    c.temp_hp ? h("span", { class: "hpbar-temp" }) : null);
  const token = (c) => h("span", { class: "token" + (c.kind === "enemy" ? " enemy" : "") },
    c.portrait ? h("img", { src: "/api/uploads/" + c.portrait, alt: "" }) : initials(c.name));

  // ---- apply + focus preservation -----------------------------------------------
  function apply(state) {
    const a = document.activeElement;
    const keep = a && a.dataset && a.dataset.keep ? { key: a.dataset.keep, start: a.selectionStart, end: a.selectionEnd, value: a.value } : null;
    const before = S;
    S = state;
    if (selected && !byId(selected)) selected = null;
    if (!selected && S.combatants.length) selected = (current() || S.combatants[0]).id;
    renderBar(); renderList(); renderDetail(); renderLog(); renderAdd();
    if (before !== state) celebrate(before, state);
    if (keep) {
      const el = document.querySelector('[data-keep="' + keep.key + '"]');
      if (el) { el.focus(); try { el.setSelectionRange(keep.start, keep.end); } catch (e) { /* number inputs */ } }
    }
  }
  function select(id) {
    selected = id;
    try { localStorage.setItem("combat-sel-" + EID, id); } catch (e) { /* ignore */ }
    renderList(); renderDetail();
    if (window.Dice && Dice.history) Dice.renderHistory();
  }

  // ---- top bar ------------------------------------------------------------------
  const nameBinder = new Binder({
    url: "/api/encounters/" + EID, model: { name: S.encounter.name },
    extract: (d) => { setTimeout(() => apply(d), 0); return d.encounter; },
  });
  nameBinder.bind($("#enc-name"), "name");

  function renderBar() {
    const e = S.encounter, st = e.status;
    const label = $("#enc-status");
    label.textContent = { planning: "Prepared", active: "In combat", ended: "Ended" }[st];
    label.className = "status-label " + st;
    if (document.activeElement !== $("#enc-name") && !nameBinder.pending.size) {
      nameBinder.baseline.name = nameBinder.model.name = e.name;
      $("#enc-name").value = e.name;
    }
    $("#round").textContent = e.round || "—";
    const cur = current();
    $("#now").textContent = st === "active" && cur ? cur.name : st === "ended" ? "Combat over" : "Not started";
    $("#start").hidden = st !== "planning";
    $("#reopen").hidden = st !== "ended";
    $("#end").hidden = st === "ended";
    $("#next").disabled = $("#prev").disabled = st !== "active";
    const u = $("#undo");
    u.disabled = !S.undo;
    u.title = S.undo ? "Undo: " + S.undo.label : "No HP change to undo";
    $("span", u).textContent = "Undo HP";
    $("#count").textContent = S.combatants.length ? S.combatants.filter((c) => !OUT.has(c.status)).length + " standing of " + S.combatants.length : "";
    document.title = e.name + (st === "active" ? " · Round " + e.round : "") + " · Campaign Ledger";
  }
  $("#next").addEventListener("click", () => run("POST", "/api/encounters/" + EID + "/next", {}, () => { const c = current(); if (c) select(c.id); }));
  $("#prev").addEventListener("click", () => run("POST", "/api/encounters/" + EID + "/prev", {}, () => { const c = current(); if (c) select(c.id); }));
  $("#start").addEventListener("click", () => run("POST", "/api/encounters/" + EID + "/start", {}, () => { const c = current(); if (c) select(c.id); }));
  $("#reopen").addEventListener("click", () => run("POST", "/api/encounters/" + EID + "/reopen"));
  $("#open-map").addEventListener("click", () => act("POST", "/api/encounters/" + EID + "/map", {}, (d) => {
    location.href = "/map/" + d.map_id + (d.created ? "?new=1" : "");
  }));
  armed($("#end"), () => run("POST", "/api/encounters/" + EID + "/end"), "End combat? Click again");
  $("#undo").addEventListener("click", () => {
    act("POST", "/api/encounters/" + EID + "/undo", {}, apply, {
      onError: (err) => {
        if (err.status === 409 && err.data.needs_force) {
          toast(err.message, "error", { ms: 12000, action: { label: "Undo anyway", run: () => run("POST", "/api/encounters/" + EID + "/undo", { force: true }) } });
        } else onErr(err);
      },
    });
  });
  $("#roll-missing").addEventListener("click", () => run("POST", "/api/encounters/" + EID + "/roll", { scope: "missing" }));
  $("#roll-enemies").addEventListener("click", () => run("POST", "/api/encounters/" + EID + "/roll", { scope: "enemies" }));
  $("#sort").addEventListener("click", () => run("POST", "/api/encounters/" + EID + "/sort"));

  document.addEventListener("keydown", (e) => {
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    const t = e.target;
    if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable)) return;
    if (e.key === "n" || e.key === "N") { if (!$("#next").disabled) { e.preventDefault(); $("#next").click(); } }
    if (e.key === "p" || e.key === "P") { if (!$("#prev").disabled) { e.preventDefault(); $("#prev").click(); } }
  });

  // ---- initiative list --------------------------------------------------------------
  function move(c, dir) {
    const ids = S.combatants.map((x) => x.id);
    const i = ids.indexOf(c.id), j = i + dir;
    if (j < 0 || j >= ids.length) return;
    [ids[i], ids[j]] = [ids[j], ids[i]];
    run("POST", "/api/encounters/" + EID + "/reorder", { ids, moved_name: c.name });
  }
  function renderList() {
    const ol = $("#init-list");
    if (!S.combatants.length) {
      ol.replaceChildren(h("li", { class: "empty", style: "border:0" }, h("h3", null, "No combatants yet"), "Add the party and some enemies below, set initiative, then start combat."));
      return;
    }
    const active = S.encounter.status === "active";
    ol.replaceChildren(...S.combatants.map((c, i) => {
      const isCur = active && c.id === S.encounter.current_id;
      const initIn = h("input", { type: "number", value: c.init_roll ?? "", placeholder: "—", "aria-label": "Initiative for " + c.name, "data-keep": "init-" + c.id,
        onchange: (e) => {
          const v = e.target.value.trim();
          run("PATCH", "/api/combatants/" + c.id, { changes: { init_roll: { from: c.init_roll, to: v === "" ? null : Number(v) } } });
        },
        onkeydown: (e) => { if (e.key === "Enter") e.target.blur(); } });
      return h("li", { class: "combatant" + (isCur ? " is-current" : "") + (c.id === selected ? " is-selected" : "") + (OUT.has(c.status) ? " is-out" : ""), "data-cid": c.id,
        "aria-current": isCur ? "true" : null,
        onclick: (e) => { if (!e.target.closest("input,button,a")) select(c.id); } },
        h("div", { class: "c-move" },
          h("button", { type: "button", "aria-label": "Move " + c.name + " up", disabled: i === 0, onclick: () => move(c, -1) }, icon("chevron-up", "sm")),
          h("button", { type: "button", "aria-label": "Move " + c.name + " down", disabled: i === S.combatants.length - 1, onclick: () => move(c, 1) }, icon("chevron-down", "sm"))),
        h("div", { class: "c-init" }, initIn, h("span", { class: "m" }, signed(c.init_mod))),
        token(c),
        h("div", { class: "c-main" },
          h("div", { class: "c-name" }, h("span", null, c.name), isCur ? h("span", { class: "acting" }, "acting") : null),
          h("div", { class: "c-sub" }, [c.kind === "enemy" ? (c.subtitle || "Enemy") : (c.kind === "pc" ? "Player character" : "NPC") + (c.subtitle ? " · " + c.subtitle : ""),
            c.status !== "ok" ? " · " + STATUS_LABEL[c.status] : ""].join("")),
          c.conditions.length ? h("div", { class: "c-conds" }, c.conditions.map((x) => h("span", { class: "tag" + (x.expired ? " is-warn" : "") },
            x.name + (x.ac && !x.expired ? " " + signed(x.ac) + " AC" : "") + (x.rounds_left != null ? " · " + x.rounds_left : "") + (x.expired ? " — expired" : "")))) : null,
          (c.notes || "").trim() ? h("div", { class: "c-note", title: c.notes }, icon("scroll-text", "sm"), h("span", null, c.notes.trim())) : null),
        h("div", { class: "c-hp" },
          h("div", { class: "hp-text" }, h("span", null, h("b", null, c.hp), " / " + c.max_hp), c.temp_hp ? h("span", { class: "temp" }, "+" + c.temp_hp + " temp") : null),
          hpbar(c)),
        h("div", { class: "c-ac" + (c.ac_bonus ? " has-bonus" : ""), title: c.ac_bonus ? c.ac_base + " " + signed(c.ac_bonus) + " from effects" : null },
          c.ac, h("small", null, c.ac_bonus ? "AC " + signed(c.ac_bonus) : "AC")));
    }));
  }

  // ---- effects: hits, heals, knock-outs and turn changes --------------------------------
  function celebrate(before, now) {
    if (!window.FX || !before || before.encounter.id !== now.encounter.id) return;
    const was = new Map(before.combatants.map((c) => [c.id, c]));
    let sound = null;
    for (const c of now.combatants) {
      const p = was.get(c.id);
      if (!p) continue;
      const row = document.querySelector('#init-list [data-cid="' + c.id + '"]');
      const total = (x) => x.hp + (x.temp_hp || 0);
      const diff = total(c) - total(p);
      if (diff < 0) {
        FX.float(row, "−" + Math.abs(diff), "dmg"); FX.flash(row, "hit"); sound = sound || "hit";
        if (c.hp === 0 && p.hp > 0) { FX.float(row, OUT.has(c.status) || c.kind === "enemy" ? "Defeated!" : "Down!", "down"); FX.flash(row, "down"); sound = "down"; }
      } else if (c.hp > p.hp) { FX.float(row, "+" + (c.hp - p.hp), "heal"); FX.flash(row, "heal"); FX.burst(row, "heal", 18); sound = sound || "heal"; }
      if (c.ac > p.ac) { FX.float(row, "+" + (c.ac - p.ac) + " AC", "ac"); sound = sound || "ac"; }
    }
    const e0 = before.encounter, e1 = now.encounter;
    if (e1.status === "active" && e0.status !== "active") { FX.banner("Roll for initiative!", e1.name, "crit"); sound = "start"; }
    else if (e1.status === "ended" && e0.status === "active") { FX.banner("Combat over", e1.name, "info"); sound = "turn"; }
    else if (e1.status === "active" && (e1.current_id !== e0.current_id || e1.round !== e0.round)) {
      const cur = byId(e1.current_id);
      if (cur) { FX.banner(cur.name + "'s turn", "Round " + e1.round, cur.kind === "enemy" ? "dmg" : "info"); sound = sound || "turn"; }
    }
    if (sound) FX.sound(sound);
  }

  // ---- detail panel ----------------------------------------------------------------
  function renderDetail() {
    const box = $("#detail");
    const c = byId(selected);
    if (!c) {
      box.replaceChildren(h("div", { class: "detail-sec faint" }, "Select a combatant to manage HP, conditions and details."));
      return;
    }
    const cid = c.id;
    const amt = h("input", { type: "number", min: 0, placeholder: "0", "aria-label": "Amount", "data-keep": "amt-" + cid, inputmode: "numeric",
      onkeydown: (e) => { if (e.key === "Enter") { e.preventDefault(); hp(e.shiftKey ? "heal" : "damage"); } } });
    function hp(op) {
      const n = Number(amt.value);
      if (!amt.value || !Number.isFinite(n) || n < 0) { amt.focus(); return; }
      run("POST", "/api/combatants/" + cid + "/hp", { op, amount: Math.trunc(n) });
      amt.value = "";
    }
    const statusSel = h("select", { "aria-label": "Status", style: "width:auto", onchange: (e) => run("PATCH", "/api/combatants/" + cid, { changes: { status: { from: c.status, to: e.target.value } } }) },
      Object.entries(STATUS_LABEL).filter(([k]) => c.kind === "enemy" ? k !== "stable" : k !== "defeated").map(([k, v]) => h("option", { value: k, selected: k === c.status }, v)));
    const removeBtn = h("button", { type: "button", class: "btn btn-sm btn-quiet btn-danger" }, icon("trash-2", "sm"), " Remove");
    armed(removeBtn, () => run("DELETE", "/api/combatants/" + cid), "Remove " + c.name + "?");

    const sections = [];
    sections.push(h("div", { class: "detail-head" }, token(c),
      h("div", { class: "grow", style: "min-width:0" }, h("h2", null, c.name),
        h("div", { class: "faint", style: "font-size:.9rem" }, c.kind === "enemy" ? (c.subtitle || "Enemy") : (c.kind === "pc" ? "Player character" : "NPC"),
          c.linked ? [" · ", h("a", { href: "/characters/" + c.character_id }, "open sheet")] : null)),
      statusSel));

    // Notes sit right under the name so they're seen before anything else.
    const notes = h("textarea", { rows: 3, placeholder: "Notes for this combatant", "aria-label": "Combatant notes", "data-keep": "notes-" + cid, class: "note-input" },
      c.notes);
    notes.addEventListener("change", () => run("PATCH", "/api/combatants/" + cid, { changes: { notes: { from: c.notes, to: notes.value } } }));
    sections.push(h("div", { class: "detail-sec" }, h("h3", { class: "rule-head" }, "Notes"), notes));

    // HP
    const editMax = h("input", { type: "number", min: 0, value: c.max_hp, "aria-label": "Max HP", style: "width:7ch" });
    const editCur = h("input", { type: "number", min: 0, value: c.hp, "aria-label": "Current HP", style: "width:7ch" });
    const editTemp = h("input", { type: "number", min: 0, value: c.temp_hp, "aria-label": "Temp HP", style: "width:7ch" });
    sections.push(h("div", { class: "detail-sec" },
      h("div", { class: "hp-readout" }, h("span", { class: "cur" }, c.hp), h("span", { class: "of" }, "/ " + c.max_hp + " HP"),
        c.temp_hp ? h("span", { class: "t" }, "+" + c.temp_hp + " temp") : null,
        h("span", { class: "grow" }), h("span", { class: c.ac_bonus ? "ac-up" : "faint", style: "font-size:.85rem" },
          "AC " + c.ac + (c.ac_bonus ? " (" + c.ac_base + " " + signed(c.ac_bonus) + ")" : ""))),
      hpbar(c),
      h("div", { class: "hp-ctl", style: "margin-top:12px" }, amt,
        h("button", { type: "button", class: "btn btn-dmg", onclick: () => hp("damage") }, icon("swords", "sm"), " Damage"),
        h("button", { type: "button", class: "btn btn-heal", onclick: () => hp("heal") }, icon("heart", "sm"), " Heal"),
        h("button", { type: "button", class: "btn btn-temp", onclick: () => hp("temp"), title: S.settings.temp_hp_stacking ? "Adds to current temp HP" : "Temp HP doesn't stack: keeps the higher value" }, icon("shield-plus", "sm"), " Temp")),
      h("div", { class: "faint", style: "font-size:.82rem;margin-top:6px" }, "Enter applies damage · Shift+Enter heals. Damage uses temp HP first."),
      h("div", { class: "hp-fix", style: "margin-top:10px" }, h("span", { class: "lbl" }, "Fix HP"),
        [-5, -1, 1, 5].map((n) => h("button", { type: "button", class: "btn btn-sm", title: "Correct current HP by " + n + " (logged; Undo HP reverses it)",
          onclick: () => run("POST", "/api/combatants/" + cid + "/hp", { op: "set", hp: Math.max(0, c.max_hp ? Math.min(c.max_hp, c.hp + n) : c.hp + n) }) },
          n > 0 ? "+" + n : "−" + Math.abs(n)))),
      h("details", { style: "margin-top:8px" }, h("summary", { class: "lbl", style: "cursor:pointer" }, "Set exact HP, max HP or temp HP"),
        h("div", { class: "row", style: "margin-top:8px;align-items:center" },
          h("label", { class: "field", style: "flex:0 0 auto" }, h("span", null, "Current"), editCur),
          h("label", { class: "field", style: "flex:0 0 auto" }, h("span", null, "Max"), editMax),
          h("label", { class: "field", style: "flex:0 0 auto" }, h("span", null, "Temp"), editTemp),
          h("button", { type: "button", class: "btn btn-sm", style: "align-self:flex-end", onclick: () => {
            const body = { op: "set" };
            if (editCur.value !== String(c.hp)) body.hp = Number(editCur.value);
            if (editMax.value !== String(c.max_hp)) body.max_hp = Number(editMax.value);
            if (editTemp.value !== String(c.temp_hp)) body.temp_hp = Number(editTemp.value);
            if (Object.keys(body).length > 1) run("POST", "/api/combatants/" + cid + "/hp", body);
          } }, "Apply")))));

    sections.push(targetSection(c));

    // Death saves
    if (c.linked && (c.hp === 0 || c.death_successes || c.death_failures)) {
      const pips = (field, cls) => h("span", { class: "pips " + cls }, [0, 1, 2].map((i) => h("button", {
        type: "button", class: "pip" + (i < c[field] ? " on" : ""), "aria-label": field.replace("_", " ") + " " + (i + 1),
        onclick: () => run("PATCH", "/api/combatants/" + cid, { changes: { [field]: { from: c[field], to: c[field] === i + 1 ? i : i + 1 } } }),
      })));
      sections.push(h("div", { class: "detail-sec" }, h("div", { class: "row", style: "align-items:center" },
        h("span", { class: "lbl" }, "Death saves"), h("span", { class: "faint" }, "Successes"), pips("death_successes", ""), h("span", { class: "faint" }, "Failures"), pips("death_failures", "fail"))));
    }

    // Conditions
    const condName = h("input", { type: "text", list: "cond-names", placeholder: "Condition or effect", "aria-label": "Condition", "data-keep": "cname-" + cid });
    const rounds = h("input", { type: "number", min: 1, placeholder: "∞", "aria-label": "Duration in rounds", title: "Rounds (leave blank for no fixed duration)" });
    const tickOn = h("select", { "aria-label": "Counts down on whose turn" },
      S.combatants.map((o) => h("option", { value: o.id, selected: o.id === cid }, o.id === cid ? "Their own turn" : o.name + "'s turn")));
    const tick = h("select", { "aria-label": "Start or end of turn" }, h("option", { value: "end" }, "at end of"), h("option", { value: "start" }, "at start of"));
    const auto = h("input", { type: "checkbox" });
    const note = h("input", { type: "text", placeholder: "Note (save DC, source…)", "aria-label": "Condition note" });
    const acChange = h("input", { type: "number", min: -10, max: 30, placeholder: "AC ±", "aria-label": "AC change while it lasts", title: "Temporary AC while this lasts, like +2 for Shield of Faith or cover" });
    function addCond(name, withDuration) {
      name = (name || condName.value).trim();
      if (!name) { condName.focus(); return; }
      const body = { name, note: withDuration ? note.value : "" };
      if (withDuration && acChange.value) body.ac = Number(acChange.value);
      if (withDuration && rounds.value) Object.assign(body, { rounds: Number(rounds.value), tick: tick.value, tick_on: Number(tickOn.value), auto_expire: auto.checked });
      run("POST", "/api/combatants/" + cid + "/conditions", body);
    }
    const condItems = c.conditions.map((x) => h("div", { class: "cond" + (x.expired ? " is-expired" : "") },
      h("div", { class: "cn" }, x.name, x.ac ? h("span", { class: "tag ac-tag" + (x.expired ? " is-off" : "") }, signed(x.ac) + " AC") : null),
      h("div", { class: "ca" },
        x.rounds_left != null && !x.expired ? [
          h("button", { type: "button", class: "icon-btn sm", "aria-label": "One less round", onclick: () => run("PATCH", "/api/combatants/" + cid + "/conditions/" + x.id, { rounds_left: Math.max(0, x.rounds_left - 1) }) }, icon("minus", "sm")),
          h("button", { type: "button", class: "icon-btn sm", "aria-label": "One more round", onclick: () => run("PATCH", "/api/combatants/" + cid + "/conditions/" + x.id, { rounds_left: x.rounds_left + 1 }) }, icon("plus", "sm"))] : null,
        x.expired ? h("button", { type: "button", class: "btn btn-sm", title: "Keep it with no fixed duration", onclick: () => run("PATCH", "/api/combatants/" + cid + "/conditions/" + x.id, { rounds_left: null }) }, "Keep") : null,
        h("button", { type: "button", class: x.expired ? "btn btn-sm btn-primary" : "icon-btn sm", "aria-label": "Remove " + x.name, title: "Remove",
          onclick: () => run("DELETE", "/api/combatants/" + cid + "/conditions/" + x.id) }, x.expired ? "Remove" : icon("x", "sm"))),
      h("div", { class: "cd" }, condDesc(x, c))));
    sections.push(h("div", { class: "detail-sec" },
      h("h3", { class: "rule-head" }, "Conditions & effects"),
      condItems.length ? h("div", { class: "cond-list" }, condItems) : h("p", { class: "faint", style: "margin:0" }, "None."),
      c.conditions.some((x) => x.name === "Disengaged" && !x.expired) ? null : h("div", { class: "row", style: "margin:8px 0 4px" },
        h("button", { type: "button", class: "btn btn-sm", title: "The Disengage action: they can move away without opportunity attacks until their turn ends",
          onclick: () => run("POST", "/api/combatants/" + cid + "/conditions", { name: "Disengaged", rounds: 1, tick: "end", tick_on: cid, auto_expire: true, note: "No opportunity attacks while moving this turn" }) },
          icon("compass", "sm"), " Disengage")),
      h("div", { class: "cond-quick", "aria-label": "Add a standard condition" },
        CONDITIONS.filter((n) => !c.conditions.some((x) => x.name === n)).map((n) => h("button", { type: "button", onclick: () => addCond(n, false) }, n))),
      h("details", { style: "margin-top:10px" }, h("summary", { class: "lbl", style: "cursor:pointer" }, "Add with duration or custom effect"),
        h("div", { class: "cond-add" }, condName, rounds, acChange, h("label", { class: "check", style: "font-size:.88rem" }, auto, "Remove automatically"),
          h("div", { class: "full row", style: "align-items:center;gap:6px;font-size:.92rem" }, h("span", { class: "faint" }, "Count down"), tick, tickOn),
          h("div", { class: "full" }, note),
          h("button", { type: "button", class: "btn btn-sm full", onclick: () => addCond(null, true) }, icon("plus", "sm"), " Add effect"),
          h("div", { class: "full faint", style: "font-size:.82rem" }, "Effects count down one per round on the chosen turn. When one runs out it's flagged for you to remove — unless “Remove automatically” is ticked. Either way it's written to the log. AC ± changes their armor class only while the effect lasts (e.g. +2 Shield of Faith, +5 Shield, +2 half cover).")))));

    // Initiative & AC
    const modIn = h("input", { type: "number", value: c.init_mod, "aria-label": "Initiative modifier", style: "width:7ch",
      onchange: (e) => run("PATCH", "/api/combatants/" + cid, { changes: { init_mod: { from: c.init_mod, to: Number(e.target.value) } } }) });
    const acIn = h("input", { type: "number", value: c.ac_base, min: 0, "aria-label": "Armor class (without temporary effects)", style: "width:7ch",
      title: c.ac_bonus ? "Base AC. Effects add " + signed(c.ac_bonus) + " for now." : "Armor class",
      onchange: (e) => run("PATCH", "/api/combatants/" + cid, { changes: { ac: { from: c.ac_base, to: Number(e.target.value) } } }) });
    const isCurrent = S.encounter.status === "active" && S.encounter.current_id === cid;
    sections.push(h("div", { class: "detail-sec row", style: "align-items:flex-end" },
      h("label", { class: "field", style: "flex:0 0 auto" }, h("span", null, "Init modifier"), modIn),
      h("label", { class: "field", style: "flex:0 0 auto" }, h("span", null, c.linked ? "AC (sheet)" : "AC"), acIn),
      S.encounter.status === "active" && !isCurrent ? h("button", { type: "button", class: "btn btn-sm", title: "Override turn order", onclick: () => run("POST", "/api/encounters/" + EID + "/set-turn", { combatant_id: cid }) }, icon("play", "sm"), " Make it their turn") : null,
      h("label", { class: "check", style: "font-size:.9rem", title: "Hidden combatants and their map tokens are never sent to players" },
        h("input", { type: "checkbox", checked: c.hidden, onchange: (e) => run("PATCH", "/api/combatants/" + cid, { changes: { hidden: { from: c.hidden, to: e.target.checked } } }) }),
        "Hidden from players"),
      h("span", { class: "grow" }), removeBtn));

    // Rolls: results only. Nothing here changes HP; initiative is set only by its own button.
    sections.push(rollSection(c));

    // Stat block (enemies)
    if (c.kind === "enemy") sections.push(statblock(c));

    box.replaceChildren(...sections, h("datalist", { id: "cond-names" }, CONDITIONS.map((n) => h("option", { value: n }))));
  }
  const ABIL = [["str", "Strength"], ["dex", "Dexterity"], ["con", "Constitution"], ["int", "Intelligence"], ["wis", "Wisdom"], ["cha", "Charisma"]];
  function attackLines(text) {
    return String(text || "").split(/\n+/).map((line) => {
      const name = (line.match(/^\s*([^.:]{1,40})[.:]/) || [])[1];
      const hit = line.match(/([+-]\s*\d+)\s*to hit/i);
      const dmg = line.match(/(\d+d\d+(?:\s*[+-]\s*\d+)?)/i);
      return name && (hit || dmg) ? { name: name.trim(), hit: hit ? hit[1].replace(/\s/g, "") : null, dmg: dmg ? dmg[1].replace(/\s/g, "") : null } : null;
    }).filter(Boolean);
  }
  function rollSection(c) {
    const roll = (req, e) => Dice.roll(Object.assign({ encounter_id: EID }, req), e);
    const btns = [];
    btns.push(h("button", { type: "button", class: "btn btn-sm", title: "Roll d20 + initiative modifier and put it in the turn order",
      onclick: (e) => roll({ check: { type: "initiative", combatant_id: c.id }, apply_initiative: true }, e).then((r) => { if (r) refresh(true); }) },
      icon("dice-5", "sm"), " Roll & set initiative"));
    const saves = h("div", { class: "roll-grid", style: "margin-top:8px" }, ABIL.map(([k, label]) => h("button", { type: "button",
      onclick: (e) => roll({ check: { type: "save", key: k, combatant_id: c.id } }, e) },
      h("span", null, label + " save"), h("b", null, c.linked ? "" : signed(Math.floor((((c.statblock.abilities || {})[k] ?? 10) - 10) / 2))))));
    return h("div", { class: "detail-sec" },
      h("h3", { class: "rule-head" }, "Rolls", h("span", { class: "count" }, "shift = advantage · ctrl = disadvantage")),
      h("div", { class: "roll-row" }, btns),
      saves,
      c.linked ? h("div", { class: "faint", style: "font-size:.82rem;margin-top:6px" }, "Uses the character sheet's saves.") : null);
  }

  // ---- hit a target: the selected combatant attacks (or heals), the DM picks who it lands on ----
  const targetsOf = new Map(); // "attacker:mode" -> Set of target ids (kept while the page is open)
  const amountOf = new Map();  // attacker id -> amount typed or rolled, so a re-render doesn't lose it
  const lastAttack = new Map(); // attacker id -> { label, total, natural }
  const modeOf = new Map();    // attacker id -> "damage" | "heal"
  let casting = null;           // { by: caster id, spell, amount (healing), done: Set of target ids }
  const isFoe = (a, b) => (a.kind === "enemy") !== (b.kind === "enemy");
  const modeFor = (c) => modeOf.get(c.id) || "damage";
  function chosenTargets(attacker, mode) {
    mode = mode || modeFor(attacker);
    const key = attacker.id + ":" + mode;
    if (!targetsOf.has(key)) {
      // Start with the obvious choice: the only opponent still standing. Healing starts empty.
      const foes = S.combatants.filter((x) => x.id !== attacker.id && isFoe(attacker, x) && !OUT.has(x.status));
      targetsOf.set(key, new Set(mode === "damage" && foes.length === 1 ? [foes[0].id] : []));
    }
    const set = targetsOf.get(key);
    [...set].forEach((id) => { if (!byId(id)) set.delete(id); });
    return set;
  }
  function attacksFor(c) {
    const roll = (req, e) => Dice.roll(Object.assign({ encounter_id: EID }, req), e);
    if (c.linked) return (c.attacks || []).map((a, i) => ({ name: a.name, heal: !!a.heal,
      hit: a.has_hit && !a.heal ? (e) => roll({ check: { type: "attack", key: i, combatant_id: c.id } }, e) : null, hitLabel: "Hit",
      dmg: a.has_dmg ? (e, crit) => roll({ check: { type: "damage", key: i, combatant_id: c.id }, crit }, e) : null, dmgLabel: a.heal ? "Heal" : "Dmg" }));
    if (c.kind !== "enemy") return [];
    return attackLines(c.statblock.attacks).map((a) => ({ name: a.name,
      hit: a.hit ? (e) => roll({ expression: "1d20" + a.hit, label: a.name + " attack", kind: "attack", subject: c.name }, e) : null, hitLabel: "Hit " + a.hit,
      dmg: a.dmg ? (e, crit) => roll({ expression: a.dmg, label: a.name + " damage", kind: "damage", subject: c.name, crit }, e) : null, dmgLabel: "Dmg " + a.dmg }));
  }
  function castSection(c) {
    const s = casting.spell, healing = s.effect === "heal";
    const people = S.combatants.filter((x) => x.id === c.id || !OUT.has(x.status))
      .map((x) => ({ id: x.id, name: x.id === c.id ? x.name + " (self)" : x.name, ally: !isFoe(c, x), done: casting.done.has(x.id),
        info: healing ? x.hp + "/" + x.max_hp + " HP" : "AC " + x.ac }));
    const end = () => { casting = null; renderDetail(); };
    const onPick = (p) => {
      const target = byId(p.id), label = s.condition || s.name;
      if (!target) return;
      casting.done.add(p.id);
      if (healing && casting.amount != null) {
        run("POST", "/api/encounters/" + EID + "/damage", { targets: [p.id], amount: casting.amount, op: "heal", attacker_id: c.id },
          () => toast(s.name + ": healed " + target.name + " for " + casting.amount + ".", "ok",
            { action: { label: "Undo", run: () => run("POST", "/api/encounters/" + EID + "/undo", {}) } }));
      }
      if (s.condition || s.ac) {
        run("POST", "/api/encounters/" + EID + "/conditions", { targets: [p.id], name: label, rounds: s.rounds, ac: s.ac || null, caster_id: c.id, note: s.condition ? s.name : "" },
          () => { if (!healing) toast(label + (s.ac ? " (" + signed(s.ac) + " AC)" : "") + " on " + target.name + ".", "ok"); });
      }
      renderDetail();
    };
    return h("div", { class: "detail-sec hit-box" + (healing ? " is-heal" : "") },
      h("h3", { class: "rule-head" }, "Cast a spell", h("span", { class: "count" }, c.name + " casts")),
      L.castPicker({ spell: s, amount: casting.amount, people, onPick, onDone: end }));
  }
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && casting) { casting = null; renderDetail(); } });

  function targetSection(c) {
    if (casting && casting.by === c.id) return castSection(c);
    if (casting) casting = null; // picked someone else: drop the half-cast spell
    const mode = modeFor(c), healing = mode === "heal";
    const set = chosenTargets(c, mode);
    const setMode = (m) => { if (m !== mode) { modeOf.set(c.id, m); renderDetail(); } };
    // Healing lists allies first; damage lists opponents first.
    const others = S.combatants.filter((x) => (healing || x.id !== c.id) && (healing || !OUT.has(x.status) || set.has(x.id)))
      .sort((a, b) => healing ? (isFoe(c, a) - isFoe(c, b)) : (isFoe(c, b) - isFoe(c, a)));
    const amt = h("input", { type: "number", min: 0, placeholder: "0", "aria-label": healing ? "Healing amount" : "Damage to deal", "data-keep": "hit-amt-" + c.id, inputmode: "numeric",
      value: amountOf.get(c.id) ?? "", oninput: (e) => amountOf.set(c.id, e.target.value),
      onkeydown: (e) => { if (e.key === "Enter") { e.preventDefault(); deal(!healing && e.shiftKey); } } });
    function deal(half) {
      const n = Number(amt.value);
      if (!set.size) { toast(healing ? "Pick who gets healed first." : "Pick who gets hit first.", "error"); return; }
      if (amt.value === "" || !Number.isFinite(n) || n < 0) { amt.focus(); return; }
      const names = [...set].map((id) => byId(id).name).join(", ");
      const dealt = half ? Math.floor(Math.trunc(n) / 2) : Math.trunc(n);
      run("POST", "/api/encounters/" + EID + "/damage", { targets: [...set], amount: Math.trunc(n), op: mode, half: !!half, attacker_id: c.id }, () => {
        toast(healing ? "Healed " + names + " for " + dealt + "." : dealt + " damage to " + names + ".", "ok",
          { action: { label: "Undo", run: () => run("POST", "/api/encounters/" + EID + "/undo", {}) } });
      });
      amountOf.delete(c.id);
    }
    const toggle = (id) => { set.has(id) ? set.delete(id) : set.add(id); renderDetail(); };
    const chips = others.length ? others.map((x) => h("button", { type: "button", class: "target-chip" + (set.has(x.id) ? " is-on" : "") + (isFoe(c, x) ? " is-foe" : "") + (healing ? " is-heal" : ""),
      "aria-pressed": set.has(x.id) ? "true" : "false", onclick: () => toggle(x.id), title: set.has(x.id) ? "Click to un-pick" : "Click to pick" },
      set.has(x.id) ? icon("check", "sm") : null, h("b", null, x.id === c.id ? x.name + " (self)" : x.name),
      h("span", { class: "num" }, x.hp + "/" + x.max_hp + (healing ? " HP · AC " + x.ac : " · AC " + x.ac))))
      : [h("span", { class: "faint" }, "No one else is in this fight yet.")];

    const atks = window.Dice ? attacksFor(c) : [];
    const after = (what) => (r) => { // a damage or healing roll fills in the amount; an attack roll is checked against AC
      if (!r) return;
      if (what === "heal") { modeOf.set(c.id, "heal"); amountOf.set(c.id, String(r.total)); }
      else if (what === "dmg") { modeOf.set(c.id, "damage"); amountOf.set(c.id, String(r.total)); }
      else { modeOf.set(c.id, "damage"); lastAttack.set(c.id, { label: r.label, total: r.total, natural: r.result && r.result.natural }); }
      renderDetail();
    };
    const atkRows = atks.length ? h("div", { class: "hit-attacks" }, atks.map((a) => h("div", { class: "roll-row", style: "align-items:center" },
      h("b", { style: "min-width:7ch" }, a.name),
      a.hit ? h("button", { type: "button", class: "btn btn-sm", onclick: (e) => a.hit(e).then(after("hit")) }, a.hitLabel) : null,
      a.dmg ? h("button", { type: "button", class: "btn btn-sm" + (a.heal ? " btn-heal" : ""), onclick: (e) => a.dmg(e, false).then(after(a.heal ? "heal" : "dmg")) },
        a.heal ? [icon("heart", "sm"), " " + a.dmgLabel] : a.dmgLabel) : null,
      a.dmg && !a.heal ? h("button", { type: "button", class: "btn btn-sm btn-quiet", title: "Critical: double the dice", onclick: (e) => a.dmg(e, true).then(after("dmg")) }, "Crit") : null))) : null;

    // Spells from the character sheet that do something.
    const sc = c.spellcasting;
    // Click the spell, then click who it's on (see castSection).
    const cast = (s, amount) => { casting = { by: c.id, spell: s, amount: amount ?? null, done: new Set() }; renderDetail(); };
    const spellRows = window.Dice && (c.spells || []).length ? h("div", { class: "hit-attacks hit-spells" },
      h("div", { class: "lbl" }, "Spells", sc ? h("span", { class: "faint", style: "text-transform:none;letter-spacing:0" }, " · save DC " + sc.dc + " · attack " + signed(sc.attack)) : null),
      c.spells.map((s) => {
        const rollSpell = (e, crit) => Dice.roll({ check: { type: "spell", key: s.index, combatant_id: c.id }, crit, encounter_id: EID }, e);
        const saveTag = s.hit && s.hit !== "attack" ? h("span", { class: "tag" }, s.hit.toUpperCase() + " save" + (sc ? " DC " + sc.dc : "")) : null;
        return h("div", { class: "roll-row", style: "align-items:center" },
          h("b", { style: "min-width:7ch" }, s.name),
          s.effect === "damage" && s.hit === "attack" ? h("button", { type: "button", class: "btn btn-sm", onclick: (e) =>
            Dice.roll({ check: { type: "spell_attack", combatant_id: c.id }, label: s.name + " attack", encounter_id: EID }, e).then(after("hit")) }, "Attack" + (sc ? " " + signed(sc.attack) : "")) : null,
          s.effect === "damage" && s.dice ? h("button", { type: "button", class: "btn btn-sm", onclick: (e) => rollSpell(e, false).then(after("dmg")) }, "Dmg " + s.dice) : null,
          s.effect === "damage" && s.dice && s.hit === "attack" ? h("button", { type: "button", class: "btn btn-sm btn-quiet", onclick: (e) => rollSpell(e, true).then(after("dmg")) }, "Crit") : null,
          s.effect === "heal" && s.dice ? h("button", { type: "button", class: "btn btn-sm btn-heal", title: "Roll the healing, then tap who gets it",
            onclick: (e) => rollSpell(e, false).then((r) => { if (r) cast(s, Math.max(0, r.total)); }) }, icon("heart", "sm"), " Cast · heal " + s.dice) : null,
          saveTag,
          (s.condition || s.ac) && s.effect !== "heal" ? h("button", { type: "button", class: "btn btn-sm" + (L.spellHelps(s) ? " btn-heal" : ""), title: "Then tap who it's on", onclick: () => cast(s) },
            icon(L.spellHelps(s) ? "shield-plus" : "zap", "sm"), " Cast · " + L.spellWhat(s)) : null);
      })) : null;

    const la = lastAttack.get(c.id);
    const verdict = !healing && la && set.size ? h("div", { class: "hit-verdict" }, la.label + ": ", h("b", null, la.total), " — ",
      [...set].map((id) => { const t = byId(id); const hits = la.natural === 20 || (la.natural !== 1 && la.total >= t.ac);
        return h("span", { class: hits ? "hits" : "misses" }, t.name + (la.natural === 20 ? " crit!" : hits ? " hit" : " missed") + " (AC " + t.ac + ")"); })
        .flatMap((x, i) => i ? [", ", x] : [x])) : null;

    const seg = h("div", { class: "seg hit-mode", role: "group", "aria-label": "Damage or heal" },
      h("button", { type: "button", class: healing ? "" : "is-on", "aria-pressed": String(!healing), onclick: () => setMode("damage") }, icon("swords", "sm"), " Damage"),
      h("button", { type: "button", class: healing ? "is-on" : "", "aria-pressed": String(healing), onclick: () => setMode("heal") }, icon("heart", "sm"), " Heal / buff"));
    const label = set.size > 1 ? (healing ? " Heal all " : " Damage all ") + set.size : (healing ? " Heal" : " Deal damage");
    return h("div", { class: "detail-sec hit-box" + (healing ? " is-heal" : "") },
      h("h3", { class: "rule-head" }, healing ? "Heal or help someone" : "Hit a target", h("span", { class: "count" }, c.name + (healing ? " helps" : " attacks"))),
      h("div", { class: "row", style: "align-items:center;margin-bottom:8px" }, seg),
      h("div", { class: "target-chips" }, chips),
      atkRows, spellRows, verdict,
      h("div", { class: "hp-ctl", style: "margin-top:10px" }, amt,
        h("button", { type: "button", class: "btn " + (healing ? "btn-heal" : "btn-dmg"), disabled: !set.size, onclick: () => deal(false) },
          icon(healing ? "heart" : "swords", "sm"), label),
        healing ? null : h("button", { type: "button", class: "btn", disabled: !set.size, title: "Half damage, rounded down — for targets that made their save (Shift+Enter)", onclick: () => deal(true) }, "Half (saved)")),
      h("div", { class: "faint", style: "font-size:.82rem;margin-top:6px" },
        healing ? (set.size ? "Roll healing above or type it, then heal. HP won't go over max." : "Click who " + c.name + " is healing or helping.")
          : set.size ? "Roll damage above or type it, then deal it. Pick more than one target for area spells." : "Click who " + c.name + " is attacking."));
  }
  // Damage rolls in the dice history can be applied — but only when the DM clicks.
  const applied = new Map(); // roll id -> what was applied, so one roll can't be applied twice by accident
  if (window.Dice) {
    Dice.actions = (r) => {
      if (r.kind === "heal") return healAction(r);
      if (r.kind !== "damage") return null;
      if (applied.has(r.id)) return h("div", { class: "dh-actions faint" }, "Applied " + applied.get(r.id));
      const sel = byId(selected);
      if (!sel) return h("div", { class: "dh-actions faint" }, "Select a combatant to apply this damage");
      const chosen = [...chosenTargets(sel, "damage")].map(byId).filter(Boolean);
      const targets = chosen.length ? chosen : [sel];
      const names = targets.map((t) => t.name).join(", ");
      const apply = (half) => {
        applied.set(r.id, (half ? Math.floor(r.total / 2) : r.total) + " to " + names);
        Dice.renderHistory();
        run("POST", "/api/encounters/" + EID + "/damage", { targets: targets.map((t) => t.id), amount: r.total, half, attacker_id: chosen.length ? sel.id : null });
      };
      return h("div", { class: "dh-actions" },
        h("button", { type: "button", class: "btn btn-sm btn-dmg", onclick: () => apply(false) }, "Apply " + r.total + " to " + names),
        h("button", { type: "button", class: "btn btn-sm", title: "Half damage, rounded down (successful save)", onclick: () => apply(true) }, "Half (" + Math.floor(r.total / 2) + ")"));
    };
  }

  // Healing rolls go to whoever the healer picked (or the selected combatant).
  function healAction(r) {
    if (applied.has(r.id)) return h("div", { class: "dh-actions faint" }, "Healed " + applied.get(r.id));
    const sel = byId(selected);
    if (!sel) return h("div", { class: "dh-actions faint" }, "Select a combatant to apply this healing");
    const chosen = [...chosenTargets(sel, "heal")].map(byId).filter(Boolean);
    const targets = chosen.length ? chosen : [sel];
    const names = targets.map((t) => t.name).join(", ");
    return h("div", { class: "dh-actions" },
      h("button", { type: "button", class: "btn btn-sm btn-heal", onclick: () => {
        applied.set(r.id, names + " for " + r.total);
        Dice.renderHistory();
        run("POST", "/api/encounters/" + EID + "/damage", { targets: targets.map((t) => t.id), amount: r.total, op: "heal", attacker_id: chosen.length ? sel.id : null });
      } }, "Heal " + names + " for " + r.total));
  }

  function condDesc(x, c) {
    const parts = [];
    if (x.expired) parts.push("Duration has run out — remove it or keep it?");
    else if (x.rounds_left != null) {
      const who = x.tick_on === c.id ? "their" : ((byId(x.tick_on) || {}).name || "another combatant") + "'s";
      parts.push(x.rounds_left + " round" + (x.rounds_left === 1 ? "" : "s") + " left · counts at " + x.tick + " of " + who + " turn" + (x.auto_expire ? " · auto-removes" : ""));
    } else parts.push("No fixed duration");
    if (x.note) parts.push(x.note);
    return parts.join(" · ");
  }
  function statblock(c) {
    const s = c.statblock || {};
    const ab = s.abilities || {};
    const line = (label, v) => v ? h("div", null, h("b", null, label + " "), v) : null;
    const hasAbil = Object.keys(ab).length;
    return h("div", { class: "detail-sec statblock" },
      h("h3", { class: "rule-head" }, "Stat block", c.creature_id ? h("span", { class: "count" }, "copied when added") : null),
      h("div", { class: "faint", style: "font-style:italic" }, [s.creature_type, s.cr ? "CR " + s.cr : ""].filter(Boolean).join(" · ") || "Quick-added enemy"),
      line("Speed", s.speed),
      hasAbil ? [h("hr", { class: "sb-rule" }), h("div", { class: "sb-abil" }, ["str", "dex", "con", "int", "wis", "cha"].map((a) =>
        h("div", null, h("b", null, { str: "Strength", dex: "Dexterity", con: "Constitution", int: "Intelligence", wis: "Wisdom", cha: "Charisma" }[a]), (ab[a] ?? 10) + " (" + signed(Math.floor(((ab[a] ?? 10) - 10) / 2)) + ")"))), h("hr", { class: "sb-rule" })] : null,
      line("Resistances", s.resistances), line("Immunities", s.immunities), line("Vulnerabilities", s.vulnerabilities),
      line("Condition immunities", s.condition_immunities), line("Senses", s.senses), line("Languages", s.languages),
      s.traits ? h("div", { style: "margin-top:8px" }, h("div", { class: "lbl" }, "Traits"), h("div", { class: "pre" }, s.traits)) : null,
      s.attacks ? h("div", { style: "margin-top:8px" }, h("div", { class: "lbl" }, "Actions"), h("div", { class: "pre" }, s.attacks)) : null,
      s.notes ? h("div", { style: "margin-top:8px" }, h("div", { class: "lbl" }, "Creature notes"), h("div", { class: "pre note-box" }, s.notes)) : null);
  }

  // ---- log ----------------------------------------------------------------------
  let lastLogLen = 0;
  function renderLog() {
    const box = $("#log-items");
    const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
    box.replaceChildren(...S.log.map((l) => h("div", { class: "log-item k-" + l.kind },
      h("span", { class: "r" }, l.round ? "R" + l.round : ""),
      h("div", null, h("span", { class: "m" }, l.message), h("time", { datetime: l.created_at }, fmtTime(l.created_at) + (l.turn_name && l.kind !== "turn" ? " · " + l.turn_name + "'s turn" : ""))))));
    $("#log-count").textContent = S.log_total > S.log.length ? "latest " + S.log.length + " of " + S.log_total : S.log_total + " entries";
    if (atBottom || S.log.length !== lastLogLen) box.scrollTop = box.scrollHeight;
    lastLogLen = S.log.length;
  }
  $("#log-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const m = e.target.message.value.trim();
    if (!m) return;
    run("POST", "/api/encounters/" + EID + "/log", { message: m });
    e.target.message.value = "";
  });

  // ---- adding combatants -----------------------------------------------------------
  $$("[data-addtab]").forEach((t) => t.addEventListener("click", () => {
    $$("[data-addtab]").forEach((x) => x.classList.toggle("is-on", x === t));
    $$("[data-addpane]").forEach((p) => { p.hidden = p.dataset.addpane !== t.dataset.addtab; });
  }));
  $("#quick-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const f = e.target;
    const quick = { name: f.name.value.trim(), max_hp: Number(f.max_hp.value), ac: f.ac.value === "" ? 10 : Number(f.ac.value),
      init_mod: f.init_mod.value === "" ? 0 : Number(f.init_mod.value), count: Number(f.count.value) || 1, save_to_library: f.save_to_library.checked };
    run("POST", "/api/encounters/" + EID + "/combatants", { quick }, async () => {
      f.reset(); f.name.focus();
      if (quick.save_to_library) { // show the new stat block in the "From library" tab right away
        try { creatures = (await api("GET", "/api/creatures?campaign_id=" + S.encounter.campaign_id)).creatures; renderAdd(); } catch (e) { /* shows after reload */ }
      }
    });
  });
  $("#lib-search").addEventListener("input", renderAdd);
  function renderAdd() {
    const q = $("#lib-search").value.trim().toLowerCase();
    const list = creatures.filter((c) => !q || c.name.toLowerCase().includes(q) || (c.creature_type || "").toLowerCase().includes(q));
    $("#lib-list").replaceChildren(...(list.length ? list.slice(0, 80).map((cr) => {
      const n = h("input", { type: "number", min: 1, max: 50, value: 1, "aria-label": "How many " + cr.name, style: "width:6ch" });
      return h("li", null, h("div", { class: "grow" }, h("b", null, cr.name), h("div", { class: "faint", style: "font-size:.85rem" },
        [cr.creature_type, cr.cr ? "CR " + cr.cr : "", cr.max_hp + " HP", "AC " + cr.ac, "init " + signed(cr.initiative_mod)].filter(Boolean).join(" · "))),
        n, h("button", { type: "button", class: "btn btn-sm", onclick: () => run("POST", "/api/encounters/" + EID + "/combatants", { creature_id: cr.id, count: Number(n.value) || 1 }) }, "Add"));
    }) : [h("li", { class: "faint" }, creatures.length ? "No match." : "The library is empty. Tick “Also save to the creature library” when quick-adding, or build stat blocks on the Creatures page.")]));
    const inEnc = new Set(S.combatants.filter((c) => c.character_id).map((c) => c.character_id));
    const avail = chars.filter((c) => !inEnc.has(c.id));
    const pcs = avail.filter((c) => c.kind === "pc");
    $("#party-list").replaceChildren(
      ...(pcs.length > 1 ? [h("li", null, h("span", { class: "grow faint" }, pcs.length + " player characters not in this fight"),
        h("button", { type: "button", class: "btn btn-sm", onclick: () => run("POST", "/api/encounters/" + EID + "/combatants", { characters: pcs.map((c) => c.id) }) }, "Add all"))] : []),
      ...(avail.length ? avail.map((c) => h("li", null, h("div", { class: "grow" }, h("b", null, c.name), h("div", { class: "faint", style: "font-size:.85rem" },
        (c.kind === "pc" ? "PC" : "NPC") + " · " + c.current_hp + "/" + c.max_hp + " HP · AC " + c.ac)),
        h("button", { type: "button", class: "btn btn-sm", onclick: () => run("POST", "/api/encounters/" + EID + "/combatants", { characters: [c.id] }) }, "Add"))) :
        [h("li", { class: "faint" }, "Every character in this campaign is already here.")]));
  }

  // ---- stay in sync (other tabs, character sheet edits) -----------------------------
  async function refresh(force) {
    if (!force && (Save.busy() || document.hidden)) return;
    try {
      if (!force) {
        const r = await api("GET", "/api/encounters/" + EID + "/rev");
        if (r.rev === S.encounter.rev) return;
      }
      apply(await api("GET", "/api/encounters/" + EID));
    } catch (e) { /* offline: the indicator shows it when a save fails */ }
  }
  setInterval(refresh, 3000);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(); });

  apply(S);
})();
