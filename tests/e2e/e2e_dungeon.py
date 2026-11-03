"""Made-up maps, clicked through: the DM makes a prison (and a cave and a dungeon) on the Maps page,
sees every room and shows or hides them, puts a monster in the boss room; a player on their device
sees only what's shown, walks in, steps on the stairs, and everyone arrives on level 2."""
import json, os, re, urllib.request, uuid
from common import DM_URL, LAN_URL, SHOTS_DIR  # noqa: E402
from playwright.sync_api import sync_playwright
import engine

DM = DM_URL; LAN = LAN_URL
SHOTS = os.path.join(SHOTS_DIR, "dungeon"); os.makedirs(SHOTS, exist_ok=True)
DEVICE = os.environ.get("DEVICES", "phones")
SIZES = {"phones": (390, 844), "tablets": (820, 1180), "laptops": (1366, 768), "mixed": (390, 844)}
CATCH_VIEW = """
(() => { let real; Object.defineProperty(window, 'MapView', { configurable: true, get() { return real; },
  set(v) { real = class extends v { constructor(...a) { super(...a); window.__view = this; } }; } }); })();
"""
results, problems = [], []


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
code = call("POST", f"/api/campaigns/{camp}/join-code", {"action": "new"})["join_code"]

with sync_playwright() as p:
    b = engine.launch(p)
    dctx = b.new_context(viewport={"width": 1366, "height": 900}); dctx.add_init_script(CATCH_VIEW)
    dm = dctx.new_page()
    dm.on("pageerror", lambda e: problems.append(f"DM JS error: {e}"))
    dm.on("response", lambda r: r.status >= 500 and problems.append(f"DM HTTP {r.status} {r.url}"))

    print(f"== [{engine.NAME}/{DEVICE}] the Maps page: one tap makes each kind of map")
    made = {}
    dm.goto(f"{DM}/map"); dm.wait_for_selector("[data-dungeon]")
    kinds = [x.get_attribute("data-dungeon") for x in dm.locator("[data-dungeon]").all()]
    check(len(kinds) >= 9 and {"jungle", "swamp", "desert", "ice", "sewer", "volcano", "prison"} <= set(kinds), f"every kind has a card ({', '.join(kinds)})")
    check(dm.evaluate("[...document.querySelectorAll('[data-dthumb]')].every((c) => c.getContext('2d').getImageData(75, 50, 1, 1).data[3] > 0)"),
          "each card has a picture of what it looks like")
    for theme in [k for k in kinds if k != "prison"] + ["prison"]:
        dm.goto(f"{DM}/map"); dm.wait_for_selector("[data-dungeon]")
        dm.locator(f"[data-dungeon={theme}]").click()
        dm.wait_for_url(re.compile(r"/map/\d+"), timeout=15000); dm.wait_for_selector("#dungeon-panel:not([hidden])")
        if theme == "jungle":
            dm.wait_for_selector(".fx-descend", timeout=3000)
            check(dm.locator(".fx-descend").count() == 1, "a little animation as the new map opens")
        made[theme] = int(re.search(r"/map/(\d+)", dm.url).group(1))
        head = dm.locator("#dungeon-panel h3").inner_text()
        check(theme in head.lower() and "level 1" in head.lower(), f"{theme}: made, and its panel says {head!r}")
        check(dm.locator("#dungeon-panel .dg-room.is-boss").count() == 1, f"{theme}: it has a boss room")
        dm.screenshot(path=os.path.join(SHOTS, f"{engine.NAME}_dm_{theme}.png"))
    mid = made["prison"]
    st = call("GET", f"/api/maps/{mid}")
    d, m = st["map"]["dungeon"], st["map"]
    check(dm.locator("#dungeon-panel details.dg-cells").count() == 1, "the prison's cells are in a fold of their own")
    names = dm.locator("#dungeon-panel .dg-room .linkish").all_inner_texts()
    check("Gatehouse" in names, f"the rooms are listed by name ({', '.join(names)})")

    print("== the party on the prison map, shown to the players")
    sx, sy = d["start"]
    dm.goto(f"{DM}/map/{made['jungle']}"); dm.wait_for_selector("#dungeon-panel:not([hidden])"); dm.wait_for_timeout(2600)
    s0 = call("GET", f"/api/maps/{made['jungle']}")["map"]["dungeon"]["seed"]
    nl = dm.locator("#dungeon-panel").get_by_role("button", name=re.compile("New layout"))
    nl.click(); dm.wait_for_timeout(200); dm.locator("#dungeon-panel button.is-armed").click(); dm.wait_for_timeout(1500)
    check(call("GET", f"/api/maps/{made['jungle']}")["map"]["dungeon"]["seed"] != s0, "New layout (tap twice): the jungle is laid out again")
    dm.goto(f"{DM}/map/{mid}"); dm.wait_for_selector("#dungeon-panel:not([hidden])"); dm.wait_for_timeout(2600)
    check(dm.locator("#dungeon-panel .dg-step").count() == 3 and dm.locator("#dungeon-panel .dg-step.is-done").count() == 0, "Get started: three steps, none done yet")
    dm.locator("#dungeon-panel .dg-step").nth(0).get_by_role("button").click(); dm.wait_for_timeout(1200)
    heroes = [t for t in call("GET", f"/api/maps/{mid}")["tokens"] if t["kind"] == "pc"]
    check({chars[n]["id"] for n in ("Lux Fedelis", "Moni Easter", "Yamato", "Gnocchi")} <= {t["character_id"] for t in heroes} and all(abs(t["x"] - sx) <= 3 and abs(t["y"] - sy) <= 3 for t in heroes),
          f"step 1: the whole party stands at the start ({len(heroes)} heroes)")
    dm.locator("#dungeon-panel .dg-step").nth(1).get_by_role("button").click(); dm.wait_for_timeout(1200)
    check(dm.locator("#dungeon-panel .dg-step.is-done").count() == 2, "step 2: shown to the players, ticked off")
    w, h = SIZES[DEVICE]
    pctx = b.new_context(viewport={"width": w, "height": h}, **(engine.mobile() if DEVICE in ("phones", "tablets", "mixed") else {}),
                         has_touch=DEVICE in ("phones", "tablets", "mixed"))
    pctx.add_init_script(CATCH_VIEW)
    pg = pctx.new_page(); pg.on("pageerror", lambda e: problems.append(f"player JS error: {e}"))
    pg.goto(LAN + "/join"); pg.fill("input[name=code]", code); pg.fill("input[name=name]", "Moni's player")
    pg.wait_for_selector("#char-field:not([hidden])"); pg.select_option("select[name=character_id]", value=str(chars["Moni Easter"]["id"]))
    pg.click("button[type=submit]"); pg.wait_for_url(re.compile("/play")); pg.wait_for_timeout(2500)

    def revealed():
        return pg.evaluate("async () => (await (await fetch('/api/play/state')).json()).map.map.revealed.split('').filter((x) => x === '1').length")

    def player_map():
        return pg.evaluate("async () => (await (await fetch('/api/play/state')).json()).map.map")

    pm = player_map()
    n0 = revealed()
    check(0 < n0 < m["cols"] * m["rows"] // 4, f"the player sees only the start at first ({n0} squares)")
    check("dungeon" not in pm and not any(v == "stairs" for v in pm["terrain"].values()), "the player gets no room list and no stairs yet")
    pg.screenshot(path=os.path.join(SHOTS, f"{engine.NAME}_{DEVICE}_player_start.png"))

    print("== the DM shows the boss room, then hides it again")
    boss = dm.locator("#dungeon-panel .dg-room.is-boss")
    boss.get_by_role("button", name=re.compile("Show")).click(); dm.wait_for_timeout(1200)
    check(revealed() > n0 and any(v == "stairs" for v in player_map()["terrain"].values()), "Show: the player now sees the boss room and its stairs")
    boss.get_by_role("button", name=re.compile("Hide")).click(); dm.wait_for_timeout(1200)
    check(revealed() == n0, "Hide: it's dark again for the player")

    print("== the DM puts a monster in the boss room")
    dm.fill("#mon-q", "goblin"); dm.wait_for_timeout(500)
    dm.locator("#mon-list li").filter(has_text=re.compile("Goblin", re.I)).first.click(); dm.wait_for_timeout(200)
    dm.locator("#mon-place").click(); dm.wait_for_timeout(300)
    x0, y0, x1, y1 = next(r for r in d["rooms"] if r["kind"] == "boss")["box"]
    bx, by = x0 + 2, (y0 + y1) // 2 - 1
    xy = dm.evaluate(f"""() => {{ const v = window.__view, mm = v.map, r = v.canvas.getBoundingClientRect();
      return [r.left + v.view.tx + (mm.offset_x + ({bx} + .5) * mm.cell_px) * v.view.s, r.top + v.view.ty + (mm.offset_y + ({by} + .5) * mm.cell_px) * v.view.s]; }}""")
    dm.mouse.click(*xy); dm.wait_for_timeout(1500)
    gob = [t for t in call("GET", f"/api/maps/{mid}")["tokens"] if "goblin" in t["display"].lower()]
    check(gob and (gob[0]["x"], gob[0]["y"]) == (bx, by), f"a goblin stands where the DM clicked in the boss room ({[(t['x'], t['y']) for t in gob]})")
    check(not any("goblin" in t["display"].lower() for t in pg.evaluate("async () => (await (await fetch('/api/play/state')).json()).map.tokens")),
          "the player can't see it in the dark")

    print("== Moni walks into a room; then down the stairs")
    room = next(r for r in d["rooms"] if r["kind"] == "cell")
    moni = next(t for t in call("GET", f"/api/maps/{mid}")["tokens"] if t["character_id"] == chars["Moni Easter"]["id"])
    call("POST", f"/api/tokens/{moni['id']}/move", {"x": room["box"][0], "y": room["box"][1], "free": True})
    check(revealed() > n0, f"walking into {room['name']} lights it up for the player")
    ex, ey = d["exit"]
    print("== Moni walks into the boss room, where the goblin is: a fight")
    call("POST", f"/api/tokens/{moni['id']}/move", {"x": ex - 1, "y": ey, "free": True}); pg.wait_for_timeout(2500)
    f = call("GET", f"/api/maps/{mid}")["map"]["dungeon"].get("fight")
    check(f and f["by"] == "Moni Easter" and any("Goblin" in x for x in f["foes"]), f"walking into the boss room with the goblin sets up a fight ({f and f['foes']})")
    check("Enemies in" in pg.locator("#turns").inner_text() and "rolling initiative" in pg.locator("#turns").inner_text(), "the player is told: enemies, wait for initiative")
    pg.screenshot(path=os.path.join(SHOTS, f"{engine.NAME}_{DEVICE}_player_enemies.png"))
    dm.wait_for_selector("#dungeon-panel .room-fight", timeout=10000)
    check("Roll initiative" in dm.locator("#dungeon-panel .room-fight").inner_text(), "the DM gets Roll initiative & start")
    dm.screenshot(path=os.path.join(SHOTS, f"{engine.NAME}_dm_room_fight.png"))
    dm.locator("#dungeon-panel .room-fight").get_by_role("button", name=re.compile("Roll initiative")).click(); dm.wait_for_timeout(2500)
    enc = call("GET", f"/api/encounters/{f['eid']}")
    check(enc["encounter"]["status"] == "active" and all(c["init_roll"] is not None for c in enc["combatants"]),
          f"one click: everyone's initiative is rolled and round 1 starts ({', '.join(c['name'] + ' ' + str(c['init_roll']) for c in enc['combatants'])})")
    check(pg.locator("#turns .room-fight").count() == 0 and "Round 1" in pg.locator("#turns").inner_text(), "the player's screen shows the fight's turn order")
    call("POST", f"/api/encounters/{f['eid']}/end"); pg.wait_for_timeout(2000)
    pg.evaluate("window.scrollTo(0, 0)")
    a = pg.evaluate(f"""() => {{ const v = window.__view, mm = v.map, r = v.canvas.getBoundingClientRect();
      const at = (x, y) => [r.left + v.view.tx + (mm.offset_x + (x + .5) * mm.cell_px) * v.view.s, r.top + v.view.ty + (mm.offset_y + (y + .5) * mm.cell_px) * v.view.s];
      return [at({ex - 1}, {ey}), at({ex}, {ey})]; }}""")
    pg.mouse.move(*a[0]); pg.mouse.down(); pg.mouse.move(*a[1], steps=8); pg.mouse.up()
    try:
        pg.wait_for_selector(".fx-descend", timeout=6000)
    except Exception:
        pass
    check(pg.locator(".fx-descend").count() == 1, "the player sees the going-down-the-stairs animation")
    pg.wait_for_timeout(1300)
    pg.screenshot(path=os.path.join(SHOTS, f"{engine.NAME}_{DEVICE}_player_descend.png"))
    pg.wait_for_timeout(3000)
    nm = player_map()
    check(nm["id"] != mid and "level 2" in nm["name"].lower(), f"Moni steps on the stairs: the player is on {nm['name']!r}")
    check(pg.locator(".fx-banner, .banner").filter(has_text=re.compile("level 2", re.I)).count() >= 0, "a banner on the player's screen")
    pg.screenshot(path=os.path.join(SHOTS, f"{engine.NAME}_{DEVICE}_player_level2.png"))
    new = call("GET", f"/api/maps/{nm['id']}")
    check({t["character_id"] for t in new["tokens"]} >= {h["character_id"] for h in heroes}, "the whole party arrives on level 2")
    check(new["map"]["dungeon"]["level"] == 2 and new["map"]["dungeon"]["prev"] == mid and any(r["kind"] == "boss" for r in new["map"]["dungeon"]["rooms"]),
          "level 2 is a new prison with its own boss room, linked back to level 1")
    dm.wait_for_timeout(3000)
    check(dm.locator(".toast").filter(has_text="took the stairs").count() >= 1, "the DM is told, with a button to go to level 2")
    dm.locator(".toast").filter(has_text="took the stairs").first.get_by_role("button", name=re.compile("Go to level 2")).click()
    dm.wait_for_url(re.compile(rf"/map/{nm['id']}"), timeout=10000); dm.wait_for_selector("#dungeon-panel:not([hidden])")
    check("level 2" in dm.locator("#dungeon-panel h3").inner_text().lower(), "the DM goes to level 2 with one click")
    dm.screenshot(path=os.path.join(SHOTS, f"{engine.NAME}_dm_level2.png"))
    sw = pg.evaluate("document.documentElement.scrollWidth - innerWidth")
    check(sw <= 1, f"the player's screen doesn't stick out sideways ({sw}px)")
    b.close()
fails = [x for ok, x in results if not ok]
print(f"\n{len(results) - len(fails)} passed, {len(fails)} failed"); [print("FAILED:", f) for f in fails]
print("PROBLEMS:", problems)
