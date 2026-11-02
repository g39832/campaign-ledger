"""Reactions, Yamato's three clones and what's left each turn, clicked through for real: four
players on their own devices (DEVICES=phones|laptops|tablets|mixed) and the DM on the Combat
screen, the map and the sheets. Uses the real characters' new rows:
Moni's Deflect attacks + Absorb Elements, Yamato's Phantasmal Killers + Action surge, Gnocchi's Sentinel."""
import json, os, re, urllib.request, uuid
from common import APP_DIR, DM_URL, LAN_IP, LAN_URL, SHOTS_DIR, TMP_DIR  # noqa: E402,F401
from playwright.sync_api import sync_playwright
import engine

DM = DM_URL; LAN = LAN_URL
SHOTS = os.path.join(SHOTS_DIR, "reactions")
os.makedirs(SHOTS, exist_ok=True)
CATCH_VIEW = """
(() => { let real; Object.defineProperty(window, 'MapView', { configurable: true, get() { return real; },
  set(v) { real = class extends v { constructor(...a) { super(...a); window.__view = this;
    const add = this.addFx.bind(this); window.__fx = []; this.addFx = (f) => { window.__fx.push(f.name || f.style || f.type); return add(f); }; } }; } }); })();
"""
results, problems = [], []
DEVICES = {
    "phones": dict.fromkeys(["Lux Fedelis", "Moni Easter", "Yamato", "Gnocchi"], "phone"),
    "laptops": dict.fromkeys(["Lux Fedelis", "Moni Easter", "Yamato", "Gnocchi"], "laptop"),
    "tablets": dict.fromkeys(["Lux Fedelis", "Moni Easter", "Yamato", "Gnocchi"], "tablet"),
    "mixed": {"Lux Fedelis": "laptop", "Moni Easter": "phone", "Yamato": "small", "Gnocchi": "tablet"},
}[os.environ.get("DEVICES", "mixed")]
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
for n in HEROES:  # everyone up and well for the test (the copy only)
    ch = call("GET", f"/api/characters/{chars[n]['id']}")["character"]
    call("PATCH", f"/api/characters/{ch['id']}", {"changes": {"current_hp": {"from": ch["current_hp"], "to": ch["max_hp"]},
                                                           "conditions": {"from": ch["conditions"], "to": []}}})
eid = call("POST", f"/api/campaigns/{camp}/encounters", {"name": "Reactions"})["encounter"]["id"]
call("POST", f"/api/encounters/{eid}/combatants", {"characters": [chars[n]["id"] for n in HEROES],
                                                   "quick": {"name": "Goblin", "max_hp": 300, "ac": 5, "count": 2}})
by = {c["name"]: c for c in call("GET", f"/api/encounters/{eid}")["combatants"]}
for g in ("Goblin 1", "Goblin 2"):
    call("POST", f"/api/combatants/{by[g]['id']}/statblock", {"attacks": "Scimitar +4 to hit 1d6+2 slashing"})
mid = call("POST", f"/api/encounters/{eid}/map")["map_id"]
call("PATCH", f"/api/maps/{mid}", {"changes": {"cols": {"to": 24}, "rows": {"to": 14}}})
POS = {"Yamato": (3, 10), "Moni Easter": (8, 5), "Goblin 1": (9, 5), "Gnocchi": (10, 5), "Lux Fedelis": (3, 2), "Goblin 2": (18, 11)}
toks = {t["display"]: t for t in call("GET", f"/api/maps/{mid}")["tokens"]}
for n, (x, y) in POS.items():
    call("POST", f"/api/tokens/{toks[n]['id']}/move", {"x": x, "y": y, "free": True})
call("POST", f"/api/campaigns/{camp}/live-map", {"map_id": mid})
ORDER = ["Yamato", "Goblin 1", "Moni Easter", "Gnocchi", "Lux Fedelis", "Goblin 2"]
for i, n in enumerate(ORDER):
    call("PATCH", f"/api/combatants/{by[n]['id']}", {"changes": {"init_roll": {"from": None, "to": 30 - i}}})
call("POST", f"/api/encounters/{eid}/start")
code = call("POST", f"/api/campaigns/{camp}/join-code", {"action": "new"})["join_code"]


def st():
    return call("GET", f"/api/encounters/{eid}")


def cb(n):
    return next(c for c in st()["combatants"] if c["name"] == n)


def hp(n):
    return cb(n)["hp"]


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

    print(f"== [{engine.NAME}] players join: {DEVICES}")
    for n in HEROES:
        ph[n] = join(n, n.split()[0] + "'s player")
    dmctx = b.new_context(viewport={"width": 1366, "height": 900}); dmctx.add_init_script(CATCH_VIEW)
    dm = dmctx.new_page()
    dm.on("pageerror", lambda e: problems.append(f"DM JS error: {e}"))
    dm.on("response", lambda r: r.status >= 500 and problems.append(f"DM HTTP {r.status} {r.url}"))
    for pg in ph.values():
        pg.wait_for_timeout(1500)

    def screen(pg, cx, cy):
        pg.evaluate("window.scrollTo(0, 0)"); pg.wait_for_timeout(150)
        return pg.evaluate(f"""() => {{ const v = window.__view, m = v.map, r = v.canvas.getBoundingClientRect();
          return [r.left + v.view.tx + (m.offset_x + ({cx} + .5) * m.cell_px) * v.view.s, r.top + v.view.ty + (m.offset_y + ({cy} + .5) * m.cell_px) * v.view.s]; }}""")

    def panel(pg):
        return pg.locator("#turns .your-moves")

    def tap_move(pg, name):
        pg.evaluate("window.scrollTo(0, 0)")
        panel(pg).locator(".fight-act").filter(has=pg.locator("b", has_text=re.compile(r"^\s*" + re.escape(name) + r"\s*$"))).first.click()
        pg.wait_for_timeout(600)

    def strip(pg):
        return " | ".join(pg.locator("#turns .turn-strip").all_inner_texts()).replace("\n", " ")

    def toasts(pg):
        return " | ".join(pg.locator(".toast").all_inner_texts())

    def wait_for(pg, fn, ms=8000):
        for _ in range(ms // 250):
            if fn():
                return True
            pg.wait_for_timeout(250)
        return fn()

    def done_box(pg):
        pg.wait_for_selector("#use-box button:has-text('Done'), #cast-box button:has-text('Done')", timeout=30000)
        pg.wait_for_timeout(400)
        t = (pg.locator("#use-box").inner_text() if pg.locator("#use-box").count() else pg.locator("#cast-box").inner_text())
        pg.locator("#use-box button:has-text('Done'), #cast-box button:has-text('Done')").first.click(); pg.wait_for_timeout(300)
        return t

    def end_turn(pg, who):
        pg.evaluate("window.scrollTo(0, 0)")
        pg.locator("#turns .end-turn-btn").click(); pg.wait_for_timeout(250); pg.locator("#turns .end-turn-btn").click(); pg.wait_for_timeout(2500)
        check(current() != who, f"{who}'s turn ends from the device (now {current()})")

    def no_overflow(pg, who):
        sw = pg.evaluate("document.documentElement.scrollWidth - innerWidth")
        check(sw <= 1, f"{who} ({DEVICES.get(who, 'DM')}): nothing sticks out sideways ({sw}px)")

    def dm_combat(select):
        dm.goto(f"{DM}/combat/{eid}"); dm.wait_for_selector("#init-list li.combatant")
        dm.locator("#init-list li.combatant").filter(has_text=select).first.locator(".c-name").click(); dm.wait_for_timeout(400)

    def dm_hit(attacker, target, amount):
        """The DM deals a hit on the Combat screen: pick the attacker, tap the target, type it, Deal damage."""
        dm_combat(attacker)
        for _ in range(3):
            chip = dm.locator("#detail .target-chip").filter(has_text=re.compile("^" + re.escape(target))).first
            if "is-on" in (chip.get_attribute("class") or ""):
                break
            chip.click(); dm.wait_for_timeout(400)
        dm.locator("#detail input[aria-label='Damage to deal']").fill(str(amount))
        dm.locator("#detail .hit-box .hp-ctl").get_by_role("button", name=re.compile("Deal damage")).click(); dm.wait_for_timeout(1500)

    # ---- Yamato: Phantasmal Killers (two clones, AC 10, 1 HP), a third, then Action surge -----------
    print("== Yamato's turn: three clones")
    y = ph["Yamato"]
    wait_for(y, lambda: "It's your turn" in y.locator("#turns").inner_text())
    s0 = strip(y)
    check("2 of 2 actions left" in s0 and "Reaction ready" in s0 and "to move" in s0, f"his turn: the strip says 2 of 2 actions, movement, reaction ready ({s0})")
    tap_move(y, "Phantasmal Killers")
    check("tap the square on the map where" in y.locator("#hint").inner_text(), "Phantasmal Killers asks where the clones appear")
    y.mouse.click(*screen(y, 8, 6))
    done_box(y)
    clones = [c for c in st()["combatants"] if "clone" in c["name"].lower()]
    check(len(clones) == 2 and all(c["ac"] == 10 and c["hp"] == 1 for c in clones), f"two clones, AC 10 and 1 HP each ({[(c['name'], c['ac'], c['hp']) for c in clones]})")
    k1 = next((c["name"] for c in clones if (tok_of(c["name"])["x"], tok_of(c["name"])["y"]) == (8, 6)), None)
    check(k1 is not None, f"one appears on the square he tapped ({k1})")
    wait_for(y, lambda: "1 of 2 actions left" in strip(y))
    check("1 of 2 actions left" in strip(y), "the strip counts down: 1 of 2 actions left")
    check("1 of 2 action" in toasts(y), f"a toast says what's left ({toasts(y)[:100]})")
    tap_move(y, "Phantasaml force")
    y.mouse.click(*screen(y, 3, 12))
    done_box(y)
    clones = [c for c in st()["combatants"] if "clone" in c["name"].lower()]
    check(len(clones) == 3, f"a third clone with Phantasmal Force: three at once ({[c['name'] for c in clones]})")
    wait_for(y, lambda: "No actions left" in strip(y))
    check("No actions left" in strip(y), "no actions left: the strip says so")
    tap_move(y, "Action surge")
    wait_for(y, lambda: "1 of 3 actions left" in strip(y))
    check("1 of 3 actions left" in strip(y), f"his Action surge (a spell row) gives one more action ({strip(y)})")
    tap_move(y, "Echo Knight"); y.wait_for_timeout(500)
    if y.locator("#cast-box .cast-go").count():
        y.locator("#cast-box .cast-go").click()
    elif "tap the square" in y.locator("#hint").inner_text():
        y.mouse.click(*screen(y, 1, 12))
    wait_for(y, lambda: "3 at a time" in toasts(y))
    check("3 at a time" in toasts(y), f"a fourth clone is refused: three at a time ({toasts(y)[:120]})")
    if y.locator("#cast-box").count():
        y.keyboard.press("Escape"); y.wait_for_timeout(300)
    y.screenshot(path=os.path.join(SHOTS, f"{engine.NAME}_{DEVICES['Yamato']}_yamato.png"))
    no_overflow(y, "Yamato")
    end_turn(y, "Yamato")

    print("== His clones' turns: what each has left, and Dismiss")
    names = [c["name"] for c in st()["combatants"] if "clone" in c["name"].lower()]
    for k, cn in enumerate(names):
        check(current() == cn, f"next up: {cn}")
        wait_for(y, lambda: "you control it" in y.locator("#turns").inner_text())
        s1 = strip(y)
        check((cn + "'s turn").lower() in s1.lower() and "2 of 2 actions left" in s1, f"{cn}'s strip: 2 of 2 actions ({s1[:90]})")
        if k < len(names) - 1:
            end_turn(y, cn)
        else:
            btn = y.locator("#turns button").filter(has_text="Dismiss").first
            btn.click(); y.wait_for_timeout(250); y.locator("#turns button").filter(has_text="Tap again to dismiss").first.click(); y.wait_for_timeout(2500)
            check(not any(c["name"] == cn for c in st()["combatants"]) and current() == "Goblin 1", f"Dismiss: {cn} is gone and the turn moves on ({current()})")
            check(not any(t["display"] == cn for t in call("GET", f"/api/maps/{mid}")["tokens"]), f"{cn}'s token is off the map")

    # ---- Goblin 1 hits Moni: Deflect (and send it back), Gnocchi's Sentinel ------------------------
    print("== Goblin 1 hits Moni (DM, Combat screen)")
    m0 = hp("Moni Easter")
    dm_hit("Goblin 1", "Moni Easter", 9)
    check(hp("Moni Easter") == m0 - 9, f"Moni takes 9 ({m0} -> {hp('Moni Easter')})")
    mo, gn, lx = ph["Moni Easter"], ph["Gnocchi"], ph["Lux Fedelis"]
    wait_for(mo, lambda: mo.locator("#turns .react-box.is-deflect").count() > 0)
    check(mo.locator("#turns .react-box.is-deflect").count() == 1, "Moni's device offers Deflect attacks")
    check("hit for 9 by Goblin 1" in mo.locator("#turns .react-box.is-deflect").inner_text() and "1d10+1+5" in mo.locator("#turns .react-box.is-deflect").inner_text(),
          f"it says the hit, who did it and the dice ({mo.locator('#turns .react-box.is-deflect').inner_text()[:120]})")
    check(mo.locator("#turns .react-box.is-absorb").count() == 0, "no Absorb Elements yet: it hasn't been cast")
    wait_for(gn, lambda: gn.locator("#turns .react-box.is-sentinel").count() > 0)
    check("Goblin 1 attacked Moni Easter next to you" in gn.locator("#turns").inner_text(), "Gnocchi's device: Sentinel, Goblin 1 attacked Moni next to you")
    check(lx.locator("#turns .react-box").count() == 0 and y.locator("#turns .react-box").count() == 0, "Lux and Yamato get no reaction offers")
    dm.wait_for_timeout(500)
    check(dm.locator("#init-list li.combatant").filter(has_text="Gnocchi").first.get_by_role("button", name=re.compile("Sentinel")).count() == 1,
          "the DM's list shows Gnocchi's Sentinel button too")
    mo.screenshot(path=os.path.join(SHOTS, f"{engine.NAME}_{DEVICES['Moni Easter']}_moni_offer.png"))
    mo.locator("#turns .react-box.is-deflect button").click()
    wait_for(mo, lambda: "Reaction used" in strip(mo) or mo.locator("#turns .react-box.is-redirect").count() > 0)
    log = [e["message"] for e in st()["log"]]
    dline = next((m for m in reversed(log) if "Deflect" in m and "reaction" in m), "")
    print("   ", dline)
    taken = int(re.search(r"takes (\d+) instead", dline).group(1)) if dline else -1
    check(dline and hp("Moni Easter") == m0 - taken, f"Deflect: the hit is cut by the roll ({m0 - 9} -> {hp('Moni Easter')})")
    g1 = hp("Goblin 1")
    if taken == 0:
        check(mo.locator("#turns .react-box.is-redirect").count() == 1, "cut to 0: she's asked who to send it at")
        tgt = mo.locator("#turns .react-box.is-redirect button")
        check(tgt.count() == 1 and "Goblin 1" in tgt.first.inner_text(), f"only Goblin 1 is within 10 ft ({tgt.all_inner_texts()})")
        tgt.first.click(); mo.wait_for_timeout(2500)
        check(hp("Goblin 1") == g1 - 9, f"the 9 goes into Goblin 1 ({g1} -> {hp('Goblin 1')})")
        g1 = hp("Goblin 1")
    else:
        check(mo.locator("#turns .react-box.is-redirect").count() == 0, "not cut to 0: nothing to send back")
    wait_for(mo, lambda: "Reaction used" in strip(mo))
    check("Reaction used" in strip(mo) and mo.locator("#turns .react-box.is-absorb").count() == 0, f"her reaction is used: no more offers ({strip(mo)})")
    gn.locator("#turns .react-box.is-sentinel button").click()
    wait_for(gn, lambda: "Reaction used" in strip(gn), 15000)
    sline = next((m for m in reversed([e["message"] for e in st()["log"]]) if "Pasta" in m), "")
    print("   ", sline)
    check("Gnocchi uses Pasta" in sline and (hp("Goblin 1") < g1) == ("missed" not in sline), "Sentinel: Gnocchi strikes Goblin 1 with Pasta, off her turn")
    check("Reaction used" in strip(gn), "Gnocchi's reaction is used")
    check(not re.search(r"\bAC \d", gn.locator("body").inner_text()), "no Armor Class on Gnocchi's screen")
    check(not re.search(r"\b\d+\s*/\s*300\b", lx.locator("body").inner_text()), "players never see a goblin's HP")
    no_overflow(mo, "Moni Easter"); no_overflow(gn, "Gnocchi")

    print("== Phantasmal Killers: the clone next to Goblin 1 is destroyed and bursts")
    dm_hit("Goblin 1", k1, 1)
    s = st()
    burst = next((e["message"] for e in reversed(s["log"]) if "bursts" in e["message"]), "")
    print("   ", burst)
    g1c = cb("Goblin 1")
    shaken = any(x["name"] == "Shaken" for x in g1c["conditions"])
    check(burst and ("Goblin 1 fails" in burst) == shaken and ("Goblin 2" not in burst), f"Goblin 1 (next to it) makes the Dex save DC 10; Goblin 2 (far) doesn't ({'shaken' if shaken else 'saved'})")

    print("== Lux burns her reaction by hand; the DM gives it back")
    wait_for(lx, lambda: lx.locator("#turns .react-burn").count() > 0)
    lx.locator("#turns .react-burn").click(); lx.wait_for_timeout(200); lx.locator("#turns .react-burn").click()
    wait_for(lx, lambda: "Reaction used" in strip(lx))
    check("Reaction used" in strip(lx), f"Lux: Use reaction (tap twice) marks it used ({strip(lx)})")
    dm_combat("Lux Fedelis")
    check("Reaction used" in dm.locator("#detail").inner_text(), "the DM sees it on Lux's details")
    dm.locator("#detail").get_by_role("button", name=re.compile("Give reaction back")).click(); dm.wait_for_timeout(1500)
    wait_for(lx, lambda: "Reaction ready" in strip(lx))
    check("Reaction ready" in strip(lx), "the DM gives it back: Lux's device says ready again")
    lx.screenshot(path=os.path.join(SHOTS, f"{engine.NAME}_{DEVICES['Lux Fedelis']}_lux.png"))
    no_overflow(lx, "Lux Fedelis")

    print("== DM's map: the panel shows the strip and the reaction")
    dm.evaluate(f"localStorage.setItem('combat-sel-{eid}', '{cb('Moni Easter')['id']}')")
    dm.goto(f"{DM}/map/{mid}"); dm.wait_for_selector(".fight .turn-strip", timeout=15000); dm.wait_for_timeout(800)
    check("Reaction used" in dm.locator(".fight .turn-strip").first.inner_text(), "the DM's map panel: Moni's reaction is used")
    dm.screenshot(path=os.path.join(SHOTS, f"{engine.NAME}_dm_map.png"))

    print("== Moni's turn: reaction back; Absorb Elements, then her Punch carries the 1d12")
    call("POST", f"/api/encounters/{eid}/next")
    check(current() == "Moni Easter", "Moni's turn")
    wait_for(mo, lambda: "It's your turn" in mo.locator("#turns").inner_text())
    s2 = strip(mo)
    check("2 of 2 actions left" in s2 and "Reaction ready" in s2, f"her turn: 2 of 2 actions and her reaction is back ({s2})")
    tap_move(mo, "Absorb Elements")   # cast it first, on her turn (one of her actions)
    wait_for(mo, lambda: "Absorb Elements (cast)" in mo.locator("#me").inner_text())
    check("Absorb Elements (cast)" in mo.locator("#me").inner_text() and "1 of 2 actions left" in strip(mo), "she casts Absorb Elements: it waits on her, and it took an action")
    dm_hit("Goblin 2", "Moni Easter", 5)
    wait_for(mo, lambda: mo.locator("#turns .react-box.is-absorb").count() > 0)
    check(mo.locator("#turns .react-box.is-absorb").count() == 1, "now a hit offers it")
    mo.locator("#turns .react-box.is-absorb button").click()
    wait_for(mo, lambda: "Absorb Elements" in mo.locator("#me").inner_text())
    check("Absorb Elements" in mo.locator("#me .c-conds").inner_text(), "Absorb Elements shows on her: +1d12 on the next hit")
    g1 = hp("Goblin 1")
    tap_move(mo, "Punch")
    mo.mouse.click(*screen(mo, *POS["Goblin 1"])); res = done_box(mo)
    print("    Punch:", res.replace("\n", " / ")[:140])
    rolls = call("GET", f"/api/rolls?encounter_id={eid}")["rolls"]
    dmg = max((r for r in rolls if r["kind"] == "damage" and "Punch" in (r["label"] or "")), key=lambda r: r["id"], default=None)
    if "missed" in res:
        check("Absorb Elements" in mo.locator("#me").inner_text(), "a miss: the bonus is still waiting")
    else:
        check(dmg and "1d12" in dmg["expression"], f"the Punch's damage has the +1d12 ({dmg and dmg['expression']})")
        wait_for(mo, lambda: "Absorb Elements" not in mo.locator("#me").inner_text())
        check("Absorb Elements" not in mo.locator("#me").inner_text(), "and then it's used up")
    check("No actions left" in strip(mo) or "last action" in toasts(mo), "after the cast and the Punch: no actions left")
    mo.screenshot(path=os.path.join(SHOTS, f"{engine.NAME}_{DEVICES['Moni Easter']}_moni_turn.png"))

    print("== Lux's Death Ward on Gnocchi, then a huge hit")
    while current() != "Lux Fedelis":
        call("POST", f"/api/encounters/{eid}/next")
    wait_for(lx, lambda: "It's your turn" in lx.locator("#turns").inner_text())
    tap_move(lx, "Death Ward")
    lx.locator("#cast-box .cast-chip").filter(has_text="Gnocchi").first.click(); lx.wait_for_timeout(300)
    lx.locator("#cast-box .cast-go").click(); done_box(lx)
    check(any(x["name"] == "Death Ward" for x in cb("Gnocchi")["conditions"]), "Lux casts Death Ward on Gnocchi from her device")
    dm_hit("Goblin 2", "Gnocchi", 999)
    g = cb("Gnocchi")
    check(g["hp"] == 1 and not any(x["name"] == "Death Ward" for x in g["conditions"]), f"999 damage: Gnocchi drops to 1 HP instead of 0, and the ward is gone ({g['hp']})")
    wait_for(gn, lambda: re.search(r"(^|\D)1\s*/\s*45", gn.locator("#me").inner_text()) is not None)
    check(re.search(r"(^|\D)1\s*/\s*45", gn.locator("#me").inner_text()) is not None, "Gnocchi's device shows 1 HP")

    print("== The spell builder (DM, sheets)")
    dm.goto(f"{DM}/characters/{chars['Moni Easter']['id']}"); dm.wait_for_selector("#spells .spell-card"); dm.wait_for_timeout(600)
    card = dm.locator("#spells .spell-card").nth(next(i for i, sp in enumerate(call("GET", f"/api/characters/{chars['Moni Easter']['id']}")["character"]["spells"]) if "Deflect" in sp["name"]))
    if card.locator(".spell-brief").count():
        card.locator(".spell-brief").click(); dm.wait_for_timeout(400)
    plain = card.locator(".spell-plain").inner_text()
    check("cut the damage by 1d10+dex+level" in plain, f"Deflect attacks reads in plain words ({plain[:110]})")
    sel = card.locator("select").filter(has=dm.locator("option[value=deflect]")).first
    check(sel.input_value() == "deflect", "its Reaction picker says Cut the hit")
    dm.locator("#spells").get_by_role("button", name=re.compile("Add spell")).click(); dm.wait_for_timeout(500)
    new = dm.locator("#spells .spell-card").last
    check(new.locator(".spell-quick button").count() >= 8, "a new spell offers quick starts")
    new.locator(".spell-quick button").filter(has_text="Reaction: hit back").click(); dm.wait_for_timeout(600)
    new = dm.locator("#spells .spell-card").last
    check("an enemy next to you attacks someone else" in new.locator(".spell-plain").inner_text(), "Reaction: hit back fills it in as Sentinel")
    dm.wait_for_timeout(1800)
    sp = call("GET", f"/api/characters/{chars['Moni Easter']['id']}")["character"]["spells"]
    check(sp[-1].get("reaction") == "sentinel", "and it's saved on the sheet")
    new.get_by_role("button", name="Remove spell").click(); dm.wait_for_timeout(1800)
    check(len(call("GET", f"/api/characters/{chars['Moni Easter']['id']}")["character"]["spells"]) == len(sp) - 1, "the test spell is removed again")
    dm.screenshot(path=os.path.join(SHOTS, f"{engine.NAME}_dm_sheet.png"), full_page=True)
    dm.goto(f"{DM}/characters/{chars['Gnocchi']['id']}"); dm.wait_for_selector("#attacks"); dm.wait_for_timeout(600)
    check("hit back an enemy next to you" in dm.locator("#attacks").inner_text(), "Gnocchi's Sentinel row says it's a reaction")
    ph2 = b.new_context(**device("phone")).new_page()
    ph2.goto(f"{DM}/characters/{chars['Yamato']['id']}"); ph2.wait_for_selector("#spells .spell-card"); ph2.wait_for_timeout(600)
    no_overflow(ph2, "DM sheet on a phone")
    b.close()
fails = [m for ok, m in results if not ok]
print(f"\n{len(results) - len(fails)} passed, {len(fails)} failed"); [print("FAILED:", f) for f in fails]
print("PROBLEMS:", problems)
