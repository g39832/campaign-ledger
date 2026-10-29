"""The players' side, really tested: a round played from four phones only."""
import json, re, time, urllib.request, uuid
from common import APP_DIR, DM_URL, LAN_IP, LAN_URL, SHOTS_DIR, TMP_DIR  # noqa: E402,F401  (paths and addresses for this computer)
from playwright.sync_api import sync_playwright
import engine

DM = DM_URL; LAN = LAN_URL
SHOTS = SHOTS_DIR
CATCH_VIEW = """
(() => { let real; Object.defineProperty(window, 'MapView', { configurable: true, get() { return real; },
  set(v) { real = class extends v { constructor(...a) { super(...a); window.__view = this;
    const add = this.addFx.bind(this); window.__fx = []; this.addFx = (f) => { if (f.type === 'attack') window.__fx.push(f.style); return add(f); }; } }; } }); })();
"""
results, problems = [], []
import os
DEVICES = {  # what each player is on: phone, tablet, laptop (mouse, no touch) or a small laptop window
    "phones": dict.fromkeys(["Lux Fedelis", "Moni Easter", "Yamato", "Gnocchi"], "phone"),
    "laptops": dict.fromkeys(["Lux Fedelis", "Moni Easter", "Yamato", "Gnocchi"], "laptop"),
    "tablets": dict.fromkeys(["Lux Fedelis", "Moni Easter", "Yamato", "Gnocchi"], "tablet"),
    "mixed": {"Lux Fedelis": "laptop", "Moni Easter": "phone", "Yamato": "small", "Gnocchi": "tablet"},
}[os.environ.get("DEVICES", "phones")]
SIZES = {"phone": (390, 844), "tablet": (820, 1180), "laptop": (1366, 768), "small": (1024, 640)}


def device(kind):
    w, h = SIZES[kind]
    if kind in ("phone", "tablet"):
        return dict(viewport={"width": w, "height": h}, **engine.mobile(), has_touch=True)
    return dict(viewport={"width": w, "height": h})


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
HEROES = ["Lux Fedelis", "Moni Easter", "Yamato", "Gnocchi"]
eid = call("POST", f"/api/campaigns/{camp}/encounters", {"name": "Phones only"})["encounter"]["id"]
call("POST", f"/api/encounters/{eid}/combatants", {"characters": [chars[n]["id"] for n in HEROES],
                                                   "quick": {"name": "Goblin", "max_hp": 300, "ac": 5, "count": 3}})
mid = call("POST", f"/api/encounters/{eid}/map")["map_id"]
call("PATCH", f"/api/maps/{mid}", {"changes": {"cols": {"to": 24}, "rows": {"to": 14}}})
POS = {"Lux Fedelis": (3, 3), "Moni Easter": (3, 6), "Yamato": (3, 9), "Gnocchi": (3, 12), "Goblin 1": (12, 3), "Goblin 2": (12, 7), "Goblin 3": (12, 11)}
toks = {t["display"]: t for t in call("GET", f"/api/maps/{mid}")["tokens"]}
for n, (x, y) in POS.items():
    call("POST", f"/api/tokens/{toks[n]['id']}/move", {"x": x, "y": y, "free": True})
call("POST", f"/api/campaigns/{camp}/live-map", {"map_id": mid})
by = {c["name"]: c for c in call("GET", f"/api/encounters/{eid}")["combatants"]}
ORDER = HEROES + ["Goblin 1", "Goblin 2", "Goblin 3"]
for i, n in enumerate(ORDER):  # turn order: the heroes in a row, then the goblins
    call("PATCH", f"/api/combatants/{by[n]['id']}", {"changes": {"init_roll": {"from": None, "to": 30 - i}}})
call("POST", f"/api/encounters/{eid}/start")
code = call("POST", f"/api/campaigns/{camp}/join-code", {"action": "new"})["join_code"]


def st():
    return call("GET", f"/api/encounters/{eid}")


def hp(n):
    return next(c for c in st()["combatants"] if c["name"] == n)["hp"]


def current():
    s = st()
    return next(c["name"] for c in s["combatants"] if c["id"] == s["encounter"]["current_id"])


def tok_of(n):
    return next(t for t in call("GET", f"/api/maps/{mid}")["tokens"] if t["display"] == n)


with sync_playwright() as p:
    b = engine.launch(p)
    ph = {}

    def join(n, name):
        ctx = b.new_context(**device(DEVICES[n])); ctx.add_init_script(CATCH_VIEW)
        pg = ctx.new_page(); pg.on("pageerror", lambda e, n=n: problems.append(f"{n} JS error: {e}"))
        pg.on("response", lambda r, n=n: r.status >= 500 and problems.append(f"{n} HTTP {r.status} {r.url}"))
        pg.goto(LAN + "/join"); pg.fill("input[name=code]", code); pg.fill("input[name=name]", name)
        pg.wait_for_selector("#char-field:not([hidden])"); pg.select_option("select[name=character_id]", value=str(chars[n]["id"]))
        pg.click("button[type=submit]"); pg.wait_for_url(re.compile("/play"), timeout=15000)
        return pg

    print(f"== [{engine.NAME}] Four players join: {DEVICES}")
    for n in HEROES:
        ph[n] = join(n, n.split()[0] + "'s player")
    for pg in ph.values():
        pg.wait_for_timeout(800)
    check(all(ph[n].locator("#me").inner_text().count(n.split()[0]) for n in HEROES), "each phone shows its own character")

    def screen(pg, cx, cy):
        pg.evaluate("window.scrollTo(0, 0)"); pg.wait_for_timeout(150)
        return pg.evaluate(f"""() => {{ const v = window.__view, m = v.map, r = v.canvas.getBoundingClientRect();
          return [r.left + v.view.tx + (m.offset_x + ({cx} + .5) * m.cell_px) * v.view.s, r.top + v.view.ty + (m.offset_y + ({cy} + .5) * m.cell_px) * v.view.s]; }}""")

    def drag(pg, a, z):
        A, Z = screen(pg, *a), screen(pg, *z)
        pg.mouse.move(*A); pg.mouse.down(); pg.mouse.move(*Z, steps=8); pg.mouse.up(); pg.wait_for_timeout(1500)

    def panel(pg):
        return pg.locator("#turns .your-moves")

    def tap_move(pg, name):
        pg.evaluate("window.scrollTo(0, 0)")
        panel(pg).locator(".fight-act").filter(has=pg.locator("b", has_text=re.compile(r"^\s*" + re.escape(name) + r"\s*$"))).first.click()
        pg.wait_for_timeout(500)

    def wait_done(pg):
        pg.wait_for_selector("#use-box button:has-text('Done'), #cast-box button:has-text('Done')", timeout=30000)
        pg.wait_for_timeout(400)
        t = (pg.locator("#use-box").inner_text() if pg.locator("#use-box").count() else pg.locator("#cast-box").inner_text())
        pg.locator("#use-box button:has-text('Done'), #cast-box button:has-text('Done')").first.click(); pg.wait_for_timeout(300)
        return t

    def toasts(pg):
        return " | ".join(pg.locator(".toast").all_inner_texts())

    def goblin_next_to(n, g):
        x, y = tok_of(n)["x"], tok_of(n)["y"]
        for dx, dy in ((1, 0), (0, 1), (-1, 0), (0, -1), (1, 1)):
            r = urllib.request.Request(DM + f"/api/tokens/{tok_of(g)['id']}/move", data=json.dumps({"x": x + dx, "y": y + dy, "free": True, "op_id": uuid.uuid4().hex}).encode(),
                                       method="POST", headers={"Content-Type": "application/json"})
            try:
                urllib.request.urlopen(r); return (x + dx, y + dy)
            except urllib.error.HTTPError:
                continue

    def tap_token(pg, n):
        t = tok_of(n); pg.mouse.click(*screen(pg, t["x"], t["y"])); pg.wait_for_timeout(500)

    def end_turn(pg, n):
        pg.evaluate("window.scrollTo(0, 0)")
        pg.locator("#turns .end-turn-btn").click(); pg.wait_for_timeout(250); pg.locator("#turns .end-turn-btn").click(); pg.wait_for_timeout(2500)
        check(current() != n, f"{n} ends their turn from the phone (now {current()})")

    def common_turn_checks(n):
        pg = ph[n]; pg.wait_for_timeout(3000)
        check("It's your turn" in pg.locator("#turns").inner_text(), f"{n}: 'It's your turn' on the phone")
        check(panel(pg).count() == 1, f"{n}: the moves panel is right under it ({', '.join(x.split(chr(10))[0] for x in panel(pg).locator('.fight-act').all_inner_texts())})")
        others = [o for o in HEROES if o != n]
        check(all(panel(ph[o]).count() == 0 for o in others), f"{n}: nobody else has a moves panel")
        o = ph[others[0]]
        check("Wait for your turn" in o.locator("#hint").inner_text(), f"{others[0]} can't move on {n}'s turn")
        o.locator(".stats .stat").first.click(); o.wait_for_timeout(1500)
        check("only you see this roll" in toasts(o), f"{others[0]} rolls off-turn: just for them")
        check(not re.search(r"\bAC \d", pg.locator("body").inner_text()), f"{n}: no enemy AC anywhere on the phone")

    # ---- Lux ----------------------------------------------------------------------------
    print("== Lux's turn"); n = "Lux Fedelis"; pg = ph[n]
    common_turn_checks(n)
    x0, y0 = tok_of(n)["x"], tok_of(n)["y"]
    drag(pg, (x0, y0), (x0 + 3, y0)); drag(pg, (x0 + 3, y0), (x0 + 2, y0))
    check((tok_of(n)["x"], tok_of(n)["y"]) == (x0 + 2, y0), "Lux moves, then readjusts back a square")
    goblin_next_to(n, "Goblin 1"); pg.wait_for_timeout(2500)
    g0 = hp("Goblin 1")
    tap_move(pg, "Bite"); tap_token(pg, "Goblin 1")
    res = wait_done(pg); print("    Bite:", res.replace("\n", " / ")[:120])
    check("Goblin 1" in res and (hp("Goblin 1") < g0) == ("missed" not in res), "Bite from the panel: rolled, and the HP matches the result")
    mv = pg.evaluate("async () => (await (await fetch('/api/play/state')).json()).character.move")
    check(mv["budget"] == mv["speed"] - 10, f"after acting, the 10 ft moved is spent (budget {mv['budget']} of {mv['speed']})")
    tap_move(pg, "Spirit Guardians"); res = wait_done(pg); print("    Guardians:", res.replace("\n", " / ")[:120])
    pg.wait_for_timeout(2500)
    check(all(ph[o].evaluate("(window.__view.zones || []).length") == 1 for o in HEROES), "Spirit Guardians: the light is on every phone")
    tap_move(pg, "Bite") if panel(pg).locator(".fight-act").filter(has_text="Bite").count() and not panel(pg).locator(".fight-act").first.is_disabled() else None
    if pg.locator("#use-box").count():
        pg.locator("#use-box").get_by_role("button", name="Cancel").click()
    pg.screenshot(path=SHOTS + f"/players_{engine.NAME}_{DEVICES[n]}_lux.png")
    end_turn(pg, n)

    # ---- Moni ---------------------------------------------------------------------------
    print("== Moni's turn"); n = "Moni Easter"; pg = ph[n]
    common_turn_checks(n)
    goblin_next_to(n, "Goblin 2"); pg.wait_for_timeout(2500)
    tap_move(pg, "Action Surge"); pg.wait_for_timeout(1500)
    check("of 4" in pg.locator("body").inner_text(), "Action Surge from the panel: 4 actions")
    for k in range(3):
        tap_move(pg, "Punch"); tap_token(pg, "Goblin 2"); wait_done(pg)
    tap_move(pg, "Grapple"); tap_token(pg, "Goblin 2"); res = wait_done(pg)
    print("    Grapple:", res.replace("\n", " / ")[:120])
    g2 = next(c for c in st()["combatants"] if c["name"] == "Goblin 2")
    check(("Grappled" in [x["name"] for x in g2["conditions"]]) == ("missed" not in res), "Grapple leaves Goblin 2 Grappled when it hits")
    check("No actions left" in panel(pg).inner_text() and panel(pg).locator(".fight-act").first.is_disabled(), "after 4 actions the moves are greyed out")
    end_turn(pg, n)

    # ---- Yamato -------------------------------------------------------------------------
    print("== Yamato's turn"); n = "Yamato"; pg = ph[n]
    common_turn_checks(n)
    tap_move(pg, "Action Surge"); pg.wait_for_timeout(1500)  # four actions: two clones, then Wide Slash
    tap_move(pg, "Phantasaml force"); pg.wait_for_timeout(600)
    check("tap the square on the map where" in pg.locator("#hint").inner_text(), "Phantasmal Force: the phone asks where the clone appears")
    yt = tok_of(n); taken = {(u["x"], u["y"]) for u in call("GET", f"/api/maps/{mid}")["tokens"]}
    SPOT = next((yt["x"] + dx, yt["y"] + dy) for dx, dy in ((2, -2), (2, 2), (-2, -2), (-2, 2), (3, 0)) if (yt["x"] + dx, yt["y"] + dy) not in taken and yt["x"] + dx >= 0 and yt["y"] + dy >= 0)
    pg.mouse.click(*screen(pg, *SPOT))  # tapping the square casts it there
    pg.wait_for_selector("#cast-box button:has-text('Done')", timeout=15000); pg.wait_for_timeout(500)
    names = [c["name"] for c in st()["combatants"]]
    check(any("clone" in x.lower() for x in names), "Phantasmal Force from the panel: the clone joins")
    ct = next(t for t in call("GET", f"/api/maps/{mid}")["tokens"] if "clone" in t["display"].lower())
    check((ct["x"], ct["y"]) == SPOT, f"it appears on the square he tapped ({ct['x']}, {ct['y']})")
    if pg.locator("#cast-box button:has-text('Done')").count():
        pg.locator("#cast-box button:has-text('Done')").click()
    tap_move(pg, "Echo Knight"); pg.wait_for_timeout(600)
    if pg.locator("#cast-box .cast-go").count():
        pg.locator("#cast-box .cast-go").click()
    pg.wait_for_timeout(3500)
    if pg.locator("#cast-box button:has-text('Done')").count():
        pg.locator("#cast-box button:has-text('Done')").click()
    CLONES = [c["name"] for c in st()["combatants"] if "clone" in c["name"].lower()]
    check(len(CLONES) == 2, f"Echo Knight from the panel: a second clone, two at once ({CLONES})")
    goblin_next_to(n, "Goblin 3"); pg.wait_for_timeout(2500)
    tap_move(pg, "Wide Slash"); pg.wait_for_timeout(600)
    check(pg.evaluate("!!window.__view.aim"), "Wide Slash from the panel: the cone shows on his map")
    t = tok_of(n); g = tok_of("Goblin 3")
    drag(pg, (t["x"] + 1, t["y"]), (g["x"], g["y"]))
    box = pg.locator("#use-box").inner_text()
    check("Goblin 3" in box, f"he points the cone at Goblin 3 ({box.splitlines()[-2] if len(box.splitlines()) > 1 else box!r})")
    for mate in pg.locator("#use-box button:has-text('ally')").all():
        mate.click(); pg.wait_for_timeout(200)
    pg.locator("#use-box").get_by_role("button", name=re.compile("^Use on")).click(); res = wait_done(pg)
    check("Goblin 3" in res, "Wide Slash lands on Goblin 3")
    end_turn(pg, n)
    # the clones act right after him: his device runs them
    for k in range(2):
        cn = current()
        check("clone" in cn.lower(), f"next up: {cn}")
        if "clone" not in cn.lower():
            break
        pg.wait_for_timeout(3000)
        check(f"It's {cn}'s turn" in pg.locator("#turns").inner_text() and "you control it" in pg.locator("#turns").inner_text(),
              f"{DEVICES[n]}: Yamato's player is told they control {cn}")
        cards = [x.split(chr(10))[0] for x in panel(pg).locator(".fight-act").all_inner_texts()]
        check(cards == ["Slash"], f"{cn}'s moves: Slash only ({cards})")
        o = ph["Lux Fedelis"]
        check("you control it" not in o.locator("#turns").inner_text() and panel(o).count() == 0, f"Lux's player doesn't get {cn}")
        t = tok_of(cn); taken = {(u["x"], u["y"]) for u in call("GET", f"/api/maps/{mid}")["tokens"]}
        to = next((t["x"] + dx, t["y"] + dy) for dx, dy in ((0, -1), (0, 1), (1, 0), (-1, 0), (1, 1), (-1, -1)) if (t["x"] + dx, t["y"] + dy) not in taken and t["x"] + dx >= 0 and t["y"] + dy >= 0)
        drag(pg, (t["x"], t["y"]), to)
        check((tok_of(cn)["x"], tok_of(cn)["y"]) == to, f"he drags {cn} on the map")
        gob = "Goblin 1" if k == 0 else "Goblin 2"
        goblin_next_to(cn, gob); pg.wait_for_timeout(2500)
        g0 = hp(gob)
        tap_move(pg, "Slash"); tap_token(pg, gob); res = wait_done(pg)
        print(f"    {cn} Slash:", res.replace(chr(10), " / ")[:120])
        check(gob in res and (hp(gob) < g0) == ("missed" not in res), f"{cn}'s Slash on {gob}: rolled, HP matches")
        end_turn(pg, cn)

    # ---- Gnocchi ------------------------------------------------------------------------
    print("== Gnocchi's turn"); n = "Gnocchi"; pg = ph[n]
    common_turn_checks(n)
    goblin_next_to(n, "Goblin 3"); pg.wait_for_timeout(2500)
    g3 = hp("Goblin 3")
    tap_move(pg, "Reckless attack"); pg.wait_for_timeout(1500)
    tap_move(pg, "Great Axe"); tap_token(pg, "Goblin 3"); res = wait_done(pg)
    print("    Great Axe:", res.replace("\n", " / ")[:120])
    rolls = call("GET", f"/api/rolls?encounter_id={eid}")["rolls"]
    dmg = next((r for r in rolls if r["kind"] == "damage" and "Great Axe" in (r["label"] or "")), None)
    m = re.search(r"(\d+) damage, doubled", res)
    check("missed" in res or (m and dmg and int(m.group(1)) == 2 * dmg["total"] and g3 - hp("Goblin 3") == int(m.group(1))),
          "Reckless + Great Axe: the rolled damage is doubled, and that's what comes off")
    end_turn(pg, n)

    # ---- the goblins: Yamato parries ---------------------------------------------------------
    print("== Goblin 1 attacks Yamato: he parries")
    while not current().startswith("Goblin"):
        call("POST", f"/api/encounters/{eid}/next")
    y0 = hp("Yamato")
    call("POST", f"/api/combatants/{by['Yamato']['id']}/hp", {"op": "damage", "amount": 8, "by": "Goblin 1"})
    ph["Yamato"].wait_for_timeout(4000)
    pb = ph["Yamato"].get_by_role("button", name=re.compile("^Parry"))
    check(pb.count() > 0, "Yamato's phone offers Parry on the goblin's turn")
    if pb.count():
        pb.first.click(); ph["Yamato"].wait_for_timeout(3000)
        check(hp("Yamato") in (y0 - 8, y0 - 4), f"the roll-off settles it ({y0} -> {hp('Yamato')})")

    print("== Pings, leaving and rejoining, landscape")
    g = ph["Gnocchi"]
    g.evaluate("window.scrollTo(0, 0)"); g.locator("[data-ptool=ping]").click(); g.mouse.click(*screen(g, 18, 3)); g.wait_for_timeout(3500)
    check(any(p for p in call("GET", f"/api/maps/{mid}")["pings"] if p["by"] == "Gnocchi's player"), "a ping from Gnocchi's phone reaches the map")
    g.locator("#leave").click(); g.wait_for_timeout(300); g.locator("#leave").click(); g.wait_for_timeout(1500)
    check("/join" in g.url, "Leave this game (tap twice) goes back to the join page")
    ph["Gnocchi"] = join("Gnocchi", "Gnocchi again")
    try:
        ph["Gnocchi"].wait_for_function("() => /Gnocchi/.test(document.querySelector('#me').innerText)", timeout=10000)  # the character loads
    except Exception:
        pass
    check("Gnocchi" in ph["Gnocchi"].locator("#me").inner_text(), "after Leave this game, the player joins straight back in as Gnocchi")
    l = ph["Lux Fedelis"]
    if DEVICES["Lux Fedelis"] in ("phone", "tablet"):
        w, h = SIZES[DEVICES["Lux Fedelis"]]; l.set_viewport_size({"width": h, "height": w})
    l.wait_for_timeout(1200)
    sw = l.evaluate("document.documentElement.scrollWidth - innerWidth")
    check(sw <= 1, f"Lux's screen ({DEVICES['Lux Fedelis']}): nothing sticks out sideways ({sw}px)")
    st_box, me_box = l.locator("#stage").bounding_box(), l.locator("#me").bounding_box()
    check(me_box["x"] > st_box["x"] + st_box["width"] - 5, f"Lux's {DEVICES['Lux Fedelis']} (wide): the map beside the character")
    b.close()
fails = [m for ok, m in results if not ok]
print(f"\n{len(results) - len(fails)} passed, {len(fails)} failed"); [print("FAILED:", f) for f in fails]
print("PROBLEMS:", problems)
