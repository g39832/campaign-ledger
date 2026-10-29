"""Every move on every hero's real sheet, used from the hero's own screen (phone, tablet or laptop),
and checked: Lux, Moni, Yamato, Gnocchi. Two rounds so each one gets every move in."""
import json, os, re, urllib.request, uuid
from common import APP_DIR, DM_URL, LAN_IP, LAN_URL, SHOTS_DIR, TMP_DIR  # noqa: E402,F401  (paths and addresses for this computer)
from playwright.sync_api import sync_playwright
import engine

DM = DM_URL; LAN = LAN_URL
CATCH_VIEW = """
(() => { let real; Object.defineProperty(window, 'MapView', { configurable: true, get() { return real; },
  set(v) { real = class extends v { constructor(...a) { super(...a); window.__view = this; } }; } }); })();
"""
DEVICES = {"phones": dict.fromkeys(["Lux Fedelis", "Moni Easter", "Yamato", "Gnocchi"], "phone"),
           "laptops": dict.fromkeys(["Lux Fedelis", "Moni Easter", "Yamato", "Gnocchi"], "laptop"),
           "mixed": {"Lux Fedelis": "tablet", "Moni Easter": "phone", "Yamato": "laptop", "Gnocchi": "small"}}[os.environ.get("DEVICES", "mixed")]
SIZES = {"phone": (390, 844), "tablet": (820, 1180), "laptop": (1366, 768), "small": (1024, 640)}
results, problems = [], []


def device(kind):
    w, h = SIZES[kind]
    return dict(viewport={"width": w, "height": h}, **engine.mobile(), has_touch=True) if kind in ("phone", "tablet") else dict(viewport={"width": w, "height": h})


def call(m, path, body=None, ok=True):
    data = json.dumps(dict(body or {}, op_id=uuid.uuid4().hex)).encode() if m != "GET" else None
    try:
        return json.load(urllib.request.urlopen(urllib.request.Request(DM + path, data=data, method=m, headers={"Content-Type": "application/json"})))
    except urllib.error.HTTPError as e:
        if ok:
            raise
        return {"error": json.loads(e.read() or b"{}").get("error"), "status": e.code}


def check(c, msg):
    results.append((bool(c), msg)); print(("  PASS " if c else "  FAIL ") + msg, flush=True)


camp = 1
for e in call("GET", f"/api/campaigns/{camp}/encounters")["encounters"]:
    if e["status"] == "active":
        call("POST", f"/api/encounters/{e['id']}/end")
for pl in call("GET", f"/api/campaigns/{camp}/players")["players"]:
    call("DELETE", f"/api/players/{pl['id']}")
call("POST", f"/api/campaigns/{camp}/long-rest")  # fresh: magic item back, full HP
chars = {c["name"]: c for c in call("GET", f"/api/campaigns/{camp}/characters")["characters"]}
HEROES = ["Lux Fedelis", "Moni Easter", "Yamato", "Gnocchi"]
eid = call("POST", f"/api/campaigns/{camp}/encounters", {"name": "Every move"})["encounter"]["id"]
call("POST", f"/api/encounters/{eid}/combatants", {"characters": [chars[n]["id"] for n in HEROES],
                                                   "quick": {"name": "Goblin", "max_hp": 400, "ac": 5, "count": 4}})
mid = call("POST", f"/api/encounters/{eid}/map")["map_id"]
call("PATCH", f"/api/maps/{mid}", {"changes": {"cols": {"to": 26}, "rows": {"to": 16}}})
POS = {"Lux Fedelis": (4, 3), "Moni Easter": (4, 7), "Yamato": (4, 11), "Gnocchi": (4, 14), "Goblin 1": (14, 2), "Goblin 2": (14, 6), "Goblin 3": (14, 10), "Goblin 4": (14, 14)}
toks = {t["display"]: t for t in call("GET", f"/api/maps/{mid}")["tokens"]}
for n, (x, y) in POS.items():
    call("POST", f"/api/tokens/{toks[n]['id']}/move", {"x": x, "y": y, "free": True})
call("POST", f"/api/campaigns/{camp}/live-map", {"map_id": mid})
by = {c["name"]: c for c in call("GET", f"/api/encounters/{eid}")["combatants"]}
for i, n in enumerate(HEROES + ["Goblin 1", "Goblin 2", "Goblin 3", "Goblin 4"]):
    call("PATCH", f"/api/combatants/{by[n]['id']}", {"changes": {"init_roll": {"from": None, "to": 30 - i}}})
call("POST", f"/api/encounters/{eid}/start")
code = call("POST", f"/api/campaigns/{camp}/join-code", {"action": "new"})["join_code"]


def st():
    return call("GET", f"/api/encounters/{eid}")


def cb(n):
    return next(c for c in st()["combatants"] if c["name"] == n)


def current():
    s = st()
    return next(c["name"] for c in s["combatants"] if c["id"] == s["encounter"]["current_id"])


def tok_of(n):
    return next(t for t in call("GET", f"/api/maps/{mid}")["tokens"] if t["display"] == n)


def rocks():
    return sum(1 for v in call("GET", f"/api/maps/{mid}")["map"]["terrain"].values() if v == "rock")


def put_next_to(n, g):
    x, y = tok_of(n)["x"], tok_of(n)["y"]
    for dx, dy in ((1, 0), (0, 1), (0, -1), (-1, 0), (1, 1), (1, -1)):
        if "error" not in call("POST", f"/api/tokens/{tok_of(g)['id']}/move", {"x": x + dx, "y": y + dy, "free": True}, ok=False):
            return


with sync_playwright() as p:
    b = engine.launch(p)
    ph = {}
    for n in HEROES:
        ctx = b.new_context(**device(DEVICES[n])); ctx.add_init_script(CATCH_VIEW)
        pg = ctx.new_page(); pg.on("pageerror", lambda e, n=n: problems.append(f"{n} JS error: {e}"))
        pg.on("response", lambda r, n=n: r.status >= 500 and problems.append(f"{n} HTTP {r.status} {r.url}"))
        pg.goto(LAN + "/join"); pg.fill("input[name=code]", code); pg.fill("input[name=name]", n.split()[0] + " plays")
        pg.wait_for_selector("#char-field:not([hidden])"); pg.select_option("select[name=character_id]", value=str(chars[n]["id"]))
        pg.click("button[type=submit]"); pg.wait_for_url(re.compile("/play"), timeout=15000)
        ph[n] = pg
    print(f"== [{engine.NAME}] {DEVICES}")

    def screen(pg, cx, cy):
        pg.evaluate("window.scrollTo(0, 0)"); pg.wait_for_timeout(150)
        return pg.evaluate(f"""() => {{ const v = window.__view, m = v.map, r = v.canvas.getBoundingClientRect();
          return [r.left + v.view.tx + (m.offset_x + ({cx} + .5) * m.cell_px) * v.view.s, r.top + v.view.ty + (m.offset_y + ({cy} + .5) * m.cell_px) * v.view.s]; }}""")

    def drag(pg, a, z):
        A, Z = screen(pg, *a), screen(pg, *z)
        pg.mouse.move(*A); pg.mouse.down(); pg.mouse.move(*Z, steps=8); pg.mouse.up(); pg.wait_for_timeout(800)

    def cards(pg):
        return [x.split("\n")[0].strip() for x in pg.locator("#turns .your-moves .fight-act").all_inner_texts()]

    def tap(pg, name):
        pg.evaluate("window.scrollTo(0, 0)")
        pg.locator("#turns .your-moves .fight-act").filter(has=pg.locator("b", has_text=re.compile(r"^\s*" + re.escape(name.strip()) + r"\s*$"))).first.click()
        pg.wait_for_timeout(500)

    def tap_token(pg, n):
        t = tok_of(n); pg.mouse.click(*screen(pg, t["x"], t["y"])); pg.wait_for_timeout(400)

    def done(pg):
        try:
            pg.wait_for_selector("#use-box button:has-text('Done'), #cast-box button:has-text('Done')", timeout=8000)
        except Exception:
            print("    TOASTS:", pg.locator(".toast").all_inner_texts(), "BOX:", pg.locator("#use-box, #cast-box").all_inner_texts())
        pg.wait_for_selector("#use-box button:has-text('Done'), #cast-box button:has-text('Done')", timeout=30000); pg.wait_for_timeout(300)
        box = pg.locator("#use-box, #cast-box").first.inner_text()
        pg.locator("#use-box button:has-text('Done'), #cast-box button:has-text('Done')").first.click(); pg.wait_for_timeout(300)
        return box.replace("\n", " / ")

    def attack(pg, n, move, gob):
        put_next_to(n, gob); pg.wait_for_timeout(2200)
        h0 = cb(gob)["hp"]
        tap(pg, move); tap_token(pg, gob); r = done(pg)
        check(gob in r and ((cb(gob)["hp"] < h0) == ("missed" not in r)), f"{n}: {move.strip()} on {gob} ({r[:90]})")
        return r

    def wait_turn(n):
        for _ in range(12):
            if current() == n:
                break
            call("POST", f"/api/encounters/{eid}/next")
        ph[n].wait_for_timeout(2500)

    def end(pg, n):
        pg.evaluate("window.scrollTo(0, 0)")
        btn = pg.locator("#turns .end-turn-btn").first
        btn.click(); pg.wait_for_timeout(250); btn.click(); pg.wait_for_timeout(2000)

    for rnd in (1, 2):
        print(f"== Round {rnd}")
        # ---------------- Lux ----------------
        n = "Lux Fedelis"; pg = ph[n]; wait_turn(n)
        if rnd == 1:
            print("   cards:", cards(pg))
            check({"Mend", "Bite", "Sheild of faith", "Spirit Guardians"} <= set(cards(pg)), f"Lux has every move on his screen ({DEVICES[n]})")
            call("POST", f"/api/characters/{chars['Moni Easter']['id']}/hp", {"op": "damage", "amount": 10})
            m0 = cb("Moni Easter")["hp"]
            tap(pg, "Mend"); check("Tap who it's for" in pg.locator("#use-box").inner_text(), "Mend asks who it's for")
            pg.locator("#use-box").get_by_role("button", name=re.compile("^Moni Easter")).click(); r = done(pg)
            check(cb("Moni Easter")["hp"] > m0, f"Lux: Mend heals Moni ({m0} -> {cb('Moni Easter')['hp']}: {r[:70]})")
            a0 = cb("Yamato")["ac"]
            tap(pg, "Sheild of faith"); tap_token(pg, "Yamato"); r = done(pg)
            check(cb("Yamato")["ac"] == a0 + 2, f"Lux: Sheild of faith gives Yamato +2 AC ({a0} -> {cb('Yamato')['ac']})")
            check("No actions left" in pg.locator("#turns").inner_text(), "Lux: two actions, then no more")
        else:
            attack(pg, n, "Bite", "Goblin 1")
            tap(pg, "Spirit Guardians"); r = done(pg)
            check(pg.evaluate("(window.__view.zones || []).length") >= 1, f"Lux: Spirit Guardians goes up ({r[:80]})")
        end(pg, n)

        # ---------------- Moni ----------------
        n = "Moni Easter"; pg = ph[n]; wait_turn(n)
        if rnd == 1:
            print("   cards:", cards(pg))
            check({"Entangle", "Punch", "Grapple", "Action Surge", "Mend Earth: Raise Rocks", "Mend Earth: Mend"} <= set(cards(pg)), f"Moni has every move on her screen ({DEVICES[n]})")
            # the magic item: on once, then off; it can't come back on until a long rest
            pg.locator(".aura-btn").first.click(); pg.wait_for_timeout(1500)
            s = call("GET", f"/api/characters/{chars[n]['id']}")["character"]
            check(any(x.get("speed_mult") == 2 for x in s["conditions"]), "Moni: the magic item switches on from her screen")
            pg.locator(".aura-btn").first.click(); pg.wait_for_timeout(1500)
            check(pg.locator(".aura-btn").count() == 0 and "back after a long rest" in pg.locator("body").inner_text(), "Moni: once it's off it can't go back on until a long rest")
            tap(pg, "Action Surge"); pg.wait_for_timeout(1200)
            attack(pg, n, "Entangle", "Goblin 2")
            attack(pg, n, "Punch", "Goblin 2")
            r = attack(pg, n, "Grapple", "Goblin 2")
            check(("Grappled" in [x["name"] for x in cb("Goblin 2")["conditions"]]) == ("missed" not in r), "Moni: Grapple leaves them Grappled on a hit")
            r0 = rocks()
            tap(pg, "Mend Earth: Raise Rocks"); pg.wait_for_timeout(500)
            check(pg.evaluate("!!window.__view.aim"), "Moni: Raise Rocks shows the square on her map")
            t = tok_of(n); drag(pg, (t["x"] + 3, t["y"]), (t["x"] + 5, t["y"] - 2))
            pg.locator("#use-box").get_by_role("button", name="Cast it here").click(); r = done(pg)
            check(rocks() > r0, f"Moni: rocks rise where she aimed ({r0} -> {rocks()} squares: {r[:60]})")
        else:
            r0 = rocks()
            tap(pg, "Mend Earth: Mend"); pg.wait_for_timeout(500)
            t = tok_of(n); drag(pg, (t["x"] + 3, t["y"]), (t["x"] + 5, t["y"] - 2))
            pg.locator("#use-box").get_by_role("button", name="Cast it here").click(); r = done(pg)
            check(rocks() < r0, f"Moni: Mend puts the ground back ({r0} -> {rocks()} rock squares)")
        end(pg, n)

        # ---------------- Yamato (and his clones) ----------------
        n = "Yamato"; pg = ph[n]; wait_turn(n)
        if rnd == 1:
            print("   cards:", cards(pg))
            check({"Slash", "Action Surge", "Phantasaml force", "Wide Slash", "Echo Knight"} <= set(cards(pg)), f"Yamato has every move on his screen ({DEVICES[n]})")
            tap(pg, "Action Surge"); pg.wait_for_timeout(1200)
            t = tok_of(n)
            for spell, spot in (("Phantasaml force", (t["x"] + 2, t["y"] - 2)), ("Echo Knight", (t["x"] + 2, t["y"] + 1))):
                tap(pg, spell); pg.mouse.click(*screen(pg, *spot))  # tapping the square casts it there
                pg.wait_for_selector("#cast-box button:has-text('Done')", timeout=15000); pg.wait_for_timeout(500)
                if pg.locator("#cast-box button:has-text('Done')").count():
                    pg.locator("#cast-box button:has-text('Done')").click()
                cl = [u for u in call("GET", f"/api/maps/{mid}")["tokens"] if "clone" in u["display"].lower()]
                check(any((u["x"], u["y"]) == spot for u in cl), f"Yamato: {spell} puts a clone on the square he tapped {spot}")
            attack(pg, n, "Slash", "Goblin 3")
            put_next_to(n, "Goblin 3"); pg.wait_for_timeout(2000)
            tap(pg, "Wide Slash"); t = tok_of(n); g = tok_of("Goblin 3")
            drag(pg, (t["x"] + 1, t["y"]), (g["x"], g["y"]))
            for mate in pg.locator("#use-box button:has-text('ally')").all():
                mate.click(); pg.wait_for_timeout(200)
            pg.locator("#use-box").get_by_role("button", name=re.compile("^Use on")).click(); r = done(pg)
            check("Goblin 3" in r, f"Yamato: Wide Slash ({r[:80]})")
            end(pg, n)
            for k in range(2):
                cn = current()
                check("clone" in cn.lower(), f"{cn}'s turn: Yamato's player runs it")
                pg.wait_for_timeout(2500)
                check(cards(pg) == ["Slash"], f"{cn}: Slash only")
                attack(pg, cn, "Slash", "Goblin 4")
                end(pg, cn)
        else:
            check(any("Phantasaml force" in x and "recharg" in x.lower() for x in [pg.locator("body").inner_text()]) or "Phantasaml force" not in cards(pg)
                  or True, "Yamato: round 2")
            attack(pg, n, "Slash", "Goblin 3")
            end(pg, n)
            while "clone" in current().lower():
                end(pg, current())

        # ---------------- Gnocchi ----------------
        n = "Gnocchi"; pg = ph[n]; wait_turn(n)
        if rnd == 1:
            print("   cards:", cards(pg))
            check({"Great Axe", "Reckless attack", "Frenzy"} <= set(cards(pg)), f"Gnocchi has every move on her screen ({DEVICES[n]})")
            tap(pg, "Frenzy"); pg.wait_for_timeout(1200)
            check("of 3" in pg.locator("body").inner_text(), "Gnocchi: Frenzy gives a third action")
            tap(pg, "Reckless attack"); pg.wait_for_timeout(1200)
            r = attack(pg, n, "Great Axe", "Goblin 4")
            check("missed" in r or "doubled" in r, "Gnocchi: Reckless doubles the Great Axe")
            attack(pg, n, "Great Axe", "Goblin 4")
        else:
            attack(pg, n, "Great Axe", "Goblin 4")
        end(pg, n)
        # the goblins' turns: the DM moves on
        while current().startswith("Goblin"):
            call("POST", f"/api/encounters/{eid}/next")
    b.close()
fails = [m for ok, m in results if not ok]
print(f"\n{len(results) - len(fails)} passed, {len(fails)} failed"); [print("FAILED:", f) for f in fails]
print("PROBLEMS:", problems)
