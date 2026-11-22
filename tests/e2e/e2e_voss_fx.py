"""E2E (2026-11-09): Steven Voss on the DM's battle map, in the "Steven Voss test room" (a data copy).

1. Every one of his moves (attacks, spells, legendary action, phase 2, his drone's Zap) is read by the
   page with its own animation look, and that look plays on the map.
2. Real clicks: Fire Bolt (a spell), a Test Hero spell copied by a drone and cast back from the map's
   LEGENDARY actions, Metal Bend (a straight steel wall dragged anywhere in range), and phase 2's
   Piston Slam (shoves + Shocked) and Magnet Pull (drags them in), each with its animation."""
import json, re, urllib.request, uuid
from common import DM_URL, SHOTS_DIR  # noqa: E402
from playwright.sync_api import sync_playwright
import engine

DM = DM_URL
results, problems = [], []
CATCH = """
(() => { let real; Object.defineProperty(window, 'MapView', { configurable: true, get() { return real; },
  set(v) { real = class extends v { constructor(...a) { super(...a); window.__view = this; window.__fx = [];
    const af = this.attackFx.bind(this); this.attackFx = (fx, age) => { window.__fx.push({ name: fx.name, look: fx.style || '' }); return af(fx, age); }; } }; } }); })();
"""
LOOKS = {"Thunder Gauntlet": "punch", "Arc Wrench": "sparks", "Titan Arm": "punch", "Iron Grip": "punch",
         "Metal Bend": "rock", "Fire Bolt": "flames", "Shocking Grasp": "sparks", "Thunderwave": "arcane", "Shatter": "arcane",
         "Fireball": "flames", "Cone of Cold": "frost", "Cure Wounds": "holy", "Drone Zap": "sparks",
         "Colossus Arms": "quake", "Tesla Lash": "sparks", "Magnet Pull": "sparks", "Piston Slam": "punch", "Overload": "sparks", "Zap": "sparks",
         "Wing Scythe": "slash", "Feather Storm": "arrow", "Star Core Beam": "laser", "Wing Guard Slam": "punch"}


def call(m, path, body=None):
    data = json.dumps(dict(body or {}, op_id=uuid.uuid4().hex)).encode() if m != "GET" else None
    return json.load(urllib.request.urlopen(urllib.request.Request(DM + path, data=data, method=m, headers={"Content-Type": "application/json"})))


def fresh_fight(eid, mid):
    """The copy carries whatever the DM last did in the real test room: start it over (drones gone,
    cooldowns and effects off, full HP, his steel walls folded away)."""
    for t in call("GET", f"/api/maps/{mid}")["tokens"]:
        if t["display"].startswith("Voss Drone"):
            call("DELETE", f"/api/tokens/{t['id']}")
    for c in call("GET", f"/api/encounters/{eid}")["combatants"]:
        if c["name"].startswith("Voss Drone"):
            call("DELETE", f"/api/combatants/{c['id']}")
        elif c["name"] in ("Steven Voss", "Test Hero"):
            for x in c["conditions"]:
                call("DELETE", f"/api/combatants/{c['id']}/conditions/{x['id']}")
            if c["name"] == "Steven Voss":
                call("POST", f"/api/combatants/{c['id']}/hp", {"op": "heal", "amount": 999})
    walls = [[int(v) for v in k.split(",")] for k, t in call("GET", f"/api/maps/{mid}")["map"]["terrain"].items() if t == "bulkhead"]
    if walls:
        call("POST", f"/api/maps/{mid}/terrain", {"value": None, "cells": walls})


def check(c, msg):
    results.append((bool(c), msg)); print(("  PASS " if c else "  FAIL ") + msg, flush=True)


camp = 1
for e in call("GET", f"/api/campaigns/{camp}/encounters")["encounters"]:
    if e["status"] == "active":
        call("POST", f"/api/encounters/{e['id']}/end")
eid = next(e["id"] for e in call("GET", f"/api/campaigns/{camp}/encounters")["encounters"] if e["name"] == "Steven Voss test room")
mid = next(m["id"] for m in call("GET", f"/api/campaigns/{camp}/maps")["maps"] if m["name"] == "Steven Voss test room")
by = {c["name"]: c for c in call("GET", f"/api/encounters/{eid}")["combatants"]}
ST, TH = by["Steven Voss"]["id"], by["Test Hero"]["id"]
hero = call("GET", f"/api/characters/{by['Test Hero']['character_id']}")["character"]
call("PATCH", f"/api/characters/{hero['id']}", {"changes": {"max_hp": {"from": hero["max_hp"], "to": 5000}, "current_hp": {"from": hero["current_hp"], "to": 5000},
                                                     "ac": {"from": hero["ac"], "to": 1}}})  # AC 1 on this copy: his +3 hits land
fresh_fight(eid, mid)
call("POST", f"/api/campaigns/{camp}/live-map", {"map_id": mid})
call("POST", f"/api/encounters/{eid}/start")
drone = next(c for c in call("GET", "/api/creatures")["creatures"] if c["name"] == "Voss Drone")


def tokens():
    return {t["display"]: t for t in call("GET", f"/api/maps/{mid}")["tokens"]}


def place(hx=6, hy=6):
    t = tokens()
    for i, d in enumerate(sorted(n for n in t if n.startswith("Voss Drone"))):  # drones out of the way, in the top corner
        call("POST", f"/api/tokens/{t[d]['id']}/move", {"x": i, "y": 0, "free": True})
    call("POST", f"/api/tokens/{t['Steven Voss']['id']}/move", {"x": 15, "y": 11, "free": True})
    call("POST", f"/api/tokens/{t['Test Hero']['id']}/move", {"x": hx, "y": hy, "free": True})
    call("POST", f"/api/tokens/{t['Steven Voss']['id']}/move", {"x": 7, "y": 6, "free": True})


def hero_at():
    t = tokens()["Test Hero"]
    return (t["x"], t["y"])


def turn(cid):
    for _ in range(12):
        if call("POST", f"/api/encounters/{eid}/next")["encounter"]["current_id"] == cid:
            return


with sync_playwright() as p:
    b = engine.launch(p)
    ctx = b.new_context(viewport={"width": 1400, "height": 1000}); ctx.add_init_script(CATCH)
    dm = ctx.new_page(); dm.on("pageerror", lambda e: problems.append(f"DM JS error: {e}"))
    place(); turn(ST)
    dm.goto(f"{DM}/map/{mid}"); dm.wait_for_timeout(3000)

    print(f"== [{engine.NAME}] 1. every move has its own look, and it plays")
    st = call("GET", f"/api/encounters/{eid}")
    sb = next(c for c in st["combatants"] if c["id"] == ST)["statblock"]
    read = dm.evaluate("""(sb) => {
      const out = {};
      const add = (list) => list.forEach((a) => { out[a.name] = a.look || ""; });
      add(L.attackLines(sb.attacks)); add(L.monsterSpells(sb.spells)); add(L.attackLines(sb.legendary)); add(L.attackLines(sb.phase2));
      add(L.attackLines(sb.drone_attacks || ""));
      return out; }""", dict(sb, drone_attacks=drone.get("attacks", "")))
    for name, look in LOOKS.items():
        check(read.get(name) == look, f"{name}: read with look {look!r} (got {read.get(name)!r})")
    dm.evaluate("window.__fx = []")
    for name, look in LOOKS.items():
        call("POST", f"/api/maps/{mid}/fx", {"by": ST, "name": name, "kind": "damage", "style": look, "targets": [{"id": TH, "how": "hit"}]})
    dm.wait_for_timeout(4000)
    played = {f["name"]: f["look"] for f in dm.evaluate("window.__fx")}
    missing = [n for n, look in LOOKS.items() if played.get(n) != look]
    check(not missing, f"all {len(LOOKS)} animations played on the DM's map" + (f" (missing {missing})" if missing else ""))

    def screen(cx, cy):
        dm.evaluate("window.scrollTo(0, 0)"); dm.wait_for_timeout(100)
        return dm.evaluate(f"""() => {{ const v = window.__view, m = v.map, r = v.canvas.getBoundingClientRect();
          return [r.left + v.view.tx + (m.offset_x + ({cx} + .5) * m.cell_px) * v.view.s, r.top + v.view.ty + (m.offset_y + ({cy} + .5) * m.cell_px) * v.view.s]; }}""")

    def select_steven():
        dm.keyboard.press("Escape"); dm.wait_for_timeout(300)
        for _ in range(5):
            dm.mouse.click(*screen(7, 6)); dm.wait_for_timeout(900)
            if "Steven Voss" in (dm.locator(".fight-head").first.inner_text() if dm.locator(".fight-head").count() else ""):
                return True
        return False

    def act_btn(name, legendary=False):
        sel = ".fight-act.is-legendary" if legendary else ".fight-act:not(.is-legendary)"
        return dm.locator(sel).filter(has=dm.locator("b", has_text=re.compile(r"^\s*" + re.escape(name) + r"\s*$"))).first

    def settle():
        dm.wait_for_timeout(3500)
        if dm.locator("#dice-dock.is-open").count():
            dm.click("#dice-close")

    def clicked(name, how, legendary=False, hx=6, hy=6):
        """Use the move from the map's side panel; returns the animations it drew."""
        place(hx, hy); turn(TH if legendary else ST); dm.wait_for_timeout(2000)
        if not select_steven():
            check(False, f"{name}: couldn't select Steven on the map"); return []
        btn = act_btn(name, legendary)
        for _ in range(5):
            if btn.count():
                break
            dm.wait_for_timeout(1000); select_steven(); btn = act_btn(name, legendary)
        if not btn.count():
            check(False, f"{name}: no button ({dm.locator('.fight-act b').all_inner_texts()})"); return []
        dm.evaluate("window.__fx = []")
        btn.click(); dm.wait_for_timeout(600)
        if how == "tap":
            for _ in range(5):
                dm.mouse.click(*screen(hx, hy)); dm.wait_for_timeout(1800)
                if dm.evaluate("window.__fx.length") or not dm.locator(".fight-aim").count():
                    break
        elif how == "chip":
            dm.locator(".cast-chip").filter(has_text="Test Hero").first.click(); dm.wait_for_timeout(300)
            dm.locator(".cast-go").first.click()
        settle()
        for _ in range(12):  # on a hit the to-hit dice land, then the damage dice, then it plays
            if dm.evaluate("window.__fx.length"):
                break
            dm.wait_for_timeout(1000)
            if dm.locator("#dice-dock.is-open").count():
                dm.click("#dice-close")
        return dm.evaluate("window.__fx")

    print("== 2. real clicks")
    fx = clicked("Fire Bolt", "chip")
    check(any(f["look"] == "flames" for f in fx), f"Fire Bolt clicked on the map plays flames ({fx[:2]})")

    turn(ST)
    call("POST", f"/api/encounters/{eid}/cast", {"caster_id": ST, "spell": {"name": "Deploy Drones", "effect": "buff", "summon": "Voss Drone", "summon_count": 2, "relay": True}, "targets": [], "force": True})
    turn(TH)
    r = call("POST", f"/api/encounters/{eid}/cast", {"caster_id": TH, "targets": [ST], "spell": {"name": "Spark Shot", "effect": "damage", "level": 0, "dice": "1", "damage_type": "lightning"}})
    check("records Spark Shot" in r["cast"]["summary"], "a drone records the Test Hero's Spark Shot")
    left0 = next(c for c in call("GET", f"/api/encounters/{eid}")["combatants"] if c["id"] == ST)["boss"]["left"]
    fx = clicked("Spark Shot (copied)", "chip", legendary=True)
    me = next(c for c in call("GET", f"/api/encounters/{eid}")["combatants"] if c["id"] == ST)
    check(any(f["look"] == "sparks" for f in fx), "the copied spell, cast as a legendary action from the map, plays sparks")
    check(me["boss"]["left"] == left0 - 1 and not me["statblock"].get("copied"), f"it used a legendary action ({left0} -> {me['boss']['left']}) and the copy")

    print("== Metal Bend")
    place(); turn(ST); dm.wait_for_timeout(2000); select_steven()
    act_btn("Metal Bend").click(); dm.wait_for_timeout(600)
    a0, z0 = screen(4, 2), screen(4, 9)
    dm.mouse.move(*a0); dm.mouse.down(); dm.mouse.move(*z0, steps=6); dm.mouse.up(); dm.wait_for_timeout(600)
    dm.locator(".fight-aim .btn-primary").click(); settle()
    wall = sorted(k for k, v in call("GET", f"/api/maps/{mid}")["map"]["terrain"].items() if v == "bulkhead")
    check(len(wall) >= 4 and len({k.split(",")[0] for k in wall}) == 1, f"a straight steel wall where it was dragged ({wall})")
    dm.screenshot(path=f"{SHOTS_DIR}/voss_wall_{engine.NAME}.png")

    print("== phase 2")
    call("POST", f"/api/combatants/{ST}/hp", {"op": "damage", "amount": 120})
    fx = clicked("Piston Slam", "tap")
    if hero_at() == (6, 6):  # a natural 1 misses even AC 1: once more (its cooldown is 0)
        fx = clicked("Piston Slam", "tap")
    check(any(f["look"] == "punch" for f in fx), f"Piston Slam plays its punch ({fx[:2]})")
    check(hero_at() != (6, 6), f"Piston Slam shoved the Test Hero ({hero_at()})")
    th = next(c for c in call("GET", f"/api/encounters/{eid}")["combatants"] if c["id"] == TH)
    check(any(x["name"] == "Shocked" for x in th["conditions"]), "and Shocked them")
    walls = [[int(v) for v in k.split(",")] for k, t in call("GET", f"/api/maps/{mid}")["map"]["terrain"].items() if t == "bulkhead"]
    if walls:  # fold the Metal Bend wall away so nothing stands between them
        call("POST", f"/api/maps/{mid}/terrain", {"value": None, "cells": walls})
    fx = clicked("Magnet Pull", "tap", hx=1, hy=6)
    check(any(f["look"] == "sparks" for f in fx), f"Magnet Pull plays sparks ({fx[:2]})")
    s = tokens()["Steven Voss"]
    hx, hy = hero_at()
    check(s["x"] - 1 <= hx <= s["x"] + s["size"] and s["y"] - 1 <= hy <= s["y"] + s["size"], f"Magnet Pull dragged the Test Hero all the way to him ({(hx, hy)}, Steven at {(s['x'], s['y'])})")
    log = " ".join(x["message"] for x in call("GET", f"/api/encounters/{eid}")["log"])
    check("Test Hero is pulled" in log, "the log says the Test Hero was pulled")
    dm.screenshot(path=f"{SHOTS_DIR}/voss_fx2_{engine.NAME}.png")
    b.close()

check(not problems, "no page errors" + ("" if not problems else ": " + "; ".join(problems[:3])))
print(f"e2e_voss_fx.py [{engine.NAME}]: {sum(1 for ok, _ in results if ok)} passed, {sum(1 for ok, _ in results if not ok)} failed")
