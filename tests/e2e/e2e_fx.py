"""E2E: attack animations reach the DM's map and every phone; friendly fire on phones needs a
second tap; the DM's area attacks catch allies (flagged, and the DM can spare them)."""
import json, re, urllib.request, uuid
from common import APP_DIR, DM_URL, LAN_IP, LAN_URL, SHOTS_DIR, TMP_DIR  # noqa: E402,F401  (paths and addresses for this computer)
from playwright.sync_api import sync_playwright
import engine

DM = DM_URL; LAN = LAN_URL
SHOTS = SHOTS_DIR
results, problems = [], []
CATCH_VIEW = """
(() => { let real; Object.defineProperty(window, 'MapView', { configurable: true, get() { return real; },
  set(v) { real = class extends v { constructor(...a) { super(...a); window.__view = this;
    const add = this.addFx.bind(this); window.__fx = []; this.addFx = (f) => { if (f.type === 'attack' || f.type === 'word') window.__fx.push({ type: f.type, style: f.style, how: f.how, text: f.text }); return add(f); }; } }; } }); })();
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
eid = call("POST", f"/api/campaigns/{camp}/encounters", {"name": "FX"})["encounter"]["id"]
call("POST", f"/api/encounters/{eid}/combatants", {"characters": [chars[n]["id"] for n in ("Moni Easter", "Gnocchi", "Yamato")],
                                                   "quick": {"name": "Goblin", "max_hp": 300, "ac": 3, "count": 2}})
mid = call("POST", f"/api/encounters/{eid}/map")["map_id"]
call("PATCH", f"/api/maps/{mid}", {"changes": {"cols": {"to": 20}, "rows": {"to": 12}}})
toks = {t["display"]: t for t in call("GET", f"/api/maps/{mid}")["tokens"]}
for n, (x, y) in {"Moni Easter": (5, 5), "Gnocchi": (6, 5), "Yamato": (4, 5), "Goblin 1": (5, 6), "Goblin 2": (12, 2)}.items():
    call("POST", f"/api/tokens/{toks[n]['id']}/move", {"x": x, "y": y, "free": True})
call("POST", f"/api/campaigns/{camp}/live-map", {"map_id": mid})
call("POST", f"/api/encounters/{eid}/start")
by = {c["name"]: c for c in call("GET", f"/api/encounters/{eid}")["combatants"]}


def fresh_turn(name):
    for _ in range(8):
        if call("POST", f"/api/encounters/{eid}/next")["encounter"]["current_id"] == by[name]["id"]:
            return


fresh_turn("Moni Easter")
code = call("POST", f"/api/campaigns/{camp}/join-code", {"action": "new"})["join_code"]


def hp(n):
    return next(c for c in call("GET", f"/api/encounters/{eid}")["combatants"] if c["name"] == n)["hp"]


with sync_playwright() as p:
    b = engine.launch(p)
    phones = {}
    for n in ("Moni Easter", "Gnocchi"):
        ctx = b.new_context(viewport={"width": 390, "height": 844}, **engine.mobile(), has_touch=True); ctx.add_init_script(CATCH_VIEW)
        pg = ctx.new_page(); pg.on("pageerror", lambda e, n=n: problems.append(f"{n} JS error: {e}"))
        pg.goto(LAN + "/join"); pg.fill("input[name=code]", code); pg.fill("input[name=name]", n.split()[0] + " fx")
        pg.wait_for_selector("#char-field:not([hidden])"); pg.select_option("select[name=character_id]", value=str(chars[n]["id"]))
        pg.click("button[type=submit]"); pg.wait_for_url(re.compile("/play")); pg.wait_for_timeout(1500)
        phones[n] = pg
    dmc = b.new_context(viewport={"width": 1400, "height": 950}); dmc.add_init_script(CATCH_VIEW)
    dm = dmc.new_page(); dm.on("pageerror", lambda e: problems.append(f"DM JS error: {e}"))
    dm.goto(f"{DM}/map/{mid}"); dm.wait_for_timeout(2000)
    moni = phones["Moni Easter"]; moni.wait_for_timeout(2000)

    def screen(pg, cx, cy):
        pg.evaluate("window.scrollTo(0, 0)"); pg.wait_for_timeout(200)
        return pg.evaluate(f"""() => {{ const v = window.__view, m = v.map, r = v.canvas.getBoundingClientRect();
          return [r.left + v.view.tx + (m.offset_x + ({cx} + .5) * m.cell_px) * v.view.s, r.top + v.view.ty + (m.offset_y + ({cy} + .5) * m.cell_px) * v.view.s]; }}""")

    def card(pg, name):
        return pg.locator(".move-card").filter(has=pg.locator("b", has_text=re.compile(r"^\s*" + re.escape(name) + r"\s*$"))).first

    print(f"== [{engine.NAME}] Moni punches Goblin 1: everyone sees it")
    card(moni, "Punch").get_by_role("button", name=re.compile("Use")).click(); moni.wait_for_timeout(400)
    moni.mouse.click(*screen(moni, 5, 6)); moni.wait_for_selector("#use-box button:has-text('Done')", timeout=25000); moni.wait_for_timeout(600); moni.wait_for_timeout(3000)
    for who, pg in (("Moni's phone", moni), ("Gnocchi's phone", phones["Gnocchi"]), ("the DM's map", dm)):
        fx = pg.evaluate("window.__fx || []")
        check(any(f["type"] == "attack" and f["style"] == "punch" for f in fx), f"{who} played the punch animation ({[f['style'] for f in fx if f['type'] == 'attack']})")
    moni.screenshot(path=SHOTS + f"/fx_{engine.NAME}_phone.png")
    if moni.locator("#use-box").get_by_role("button", name="Done").count():
        moni.locator("#use-box").get_by_role("button", name="Done").click()
    print("== Friendly fire: Gnocchi is right next to her")
    card(moni, "Punch").get_by_role("button", name=re.compile("Use")).click(); moni.wait_for_timeout(400)
    chip = moni.locator("#use-box").get_by_role("button", name=re.compile("Gnocchi"))
    check(chip.count() == 1 and "ally" in chip.inner_text(), f"Gnocchi is in the list, marked as an ally ({chip.inner_text()!r})")
    check(moni.locator("#use-box").get_by_role("button", name=re.compile("Moni")).count() == 0, "Moni herself isn't")
    m0 = hp("Moni Easter")
    moni.mouse.click(*screen(moni, 5, 5)); moni.wait_for_timeout(1500)   # her own token
    check(hp("Moni Easter") == m0 and "can't attack yourself" in " ".join(moni.locator(".toast").all_inner_texts()),
          "tapping her own token: refused, she can't hit herself")
    g0 = hp("Gnocchi")
    chip.click(); moni.wait_for_timeout(900)
    check(hp("Gnocchi") == g0 and "on your side" in " ".join(moni.locator(".toast").all_inner_texts()), "first tap only warns: she's on your side")
    moni.locator("#use-box").get_by_role("button", name=re.compile("Gnocchi")).click(); moni.wait_for_selector("#use-box button:has-text('Done')", timeout=25000); moni.wait_for_timeout(600)
    res = moni.locator("#use-box").inner_text() if moni.locator("#use-box").count() else ""
    check("Gnocchi" in res, f"second tap: Moni punches Gnocchi ({' / '.join(res.splitlines())[:110]!r})")
    if moni.locator("#use-box").get_by_role("button", name="Done").count():
        moni.locator("#use-box").get_by_role("button", name="Done").click()

    print("== The DM's area attack catches an ally too")
    fresh_turn("Yamato")
    dm.wait_for_timeout(2500)
    dm.mouse.click(*screen(dm, 4, 5)); dm.wait_for_selector(".fight-act"); dm.wait_for_timeout(500)
    ws = dm.locator(".fight-act").filter(has=dm.locator("b", has_text=re.compile(r"^\s*Wide Slash\s*$"))).first
    ws.click(); dm.wait_for_selector(".fight-aim"); dm.wait_for_timeout(300)
    a, z = screen(dm, 4, 5), screen(dm, 7, 5)
    dm.mouse.move(*a); dm.mouse.down(); dm.mouse.move(*z, steps=6); dm.mouse.up(); dm.wait_for_timeout(600)
    inn = dm.locator(".fight-aim").inner_text()
    print("    ", inn.replace("\n", " / ")[:200])
    check("⚠" in inn and "(ally)" in inn, "allies in the cone are flagged ⚠ (ally)")
    ally = dm.locator(".fight-aim button.tag").filter(has_text="(ally)").first
    name = ally.inner_text().replace("⚠ ", "").replace(" (ally)", "")
    ally.click(); dm.wait_for_timeout(300)
    check("text-decoration" in (dm.locator(".fight-aim button.tag").filter(has_text=name).first.get_attribute("style") or ""), f"tapping {name} spares them")
    dm.screenshot(path=SHOTS + f"/fx_{engine.NAME}_dm_aim.png")
    dm.locator(".fight-aim").get_by_role("button", name=re.compile("Cancel")).click()
    b.close()
fails = [m for ok, m in results if not ok]
print(f"\n{len(results) - len(fails)} passed, {len(fails)} failed"); [print("FAILED:", f) for f in fails]
print("PROBLEMS:", problems)
