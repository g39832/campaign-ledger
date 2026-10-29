"""Dice colors, really clicked: a player picks theirs on their phone, the DM picks a character's on
the sheet, and a roll shows up in the roller's colors on other screens."""
import json, os, re, urllib.request, uuid
from common import APP_DIR, DM_URL, LAN_IP, LAN_URL, SHOTS_DIR, TMP_DIR  # noqa: E402,F401  (paths and addresses for this computer)
from playwright.sync_api import sync_playwright
import engine

DM = DM_URL; LAN = LAN_URL
SHOTS = SHOTS_DIR
results, problems = [], []


def call(m, path, body=None):
    data = json.dumps(dict(body or {}, op_id=uuid.uuid4().hex)).encode() if m != "GET" else None
    return json.load(urllib.request.urlopen(urllib.request.Request(DM + path, data=data, method=m, headers={"Content-Type": "application/json"})))


def check(c, msg):
    results.append((bool(c), msg)); print(("  PASS " if c else "  FAIL ") + msg, flush=True)


for e in call("GET", "/api/campaigns/1/encounters")["encounters"]:  # no fight: Lux's rolls are for everyone
    if e["status"] == "active":
        call("POST", f"/api/encounters/{e['id']}/end")
for pl in call("GET", "/api/campaigns/1/players")["players"]:
    call("DELETE", f"/api/players/{pl['id']}")
chars = {c["name"]: c for c in call("GET", "/api/campaigns/1/characters")["characters"]}
LUX, MONI = chars["Lux Fedelis"]["id"], chars["Moni Easter"]["id"]
call("PATCH", f"/api/characters/{LUX}", {"changes": {"dice_style": {"from": call("GET", f"/api/characters/{LUX}")["character"]["dice_style"], "to": {}}}})  # Lux starts classic (in this copy)
code = call("POST", "/api/campaigns/1/join-code", {"action": "new"})["join_code"]
with sync_playwright() as p:
    b = engine.launch(p)
    ph = b.new_context(viewport={"width": 390, "height": 844}, **engine.mobile(), has_touch=True).new_page()
    ph.on("pageerror", lambda e: problems.append(f"phone JS error: {e}"))
    ph.goto(LAN + "/join"); ph.fill("input[name=code]", code); ph.fill("input[name=name]", "Lux plays")
    ph.wait_for_selector("#char-field:not([hidden])"); ph.select_option("select[name=character_id]", value=str(LUX))
    ph.click("button[type=submit]"); ph.wait_for_url(re.compile("/play")); ph.wait_for_timeout(2000)
    fold = ph.locator("details.dice-fold")
    check(fold.count() == 1 and not fold.evaluate("d => d.open"), "the phone has 'My dice colors', folded away")
    fold.locator("summary").click(); ph.wait_for_timeout(400)
    check(fold.locator(".dc-set").count() == 9 and fold.locator("input[type=color]").count() == 2, "nine color sets and two color pickers")
    fold.locator(".dc-set", has_text="Royal purple").click(); ph.wait_for_timeout(1800)
    check(call("GET", f"/api/characters/{LUX}")["character"]["dice_style"] == {"body": "#4b2a6b", "ink": "#f2e6ff"}, "tapping Royal purple saves Lux's dice")
    fold = ph.locator("details.dice-fold")
    check(fold.evaluate("d => d.open") and fold.locator(".dc-set.is-on", has_text="Royal purple").count() == 1, "it stays open with Royal purple picked")
    fold.scroll_into_view_if_needed(); ph.wait_for_timeout(1300)
    fold.screenshot(path=SHOTS + rf"\dicecolors_phone_{engine.NAME}.png")
    # his own color: the die color picker
    fold.locator("input[aria-label='Die color']").evaluate("(el) => { el.value = '#0f7a6b'; el.dispatchEvent(new Event('change', { bubbles: true })); }")
    ph.wait_for_timeout(1500)
    check(call("GET", f"/api/characters/{LUX}")["character"]["dice_style"]["body"] == "#0f7a6b", "his own die color from the picker")

    # the DM: Moni's sheet
    dm = b.new_page(viewport={"width": 1400, "height": 950}); dm.on("pageerror", lambda e: problems.append(f"DM JS error: {e}"))
    dm.goto(DM + f"/characters/{MONI}"); dm.wait_for_timeout(1200)
    head = dm.locator("[data-fold=dice]")
    if dm.locator("[data-fold-body=dice]").first.is_hidden():
        head.click(); dm.wait_for_timeout(300)
    dm.locator("#dice-colors .dc-set", has_text="Forest").click(); dm.wait_for_timeout(2500)
    check(call("GET", f"/api/characters/{MONI}")["character"]["dice_style"] == {"body": "#2f5d34", "ink": "#f1ecd8"}, "the DM gives Moni Forest dice on her sheet (saved)")
    dm.locator("#dice-colors").screenshot(path=SHOTS + rf"\dicecolors_sheet_{engine.NAME}.png")
    check(not dm.locator(".save-status.is-error, .conflict").count(), "no save problems on the sheet")
    # Lux rolls: the DM's screen draws his dice in his colors
    dm.goto(DM + "/"); dm.wait_for_timeout(1500)
    dm.evaluate("Dice.toggle(true)"); dm.wait_for_timeout(300)  # the DM's dice tray open: other people's rolls play there
    ph.evaluate("window.scrollTo(0, 0)")
    ph.evaluate("Dice.roll({ expression: '2d20', label: 'Perception check', kind: 'custom' })"); ph.wait_for_timeout(500)  # Lux rolls from his dice tray
    dm.wait_for_timeout(3000)
    last = call("GET", "/api/rolls")["rolls"][:1]
    print("    newest roll:", [(r["roller_name"], r["label"], r["visibility"], r.get("dice")) for r in last], "| DM history:", dm.evaluate("Dice.history.length"), "| open:", dm.evaluate("Dice.isOpen()"))
    cur = dm.evaluate("Dice.current && Dice.current.dice")
    check(cur == {"body": "#0f7a6b", "ink": "#f2e6ff"} or (cur and cur.get("body") == "#0f7a6b"), f"the DM's screen gets Lux's roll with his colors ({cur})")
    dm.wait_for_timeout(2500)
    px = dm.evaluate("""() => { const c = document.querySelector('#dice-canvas'), x = c.getContext('2d'); const d = x.getImageData(0, 0, c.width, c.height).data;
      let n = 0; for (let i = 0; i < d.length; i += 16) { const r = d[i], g = d[i + 1], b = d[i + 2]; if (g > r + 25 && b > r + 10 && g < 200) n++; } return n; }""")
    check(px > 30, f"and draws them teal on the tray ({px} teal pixels)")
    dm.locator(".dice-tray").screenshot(path=SHOTS + rf"\dicecolors_tray_{engine.NAME}.png")
    # back to classic
    ph.locator("details.dice-fold .dc-set", has_text="Classic").click(); ph.wait_for_timeout(1500)
    check(call("GET", f"/api/characters/{LUX}")["character"]["dice_style"] == {}, "Classic puts his dice back")
    b.close()
fails = [m for ok, m in results if not ok]
print(f"\n{len(results) - len(fails)} passed, {len(fails)} failed"); [print("FAILED:", f) for f in fails]
print("PROBLEMS:", problems)
