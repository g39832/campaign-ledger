(function () {
  "use strict";
  const { h, $, $$, boot, api, act, toast, Save, fmtDate, fmtTime } = L;
  const CID = window.CAMPAIGN_ID;
  let settings = boot("boot");

  // ---- theme ------------------------------------------------------------------
  function drawTheme() {
    const t = document.documentElement.dataset.theme;
    $$("[data-theme-set]").forEach((b) => { b.classList.toggle("is-on", b.dataset.themeSet === t); b.setAttribute("aria-pressed", b.dataset.themeSet === t); });
  }
  $$("[data-theme-set]").forEach((b) => b.addEventListener("click", () => {
    document.documentElement.dataset.theme = b.dataset.themeSet;
    drawTheme();
    Save.push({ key: "theme", run: () => api("PATCH", "/api/settings", { theme: b.dataset.themeSet }) });
  }));
  $("#theme-toggle").addEventListener("click", () => setTimeout(drawTheme, 0));
  drawTheme();

  // ---- campaign rules -----------------------------------------------------------
  if (CID) {
    const get = (path) => path.split(".").reduce((o, k) => (o || {})[k], settings);
    const put = (path, v) => { const [a, b] = path.split("."); settings[a] = Object.assign({}, settings[a], { [b]: v }); };
    function save() {
      const snapshot = JSON.parse(JSON.stringify(settings));
      Save.push({
        key: "campaign-settings",
        run: async () => { const d = await api("PATCH", "/api/campaigns/" + CID, { changes: { settings: { to: snapshot } } }); settings = d.campaign.settings; },
        fail: (err) => { toast(err.message, "error"); location.reload(); },
      });
    }
    $$("[data-set]").forEach((el) => {
      const path = el.dataset.set;
      if (el.type === "checkbox") el.checked = !!get(path); else el.value = get(path);
      el.addEventListener("change", () => {
        let v = el.type === "checkbox" ? el.checked : el.type === "number" ? Number(el.value) : el.value;
        if (el.type === "number" && (!Number.isInteger(v) || v < 1)) { el.setAttribute("aria-invalid", "true"); toast("Use a whole number of 1 or more.", "error"); return; }
        el.removeAttribute("aria-invalid");
        put(path, v); save();
      });
    });
    const skip = new Set(get("combat.skip_statuses") || []);
    $$("#skip-set input").forEach((cb) => {
      cb.checked = skip.has(cb.value);
      cb.addEventListener("change", () => { put("combat.skip_statuses", $$("#skip-set input").filter((x) => x.checked).map((x) => x.value)); save(); });
    });
  }

  // ---- snapshots ------------------------------------------------------------------
  async function loadSnapshots() {
    try {
      const d = await api("GET", "/api/backup/snapshots");
      $("#snapshots").replaceChildren(
        h("div", { style: "font-size:.9rem;margin-bottom:6px" }, "Folder: ", h("code", null, d.folder)),
        d.snapshots.length ? h("table", { class: "ledger" }, h("tbody", null, d.snapshots.slice(0, 12).map((s) => h("tr", null,
          h("td", null, h("code", null, s.name)), h("td", { class: "r nowrap" }, fmtDate(s.modified) + " " + fmtTime(s.modified)), h("td", { class: "r nowrap" }, Math.round(s.size / 1024) + " KB"))))) :
          h("p", null, "No snapshots yet."));
    } catch (e) { $("#snapshots").textContent = e.message; }
  }
  loadSnapshots();

  // ---- import -----------------------------------------------------------------------
  const report = $("#import-report");
  $("#import-file").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    e.target.value = "";
    if (!file) return;
    report.replaceChildren(h("p", { class: "faint" }, "Checking " + file.name + "…"));
    const fd = new FormData(); fd.append("file", file);
    let r;
    try { r = await api("POST", "/api/backup/inspect", fd); }
    catch (err) {
      report.replaceChildren(h("div", { class: "err-box" }, h("b", null, "Can't import this file. "), err.message,
        err.data && err.data.details ? h("ul", null, err.data.details.map((d) => h("li", null, d))) : null));
      return;
    }
    showReport(file.name, r);
  });

  function showReport(name, r) {
    const choices = {};
    const rows = r.campaigns.map((c) => {
      const opts = c.exists
        ? [["replace", "Replace the existing “" + c.local_name + "” with the backup"], ["copy", "Import as a separate copy"], ["skip", "Skip"]]
        : [["add", "Import"], ["skip", "Skip"]];
      choices[c.uid] = c.exists ? "skip" : "add";
      const sel = h("select", { style: "width:auto", onchange: (e) => { choices[c.uid] = e.target.value; warn(); } },
        opts.map(([v, l]) => h("option", { value: v, selected: v === choices[c.uid] }, l)));
      const cnt = c.counts;
      return h("div", { class: "camp" },
        h("div", null, h("b", null, c.name), c.archived ? h("span", { class: "faint" }, " (archived)") : null,
          h("div", { class: "faint", style: "font-size:.88rem" }, `${cnt.characters} characters · ${cnt.morality_events} morality events · ${cnt.encounters} encounters · ${cnt.journal} journal entries`),
          c.exists ? h("div", { style: "font-size:.88rem;color:var(--hp-mid)" }, "Already exists here as “" + c.local_name + "”.") : null),
        sel);
    });
    const warnBox = h("div");
    function warn() {
      const replacing = r.campaigns.filter((c) => choices[c.uid] === "replace");
      warnBox.replaceChildren(...(replacing.length ? [h("div", { class: "warn-box" }, h("b", null, "Replacing: "),
        replacing.map((c) => "“" + c.local_name + "”").join(", "),
        ". Everything currently in " + (replacing.length > 1 ? "those campaigns" : "that campaign") + " will be swapped for the backup's version. A database snapshot is taken first, so this can be undone by restoring it.")] : []));
    }
    warn();
    const go = h("button", { type: "button", class: "btn btn-primary" }, "Import selected");
    go.addEventListener("click", () => {
      go.disabled = true;
      act("POST", "/api/backup/import", { token: r.token, decisions: choices }, (d) => {
        report.replaceChildren(h("div", { class: "warn-box", style: "border-color:var(--ok)" },
          h("b", null, "Imported. "), d.imported.map((i) => i.name + " (" + i.mode + ")").join(", ") || "Creature library only",
          ". Safety snapshot saved as ", h("code", null, d.snapshot), ".",
          h("div", { style: "margin-top:6px" }, h("a", { href: "/campaigns" }, "Go to campaigns"))));
        loadSnapshots();
      }, { onError: (err) => { go.disabled = false; toast(err.message, "error"); } });
    });
    report.replaceChildren(
      h("div", { style: "margin:8px 0" }, h("b", null, name), h("span", { class: "faint" }, " · exported " + fmtDate(r.exported_at) + " · checksum verified")),
      ...r.warnings.map((w) => h("div", { class: "warn-box" }, w)),
      ...rows,
      r.library_total ? h("p", { class: "faint", style: "font-size:.9rem;margin-top:8px" }, `${r.library_new} of ${r.library_total} library creatures are new and will be added; ones you already have are left alone.`) : null,
      warnBox,
      h("div", { class: "row", style: "margin-top:10px" }, go, h("button", { type: "button", class: "btn btn-quiet", onclick: () => report.replaceChildren() }, "Cancel")));
  }
})();
