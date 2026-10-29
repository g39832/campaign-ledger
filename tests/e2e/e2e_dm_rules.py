"""E2E: the DM's map follows turns and speed in a fight (Free move overrides), the DM's rolls
for a hero count toward their two actions, and the phone keeps the map in view."""
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


def call(m, path, body=None):
    data = json.dumps(dict(body or {}, op_id=uuid.uuid4().hex)).encode() if m != "GET" else None
    return json.load(urllib.request.urlopen(urllib.request.Request(DM + path, data=data, method=m, headers={"Content-Type": "application/json"})))


def _unarchive_test_hero():
    """The real data has Test Hero archived: bring it back in this copy only."""
    allc = call("GET", "/api/campaigns/1/characters?archived=1")["characters"]
    th = next((c for c in allc if c["name"] == "Test Hero"), None)
    if th and th.get("archived"):
        full = call("GET", f"/api/characters/{th['id']}")["character"]
        call("PATCH", f"/api/characters/{th['id']}", {"changes": {"archived": {"from": True, "to": False}}})


def check(c, msg):
    results.append((bool(c), msg)); print(("  PASS " if c else "  FAIL ") + msg, flush=True)


_unarchive_test_hero()
camp = call("GET", "/api/campaigns")["campaigns"][0]["id"]
for e in call("GET", f"/api/campaigns/{camp}/encounters")["encounters"]:
    if e["status"] == "active":
        call("POST", f"/api/encounters/{e['id']}/end")
heroes = [c["id"] for c in call("GET", f"/api/campaigns/{camp}/characters")["characters"]]
eid = call("POST", f"/api/campaigns/{camp}/encounters", {"name": "DM rules"})["encounter"]["id"]
call("POST", f"/api/encounters/{eid}/combatants", {"characters": heroes, "quick": {"name": "Goblin", "max_hp": 30, "ac": 10, "count": 1}})
mid = call("POST", f"/api/encounters/{eid}/map")["map_id"]
call("PATCH", f"/api/maps/{mid}", {"changes": {"cols": {"to": 30}, "rows": {"to": 16}}})
for i, t in enumerate(call("GET", f"/api/maps/{mid}")["tokens"]):
    call("POST", f"/api/tokens/{t['id']}/move", {"x": 2, "y": i * 2, "free": True})
call("POST", f"/api/campaigns/{camp}/live-map", {"map_id": mid})
call("POST", f"/api/encounters/{eid}/start")
st = call("GET", f"/api/encounters/{eid}")
by = {c["name"]: c for c in st["combatants"]}
toks = {t["display"]: t for t in call("GET", f"/api/maps/{mid}")["tokens"]}
hero = "Test Hero"
call("POST", f"/api/encounters/{eid}/set-turn", {"combatant_id": by["Lux Fedelis"]["id"]})

with sync_playwright() as p:
    b = engine.launch(p)
    ctx = b.new_context(viewport={"width": 1440, "height": 1000}); ctx.add_init_script(CATCH_VIEW)
    pg = ctx.new_page()
    pg.on("pageerror", lambda e: problems.append(f"JS error: {e}"))
    pg.goto(f"{DM}/map/{mid}"); pg.wait_for_timeout(1500)

    def screen(cx, cy):
        return pg.evaluate(f"""() => {{ const v = window.__view, m = v.map, r = v.canvas.getBoundingClientRect();
          return [r.left + v.view.tx + (m.offset_x + ({cx} + .5) * m.cell_px) * v.view.s, r.top + v.view.ty + (m.offset_y + ({cy} + .5) * m.cell_px) * v.view.s]; }}""")

    def drag(fx, fy, tx, ty):
        a, z = screen(fx, fy), screen(tx, ty)
        pg.mouse.move(*a); pg.mouse.down(); pg.mouse.move(*z, steps=8); pg.mouse.up(); pg.wait_for_timeout(1500)

    def at(name):
        t = next(t for t in call("GET", f"/api/maps/{mid}")["tokens"] if t["display"] == name)
        return (t["x"], t["y"])

    toasts = lambda: " | ".join(pg.locator(".toast").all_inner_texts())
    x0, y0 = at(hero)
    print("== Not Test Hero's turn: dragging them on the DM map")
    drag(x0, y0, x0 + 2, y0)
    check(at(hero) == (x0, y0), "it snaps back")
    check(f"not {hero}'s turn" in toasts(), f"toast: {toasts()[-120:]!r}")
    print("== Their turn: 30 ft")
    for _ in range(len(by) + 1):  # a fresh turn for them (Next, so their turn starts over)
        cur = call("POST", f"/api/encounters/{eid}/next")["encounter"]["current_id"]
        if cur == by[hero]["id"]:
            break
    pg.wait_for_timeout(2500)
    a, z = screen(x0, y0), screen(x0 + 8, y0)
    pg.mouse.move(*a); pg.mouse.down(); pg.mouse.move(*z, steps=8); pg.wait_for_timeout(300)
    pg.screenshot(path=SHOTS + "/dm_reach_toofar.png")
    held = pg.evaluate("() => window.__view.drag && window.__view.drag.at")
    check(held and held[0] == x0 + 6, f"while dragging 40 ft away, the token stays at the box edge (30 ft): {held}")
    pg.mouse.move(*screen(x0 + 4, y0), steps=6); pg.wait_for_timeout(300)
    pg.screenshot(path=SHOTS + "/dm_reach_ok.png")
    pg.mouse.up(); pg.wait_for_timeout(1500)
    check(at(hero) == (x0 + 4, y0), "20 ft works")
    drag(x0 + 4, y0, x0 + 9, y0)
    check(at(hero) == (x0 + 6, y0), f"dragging 25 ft further stops at the edge of the box: 10 ft ({at(hero)})")
    drag(x0 + 6, y0, x0 + 9, y0)
    check(at(hero) == (x0 + 6, y0), "with 0 ft left it doesn't move at all")
    print("== Free move")
    pg.locator("#free-move").click(); pg.wait_for_timeout(300)
    drag(x0 + 6, y0, x0 + 14, y0)
    check(at(hero) == (x0 + 14, y0), "Free move: anywhere")
    pg.locator("#free-move").click()
    print("== Two actions when the DM rolls for a hero")
    me_ = next(c for c in call("GET", f"/api/encounters/{eid}")["combatants"] if c["name"] == hero)
    print("    debug conds", [(x["name"], x.get("extra_moves"), x.get("extra_total"), x.get("expired"), x.get("encounter_id")) for x in me_["conditions"]])
    codes = []
    for _ in range(3):
        r = pg.evaluate(f"""async () => {{ const r = await fetch('/api/rolls', {{method: 'POST', headers: {{'Content-Type': 'application/json'}},
          body: JSON.stringify({{check: {{type: 'attack', key: 0, combatant_id: {by[hero]['id']}}}}})}}); return [r.status, (await r.json()).error || ''] }}""")
        codes.append(r)
    check([c[0] for c in codes] == [201, 201, 403] and "2 actions" in codes[2][1], f"third attack refused ({codes})")
    pg.screenshot(path=SHOTS + "/dm_rules.png")
    ctx.close()

    print("== Phone: the map stays in view while scrolling")
    code = call("POST", f"/api/campaigns/{camp}/join-code", {"action": "new"})["join_code"]
    for pl in call("GET", f"/api/campaigns/{camp}/players")["players"]:
        if pl.get("character_id") == by[hero]["character_id"] and not pl.get("revoked"):
            call("DELETE", f"/api/players/{pl['id']}")
    ph = b.new_context(viewport={"width": 390, "height": 844}, **engine.mobile(), has_touch=True)
    pp = ph.new_page(); pp.on("pageerror", lambda e: problems.append(f"phone JS error: {e}"))
    pp.goto(LAN + "/join"); pp.fill("input[name=code]", code); pp.fill("input[name=name]", "Layout test")
    pp.wait_for_selector("#char-field:not([hidden])"); pp.select_option("select[name=character_id]", value=str(by[hero]["character_id"]))
    pp.click("button[type=submit]"); pp.wait_for_url(re.compile("/play")); pp.wait_for_timeout(2500)
    pp.screenshot(path=SHOTS + "/phone_top.png")
    pp.evaluate("window.scrollTo(0, 900)"); pp.wait_for_timeout(500)
    box = pp.locator("#stage").bounding_box()
    check(box and box["y"] >= -1 and box["y"] < 20 and box["height"] > 250, f"after scrolling, the map is still at the top ({box})")
    pp.screenshot(path=SHOTS + "/phone_scrolled.png")
    pp.locator("#map-size").click(); pp.wait_for_timeout(400)
    h2 = pp.locator("#stage").bounding_box()["height"]
    check(h2 > box["height"], f"Map size makes it bigger ({box['height']:.0f} -> {h2:.0f})")
    pp.locator("#map-size").click(); pp.wait_for_timeout(400)
    h3 = pp.locator("#stage").bounding_box()["height"]
    check(h3 < box["height"], f"and smaller ({h3:.0f})")
    pp.screenshot(path=SHOTS + "/phone_small.png")
    check(pp.locator("details.roll-fold").count() == 1 and not pp.locator("details.roll-fold").evaluate("d => d.open"), "saving throws & skills folded on the phone")
    ph.close(); b.close()
fails = [m for ok, m in results if not ok]
print(f"\n{len(results) - len(fails)} passed, {len(fails)} failed"); [print("FAILED:", f) for f in fails]
print("PROBLEMS:", problems)
