/* DM battle map editor. Token positions, fog and terrain are saved per
   action; settings autosave through a Binder. Combat data is read-only here
   except "Next turn", which uses the normal encounter endpoint. */
(function () {
  "use strict";
  const { h, icon, $, $$, boot, act, api, toast, armed, Binder, Save } = L;
  let S = boot("boot-map");
  const MID = S.map.id;
  let terrainKind = "wall";
  let revs = { rev: S.map.rev, encounter_rev: S.encounter ? S.encounter.rev : null };

  const view = new MapView($("#stage"), {
    role: "dm",
    imageUrl: (m) => (m.image ? "/api/uploads/" + m.image : null),
    onSelect: (t) => {
      if (aim) { aimAt(t); view.selectedId = selectedToken; view.draw(); return; } // picking a target, not a new token
      selectedToken = t ? t.id : null; renderSelected(); renderTokens();
    },
    canMove: () => !aim,
    onMove: (t, x, y) => run("POST", "/api/tokens/" + t.id + "/move", { x, y }),
    onBrush: (tool, cells) => {
      if (tool === "paint") run("POST", "/api/maps/" + MID + "/terrain", { cells, value: terrainKind === "erase" ? null : terrainKind });
      else run("POST", "/api/maps/" + MID + "/fog", { cells, reveal: tool === "reveal" });
    },
    onPlace: (x, y) => {
      if (pendingMonster) { dropMonsters(x, y); return; }
      run("POST", "/api/maps/" + MID + "/tokens", { kind: "marker", label: "Marker", x, y, hidden: true },
        () => toast("Marker placed (hidden from players). Rename it or change it to a trap on the right.", "ok"));
    },
    canEditShapes: true,
    onPing: (x, y) => { api("POST", "/api/maps/" + MID + "/ping", { x, y }).then((d) => view.setPings(d.pings)).catch((e) => toast(e.message, "error")); if (window.FX) FX.sound("ping"); },
    onArea: (a) => run("POST", "/api/maps/" + MID + "/shapes", { kind: a.kind, x: a.x, y: a.y, size: a.size, width: a.width, dir: a.dir, color: a.color, label: a.label, hidden: a.hidden },
      (d) => { view.selectedShape = d.shape_id; renderAreas(); if (window.FX) FX.sound("hit"); }),
    onShapeMove: (sh, x, y) => run("PATCH", "/api/maps/" + MID + "/shapes/" + sh.id, { x, y }),
    onSelectShape: () => renderAreas(),
  });
  let selectedToken = null;
  let aim = null;        // { by, act, amount, done: Set, half } while the DM taps who an attack or spell hits
  let lastResult = null; // { by, text, kind, undo } what the last attack did, shown under the buttons
  let enc = null, encLoading = false; // the map's encounter with full combatant details, for the fight panel
  let hpAmt = "";
  let pendingMonster = null; // the monster waiting to be clicked onto the map

  function run(method, url, body, after) {
    return act(method, url, body, (d) => { if (d && d.map) apply(d); if (after) after(d); },
      { onError: (err) => { toast(err.message, "error"); refresh(true); } });
  }
  // a monster's death and a hero being knocked down get their own moment
  function moments(before, now) {
    if (!window.FX || !before) return;
    const was = new Map(before.tokens.map((t) => [t.id, t]));
    for (const t of now.tokens) {
      const p = was.get(t.id);
      if (!p || p.hp == null || t.hp == null || !(p.hp > 0 && t.hp === 0)) continue;
      if (t.kind === "enemy") { FX.banner("Defeated!", t.display + " falls", "down"); FX.burst($("#stage"), "fumble", 40); }
      else FX.banner(t.display + " is down!", "Knocked prone · roll death saves", "down");
      FX.sound("down");
    }
  }
  function apply(state) {
    moments(S, state);
    S = state;
    revs = { rev: S.map.rev, encounter_rev: S.encounter ? S.encounter.rev : null };
    view.setData(S.map, S.tokens);
    renderTop(); renderOrder(); renderTokens(); renderSelected(); renderAreas(); syncSettings();
    if (state.pings) view.setPings(state.pings);
  }

  // ---- top bar -------------------------------------------------------------------
  const nameBinder = new Binder({ url: "/api/maps/" + MID, model: { name: S.map.name }, extract: (d) => { setTimeout(() => apply(d), 0); return d.map; } });
  nameBinder.bind($("#map-name"), "name");
  function renderTop() {
    $("#live-flag").textContent = S.live ? "Players can see this map" : "";
    $("span", $("#live-btn")).textContent = S.live ? "Stop showing to players" : "Show to players";
    document.title = S.map.name + " · Campaign Ledger";
  }
  $("#live-btn").addEventListener("click", () => act("POST", "/api/campaigns/" + S.map.campaign_id + "/live-map",
    { map_id: S.live ? null : MID }, () => refresh(true)));
  $("#preview-btn").addEventListener("click", async (e) => {
    e.preventDefault();
    const d = await api("GET", "/api/maps/" + MID + "/player-preview");
    const shown = d.tokens.length, total = S.tokens.length;
    toast(`Players would see ${shown} of ${total} tokens` + (S.map.fog_enabled ? `, and ${(d.map.revealed.match(/1/g) || []).length} revealed squares.` : ". Fog of war is off."), "ok", { ms: 7000 });
  });

  // ---- tools ---------------------------------------------------------------------------
  const HINTS = {
    select: "Drag tokens to move them. Drag empty space to pan. Scroll or pinch to zoom.",
    pan: "Drag to pan. Scroll or pinch to zoom.",
    measure: "Drag to measure. Diagonals count as one square (5e rule).",
    reveal: "Paint squares to reveal them to players.",
    conceal: "Paint squares to hide them under fog.",
    paint: "Paint terrain. Choose a type in the Brush panel.",
    place: "Click a square to drop a marker. It starts hidden from players.",
    ping: "Click to ping a spot. Everyone sees a ripple there for a few seconds. (Double-click works with any tool.)",
    area: "Click to place the area. For cones and lines, press where it starts and drag to aim.",
  };
  function setTool(t) {
    if (t !== "place" && pendingMonster) { pendingMonster = null; renderMonsters(); }
    if (t !== "select" && aim) { aim = null; renderSelected(); }
    view.tool = t;
    $$("[data-tool]").forEach((b) => { b.classList.toggle("is-on", b.dataset.tool === t); b.setAttribute("aria-pressed", b.dataset.tool === t); });
    $("#hint").textContent = HINTS[t];
    const brushy = ["reveal", "conceal", "paint"].includes(t);
    $("#brush-panel").hidden = !brushy;
    $("#terrain-palette").hidden = t !== "paint";
    $("#fog-all").hidden = t === "paint";
    $("#area-panel").hidden = t !== "area";
    if (brushy && t !== "paint" && !S.map.fog_enabled) toast("Fog of war is off for this map. Turn it on in Map & grid settings so players only see revealed squares.");
  }
  $$("[data-tool]").forEach((b) => b.addEventListener("click", () => setTool(b.dataset.tool)));
  $$("#brush-size [data-b]").forEach((b) => b.addEventListener("click", () => {
    view.brush = Number(b.dataset.b);
    $$("#brush-size [data-b]").forEach((x) => x.classList.toggle("is-on", x === b));
  }));
  $("#brush-size [data-b='1']").classList.add("is-on");
  $("#terrain-palette").replaceChildren(...[...Object.entries(MapView.TERRAIN), ["erase", { fill: "transparent", label: "Erase" }]].map(([k, T]) =>
    h("button", { type: "button", class: k === terrainKind ? "is-on" : "", "data-t": k, onclick: (e) => {
      terrainKind = k; $$("#terrain-palette button").forEach((x) => x.classList.toggle("is-on", x.dataset.t === k));
    } }, h("span", { class: "swatch", style: "background:" + T.fill }), T.label)));
  $$("[data-fog]").forEach((b) => armed(b, () => run("POST", "/api/maps/" + MID + "/fog", { all: b.dataset.fog }), b.dataset.fog === "reveal" ? "Reveal everything?" : "Hide everything?"));
  $("#zoom-in").addEventListener("click", () => view.zoom(1.25));
  $("#zoom-out").addEventListener("click", () => view.zoom(0.8));
  $("#zoom-fit").addEventListener("click", () => view.fit());
  setTool("select");

  // ---- add monsters from the library or the Monster Book -------------------------------------
  let monsters = [], chosen = null;
  async function loadMonsters() {
    try {
      const [lib, book] = await Promise.all([api("GET", "/api/creatures?campaign_id=" + S.map.campaign_id), api("GET", "/api/monster-book")]);
      const have = new Set(lib.creatures.map((c) => c.name.toLowerCase()));
      monsters = lib.creatures.map((c) => ({ key: "c" + c.id, creature_id: c.id, name: c.name, info: [c.cr ? "CR " + c.cr : "", c.max_hp + " HP", "AC " + c.ac].filter(Boolean).join(" · "), from: "Your library" }))
        .concat(book.monsters.filter((m) => !have.has(m.name.toLowerCase())).map((m) => ({ key: "b" + m.name, book: m.name, name: m.name, info: "CR " + m.cr + " · " + m.max_hp + " HP · AC " + m.ac, from: "Monster Book" })));
    } catch (e) { monsters = []; }
    renderMonsters();
  }
  function renderMonsters() {
    const q = $("#mon-q").value.trim().toLowerCase();
    const list = monsters.filter((m) => !q || m.name.toLowerCase().includes(q)).slice(0, 60);
    $("#mon-list").replaceChildren(...(list.length ? list.map((m) => h("li", { class: chosen && chosen.key === m.key ? "is-sel" : "",
      onclick: () => { chosen = m; pendingMonster = null; renderMonsters(); } },
      h("b", null, m.name), h("span", { class: "faint" }, m.info), h("span", { class: "tag" }, m.from))) : [h("li", { class: "faint" }, monsters.length ? "No monsters match." : "No monsters yet.")]));
    const btn = $("#mon-place");
    btn.disabled = !chosen;
    btn.classList.toggle("is-armed", !!pendingMonster);
    $("span", btn).textContent = pendingMonster ? "Click the map… (Esc to cancel)" : chosen ? "Place " + ($("#mon-count").value || 1) + " × " + chosen.name : "Pick a monster";
  }
  function dropMonsters(x, y) {
    const m = pendingMonster, n = Math.max(1, Math.min(20, Number($("#mon-count").value) || 1));
    const body = Object.assign({ count: n, x, y, hidden: $("#mon-hidden").checked }, m.creature_id ? { creature_id: m.creature_id } : { book: m.book });
    run("POST", "/api/maps/" + MID + "/monsters", body, (d) => {
      toast("Added " + d.added.join(", ") + (body.hidden ? " — hidden from players until you show them" : "") + (d.encounter_created ? ". Made an encounter for this map so you can run the fight." : "."), "ok",
        { action: { label: "Open combat", run: () => { location.href = "/combat/" + d.map.encounter_id; } } });
      if (window.FX) FX.sound("hit");
    });
    // stay ready to drop more of the same until another tool is picked
  }
  $("#mon-q").addEventListener("input", renderMonsters);
  $("#mon-count").addEventListener("input", renderMonsters);
  $("#mon-place").addEventListener("click", () => {
    if (!chosen) return;
    pendingMonster = pendingMonster ? null : chosen;
    if (pendingMonster) { setTool("place"); pendingMonster = chosen; const n = Number($("#mon-count").value) || 1; $("#hint").textContent = "Click where " + (n > 1 ? "the " + n + " × " + chosen.name + " go" : "the " + chosen.name + " goes") + ". Keep clicking to add more; pick Move when you're done."; }
    renderMonsters();
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && pendingMonster) { pendingMonster = null; setTool("select"); renderMonsters(); } });
  loadMonsters();

  // ---- spell areas -------------------------------------------------------------------------
  const DAMAGE_COLORS = [["Fire", "#e0714f"], ["Cold", "#7fc4e8"], ["Lightning", "#f3d23a"], ["Acid", "#8fd14f"], ["Poison", "#5fa04a"],
    ["Necrotic", "#7a5a9e"], ["Radiant", "#ffe9a0"], ["Thunder", "#6f8fd6"], ["Psychic", "#d36fb0"], ["Force", "#c8c8e8"], ["Dark", "#222"], ["Plain", "#c7a25e"]];
  const AREA_PRESETS = [
    ["Fireball", "circle", 20, "#e0714f"], ["Burning Hands", "cone", 15, "#e0714f"], ["Lightning Bolt", "line", 100, "#f3d23a"],
    ["Thunderwave", "square", 15, "#6f8fd6"], ["Shatter", "circle", 10, "#6f8fd6"], ["Cone of Cold", "cone", 60, "#7fc4e8"],
    ["Spirit Guardians", "circle", 15, "#ffe9a0"], ["Entangle", "square", 20, "#8fd14f"], ["Web", "square", 20, "#e8e8e8"],
    ["Fog Cloud", "circle", 20, "#9aa0a6"], ["Darkness", "circle", 15, "#222"], ["Cloudkill", "circle", 20, "#5fa04a"],
    ["Breath (cone)", "cone", 15, "#e0714f"], ["Breath (line)", "line", 30, "#8fd14f"],
  ];
  const spec = view.areaSpec;
  function syncSpec() {
    spec.kind = $("#area-kind").value; spec.size = Number($("#area-size").value) || 20;
    spec.width = Number($("#area-width").value) || 5; spec.label = $("#area-label").value.trim(); spec.hidden = $("#area-hidden").checked;
    $("#area-width-wrap").hidden = spec.kind !== "line";
    $$("#area-colors button").forEach((b) => b.classList.toggle("is-on", b.dataset.c === spec.color));
  }
  ["#area-kind", "#area-size", "#area-width", "#area-label", "#area-hidden"].forEach((sel) => $(sel).addEventListener("input", syncSpec));
  $("#area-colors").replaceChildren(...DAMAGE_COLORS.map(([name, c]) => h("button", { type: "button", "data-c": c, title: name, "aria-label": name,
    onclick: () => { spec.color = c; syncSpec(); } }, h("span", { class: "swatch", style: "background:" + c }), name)));
  $("#area-presets").replaceChildren(...AREA_PRESETS.map(([name, kind, size, c]) => h("button", { type: "button", class: "btn btn-sm",
    onclick: () => { $("#area-kind").value = kind; $("#area-size").value = size; $("#area-label").value = name; spec.color = c; syncSpec(); toast(name + ": click the map to place it" + (kind === "cone" || kind === "line" ? ", then drag to aim." : "."), "ok"); } }, name)));
  syncSpec();
  function renderAreas() {
    const shapes = S.map.shapes || [];
    $("#areas-panel").hidden = !shapes.length;
    $("#areas-count").textContent = shapes.length || "";
    $("#areas").replaceChildren(...shapes.map((sh) => {
      const inside = MapView.tokensInShape(sh, S.map, S.tokens).map((t) => t.display);
      const turn = (deg) => run("PATCH", "/api/maps/" + MID + "/shapes/" + sh.id, { dir: (sh.dir || 0) + deg });
      const del = h("button", { type: "button", class: "icon-btn sm", "aria-label": "Remove area", title: "Remove",
        onclick: () => run("DELETE", "/api/maps/" + MID + "/shapes/" + sh.id) }, icon("x", "sm"));
      return h("li", { class: view.selectedShape === sh.id ? "is-sel" : "", onclick: (e) => { if (e.target.closest("button")) return; view.selectedShape = sh.id; view.draw(); renderAreas(); } },
        h("div", { class: "row", style: "align-items:center;gap:6px" },
          h("span", { class: "swatch", style: "background:" + sh.color }),
          h("b", { class: "grow" }, (sh.label || ({ circle: "Circle", cone: "Cone", line: "Line", square: "Cube" })[sh.kind]) + " · " + sh.size + " ft"),
          sh.hidden ? h("span", { class: "faint", title: "Hidden from players" }, icon("eye-off", "sm")) : null,
          sh.kind === "cone" || sh.kind === "line" ? [h("button", { type: "button", class: "icon-btn sm", title: "Turn left", "aria-label": "Turn left", onclick: () => turn(-45) }, icon("rotate-ccw", "sm")),
            h("button", { type: "button", class: "icon-btn sm", title: "Turn right", "aria-label": "Turn right", onclick: () => turn(45) }, icon("refresh-cw", "sm"))] : null,
          h("button", { type: "button", class: "icon-btn sm", title: sh.hidden ? "Show to players" : "Hide from players", "aria-label": "Toggle hidden",
            onclick: () => run("PATCH", "/api/maps/" + MID + "/shapes/" + sh.id, { hidden: !sh.hidden }) }, icon("eye-off", "sm")),
          del),
        h("div", { class: "faint", style: "font-size:.85rem" }, inside.length ? "Inside: " + inside.join(", ") : "Nobody inside"));
    }));
  }
  armed($("#areas-clear"), () => run("DELETE", "/api/maps/" + MID + "/shapes"), "Clear all areas?");

  // ---- turn order (read-only, plus Next turn) -----------------------------------------------
  function renderOrder() {
    const box = $("#order"), e = S.encounter;
    if (!e) { box.replaceChildren(h("p", { class: "faint", style: "margin:0;font-size:.9rem" }, "Link an encounter in Map & grid settings to show its turn order here.")); return; }
    box.replaceChildren(
      h("div", { class: "row", style: "align-items:center;margin-bottom:6px" },
        h("a", { href: "/combat/" + e.id, style: "font-weight:700" }, e.name),
        h("span", { class: "faint" }, e.status === "active" ? "Round " + e.round : e.status === "ended" ? "ended" : "not started"),
        h("span", { class: "grow" }),
        e.status === "active" ? h("button", { type: "button", class: "btn btn-sm btn-primary", onclick: () =>
          act("POST", "/api/encounters/" + e.id + "/next", {}, () => refresh(true)) }, "Next turn") : null),
      h("ol", { class: "mini-order" }, e.order.map((o) => h("li", {
        class: (o.id === e.current_id && e.status === "active" ? "is-current" : "") + (["dead", "defeated", "fled"].includes(o.status) ? " is-out" : "") },
        h("span", { class: "i" }, o.init_roll ?? "—"), h("span", { class: "grow" }, o.name), o.hidden ? h("span", { class: "faint", title: "Hidden from players" }, icon("eye-off", "sm")) : null,
        h("span", { class: "faint num" }, o.hp + "/" + o.max_hp)))));
  }

  // ---- tokens ----------------------------------------------------------------------------
  function renderTokens() {
    $("#token-count").textContent = S.tokens.length;
    const hiddenCount = S.tokens.filter((t) => (t.hidden || t.combatant_hidden) && !["trap", "marker"].includes(t.kind)).length;
    $("#reveal-all").hidden = !hiddenCount;
    $("#reveal-all").lastChild.textContent = " Show all hidden (" + hiddenCount + ")";
    $("#tokens").replaceChildren(...(S.tokens.length ? S.tokens.map((t) => h("li", { class: (t.id === selectedToken ? "is-sel" : "") + (t.hidden || t.combatant_hidden ? " is-hidden" : ""), onclick: (e) => { if (e.target.closest("button")) return; selectedToken = t.id; view.selectedId = t.id; view.draw(); renderSelected(); renderTokens(); } },
      h("span", { class: "swatch", style: "background:" + (t.color || MapView.KIND_COLOR[t.kind]) }),
      h("span", { class: "nm" }, t.display),
      h("button", { type: "button", class: "icon-btn sm eye-btn" + (t.hidden || t.combatant_hidden ? " is-off" : ""),
        title: t.hidden || t.combatant_hidden ? "Hidden from players — click to show" : "Players can see this — click to hide",
        "aria-label": (t.hidden || t.combatant_hidden ? "Show " : "Hide ") + t.display,
        onclick: () => run("POST", "/api/tokens/" + t.id + "/visibility", { hidden: !(t.hidden || t.combatant_hidden) }, () => { if (window.FX && (t.hidden || t.combatant_hidden)) FX.sound("start"); }) },
        icon(t.hidden || t.combatant_hidden ? "eye-off" : "sun", "sm")),
      h("span", { class: "faint", style: "font-size:.8rem" }, t.kind),
      (t.notes || "").trim() ? h("span", { class: "c-note tok-note", title: t.notes }, icon("scroll-text", "sm"), h("span", null, t.notes.trim())) : null)) : [h("li", { class: "faint" }, "No tokens yet.")]));
  }
  $("#from-enc").addEventListener("click", () => run("POST", "/api/maps/" + MID + "/tokens/from-encounter"));
  $("#reveal-all").addEventListener("click", () => run("POST", "/api/maps/" + MID + "/reveal", {}, (d) => {
    toast("Showed " + d.revealed + " to the players.", "ok");
    if (window.FX) { FX.banner("Ambush!", "The hidden enemies are revealed", "dmg"); FX.sound("start"); }
  }));
  $("#add-char").addEventListener("change", (e) => {
    const id = Number(e.target.value); e.target.value = "";
    if (id) run("POST", "/api/maps/" + MID + "/tokens", { character_id: id, x: 0, y: 0 });
  });
  let selPending = false;
  function renderSelected() {
    const box = $("#selected-panel");
    const t = S.tokens.find((x) => x.id === selectedToken);
    // typing in the panel (token notes, label, a monster's attacks): wait until they're done
    const ae = document.activeElement;
    if (t && box.contains(ae) && ae.matches("textarea, input[type=text], select")) { selPending = true; return; }
    selPending = false;
    box.hidden = !t;
    if (!t) return;
    const patch = (field, to) => run("PATCH", "/api/tokens/" + t.id, { changes: { [field]: { from: t[field], to } } });
    const del = h("button", { type: "button", class: "btn btn-sm btn-quiet btn-danger" }, icon("trash-2", "sm"), " Remove token");
    armed(del, () => run("DELETE", "/api/tokens/" + t.id, {}, () => { selectedToken = null; renderSelected(); }), "Remove from map?");
    const fight = t.combatant_id ? fightPanel(t) : null;
    const keep = document.activeElement && document.activeElement.dataset && document.activeElement.dataset.keep;
    box.replaceChildren(
      fight || h("h3", { class: "rule-head" }, "Selected token"),
      h(fight ? "details" : "div", { class: "token-settings", "data-key": "token-settings", style: "display:grid;gap:8px" },
        fight ? h("summary", { class: "lbl" }, "Token settings") : null,
        h("div", null, h("b", null, t.display), t.hp != null ? h("span", { class: "faint" }, " · " + t.hp + "/" + t.max_hp + " HP") : null,
          t.character_id && !t.combatant_id ? h("div", { class: "faint", style: "font-size:.82rem" }, "HP and conditions come from the character sheet; this token only sets position.") : null),
        h("div", { class: "grid2" },
          h("label", { class: "field" }, h("span", null, "Label"), h("input", { type: "text", value: t.label, placeholder: t.name || "", onchange: (e) => patch("label", e.target.value) })),
          h("label", { class: "field" }, h("span", null, "Type"), h("select", { onchange: (e) => patch("kind", e.target.value) },
            ["pc", "npc", "enemy", "trap", "marker", "object"].map((k) => h("option", { value: k, selected: k === t.kind }, k)))),
          h("label", { class: "field" }, h("span", null, "Size (squares)"), h("select", { onchange: (e) => patch("size", Number(e.target.value)) },
            [[1, "Medium / small"], [2, "Large"], [3, "Huge"], [4, "Gargantuan"]].map(([v, l]) => h("option", { value: v, selected: v === t.size }, l)))),
          h("label", { class: "field" }, h("span", null, "Colour"), h("input", { type: "color", value: t.color || MapView.KIND_COLOR[t.kind], style: "min-height:34px;padding:2px", onchange: (e) => patch("color", e.target.value) }))),
        h("label", { class: "check" }, h("input", { type: "checkbox", checked: t.hidden, onchange: (e) => patch("hidden", e.target.checked) }), "Hidden from players"),
        t.combatant_hidden ? h("div", { class: "faint", style: "font-size:.82rem" }, "This combatant is hidden in the encounter, so players can't see it either way.") : null,
        h("label", { class: "field" }, h("span", null, "Token notes (only you see these)"), h("textarea", { rows: 3, class: "note-input", onchange: (e) => patch("notes", e.target.value) }, t.notes)),
        del));
    L.restoreOpen(box);
    if (keep) { const el = box.querySelector('[data-keep="' + keep + '"]'); if (el) el.focus(); }
  }
  $("#selected-panel").addEventListener("focusout", () => setTimeout(() => { if (selPending) renderSelected(); }, 0));

  // ---- fight from the map: pick a token, click an attack or spell, tap who it's on -----------
  const EID = () => S.map.encounter_id;
  const fighter = (id) => enc && enc.combatants.find((c) => c.id === id);
  const signed = L.signed;
  function ensureEnc() {
    const want = S.encounter ? S.encounter.rev : null;
    if (encLoading || !EID() || (enc && enc.encounter.id === EID() && enc.encounter.rev === want)) return;
    encLoading = true;
    api("GET", "/api/encounters/" + EID()).then((d) => { enc = d; }).catch(() => { enc = null; })
      .finally(() => { encLoading = false; renderSelected(); });
  }
  // wait: each roll lands before the next starts, so the d20 is seen before the damage
  const roll = (req) => Dice.roll(Object.assign({ encounter_id: EID() }, req), null, { wait: true });
  // House rule (Settings → Combat): every attack and harmful spell rolls d20 + bonus against AC.
  const toHitRule = () => !enc || !enc.settings || enc.settings.roll_to_hit !== false;
  /* Everything this combatant can do, as buttons.
     single: one target, rolled when it's tapped. many: tap each one it reaches.
     toHit: rolled against each target's AC first. dmg / roll: the damage (or healing). effect: a condition it puts on. */
  function actionsFor(c) {
    const out = [], rule = toHitRule();
    if (c.linked) {
      (c.attacks || []).forEach((a, i) => !a.has_dmg && !a.has_hit ? (a.ac
        // no dice: "+2 ac to target" works like a buff spell; anything else is just a note
        ? out.push({ name: a.name, many: true, icon: a.ac > 0 ? "shield-plus" : "zap", info: signed(a.ac) + " AC", effect: { name: a.name, condition: a.name, ac: a.ac, rounds: null } })
        : null) : out.push({ name: a.name || "Attack", heal: !!a.heal, single: true, icon: a.heal ? "heart" : "swords",
        info: a.heal ? "heals" : a.has_hit ? "attack roll" : rule ? "d20 to hit" : "damage",
        toHit: a.heal ? null : a.has_hit ? () => roll({ check: { type: "attack", key: i, combatant_id: c.id } })
          : rule ? () => roll({ expression: "1d20", label: (a.name || "Attack") + " attack", kind: "attack", subject: c.name }) : null,
        dmg: a.has_dmg ? (crit) => roll({ check: { type: "damage", key: i, combatant_id: c.id }, crit }) : null }));
      const sc = c.spellcasting;
      (c.spells || []).forEach((s) => {
        const rollSpell = (crit) => roll({ check: { type: "spell", key: s.index, combatant_id: c.id }, crit });
        const spellAtk = sc ? () => roll({ check: { type: "spell_attack", combatant_id: c.id }, label: s.name + " attack" })
          : () => roll({ expression: "1d20", label: s.name + " attack", kind: "attack", subject: c.name });
        const atkInfo = "spell attack " + (sc ? signed(sc.attack) : "+0");
        const what = L.spellWhat(s);
        if (s.effect === "damage" && s.hit === "attack" && s.dice)
          out.push({ name: s.name, single: true, icon: "wand-sparkles", info: atkInfo + " · " + s.dice, toHit: spellAtk, dmg: rollSpell });
        else if (s.effect === "damage" && s.dice)
          out.push({ name: s.name, many: true, icon: "wand-sparkles", roll: () => rollSpell(false), crit: () => rollSpell(true),
            info: (rule ? atkInfo + " · " : s.hit ? s.hit.toUpperCase() + " save" + (sc ? " DC " + sc.dc : "") + " · " : "") + s.dice,
            toHit: rule ? spellAtk : null, save: !rule && !!s.hit });
        else if (s.effect === "heal" && s.dice)
          out.push({ name: s.name, many: true, heal: true, icon: "heart", info: "heals " + s.dice, roll: () => rollSpell(false) });
        else if (s.condition || s.ac) {
          const helps = L.spellHelps(s);
          out.push({ name: s.name, many: true, icon: helps ? "shield-plus" : "zap", info: (rule && !helps ? atkInfo + " · " : "") + what, effect: s,
            toHit: rule && !helps ? spellAtk : null });
        }
      });
    } else {
      const sb = c.statblock || {};
      L.attackLines(sb.attacks).forEach((a) => out.push(monsterAction(c, a, false, rule)));
      L.attackLines(sb.spells).forEach((a) => out.push(monsterAction(c, a, true, rule)));
    }
    return out;
  }
  // One line of a monster's Attacks or Spells box. Spells can reach several targets.
  function monsterAction(c, a, spell, rule) {
    if (a.check) return { name: a.name, instant: true, icon: "dice-5",
      info: "roll " + a.check + (a.beat != null ? " · beat " + a.beat : a.dc != null ? " · DC " + a.dc : ""),
      run: async () => {
        const r = await roll({ expression: a.check, label: a.name, kind: "custom", subject: c.name });
        if (!r) return;
        const v = L.checkVerdict(a, r.total);
        say(c.id, a.name + ": rolled " + r.total + (v ? " — " + v : "") + ".", v && !/^(beats|makes)/.test(v) ? "miss" : "hit");
      } };
    const kind = a.heal ? "heal" : "damage";
    const dmg = a.dmg ? (crit) => roll({ expression: a.dmg, label: a.name + (a.heal ? " healing" : " damage"), kind, subject: c.name, crit }) : null;
    const toHit = a.heal ? null : a.hit || rule ? () => roll({ expression: "1d20" + (a.hit || ""), label: a.name + " attack", kind: "attack", subject: c.name }) : null;
    const effect = a.condition ? { name: a.name, condition: a.condition, rounds: a.rounds, ac: 0 } : null;
    const info = [toHit ? (a.hit || "+0") + " to hit" : "", a.dmg ? (a.heal ? "heals " : "") + a.dmg + (a.heal || toHit ? "" : " damage") : "",
      a.condition ? a.condition + (a.rounds ? " " + a.rounds + " rds" : "") : ""].filter(Boolean).join(" · ");
    const icon = a.heal ? "heart" : spell ? (a.dmg ? "wand-sparkles" : "zap") : "swords";
    return spell || a.area
      ? { name: a.name, many: true, heal: a.heal, icon, info, toHit, effect, roll: dmg ? () => dmg(false) : null, crit: dmg && !a.heal ? () => dmg(true) : null }
      : { name: a.name, single: true, heal: a.heal, icon, info, toHit, effect, dmg };
  }
  function say(by, text, kind, undo) {
    lastResult = { by, text, kind, undo };
    renderSelected();
    if (window.FX) FX.sound(kind === "miss" ? "fumble" : kind === "heal" ? "heal" : kind === "crit" ? "crit" : "hit");
  }
  const undoHp = () => act("POST", "/api/encounters/" + EID() + "/undo", {}, () => { lastResult = null; refresh(true); });
  const hpTo = (target, op, amount, by, after) => act("POST", "/api/encounters/" + EID() + "/damage",
    { targets: [target.id], amount, op, attacker_id: by.id }, () => { refresh(true); if (after) after(); }, { onError: (e) => toast(e.message, "error") });
  const putEffect = (c, target, s, after) => act("POST", "/api/encounters/" + EID() + "/conditions",
    { targets: [target.id], name: s.condition || s.name, rounds: s.rounds, ac: s.ac || null, caster_id: c.id, note: s.condition && s.condition !== s.name ? s.name : "" },
    () => { refresh(true); if (after) after(); }, { onError: (e) => toast(e.message, "error") });
  // Roll to hit against the target's AC: { hit, crit, text } or null if the roll failed to happen.
  async function rollToHit(a, target) {
    const r = await a.toHit();
    if (!r) return null;
    const nat = r.result && r.result.natural, crit = nat === 20;
    const hit = crit || (nat !== 1 && r.total >= target.ac);
    return { hit, crit, text: r.total + " vs AC " + target.ac + (nat === 1 ? ", natural 1" : crit ? ", natural 20" : "") };
  }

  async function arm(c, a) {
    lastResult = null;
    if (a.instant) { await a.run(); return; } // a plain roll: no target to pick
    aim = { by: c.id, act: a, amount: null, done: new Set(), half: false };
    if (a.roll) { // area / healing spells: roll once, then every tap gets the same amount
      const r = await a.roll();
      if (!r) { aim = null; renderSelected(); return; }
      aim.amount = Math.max(0, r.total);
    }
    setTool("select");
    $("#hint").textContent = a.name + ": tap " + (a.single ? "who it's aimed at" : "each one it reaches") + " on the map. Esc cancels.";
    renderSelected();
  }
  function stopAim() { aim = null; setTool(view.tool); renderSelected(); }
  async function aimAt(t) {
    const cur = aim, c = fighter(cur.by), a = cur.act;
    const target = t && t.combatant_id ? fighter(t.combatant_id) : null;
    if (!t) return;
    if (!target) { toast((t.display || "That token") + " isn't a fighter, just a marker on the map. Heroes and monsters in the fight can be targeted.", "error"); return; }
    if (a.single) {
      aim = null; setTool(view.tool);
      let crit = false, how = "";
      if (a.toHit) {
        const r = await rollToHit(a, target);
        if (!r) { renderSelected(); return; }
        if (!r.hit) { say(c.id, a.name + ": missed " + target.name + " (" + r.text + ").", "miss"); return; }
        crit = r.crit; how = " (" + r.text + ")";
      }
      if (a.effect) putEffect(c, target, a.effect, a.dmg ? null : () => say(c.id, a.name + ": " + target.name + " is " + a.effect.condition + how + ".", "hit"));
      if (!a.dmg) { if (!a.effect) say(c.id, a.name + ": hit " + target.name + how + ".", "hit"); return; }
      const d = await a.dmg(crit && !a.heal);
      if (!d) { renderSelected(); return; }
      const n = Math.max(0, d.total);
      hpTo(target, a.heal ? "heal" : "damage", n, c, () => say(c.id, a.heal ? a.name + ": healed " + target.name + " for " + n + "."
        : (crit ? "Critical hit! " : "Hit! ") + n + " damage to " + target.name + " with " + a.name + how + (a.effect ? ", and " + a.effect.condition : "") + ".",
        a.heal ? "heal" : crit ? "crit" : "hit", true));
      return;
    }
    // spells that reach several: each tap lands on one more (rolling to hit each one first)
    if (cur.done.has(target.id)) return;
    cur.done.add(target.id);
    renderSelected();
    let how = "", crit = false;
    if (a.toHit) {
      const r = await rollToHit(a, target);
      if (!r) { cur.done.delete(target.id); renderSelected(); return; }
      if (!r.hit) { say(c.id, a.name + ": missed " + target.name + " (" + r.text + ").", "miss"); return; }
      how = " (" + r.text + ")";
      crit = r.crit;
    }
    if (crit && a.crit && cur.amount != null) { // natural 20: this one takes double dice
      const d = await a.crit();
      if (d) {
        const n = Math.max(0, d.total);
        if (a.effect) putEffect(c, target, a.effect);
        hpTo(target, "damage", n, c, () => say(c.id, "Critical hit! " + a.name + ": " + n + " damage to " + target.name + how + ".", "crit", true));
        return;
      }
    }
    if (a.effect && cur.amount == null) {
      putEffect(c, target, a.effect, () => say(c.id, a.name + ": " + (a.effect.condition || a.effect.name) + " on " + target.name + how + ".", a.toHit ? "hit" : "heal"));
      return;
    }
    if (a.effect) putEffect(c, target, a.effect);
    const half = !a.heal && cur.half, n = half ? Math.floor(cur.amount / 2) : cur.amount;
    hpTo(target, a.heal ? "heal" : "damage", n, c, () => say(c.id, a.name + ": " + (a.heal ? "healed " + target.name + " for " + n
      : n + " damage to " + target.name + (half ? " (saved, half)" : "") + how) + ".", a.heal ? "heal" : "hit", true));
  }
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && aim) stopAim(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && aim) stopAim(); });

  function fightPanel(t) {
    ensureEnc();
    const c = fighter(t.combatant_id);
    if (!c) return h("div", null, h("h3", { class: "rule-head" }, t.display), h("p", { class: "faint", style: "margin:0" }, encLoading || !enc ? "Loading…" : "This token's combatant was removed from the fight."));
    const isTurn = enc.encounter.status === "active" && enc.encounter.current_id === c.id;
    const pct = c.max_hp ? Math.max(0, Math.min(100, Math.round(c.hp / c.max_hp * 100))) : 0;
    const acts = actionsFor(c);
    const a = aim && aim.by === c.id ? aim.act : null;
    // aiming: one big instruction instead of the buttons
    const aiming = a ? h("div", { class: "fight-aim" + (a.heal ? " is-heal" : "") },
      h("div", { class: "fa-head" }, icon(a.icon, "sm"), h("b", null, a.name),
        aim.amount != null ? h("span", { class: "tag" }, (a.heal ? "heals " : "") + aim.amount + (a.heal ? "" : " damage")) : null),
      h("p", { class: "fa-ask" }, a.single ? "Now tap who " + c.name + " " + (a.heal ? "heals" : "attacks") + " on the map."
        : aim.done.size ? "Tap anyone else it reaches, or Done." : "Now tap each one it reaches on the map."),
      a.toHit ? h("p", { class: "faint", style: "margin:0 0 6px;font-size:.85rem" }, a.single ? "It rolls a d20 to hit against their AC; on a hit it " + (a.dmg ? "rolls and deals the damage." : "lands.")
        : "Each one you tap gets its own d20 roll against their AC" + (aim.amount != null ? "; a hit takes the " + aim.amount + "." : ".")) : null,
      a.save ? h("label", { class: "check" }, h("input", { type: "checkbox", checked: aim.half, onchange: (e) => { aim.half = e.target.checked; } }), "This one saved: half damage") : null,
      h("button", { type: "button", class: "btn btn-sm" + (aim.done.size ? " btn-primary" : ""), onclick: stopAim }, aim.done.size ? "Done" : "Cancel")) : null;
    const res = lastResult && lastResult.by === c.id ? h("div", { class: "fight-result is-" + lastResult.kind, role: "status" },
      h("span", null, lastResult.text), lastResult.undo ? h("button", { type: "button", class: "btn btn-sm btn-quiet", onclick: undoHp }, icon("undo-2", "sm"), " Undo") : null) : null;
    const amt = h("input", { type: "number", min: 0, placeholder: "0", inputmode: "numeric", "data-keep": "fight-amt", "aria-label": "Amount", value: hpAmt,
      oninput: (e) => { hpAmt = e.target.value; } });
    const hp = (op) => {
      const n = Math.trunc(Number(amt.value));
      if (amt.value === "" || !Number.isFinite(n) || n < 0) { amt.focus(); return; }
      hpAmt = "";
      act("POST", "/api/combatants/" + c.id + "/hp", { op, amount: n }, () => refresh(true), { onError: (e) => toast(e.message, "error") });
    };
    const down = c.linked && c.hp === 0 && !["dead", "stable"].includes(c.status);
    const pipRow = (n, cls) => h("span", { class: "pips " + cls }, [0, 1, 2].map((i) => h("span", { class: "pip" + (i < n ? " on" : "") })));
    const deathBox = c.linked && (c.hp === 0 || c.death_successes || c.death_failures) ? h("div", { class: "death-box" },
      h("div", { class: "death-head" }, icon("skull", "sm"), h("b", null, down ? c.name + " is down" : c.status === "dead" ? c.name + " has died" : c.status === "stable" ? c.name + " is stable" : "Death saves")),
      h("div", { class: "row", style: "align-items:center;gap:8px" }, h("span", { class: "faint" }, "Saves"), pipRow(c.death_successes, ""), h("span", { class: "faint" }, "Fails"), pipRow(c.death_failures, "fail")),
      down ? h("button", { type: "button", class: "btn btn-primary", style: "margin-top:8px", onclick: () => act("POST", "/api/combatants/" + c.id + "/death-save", {},
        (d) => { if (window.Dice) Dice.show(d.roll); enc = null; refresh(true); }, { onError: (e) => toast(e.message, "error") }) },
        icon("dice-5", "sm"), " Roll death save") : null,
      down ? h("p", { class: "faint", style: "margin:6px 0 0;font-size:.85rem" }, "10 or more is a success. A hero standing right next to " + c.name + " adds +" + ((enc.settings || {}).ally_death_save_bonus ?? 2) + ".") : null) : null;
    return h("div", { class: "fight" },
      deathBox,
      h("div", { class: "fight-head" },
        h("b", { class: "fight-name" }, c.name), isTurn ? h("span", { class: "tag is-good" }, "Their turn") : null,
        h("span", { class: "grow" }), h("span", { class: "fight-ac", title: c.ac_bonus ? "Includes " + signed(c.ac_bonus) + " from effects" : "Armor class" }, h("b", null, c.ac), " AC")),
      h("div", { class: "fight-hp" }, h("span", { class: "hpbar", "data-level": pct <= 25 ? "low" : pct <= 50 ? "mid" : "high" }, h("span", { class: "hpbar-fill", style: "width:" + pct + "%" })),
        h("span", { class: "num" }, c.hp + " / " + c.max_hp + " HP" + (c.temp_hp ? " +" + c.temp_hp + " temp" : ""))),
      (c.conditions || []).length ? h("div", { class: "c-conds" }, c.conditions.map((x) => h("span", { class: "tag" }, x.name + (x.ac ? " " + signed(x.ac) + " AC" : "")))) : null,
      aiming, res,
      a ? null : acts.length ? h("div", { class: "fight-acts" },
        h("div", { class: "lbl" }, "Attacks & spells — click one, then tap who"),
        acts.map((x) => h("button", { type: "button", class: "fight-act" + (x.heal ? " is-heal" : ""), onclick: () => arm(c, x) },
          icon(x.icon, "sm"), h("b", null, x.name), x.info ? h("span", { class: "faint" }, x.info) : null)))
        : h("p", { class: "faint", style: "margin:8px 0 0;font-size:.88rem" }, c.linked ? "No attacks or spells on " + c.name + "'s sheet yet."
          : "No attacks or spells written for " + c.name + " yet. Write some below."),
      (c.linked ? (c.attacks || []).filter((x) => !x.has_dmg && !x.has_hit && !x.ac).map((x) => x.name + (x.notes ? ": " + x.notes : ""))
        : L.attackNotes((c.statblock || {}).attacks).concat(L.attackNotes((c.statblock || {}).spells))).map((n) => h("div", { class: "fight-note" }, n)),
      c.linked || a ? null : L.monsterEditor(c, () => { enc = null; refresh(true); renderSelected(); }),
      a ? null : h("div", { class: "hp-ctl fight-hpctl" }, amt,
        h("button", { type: "button", class: "btn btn-sm btn-dmg", onclick: () => hp("damage") }, "Damage"),
        h("button", { type: "button", class: "btn btn-sm btn-heal", onclick: () => hp("heal") }, "Heal")),
      h("a", { class: "faint", style: "font-size:.85rem", href: "/combat/" + EID() }, "Open the full fight on the Combat screen"));
  }

  // ---- settings autosave -----------------------------------------------------------------
  const settingsModel = {};
  $$("[data-m]").forEach((el) => { settingsModel[el.dataset.m] = S.map[el.dataset.m]; });
  const sb = new Binder({ url: "/api/maps/" + MID, model: settingsModel, extract: (d) => { setTimeout(() => apply(d), 0); return d.map; } });
  $$("[data-m]").forEach((el) => {
    const f = el.dataset.m;
    sb.bind(el, f, { int: el.type === "number" || f === "encounter_id", nullable: f === "encounter_id" });
    if (el.type === "color") el.addEventListener("input", () => { S.map[f] = el.value; view.setData(S.map, S.tokens); });
    if (el.type === "number" && ["cell_px", "offset_x", "offset_y", "grid_opacity"].includes(f)) el.addEventListener("input", () => {
      const v = Number(el.value); if (Number.isFinite(v)) { S.map[f] = v; view.draw(); }
    });
  });
  function syncSettings() { sb.refresh(Object.fromEntries(Object.keys(settingsModel).map((k) => [k, S.map[k]]))); }

  $("#map-image").addEventListener("change", async (e) => {
    const file = e.target.files[0]; if (!file) return;
    const fd = new FormData(); fd.append("file", file);
    try { apply(await api("POST", "/api/maps/" + MID + "/image", fd)); view.fitted = false; location.reload(); }
    catch (err) { toast(err.message, "error"); }
  });
  const clr = $("#clear-image");
  if (clr) armed(clr, () => run("DELETE", "/api/maps/" + MID + "/image", {}, () => location.reload()), "Remove the image?");
  ["#delete-map", "#delete-map-top"].forEach((sel) => armed($(sel), () => act("DELETE", "/api/maps/" + MID, {}, () => { location.href = "/map"; }), "Delete this map for good?"));

  // ---- stay in sync with players moving tokens and the combat screen -------------------------
  async function refresh(force) {
    if (!force && (Save.busy() || view.drag || document.hidden)) return;
    try {
      if (!force) {
        const r = await api("GET", "/api/maps/" + MID + "/rev");
        if (r.rev === revs.rev && r.encounter_rev === revs.encounter_rev && r.ping === revs.ping) return;
        revs.ping = r.ping;
      }
      const d = await api("GET", "/api/maps/" + MID);
      revs = { rev: d.map.rev, encounter_rev: d.encounter ? d.encounter.rev : null, ping: revs.ping };
      const fresh = (d.pings || []).filter((p) => !view.seenPings.has(p.id) && p.by !== "DM");
      apply(d);
      if (fresh.length && window.FX) FX.sound("ping");
    } catch (e) { /* offline */ }
  }
  setInterval(refresh, 1500);

  // Dice can tumble across the map (an overlay canvas that never touches map data).
  if (window.Dice) { Dice.overlayHost = $("#stage"); $(".dd-overmap").hidden = false; }
  apply(S);
  if (new URLSearchParams(location.search).has("new")) {
    toast("Made a battle map for “" + (S.encounter ? S.encounter.name : S.map.name) + "”. The party is on the left edge and enemies on the right; drag them into place.", "ok", { ms: 9000 });
    history.replaceState(null, "", location.pathname);
  }
})();
