"""Does every move a player makes with their finger actually register? A tablet (touch, sharp display,
slowed processor) drags its hero one to three squares at a time, over and over, while the DM's map is
open and another player moves too. After each drag: did the token land where the finger let go, and
if not, what did the screen say? Runs on a plain dungeon and the Abandoned prison (MOVE_THEMES)."""
import json, os, random, re, time, urllib.request, uuid
from common import DM_URL, LAN_URL  # noqa: E402
from playwright.sync_api import sync_playwright
import engine

DM = DM_URL; LAN = LAN_URL
CPU = float(os.environ.get("CPU_SLOW", "4"))
THEMES = os.environ.get("MOVE_THEMES", "dungeon,futureprison").split(",")
MOVES = int(os.environ.get("MOVES", "25"))
CATCH_VIEW = """
(() => { let real; Object.defineProperty(window, 'MapView', { configurable: true, get() { return real; },
  set(v) { real = class extends v { constructor(...a) { super(...a); window.__view = this; } }; } }); })();
"""
FLOOR = ("metal", "stone", "grass", "sand", "wood", "grate", "floor", "dirt")
results = []


def call(m, path, body=None):
    data = json.dumps(dict(body or {}, op_id=uuid.uuid4().hex)).encode() if m != "GET" else None
    return json.load(urllib.request.urlopen(urllib.request.Request(DM + path, data=data, method=m, headers={"Content-Type": "application/json"})))


def check(c, msg):
    results.append((bool(c), msg)); print(("  PASS " if c else "  FAIL ") + msg, flush=True)


def join(b, code, char_id, name, touch):
    ctx = b.new_context(viewport={"width": 820, "height": 1180} if touch else {"width": 1280, "height": 900},
                        device_scale_factor=2 if touch else 1, is_mobile=touch, has_touch=touch)
    ctx.add_init_script(CATCH_VIEW)
    pg = ctx.new_page()
    pg.goto(LAN + "/join"); pg.fill("input[name=code]", code); pg.fill("input[name=name]", name)
    pg.wait_for_selector("#char-field:not([hidden])"); pg.select_option("select[name=character_id]", value=str(char_id))
    pg.click("button[type=submit]"); pg.wait_for_url(re.compile("/play")); pg.wait_for_selector("#me h3", timeout=20000)
    pg.wait_for_function("window.__view && window.__view.tokens.some((t) => t.own)", timeout=20000)
    return ctx, pg


SCREEN_OF = """([x, y]) => { const v = window.__view, m = v.map, r = v.canvas.getBoundingClientRect();
  const wx = m.offset_x + (x + 0.5) * m.cell_px, wy = m.offset_y + (y + 0.5) * m.cell_px;
  return [r.left + wx * v.view.s + v.view.tx, r.top + wy * v.view.s + v.view.ty]; }"""


def touch_drag(cdp, a, b, steps=8):
    pt = lambda p: [{"x": p[0], "y": p[1], "id": 1, "radiusX": 6, "radiusY": 6, "force": 1}]
    cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": pt(a)})
    for i in range(1, steps + 1):
        cdp.send("Input.dispatchTouchEvent", {"type": "touchMove", "touchPoints": pt((a[0] + (b[0] - a[0]) * i / steps, a[1] + (b[1] - a[1]) * i / steps))})
        time.sleep(0.016)
    cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})


camp = 1
for e in call("GET", f"/api/campaigns/{camp}/encounters")["encounters"]:
    if e["status"] == "active":
        call("POST", f"/api/encounters/{e['id']}/end")
chars = {c["name"]: c for c in call("GET", f"/api/campaigns/{camp}/characters")["characters"]}
rnd = random.Random(7)

with sync_playwright() as p:
    b = engine.launch(p)
    for theme in THEMES:
        for pl in call("GET", f"/api/campaigns/{camp}/players")["players"]:
            call("DELETE", f"/api/players/{pl['id']}")
        code = call("POST", f"/api/campaigns/{camp}/join-code", {"action": "new"})["join_code"]
        mid = call("POST", f"/api/campaigns/{camp}/dungeons", {"theme": theme})["map"]["id"]
        call("POST", f"/api/maps/{mid}/party-to-start")
        call("POST", f"/api/campaigns/{camp}/live-map", {"map_id": mid})
        # no fights for this one: hide the enemies far away, so only movement itself is tested
        mp = call("GET", f"/api/maps/{mid}")
        for t in mp["tokens"]:
            if t.get("kind") == "enemy" or (t.get("combatant_id") and not t.get("character_id")):
                call("DELETE", f"/api/tokens/{t['id']}")
        dmctx = b.new_context(viewport={"width": 1400, "height": 900}); dm = dmctx.new_page(); dm.goto(DM + f"/maps/{mid}")
        tctx, pg = join(b, code, chars["Moni Easter"]["id"], "Tablet", True)
        octx, other = join(b, code, chars["Lux Fedelis"]["id"], "Laptop", False)
        cdp = tctx.new_cdp_session(pg)
        if engine.NAME == "chromium":
            cdp.send("Emulation.setCPUThrottlingRate", {"rate": CPU})
        pg.evaluate("window.__view.zoom(2)")
        missed, refused = [], []
        for i in range(MOVES):
            pg.wait_for_timeout(rnd.choice([150, 400, 900]))  # quick moves and slow ones
            me = next(t for t in pg.evaluate("window.__view.tokens") if t.get("own"))
            terr = pg.evaluate("window.__view.map.terrain"); rev = pg.evaluate("window.__view.map.revealed || ''")
            cols = pg.evaluate("window.__view.map.cols")
            busy = {(int(t["x"]), int(t["y"])) for t in pg.evaluate("window.__view.tokens")}
            opts = [(int(me["x"]) + dx, int(me["y"]) + dy) for dx in range(-3, 4) for dy in range(-3, 4) if (dx or dy)]
            opts = [c for c in opts if terr.get(f"{c[0]},{c[1]}") in FLOOR and c not in busy and (not rev or rev[c[1] * cols + c[0]] == "1")]
            if not opts:
                continue
            tgt = rnd.choice(opts)
            # keep both on screen: centre the view on the hero
            pg.evaluate("""([x, y]) => { const v = window.__view, m = v.map; const wx = m.offset_x + (x + .5) * m.cell_px, wy = m.offset_y + (y + .5) * m.cell_px;
              v.view.tx = v.w / 2 - wx * v.view.s; v.view.ty = v.h / 2 - wy * v.view.s; v.draw(); }""", [me["x"], me["y"]])
            pg.evaluate("document.querySelector('#toasts') && (document.querySelector('#toasts').innerHTML = '')")
            a = pg.evaluate(SCREEN_OF, [me["x"], me["y"]]); z = pg.evaluate(SCREEN_OF, list(tgt))
            # the other player moves at about the same time now and then
            if rnd.random() < 0.4:
                ot = next(t for t in other.evaluate("window.__view.tokens") if t.get("own"))
                other.evaluate("([t, x, y]) => window.__view.opts.onMove(window.__view.tokens.find((k) => k.id === t), x, y)",
                               [ot["id"], ot["x"], ot["y"] + (1 if rnd.random() < .5 else -1)])
            touch_drag(cdp, a, z)
            landed = False
            for _ in range(40):
                pg.wait_for_timeout(100)
                srv = next(t for t in call("GET", f"/api/maps/{mid}")["tokens"] if t["id"] == me["id"])
                if (srv["x"], srv["y"]) == tgt:
                    landed = True; break
            pg.wait_for_timeout(600)
            shown = next(t for t in pg.evaluate("window.__view.tokens") if t["id"] == me["id"])
            toasts = pg.locator("#toasts").inner_text().strip().replace("\n", " ")
            if not landed:
                refused.append((i, toasts))
                print(f"   move {i}: {me['x']},{me['y']} -> {tgt} refused: {toasts!r}", flush=True)
                x0, y0 = int(min(me["x"], tgt[0])) - 1, int(min(me["y"], tgt[1])) - 1
                for yy in range(y0, int(max(me["y"], tgt[1])) + 2):  # S start, T target, # solid, . open
                    print("      " + "".join("S" if (xx, yy) == (me["x"], me["y"]) else "T" if (xx, yy) == tgt else
                                             "." if terr.get(f"{xx},{yy}") in FLOOR else "#" for xx in range(x0, int(max(me["x"], tgt[0])) + 2)), flush=True)
            if (shown["x"], shown["y"]) != (srv["x"], srv["y"]) or (not landed and not toasts):
                missed.append((i, (me["x"], me["y"]), tgt, (srv["x"], srv["y"]), (shown["x"], shown["y"]), toasts))
                print(f"   move {i}: {me['x']},{me['y']} -> {tgt}: server {srv['x']},{srv['y']}, screen {shown['x']},{shown['y']}  toast: {toasts!r}", flush=True)
        print(f"== {theme}: {MOVES - len(refused)} of {MOVES} drags moved the hero; {len(refused)} refused with a reason")
        check(not missed, f"{theme}: the screen always shows the hero where the server has them ({len(missed)} out of step)")
        check(len(refused) <= MOVES // 10, f"{theme}: open-floor drags nearby are rarely refused ({len(refused)})")
        for c in (tctx, octx, dmctx):
            c.close()
    b.close()
ok = sum(1 for r in results if r[0])
print(f"e2e_move_reads.py [{engine.NAME}]: {ok} passed, {len(results) - ok} failed")
raise SystemExit(0 if ok == len(results) else 1)
