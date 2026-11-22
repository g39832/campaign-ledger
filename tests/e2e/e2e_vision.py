"""Line of sight and spotting, clicked through: on a made-up map the player's phone shows what the
heroes can see (40 ft, stopped by walls), remembered squares dimmed; an enemy shows only while
someone can see it; walking into view starts a fight with just that hero, the DM adds another hero
with one click, and rolls initiative."""
import json, os, re, urllib.request, uuid
from common import DM_URL, LAN_URL, SHOTS_DIR  # noqa: E402
from playwright.sync_api import sync_playwright
import engine

DM = DM_URL; LAN = LAN_URL
SHOTS = os.path.join(SHOTS_DIR, "vision"); os.makedirs(SHOTS, exist_ok=True)
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
MONI, LUX = chars["Moni Easter"], chars["Lux Fedelis"]
code = call("POST", f"/api/campaigns/{camp}/join-code", {"action": "new"})["join_code"]

# a made-up map turned into a long hall (y = 5) with a side passage, Lux waiting in a cupboard far off
st = call("POST", f"/api/campaigns/{camp}/dungeons", {"theme": "dungeon"})
mid, m = st["map"]["id"], st["map"]
call("POST", f"/api/maps/{mid}/terrain", {"cells": [[x, y] for x in range(m["cols"]) for y in range(m["rows"])], "value": "wall"})
call("POST", f"/api/maps/{mid}/terrain", {"cells": [[x, 5] for x in range(1, 36)] + [[20, 6], [20, 7], [2, 22]], "value": "stone"})
call("POST", f"/api/campaigns/{camp}/live-map", {"map_id": mid})
call("POST", f"/api/maps/{mid}/tokens", {"character_id": MONI["id"], "x": 1, "y": 5})
call("POST", f"/api/maps/{mid}/tokens", {"character_id": LUX["id"], "x": 2, "y": 22})
call("POST", f"/api/maps/{mid}/monsters", {"book": "Bandit", "x": 25, "y": 5, "hidden": True})
call("POST", f"/api/maps/{mid}/monsters", {"book": "Thug", "x": 20, "y": 7})
moni = next(t for t in call("GET", f"/api/maps/{mid}")["tokens"] if t["character_id"] == MONI["id"])

with sync_playwright() as p:
    b = engine.launch(p)
    w, h = SIZES[DEVICE]
    touch = DEVICE in ("phones", "tablets", "mixed")
    pctx = b.new_context(viewport={"width": w, "height": h}, **(engine.mobile() if touch else {}), has_touch=touch)
    pctx.add_init_script(CATCH_VIEW)
    pg = pctx.new_page(); pg.on("pageerror", lambda e: problems.append(f"player JS error: {e}"))
    pg.on("response", lambda r: r.status >= 500 and problems.append(f"player HTTP {r.status} {r.url}"))
    print(f"== [{engine.NAME}/{DEVICE}] the player's view of a long hall")
    pg.goto(LAN + "/join"); pg.fill("input[name=code]", code); pg.fill("input[name=name]", "Moni's player")
    pg.wait_for_selector("#char-field:not([hidden])"); pg.select_option("select[name=character_id]", value=str(MONI["id"]))
    pg.click("button[type=submit]"); pg.wait_for_url(re.compile("/play")); pg.wait_for_timeout(2500)
    call("POST", f"/api/tokens/{moni['id']}/move", {"x": 3, "y": 5, "free": True}); pg.wait_for_timeout(2500)
    vm = pg.evaluate("window.__view.map")
    cols = vm["cols"]
    lit = [x for x in range(cols) if vm["visible"][5 * cols + x] == "1"]
    check(lit and max(lit) == 3 + 8, f"she sees 40 ft down the hall: squares {min(lit)}..{max(lit)}")
    check(vm["visible"][4 * cols + 6] == "1" and vm["visible"][3 * cols + 6] != "1", "the hall's walls are seen, nothing behind them")
    check(not any(t["display"].startswith(("Bandit", "Thug")) for t in pg.evaluate("window.__view.tokens")), "no enemies in sight, none on her map")
    pg.screenshot(path=os.path.join(SHOTS, f"{engine.NAME}_{DEVICE}_hall.png"))
    call("POST", f"/api/tokens/{moni['id']}/move", {"x": 12, "y": 5, "free": True}); pg.wait_for_timeout(2500)
    vm = pg.evaluate("window.__view.map")
    check(vm["revealed"][5 * cols + 3] == "1" and vm["visible"][5 * cols + 3] != "1", "where she was is remembered, but out of sight now (drawn dimmed)")
    check(pg.evaluate(f"""() => {{ const v = window.__view, mm = v.map, c = v.canvas, r = c.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
        const at = (x, y) => {{ const px = (v.view.tx + (mm.offset_x + (x + .5) * mm.cell_px) * v.view.s) * dpr, py = (v.view.ty + (mm.offset_y + (y + .5) * mm.cell_px) * v.view.s) * dpr;
          const d = c.getContext('2d').getImageData(px, py, 1, 1).data; return d[0] + d[1] + d[2]; }};
        return at(2, 5) < at(14, 5); }}"""), "on screen, the remembered squares are darker than the ones she sees")
    pg.screenshot(path=os.path.join(SHOTS, f"{engine.NAME}_{DEVICE}_remembered.png"))

    print("== walking into view of the bandit: a fight with just Moni")
    dctx = b.new_context(viewport={"width": 1366, "height": 900}); dctx.add_init_script(CATCH_VIEW)
    dm = dctx.new_page(); dm.on("pageerror", lambda e: problems.append(f"DM JS error: {e}"))
    dm.goto(f"{DM}/map/{mid}"); dm.wait_for_selector("#dungeon-panel:not([hidden])"); dm.wait_for_timeout(2000)
    call("POST", f"/api/tokens/{moni['id']}/move", {"x": 18, "y": 5, "free": True}); pg.wait_for_timeout(3000)
    f = call("GET", f"/api/maps/{mid}")["map"]["dungeon"].get("fight")
    check(f and f["foes"] == ["Bandit"] and f["heroes"] == ["Moni Easter"], f"the bandit and Moni, nobody else ({f and f['what']})")
    check("Thug" not in str(f and f["foes"]), "the thug round the corner isn't in it")
    check(any(t["display"].startswith("Bandit") for t in pg.evaluate("window.__view.tokens")), "the bandit appears on her map")
    check("spots" in pg.locator("#turns").inner_text() or "spotted" in pg.locator("#turns").inner_text(), "her screen says who spotted whom")
    pg.screenshot(path=os.path.join(SHOTS, f"{engine.NAME}_{DEVICE}_spotted.png"))
    dm.wait_for_selector("#dungeon-panel .join-fight", timeout=10000)
    check("Lux" in dm.locator("#dungeon-panel .join-fight").inner_text(), "the DM sees Lux under 'Not in this fight yet'")
    dm.screenshot(path=os.path.join(SHOTS, f"{engine.NAME}_dm_join.png"))
    dm.locator(f"#dungeon-panel [data-join='{LUX['id']}']").click(); dm.wait_for_timeout(2000)
    names = sorted(c["name"] for c in call("GET", f"/api/encounters/{f['eid']}")["combatants"])
    check(names == ["Bandit", "Lux Fedelis", "Moni Easter"], f"one click: Lux joins ({names})")
    check(dm.locator("#dungeon-panel .join-fight").count() == 0, "and nobody's left out now")
    dm.locator("#dungeon-panel .room-fight").get_by_role("button", name=re.compile("Roll initiative")).click(); dm.wait_for_timeout(2500)
    enc = call("GET", f"/api/encounters/{f['eid']}")
    check(enc["encounter"]["status"] == "active" and all(c["init_roll"] is not None for c in enc["combatants"]), "Roll initiative & start: round 1")
    call("POST", f"/api/encounters/{f['eid']}/end")
    b.close()

for prob in problems:
    results.append((False, prob)); print("  FAIL " + prob)
ok = sum(1 for r in results if r[0])
print(f"e2e_vision.py [{engine.NAME}/{DEVICE}]: {ok} passed, {len(results) - ok} failed")
raise SystemExit(0 if ok == len(results) else 1)
