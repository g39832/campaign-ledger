"""E2E: Yamato aims Wide Slash's cone on his phone: it shows, he drags to turn it, sees who it
catches (teammates flagged, can be spared), then Uses it."""
import json, re, urllib.request, uuid
from common import APP_DIR, DM_URL, LAN_IP, LAN_URL, SHOTS_DIR, TMP_DIR  # noqa: E402,F401  (paths and addresses for this computer)
from playwright.sync_api import sync_playwright
import engine

DM = DM_URL; LAN = LAN_URL
SHOTS = SHOTS_DIR
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
eid = call("POST", f"/api/campaigns/{camp}/encounters", {"name": "Cone"})["encounter"]["id"]
call("POST", f"/api/encounters/{eid}/combatants", {"characters": [chars["Yamato"]["id"], chars["Gnocchi"]["id"]],
                                                   "quick": {"name": "Goblin", "max_hp": 300, "ac": 3, "count": 3}})
mid = call("POST", f"/api/encounters/{eid}/map")["map_id"]
call("PATCH", f"/api/maps/{mid}", {"changes": {"cols": {"to": 20}, "rows": {"to": 12}}})
toks = {t["display"]: t for t in call("GET", f"/api/maps/{mid}")["tokens"]}
for n, (x, y) in {"Yamato": (5, 5), "Goblin 1": (7, 5), "Goblin 2": (8, 4), "Gnocchi": (6, 5), "Goblin 3": (5, 9)}.items():
    call("POST", f"/api/tokens/{toks[n]['id']}/move", {"x": x, "y": y, "free": True})
call("POST", f"/api/campaigns/{camp}/live-map", {"map_id": mid})
call("POST", f"/api/encounters/{eid}/start")
by = {c["name"]: c for c in call("GET", f"/api/encounters/{eid}")["combatants"]}
for _ in range(8):
    if call("POST", f"/api/encounters/{eid}/next")["encounter"]["current_id"] == by["Yamato"]["id"]:
        break
code = call("POST", f"/api/campaigns/{camp}/join-code", {"action": "new"})["join_code"]
with sync_playwright() as p:
    b = engine.launch(p)
    ctx = b.new_context(viewport={"width": 390, "height": 844}, **engine.mobile(), has_touch=True); ctx.add_init_script(CATCH_VIEW)
    ph = ctx.new_page(); ph.on("pageerror", lambda e: problems.append(f"JS error: {e}"))
    ph.goto(LAN + "/join"); ph.fill("input[name=code]", code); ph.fill("input[name=name]", "Yamato cone")
    ph.wait_for_selector("#char-field:not([hidden])"); ph.select_option("select[name=character_id]", value=str(chars["Yamato"]["id"]))
    ph.click("button[type=submit]"); ph.wait_for_url(re.compile("/play")); ph.wait_for_timeout(3000)

    def screen(cx, cy):
        ph.evaluate("window.scrollTo(0, 0)"); ph.wait_for_timeout(200)
        return ph.evaluate(f"""() => {{ const v = window.__view, m = v.map, r = v.canvas.getBoundingClientRect();
          return [r.left + v.view.tx + (m.offset_x + ({cx} + .5) * m.cell_px) * v.view.s, r.top + v.view.ty + (m.offset_y + ({cy} + .5) * m.cell_px) * v.view.s]; }}""")

    card = ph.locator(".move-card").filter(has=ph.locator("b", has_text=re.compile(r"^\s*Wide Slash\s*$"))).first
    card.get_by_role("button", name=re.compile("Use")).click(); ph.wait_for_timeout(800)
    check(ph.evaluate("!!window.__view.aim && window.__view.aim.shape.kind === 'cone'"), "tapping Use shows the cone on his map")
    box = ph.locator("#use-box").inner_text()
    print("    pointing at the nearest goblin:", box.replace("\n", " / ")[:160])
    check("Goblin 1" in box and "Gnocchi" in box and "ally" in box, "it lists who's in it, Gnocchi flagged as an ally")
    ph.locator("#stage").screenshot(path=SHOTS + "/phone_cone_1.png")
    # drag to point it down at Goblin 3
    a, z = screen(6, 5), screen(5, 9)
    ph.mouse.move(*a); ph.mouse.down(); ph.mouse.move(*z, steps=8); ph.mouse.up(); ph.wait_for_timeout(600)
    box = ph.locator("#use-box").inner_text()
    print("    turned down:", box.replace("\n", " / ")[:160])
    check("Goblin 3" in box and "Goblin 1" not in box, "dragging turns the cone: now it catches Goblin 3")
    ph.locator("#stage").screenshot(path=SHOTS + "/phone_cone_2.png")
    a, z = screen(5, 9), screen(8, 5)
    ph.mouse.move(*a); ph.mouse.down(); ph.mouse.move(*z, steps=8); ph.mouse.up(); ph.wait_for_timeout(600)
    g = ph.locator("#use-box").get_by_role("button", name=re.compile("Gnocchi"))
    if g.count():
        g.click(); ph.wait_for_timeout(300)
    n_before = ph.locator("#use-box").get_by_role("button", name=re.compile("^Use on")).inner_text()
    print("    ", n_before)
    g0 = next(c for c in call("GET", f"/api/encounters/{eid}")["combatants"] if c["name"] == "Gnocchi")["hp"]
    ph.locator("#use-box").get_by_role("button", name=re.compile("^Use on")).click()
    ph.wait_for_selector("#use-box button:has-text('Done')", timeout=30000)
    res = ph.locator("#use-box").inner_text()
    print("    result:", res.replace("\n", " / ")[:200])
    check("Goblin" in res and "Gnocchi" not in res, "Use: the goblins in the cone are hit; spared Gnocchi isn't")
    check(next(c for c in call("GET", f"/api/encounters/{eid}")["combatants"] if c["name"] == "Gnocchi")["hp"] == g0, "Gnocchi's HP untouched")
    check(not ph.evaluate("!!window.__view.aim"), "the cone goes away after")
    b.close()
fails = [m for ok, m in results if not ok]
print(f"\n{len(results) - len(fails)} passed, {len(fails)} failed"); [print("FAILED:", f) for f in fails]
print("PROBLEMS:", problems)
