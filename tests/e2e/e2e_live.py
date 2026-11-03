"""The table feels alive: tokens slide instead of jumping, a slow old reply can't undo something
newer, your own move stays put while it's saving, nothing is missed while you hold the map, and a
screen catches up after a dropped connection or a locked phone. Prints how long moves take."""
import json, os, time, urllib.request, uuid
from common import DM_URL, LAN_URL  # noqa: E402
from playwright.sync_api import sync_playwright
import engine

DM = DM_URL; LAN = LAN_URL
results, problems = [], []
TOOLS = """
(() => { let real; Object.defineProperty(window, 'MapView', { configurable: true, get() { return real; },
  set(v) { real = class extends v { constructor(...a) { super(...a); window.__view = this; } }; } });
  // slow down chosen requests: `before` waits before asking, `after` holds the reply back
  const f = window.fetch; window.__slow = [];
  window.fetch = async (u, i) => {
    const s = window.__slow.find((x) => String(u).includes(x.url) && (!x.method || (i && i.method) === x.method) && x.n > 0);
    if (s) s.n--;
    if (s && s.before) await new Promise((z) => setTimeout(z, s.before));
    const r = await f(u, i);
    if (s && s.after) await new Promise((z) => setTimeout(z, s.after));
    return r;
  };
  // go deaf to live updates, to act out a dropped connection
  const ES = window.EventSource;
  window.EventSource = class extends ES { constructor(...a) { super(...a); window.__es = this; }
    addEventListener(k, fn) { super.addEventListener(k, (e) => { if (!window.__deaf) fn(e); }); } };
  // what's drawn, frame by frame
  window.__record = (id) => { const out = []; window.__track = out; const t0 = performance.now();
    (function tick() { if (window.__track !== out) return; const v = window.__view, t = v.tokens.find((x) => x.id === id);
      if (t) { const [x, y] = v.shownAt(t); out.push([performance.now() - t0, x, y, t.x]); } requestAnimationFrame(tick); })(); };
})();
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
mid = call("POST", f"/api/campaigns/{camp}/maps", {"name": "Live test", "cols": 40, "rows": 12})["map"]["id"]
call("PATCH", f"/api/maps/{mid}", {"changes": {"fog_enabled": {"to": False}, "players_can_move": {"to": True}}})
lux = call("POST", f"/api/maps/{mid}/tokens", {"character_id": chars["Lux Fedelis"]["id"], "x": 2, "y": 2})
lux = next(t["id"] for t in call("GET", f"/api/maps/{mid}")["tokens"] if t["display"] == "Lux Fedelis")
call("POST", f"/api/maps/{mid}/tokens", {"character_id": chars["Moni Easter"]["id"], "x": 2, "y": 8})
moni = next(t["id"] for t in call("GET", f"/api/maps/{mid}")["tokens"] if t["display"] == "Moni Easter")
call("POST", f"/api/campaigns/{camp}/live-map", {"map_id": mid})
code = call("POST", f"/api/campaigns/{camp}/join-code", {"action": "new"})["join_code"]


def move(token, x, y):
    return call("POST", f"/api/tokens/{token}/move", {"x": x, "y": y, "free": True})


with sync_playwright() as p:
    b = engine.launch(p)
    ctx = b.new_context(viewport={"width": 1100, "height": 760}); ctx.add_init_script(TOOLS)
    pg = ctx.new_page()
    pg.on("pageerror", lambda e: problems.append(f"player JS error: {e}"))
    pg.goto(LAN + "/join"); pg.fill("input[name=code]", code); pg.fill("input[name=name]", "Moni's player")
    pg.wait_for_selector("#char-field:not([hidden])"); pg.select_option("select[name=character_id]", value=str(chars["Moni Easter"]["id"]))
    pg.click("button[type=submit]"); pg.wait_for_timeout(2000)
    pg.wait_for_function("window.__view && window.__view.tokens.length === 2", timeout=15000)

    def logical(token):
        return pg.evaluate("(id) => { const t = window.__view.tokens.find((x) => x.id === id); return [t.x, t.y]; }", token)

    def settled(token, x, y, ms=3000):
        for _ in range(ms // 50):
            if logical(token) == [x, y] and pg.evaluate("window.__view.glides.size") == 0:
                return True
            pg.wait_for_timeout(50)
        return False

    def cell(cx, cy):
        pg.evaluate("window.scrollTo(0, 0)"); pg.wait_for_timeout(100)
        return pg.evaluate("""([cx, cy]) => { const v = window.__view, m = v.map, r = v.canvas.getBoundingClientRect();
          return [r.left + v.view.tx + (m.offset_x + (cx + .5) * m.cell_px) * v.view.s, r.top + v.view.ty + (m.offset_y + (cy + .5) * m.cell_px) * v.view.s]; }""", [cx, cy])

    print(f"== [{engine.NAME}] someone else's token slides to its new square")
    lags = []
    for x in (6, 10, 14):
        pg.evaluate("(id) => window.__record(id)", lux)
        t0 = time.time(); move(lux, x, 2)
        settled(lux, x, 2); lags.append(time.time() - t0)
        frames = pg.evaluate("window.__track"); xs = [f[1] for f in frames]
        between = [v for v in xs if x - 4 < v < x]
        check(len(between) >= 3, f"it passes through the squares in between, not a jump ({len(between)} frames on the way to x={x})")
        check(all(b2 >= a - 0.001 for a, b2 in zip(xs, xs[1:])), "it only goes forward, no jitter")
        check(abs(xs[-1] - x) < 0.001, "and lands exactly on the square")
    print(f"   move to finished slide on another screen: {sorted(lags)[1] * 1000:.0f} ms")

    print("== a very long trip just arrives")
    pg.evaluate("(id) => window.__record(id)", lux)
    move(lux, 39, 2); settled(lux, 39, 2)
    check(sum(1 for f in pg.evaluate("window.__track") if 15 < f[1] < 39) == 0, "no slide across the whole map")
    move(lux, 14, 2); settled(lux, 14, 2)

    print("== with reduced motion on, tokens don't slide")
    pg.emulate_media(reduced_motion="reduce")
    pg.evaluate("(id) => window.__record(id)", lux)
    move(lux, 18, 2); settled(lux, 18, 2)
    check(sum(1 for f in pg.evaluate("window.__track") if 14 < f[1] < 18) == 0, "reduced motion: straight there")
    pg.emulate_media(reduced_motion="no-preference")

    print("== a slow old reply can't undo something newer")
    pg.evaluate("window.__slow.push({ url: '/api/play/state', after: 1500, n: 1 })")
    pg.evaluate("(id) => window.__record(id)", lux)
    move(lux, 21, 2); pg.wait_for_timeout(350)
    move(lux, 25, 2); settled(lux, 25, 2); pg.wait_for_timeout(2200)
    seq = [f[3] for f in pg.evaluate("window.__track")]
    first25 = seq.index(25) if 25 in seq else len(seq)
    check(25 in seq and all(v == 25 for v in seq[first25:]), f"once at the newest spot it stays there ({sorted(set(seq[first25:]))})")

    print("== your own move stays where you dropped it while it saves")
    a, z = cell(2, 8), cell(5, 8)
    pg.evaluate("window.__slow.push({ url: '/move', method: 'POST', before: 900, n: 1 })")
    pg.mouse.move(*a); pg.mouse.down(); pg.mouse.move(*z, steps=8); pg.mouse.up()
    pg.evaluate("(id) => window.__record(id)", moni)
    pg.wait_for_timeout(100); move(lux, 26, 2)  # someone else's move: a fresh copy arrives before ours has landed
    pg.wait_for_timeout(2200)
    seq = pg.evaluate("window.__track")
    check(seq and all(abs(f[1] - 5) < 0.001 for f in seq), f"it never goes back ({sorted(set(round(f[1], 1) for f in seq))})")
    check(call("GET", f"/api/maps/{mid}") and next(t for t in call("GET", f"/api/maps/{mid}")["tokens"] if t["id"] == moni)["x"] == 5, "and the move saved")

    print("== a refused move slides back")
    call("PATCH", f"/api/maps/{mid}", {"changes": {"players_can_move": {"to": False}}}); pg.wait_for_timeout(1000)
    a, z = cell(5, 8), cell(8, 8)
    pg.mouse.move(*a); pg.mouse.down(); pg.mouse.move(*z, steps=8); pg.mouse.up()
    check(settled(moni, 5, 8), f"locked: the token goes back ({logical(moni)})")
    call("PATCH", f"/api/maps/{mid}", {"changes": {"players_can_move": {"to": True}}}); pg.wait_for_timeout(1000)

    print("== nothing is missed while you hold the map")
    a, z = cell(30, 10), cell(26, 8)
    pg.mouse.move(*a); pg.mouse.down(); pg.mouse.move(*z, steps=6)
    check(pg.evaluate("!!window.__view.drag"), "(holding the map)")
    move(lux, 28, 2); pg.wait_for_timeout(1200)
    pg.mouse.up(); t0 = time.time()
    check(settled(lux, 28, 2, 1500), f"a move made meanwhile shows when you let go ({time.time() - t0:.2f} s, now {logical(lux)})")

    print("== catching up after the connection drops or the phone was locked")
    pg.evaluate("window.__deaf = true")
    move(lux, 30, 2); pg.wait_for_timeout(100)
    pg.evaluate("window.__es.onopen()")
    check(settled(lux, 30, 2, 1500), f"reconnecting catches up at once ({logical(lux)})")
    move(lux, 32, 2); pg.wait_for_timeout(100)
    pg.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
    check(settled(lux, 32, 2, 1500), f"coming back to the page catches up at once ({logical(lux)})")
    pg.evaluate("window.__deaf = false")

    print("== a live update can't swallow a tap")
    box = pg.locator("[data-ptool=measure]").bounding_box()
    pg.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2); pg.mouse.down()
    move(lux, 34, 2); pg.wait_for_timeout(500)
    check(logical(lux) == [32, 2], f"nothing is redrawn while a button is held down ({logical(lux)})")
    pg.mouse.up()
    check(settled(lux, 34, 2, 1500), f"and it comes through when the finger lifts ({logical(lux)})")
    check(pg.locator("[data-ptool=measure]").get_attribute("aria-pressed") == "true", "and the tap counted")
    pg.locator("[data-ptool=select]").click()

    print("== how long a move takes the server")
    took = []
    for i in range(9):
        t0 = time.time(); move(lux, 20 + i, 4); took.append(time.time() - t0)
    print(f"   a move, sent and saved: middle {sorted(took)[4] * 1000:.0f} ms, slowest {max(took) * 1000:.0f} ms")
    check(sorted(took)[4] < 0.25, f"a move saves quickly ({sorted(took)[4] * 1000:.0f} ms)")
    b.close()
fails = [x for ok, x in results if not ok]
print(f"\n{len(results) - len(fails)} passed, {len(fails)} failed"); [print("FAILED:", f) for f in fails]
print("PROBLEMS:", problems)
