"""How smooth the player's map is on a tablet: an iPad-sized screen with a sharp (2x) display and the
processor slowed down (CPU_SLOW, default 4x, like a mid-range tablet). On the Abandoned prison and a
plain dungeon: how long one frame of the map takes to draw, frames per second while a token slides
and effects play, and how long a move takes from tap to the map showing it. Chrome only (it can slow
the processor down). PERF_THEMES=futureprison,dungeon picks the maps."""
import json, os, re, time, urllib.request, uuid
from common import DM_URL, LAN_URL  # noqa: E402
from playwright.sync_api import sync_playwright
import engine

DM = DM_URL; LAN = LAN_URL
CPU = float(os.environ.get("CPU_SLOW", "4"))
THEMES = os.environ.get("PERF_THEMES", "futureprison,dungeon").split(",")
CATCH_VIEW = """
(() => { let real; Object.defineProperty(window, 'MapView', { configurable: true, get() { return real; },
  set(v) { real = class extends v { constructor(...a) { super(...a); window.__view = this; } }; } }); })();
"""
results = []


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

with sync_playwright() as p:
    b = engine.launch(p)
    for theme in THEMES:
        for pl in call("GET", f"/api/campaigns/{camp}/players")["players"]:
            call("DELETE", f"/api/players/{pl['id']}")
        code = call("POST", f"/api/campaigns/{camp}/join-code", {"action": "new"})["join_code"]
        mid = call("POST", f"/api/campaigns/{camp}/dungeons", {"theme": theme})["map"]["id"]
        call("POST", f"/api/maps/{mid}/party-to-start")
        call("POST", f"/api/maps/{mid}/fog", {"all": "reveal"})  # the worst case: the whole map explored
        call("POST", f"/api/campaigns/{camp}/live-map", {"map_id": mid})
        ctx = b.new_context(viewport={"width": 820, "height": 1180}, device_scale_factor=2, is_mobile=True, has_touch=True)
        ctx.add_init_script(CATCH_VIEW)
        pg = ctx.new_page()
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(LAN + "/join"); pg.fill("input[name=code]", code); pg.fill("input[name=name]", "Tablet")
        pg.wait_for_selector("#char-field:not([hidden])"); pg.select_option("select[name=character_id]", value=str(chars["Moni Easter"]["id"]))
        pg.click("button[type=submit]"); pg.wait_for_url(re.compile("/play")); pg.wait_for_selector("#me h3", timeout=20000); pg.wait_for_timeout(2500)
        cdp = ctx.new_cdp_session(pg); cdp.send("Emulation.setCPUThrottlingRate", {"rate": CPU})
        pg.evaluate("window.__view.zoom(2.2)")  # zoomed in, like a player looking at their corner
        frame = pg.evaluate("() => { const v = window.__view; v.draw(); const t = performance.now(); for (let i = 0; i < 15; i++) v.draw(); return (performance.now() - t) / 15; }")
        # frames per second while things move: a ping and a few effects, for two seconds
        fps = pg.evaluate("""() => new Promise((done) => { const v = window.__view, m = v.map; let n = 0; const t0 = performance.now();
          for (let i = 0; i < 6; i++) v.addFx({ type: 'ping', x: m.cols / 2 + i, y: m.rows / 2, by: '', color: '#f3d58a', ms: 2500 });
          const tick = () => { n++; if (performance.now() - t0 < 2000) requestAnimationFrame(tick); else done(n / ((performance.now() - t0) / 1000)); };
          requestAnimationFrame(tick); })""")
        # a move: tap-to-shown (the request, the reload of the game state and the redraw)
        me = next(t for t in pg.evaluate("window.__view.tokens") if t.get("own"))
        tgt = [me["x"], me["y"] + 1]
        terr = pg.evaluate("window.__view.map.terrain")
        busy = {(int(t["x"]), int(t["y"])) for t in pg.evaluate("window.__view.tokens")}
        for dx, dy in ((1, 0), (0, 1), (-1, 0), (0, -1), (1, 1), (-1, -1), (1, -1), (-1, 1)):
            k = f"{int(me['x']) + dx},{int(me['y']) + dy}"
            if terr.get(k) in ("metal", "stone", "grass", "sand", "wood", "grate") and (int(me["x"]) + dx, int(me["y"]) + dy) not in busy:
                tgt = [me["x"] + dx, me["y"] + dy]
                break
        # (the same call a finger lifting off the token makes at the end of a drag)
        lag = pg.evaluate(f"""async () => {{ const v = window.__view, t0 = performance.now();
          const mine = v.tokens.find((x) => x.own);
          await v.opts.onMove(mine, {tgt[0]}, {tgt[1]});
          const t1 = performance.now();
          for (let i = 0; i < 300; i++) {{ const t = window.__view.tokens.find((x) => x.own); if (t && t.x === {tgt[0]} && t.y === {tgt[1]}) return [t1 - t0, performance.now() - t0]; await new Promise((r) => setTimeout(r, 10)); }}
          return [t1 - t0, -1]; }}""")
        if lag[1] < 0:
            print("     the move didn't land:", pg.locator("#toasts").inner_text()[:200])
        print(f"== {theme} (tablet, CPU {CPU:g}x slower): one frame {frame:.1f} ms, {fps:.0f} fps while effects play, move: server {lag[0]:.0f} ms, on screen {lag[1]:.0f} ms")
        check(frame < 16, f"{theme}: a frame draws in {frame:.1f} ms (under 16 ms keeps 60 fps)")
        check(fps >= 45, f"{theme}: {fps:.0f} frames a second while effects play")
        check(lag[1] < 700, f"{theme}: a move shows on the tablet in {lag[1]:.0f} ms")
        check(not errs, f"{theme}: no errors on the page {errs[:1]}")
        ctx.close()
    b.close()
ok = sum(1 for r in results if r[0])
print(f"e2e_tablet_speed.py [{engine.NAME}]: {ok} passed, {len(results) - ok} failed")
raise SystemExit(0 if ok == len(results) else 1)
