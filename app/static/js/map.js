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
    onSelect: (t) => { selectedToken = t ? t.id : null; renderSelected(); renderTokens(); },
    onMove: (t, x, y) => run("POST", "/api/tokens/" + t.id + "/move", { x, y }),
    onBrush: (tool, cells) => {
      if (tool === "paint") run("POST", "/api/maps/" + MID + "/terrain", { cells, value: terrainKind === "erase" ? null : terrainKind });
      else run("POST", "/api/maps/" + MID + "/fog", { cells, reveal: tool === "reveal" });
    },
    onPlace: (x, y) => run("POST", "/api/maps/" + MID + "/tokens", { kind: "marker", label: "Marker", x, y, hidden: true },
      () => toast("Marker placed (hidden from players). Rename it or change it to a trap on the right.", "ok")),
    canEditShapes: true,
    onPing: (x, y) => { api("POST", "/api/maps/" + MID + "/ping", { x, y }).then((d) => view.setPings(d.pings)).catch((e) => toast(e.message, "error")); if (window.FX) FX.sound("ping"); },
    onArea: (a) => run("POST", "/api/maps/" + MID + "/shapes", { kind: a.kind, x: a.x, y: a.y, size: a.size, width: a.width, dir: a.dir, color: a.color, label: a.label, hidden: a.hidden },
      (d) => { view.selectedShape = d.shape_id; renderAreas(); if (window.FX) FX.sound("hit"); }),
    onShapeMove: (sh, x, y) => run("PATCH", "/api/maps/" + MID + "/shapes/" + sh.id, { x, y }),
    onSelectShape: () => renderAreas(),
  });
  let selectedToken = null;

  function run(method, url, body, after) {
    return act(method, url, body, (d) => { if (d && d.map) apply(d); if (after) after(d); },
      { onError: (err) => { toast(err.message, "error"); refresh(true); } });
  }
  function apply(state) {
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
    $("#tokens").replaceChildren(...(S.tokens.length ? S.tokens.map((t) => h("li", { class: t.id === selectedToken ? "is-sel" : "", onclick: () => { selectedToken = t.id; view.selectedId = t.id; view.draw(); renderSelected(); renderTokens(); } },
      h("span", { class: "swatch", style: "background:" + (t.color || MapView.KIND_COLOR[t.kind]) }),
      h("span", { class: "nm" }, t.display), t.hidden || t.combatant_hidden ? h("span", { class: "faint", title: "Hidden from players" }, icon("eye-off", "sm")) : null,
      h("span", { class: "faint", style: "font-size:.8rem" }, t.kind),
      (t.notes || "").trim() ? h("span", { class: "c-note tok-note", title: t.notes }, icon("scroll-text", "sm"), h("span", null, t.notes.trim())) : null)) : [h("li", { class: "faint" }, "No tokens yet.")]));
  }
  $("#from-enc").addEventListener("click", () => run("POST", "/api/maps/" + MID + "/tokens/from-encounter"));
  $("#add-char").addEventListener("change", (e) => {
    const id = Number(e.target.value); e.target.value = "";
    if (id) run("POST", "/api/maps/" + MID + "/tokens", { character_id: id, x: 0, y: 0 });
  });
  function renderSelected() {
    const box = $("#selected-panel");
    const t = S.tokens.find((x) => x.id === selectedToken);
    box.hidden = !t;
    if (!t) return;
    const patch = (field, to) => run("PATCH", "/api/tokens/" + t.id, { changes: { [field]: { from: t[field], to } } });
    const del = h("button", { type: "button", class: "btn btn-sm btn-quiet btn-danger" }, icon("trash-2", "sm"), " Remove token");
    armed(del, () => run("DELETE", "/api/tokens/" + t.id, {}, () => { selectedToken = null; renderSelected(); }), "Remove from map?");
    box.replaceChildren(
      h("h3", { class: "rule-head" }, "Selected token"),
      h("div", { style: "display:grid;gap:8px" },
        h("div", null, h("b", null, t.display), t.hp != null ? h("span", { class: "faint" }, " · " + t.hp + "/" + t.max_hp + " HP") : null,
          t.combatant_id || t.character_id ? h("div", { class: "faint", style: "font-size:.82rem" }, "HP and conditions come from " + (t.combatant_id ? "the encounter" : "the character sheet") + "; this token only sets position.") : null),
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
