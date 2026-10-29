"""Instant updates: a change shows on other screens right away (a player's phone, the DM's map),
not on the next 1.5-3 s check; and with the instant connection blocked, the regular checks
still bring it in."""
import json, re, time, urllib.request, uuid
from playwright.sync_api import sync_playwright
from common import DM_URL, LAN_URL  # noqa: E402
import engine

CATCH_VIEW = """
(() => { let real; Object.defineProperty(window, 'MapView', { configurable: true, get() { return real; },
  set(v) { real = class extends v { constructor(...a) { super(...a); window.__view = this; } }; } }); })();
"""
results, problems = [], []


def call(m, path, body=None):
    data = json.dumps(dict(body or {}, op_id=uuid.uuid4().hex)).encode() if m != "GET" else None
    return json.load(urllib.request.urlopen(urllib.request.Request(DM_URL + path, data=data, method=m, headers={"Content-Type": "application/json"})))


def check(c, msg):
    results.append((bool(c), msg)); print(("  PASS " if c else "  FAIL ") + msg, flush=True)


for e in call("GET", "/api/campaigns/1/encounters")["encounters"]:
    if e["status"] == "active":
        call("POST", f"/api/encounters/{e['id']}/end")
for pl in call("GET", "/api/campaigns/1/players")["players"]:
    call("DELETE", f"/api/players/{pl['id']}")
chars = {c["name"]: c for c in call("GET", "/api/campaigns/1/characters")["characters"]}
eid = call("POST", "/api/campaigns/1/encounters", {"name": "Instant"})["encounter"]["id"]
call("POST", f"/api/encounters/{eid}/combatants", {"characters": [chars["Lux Fedelis"]["id"]], "quick": {"name": "Goblin", "max_hp": 20, "ac": 10, "count": 1}})
mid = call("POST", f"/api/encounters/{eid}/map")["map_id"]
call("POST", "/api/campaigns/1/live-map", {"map_id": mid})
call("POST", f"/api/encounters/{eid}/start")
code = call("POST", "/api/campaigns/1/join-code", {"action": "new"})["join_code"]
gob = next(t for t in call("GET", f"/api/maps/{mid}")["tokens"] if t["display"].startswith("Goblin"))


def pos_on(page):
    return page.evaluate("() => { const t = (window.__view.tokens || []).find((t) => (t.display || '').startsWith('Goblin')); return t ? [t.x, t.y] : null; }")


def timed_move(pages, x, y):
    call("POST", f"/api/tokens/{gob['id']}/move", {"x": x, "y": y, "free": True})
    t0 = time.time(); seen = {}
    while time.time() - t0 < 15 and len(seen) < len(pages):
        for name, pg in pages.items():
            if name not in seen and pos_on(pg) == [x, y]:
                seen[name] = time.time() - t0
        time.sleep(0.03)
    return seen


with sync_playwright() as p:
    b = engine.launch(p)
    ph = b.new_context(viewport={"width": 390, "height": 844}, **engine.mobile(), has_touch=True); ph.add_init_script(CATCH_VIEW)
    pp = ph.new_page(); pp.on("pageerror", lambda e: problems.append(f"phone JS error: {e}"))
    pp.goto(LAN_URL + "/join"); pp.fill("input[name=code]", code); pp.fill("input[name=name]", "Lux plays")
    pp.wait_for_selector("#char-field:not([hidden])"); pp.select_option("select[name=character_id]", value=str(chars["Lux Fedelis"]["id"]))
    pp.click("button[type=submit]"); pp.wait_for_url(re.compile("/play")); pp.wait_for_timeout(2500)
    dctx = b.new_context(viewport={"width": 1300, "height": 900}); dctx.add_init_script(CATCH_VIEW)
    dm = dctx.new_page(); dm.on("pageerror", lambda e: problems.append(f"DM JS error: {e}"))
    dm.goto(DM_URL + f"/map/{mid}"); dm.wait_for_timeout(2500)
    check(pp.evaluate("L.live.connected") and dm.evaluate("L.live.connected"), "both screens have the instant connection")
    times = []
    for i, (x, y) in enumerate(((5, 5), (6, 3), (2, 7), (8, 8), (4, 2))):
        seen = timed_move({"phone": pp, "dm": dm}, x, y)
        times.append(seen)
    worst = max(max(s.values()) if s else 99 for s in times)
    avg = sum(sum(s.values()) / max(1, len(s)) for s in times) / len(times)
    print(f"    move -> on screen: average {avg:.2f} s, slowest {worst:.2f} s ({times})")
    check(all(len(s) == 2 for s in times) and worst < 2 and avg < 1, f"a move shows on the phone and the DM's map within about a second (slowest {worst:.2f} s, average {avg:.2f} s)")
    # HP and a roll: the phone's turn order / dice pick them up at once too
    gcb = next(c for c in call("GET", f"/api/encounters/{eid}")["combatants"] if c["name"].startswith("Goblin"))
    t0 = time.time()
    call("POST", f"/api/encounters/{eid}/damage", {"targets": [gcb["id"]], "amount": 15})
    pp.wait_for_function("() => /bloodied/i.test(document.querySelector('#turns').innerText)", timeout=8000)
    check(time.time() - t0 < 1.5, f"an HP change shows on the phone right away ({time.time() - t0:.2f} s)")
    # with the instant connection blocked, the regular checks still bring changes in
    fb = b.new_context(viewport={"width": 1300, "height": 900}); fb.add_init_script(CATCH_VIEW)
    fb.route(re.compile(r".*/api/play/events.*"), lambda route: route.abort())
    slow = fb.new_page(); slow.goto(DM_URL + f"/map/{mid}"); slow.wait_for_timeout(2500)
    check(not slow.evaluate("L.live.connected"), "a screen without the instant connection (blocked)")
    seen = timed_move({"fallback": slow}, 3, 3)
    check(seen and seen["fallback"] < 4, f"still gets the change from its regular checks ({seen})")
    b.close()
fails = [m for ok, m in results if not ok]
print(f"\n{len(results) - len(fails)} passed, {len(fails)} failed"); [print("FAILED:", f) for f in fails]
print("PROBLEMS:", problems)
