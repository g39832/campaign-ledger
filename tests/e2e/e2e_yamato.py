"""E2E: Yamato's clone spell and Parry, with real clicks (sheet, creatures, combat, map, player)."""
import json, re, urllib.request, uuid
from common import APP_DIR, DM_URL, LAN_IP, LAN_URL, SHOTS_DIR, TMP_DIR  # noqa: E402,F401  (paths and addresses for this computer)
from playwright.sync_api import sync_playwright

DM = DM_URL; LAN = LAN_URL
SHOTS = SHOTS_DIR + r"\yamato"
results, problems = [], []


def call(m, path, body=None):
    data = json.dumps(dict(body or {}, op_id=uuid.uuid4().hex)).encode() if m != "GET" else None
    return json.load(urllib.request.urlopen(urllib.request.Request(DM + path, data=data, method=m, headers={"Content-Type": "application/json"})))


def check(c, msg):
    results.append((bool(c), msg)); print(("  PASS " if c else "  FAIL ") + msg, flush=True)


def watch(pg, who):
    pg.on("pageerror", lambda e: problems.append(f"{who} JS error: {e}"))
    pg.on("console", lambda m: m.type == "error" and "Failed to load resource" not in m.text and problems.append(f"{who} console: {m.text}"))
    pg.on("response", lambda r: r.status >= 500 and problems.append(f"{who} HTTP {r.status} {r.url}"))


def close_dice(pg):
    pg.wait_for_timeout(2200)
    if pg.locator("#dice-dock.is-open").count():
        pg.click("#dice-close"); pg.wait_for_timeout(200)


YAM = 3
with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    pg = b.new_page(viewport={"width": 1440, "height": 1000}); watch(pg, "DM")

    print("== Creatures: give the clone its Slash")
    clone = next(c for c in call("GET", "/api/creatures")["creatures"] if c["name"].lower() == "yamato clone")
    pg.goto(f"{DM}/creatures"); pg.wait_for_timeout(800)
    pg.locator("#list li, #list a, #list button").filter(has_text=re.compile("yamato clone", re.I)).first.click(); pg.wait_for_timeout(600)
    pg.locator("#editor .mrows").nth(0).get_by_role("button", name="Edit as text").click()  # the form's text view
    pg.locator("#editor").get_by_label("Attacks as text").fill("Slash 2d8")
    pg.wait_for_timeout(2200)
    clone = next(c for c in call("GET", "/api/creatures")["creatures"] if c["id"] == clone["id"])
    check(clone["attacks"] == "Slash 2d8", "clone creature has Slash 2d8")

    print("== Sheet: the clone spell and Parry (already on his real sheet)")
    ch = call("GET", f"/api/characters/{YAM}")["character"]
    sp = {s["name"]: s for s in ch["spells"]}
    check(sp["Phantasaml force"].get("summon") == "yamato clone" and sp["Phantasaml force"]["effect"] == "buff", "Phantasaml force summons the yamato clone")
    check(sp["Parry"].get("parry") is True and sp["Parry"].get("cooldown") == 1, "Parry is ticked (1-turn cooldown kept)")
    check(sp["Phantasaml force"].get("from_attack") is not None and sp["Wide Slash"]["dice"] == "2d12", "his other spell details are untouched")
    pg.screenshot(path=SHOTS + r"\sheet.png", full_page=True)

    print("== Combat: cast the clone, it goes right after him")
    eid = call("POST", "/api/campaigns/1/encounters", {"name": "Clone test"})["encounter"]["id"]
    st = call("POST", f"/api/encounters/{eid}/combatants", {"characters": [YAM], "quick": {"name": "Goblin", "max_hp": 30, "ac": 10, "count": 2}})
    by = {c["name"]: c for c in st["combatants"]}
    for n, r in (("Goblin 1", 19), ("Yamato", 14), ("Goblin 2", 6)):
        call("PATCH", f"/api/combatants/{by[n]['id']}", {"changes": {"init_roll": {"from": None, "to": r}}})
    pg.goto(f"{DM}/combat/{eid}"); pg.click("#start"); pg.wait_for_timeout(800)
    pg.locator("#init-list li.combatant").filter(has_text="Yamato").first.locator(".c-name").click(); pg.wait_for_timeout(300)
    pg.locator("#detail .spell-row").filter(has_text="Phantasaml force").get_by_role("button", name="Cast").click()
    pg.wait_for_selector("#detail .cast-picker")
    check("appears next to Yamato" in pg.locator("#detail .cast-picker").inner_text(), "cast panel says the clone appears next to him")
    pg.locator("#detail .cast-go").click(); pg.wait_for_selector("#detail .cast-result")
    print("   ", pg.locator("#detail .cast-result").inner_text().replace("\n", " | "))
    close_dice(pg); pg.locator("#detail .cast-picker").get_by_role("button", name="Done").click(); pg.wait_for_timeout(500)
    order = [x.strip().split("\n")[0] for x in pg.locator("#init-list li.combatant .c-name > span:first-child").all_inner_texts()]
    print("    order:", order)
    check(order[:4] == ["Goblin 1", "Yamato", "yamato clone", "Goblin 2"], "turn order: Goblin 1, Yamato, his clone, Goblin 2")
    check("acts right after Yamato" in pg.locator("#init-list li.combatant").filter(has_text="yamato clone").first.inner_text(), "the clone's row says it acts right after Yamato")
    # the clone's Slash
    pg.locator("#init-list li.combatant").filter(has_text="yamato clone").first.locator(".c-name").click(); pg.wait_for_timeout(300)
    check(pg.locator("#detail .hit-attacks .roll-row").filter(has_text="Slash").count() >= 1, "the clone has its Slash attack ready")
    # recast while it stands is refused
    pg.locator("#init-list li.combatant").filter(has_text="Yamato").first.locator(".c-name").click(); pg.wait_for_timeout(300)
    check("recharging" in pg.locator("#detail .spell-row").filter(has_text="Phantasaml force").inner_text(), "Phantasaml force is recharging (2 turns)")

    print("== Parry: a goblin hits Yamato, the DM screen offers Parry")
    y0 = next(c for c in call("GET", f"/api/encounters/{eid}")["combatants"] if c["name"] == "Yamato")["hp"]
    pg.locator("#init-list li.combatant").filter(has_text="Goblin 1").first.locator(".c-name").click(); pg.wait_for_timeout(300)
    for _ in range(3):
        chip = pg.locator("#detail .target-chip").filter(has_text=re.compile("^Yamato")).first
        if "is-on" in (chip.get_attribute("class") or ""):
            break
        chip.click(); pg.wait_for_timeout(500)
    pg.locator("#detail input[aria-label='Damage to deal']").fill("9")
    pg.locator("#detail .hit-box .hp-ctl").get_by_role("button", name=re.compile("Deal damage")).click(); pg.wait_for_timeout(1200)
    row = pg.locator("#init-list li.combatant").filter(has_text="Yamato").first
    check(row.get_by_role("button", name=re.compile("Parry\\?")).count() == 1, "Yamato's row shows a Parry? button")
    check(pg.locator(".toast").filter(has_text="Parry").count() >= 1, "a toast offers the Parry roll-off")
    pg.screenshot(path=SHOTS + r"\combat_parry_offer.png")
    row.get_by_role("button", name=re.compile("Parry\\?")).click(); pg.wait_for_timeout(1500)
    st = call("GET", f"/api/encounters/{eid}")
    y1 = next(c for c in st["combatants"] if c["name"] == "Yamato")["hp"]
    msg = next(e["message"] for e in reversed(st["log"]) if "roll-off" in e["message"])
    print("   ", msg)
    if "parries" in msg:
        check(y1 == y0 - 4, f"won the roll-off: takes 4 (half of 9) — {y0} -> {y1}")
    else:
        check(y1 == y0 - 9, f"lost the roll-off: takes the full 9 — {y0} -> {y1}")
    check(row.get_by_role("button", name=re.compile("Parry\\?")).count() == 0, "the Parry? button is gone (recharging)")
    pg.screenshot(path=SHOTS + r"\combat_parry_done.png")

    print("== Map: the clone's token is next to Yamato; a new clone after it's beaten")
    mid = call("POST", f"/api/encounters/{eid}/map")["map_id"]
    m = call("GET", f"/api/maps/{mid}")
    cl = next((t for t in m["tokens"] if t["display"].lower() == "yamato clone"), None)
    check(cl is not None, "the clone has a token on the map")
    cid = next(c for c in st["combatants"] if c["name"] == "yamato clone")["id"]
    call("POST", f"/api/combatants/{cid}/hp", {"op": "damage", "amount": 1})
    ycb = next(c for c in st["combatants"] if c["name"] == "Yamato")
    for x in ycb["conditions"]:
        if x.get("cooldown"):
            call("DELETE", f"/api/combatants/{ycb['id']}/conditions/{x['id']}")
    pg.evaluate(f"localStorage.setItem('combat-sel-{eid}', '{ycb['id']}')")
    pg.add_init_script("""(() => { let real; Object.defineProperty(window, 'MapView', { configurable: true, get() { return real; },
      set(v) { real = class extends v { constructor(...a) { super(...a); window.__view = this; } }; } }); })();""")
    pg.goto(f"{DM}/map/{mid}"); pg.wait_for_selector(".fight-act")
    btn = pg.locator(".fight-act").filter(has=pg.locator("b", has_text="Phantasaml force")).first
    off = "is-offturn" in (btn.get_attribute("class") or "")
    btn.click()
    if off:
        pg.wait_for_timeout(200); pg.locator(".fight-act").filter(has=pg.locator("b", has_text="Phantasaml force")).first.click()
    pg.wait_for_timeout(600)
    check("click the square where" in pg.locator("#hint").inner_text(), "the map asks where the clone appears")
    m = call("GET", f"/api/maps/{mid}")
    me = next(t for t in m["tokens"] if t["display"] == "Yamato")
    taken = {(t["x"], t["y"]) for t in m["tokens"]}
    spot = next((me["x"] + d, me["y"]) for d in (3, 4, 5, -3, -4) if (me["x"] + d, me["y"]) not in taken and 0 <= me["x"] + d < m["map"]["cols"])
    xy = pg.evaluate(f"""() => {{ const v = window.__view, mm = v.map, r = v.canvas.getBoundingClientRect();
      return [r.left + v.view.tx + (mm.offset_x + ({spot[0]} + .5) * mm.cell_px) * v.view.s, r.top + v.view.ty + (mm.offset_y + ({spot[1]} + .5) * mm.cell_px) * v.view.s]; }}""")
    pg.mouse.click(*xy); pg.wait_for_timeout(2000)
    m = call("GET", f"/api/maps/{mid}")
    c2 = next((t for t in m["tokens"] if t["display"].lower() == "yamato clone 2"), None)
    check(c2 is not None and (c2["x"], c2["y"]) == spot, f"casting from the map puts yamato clone 2 on the square the DM clicked {spot}")
    close_dice(pg)
    pg.screenshot(path=SHOTS + r"\map_clone.png")

    print("== Player: Yamato's own screen gets the Parry button")
    code = call("POST", "/api/campaigns/1/join-code", {"action": "new"})["join_code"]
    for pl in call("GET", "/api/campaigns/1/players")["players"]:
        if pl.get("name") == "Yamato test" or pl.get("character_id") == YAM:
            call("DELETE", f"/api/players/{pl['id']}")
    ctx = b.new_context(viewport={"width": 420, "height": 900}, is_mobile=True, has_touch=True)
    pp = ctx.new_page(); watch(pp, "player")
    pp.goto(LAN + "/join"); pp.fill("input[name=code]", code); pp.fill("input[name=name]", "Yamato test")
    pp.wait_for_selector("#char-field:not([hidden])"); pp.select_option("select[name=character_id]", value=str(YAM))
    pp.click("button[type=submit]"); pp.wait_for_url(re.compile("/play")); pp.wait_for_timeout(1500)
    ycb = next(c for c in call("GET", f"/api/encounters/{eid}")["combatants"] if c["name"] == "Yamato")
    for x in ycb["conditions"]:
        if x.get("cooldown"):
            call("DELETE", f"/api/combatants/{ycb['id']}/conditions/{x['id']}")
    y0 = ycb["hp"]
    call("POST", f"/api/encounters/{eid}/damage", {"targets": [ycb["id"]], "amount": 6})
    pp.wait_for_timeout(4000)
    check("You were hit for 6!" in pp.locator("body").inner_text(), "his screen says he was hit for 6 and offers Parry")
    pp.screenshot(path=SHOTS + r"\player_offer.png")
    pp.get_by_role("button", name=re.compile("^Parry!")).click(); pp.wait_for_timeout(2000)
    y1 = next(c for c in call("GET", f"/api/encounters/{eid}")["combatants"] if c["name"] == "Yamato")["hp"]
    check(y1 in (y0 - 3, y0 - 6), f"player's parry resolves ({y0} -> {y1}: {'won, half' if y1 == y0 - 3 else 'lost, full'})")
    check(pp.locator(".toast").filter(has_text=re.compile("Parried|DM wins")).count() >= 1, "he sees who won")
    pp.screenshot(path=SHOTS + r"\player_done.png")
    ctx.close(); b.close()

fails = [m for ok, m in results if not ok]
print(f"\n{len(results) - len(fails)} passed, {len(fails)} failed"); [print("FAILED:", f) for f in fails]
print("PROBLEMS:", problems)
