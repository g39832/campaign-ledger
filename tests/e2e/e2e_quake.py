"""E2E: Harlan Voss's Earth Shattter (40 ft radius) shakes the map and splits the ground across
the whole radius, on the DM's map and on a player's phone."""
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
QUAKE = "() => { const q = (window.__view && window.__view.fx || []).find((f) => f.type === 'quake'); return q ? { x: q.x, y: q.y, r: q.r, cracks: q.cracks.length } : null; }"


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
harlan = next(c for c in call("GET", "/api/creatures")["creatures"] if c["name"] == "Harlan Voss")
eid = call("POST", f"/api/campaigns/{camp}/encounters", {"name": "Quake"})["encounter"]["id"]
call("POST", f"/api/encounters/{eid}/combatants", {"characters": [chars["Moni Easter"]["id"], chars["Lux Fedelis"]["id"]]})
call("POST", f"/api/encounters/{eid}/combatants", {"creature_id": harlan["id"], "count": 1})
mid = call("POST", f"/api/encounters/{eid}/map")["map_id"]
call("PATCH", f"/api/maps/{mid}", {"changes": {"cols": {"to": 24}, "rows": {"to": 16}}})
toks = {t["display"]: t for t in call("GET", f"/api/maps/{mid}")["tokens"]}
for n, (x, y) in {"Harlan Voss": (11, 7), "Moni Easter": (14, 8), "Lux Fedelis": (8, 5)}.items():
    call("POST", f"/api/tokens/{toks[n]['id']}/move", {"x": x, "y": y, "free": True})
call("POST", f"/api/campaigns/{camp}/live-map", {"map_id": mid})
call("POST", f"/api/encounters/{eid}/start")
by = {c["name"]: c for c in call("GET", f"/api/encounters/{eid}")["combatants"]}
call("POST", f"/api/encounters/{eid}/set-turn", {"combatant_id": by["Harlan Voss"]["id"]})
code = call("POST", f"/api/campaigns/{camp}/join-code", {"action": "new"})["join_code"]

with sync_playwright() as p:
    b = engine.launch(p)
    ctx = b.new_context(viewport={"width": 390, "height": 844}, **engine.mobile(), has_touch=True); ctx.add_init_script(CATCH_VIEW)
    pp = ctx.new_page(); pp.on("pageerror", lambda e: problems.append(f"phone JS error: {e}"))
    pp.goto(LAN + "/join"); pp.fill("input[name=code]", code); pp.fill("input[name=name]", "Quake test")
    pp.wait_for_selector("#char-field:not([hidden])"); pp.select_option("select[name=character_id]", value=str(chars["Moni Easter"]["id"]))
    pp.click("button[type=submit]"); pp.wait_for_url(re.compile("/play")); pp.wait_for_timeout(3000)

    dctx = b.new_context(viewport={"width": 1400, "height": 950}); dctx.add_init_script(CATCH_VIEW)
    pg = dctx.new_page(); pg.on("pageerror", lambda e: problems.append(f"DM JS error: {e}"))
    pg.goto(f"{DM}/map/{mid}"); pg.wait_for_timeout(1500)
    pg.evaluate(f"""() => {{ const v = window.__view, m = v.map, r = v.canvas.getBoundingClientRect();
        const t = v.tokens.find((t) => t.display === 'Harlan Voss');
        const x = r.left + v.view.tx + (m.offset_x + (t.x + 0.5) * m.cell_px) * v.view.s, y = r.top + v.view.ty + (m.offset_y + (t.y + 0.5) * m.cell_px) * v.view.s;
        window.__harlan = [x, y]; }}""")
    pg.mouse.click(*pg.evaluate("window.__harlan")); pg.wait_for_selector(".fight-act"); pg.wait_for_timeout(500)
    act = pg.locator(".fight-act").filter(has=pg.locator("b", has_text=re.compile(r"^\s*Earth Shattter\s*$"))).first
    check(act.count() == 1 and "40 ft radius" in act.inner_text(), "Harlan has Earth Shattter, 40 ft radius")
    act.click(); pg.wait_for_timeout(600)
    pg.get_by_role("button", name=re.compile(r"Confirm")).first.click()
    got = None
    for _ in range(150):  # the dice roll first
        pg.wait_for_timeout(100)
        got = pg.evaluate(QUAKE)
        if got:
            break
    check(got is not None, f"the DM's map shows an earthquake ({got})")
    if got:
        check(abs(got["r"] - 8) < 0.01, "it fills the 40 ft radius (8 squares)")
        check(abs(got["x"] - 11.5) < 0.6 and abs(got["y"] - 7.5) < 0.6, "centred on Harlan")
        check(got["cracks"] >= 10, "with cracks and rocks across it")
        pg.wait_for_timeout(700); pg.screenshot(path=SHOTS + rf"\quake_dm_{engine.NAME}.png")
    shook = pg.evaluate("() => { const v = window.__view; return v.quakeShake ? v.quakeShake() : null; }")
    check(shook is not None, "the map can shake")
    ph = None
    for _ in range(60):
        pp.wait_for_timeout(100)
        ph = pp.evaluate(QUAKE)
        if ph:
            break
    check(ph is not None, f"the player's phone shows the earthquake too ({ph})")
    if ph:
        pp.wait_for_timeout(500); pp.screenshot(path=SHOTS + rf"\quake_phone_{engine.NAME}.png")
    pg.wait_for_timeout(3500)
    check(pg.evaluate(QUAKE) is None, "and it's over after a few seconds")
    log = " ".join(x["message"] for x in call("GET", f"/api/encounters/{eid}")["log"])
    check("Earth Shattter" in log or any("Earth Shattter" in r.get("label", "") for r in call("GET", f"/api/rolls?encounter_id={eid}")["rolls"]),
          "the attack itself still rolls as before")
    b.close()
fails = [m for ok, m in results if not ok]
print(f"\n{len(results) - len(fails)} passed, {len(fails)} failed"); [print("FAILED:", f) for f in fails]
print("PROBLEMS:", problems)
