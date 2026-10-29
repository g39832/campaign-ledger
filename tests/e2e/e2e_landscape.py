"""E2E: a phone in landscape keeps the map in view (left) while the character scrolls (right);
portrait is unchanged."""
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
if not call("GET", "/api/campaigns")["campaigns"][0].get("live_map_id"):
    mid = call("GET", f"/api/campaigns/{camp}/maps")["maps"][0]["id"]
    call("POST", f"/api/campaigns/{camp}/live-map", {"map_id": mid})
code = call("POST", f"/api/campaigns/{camp}/join-code", {"action": "new"})["join_code"]
hero = next(c for c in call("GET", f"/api/campaigns/{camp}/characters")["characters"] if c["name"] == "Test Hero")
for e in call("GET", f"/api/campaigns/{camp}/encounters")["encounters"]:
    if e["status"] == "active":
        call("POST", f"/api/encounters/{e['id']}/end")
eid = call("POST", f"/api/campaigns/{camp}/encounters", {"name": "Tablet"})["encounter"]["id"]
call("POST", f"/api/encounters/{eid}/combatants", {"characters": [hero["id"]], "quick": {"name": "Goblin", "max_hp": 30, "ac": 10, "count": 1}})
mid = call("POST", f"/api/encounters/{eid}/map")["map_id"]
call("POST", f"/api/campaigns/{camp}/live-map", {"map_id": mid})
call("POST", f"/api/encounters/{eid}/start")
cb = next(c["id"] for c in call("GET", f"/api/encounters/{eid}")["combatants"] if c["name"] == "Test Hero")
for pl in call("GET", f"/api/campaigns/{camp}/players")["players"]:
    if pl.get("character_id") == hero["id"] and not pl.get("revoked"):
        call("DELETE", f"/api/players/{pl['id']}")
with sync_playwright() as p:
    b = engine.launch(p)
    ctx = b.new_context(viewport={"width": 844, "height": 390}, **engine.mobile(), has_touch=True)
    pp = ctx.new_page(); pp.on("pageerror", lambda e: problems.append(f"JS error: {e}"))
    pp.goto(LAN + "/join"); pp.fill("input[name=code]", code); pp.fill("input[name=name]", "Landscape")
    pp.wait_for_selector("#char-field:not([hidden])"); pp.select_option("select[name=character_id]", value=str(hero["id"]))
    pp.click("button[type=submit]"); pp.wait_for_url(re.compile("/play")); pp.wait_for_timeout(2500)
    st, me = pp.locator("#stage").bounding_box(), pp.locator("#me").bounding_box()
    check(me["x"] > st["x"] + st["width"] - 5, f"landscape: map on the left, character on the right (map {st['width']:.0f} wide, panel at x={me['x']:.0f})")
    check(st["height"] > 330, f"the map fills the height ({st['height']:.0f} of 390)")
    pp.screenshot(path=SHOTS + "/landscape_top.png")
    for y in (600, 1400, 99999):
        pp.evaluate(f"window.scrollTo(0, {y})"); pp.wait_for_timeout(400)
        box = pp.locator("#stage").bounding_box()
        check(0 <= box["y"] <= 12 and box["height"] > 330, f"scrolled to {y}: the map came down with it (top at {box['y']:.0f})")
    pp.screenshot(path=SHOTS + "/landscape_scrolled.png")
    for w, hgt, name in ((1024, 768, "iPad landscape"), (1180, 820, "iPad Air landscape"), (1280, 800, "Android tablet landscape"), (1366, 1024, "iPad Pro landscape")):
        pp.set_viewport_size({"width": w, "height": hgt}); pp.evaluate("window.scrollTo(0, 0)"); pp.wait_for_timeout(600)
        st, me = pp.locator("#stage").bounding_box(), pp.locator("#me").bounding_box()
        check(me["x"] > st["x"] + st["width"] - 5, f"{name} {w}x{hgt}: map beside the menu")
        pp.evaluate("window.scrollTo(0, 99999)"); pp.wait_for_timeout(500)
        box = pp.locator("#stage").bounding_box()
        check(box["y"] >= 0 and box["y"] + box["height"] <= hgt + 2 and box["height"] > hgt * 0.6, f"{name}: scrolled to the bottom, the map is still fully in view (y={box['y']:.0f}, h={box['height']:.0f})")
        pp.screenshot(path=SHOTS + f"/tablet_{w}.png")
    print("== End my turn")
    call("POST", f"/api/encounters/{eid}/set-turn", {"combatant_id": cb})
    pp.set_viewport_size({"width": 390, "height": 844}); pp.evaluate("window.scrollTo(0, 0)"); pp.wait_for_timeout(3000)
    btn = pp.locator("#turns .end-turn-btn")
    check(btn.count() == 1, "an End my turn button on her turn")
    btn.click(); pp.wait_for_timeout(400)
    check("Tap again" in pp.locator("#turns .end-turn-btn").inner_text(), "first tap only arms it")
    pp.locator("#turns .end-turn-btn").click(); pp.wait_for_timeout(2500)
    cur = call("GET", f"/api/encounters/{eid}")["encounter"]["current_id"]
    check(cur != cb and pp.locator(".end-turn-btn").count() == 0, "second tap ends her turn; the button goes away")
    pp.set_viewport_size({"width": 390, "height": 844}); pp.evaluate("window.scrollTo(0, 0)"); pp.wait_for_timeout(600)
    st, me = pp.locator("#stage").bounding_box(), pp.locator("#me").bounding_box()
    check(me["y"] > st["y"] + st["height"] - 5 and 300 < st["height"] < 420, f"turned back to portrait: map on top again ({st['height']:.0f} tall)")
    b.close()
fails = [m for ok, m in results if not ok]
print(f"\n{len(results) - len(fails)} passed, {len(fails)} failed"); [print("FAILED:", f) for f in fails]
print("PROBLEMS:", problems)
