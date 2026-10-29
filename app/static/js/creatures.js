(function () {
  "use strict";
  const { h, icon, $, boot, Binder, act, armed, signed, api, toast } = L;
  let list = boot("boot");
  let current = null;
  try { current = Number(localStorage.getItem("creature-sel")) || null; } catch (e) { /* ignore */ }
  if (!list.some((c) => c.id === current)) current = list[0] ? list[0].id : null;
  const ABS = ["str", "dex", "con", "int", "wis", "cha"];
  const NAMES = { str: "Strength", dex: "Dexterity", con: "Constitution", int: "Intelligence", wis: "Wisdom", cha: "Charisma" };

  function renderList() {
    const q = $("#q").value.trim().toLowerCase();
    const shown = list.filter((c) => !q || c.name.toLowerCase().includes(q) || (c.creature_type || "").toLowerCase().includes(q))
      .sort((a, b) => a.name.localeCompare(b.name));
    $("#list").replaceChildren(...(shown.length ? shown.map((c) => h("li", null, h("button", { type: "button", class: c.id === current ? "is-on" : "", onclick: () => open(c.id) },
      h("span", { class: "t" }, c.name),
      h("span", { class: "m" }, [c.creature_type, c.cr ? "CR " + c.cr : "", c.max_hp + " HP", "AC " + c.ac].filter(Boolean).join(" · "))))) :
      [h("li", { class: "faint", style: "padding:14px" }, list.length ? "No match." : "No creatures yet. Create one, or tick “save to library” when quick-adding an enemy in combat.")]));
  }
  $("#q").addEventListener("input", renderList);
  $("#new").addEventListener("click", () => act("POST", "/api/creatures", { name: "New creature", max_hp: 10, ac: 12 }, (d) => {
    list.push(d.creature); open(d.creature.id);
    const n = $("#editor .sb-name"); if (n) { n.focus(); n.select(); }
  }));

  function open(id) {
    Binder.flushAll();
    current = id;
    try { localStorage.setItem("creature-sel", id); } catch (e) { /* ignore */ }
    renderList();
    renderEditor(list.find((c) => c.id === id));
  }
  function renderEditor(c) {
    const box = $("#editor");
    if (!c) { box.replaceChildren(h("div", { class: "empty" }, h("h3", null, "No creature selected"), "Pick one from the list or create a new stat block.")); return; }
    const model = {};
    ["name", "creature_type", "cr", "max_hp", "ac", "initiative_mod", "speed", "abilities", "attacks", "spells", "traits", "resistances", "immunities",
      "vulnerabilities", "condition_immunities", "senses", "languages", "notes"].forEach((k) => { model[k] = c[k]; });
    const b = new Binder({ url: "/api/creatures/" + c.id, model, onSaved: (rec) => {
      const i = list.findIndex((x) => x.id === rec.id); if (i >= 0) list[i] = rec; renderList();
    } });
    const inp = (field, attrs) => b.bind(attrs && attrs.wrap ? L.wrapText(Object.assign({}, attrs, { wrap: null }))
      : h(attrs && attrs.rows ? "textarea" : "input", Object.assign({ type: attrs && attrs.type ? attrs.type : "text" }, attrs || {})), field, { int: attrs && attrs.type === "number" });
    const prop = (label, field, attrs) => h("label", { class: "field" }, h("span", null, label), inp(field, attrs));
    const modOut = {};
    const abil = ABS.map((a) => {
      const m = h("div", { class: "m" });
      modOut[a] = m;
      const el = h("input", { type: "number", min: 1, max: 30, value: (model.abilities || {})[a] ?? 10, "aria-label": NAMES[a] });
      el.addEventListener("input", () => {
        const ab = Object.assign({}, b.model.abilities || {});
        ab[a] = Number(el.value) || 10;
        b.set("abilities", ab); mods();
      });
      return h("label", { class: "field" }, h("span", { class: "lbl" }, NAMES[a]), el, m);
    });
    function mods() { ABS.forEach((a) => { modOut[a].textContent = signed(Math.floor((((b.model.abilities || {})[a] ?? 10) - 10) / 2)); }); }
    const del = h("button", { type: "button", class: "btn btn-sm btn-quiet btn-danger" }, icon("trash-2", "sm"), " Delete from library");
    // Put this creature straight into an encounter (stats are copied, as in combat).
    const encs = boot("boot-encounters");
    const encSel = h("select", { "aria-label": "Encounter", style: "width:auto;min-width:0;flex:1 1 160px" },
      encs.length ? encs.map((e) => h("option", { value: e.id }, e.name + (e.status === "active" ? " (running)" : ""))) : h("option", { value: "" }, "No open encounters"));
    const count = h("input", { type: "number", min: 1, max: 50, value: 1, "aria-label": "How many", style: "width:64px" });
    const addBtn = h("button", { type: "button", class: "btn btn-sm btn-primary", disabled: !encs.length, onclick: () => {
      const n = Math.max(1, Math.min(50, Number(count.value) || 1));
      act("POST", "/api/encounters/" + encSel.value + "/combatants", { creature_id: c.id, count: n }, () => {
        toast(`Added ${n} × ${b.model.name} to ${encSel.options[encSel.selectedIndex].text}.`, "ok", {
          action: { label: "Open encounter", run: () => { location.href = "/combat/" + encSel.value; } } });
      });
    } }, icon("swords", "sm"), " Add to encounter");
    const toEncounter = h("div", { class: "row to-encounter", style: "align-items:center;margin-top:12px" },
      h("span", { class: "lbl" }, "Use in a fight"), encSel, count, addBtn,
      encs.length ? null : h("a", { href: "/combat#new", style: "font-size:.9rem" }, "Create an encounter"));
    armed(del, () => act("DELETE", "/api/creatures/" + c.id, {}, () => { list = list.filter((x) => x.id !== c.id); open(list[0] ? list[0].id : null); }), "Delete? Existing enemies stay as they are");
    box.replaceChildren(h("div", { class: "sb-edit" },
      inp("name", { class: "input sb-name", "aria-label": "Name", maxlength: 200, wrap: true }),
      inp("creature_type", { class: "input sb-type", placeholder: "Medium humanoid (goblinoid), neutral evil", "aria-label": "Type" }),
      h("hr"),
      h("div", { class: "sb-props" },
        prop("Hit points", "max_hp", { type: "number", min: 1 }),
        prop("Armor class", "ac", { type: "number", min: 0 }),
        prop("Initiative mod", "initiative_mod", { type: "number" }),
        prop("Challenge", "cr", { placeholder: "1/4" }),
        h("div", { style: "grid-column:1/-1" }, prop("Speed", "speed", { placeholder: "30 ft., climb 20 ft." }))),
      h("hr"),
      h("div", { class: "sb-abils" }, abil),
      h("hr"),
      h("div", { class: "sb-texts" },
        prop("Damage resistances", "resistances"), prop("Damage immunities", "immunities"),
        prop("Vulnerabilities", "vulnerabilities"), prop("Condition immunities", "condition_immunities"),
        prop("Senses", "senses", { placeholder: "darkvision 60 ft., passive Perception 9" }), prop("Languages", "languages"),
        h("div", { class: "full" }, prop("Traits & special abilities", "traits", { rows: 4, class: "prose" })),
        h("div", { class: "full field" }, h("span", null, "Actions & attacks"),
          L.attackRows({ text: model.attacks || "", kind: "attacks", onChange: (t) => b.set("attacks", t) })),
        h("div", { class: "full field" }, h("span", null, "Spells"),
          L.attackRows({ text: model.spells || "", kind: "spells", onChange: (t) => b.set("spells", t) })),
        h("div", { class: "full" }, prop("DM notes", "notes", { rows: 3 })))),
      toEncounter,
      h("div", { class: "row", style: "margin-top:12px;justify-content:flex-end" }, del));
    mods();
  }
  // ---- Monster Book ----------------------------------------------------------------
  let book = null;
  const crNum = (cr) => (String(cr).includes("/") ? Number(cr.split("/")[0]) / Number(cr.split("/")[1]) : Number(cr));
  function shownBook() {
    const q = $("#book-q").value.trim().toLowerCase();
    const [lo, hi] = ($("#book-cr").value || "-1-99").split(/(?<=\d)-/).map(Number);
    return book.filter((m) => (!q || m.name.toLowerCase().includes(q) || m.creature_type.toLowerCase().includes(q))
      && (!$("#book-cr").value || (crNum(m.cr) >= lo && crNum(m.cr) <= hi)));
  }
  function renderBook() {
    const items = shownBook();
    $("#book-count").textContent = items.length + " shown · " + book.filter((m) => m.in_library).length + " of " + book.length + " in your library";
    $("#book-list").replaceChildren(...(items.length ? items.map((m) => h("li", { class: m.in_library ? "is-added" : "" },
      h("span", { class: "book-cr num", title: "Challenge rating" }, "CR " + m.cr),
      h("span", { class: "book-name" }, h("b", null, m.name), h("span", { class: "faint" }, m.creature_type)),
      h("span", { class: "book-stats num faint" }, m.max_hp + " HP · AC " + m.ac),
      m.in_library
        ? h("span", { class: "book-done" }, icon("check", "sm"), " In library")
        : h("button", { type: "button", class: "btn btn-sm", onclick: () => addFromBook([m.name]) }, icon("plus", "sm"), " Add"))) :
      [h("li", { class: "faint" }, "No monsters match.")]));
  }
  function addFromBook(names) {
    act("POST", "/api/monster-book/add", { names, campaign_id: window.CAMPAIGN_ID }, (d) => {
      list = d.creatures;
      book.forEach((m) => { if (d.added.includes(m.name) || d.skipped.includes(m.name)) m.in_library = true; });
      renderBook(); renderList();
      if (d.added.length) {
        const first = list.find((c) => c.name === d.added[0]);
        if (first && names.length === 1) open(first.id);
        toast(d.added.length === 1 ? d.added[0] + " added to your library." : d.added.length + " monsters added to your library.", "ok");
      } else toast("Already in your library.", null);
    });
  }
  async function loadBook() {
    try {
      const d = await api("GET", "/api/monster-book" + (window.CAMPAIGN_ID ? "?campaign_id=" + window.CAMPAIGN_ID : ""));
      book = d.monsters; $("#book-credit").textContent = d.attribution; renderBook();
    } catch (e) { $("#book-list").replaceChildren(h("li", { class: "faint" }, e.message)); }
  }
  $("#book-toggle").addEventListener("click", () => {
    const panel = $("#book"), open_ = panel.hidden;
    panel.hidden = !open_;
    $("#book-toggle").setAttribute("aria-expanded", open_);
    if (open_ && !book) loadBook();
    if (open_) $("#book-q").focus();
  });
  $("#book-q").addEventListener("input", () => book && renderBook());
  $("#book-cr").addEventListener("change", () => book && renderBook());
  $("#book-add-all").addEventListener("click", () => {
    const names = book ? shownBook().filter((m) => !m.in_library).map((m) => m.name) : [];
    if (!names.length) { toast("Everything shown is already in your library.", null); return; }
    addFromBook(names);
  });
  // An empty library opens the Monster Book straight away.
  if (!list.length) $("#book-toggle").click();

  renderList();
  open(current);
})();
