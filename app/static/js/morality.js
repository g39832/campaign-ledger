/* Morality page: alignment chart with the character's path, axis meters,
   the deed form and the ledger. Scores always come from the server, which
   recomputes them from the full event history after every change. */
(function () {
  "use strict";
  const { h, icon, $, $$, signed, boot, act, toast, armed, fmtDate } = L;
  let M = boot("boot");
  const CID = M.character.id;
  const PRESET_TAGS = ["mercy", "justice", "loyalty", "sacrifice", "honesty", "courage", "betrayal", "cruelty", "greed", "rebellion", "deception", "cowardice"];
  const NS = "http://www.w3.org/2000/svg";
  const s = (tag, attrs, ...kids) => {
    const el = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs || {})) if (v !== null && v !== undefined) el.setAttribute(k, v);
    kids.flat().forEach((k) => k != null && el.append(k instanceof Node ? k : document.createTextNode(k)));
    return el;
  };

  function apply(state) {
    const change = state.alignment_change;
    M = state;
    render();
    if (change) toast(`${M.character.name}'s alignment changed: ${change.from || "unset"} → ${change.to}`, "ok", { ms: 8000 });
  }
  function run(method, url, body) { return act(method, url, body, apply); }

  // ---- chart --------------------------------------------------------------------
  function renderChart() {
    const svg = $("#chart");
    const { scale, law_threshold: lt, good_threshold: gt } = M.config;
    const P = 34, W = 400 - P * 2;
    const x = (law) => P + ((scale - law) / (2 * scale)) * W;       // lawful on the left
    const y = (good) => P + ((scale - good) / (2 * scale)) * W;     // good at the top
    const kids = [s("title", { id: "chart-title" }, "Alignment chart: " + M.character.name + " is " + M.computed_alignment + " by score")];
    const cols = [[scale, lt, "Lawful"], [lt, -lt, "Neutral"], [-lt, -scale, "Chaotic"]];
    const rows = [[scale, gt, "Good"], [gt, -gt, "Neutral"], [-gt, -scale, "Evil"]];
    const cur = M.computed_alignment;
    rows.forEach(([g1, g2, gl]) => cols.forEach(([l1, l2, ll]) => {
      const name = ll === "Neutral" && gl === "Neutral" ? "True Neutral" : ll + " " + gl;
      const on = name === cur;
      const shown = M.character.alignment === name && !M.character.auto_alignment;
      kids.push(s("rect", { x: x(l1), y: y(g1), width: x(l2) - x(l1), height: y(g2) - y(g1),
        fill: on ? "var(--brass-soft)" : "transparent", stroke: shown ? "var(--accent)" : "var(--line)", "stroke-width": shown ? 2 : 1 }));
      kids.push(s("text", { x: (x(l1) + x(l2)) / 2, y: y(g1) + 15, "text-anchor": "middle", "font-size": 11,
        fill: on ? "var(--text)" : "var(--text-3)", "font-weight": on ? 700 : 500 }, name === "True Neutral" ? "True Neutral" : name));
    }));
    kids.push(s("rect", { x: P, y: P, width: W, height: W, fill: "none", stroke: "var(--line-strong)" }));
    kids.push(s("text", { x: P, y: P - 12, "font-size": 12, fill: "var(--law)" }, "← Lawful"));
    kids.push(s("text", { x: P + W, y: P - 12, "font-size": 12, fill: "var(--chaos)", "text-anchor": "end" }, "Chaotic →"));
    kids.push(s("text", { x: 14, y: P + 4, "font-size": 12, fill: "var(--good)", transform: `rotate(-90 14 ${P + 4})`, "text-anchor": "end" }, "Good ↑"));
    kids.push(s("text", { x: 14, y: P + W, "font-size": 12, fill: "var(--evil)", transform: `rotate(-90 14 ${P + W})` }, "↓ Evil"));
    const pts = M.timeline;
    if (pts.length > 1) {
      kids.push(s("polyline", { points: pts.map((p) => x(p.plot_law) + "," + y(p.plot_good)).join(" "), fill: "none",
        stroke: "var(--brass)", "stroke-width": 1.75, "stroke-linejoin": "round", opacity: .75 }));
    }
    const evById = Object.fromEntries(M.events.map((e) => [e.id, e]));
    pts.forEach((p, i) => {
      const last = i === pts.length - 1;
      const label = p.event_id ? evById[p.event_id].title : "Starting point";
      const g = s("g", null, s("title", null, `${label} — law ${signed(p.law)}, good ${signed(p.good)} (${p.alignment})`),
        s("circle", { cx: x(p.plot_law), cy: y(p.plot_good), r: last ? 7 : 3.5,
          fill: last ? "var(--accent)" : i === 0 ? "var(--surface)" : "var(--brass)", stroke: last ? "var(--surface)" : "var(--brass)", "stroke-width": last ? 2.5 : 1.25 }));
      kids.push(g);
    });
    svg.replaceChildren(...kids);
  }

  function meter(label, val, t, scale, left, right, colorL, colorR) {
    const pos = (v) => ((scale - Math.max(-scale, Math.min(scale, v))) / (2 * scale)) * 100;
    return h("div", null,
      h("div", { class: "meter" },
        h("span", { style: "color:" + colorL }, left),
        h("div", { class: "track" },
          h("span", { class: "zone", style: `left:${pos(t)}%;width:${pos(-t) - pos(t)}%` }),
          h("span", { class: "mark", style: `left:${pos(val)}%` })),
        h("span", { class: "end-r", style: "color:" + colorR }, right)),
      h("div", { class: "meter-val" }, label + " " + signed(val) + (Math.abs(val) > scale ? " (beyond the scale)" : "")));
  }

  // ---- form -----------------------------------------------------------------------
  function impactInput(name, value, aria) {
    const inp = h("input", { type: "number", name, value: value || 0, min: -1000, max: 1000, "aria-label": aria });
    const step = (d) => { inp.value = (Number(inp.value) || 0) + d; inp.dispatchEvent(new Event("input", { bubbles: true })); };
    return h("div", { class: "impact" },
      h("button", { type: "button", class: "icon-btn", "aria-label": "Less", onclick: () => step(-5) }, icon("minus", "sm")),
      inp,
      h("button", { type: "button", class: "icon-btn", "aria-label": "More", onclick: () => step(5) }, icon("plus", "sm")));
  }
  function tagPicker(selected) {
    const chosen = new Set(selected || []);
    const wrap = h("div", { class: "tag-picks" });
    const custom = h("input", { type: "text", placeholder: "Other tag", style: "width:12ch;min-height:30px;padding:3px 7px", "aria-label": "Custom tag",
      onkeydown: (e) => { if (e.key === "Enter") { e.preventDefault(); const v = custom.value.trim().toLowerCase(); if (v) { chosen.add(v); custom.value = ""; draw(); } } } });
    function draw() {
      const all = Array.from(new Set(PRESET_TAGS.concat(Array.from(chosen))));
      wrap.replaceChildren(...all.map((t) => h("button", { type: "button", class: chosen.has(t) ? "is-on" : "", "aria-pressed": chosen.has(t),
        onclick: () => { chosen.has(t) ? chosen.delete(t) : chosen.add(t); draw(); } }, t)), custom);
    }
    draw();
    wrap.value = () => Array.from(chosen);
    return wrap;
  }
  function deedFields(form, ev) {
    ev = ev || {};
    const tags = tagPicker(ev.tags);
    const preview = h("div", { class: "full faint", style: "font-size:.9rem" });
    form.replaceChildren(
      h("label", { class: "field span2" }, h("span", null, "What happened"), h("input", { type: "text", name: "title", required: true, maxlength: 300, value: ev.title || "", placeholder: "Spared the captured assassin" })),
      h("label", { class: "field" }, h("span", null, "Session"), h("input", { type: "text", name: "session_label", maxlength: 100, value: ev.session_label || "", placeholder: "Session 12" })),
      h("label", { class: "field" }, h("span", null, "Date"), h("input", { type: "date", name: "occurred_on", value: ev.occurred_on || "" })),
      h("div", { class: "field span2" }, h("span", null, "Law ↔ Chaos impact"), impactInput("law_delta", ev.law_delta, "Lawfulness impact"),
        h("span", { class: "faint", style: "font-family:var(--sans);letter-spacing:0;font-size:.8rem" }, "positive = lawful, negative = chaotic")),
      h("div", { class: "field span2" }, h("span", null, "Good ↔ Evil impact"), impactInput("good_delta", ev.good_delta, "Goodness impact"),
        h("span", { class: "faint", style: "font-family:var(--sans);letter-spacing:0;font-size:.8rem" }, "positive = good, negative = evil")),
      h("div", { class: "field full" }, h("span", null, "Tags"), tags),
      h("label", { class: "field full" }, h("span", null, "Description"), h("textarea", { name: "description", rows: 2, class: "prose" }, ev.description || "")),
      h("label", { class: "field full" }, h("span", null, "DM commentary (optional)"), h("textarea", { name: "dm_notes", rows: 2 }, ev.dm_notes || "")),
      preview);
    const calc = () => {
      const dl = Number(form.law_delta.value) || 0, dg = Number(form.good_delta.value) || 0;
      const law = M.law + dl - (ev.law_delta || 0), good = M.good + dg - (ev.good_delta || 0);
      const al = alignmentFor(law, good);
      preview.textContent = `${ev.id ? "After this edit" : "After this deed"}: law ${signed(law)}, good ${signed(good)} — ${al}${al !== M.computed_alignment ? " (shift from " + M.computed_alignment + ")" : ""}.`;
    };
    form.addEventListener("input", calc);
    calc();
    return () => ({
      title: form.title.value.trim(), session_label: form.session_label.value.trim(), occurred_on: form.occurred_on.value,
      law_delta: Number(form.law_delta.value) || 0, good_delta: Number(form.good_delta.value) || 0,
      tags: tags.value(), description: form.description.value, dm_notes: form.dm_notes.value,
    });
  }
  function alignmentFor(law, good) {
    const { law_threshold: lt, good_threshold: gt } = M.config;
    const l = law >= lt ? "Lawful" : law <= -lt ? "Chaotic" : "Neutral";
    const g = good >= gt ? "Good" : good <= -gt ? "Evil" : "Neutral";
    return l === "Neutral" && g === "Neutral" ? "True Neutral" : l + " " + g;
  }
  const form = $("#deed-form");
  let readForm;
  function resetForm() {
    readForm = deedFields(form);
    form.append(h("div", { class: "full row", style: "justify-content:flex-end" }, h("button", { type: "submit", class: "btn btn-primary" }, icon("feather", "sm"), " Record deed")));
  }
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const data = readForm();
    if (!data.title) { form.title.focus(); return; }
    act("POST", "/api/characters/" + CID + "/morality", data, (d) => { apply(d); resetForm(); });
  });

  // ---- ledger ---------------------------------------------------------------------
  function deltaSpan(v, pos, neg, cls1, cls2) {
    if (!v) return null;
    return h("span", { class: "delta " + (v > 0 ? cls1 : cls2) }, signed(v) + " " + (v > 0 ? pos : neg));
  }
  function renderLedger() {
    const ol = $("#deeds");
    const reversed = new Set(M.events.filter((e) => e.reverses_id).map((e) => e.reverses_id));
    const points = Object.fromEntries(M.timeline.filter((p) => p.event_id).map((p, i) => [p.event_id, { p, prev: M.timeline[i] }]));
    const items = [];
    M.events.slice().reverse().forEach((ev) => {
      const { p, prev } = points[ev.id];
      if (p.alignment !== prev.alignment) items.push(h("li", { class: "shift" }, "Became " + p.alignment));
      const li = h("li", { class: "deed" + (ev.reverses_id ? " is-reversal" : "") + (reversed.has(ev.id) ? " is-reversed" : "") });
      const del = h("button", { type: "button", class: "btn btn-sm btn-quiet btn-danger" }, icon("trash-2", "sm"), " Delete");
      armed(del, () => run("DELETE", "/api/morality/" + ev.id), "Delete this deed?");
      li.append(
        h("div", { class: "when" }, h("b", null, ev.session_label || "—"), ev.occurred_on ? fmtDate(ev.occurred_on) : ""),
        h("div", null,
          h("h4", null, ev.title),
          ev.description ? h("div", { class: "desc" }, ev.description) : null,
          ev.dm_notes ? h("div", { class: "dm" }, ev.dm_notes) : null,
          ev.tags.length ? h("div", { class: "c-conds", style: "margin-top:6px" }, ev.tags.map((t) => h("span", { class: "tag" }, t))) : null),
        h("div", { class: "impacts" },
          deltaSpan(ev.law_delta, "Lawful", "Chaotic", "law", "chaos"),
          deltaSpan(ev.good_delta, "Good", "Evil", "good", "evil"),
          !ev.law_delta && !ev.good_delta ? h("span", { class: "delta zero" }, "No shift") : null,
          h("span", { class: "running" }, "law " + signed(p.law) + " · good " + signed(p.good))),
        h("div", { class: "acts" },
          h("button", { type: "button", class: "btn btn-sm btn-quiet", onclick: () => editDeed(li, ev) }, icon("pencil", "sm"), " Edit"),
          !ev.reverses_id && !reversed.has(ev.id) ? h("button", { type: "button", class: "btn btn-sm btn-quiet", title: "Adds an offsetting entry and keeps this one in the history",
            onclick: () => run("POST", "/api/morality/" + ev.id + "/reverse") }, icon("rotate-ccw", "sm"), " Reverse") : null,
          reversed.has(ev.id) ? h("span", { class: "faint", style: "font-size:.85rem" }, "Reversed later") : null,
          del));
      items.push(li);
    });
    const start = M.timeline[0];
    items.push(h("li", { class: "deed" }, h("div", { class: "when" }, h("b", null, "Start")), h("div", null, h("h4", { class: "muted" }, "Starting point"),
      h("div", { class: "desc" }, start.alignment)), h("div", { class: "impacts" }, h("span", { class: "running" }, "law " + signed(start.law) + " · good " + signed(start.good)))));
    ol.replaceChildren(...items);
    $("#ledger-count").textContent = M.events.length + " event" + (M.events.length === 1 ? "" : "s");
  }
  function editDeed(li, ev) {
    const f = h("form", { class: "deed-form deed-edit panel panel-pad" });
    const read = deedFields(f, ev);
    f.append(h("div", { class: "full row", style: "justify-content:flex-end" },
      h("button", { type: "button", class: "btn btn-sm", onclick: () => renderLedger() }, "Cancel"),
      h("button", { type: "submit", class: "btn btn-sm btn-primary" }, "Save changes")));
    f.addEventListener("submit", (e) => {
      e.preventDefault();
      const data = read();
      if (!data.title) return;
      const changes = {};
      for (const [k, v] of Object.entries(data)) if (JSON.stringify(v) !== JSON.stringify(ev[k])) changes[k] = { from: ev[k], to: v };
      if (!Object.keys(changes).length) { renderLedger(); return; }
      act("PATCH", "/api/morality/" + ev.id, { changes }, apply, { onError: (err) => { toast(err.message, "error"); if (err.status === 409) location.reload(); } });
    });
    li.append(f);
    f.title.focus();
  }

  // ---- settings -------------------------------------------------------------------
  const autoEl = $("#auto-align"), manEl = $("#manual-align");
  autoEl.addEventListener("change", () => run("POST", "/api/characters/" + CID + "/morality/settings", { auto_alignment: autoEl.checked }));
  manEl.addEventListener("change", () => run("POST", "/api/characters/" + CID + "/morality/settings", { alignment: manEl.value }));
  ["law", "good"].forEach((ax) => $("#" + ax + "-start").addEventListener("change", (e) => {
    const v = Number(e.target.value);
    if (!Number.isInteger(v)) return;
    run("POST", "/api/characters/" + CID + "/morality/settings", { [ax + "_start"]: v });
  }));

  // ---- Saints & Sinners: a -100..+100 score moved one point at a time ----
  function renderSaintsSinners() {
    const ss = M.saints_sinners;
    const box = $("#saints-sinners");
    box.dataset.side = ss.side;
    $("#ss-score").textContent = ss.score > 0 ? "+" + ss.score : ss.score < 0 ? "−" + Math.abs(ss.score) : "0";
    $("#ss-title").textContent = ss.title;
    $("#ss-desc").textContent = ss.description;
    $("#ss-side").textContent = ss.side === "saint" ? "Saintly side" : ss.side === "sinner" ? "Sinful side" : "Neither side yet";
    const fill = $("#ss-fill"), pct = Math.abs(ss.score) / 2; // half the bar per side
    fill.style.left = ss.score >= 0 ? "50%" : (50 - pct) + "%";
    fill.style.width = pct + "%";
    $("#ss-down").disabled = ss.score <= -100;
    $("#ss-up").disabled = ss.score >= 100;
  }
  [["#ss-up", 1], ["#ss-down", -1]].forEach(([sel, step]) => $(sel).addEventListener("click", () =>
    act("POST", "/api/characters/" + CID + "/saints-sinners", { step }, (d) => {
      M.saints_sinners = d.saints_sinners;
      renderSaintsSinners();
    })));

  function render() {
    renderSaintsSinners();
    const c = M.character;
    $("#align-name").textContent = c.alignment || "Unset";
    const note = $("#align-note");
    if (!c.auto_alignment && c.alignment !== M.computed_alignment) note.textContent = "Set by hand. The scores currently point to " + M.computed_alignment + ".";
    else if (c.auto_alignment) note.textContent = "Follows the scores automatically.";
    else note.textContent = "Set by hand.";
    autoEl.checked = c.auto_alignment;
    manEl.value = c.alignment;
    manEl.disabled = c.auto_alignment;
    $("#manual-row").style.opacity = c.auto_alignment ? .55 : 1;
    if (document.activeElement !== $("#law-start")) $("#law-start").value = c.law_start;
    if (document.activeElement !== $("#good-start")) $("#good-start").value = c.good_start;
    const { scale, law_threshold: lt, good_threshold: gt } = M.config;
    $("#scale-explainer").textContent = `Scores run from −${scale} to +${scale} with 0 as neutral. Law of +${lt} or more is Lawful, −${lt} or less is Chaotic; good of +${gt} or more is Good, −${gt} or less is Evil. Totals are the starting score plus every recorded impact, so editing or deleting a deed changes them by exactly that deed's amount. Adjust the scale and thresholds in Settings.`;
    $("#meters").replaceChildren(
      meter("Law", M.law, lt, scale, "Lawful", "Chaotic", "var(--law)", "var(--chaos)"),
      meter("Good", M.good, gt, scale, "Good", "Evil", "var(--good)", "var(--evil)"));
    renderChart();
    renderLedger();
  }

  resetForm();
  render();
})();
