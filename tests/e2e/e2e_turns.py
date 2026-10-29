"""E2E on a phone: turn-only movement within speed, Dash, two actions, rolls only on your
turn, ping cooldown, no HP buttons, move cards; Yamato's clone summons again."""
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


def check(c, msg):
    results.append((bool(c), msg)); print(("  PASS " if c else "  FAIL ") + msg, flush=True)


CATCH_VIEW = """
(() => { let real; Object.defineProperty(window, 'MapView', { configurable: true, get() { return real; },
  set(v) { real = class extends v { constructor(...a) { super(...a); window.__view = this; } }; } }); })();
"""

# the fight is over in this copy; a fresh one with a map
for e in call("GET", "/api/campaigns/1/encounters")["encounters"]:
    if e["status"] == "active":
        call("POST", f"/api/encounters/{e['id']}/end")
eid = call("POST", "/api/campaigns/1/encounters", {"name": "Turn rules"})["encounter"]["id"]
call("POST", f"/api/encounters/{eid}/combatants", {"characters": [1, 2, 3, 4], "quick": {"name": "Goblin", "max_hp": 30, "ac": 10, "count": 1}})
mid = call("POST", f"/api/encounters/{eid}/map")["map_id"]
call("PATCH", f"/api/maps/{mid}", {"changes": {"cols": {"to": 24}, "rows": {"to": 16}}})
toks = {t["display"]: t for t in call("GET", f"/api/maps/{mid}")["tokens"]}
for n, (x, y) in {"Moni Easter": (2, 2), "Lux Fedelis": (2, 6), "Yamato": (4, 8), "Gnocchi": (6, 8), "Goblin": (14, 2)}.items():
    call("POST", f"/api/tokens/{toks[n]['id']}/move", {"x": x, "y": y})
call("POST", "/api/campaigns/1/live-map", {"map_id": mid})
call("POST", f"/api/encounters/{eid}/start")
by = {c["name"]: c for c in call("GET", f"/api/encounters/{eid}")["combatants"]}
call("POST", f"/api/encounters/{eid}/set-turn", {"combatant_id": by["Goblin"]["id"]})
moni = call("GET", "/api/characters/2")["character"]
item = next((i for i, s in enumerate(moni["spells"]) if s.get("aura")), None)
if item is not None:
    call("POST", "/api/characters/2/aura", {"index": item, "on": False})
code = call("POST", "/api/campaigns/1/join-code", {"action": "new"})["join_code"]

with sync_playwright() as p:
    b = engine.launch(p)
    ctx = b.new_context(viewport={"width": 390, "height": 844}, **engine.mobile(), has_touch=True)
    ctx.add_init_script(CATCH_VIEW)
    pp = ctx.new_page()
    pp.on("pageerror", lambda e: problems.append(f"JS error: {e}"))
    pp.on("response", lambda r: r.status >= 500 and problems.append(f"HTTP {r.status} {r.url}"))
    pp.goto(LAN + "/join"); pp.fill("input[name=code]", code); pp.fill("input[name=name]", "Turn test")
    pp.wait_for_selector("#char-field:not([hidden])"); pp.select_option("select[name=character_id]", value="2")
    pp.click("button[type=submit]"); pp.wait_for_url(re.compile("/play")); pp.wait_for_timeout(2500)

    def screen(cx, cy):
        return pp.evaluate(f"""() => {{ const v = window.__view, m = v.map, r = v.canvas.getBoundingClientRect();
          return [r.left + v.view.tx + (m.offset_x + ({cx} + .5) * m.cell_px) * v.view.s, r.top + v.view.ty + (m.offset_y + ({cy} + .5) * m.cell_px) * v.view.s]; }}""")

    def drag(fx, fy, tx, ty):
        pp.evaluate("window.scrollTo(0, 0)"); pp.wait_for_timeout(200)
        a, z = screen(fx, fy), screen(tx, ty)
        pp.mouse.move(*a); pp.mouse.down(); pp.mouse.move((a[0] + z[0]) / 2, (a[1] + z[1]) / 2, steps=5); pp.mouse.move(*z, steps=5); pp.mouse.up()
        pp.wait_for_timeout(1500)

    def where():
        t = next(t for t in call("GET", f"/api/maps/{mid}")["tokens"] if t["display"] == "Moni Easter")
        return (t["x"], t["y"])

    def toasts():
        return " | ".join(pp.locator(".toast").all_inner_texts())

    print("== Not her turn")
    pp.locator("#stage").scroll_into_view_if_needed()
    check("Wait for your turn to move" in pp.locator("#hint").inner_text(), f"hint: {pp.locator('#hint').inner_text()!r}")
    drag(2, 2, 4, 2)
    check(where() == (2, 2), "dragging her token does nothing off-turn")
    check(pp.locator(".hp-ctl, .btn-dmg").count() == 0, "no Damage/Heal/Temp HP buttons on her phone")
    pp.locator(".stats .stat").first.click(); pp.wait_for_timeout(1200)
    check("only you see this roll" in toasts(), f"an ability roll off-turn is just for her ({toasts()[:90]!r})")
    cards = pp.locator(".move-card")
    check(cards.count() >= 3, f"her moves show as cards ({cards.count()})")
    print("    ", [c.replace("\n", " / ") for c in cards.all_inner_texts()][:4])
    pp.screenshot(path=SHOTS + r"\turns_offturn.png", full_page=True)

    print("== Her turn")
    call("POST", f"/api/encounters/{eid}/set-turn", {"combatant_id": by["Moni Easter"]["id"]})
    pp.wait_for_timeout(3500)
    hint = pp.locator("#hint").inner_text()
    pt = screen(2, 2)
    print("    debug", pt, pp.evaluate(f"() => {{ const v = window.__view, r = v.canvas.getBoundingClientRect(); const t = v.tokenAt({pt[0]} - r.left, {pt[1]} - r.top); return [t && t.display, t && t.movable, v.view, r.top, r.height, innerHeight, v.tool] }}"))
    check("30 of 30 ft left" in hint, f"hint: {hint!r}")
    drag(2, 2, 5, 2)
    check(where() == (5, 2), f"she moves 15 ft ({where()})")
    pp.wait_for_timeout(500)
    check("15 of 30 ft left" in pp.locator("#hint").inner_text(), f"hint now: {pp.locator('#hint').inner_text()!r}")
    drag(5, 2, 9, 2)
    check(where() == (8, 2), f"dragging 20 ft more stops at the edge of her 15 ft ({where()})")
    a, z = screen(8, 2), screen(6, 2)
    pp.mouse.move(*a); pp.mouse.down(); pp.mouse.move(*z, steps=6); pp.mouse.up(); pp.wait_for_timeout(1500)
    check(where() == (6, 2), f"she readjusts: slides back 10 ft even with no movement left ({where()})")
    a, z = screen(6, 2), screen(8, 2)
    pp.mouse.move(*a); pp.mouse.down(); pp.mouse.move(*z, steps=6); pp.mouse.up(); pp.wait_for_timeout(1500)
    check("0 of 30 ft left (you can still readjust)" in pp.locator("#hint").inner_text(), f"hint: {pp.locator('#hint').inner_text()!r}")
    pp.get_by_role("button", name=re.compile("^ ?Dash$")).click(); pp.wait_for_timeout(2000)
    check("30 of 30 ft left" in pp.locator("#hint").inner_text(), f"Dash: the 30 ft she'd moved is spent, Dash gives 30 more from here: {pp.locator('#hint').inner_text()!r}")
    check("Actions left this turn: 1 of 2" in pp.locator("body").inner_text(), "Dash used one of her two actions")
    drag(8, 2, 12, 2)
    check(where() == (12, 2), "after Dash the 20 ft move works")

    print("== Using a move on an enemy, like the DM")
    gob0 = next(c for c in call("GET", f"/api/encounters/{eid}")["combatants"] if c["name"] == "Goblin")["hp"]
    punch = pp.locator(".move-card").filter(has_text="Punch").first
    punch.get_by_role("button", name=re.compile("Use")).click(); pp.wait_for_timeout(600)
    box = pp.locator("#use-box")
    check(box.count() == 1 and "Goblin" in box.inner_text() and "Moni" not in box.inner_text().split("Punch", 1)[1], f"the picker lists enemies only ({box.inner_text()[:80]!r})")
    pp.evaluate("window.scrollTo(0, 0)"); pp.wait_for_timeout(200)
    gob = next(t for t in call("GET", f"/api/maps/{mid}")["tokens"] if t["display"] == "Goblin")
    call("POST", f"/api/tokens/{gob['id']}/move", {"x": 13, "y": 2, "free": True}); pp.wait_for_timeout(2500)  # next to her: Punch reaches 5 ft
    pp.mouse.click(*screen(13, 2)); pp.wait_for_timeout(3500)
    gob1 = next(c for c in call("GET", f"/api/encounters/{eid}")["combatants"] if c["name"] == "Goblin")["hp"]
    res = pp.locator("#use-box").inner_text() if pp.locator("#use-box").count() else ""
    print("    result:", res.replace(chr(10), " / "))
    check("Goblin" in res and (("missed" in res) == (gob1 == gob0)), f"tapping the goblin's token resolves it (HP {gob0} -> {gob1})")
    check(not re.search(r"AC", res) and not re.search(r"vs AC", pp.locator("body").inner_text()), "no Armor Class shown to her")
    pp.screenshot(path=SHOTS + "/turns_use.png", full_page=False)
    pp.get_by_role("button", name="Done").click(); pp.wait_for_timeout(300)
    lux = next(t for t in call("GET", f"/api/maps/{mid}")["tokens"] if t["display"] == "Lux Fedelis")
    st = pp.evaluate(f"async () => {{ const r = await fetch('/api/play/me/use', {{method: 'POST', headers: {{'Content-Type': 'application/json'}}, body: JSON.stringify({{what: 'attack', index: 2, targets: [{lux['combatant_id']}]}})}}); return [r.status, (await r.json()).error] }}")
    check(st[0] == 403, f"she can't aim it at Lux ({st})")

    print("== Two actions")
    body = pp.locator("body").inner_text()
    check("No actions left this turn" in body, "Dash + the punch used both her actions")
    punch = pp.locator(".move-card").filter(has_text="Punch").first
    check(punch.get_by_role("button", name=re.compile("Use")).is_disabled(), "Use is greyed out with no actions left")

    print("== Pings")
    pp.evaluate("window.scrollTo(0, 0)")
    pp.locator("[data-ptool=ping]").click()
    pp.mouse.click(*screen(12, 10)); pp.wait_for_timeout(600)
    pp.mouse.click(*screen(13, 10)); pp.wait_for_timeout(600)
    check("before pinging again" in toasts(), "a second ping right away waits for the cooldown")
    pings = call("GET", f"/api/maps/{mid}")["pings"]
    check(len([x for x in pings if x["by"] == "Turn test"]) == 1, f"only one ping went out ({len(pings)})")
    pp.screenshot(path=SHOTS + r"\turns_myturn.png", full_page=True)
    ctx.close()

    print("== Yamato's clone")
    yam = call("GET", "/api/characters/3")["character"]
    pf = next(i for i, s in enumerate(yam["spells"]) if (s.get("summon") or "").lower() == "yamato clone")
    call("POST", f"/api/encounters/{eid}/set-turn", {"combatant_id": by["Yamato"]["id"]})
    r = call("POST", f"/api/encounters/{eid}/cast", {"caster_id": by["Yamato"]["id"], "spell": pf, "targets": []})
    names = [c["name"] for c in r["combatants"]]
    check(any("yamato clone" in n.lower() for n in names), f"the clone joins the fight ({names})")
    order = [c["name"] for c in sorted(r["combatants"], key=lambda c: c["sort_order"])]
    i = order.index("Yamato")
    check("clone" in order[i + 1].lower(), "and acts right after Yamato")
    b.close()
fails = [m for ok, m in results if not ok]
print(f"\n{len(results) - len(fails)} passed, {len(fails)} failed"); [print("FAILED:", f) for f in fails]
print("PROBLEMS:", problems)
