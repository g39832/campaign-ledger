"""E2E game night, current rules: four phones and the DM play a whole round. Each hero on their
own turn moves within their speed, uses a move on a goblin by tapping its token, and ends their
turn from the phone. Moni surges (4 actions), Gnocchi goes Reckless, Yamato summons his clone
and parries; the DM's map and combat screen stay in step."""
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
chars = {c["name"]: c for c in call("GET", f"/api/campaigns/{camp}/characters")["characters"]}
HEROES = ["Lux Fedelis", "Moni Easter", "Yamato", "Gnocchi"]
for pl in call("GET", f"/api/campaigns/{camp}/players")["players"]:
    if not pl.get("revoked"):
        call("DELETE", f"/api/players/{pl['id']}")
eid = call("POST", f"/api/campaigns/{camp}/encounters", {"name": "Round test"})["encounter"]["id"]
call("POST", f"/api/encounters/{eid}/combatants", {"characters": [chars[n]["id"] for n in HEROES],
                                                   "quick": {"name": "Goblin", "max_hp": 200, "ac": 5, "count": 2}})
mid = call("POST", f"/api/encounters/{eid}/map")["map_id"]
call("PATCH", f"/api/maps/{mid}", {"changes": {"cols": {"to": 24}, "rows": {"to": 14}}})
spots = {"Lux Fedelis": (2, 2), "Moni Easter": (2, 5), "Yamato": (2, 8), "Gnocchi": (2, 11), "Goblin 1": (12, 4), "Goblin 2": (12, 9)}
for t in call("GET", f"/api/maps/{mid}")["tokens"]:
    if t["display"] in spots:
        call("POST", f"/api/tokens/{t['id']}/move", {"x": spots[t["display"]][0], "y": spots[t["display"]][1], "free": True})
call("POST", f"/api/campaigns/{camp}/live-map", {"map_id": mid})
by = {c["name"]: c for c in call("GET", f"/api/encounters/{eid}")["combatants"]}
order = HEROES + ["Goblin 1", "Goblin 2"]
call("POST", f"/api/encounters/{eid}/order", {"order": [by[n]["id"] for n in order]}) if False else None
call("POST", f"/api/encounters/{eid}/start")
code = call("POST", f"/api/campaigns/{camp}/join-code", {"action": "new"})["join_code"]


def hp(name):
    return next(c for c in call("GET", f"/api/encounters/{eid}")["combatants"] if c["name"] == name)["hp"]


def current():
    st = call("GET", f"/api/encounters/{eid}")
    return next(c["name"] for c in st["combatants"] if c["id"] == st["encounter"]["current_id"])


def to_turn(name):
    for _ in range(12):
        if current() == name:
            return
        call("POST", f"/api/encounters/{eid}/next")


with sync_playwright() as p:
    b = engine.launch(p)
    phones = {}
    for n in HEROES:
        ctx = b.new_context(viewport={"width": 390, "height": 844}, **engine.mobile(), has_touch=True)
        ctx.add_init_script(CATCH_VIEW)
        pg = ctx.new_page(); pg.on("pageerror", lambda e, n=n: problems.append(f"{n} JS error: {e}"))
        pg.on("response", lambda r, n=n: r.status >= 500 and problems.append(f"{n} HTTP {r.status} {r.url}"))
        pg.goto(LAN + "/join"); pg.fill("input[name=code]", code); pg.fill("input[name=name]", n.split()[0] + "'s player")
        pg.wait_for_selector("#char-field:not([hidden])"); pg.select_option("select[name=character_id]", value=str(chars[n]["id"]))
        pg.click("button[type=submit]"); pg.wait_for_url(re.compile("/play"))
        phones[n] = pg
    for pg in phones.values():
        pg.wait_for_timeout(500)

    def screen(pg, cx, cy):
        pg.evaluate("window.scrollTo(0, 0)"); pg.wait_for_timeout(200)
        return pg.evaluate(f"""() => {{ const v = window.__view, m = v.map, r = v.canvas.getBoundingClientRect();
          return [r.left + v.view.tx + (m.offset_x + ({cx} + .5) * m.cell_px) * v.view.s, r.top + v.view.ty + (m.offset_y + ({cy} + .5) * m.cell_px) * v.view.s]; }}""")

    def where(name):
        t = next(t for t in call("GET", f"/api/maps/{mid}")["tokens"] if t["display"] == name)
        return (t["x"], t["y"])

    def drag(pg, a, z):
        A, Z = screen(pg, *a), screen(pg, *z)
        pg.mouse.move(*A); pg.mouse.down(); pg.mouse.move(*Z, steps=8); pg.mouse.up(); pg.wait_for_timeout(1500)

    def use(pg, move, foe):
        card = pg.locator(".move-card").filter(has=pg.locator("b", has_text=re.compile(r"^\s*" + re.escape(move) + r"\s*$"))).first
        card.get_by_role("button", name=re.compile("Use")).click(); pg.wait_for_timeout(400)
        me_ = where(current())  # physical moves reach 5 ft: the goblin steps up next to the hero (DM's Free move)
        gt = next(t for t in call("GET", f"/api/maps/{mid}")["tokens"] if t["display"] == foe)
        call("POST", f"/api/tokens/{gt['id']}/move", {"x": me_[0] + 1, "y": me_[1], "free": True}); pg.wait_for_timeout(2500)
        g = where(foe)
        pg.mouse.click(*screen(pg, *g)); pg.wait_for_selector("#use-box button:has-text('Done')", timeout=25000); pg.wait_for_timeout(600)
        box = pg.locator("#use-box")
        text = box.inner_text() if box.count() else ""
        if box.count() and box.get_by_role("button", name="Done").count():
            box.get_by_role("button", name="Done").click()
        if pg.locator("#dice-dock.is-open").count():
            pg.click("#dice-close")
        return text

    def end_turn(pg):
        pg.evaluate("window.scrollTo(0, 0)")
        pg.locator("#turns .end-turn-btn").click(); pg.wait_for_timeout(300)
        pg.locator("#turns .end-turn-btn").click(); pg.wait_for_timeout(2500)

    for n in HEROES:
        to_turn(n)
        pg = phones[n]; pg.wait_for_timeout(3500)
        print(f"== {n}'s turn")
        check("It's your turn" in pg.locator("#turns").inner_text(), f"{n}'s phone says it's their turn")
        others = [o for o in HEROES if o != n]
        check(all(phones[o].locator(".end-turn-btn").count() == 0 for o in others), "nobody else gets an End turn button")
        speed = 40 if n == "Gnocchi" else 30
        x0, y0 = where(n)
        drag(pg, (x0, y0), (x0 + 12, y0))
        check(where(n) == (x0 + speed // 5, y0), f"{n} drags 60 ft and stops at their {speed} ft ({where(n)})")
        if n == "Moni Easter":
            pg.get_by_role("button", name=re.compile("^ ?Action Surge$")).click(); pg.wait_for_timeout(2000)
            check("of 4" in pg.locator("body").inner_text(), "Action Surge: 4 actions this turn")
            g0 = hp("Goblin 1")
            for i in range(4):
                use(pg, "Punch", "Goblin 1")
            check(hp("Goblin 1") < g0, f"Moni's punches land (Goblin 1: {g0} -> {hp('Goblin 1')})")
            check("No actions left" in pg.locator("body").inner_text(), "after 4, no actions left")
        elif n == "Gnocchi":
            pg.get_by_role("button", name=re.compile("^ ?Reckless attack$")).click(); pg.wait_for_timeout(2000)
            t = use(pg, "Great Axe", "Goblin 2")
            print("    ", t.replace("\n", " / "))
            check("Goblin 2" in t, "Gnocchi's reckless Great Axe at Goblin 2 resolves")
        elif n == "Yamato":
            card = pg.locator(".move-card").filter(has_text="Phantasaml force").first
            btn = card.get_by_role("button", name=re.compile("Cast|Use"))
            if btn.count():
                btn.first.click(); pg.wait_for_timeout(600)
                if pg.locator("#cast-box .cast-go").count():
                    pg.locator("#cast-box .cast-go").click(); pg.wait_for_timeout(2500)
            names = [c["name"] for c in call("GET", f"/api/encounters/{eid}")["combatants"]]
            check(any("clone" in x.lower() for x in names), f"Yamato's clone joins the fight ({names})")
            t = use(pg, "Slash", "Goblin 1")
            check("Goblin 1" in t, "Yamato slashes Goblin 1")
        else:
            t = use(pg, "Bite", "Goblin 1")
            check("Goblin 1" in t or t == "", f"{n} attacks ({t[:60]!r})")
        check(not re.search(r"\bAC \d", pg.locator("body").inner_text()), f"{n}'s phone never shows a goblin's AC")
        end_turn(pg)
        check(current() != n and pg.locator(".end-turn-btn", has_text="End my turn").count() == 0, f"{n} ends their own turn from the phone (now {current()})")
        pg.screenshot(path=SHOTS + f"/round_{n.split()[0]}.png")

    print("== The goblins: the DM attacks Yamato, who parries")
    to_turn("Goblin 1")
    dm = b.new_page(viewport={"width": 1400, "height": 1000}); dm.on("pageerror", lambda e: problems.append(f"DM JS error: {e}"))
    dm.goto(f"{DM}/combat/{eid}"); dm.wait_for_timeout(1200)
    y0 = hp("Yamato")
    call("POST", f"/api/combatants/{by['Yamato']['id']}/hp", {"op": "damage", "amount": 8, "by": "Goblin 1"})
    yam = phones["Yamato"]; yam.wait_for_timeout(4000)
    pb = yam.get_by_role("button", name=re.compile("^Parry"))
    check(pb.count() > 0, "Yamato's phone offers Parry when he's hit")
    if pb.count():
        pb.first.click(); yam.wait_for_timeout(2500)
        check(hp("Yamato") in (y0 - 8, y0 - 4), f"parry roll-off settled (HP {y0} -> {hp('Yamato')})")
    dm.click("#next"); dm.wait_for_timeout(1500)
    check(current() != "Goblin 1", "the DM's Next still works")
    dm.screenshot(path=SHOTS + "/round_dm.png")
    b.close()
fails = [m for ok, m in results if not ok]
print(f"\n{len(results) - len(fails)} passed, {len(fails)} failed"); [print("FAILED:", f) for f in fails]
print("PROBLEMS:", problems)
