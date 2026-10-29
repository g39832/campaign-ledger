"""E2E: Lux's Spirit Guardians from her phone (one tap, 20 ft around her, enemies only, light on
every map, half speed for enemies inside, 3 rounds then a cooldown) and Take it back, on the
phone and on the DM's map."""
import json, re, urllib.request, uuid
from common import APP_DIR, DM_URL, LAN_IP, LAN_URL, SHOTS_DIR, TMP_DIR  # noqa: E402,F401  (paths and addresses for this computer)
from playwright.sync_api import sync_playwright
import engine

DM = DM_URL; LAN = LAN_URL
SHOTS = SHOTS_DIR
results, problems = [], []
CATCH_VIEW = """
(() => { let real; Object.defineProperty(window, 'MapView', { configurable: true, get() { return real; },
  set(v) { real = class extends v { constructor(...a) { super(...a); window.__view = this; } }; } }); })();
"""
GUARDIANS = {"name": "Spirit Guardians", "effect": "damage", "level": 3, "dice": "3d8", "damage_type": "radiant", "hit": "wis",
             "force_save": True, "save_half": False, "area": "20 ft radius", "rounds": 3, "cooldown": 3, "zone": True, "zone_speed": "0.5",
             "notes": "Homebrew: 20 ft all around Lux"}


def call(m, path, body=None):
    data = json.dumps(dict(body or {}, op_id=uuid.uuid4().hex)).encode() if m != "GET" else None
    return json.load(urllib.request.urlopen(urllib.request.Request(DM + path, data=data, method=m, headers={"Content-Type": "application/json"})))


def check(c, msg):
    results.append((bool(c), msg)); print(("  PASS " if c else "  FAIL ") + msg, flush=True)


camp = 1
for e in call("GET", f"/api/campaigns/{camp}/encounters")["encounters"]:
    if e["status"] == "active":
        call("POST", f"/api/encounters/{e['id']}/end")
for pl in call("GET", f"/api/campaigns/{camp}/players")["players"]:
    call("DELETE", f"/api/players/{pl['id']}")
chars = {c["name"]: c for c in call("GET", f"/api/campaigns/{camp}/characters")["characters"]}
lux = call("GET", f"/api/characters/{chars['Lux Fedelis']['id']}")["character"]
call("PATCH", f"/api/characters/{lux['id']}", {"changes": {"spells": {"from": lux["spells"], "to": [GUARDIANS]}}})
eid = call("POST", f"/api/campaigns/{camp}/encounters", {"name": "Guardians"})["encounter"]["id"]
call("POST", f"/api/encounters/{eid}/combatants", {"characters": [chars[n]["id"] for n in ("Lux Fedelis", "Gnocchi")],
                                                   "quick": {"name": "Goblin", "max_hp": 200, "ac": 3, "count": 3}})
mid = call("POST", f"/api/encounters/{eid}/map")["map_id"]
call("PATCH", f"/api/maps/{mid}", {"changes": {"cols": {"to": 24}, "rows": {"to": 14}}})
toks = {t["display"]: t for t in call("GET", f"/api/maps/{mid}")["tokens"]}
for n, (x, y) in {"Lux Fedelis": (8, 6), "Gnocchi": (9, 6), "Goblin 1": (11, 6), "Goblin 2": (8, 10), "Goblin 3": (20, 6)}.items():
    call("POST", f"/api/tokens/{toks[n]['id']}/move", {"x": x, "y": y, "free": True})
call("POST", f"/api/campaigns/{camp}/live-map", {"map_id": mid})
call("POST", f"/api/encounters/{eid}/start")
by = {c["name"]: c for c in call("GET", f"/api/encounters/{eid}")["combatants"]}


def fresh_turn(name):
    for _ in range(10):
        if call("POST", f"/api/encounters/{eid}/next")["encounter"]["current_id"] == by[name]["id"]:
            return


def hp(n):
    return next(c for c in call("GET", f"/api/encounters/{eid}")["combatants"] if c["name"] == n)["hp"]


fresh_turn("Lux Fedelis")
code = call("POST", f"/api/campaigns/{camp}/join-code", {"action": "new"})["join_code"]
with sync_playwright() as p:
    b = engine.launch(p)
    ctx = b.new_context(viewport={"width": 390, "height": 844}, **engine.mobile(), has_touch=True); ctx.add_init_script(CATCH_VIEW)
    lx = ctx.new_page(); lx.on("pageerror", lambda e: problems.append(f"phone JS error: {e}"))
    lx.goto(LAN + "/join"); lx.fill("input[name=code]", code); lx.fill("input[name=name]", "Lux zone")
    lx.wait_for_selector("#char-field:not([hidden])"); lx.select_option("select[name=character_id]", value=str(lux["id"]))
    lx.click("button[type=submit]"); lx.wait_for_url(re.compile("/play")); lx.wait_for_timeout(3000)
    dmc = b.new_context(viewport={"width": 1400, "height": 950}); dmc.add_init_script(CATCH_VIEW)
    dm = dmc.new_page(); dm.on("pageerror", lambda e: problems.append(f"DM JS error: {e}"))
    dm.goto(f"{DM}/map/{mid}"); dm.wait_for_timeout(1500)

    print(f"== [{engine.NAME}] The DM casts it for Lux from the map, then takes it back")
    dm.mouse.click(*dm.evaluate("""() => { const v = window.__view, m = v.map, r = v.canvas.getBoundingClientRect(); const t = v.tokens.find(t => t.display === 'Lux Fedelis');
      return [r.left + v.view.tx + (m.offset_x + (t.x + .5) * m.cell_px) * v.view.s, r.top + v.view.ty + (m.offset_y + (t.y + .5) * m.cell_px) * v.view.s]; }"""))
    dm.wait_for_selector(".fight-act"); dm.wait_for_timeout(500)
    g1 = hp("Goblin 1")
    dm.locator(".fight-act").filter(has=dm.locator("b", has_text=re.compile(r"^\s*Spirit Guardians\s*$"))).first.click(); dm.wait_for_selector(".fight-result .take-back", timeout=25000); dm.wait_for_timeout(2500)
    if dm.locator("#dice-dock.is-open").count():
        dm.click("#dice-close")
    check(dm.evaluate("(window.__view.zones || []).length") == 1, "cast from the DM's map: the light rises around Lux")
    tb = dm.locator(".fight-result").get_by_role("button", name=re.compile("Take it back"))
    check(tb.count() == 1, "the DM's result has a Take it back button")
    tb.click(); dm.wait_for_timeout(2500)
    check(hp("Goblin 1") == g1 and dm.evaluate("(window.__view.zones || []).length") == 0, "taken back: no damage, no light")
    lx.wait_for_timeout(2500)
    card = lx.locator(".move-card").filter(has_text="Spirit Guardians").first
    check("around the caster for 3 rounds, enemies only" in card.inner_text(), f"the card says what it does ({card.inner_text().splitlines()[1][:110]!r})")
    before = {n: hp(n) for n in ("Gnocchi", "Goblin 1", "Goblin 2", "Goblin 3")}
    print(f"== [{engine.NAME}] Lux taps Use")
    card.get_by_role("button", name=re.compile("Use")).click(); lx.wait_for_selector("#use-box button:has-text('Done')", timeout=25000); lx.wait_for_timeout(600); dm.wait_for_timeout(2500)
    res = lx.locator("#use-box").inner_text()
    print("    ", " / ".join(res.splitlines())[:300])
    check("Goblin 1" in res and "Goblin 2" in res and "Goblin 3" not in res and "Gnocchi" not in res,
          "Goblins 1 and 2 (within 20 ft) save; Goblin 3 (60 ft away) and Gnocchi (a teammate) don't")
    check(hp("Gnocchi") == before["Gnocchi"] and hp("Goblin 3") == before["Goblin 3"], "Gnocchi and Goblin 3 untouched")
    check(lx.evaluate("(window.__view.zones || []).length") == 1, "her phone draws the light around her")
    dm.wait_for_timeout(2500)
    check(dm.evaluate("(window.__view.zones || []).length") == 1, "the DM's map draws it too")
    dm.locator("#stage").screenshot(path=SHOTS + f"/zone_{engine.NAME}_dm.png")
    lx.evaluate("window.scrollTo(0, 0)"); lx.screenshot(path=SHOTS + f"/zone_{engine.NAME}_phone.png")
    print("== Take it back on the phone")
    lx.locator("#use-box").get_by_role("button", name=re.compile("Take it back")).click(); lx.wait_for_timeout(2500)
    check(all(hp(n) == before[n] for n in before), "everyone's HP is back")
    check(lx.evaluate("(window.__view.zones || []).length") == 0, "the light is gone")
    check("Actions left this turn: 2 of 2" in lx.locator("body").inner_text(), "her action is back")
    print("== Cast it again: it stays up, enemies inside are slowed")
    lx.locator(".move-card").filter(has_text="Spirit Guardians").first.get_by_role("button", name=re.compile("Use")).click(); lx.wait_for_selector("#use-box button:has-text('Done')", timeout=25000); lx.wait_for_timeout(600)
    lx.locator("#use-box").get_by_role("button", name="Done").click()
    check("recharging · ready in 6 turns" in lx.locator(".move-card").filter(has_text="Spirit Guardians").first.inner_text(), "it recharges: 3 rounds up + 3 cooldown")
    call("POST", f"/api/encounters/{eid}/set-turn", {"combatant_id": by["Goblin 1"]["id"]}); dm.wait_for_timeout(2500)
    mv = call("GET", f"/api/maps/{mid}")["move"]
    check(mv["speed"] == 15, f"Goblin 1, inside it, moves 15 ft instead of 30 ({mv['speed']})")
    call("POST", f"/api/encounters/{eid}/set-turn", {"combatant_id": by["Goblin 3"]["id"]})
    check(call("GET", f"/api/maps/{mid}")["move"]["speed"] == 30, "Goblin 3, outside, still 30 ft")
    call("POST", f"/api/encounters/{eid}/set-turn", {"combatant_id": by["Gnocchi"]["id"]})
    check(call("GET", f"/api/maps/{mid}")["move"]["speed"] == 40, "Gnocchi, a teammate inside it, keeps her 40 ft")
    for _ in range(3):
        fresh_turn("Lux Fedelis"); call("POST", f"/api/encounters/{eid}/next")
    check(call("GET", f"/api/maps/{mid}")["zones"] == [], "three of Lux's turns later it's down")
    print("== The DM's map: Take it back after a misclick")
    fresh_turn("Goblin 1"); dm.wait_for_timeout(2500)
    dm.mouse.click(*dm.evaluate("""() => { const v = window.__view, m = v.map, r = v.canvas.getBoundingClientRect(); const t = v.tokens.find(t => t.display === 'Goblin 1');
      return [r.left + v.view.tx + (m.offset_x + (t.x + .5) * m.cell_px) * v.view.s, r.top + v.view.ty + (m.offset_y + (t.y + .5) * m.cell_px) * v.view.s]; }"""))
    dm.wait_for_timeout(600)
    g = hp("Gnocchi")
    r = call("POST", f"/api/encounters/{eid}/cast", {"caster_id": by["Goblin 1"]["id"], "spell": {"name": "Fire Bolt", "effect": "damage", "dice": "1d10", "hit": "attack", "attack_bonus": 50},
                                                      "targets": [by["Gnocchi"]["id"]]})
    dm.wait_for_timeout(500)
    back = call("POST", f"/api/encounters/{eid}/casts/{r['cast']['undo']}/undo")
    check(back["taken_back"] == "Fire Bolt" and hp("Gnocchi") == g, "the DM takes back a misclicked Fire Bolt")
    b.close()
fails = [m for ok, m in results if not ok]
print(f"\n{len(results) - len(fails)} passed, {len(fails)} failed"); [print("FAILED:", f) for f in fails]
print("PROBLEMS:", problems)
