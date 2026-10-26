(function () {
  "use strict";
  const { h, icon, $, $$, boot, Binder, act, api, toast, armed, debounce, fmtDate } = L;
  const CID = window.CAMPAIGN_ID;
  let entries = boot("boot-entries");
  const linkables = boot("boot-links");
  const KINDS = {
    session: "Session", npc: "NPC", location: "Location", quest: "Quest", faction: "Faction", discovery: "Discovery",
    decision: "Player decision", mystery: "Mystery", hook: "Plot hook", loot: "Loot & rewards", note: "Note",
  };
  const STATUSES = {
    quest: ["active", "on hold", "completed", "failed"], mystery: ["unresolved", "solved"], hook: ["open", "used", "dropped"],
    npc: ["alive", "dead", "missing", "unknown"], faction: ["ally", "neutral", "hostile", "unknown"],
    loot: ["unclaimed", "claimed", "sold"], location: ["unexplored", "visited", "cleared"],
  };
  const LINK_LABEL = { character: "Character", encounter: "Encounter", morality: "Morality event" };
  let kind = "", q = "", current = null, binder = null;

  const params = new URLSearchParams(location.search);
  current = Number(params.get("entry")) || (entries[0] && entries[0].id) || null;

  // ---- side list ------------------------------------------------------------------
  $("#kinds").replaceChildren(...[["", "All"], ...Object.entries(KINDS)].map(([k, label]) =>
    h("button", { type: "button", "data-kind": k, class: k === kind ? "is-on" : "", onclick: () => { kind = k; load(); } }, label)));
  const newSel = $("#new-kind");
  Object.entries(KINDS).forEach(([k, label]) => newSel.append(h("option", { value: k }, label)));
  newSel.addEventListener("change", () => { if (newSel.value) create(newSel.value); newSel.value = ""; });
  $("[data-new='session']").addEventListener("click", () => create("session"));

  function create(k) {
    const body = { kind: k };
    if (k === "session") body.session_date = new Date().toISOString().slice(0, 10);
    else body.title = "New " + KINDS[k].toLowerCase();
    if (STATUSES[k]) body.status = STATUSES[k][0];
    act("POST", "/api/campaigns/" + CID + "/journal", body, (d) => {
      entries.unshift(d.entry);
      kind = ""; q = ""; $("#q").value = "";
      open(d.entry.id);
      renderList();
      const t = $("#editor .j-title");
      if (t) { t.focus(); t.select(); }
    });
  }

  const load = debounce(async () => {
    $$("#kinds button").forEach((b) => b.classList.toggle("is-on", b.dataset.kind === kind));
    try {
      const d = await api("GET", "/api/campaigns/" + CID + "/journal?q=" + encodeURIComponent(q) + "&kind=" + encodeURIComponent(kind));
      entries = d.entries;
      renderList();
    } catch (e) { toast(e.message, "error"); }
  }, 200);
  $("#q").addEventListener("input", (e) => { q = e.target.value.trim(); load(); });

  function snippet(e) {
    if (!q) return null;
    const words = q.toLowerCase().split(/\s+/).filter(Boolean);
    const body = e.body || "";
    const low = body.toLowerCase();
    const i = Math.min(...words.map((w) => { const j = low.indexOf(w); return j < 0 ? Infinity : j; }));
    if (!Number.isFinite(i)) return null;
    const start = Math.max(0, i - 40), text = (start ? "…" : "") + body.slice(start, i + 80).replace(/\s+/g, " ") + "…";
    const frag = h("span", { class: "faint", style: "font-size:.85rem" });
    const re = new RegExp("(" + words.map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|") + ")", "ig");
    text.split(re).forEach((part, k) => frag.append(k % 2 ? h("mark", null, part) : part));
    return frag;
  }
  function renderList() {
    const ul = $("#list");
    if (!entries.length) {
      ul.replaceChildren(h("li", { class: "faint", style: "padding:14px" }, q || kind ? "Nothing matches." : "The journal is empty. Start with a session note."));
      return;
    }
    ul.replaceChildren(...entries.map((e) => h("li", null, h("button", { type: "button", class: e.id === current ? "is-on" : "", onclick: () => open(e.id) },
      h("span", { class: "kind" }, KINDS[e.kind] + (e.pinned ? " · pinned" : "")),
      h("span", { class: "t" }, e.title || "Untitled"),
      h("span", { class: "m" }, e.kind === "session" && e.session_date ? fmtDate(e.session_date) : null, e.status ? h("span", null, e.status) : null),
      snippet(e)))));
  }

  // ---- editor ---------------------------------------------------------------------
  async function open(id) {
    Binder.flushAll();
    current = id;
    history.replaceState(null, "", "/journal" + (id ? "?entry=" + id : ""));
    renderList();
    if (!id) return renderEditor(null);
    let e = entries.find((x) => x.id === id);
    try { e = (await api("GET", "/api/journal/" + id)).entry; }
    catch (err) { if (err.status === 404) { current = null; return renderEditor(null); } }
    renderEditor(e);
  }
  function syncListItem(rec) {
    const i = entries.findIndex((x) => x.id === rec.id);
    if (i >= 0) { entries[i] = Object.assign({}, entries[i], rec); renderList(); }
  }
  function renderEditor(e) {
    const box = $("#editor");
    if (!e) {
      box.replaceChildren(h("div", { class: "empty", style: "margin-top:30px" }, h("h3", null, "Nothing selected"), "Pick an entry on the left, or start a new one."));
      return;
    }
    const model = { title: e.title, kind: e.kind, session_number: e.session_number, session_date: e.session_date, status: e.status, tags: e.tags, pinned: e.pinned, body: e.body };
    binder = new Binder({ url: "/api/journal/" + e.id, model, onSaved: syncListItem, onRemote: () => {} });
    const title = L.wrapText({ class: "input j-title", "aria-label": "Title", maxlength: 300 });
    const kindSel = h("select", { style: "width:auto" }, Object.entries(KINDS).map(([k, l]) => h("option", { value: k }, l)));
    const num = h("input", { type: "number", min: 0, style: "width:8ch" });
    const date = h("input", { type: "date" });
    const status = h("input", { type: "text", list: "status-opts", style: "width:16ch", placeholder: "—" });
    const statusList = h("datalist", { id: "status-opts" });
    const tags = L.wrapText({ placeholder: "comma, separated", "aria-label": "Tags", style: "min-width:24ch;max-width:100%" });
    const pinned = h("input", { type: "checkbox" });
    const body = h("textarea", { class: "j-body", placeholder: e.kind === "session" ? "What happened this session? Who did they meet, what did they decide, what's still unresolved?" : "Write it down…" });
    binder.bind(title, "title");
    binder.bind(kindSel, "kind", { onInput: () => layout() });
    binder.bind(num, "session_number", { nullable: true });
    binder.bind(date, "session_date");
    binder.bind(status, "status");
    binder.bind(pinned, "pinned");
    binder.bind(body, "body");
    tags.value = (e.tags || []).join(", ");
    tags.addEventListener("input", () => binder.set("tags", tags.value.split(",").map((t) => t.trim()).filter(Boolean)));
    binder.inputs.set("tags", tags);

    const sessionFields = [h("label", { class: "field" }, h("span", null, "Session no."), num), h("label", { class: "field" }, h("span", null, "Played on"), date)];
    const statusField = h("label", { class: "field" }, h("span", null, "Status"), status, statusList);
    function layout() {
      const k = binder.model.kind;
      sessionFields.forEach((f) => { f.hidden = k !== "session"; });
      statusList.replaceChildren(...(STATUSES[k] || []).map((s) => h("option", { value: s })));
      statusField.hidden = k === "session";
    }
    layout();

    const links = h("div", { class: "chip-pick" });
    let current = e.links || [];
    function drawLinks() {
      const add = h("select", { style: "width:auto;min-height:30px;padding:3px 26px 3px 8px", "aria-label": "Link to" },
        h("option", { value: "" }, "Link to…"),
        Object.entries(linkables).map(([type, items]) => items.length ? h("optgroup", { label: LINK_LABEL[type] },
          items.filter((it) => !current.some((l) => l.type === type && l.id === it.id)).map((it) => h("option", { value: type + ":" + it.id }, it.label))) : null));
      add.addEventListener("change", () => {
        if (!add.value) return;
        const [type, id] = add.value.split(":");
        saveLinks(current.concat([{ type, id: Number(id) }]));
      });
      links.replaceChildren(...current.map((l) => h("span", { class: "tag" },
        h("span", { class: "faint" }, LINK_LABEL[l.type] + ":"),
        h("a", { href: l.type === "character" ? "/characters/" + l.id : l.type === "encounter" ? "/combat/" + l.id : "#", style: "text-decoration:none" }, l.label || "#" + l.id),
        h("button", { type: "button", "aria-label": "Remove link", onclick: () => saveLinks(current.filter((x) => !(x.type === l.type && x.id === l.id))) }, icon("x", "sm")))), add);
    }
    function saveLinks(next) {
      act("PUT", "/api/journal/" + e.id + "/links", { links: next.map((l) => ({ type: l.type, id: l.id })) }, (d) => { current = d.entry.links; drawLinks(); });
    }
    drawLinks();

    const del = h("button", { type: "button", class: "btn btn-sm btn-quiet btn-danger" }, icon("trash-2", "sm"), " Delete entry");
    armed(del, () => act("DELETE", "/api/journal/" + e.id, {}, () => {
      entries = entries.filter((x) => x.id !== e.id);
      open(entries[0] ? entries[0].id : null);
    }), "Delete for good? Click again");

    box.replaceChildren(
      h("div", { class: "row", style: "align-items:center;gap:8px;margin-bottom:4px" }, h("span", { class: "kind" }, KINDS[e.kind]), h("span", { class: "grow" }),
        h("label", { class: "check", style: "font-size:.92rem" }, pinned, "Pin to top")),
      title,
      h("div", { class: "j-meta" },
        h("label", { class: "field" }, h("span", null, "Type"), kindSel), ...sessionFields, statusField,
        h("label", { class: "field" }, h("span", null, "Tags"), tags)),
      body,
      h("div", { style: "margin-top:14px" }, h("div", { class: "lbl", style: "margin-bottom:6px" }, "Linked to"), links),
      h("div", { class: "j-foot" }, h("span", null, "Created " + fmtDate(e.created_at) + " · last edited " + fmtDate(e.updated_at)), del));
  }

  renderList();
  open(current);
})();
