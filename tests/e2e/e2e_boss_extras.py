"""Boss extras, clicked: tick Boss and fill in the Boss extras on the Creatures page; in a fight the
boss bar shows on the DM's map (with HP), the Combat screen and a player's phone (no numbers);
legendary actions are used from the DM's fight panel; at half HP Phase 2 shows with its attacks."""
import json, re, time, urllib.request, uuid
from playwright.sync_api import sync_playwright
from common import DM_URL, LAN_URL, SHOTS_DIR  # noqa: E402
import engine

results, problems = [], []


def call(m, path, body=None):
    data = json.dumps(dict(body or {}, op_id=uuid.uuid4().hex)).encode() if m != "GET" else None
    return json.load(urllib.request.urlopen(urllib.request.Request(DM_URL + path, data=data, method=m, headers={"Content-Type": "application/json"})))


def check(c, msg):
    results.append((bool(c), msg)); print(("  PASS " if c else "  FAIL ") + msg, flush=True)


for e in call("GET", "/api/campaigns/1/encounters")["encounters"]:
    if e["status"] == "active":
        call("POST", f"/api/encounters/{e['id']}/end")
for pl in call("GET", "/api/campaigns/1/players")["players"]:
    call("DELETE", f"/api/players/{pl['id']}")
chars = {c["name"]: c for c in call("GET", "/api/campaigns/1/characters")["characters"]}
cr = call("POST", "/api/creatures", {"name": "Ash Wyrm", "max_hp": 80, "ac": 16, "attacks": "Bite: +7 to hit, 2d10+3 piercing damage"})["creature"]
code = call("POST", "/api/campaigns/1/join-code", {"action": "new"})["join_code"]
with sync_playwright() as p:
    b = engine.launch(p)
    pg = b.new_page(viewport={"width": 1400, "height": 950}); pg.on("pageerror", lambda e: problems.append(f"DM JS error: {e}"))
    pg.goto(DM_URL + "/creatures"); pg.wait_for_timeout(1200)
    pg.locator("#list li button").filter(has=pg.locator(".t", has_text=re.compile(r"^Ash Wyrm$"))).first.click(); pg.wait_for_timeout(500)
    check(pg.locator("#editor .boss-extras").count() == 0, "no Boss extras until Boss is ticked")
    pg.locator("#editor .sb-boss input").check(); pg.wait_for_timeout(1500)
    ex = pg.locator("#editor .boss-extras")
    check(ex.count() == 1, "ticking Boss shows the Boss extras")
    lg = ex.locator(".mrows").nth(0)
    lg.get_by_role("button", name="Add an attack").click(); pg.wait_for_timeout(200)
    card = lg.locator(".mrow").last
    card.locator(".mr-name").fill("Tail swipe"); card.get_by_label("To hit").fill("+7"); card.get_by_label("Dice").fill("1d8+3"); pg.wait_for_timeout(300)
    ex.get_by_label("Legendary actions per round").fill("2")
    ex.get_by_label("Legendary resistance (per fight)").fill("1")
    p2 = ex.locator(".mrows").nth(1)
    p2.get_by_role("button", name="Add an attack").click(); pg.wait_for_timeout(200)
    c2 = p2.locator(".mrow").last
    c2.locator(".mr-name").fill("Ash breath"); c2.get_by_label("Dice").fill("6d6"); pg.wait_for_timeout(2500)
    saved = next(c for c in call("GET", "/api/creatures")["creatures"] if c["id"] == cr["id"])
    check(saved["boss"] and saved["legendary"].startswith("Tail swipe:") and saved["legendary_per_round"] == 2 and saved["legendary_resistance"] == 1
          and saved["phase2"].startswith("Ash breath:"), f"the boss extras save ({saved['legendary']!r}, {saved['phase2']!r})")
    pg.locator("#editor").screenshot(path=SHOTS_DIR + rf"\boss_extras_editor_{engine.NAME}.png")
    # the fight
    eid = call("POST", "/api/campaigns/1/encounters", {"name": "Ash Wyrm lair"})["encounter"]["id"]
    call("POST", f"/api/encounters/{eid}/combatants", {"characters": [chars["Lux Fedelis"]["id"]]})
    call("POST", f"/api/encounters/{eid}/combatants", {"creature_id": cr["id"], "count": 1})
    mid = call("POST", f"/api/encounters/{eid}/map")["map_id"]
    call("POST", "/api/campaigns/1/live-map", {"map_id": mid})
    call("POST", f"/api/encounters/{eid}/start")
    by = {c["name"]: c for c in call("GET", f"/api/encounters/{eid}")["combatants"]}
    call("POST", f"/api/encounters/{eid}/set-turn", {"combatant_id": by["Lux Fedelis"]["id"]})
    pg.evaluate(f"localStorage.setItem('combat-sel-{eid}', '{by['Ash Wyrm']['id']}')")
    pg.goto(DM_URL + f"/map/{mid}"); pg.wait_for_timeout(2500)
    bar = pg.locator("#boss-bar")
    check(bar.count() == 1 and "Ash Wyrm" in bar.inner_text() and "80 / 80 HP" in bar.inner_text(), f"the DM's map has the boss bar with its HP ({bar.inner_text() if bar.count() else ''!r})")
    leg = pg.locator(".legendary-acts")
    check(leg.count() == 1 and "2 of 2 left" in leg.inner_text(), "the boss's panel offers its legendary actions (2 of 2)")
    leg.locator(".fight-act", has_text="Tail swipe").click(); pg.wait_for_timeout(1500)
    check(pg.locator(".fight-aim").count() == 1 and "Tail swipe" in pg.locator(".fight-aim").inner_text(), "using Tail swipe gets it ready to aim at someone")
    w = next(c for c in call("GET", f"/api/encounters/{eid}")["combatants"] if c["name"] == "Ash Wyrm")
    check(w["boss"]["left"] == 1, "the server counted it")
    pg.keyboard.press("Escape"); pg.wait_for_timeout(500)
    check("1 of 2 left" in pg.locator(".legendary-acts").inner_text(), "and the panel says 1 of 2 left")
    pg.screenshot(path=SHOTS_DIR + rf"\boss_map_{engine.NAME}.png")
    # a player's phone: the bar without numbers
    ph = b.new_context(viewport={"width": 390, "height": 844}, **engine.mobile(), has_touch=True).new_page()
    ph.on("pageerror", lambda e: problems.append(f"phone JS error: {e}"))
    ph.goto(LAN_URL + "/join"); ph.fill("input[name=code]", code); ph.fill("input[name=name]", "Lux plays")
    ph.wait_for_selector("#char-field:not([hidden])"); ph.select_option("select[name=character_id]", value=str(chars["Lux Fedelis"]["id"]))
    ph.click("button[type=submit]"); ph.wait_for_url(re.compile("/play")); ph.wait_for_timeout(2500)
    pb = ph.locator("#boss-bar")
    check(pb.count() == 1 and "Ash Wyrm" in pb.inner_text() and not re.search(r"\d+\s*/\s*\d+", pb.inner_text()), f"the player's phone has the boss bar, no numbers ({pb.inner_text() if pb.count() else ''!r})")
    # half HP: Phase 2 for everyone, with its attack
    ph.evaluate("() => { window.__banners = []; const o = FX.banner; FX.banner = (t, s, k) => { window.__banners.push(t + ' | ' + s); return o(t, s, k); }; }")
    call("POST", f"/api/combatants/{w['id']}/hp", {"op": "damage", "amount": 40})
    ph.wait_for_timeout(2500); pg.wait_for_timeout(1000)
    check(ph.locator("#boss-bar .is-phase2").count() == 1 and "Phase 2" in ph.locator("#boss-bar").inner_text(), "at half HP the phone shows Phase 2")
    bn = ph.evaluate("window.__banners")
    check(any(x.startswith("Phase 2!") and "Ash Wyrm" in x for x in bn), f"with a Phase 2 banner ({bn})")
    ph.screenshot(path=SHOTS_DIR + rf"\boss_phone_{engine.NAME}.png")
    acts = [x.split("\n")[0] for x in pg.locator(".fight-acts:not(.legendary-acts) .fight-act").all_inner_texts()]
    check(any("Ash breath" in x for x in acts), f"and the DM's panel has its phase 2 attack ({acts})")
    # the Combat screen
    pg.goto(DM_URL + f"/combat/{eid}"); pg.wait_for_timeout(1500)
    pg.locator("#init-list li.combatant").filter(has_text="Ash Wyrm").first.locator(".c-name").click(); pg.wait_for_timeout(500)
    check(pg.locator("#boss-bar").count() == 1 and pg.locator(".legendary-box").count() == 1 and "1 of 2 left" in pg.locator(".legendary-box").inner_text(),
          "the Combat screen has the bar and the legendary actions (1 of 2 left)")
    check("Legendary Resistance: 1 of 1" in pg.locator("#detail").inner_text(), "and its legendary resistance")
    pg.screenshot(path=SHOTS_DIR + rf"\boss_combat_{engine.NAME}.png")
    b.close()
fails = [m for ok, m in results if not ok]
print(f"\n{len(results) - len(fails)} passed, {len(fails)} failed"); [print("FAILED:", f) for f in fails]
print("PROBLEMS:", problems)
