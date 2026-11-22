"""The abandoned prison, clicked through on a DM screen and a player's device: making the map, its
look, chests (place, look inside, add a magic item from the list), a player opening a chest and
taking the loot onto their sheet, locked chests and sealed doors with access cards, a room fight
with the prison's enemies, "Let it act" (an enemy moves and fires a laser by itself), a fallen enemy
dropping its gear, and everything still the same after a reload."""
import json, os, re, urllib.request, uuid
from common import DM_URL, LAN_URL, SHOTS_DIR  # noqa: E402
from playwright.sync_api import sync_playwright
import engine

DM = DM_URL; LAN = LAN_URL
SHOTS = os.path.join(SHOTS_DIR, "prison"); os.makedirs(SHOTS, exist_ok=True)
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


def cell_xy(page, x, y):
    return page.evaluate(f"""() => {{ const v = window.__view, mm = v.map, r = v.canvas.getBoundingClientRect();
      return [r.left + v.view.tx + (mm.offset_x + ({x} + .5) * mm.cell_px) * v.view.s, r.top + v.view.ty + (mm.offset_y + ({y} + .5) * mm.cell_px) * v.view.s]; }}""")


camp = 1
for e in call("GET", f"/api/campaigns/{camp}/encounters")["encounters"]:
    if e["status"] == "active":
        call("POST", f"/api/encounters/{e['id']}/end")
for pl in call("GET", f"/api/campaigns/{camp}/players")["players"]:
    call("DELETE", f"/api/players/{pl['id']}")
chars = {c["name"]: c for c in call("GET", f"/api/campaigns/{camp}/characters")["characters"]}
MONI = chars["Moni Easter"]
code = call("POST", f"/api/campaigns/{camp}/join-code", {"action": "new"})["join_code"]


def moni_sheet():
    return call("GET", f"/api/characters/{MONI['id']}")["character"]


def give_moni(*names):
    sh = moni_sheet()
    call("PATCH", f"/api/characters/{MONI['id']}", {"changes": {"equipment": {"from": sh["equipment"], "to": sh["equipment"] + [
        {"qty": 1, "name": n, "weight": 0, "notes": "test"} for n in names]}}})


with sync_playwright() as p:
    b = engine.launch(p)
    dctx = b.new_context(viewport={"width": 1366, "height": 900}); dctx.add_init_script(CATCH_VIEW)
    dm = dctx.new_page()
    dm.on("pageerror", lambda e: problems.append(f"DM JS error: {e}"))
    dm.on("response", lambda r: r.status >= 500 and problems.append(f"DM HTTP {r.status} {r.url}"))

    print(f"== [{engine.NAME}/{DEVICE}] making the abandoned prison from the Maps page")
    dm.goto(f"{DM}/map"); dm.wait_for_selector("[data-dungeon]")
    check(dm.locator("[data-dungeon=futureprison]").count() == 1, "the Maps page has an Abandoned prison card")
    check(dm.evaluate("(() => { const c = document.querySelector('[data-dthumb=futureprison]'); return c && c.getContext('2d').getImageData(75, 50, 1, 1).data[3] > 0; })()"),
          "its card has a picture")
    dm.locator("[data-dungeon=futureprison]").click()
    dm.wait_for_url(re.compile(r"/map/\d+"), timeout=20000); dm.wait_for_selector("#dungeon-panel:not([hidden])"); dm.wait_for_timeout(2800)
    mid = int(re.search(r"/map/(\d+)", dm.url).group(1))
    st = call("GET", f"/api/maps/{mid}")
    m, d = st["map"], st["map"]["dungeon"]
    check("abandoned prison" in dm.locator("#dungeon-panel h3").inner_text().lower(), "the panel says Abandoned prison · level 1")
    foes = [t for t in st["tokens"] if t["kind"] == "enemy"]
    check(len(foes) >= 8 and all(t["combatant_hidden"] for t in foes), f"{len(foes)} enemies wait hidden in the rooms")
    check(all((t["portrait"] or "").startswith("prison-") for t in foes), "every enemy has its own picture")
    n_chests = dm.locator("#chest-panel details.chest-card").count()
    check(n_chests == len(m["chests"]) >= 10, f"the Chests panel lists the {n_chests} chests")
    terr = set(m["terrain"].values())
    check({"metal", "bulkhead", "redlight", "camera", "turret", "sealed", "panel", "forcefield", "blastdoor"} <= terr, "steel walls, red lights, cameras, turrets, sealed doors")
    check(dm.evaluate("window.__view.map.chests.length") == len(m["chests"]), "the chests are on the drawn map")
    dm.screenshot(path=os.path.join(SHOTS, f"{engine.NAME}_dm_prison.png"))
    for nm in ("Prison Warden", "Security Drone", "Sentinel Unit"):
        check(nm in [c["name"] for c in call("GET", f"/api/creatures?campaign_id={camp}")["creatures"]], f"{nm} is in the creature library")

    print("== the DM looks inside a chest and adds a magic item from the list")
    vault = next(c for c in m["chests"] if c["kind"] == "legendary")
    card = dm.locator(f'[data-chest-card="{vault["id"]}"]')
    card.locator("summary").click(); dm.wait_for_timeout(300)
    check("Warden's access card" in card.inner_text(), "the Legendary cache is locked with the Warden's access card")
    card.locator("select[aria-label='Rarity of the magic item']").select_option("legendary")
    card.get_by_role("button", name=re.compile("Add a magic item")).click()
    dm.wait_for_selector(f'[data-chest-card="{vault["id"]}"] .loot-item.rarity-legendary', timeout=8000)
    card = dm.locator(f'[data-chest-card="{vault["id"]}"]')
    check(card.locator(".loot-item.rarity-legendary").count() >= 1 and "magic" in card.inner_text().lower(), "a Legendary magic item from the list is in it")
    card.get_by_role("button", name=re.compile("Roll it now")).click(); dm.wait_for_timeout(1200)
    card = dm.locator(f'[data-chest-card="{vault["id"]}"]')
    rolled = call("GET", f"/api/maps/{mid}")["map"]["chests"]
    vrow = next(c for c in rolled if c["id"] == vault["id"])
    check(vrow["rolled"] and card.locator(".loot-item").count() == len(vrow["loot"]) >= 3, f"Roll it now: {len(vrow['loot'])} things, shown with their rarity")
    check(any(i.get("magic") and i["rarity"] == "legendary" for i in vrow["loot"]), "the magic item the DM put in is still there after the roll")
    dm.screenshot(path=os.path.join(SHOTS, f"{engine.NAME}_dm_chest_card.png"))

    print("== the DM places a chest in the start room")
    start = next(r for r in d["rooms"] if r["kind"] == "start")
    taken = {(c["x"], c["y"]) for c in rolled}
    spot = next((x, y) for y in range(start["box"][1], start["box"][3] + 1) for x in range(start["box"][0], start["box"][2] + 1)
                if (x, y) not in taken and m["terrain"].get(f"{x},{y}") == "metal" and (x, y) != tuple(d["start"]))
    dm.locator("#chest-kind").select_option("medical")
    dm.locator("#chest-place").click(); dm.wait_for_timeout(200)
    dm.mouse.click(*cell_xy(dm, *spot)); dm.wait_for_timeout(1500)
    dm.keyboard.press("Escape")
    placed = [c for c in call("GET", f"/api/maps/{mid}")["map"]["chests"] if (c["x"], c["y"]) == spot]
    check(placed and placed[0]["kind"] == "medical", f"a Medical Storage Chest where the DM clicked {spot}")
    med = placed[0]

    print("== the party goes in; the player opens the chest next to them")
    dm.locator("#dungeon-panel .dg-step").nth(0).get_by_role("button").click(); dm.wait_for_timeout(1200)
    dm.locator("#dungeon-panel .dg-step").nth(1).get_by_role("button").click(); dm.wait_for_timeout(1200)
    moni_tok = next(t for t in call("GET", f"/api/maps/{mid}")["tokens"] if t["character_id"] == MONI["id"])
    others = {(round(t["x"]), round(t["y"])) for t in call("GET", f"/api/maps/{mid}")["tokens"] if t["id"] != moni_tok["id"]}
    near = next((spot[0] + dx, spot[1] + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if (dx or dy)
                and m["terrain"].get(f"{spot[0] + dx},{spot[1] + dy}") == "metal" and (spot[0] + dx, spot[1] + dy) not in others | taken | {spot})
    call("POST", f"/api/tokens/{moni_tok['id']}/move", {"x": near[0], "y": near[1], "free": True})
    w, h = SIZES[DEVICE]
    touch = DEVICE in ("phones", "tablets", "mixed")
    pctx = b.new_context(viewport={"width": w, "height": h}, **(engine.mobile() if touch else {}), has_touch=touch)
    pctx.add_init_script(CATCH_VIEW)
    pg = pctx.new_page(); pg.on("pageerror", lambda e: problems.append(f"player JS error: {e}"))
    pg.on("response", lambda r: r.status >= 500 and problems.append(f"player HTTP {r.status} {r.url}"))
    pg.goto(LAN + "/join"); pg.fill("input[name=code]", code); pg.fill("input[name=name]", "Moni's player")
    pg.wait_for_selector("#char-field:not([hidden])"); pg.select_option("select[name=character_id]", value=str(MONI["id"]))
    pg.click("button[type=submit]"); pg.wait_for_url(re.compile("/play")); pg.wait_for_timeout(2500)
    pstate = pg.evaluate("async () => (await (await fetch('/api/play/state')).json()).map.map")
    check(any(c["id"] == med["id"] for c in pstate["chests"]) and not any("loot" in c for c in pstate["chests"] if not c["opened"]),
          "the player sees the chests in the lit room, but not what's inside")
    check(not any(c["id"] == vault["id"] for c in pstate["chests"]), "the vault's chest is still in the dark for them")
    pg.wait_for_selector("#nearby:not([hidden])", timeout=8000)
    check("Medical Storage Chest" in pg.locator("#nearby").inner_text(), "'Next to you' shows the chest")
    pg.screenshot(path=os.path.join(SHOTS, f"{engine.NAME}_{DEVICE}_player_nearby.png"))
    pg.locator(f'#nearby button[data-chest="{med["id"]}"]').click()
    pg.wait_for_selector("#loot-pop .loot-box", timeout=8000)
    items = pg.locator("#loot-pop .loot-item")
    n_items = items.count()
    check(n_items >= 1, f"it opens: {n_items} thing(s) inside, with names, rarity and what they do")
    check(pg.locator("#loot-pop .rarity-tag").count() == n_items and pg.locator("#loot-pop .loot-desc").count() == n_items, "every item shows its rarity and description")
    pg.wait_for_timeout(600)  # (after its little rise-in animation)
    pg.screenshot(path=os.path.join(SHOTS, f"{engine.NAME}_{DEVICE}_player_loot.png"))
    dm.wait_for_timeout(2500)
    check(call("GET", f"/api/maps/{mid}")["map"]["chests"][[c["id"] for c in call("GET", f"/api/maps/{mid}")["map"]["chests"]].index(med["id"])]["opened"],
          "the chest is marked opened for everyone")
    check(dm.evaluate(f"window.__view.map.chests.find((c) => c.id === {med['id']}).opened"), "the DM's map shows it open (lid up)")
    first = pg.locator("#loot-pop .loot-name").first.inner_text().split(" ×")[0]
    pg.locator("#loot-pop .loot-item").first.get_by_role("button", name="Take").click(); pg.wait_for_timeout(1500)
    check(any(r["name"] == first for r in moni_sheet()["equipment"]), f"Take: {first} is on Moni's sheet")
    check(pg.locator("#loot-pop .loot-item").count() == n_items - 1, "and it's gone from the chest")
    if pg.locator("#take-all").count():
        pg.locator("#take-all").click(); pg.wait_for_timeout(1500)
    elif pg.locator("#loot-pop .loot-item").count():
        pg.locator("#loot-pop .loot-item").first.get_by_role("button", name="Take").click(); pg.wait_for_timeout(1500)
    check(pg.locator("#loot-pop .loot-item").count() == 0 and "Nothing left" in pg.locator("#loot-pop").inner_text(), "Take all: the chest is empty")
    pg.locator("#loot-close").click()
    again = pg.evaluate(f"async () => (await fetch('/api/play/chests/{med['id']}/take', {{method: 'POST', headers: {{'Content-Type': 'application/json'}}, body: JSON.stringify({{item: 'all'}})}})).status")
    check(again == 409, "nothing can be taken twice (the server says it's empty)")

    print("== the player sees their inventory")
    pg.wait_for_selector("#inventory .inv-item", timeout=8000)
    inv = pg.locator("#inventory").inner_text()
    check(first in inv, f"Inventory on the player screen lists {first}")
    check(pg.locator("#inventory .inv-rarity").count() >= 1, "chest items show their rarity there")
    check(" lb" in pg.locator("#inventory .inv-weight").inner_text(), "and the weight carried of what they can carry")
    pg.reload(); pg.wait_for_selector("#inventory .inv-item", timeout=10000)
    check(first in pg.locator("#inventory").inner_text(), "still there after a refresh")
    sheet_names = [r["name"] for r in moni_sheet()["equipment"] if str(r.get("name") or "").strip()]
    check(pg.locator("#inventory .inv-item").count() == len(sheet_names), f"every item on the sheet is listed ({len(sheet_names)})")
    pg.locator("#inventory").scroll_into_view_if_needed()
    pg.screenshot(path=os.path.join(SHOTS, f"{engine.NAME}_{DEVICE}_player_inventory.png"))

    print("== a sealed door needs its card")
    armory = next(r for r in d["rooms"] if r["name"] == "Hidden armory")
    ax, ay = armory["door"]
    call("POST", f"/api/maps/{mid}/rooms/{d['rooms'].index(armory)}/reveal", {"reveal": False})
    call("POST", f"/api/tokens/{moni_tok['id']}/move", {"x": ax + 1, "y": ay, "free": True}); pg.wait_for_timeout(2500)
    pg.wait_for_selector("#nearby button[data-door]", timeout=8000)
    pg.locator("#nearby button[data-door]").click(); pg.wait_for_timeout(1200)
    check("Security keycard" in pg.locator("#toasts").inner_text(), "without the card: 'Sealed. It needs a Security keycard'")
    give_moni("Security keycard"); pg.wait_for_timeout(500)
    pg.locator("#nearby button[data-door]").click(); pg.wait_for_timeout(2500)
    after = call("GET", f"/api/maps/{mid}")["map"]
    check(after["terrain"][f"{ax},{ay}"] == "blastdoor", "with the card in her pack: the door opens")
    cx, cy = (armory["box"][0] + armory["box"][2]) // 2, (armory["box"][1] + armory["box"][3]) // 2
    check(after["revealed"][cy * after["cols"] + cx] == "1", "and the Hidden armory lights up")
    pg.screenshot(path=os.path.join(SHOTS, f"{engine.NAME}_{DEVICE}_player_door.png"))

    print("== a fight in the security office, and an enemy that acts by itself")
    office = next(r for r in d["rooms"] if r["name"] == "Security office") if any(r["name"] == "Security office" for r in d["rooms"]) \
        else next(r for r in d["rooms"] if r["kind"] == "boss")
    door = next(((x, y) for x in range(office["box"][0], office["box"][2] + 1) for y in (office["box"][1], office["box"][3])
                 if after["terrain"].get(f"{x},{y}") == "metal" and (x, y) not in {(round(t["x"]), round(t["y"])) for t in call("GET", f"/api/maps/{mid}")["tokens"]}
                 and (x, y) not in {(c["x"], c["y"]) for c in after["chests"]}), None)
    call("POST", f"/api/tokens/{moni_tok['id']}/move", {"x": door[0], "y": door[1], "free": True}); dm.wait_for_timeout(2500)
    f = call("GET", f"/api/maps/{mid}")["map"]["dungeon"].get("fight")
    check(f and any("Guard" in x for x in f["foes"]), f"walking into {office['name']} starts a fight ({f and f['foes']})")
    dm.wait_for_selector("#dungeon-panel .room-fight", timeout=10000)
    dm.locator("#dungeon-panel .room-fight").get_by_role("button", name=re.compile("Roll initiative")).click(); dm.wait_for_timeout(2500)
    enc = call("GET", f"/api/encounters/{f['eid']}")
    guard = next(c for c in enc["combatants"] if c["name"].startswith("Cybernetic Prison Guard"))
    call("POST", f"/api/encounters/{f['eid']}/set-turn", {"combatant_id": guard["id"]})
    dm.goto(f"{DM}/map/{mid}"); dm.wait_for_selector("#tb-act", timeout=10000); dm.wait_for_timeout(1500)
    hp0 = moni_sheet()["current_hp"]
    last_roll = max([r["id"] for r in call("GET", f"/api/rolls?campaign_id={camp}&limit=1")["rolls"]] or [0])
    dm.evaluate("() => { window.__seenLaser = false; const v = window.__view, add = v.addFx.bind(v); v.addFx = (f) => { if (f && f.style === 'laser') window.__seenLaser = true; return add(f); }; }")
    pg.evaluate("() => { window.__seenLaser = false; const v = window.__view, add = v.addFx.bind(v); v.addFx = (f) => { if (f && f.style === 'laser') window.__seenLaser = true; return add(f); }; }")
    dm.locator("#tb-act").click(); dm.wait_for_timeout(5000); pg.wait_for_timeout(3000)
    enc2 = call("GET", f"/api/encounters/{f['eid']}")
    log = " ".join(l["message"] for l in enc2["log"][-12:])
    check(guard["name"] in log and ("Pulse Rifle" in log or "Shock Stock" in log or "moves" in log or "dashes" in log), f"Let it act: the guard acted ({log[-160:]!r})")
    check(enc2["encounter"]["current_id"] != guard["id"], "and the turn moved on")
    new_rolls = call("GET", f"/api/rolls?campaign_id={camp}&after_id={last_roll}")["rolls"]
    check(any(r["kind"] == "attack" and r["roller_name"].startswith("Cybernetic") for r in new_rolls), "its attack is a real roll")
    seen = pg.evaluate(f"async () => (await (await fetch('/api/rolls?after_id={last_roll}')).json()).rolls.map((r) => r.roller_name)")
    check(any(n.startswith("Cybernetic") for n in seen), "and the player sees the dice too")
    if "Pulse Rifle" in log:
        check(dm.evaluate("window.__seenLaser") and pg.evaluate("window.__seenLaser"), "a laser beam shows on the DM's map and the player's")
    dm.screenshot(path=os.path.join(SHOTS, f"{engine.NAME}_dm_let_it_act.png"))
    pg.screenshot(path=os.path.join(SHOTS, f"{engine.NAME}_{DEVICE}_player_shot.png"))
    print(f"     (Moni {hp0} -> {moni_sheet()['current_hp']} HP)")

    print("== a fallen guard drops its gear")
    call("POST", f"/api/encounters/{f['eid']}/damage", {"targets": [guard["id"]], "amount": 999}); pg.wait_for_timeout(2500)
    drops = [c for c in call("GET", f"/api/maps/{mid}")["map"]["chests"] if c["kind"] == "drop"]
    check(len(drops) == 1 and drops[0]["loot"], f"a case of gear lies where it fell ({[i['name'] for i in drops[0]['loot']] if drops else None})")
    check(any(c["id"] == drops[0]["id"] for c in pg.evaluate("async () => (await (await fetch('/api/play/state')).json()).map.map.chests")),
          "the player sees it on the map")
    call("POST", f"/api/encounters/{f['eid']}/end")

    print("== combat screen and settings")
    dm.goto(f"{DM}/settings"); dm.wait_for_selector("[data-set='loot.magic_items']")
    check(dm.locator("[data-set='loot.magic_items']").is_checked() and not dm.locator("[data-set='loot.auto_act']").is_checked(),
          "Settings: magic items in chests (on) and enemies act on their own (off)")

    print("== saved: reload both screens")
    pg.reload(); pg.wait_for_timeout(3000); dm.goto(f"{DM}/map/{mid}"); dm.wait_for_timeout(2500)
    pc = {c["id"]: c for c in pg.evaluate("async () => (await (await fetch('/api/play/state')).json()).map.map.chests")}
    check(pc.get(med["id"], {}).get("opened") and pc[med["id"]]["loot"] == [], "after a reload the chest is still open and empty")
    check(dm.evaluate(f"window.__view.map.chests.find((c) => c.id === {med['id']}).opened"), "the DM's map too")
    check(dm.evaluate(f"window.__view.map.terrain['{ax},{ay}']") == "blastdoor", "and the armory door stays open")
    check(any(r["name"] == first for r in moni_sheet()["equipment"]), "the loot is still on Moni's sheet")

    dm.screenshot(path=os.path.join(SHOTS, f"{engine.NAME}_dm_end.png"))
    b.close()

for prob in problems:
    results.append((False, prob)); print("  FAIL " + prob)
ok = sum(1 for r in results if r[0])
print(f"e2e_prison.py [{engine.NAME}/{DEVICE}]: {ok} passed, {len(results) - ok} failed")
raise SystemExit(0 if ok == len(results) else 1)
