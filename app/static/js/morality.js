/* Saints & Sinners: one -100..+100 morality score for the whole party.
   Moved one point at a time with the buttons, or set by typing a number.
   The server keeps it within range and is the source of truth. */
(function () {
  "use strict";
  const { $, boot, act, toast } = L;
  const CID = Number(document.body.dataset.campaign);
  let S = boot("boot");
  const input = $("#ss-score");

  function render() {
    const box = $("#saints-sinners");
    box.dataset.side = S.side;
    if (document.activeElement !== input) input.value = S.score;
    $("#ss-title").textContent = S.title;
    $("#ss-desc").textContent = S.description;
    $("#ss-side").textContent = S.side === "saint" ? "Saintly side" : S.side === "sinner" ? "Sinful side" : "Neither side yet";
    const fill = $("#ss-fill"), pct = Math.abs(S.score) / 2; // half the bar per side
    fill.style.left = S.score >= 0 ? "50%" : (50 - pct) + "%";
    fill.style.width = pct + "%";
    $("#ss-down").disabled = S.score <= -100;
    $("#ss-up").disabled = S.score >= 100;
  }
  function send(body) {
    act("POST", "/api/campaigns/" + CID + "/saints-sinners", body, (d) => { S = d.saints_sinners; input.value = S.score; render(); },
      { onError: (err) => { toast(err.message, "error"); input.value = S.score; } });
  }
  $("#ss-up").addEventListener("click", () => send({ step: 1 }));
  $("#ss-down").addEventListener("click", () => send({ step: -1 }));

  // Typing: saved on Enter or when the box loses focus. Out-of-range numbers are kept within -100..+100.
  function commit() {
    const raw = input.value.trim();
    if (raw === "" || !/^[+-]?\d+$/.test(raw)) { input.value = S.score; if (raw !== "") toast("Type a whole number from -100 to 100.", "error"); return; }
    const n = Number(raw);
    if (n === S.score) { input.value = S.score; return; }
    if (n > 100 || n < -100) toast("Kept within -100 to +100.", null);
    send({ value: n });
  }
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); input.blur(); }
    if (e.key === "Escape") { input.value = S.score; input.blur(); }
  });
  input.addEventListener("blur", commit);

  render();
})();
