"""E2E edge cases on phones: area moves (Wide Slash on two goblins), Spirit Guardians from
Lux's phone, Cure Wounds on a teammate (uses an action), Disengage when movement is locked,
a grappled hero, and a fight with no shared battle map (picking enemies from the list)."""
import json, re, urllib.request, uuid
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


camp = 1
for e in call("GET", f"/api/campaigns/{camp}/encounters")["encounters"]:
    if e["status"] == "active":
        call("POST", f"/api/encounters/{e['id']}/end")
for pl in call("GET", f"/api/campaigns/{camp}/players")["players"]:
    call("DELETE", f"/api/players/{pl['id']}")
chars = {c["name"]: c for c in call("GET", f"/api/campaigns/{camp}/characters")["characters"]}
HEROES = ["Lux Fedelis", "Yamato", "Gnocchi"]
eid = call("POST", f"/api/campaigns/{camp}/encounters", {"name": "Edges"})["encounter"]["id"]
call("POST", f"/api/encounters/{eid}/combatants", {"characters": [chars[n]["id"] for n in HEROES],
                                                   "quick": {"name": "Goblin", "max_hp": 200, "ac": 3, "count": 3}})
call("POST", f"/api/campaigns/{camp}/live-map", {"map_id": None})
call("POST", f"/api/encounters/{eid}/start")
by = {c["name"]: c for c in call("GET", f"/api/encounters/{eid}")["combatants"]}
code = call("POST", f"/api/campaigns/{camp}/join-code", {"action": "new"})["join_code"]


def hp(name):
    return next(c for c in call("GET", f"/api/encounters/{eid}")["combatants"] if c["name"] == name)["hp"]


def turn(name):
    call("POST", f"/api/encounters/{eid}/set-turn", {"combatant_id": by[name]["id"]})
    for _ in range(12):  # a fresh turn (Next starts it over)
        st = call("POST", f"/api/encounters/{eid}/next")
        if st["encounter"]["current_id"] == by[name]["id"]:
            return


with sync_playwright() as p:
    b = engine.launch(p)
    ph = {}
    for n in HEROES:
        ctx = b.new_context(viewport={"width": 390, "height": 844}, **engine.mobile(), has_touch=True)
        pg = ctx.new_page(); pg.on("pageerror", lambda e, n=n: problems.append(f"{n} JS error: {e}"))
        pg.on("response", lambda r, n=n: r.status >= 500 and problems.append(f"{n} HTTP {r.status} {r.url}"))
        pg.goto(LAN + "/join"); pg.fill("input[name=code]", code); pg.fill("input[name=name]", n.split()[0] + " tester")
        pg.wait_for_selector("#char-field:not([hidden])"); pg.select_option("select[name=character_id]", value=str(chars[n]["id"]))
        pg.click("button[type=submit]"); pg.wait_for_url(re.compile("/play"))
        ph[n] = pg
    toasts = lambda pg: " | ".join(pg.locator(".toast").all_inner_texts())

    def card(pg, name):
        return pg.locator(".move-card").filter(has=pg.locator("b", has_text=re.compile(r"^\s*" + re.escape(name) + r"\s*$"))).first

    def close(pg):
        if pg.locator("#use-box").get_by_role("button", name="Done").count():
            pg.locator("#use-box").get_by_role("button", name="Done").click()
        if pg.locator("#dice-dock.is-open").count():
            pg.click("#dice-close")

    print("== No battle map shared: Yamato's Wide Slash on two goblins, picked from the list")
    turn("Yamato"); y = ph["Yamato"]; y.wait_for_timeout(3500)
    check(y.locator("#no-map").is_visible(), "the phone says there's no map")
    st = y.locator("#stage").bounding_box()
    check(st["height"] < 160, f"and the empty map box is just a small strip ({st['height']:.0f}px)")
    y.screenshot(path=SHOTS + "/edges_nomap.png")
    g1, g2, g3 = hp("Goblin 1"), hp("Goblin 2"), hp("Goblin 3")
    card(y, "Wide Slash").get_by_role("button", name=re.compile("Use")).click(); y.wait_for_timeout(400)
    box = y.locator("#use-box")
    check("Tap each enemy it reaches" in box.inner_text(), "an area move lets her pick several")
    box.get_by_role("button", name=re.compile("^Goblin 1")).click(); box.get_by_role("button", name=re.compile("^Goblin 2")).click()
    box.get_by_role("button", name=re.compile("Use on 2")).click(); y.wait_for_selector("#use-box button:has-text('Done')", timeout=25000); y.wait_for_timeout(600)
    res = y.locator("#use-box").inner_text()
    print("    ", res.replace("\n", " / "))
    check("Goblin 1" in res and "Goblin 2" in res and hp("Goblin 3") == g3, "Wide Slash reached exactly the two picked")
    check(hp("Goblin 1") < g1 or "miss" in res, "and did damage")
    close(y); y.wait_for_timeout(1500)
    check("recharging" in card(y, "Wide Slash").inner_text(), f"Wide Slash is recharging ({card(y, 'Wide Slash').inner_text()!r})")
    check("Actions left this turn: 1 of" in y.locator("body").inner_text(), "it used one action")

    print("== Lux: Cure Wounds a teammate (uses an action), then Spirit Guardians on the goblins")
    turn("Lux Fedelis"); lx = ph["Lux Fedelis"]; lx.wait_for_timeout(3500)
    sg = card(lx, "Spirit Guardians")
    btn = sg.get_by_role("button", name=re.compile("Use"))
    check(btn.count() == 1, "Spirit Guardians has a Use button on her turn")
    btn.click(); lx.wait_for_timeout(400)
    box = lx.locator("#use-box")
    for gname in ("Goblin 1", "Goblin 2", "Goblin 3"):
        box.get_by_role("button", name=re.compile("^" + gname)).click()
    box.get_by_role("button", name=re.compile("Use on 3")).click(); lx.wait_for_selector("#use-box button:has-text('Done')", timeout=25000); lx.wait_for_timeout(600)
    res = lx.locator("#use-box").inner_text()
    print("    ", res.replace("\n", " / "))
    st = call("GET", f"/api/encounters/{eid}")
    gobs = [c for c in st["combatants"] if c["name"].startswith("Goblin")]
    check(all(g["name"] in res for g in gobs), "no map shared: she picks who's in it, and all three goblins make the save")
    check(any(x.get("zone") for x in next(c for c in st["combatants"] if c["name"] == "Lux Fedelis")["conditions"]), "the zone is up around Lux for its rounds")
    check(not re.search(r"\bAC \d", lx.locator("body").inner_text()), "no AC on Lux's phone")
    close(lx)

    print("== Gnocchi grappled on her turn")
    turn("Gnocchi"); gn = ph["Gnocchi"]
    call("POST", f"/api/combatants/{by['Gnocchi']['id']}/conditions", {"name": "Grappled"})
    gn.wait_for_timeout(3500)
    check("Grappled" in gn.locator("body").inner_text(), "her phone shows Grappled")
    gn.screenshot(path=SHOTS + "/edges_grappled.png", full_page=True)
    print("== Movement locked by the DM: Disengage lets her move (and uses an action)")
    mid = call("POST", f"/api/encounters/{eid}/map")["map_id"]
    call("POST", f"/api/campaigns/{camp}/live-map", {"map_id": mid})
    call("PATCH", f"/api/maps/{mid}", {"changes": {"players_can_move": {"to": False}}})
    gc = next(c for c in call("GET", f"/api/encounters/{eid}")["combatants"] if c["name"] == "Gnocchi")
    cid = next(x["id"] for x in gc["conditions"] if x["name"] == "Grappled")
    call("DELETE", f"/api/combatants/{by['Gnocchi']['id']}/conditions/{cid}")
    gn.wait_for_timeout(3500)
    check(gn.locator("#stage").bounding_box()["height"] > 300, "once a map is shared it's full size again")
    check("The DM has locked movement" in gn.locator("#hint").inner_text(), f"hint: {gn.locator('#hint').inner_text()!r}")
    gn.get_by_role("button", name=re.compile("Disengage")).click(); gn.wait_for_timeout(2500)
    check("Disengaged" in gn.locator("body").inner_text() and "Actions left this turn: 1 of" in gn.locator("body").inner_text(), "Disengaged, one action used")
    tok = next(t for t in call("GET", f"/api/maps/{mid}")["tokens"] if t["display"] == "Gnocchi")
    r = gn.evaluate(f"async () => {{ const r = await fetch('/api/play/tokens/{tok['id']}/move', {{method: 'POST', headers: {{'Content-Type': 'application/json'}}, body: JSON.stringify({{x: {tok['x'] + 2}, y: {tok['y']}}})}}); return r.status }}")
    check(r == 200, f"after Disengage she can move even though movement is locked ({r})")
    print("== Two phones at once: Yamato can't act on Gnocchi's turn")
    r = ph["Yamato"].evaluate(f"async () => {{ const r = await fetch('/api/play/me/use', {{method: 'POST', headers: {{'Content-Type': 'application/json'}}, body: JSON.stringify({{what: 'attack', index: 0, targets: [{by['Goblin 3']['id']}]}})}}); return [r.status, (await r.json()).error] }}")
    check(r[0] == 403 and "not your turn" in r[1], f"Yamato is refused on Gnocchi's turn ({r})")
    b.close()
fails = [m for ok, m in results if not ok]
print(f"\n{len(results) - len(fails)} passed, {len(fails)} failed"); [print("FAILED:", f) for f in fails]
print("PROBLEMS:", problems)
