"""E2E (2026-11-15): with no map shared, the player screen shows the campaign's emblem (a hollow star
in an orbit) with the campaign name, instead of an empty box. Sharing a map hides it again."""
import json, re, urllib.request, uuid
from common import DM_URL, LAN_URL, SHOTS_DIR  # noqa: E402
from playwright.sync_api import sync_playwright
import engine

DM, LAN, SHOTS = DM_URL, LAN_URL, SHOTS_DIR
results, problems = [], []


def call(m, path, body=None):
    data = json.dumps(dict(body or {}, op_id=uuid.uuid4().hex)).encode() if m != "GET" else None
    return json.load(urllib.request.urlopen(urllib.request.Request(DM + path, data=data, method=m, headers={"Content-Type": "application/json"})))


def check(c, msg):
    results.append((bool(c), msg)); print(("  PASS " if c else "  FAIL ") + msg, flush=True)


camp = 1
live = call("GET", f"/api/campaigns/{camp}/maps")
for pl in call("GET", f"/api/campaigns/{camp}/players")["players"]:
    call("DELETE", f"/api/players/{pl['id']}")
call("POST", f"/api/campaigns/{camp}/live-map", {"map_id": None})
chars = {c["name"]: c for c in call("GET", f"/api/campaigns/{camp}/characters")["characters"]}
code = call("POST", f"/api/campaigns/{camp}/join-code", {"action": "new"})["join_code"]
with sync_playwright() as p:
    b = engine.launch(p)
    for theme in ("dark", "light"):
        ctx = b.new_context(viewport={"width": 390, "height": 844}, **engine.mobile(), has_touch=True, color_scheme=theme)
        ph = ctx.new_page(); ph.on("pageerror", lambda e: problems.append(f"phone JS error: {e}"))
        ph.goto(LAN + "/join"); ph.fill("input[name=code]", code); ph.fill("input[name=name]", "Logo " + theme)
        ph.wait_for_selector("#char-field:not([hidden])"); ph.select_option("select[name=character_id]", value=str(chars["Lux Fedelis" if theme == "dark" else "Gnocchi"]["id"]))
        ph.click("button[type=submit]"); ph.wait_for_url(re.compile("/play")); ph.wait_for_timeout(2500)
        logo = ph.locator("#no-map")
        check(logo.is_visible() and ph.locator("#no-map .nm-emblem").is_visible(), f"[{theme}] no map shared: the emblem shows")
        check(ph.locator("#no-map-title").inner_text().strip() == "The Hollow Star", f"[{theme}] with the campaign's name")
        box = ph.locator("#no-map .nm-emblem").bounding_box()
        check(box and box["width"] > 150 and box["x"] >= 0 and box["x"] + box["width"] <= 390, f"[{theme}] big enough and fits the phone ({box and int(box['width'])} px)")
        ph.screenshot(path=f"{SHOTS}/no_map_logo_{theme}_{engine.NAME}.png")
        if theme == "dark":
            call("POST", f"/api/campaigns/{camp}/live-map", {"map_id": 7})
            ph.wait_for_timeout(3500)
            check(not ph.locator("#no-map").is_visible(), "the DM shares a map: the emblem goes and the map shows")
            call("POST", f"/api/campaigns/{camp}/live-map", {"map_id": None})
            ph.wait_for_timeout(3500)
            check(ph.locator("#no-map").is_visible(), "and comes back when the map is taken away")
        players = call("GET", f"/api/campaigns/{camp}/players")["players"]
        for pl in players:
            call("DELETE", f"/api/players/{pl['id']}")
        ctx.close()
    b.close()

check(not problems, "no page errors" + ("" if not problems else ": " + "; ".join(problems[:3])))
print(f"e2e_no_map_logo.py [{engine.NAME}]: {sum(1 for ok, _ in results if ok)} passed, {sum(1 for ok, _ in results if not ok)} failed")
