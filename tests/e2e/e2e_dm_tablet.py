"""E2E: the DM's battle map and combat screen on tablets (landscape and portrait)."""
import json, urllib.request, uuid
from common import APP_DIR, DM_URL, LAN_IP, LAN_URL, SHOTS_DIR, TMP_DIR  # noqa: E402,F401  (paths and addresses for this computer)
from playwright.sync_api import sync_playwright
import engine

DM = DM_URL
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
chars = {c["name"]: c for c in call("GET", f"/api/campaigns/{camp}/characters")["characters"]}
eid = call("POST", f"/api/campaigns/{camp}/encounters", {"name": "Tablet DM"})["encounter"]["id"]
call("POST", f"/api/encounters/{eid}/combatants", {"characters": [c["id"] for c in chars.values()], "quick": {"name": "Goblin", "max_hp": 20, "count": 3}})
mid = call("POST", f"/api/encounters/{eid}/map")["map_id"]
call("POST", f"/api/encounters/{eid}/start")
with sync_playwright() as p:
    b = engine.launch(p)
    for w, hgt, name in ((1024, 768, "iPad landscape"), (1180, 820, "iPad Air landscape"), (1280, 800, "Android tablet landscape"), (768, 1024, "iPad portrait")):
        ctx = b.new_context(viewport={"width": w, "height": hgt}, has_touch=True)
        pg = ctx.new_page(); pg.on("pageerror", lambda e: problems.append(f"JS error: {e}"))
        pg.goto(f"{DM}/map/{mid}"); pg.wait_for_timeout(1500)
        stage, side = pg.locator("#stage").bounding_box(), pg.locator(".map-side").first.bounding_box()
        beside = side["x"] >= stage["x"] + stage["width"] - 5
        if w > hgt:
            check(beside, f"{name} {w}x{hgt}: the map's side menu is beside the map (map {stage['width']:.0f} wide, menu at x={side['x']:.0f})")
            pg.evaluate("window.scrollTo(0, 99999)"); pg.wait_for_timeout(500)
            box = pg.locator("#stage").bounding_box()
            check(box["y"] >= 0 and box["y"] + box["height"] <= hgt + 2, f"{name}: scrolled down the menu, the map stays in view (y={box['y']:.0f}, h={box['height']:.0f})")
        else:
            check(stage["height"] > 300, f"{name}: map on top, {stage['height']:.0f}px tall")
        pg.screenshot(path=SHOTS + f"/dm_tablet_{w}.png")
        pg.goto(f"{DM}/combat/{eid}"); pg.wait_for_timeout(1000)
        sw = pg.evaluate("document.documentElement.scrollWidth")
        check(sw <= w + 1, f"{name}: the combat screen fits the width ({sw} <= {w})")
        ctx.close()
    b.close()
fails = [m for ok, m in results if not ok]
print(f"\n{len(results) - len(fails)} passed, {len(fails)} failed"); [print("FAILED:", f) for f in fails]
print("PROBLEMS:", problems)
