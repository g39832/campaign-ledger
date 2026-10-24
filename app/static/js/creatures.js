(function () {
  "use strict";
  const { h, icon, $, boot, Binder, act, armed, signed } = L;
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
    ["name", "creature_type", "cr", "max_hp", "ac", "initiative_mod", "speed", "abilities", "attacks", "traits", "resistances", "immunities",
      "vulnerabilities", "condition_immunities", "senses", "languages", "notes"].forEach((k) => { model[k] = c[k]; });
    const b = new Binder({ url: "/api/creatures/" + c.id, model, onSaved: (rec) => {
      const i = list.findIndex((x) => x.id === rec.id); if (i >= 0) list[i] = rec; renderList();
    } });
    const inp = (field, attrs) => b.bind(h(attrs && attrs.rows ? "textarea" : "input", Object.assign({ type: attrs && attrs.type ? attrs.type : "text" }, attrs || {})), field, { int: attrs && attrs.type === "number" });
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
    armed(del, () => act("DELETE", "/api/creatures/" + c.id, {}, () => { list = list.filter((x) => x.id !== c.id); open(list[0] ? list[0].id : null); }), "Delete? Existing enemies stay as they are");
    box.replaceChildren(h("div", { class: "sb-edit" },
      inp("name", { class: "input sb-name", "aria-label": "Name", maxlength: 200 }),
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
        h("div", { class: "full" }, prop("Actions & attacks", "attacks", { rows: 5, class: "prose", placeholder: "Scimitar. Melee Weapon Attack: +4 to hit, reach 5 ft., one target. Hit: 5 (1d6 + 2) slashing damage." })),
        h("div", { class: "full" }, prop("DM notes", "notes", { rows: 3 })))),
      h("div", { class: "row", style: "margin-top:12px;justify-content:flex-end" }, del));
    mods();
  }
  renderList();
  open(current);
})();
