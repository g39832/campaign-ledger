"""E2E: physical moves reach 5 ft, on a phone and on the DM's map; Free move ignores it."""
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


def check(c, msg):
    results.append((bool(c), msg)); print(("  PASS " if c else "  FAIL ") + msg, flush=True)


camp = 1
for e in call("GET", f"/api/campaigns/{camp}/encounters")["encounters"]:
    if e["status"] == "active":
        call("POST", f"/api/encounters/{e['id']}/end")
for pl in call("GET", f"/api/campaigns/{camp}/players")["players"]:
    call("DELETE", f"/api/players/{pl['id']}")
chars = {c["name"]: c for c in call("GET", f"/api/campaigns/{camp}/characters")["characters"]}
eid = call("POST", f"/api/campaigns/{camp}/encounters", {"name": "Reach"})["encounter"]["id"]
call("POST", f"/api/encounters/{eid}/combatants", {"characters": [chars["Moni Easter"]["id"], chars["Lux Fedelis"]["id"]],
                                                   "quick": {"name": "Goblin", "max_hp": 200, "ac": 3, "count": 2}})
mid = call("POST", f"/api/encounters/{eid}/map")["map_id"]
call("PATCH", f"/api/maps/{mid}", {"changes": {"cols": {"to": 24}, "rows": {"to": 12}}})
toks = {t["display"]: t for t in call("GET", f"/api/maps/{mid}")["tokens"]}
for n, (x, y) in {"Moni Easter": (2, 2), "Lux Fedelis": (2, 8), "Goblin 1": (10, 2), "Goblin 2": (3, 9)}.items():
    call("POST", f"/api/tokens/{toks[n]['id']}/move", {"x": x, "y": y, "free": True})
call("POST", f"/api/campaigns/{camp}/live-map", {"map_id": mid})
call("POST", f"/api/encounters/{eid}/start")
by = {c["name"]: c for c in call("GET", f"/api/encounters/{eid}")["combatants"]}


def fresh_turn(name):
    for _ in range(8):
        st = call("POST", f"/api/encounters/{eid}/next")
        if st["encounter"]["current_id"] == by[name]["id"]:
            return


fresh_turn("Moni Easter")
code = call("POST", f"/api/campaigns/{camp}/join-code", {"action": "new"})["join_code"]


def hp(n):
    return next(c for c in call("GET", f"/api/encounters/{eid}")["combatants"] if c["name"] == n)["hp"]


with sync_playwright() as p:
    b = engine.launch(p)
    ctx = b.new_context(viewport={"width": 390, "height": 844}, **engine.mobile(), has_touch=True); ctx.add_init_script(CATCH_VIEW)
    pp = ctx.new_page(); pp.on("pageerror", lambda e: problems.append(f"phone JS error: {e}"))
    pp.goto(LAN + "/join"); pp.fill("input[name=code]", code); pp.fill("input[name=name]", "Reach test")
    pp.wait_for_selector("#char-field:not([hidden])"); pp.select_option("select[name=character_id]", value=str(chars["Moni Easter"]["id"]))
    pp.click("button[type=submit]"); pp.wait_for_url(re.compile("/play")); pp.wait_for_timeout(3000)

    def toasts(pg):
        return " | ".join(pg.locator(".toast").all_inner_texts())

    def screen(pg, cx, cy):
        pg.evaluate("window.scrollTo(0, 0)"); pg.wait_for_timeout(200)
        return pg.evaluate(f"""() => {{ const v = window.__view, m = v.map, r = v.canvas.getBoundingClientRect();
          return [r.left + v.view.tx + (m.offset_x + ({cx} + .5) * m.cell_px) * v.view.s, r.top + v.view.ty + (m.offset_y + ({cy} + .5) * m.cell_px) * v.view.s]; }}""")

    def punch_card():
        return pp.locator(".move-card").filter(has=pp.locator("b", has_text=re.compile(r"^\s*Punch\s*$"))).first

    print("== Moni's phone: Punch a goblin 40 ft away")
    punch_card().get_by_role("button", name=re.compile("Use")).click(); pp.wait_for_timeout(400)
    chip = pp.locator("#use-box").get_by_role("button", name=re.compile("^Goblin 1"))
    check(chip.is_disabled() and "40 ft" in chip.inner_text(), f"Goblin 1 is greyed out in the list ({chip.inner_text()!r})")
    check("reaches 5 ft" in pp.locator("#use-box").inner_text(), "the picker says Punch reaches 5 ft")
    g0 = hp("Goblin 1")
    pp.mouse.click(*screen(pp, 10, 2)); pp.wait_for_timeout(1200)
    check("40 ft away" in toasts(pp) and hp("Goblin 1") == g0, f"tapping its token: refused ({toasts(pp)[-110:]!r})")
    pp.locator("#use-box").get_by_role("button", name="Cancel").click()
    print("== She walks up next to it")
    a, z = screen(pp, 2, 2), screen(pp, 9, 2)
    pp.mouse.move(*a); pp.mouse.down(); pp.mouse.move(*z, steps=8); pp.mouse.up(); pp.wait_for_timeout(2500)
    t = next(t for t in call("GET", f"/api/maps/{mid}")["tokens"] if t["display"] == "Moni Easter")
    check((t["x"], t["y"]) == (8, 2), f"she moved 30 ft to (8, 2): {t['x']},{t['y']}")
    call("POST", f"/api/tokens/{toks['Goblin 1']['id']}/move", {"x": 9, "y": 2, "free": True}); pp.wait_for_timeout(2500)
    punch_card().get_by_role("button", name=re.compile("Use")).click(); pp.wait_for_timeout(400)
    check(not pp.locator("#use-box").get_by_role("button", name=re.compile("^Goblin 1")).is_disabled(), "the goblin steps up next to her: now it can be picked")
    pp.mouse.click(*screen(pp, 9, 2)); pp.wait_for_selector("#use-box button:has-text('Done')", timeout=25000); pp.wait_for_timeout(600)
    res = pp.locator("#use-box").inner_text() if pp.locator("#use-box").count() else ""
    check("Goblin 1" in res and ("hit" in res or "missed" in res or "CRIT" in res), f"the punch is rolled ({' / '.join(res.splitlines())[:120]!r})")
    ctx.close()

    print("== The DM's map: Lux bites")
    fresh_turn("Lux Fedelis")
    dm = b.new_context(viewport={"width": 1400, "height": 950}); dm.add_init_script(CATCH_VIEW)
    pg = dm.new_page(); pg.on("pageerror", lambda e: problems.append(f"DM JS error: {e}"))
    pg.goto(f"{DM}/map/{mid}"); pg.wait_for_timeout(1500)
    pg.mouse.click(*screen(pg, 2, 8)); pg.wait_for_selector(".fight-act"); pg.wait_for_timeout(500)

    def bite():
        return pg.locator(".fight-act").filter(has=pg.locator("b", has_text=re.compile(r"^\s*Bite\s*$"))).first

    g1 = hp("Goblin 1")
    bite().click(); pg.wait_for_timeout(400)
    pg.mouse.click(*screen(pg, 9, 2)); pg.wait_for_timeout(1500)
    check("only reaches 5 ft" in toasts(pg) and hp("Goblin 1") == g1, f"biting Goblin 1 across the map: refused ({toasts(pg)[-120:]!r})")
    before = len(call("GET", f"/api/rolls?encounter_id={eid}")["rolls"])
    pg.mouse.click(*screen(pg, 3, 9)); pg.wait_for_timeout(8000)
    if pg.locator("#dice-dock.is-open").count():
        pg.click("#dice-close")
    check(len(call("GET", f"/api/rolls?encounter_id={eid}")["rolls"]) > before, "biting Goblin 2, right next to her, is rolled")
    print("== Free move ignores reach")
    pg.locator("#free-move").click(); pg.wait_for_timeout(300)
    pg.mouse.click(*screen(pg, 2, 8)); pg.wait_for_timeout(500)
    bite().click(); pg.wait_for_timeout(400)
    before = len(call("GET", f"/api/rolls?encounter_id={eid}")["rolls"])
    pg.mouse.click(*screen(pg, 9, 2)); pg.wait_for_timeout(8000)
    check(len(call("GET", f"/api/rolls?encounter_id={eid}")["rolls"]) > before, "with Free move on, the far bite is rolled")
    pg.screenshot(path=SHOTS + "/reach_dm.png")
    b.close()
fails = [m for ok, m in results if not ok]
print(f"\n{len(results) - len(fails)} passed, {len(fails)} failed"); [print("FAILED:", f) for f in fails]
print("PROBLEMS:", problems)
