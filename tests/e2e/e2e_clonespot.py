"""Grayson's live fight (Restless crypt), copied: Yamato's player picks where the clone appears,
on a phone and on a laptop."""
import json, re, urllib.request, uuid
from common import APP_DIR, DM_URL, LAN_IP, LAN_URL, SHOTS_DIR, TMP_DIR  # noqa: E402,F401  (paths and addresses for this computer)
from playwright.sync_api import sync_playwright
import engine

DM = DM_URL; LAN = LAN_URL; EID = 4
CATCH_VIEW = """
(() => { let real; Object.defineProperty(window, 'MapView', { configurable: true, get() { return real; },
  set(v) { real = class extends v { constructor(...a) { super(...a); window.__view = this; } }; } }); })();
"""


def call(m, path, body=None):
    data = json.dumps(dict(body or {}, op_id=uuid.uuid4().hex)).encode() if m != "GET" else None
    return json.load(urllib.request.urlopen(urllib.request.Request(DM + path, data=data, method=m, headers={"Content-Type": "application/json"})))


for e in call("GET", "/api/campaigns/1/encounters")["encounters"]:
    if e["status"] == "active":
        call("POST", f"/api/encounters/{e['id']}/end")
chars = {c["name"]: c for c in call("GET", "/api/campaigns/1/characters")["characters"]}
EID = call("POST", "/api/campaigns/1/encounters", {"name": "Clone spot"})["encounter"]["id"]
call("POST", f"/api/encounters/{EID}/combatants", {"characters": [chars[n]["id"] for n in ("Yamato", "Lux Fedelis")], "quick": {"name": "Ghoul", "max_hp": 50, "ac": 10, "count": 2}})
mid = call("POST", f"/api/encounters/{EID}/map")["map_id"]
call("PATCH", f"/api/maps/{mid}", {"changes": {"cols": {"to": 30}, "rows": {"to": 18}}})
call("POST", "/api/campaigns/1/live-map", {"map_id": mid})
call("POST", f"/api/encounters/{EID}/start")
st = call("GET", f"/api/encounters/{EID}")
yam = next(c for c in st["combatants"] if c["name"] == "Yamato")
call("POST", f"/api/encounters/{EID}/set-turn", {"combatant_id": yam["id"]})
toks = {t["display"]: t for t in call("GET", f"/api/maps/{mid}")["tokens"]}
for n, (x, y) in {"Yamato": (12, 8), "Lux Fedelis": (10, 4), "Ghoul 1": (20, 8), "Ghoul 2": (20, 12)}.items():
    call("POST", f"/api/tokens/{toks[n]['id']}/move", {"x": x, "y": y, "free": True})
# like a real map: a hidden marker (a trap the players can't see) where the player will tap
call("POST", f"/api/maps/{mid}/tokens", {"kind": "marker", "label": "Trap", "x": 9, "y": 6, "hidden": True})
call("POST", f"/api/encounters/{EID}/cast", {"caster_id": yam["id"], "spell": 0, "targets": []})  # a clone from before, then beaten
for pl in call("GET", "/api/campaigns/1/players")["players"]:
    call("DELETE", f"/api/players/{pl['id']}")
code = call("POST", "/api/campaigns/1/join-code", {"action": "new"})["join_code"]
log, results = [], []


def check(c, msg):
    results.append((bool(c), msg)); print(("  PASS " if c else "  FAIL ") + msg, flush=True)
with sync_playwright() as p:
    b = engine.launch(p)
    for kind, opts in (("phone", dict(viewport={"width": 390, "height": 844}, **engine.mobile(), has_touch=True)), ("laptop", dict(viewport={"width": 1366, "height": 768}))):
        # fresh: no clones, nothing recharging, Yamato's turn
        st = call("GET", f"/api/encounters/{EID}")
        for c in st["combatants"]:
            if "clone" in c["name"].lower() and c["status"] not in ("dead", "defeated"):
                call("POST", f"/api/combatants/{c['id']}/hp", {"op": "damage", "amount": 99})
        y = next(c for c in call("GET", f"/api/encounters/{EID}")["combatants"] if c["name"] == "Yamato")
        for x in y["conditions"]:
            if x.get("cooldown"):
                call("DELETE", f"/api/combatants/{y['id']}/conditions/{x['id']}")
        for _ in range(30):  # on to Yamato's next turn: fresh actions
            if call("POST", f"/api/encounters/{EID}/next")["encounter"]["current_id"] == yam["id"]:
                break
        for pl in call("GET", "/api/campaigns/1/players")["players"]:
            call("DELETE", f"/api/players/{pl['id']}")
        ctx = b.new_context(**opts); ctx.add_init_script(CATCH_VIEW)
        def patch(route):
            r = route.fetch(); body = r.text()
            body = body.replace("k.busy = true; render();\n    try {\n      const d = await api(\"POST\", \"/api/play/cast\"",
                                "console.log('CASTNOW ' + JSON.stringify({ at: k.at, map: !!S.map })); k.busy = true; render();\n    try {\n      const d = await api(\"POST\", \"/api/play/cast\"")
            body = body.replace("casting.at = [x, y];", "console.log('ONPLACE ' + x + ',' + y); casting.at = [x, y];")
            route.fulfill(response=r, body=body)
        ctx.route(re.compile(r".*/static/js/play\.js.*"), patch)
        pg = ctx.new_page(); pg.on("pageerror", lambda e: log.append(f"JS error: {e}"))
        pg.on("console", lambda m: (m.type == "error" or "CASTNOW" in m.text or "ONPLACE" in m.text) and print("   console:", m.text))
        pg.goto(LAN + "/join"); pg.fill("input[name=code]", code); pg.fill("input[name=name]", "Test")
        pg.wait_for_selector("#char-field:not([hidden])"); pg.select_option("select[name=character_id]", value=str(yam["character_id"]))
        pg.click("button[type=submit]"); pg.wait_for_url(re.compile("/play")); pg.wait_for_timeout(3000)
        print(f"== {kind}: cards", [x.split(chr(10))[0] for x in pg.locator("#turns .your-moves .fight-act").all_inner_texts()])
        pg.locator("#turns .your-moves").scroll_into_view_if_needed(); pg.evaluate("window.scrollBy(0, 400)"); pg.wait_for_timeout(300)
        pg.locator("#turns .your-moves .fight-act").filter(has=pg.locator("b", has_text=re.compile(r"^\s*Echo Knight\s*$"))).first.click()
        pg.wait_for_timeout(600)
        print("   tool:", pg.evaluate("window.__view.tool"), "| hint:", pg.locator("#hint").inner_text()[:90])
        print("   box:", pg.locator("#cast-box").inner_text().replace(chr(10), " / ")[:200] if pg.locator("#cast-box").count() else "NO CAST BOX")
        toks = call("GET", f"/api/maps/{mid}")["tokens"]; me = next(t for t in toks if t["display"] == "Yamato")
        taken = {(t["x"], t["y"]) for t in toks if not (kind == "phone" and t["display"] == "Trap")}  # the phone taps the hidden trap's square
        spot = next((me["x"] + dx, me["y"] + dy) for dx, dy in (((-3, -2), (-3, 2)) if kind == "phone" else ((-3, 2), (3, -3))) if (me["x"] + dx, me["y"] + dy) not in taken)
        # like a real phone: he's scrolled down to his moves; tapping the spell brings the map into view
        pg.wait_for_timeout(900)
        top = pg.evaluate("document.querySelector('#stage').getBoundingClientRect().top")
        print("   map's top after tapping the spell:", round(top), "(on screen)" if top > -5 else "(OFF SCREEN)")
        xy = pg.evaluate(f"""() => {{ const v = window.__view, m = v.map, r = v.canvas.getBoundingClientRect();
          return [r.left + v.view.tx + (m.offset_x + ({spot[0]} + .5) * m.cell_px) * v.view.s, r.top + v.view.ty + (m.offset_y + ({spot[1]} + .5) * m.cell_px) * v.view.s]; }}""")
        if kind == "phone":
            pg.touchscreen.tap(*xy)
        else:
            pg.mouse.click(*xy)
        pg.wait_for_timeout(3000)
        cl = [(t["display"], t["x"], t["y"]) for t in call("GET", f"/api/maps/{mid}")["tokens"] if "clone" in t["display"].lower()]
        check(any((x, y) == spot for _, x, y in cl), f"{kind}: the clone appears on the square he tapped {spot} ({cl})")
        ctx.close()
    def fresh():
        for c in call("GET", f"/api/encounters/{EID}")["combatants"]:
            if "clone" in c["name"].lower() and c["status"] not in ("dead", "defeated"):
                call("POST", f"/api/combatants/{c['id']}/hp", {"op": "damage", "amount": 99})
        y = next(c for c in call("GET", f"/api/encounters/{EID}")["combatants"] if c["name"] == "Yamato")
        for x in y["conditions"]:
            if x.get("cooldown"):
                call("DELETE", f"/api/combatants/{y['id']}/conditions/{x['id']}")
        for _ in range(30):
            if call("POST", f"/api/encounters/{EID}/next")["encounter"]["current_id"] == yam["id"]:
                break

    def screen(pg, cx, cy):
        return pg.evaluate(f"""() => {{ const v = window.__view, m = v.map, r = v.canvas.getBoundingClientRect();
          return [r.left + v.view.tx + (m.offset_x + ({cx} + .5) * m.cell_px) * v.view.s, r.top + v.view.ty + (m.offset_y + ({cy} + .5) * m.cell_px) * v.view.s]; }}""")

    # the DM's map on a tablet, with a finger
    fresh()
    ctx = b.new_context(viewport={"width": 1180, "height": 820}, is_mobile=True, has_touch=True); ctx.add_init_script(CATCH_VIEW)
    dm = ctx.new_page(); dm.on("pageerror", lambda e: log.append(f"DM JS error: {e}"))
    dm.goto(DM + f"/map/{mid}"); dm.wait_for_timeout(500)
    dm.evaluate(f"localStorage.setItem('combat-sel-{EID}', '{yam['id']}')"); dm.reload(); dm.wait_for_selector(".fight-act"); dm.wait_for_timeout(800)
    btn = dm.locator(".fight-act").filter(has=dm.locator("b", has_text=re.compile(r"^\s*Phantasaml force\s*$"))).first
    btn.tap(); dm.wait_for_timeout(300)
    if "click the square" not in dm.locator("#hint").inner_text():
        btn.tap(); dm.wait_for_timeout(300)
    print("== DM tablet: hint:", dm.locator("#hint").inner_text()[:90])
    dm.touchscreen.tap(*screen(dm, 6, 13)); dm.wait_for_timeout(2500)
    cl = [(t["display"], t["x"], t["y"]) for t in call("GET", f"/api/maps/{mid}")["tokens"] if "clone" in t["display"].lower() and t["x"] == 6 and t["y"] == 13]
    check(cl, f"DM tablet: the clone appears on the square tapped with a finger (6, 13) ({cl})")
    ctx.close()
    # fog: Yamato's phone can only pick squares he can see
    fresh()
    call("PATCH", f"/api/maps/{mid}", {"changes": {"fog_enabled": {"from": False, "to": True}}})
    call("POST", f"/api/maps/{mid}/fog", {"cells": [[x, y] for x in range(8, 17) for y in range(4, 13)], "reveal": True})
    for pl in call("GET", "/api/campaigns/1/players")["players"]:
        call("DELETE", f"/api/players/{pl['id']}")
    ctx = b.new_context(viewport={"width": 390, "height": 844}, **engine.mobile(), has_touch=True); ctx.add_init_script(CATCH_VIEW)
    pg = ctx.new_page()
    pg.goto(LAN + "/join"); pg.fill("input[name=code]", code); pg.fill("input[name=name]", "Test")
    pg.wait_for_selector("#char-field:not([hidden])"); pg.select_option("select[name=character_id]", value=str(yam["character_id"]))
    pg.click("button[type=submit]"); pg.wait_for_url(re.compile("/play")); pg.wait_for_timeout(3000)
    pg.locator("#turns .your-moves .fight-act").filter(has=pg.locator("b", has_text=re.compile(r"^\s*Phantasaml force\s*$"))).first.click(); pg.wait_for_timeout(500)
    pg.evaluate("window.scrollTo(0, 0)"); pg.touchscreen.tap(*screen(pg, 2, 2)); pg.wait_for_timeout(500)
    check(any("can't see that square" in t for t in pg.locator(".toast").all_inner_texts()) and pg.evaluate("window.__view.mark") is None,
          "with fog, tapping a square he can't see is refused right away")
    pg.touchscreen.tap(*screen(pg, 14, 6)); pg.wait_for_timeout(3000)
    cl = [t for t in call("GET", f"/api/maps/{mid}")["tokens"] if "clone" in t["display"].lower() and (t["x"], t["y"]) == (14, 6)]
    check(cl, "with fog, a square he can see works")
    b.close()
fails = [m for ok, m in results if not ok]
print(f"\n{len(results) - len(fails)} passed, {len(fails)} failed"); [print("FAILED:", f) for f in fails]
print("PROBLEMS:", log)
