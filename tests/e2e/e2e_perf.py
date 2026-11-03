"""How fast it feels: page loads, how much each page downloads, how many requests a page makes
while nobody does anything, how long the map takes to draw, and how long a change on the DM's
screen takes to show up on a player's phone. Prints numbers (and checks a few limits).
E2E_SLOW=1 adds a 150 ms delay to every request, like playing over the online link."""
import json, os, re, time, urllib.request, uuid
from common import DM_URL, LAN_URL  # noqa: E402
from playwright.sync_api import sync_playwright
import engine

DM = DM_URL; LAN = LAN_URL
SLOW = int(os.environ.get("E2E_SLOW", "0")) and 150
results, problems = [], []


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
mid = call("POST", f"/api/campaigns/{camp}/dungeons", {"theme": "prison"})["map"]["id"]
call("POST", f"/api/maps/{mid}/party-to-start")
d = call("GET", f"/api/maps/{mid}")["map"]["dungeon"]
call("POST", f"/api/maps/{mid}/monsters", {"book": "Goblin", "count": 3, "x": d["exit"][0] - 3, "y": d["exit"][1]})
call("POST", f"/api/campaigns/{camp}/live-map", {"map_id": mid})
code = call("POST", f"/api/campaigns/{camp}/join-code", {"action": "new"})["join_code"]


def meter(pg, who):
    st = {"n": 0, "bytes": 0, "urls": []}

    def on(resp):
        try:
            size = int(resp.headers.get("content-length") or 0) or len(resp.body())
        except Exception:
            size = 0
        st["n"] += 1; st["bytes"] += size; st["urls"].append(resp.url.split("?")[0].split(":5077")[-1])
    pg.on("response", on)
    pg.on("pageerror", lambda e: problems.append(f"{who} JS error: {e}"))
    return st


def slow(ctx, pg):
    """Like the online link: 150 ms each way and a phone-ish 4 Mbit/s (Chrome's own throttling,
    which keeps the browser's cache working, unlike delaying requests by hand)."""
    if SLOW and engine.NAME == "chromium":
        cdp = ctx.new_cdp_session(pg)
        cdp.send("Network.enable")
        cdp.send("Network.emulateNetworkConditions", {"offline": False, "latency": SLOW, "downloadThroughput": 4e6 / 8, "uploadThroughput": 2e6 / 8})


def sent(pg):
    """KB actually transferred for this page so far (cached files count 0)."""
    return pg.evaluate("() => Math.round(performance.getEntries().filter((e) => e.transferSize != null).reduce((s, e) => s + e.transferSize, 0) / 1024)")


def nav_ms(pg):
    return pg.evaluate("() => { const n = performance.getEntriesByType('navigation')[0]; return [Math.round(n.domContentLoadedEventEnd), Math.round(n.loadEventEnd)]; }")


with sync_playwright() as p:
    b = engine.launch(p)
    print(f"== [{engine.NAME}] {'with a 150 ms delay per request' if SLOW else 'on the local network'}")
    # the player's phone
    pctx = b.new_context(viewport={"width": 390, "height": 844}, **engine.mobile(), has_touch=True)
    pg = pctx.new_page(); pm = meter(pg, "player"); slow(pctx, pg)
    pg.goto(LAN + "/join"); pg.fill("input[name=code]", code); pg.fill("input[name=name]", "Speedy")
    pg.wait_for_selector("#char-field:not([hidden])"); pg.select_option("select[name=character_id]", value=str(chars["Moni Easter"]["id"]))
    pm.update(n=0, bytes=0, urls=[])
    t0 = time.time(); pg.click("button[type=submit]"); pg.wait_for_url(re.compile("/play")); pg.wait_for_selector("#me h3", timeout=20000)
    first = time.time() - t0
    pg.wait_for_timeout(1500)
    dcl, load = nav_ms(pg)
    print(f"   player /play: ready in {first * 1000:.0f} ms (DOM {dcl} ms, load {load} ms), {pm['n']} requests, {sent(pg)} KB transferred")
    check(first < (8 if SLOW else 4), f"the player's screen is ready in {first:.1f} s")
    # the same page again (a reload): cached files shouldn't come down again
    pm.update(n=0, bytes=0, urls=[])
    t0 = time.time(); pg.reload(); pg.wait_for_selector("#me h3", timeout=20000); again = time.time() - t0
    pg.wait_for_timeout(1500)
    print(f"   player reload: ready in {again * 1000:.0f} ms, {pm['n']} requests, {sent(pg)} KB transferred")
    again_kb = pg.evaluate("() => performance.getEntriesByType('resource').filter((e) => e.name.includes('/static/') && e.transferSize > 0).length")
    print(f"   static files downloaded again on reload: {again_kb}")
    print("   biggest on reload:", pg.evaluate("() => performance.getEntries().filter((e) => e.transferSize > 2000).sort((a, b) => b.transferSize - a.transferSize).slice(0, 6).map((e) => e.name.replace(location.origin, '') + ' ' + Math.round(e.transferSize / 1024) + 'KB ' + (e.encodedBodySize !== e.decodedBodySize ? 'gz' : '')).join(' | ')"))
    check(again_kb == 0, "a reload doesn't download the scripts and styles again")
    # the DM's map
    dctx = b.new_context(viewport={"width": 1366, "height": 900})
    dctx.add_init_script("""(() => { let real; Object.defineProperty(window, 'MapView', { configurable: true, get() { return real; },
      set(v) { real = class extends v { constructor(...a) { super(...a); window.__view = this; } }; } }); })();""")
    dm = dctx.new_page(); dmm = meter(dm, "DM"); slow(dctx, dm)
    t0 = time.time(); dm.goto(f"{DM}/map/{mid}"); dm.wait_for_selector("#dungeon-panel:not([hidden])", timeout=20000); dmt = time.time() - t0
    dm.wait_for_timeout(2500)
    dcl, load = nav_ms(dm)
    print(f"   DM map page: ready in {dmt * 1000:.0f} ms (DOM {dcl} ms, load {load} ms), {dmm['n']} requests, {sent(dm)} KB transferred")
    draw = dm.evaluate("() => { const v = window.__view; const t = performance.now(); for (let i = 0; i < 20; i++) v.draw(); return (performance.now() - t) / 20; }")
    pdraw = pg.evaluate("() => { const v = window.__view; if (!v) return -1; const t = performance.now(); for (let i = 0; i < 20; i++) v.draw(); return (performance.now() - t) / 20; }")
    print(f"   one map frame: DM {draw:.1f} ms, phone {pdraw:.1f} ms")
    check(draw < 25, f"the DM's map draws a frame in {draw:.1f} ms")
    # sitting still for 20 seconds: what does each page ask the server for?
    pm.update(n=0, bytes=0, urls=[]); dmm.update(n=0, bytes=0, urls=[])
    pg.wait_for_timeout(20000)
    print(f"   idle 20 s: player {pm['n']} requests ({pm['bytes'] / 1024:.0f} KB), DM {dmm['n']} requests ({dmm['bytes'] / 1024:.0f} KB)")
    from collections import Counter
    print("     player:", dict(Counter(pm["urls"]).most_common(6)))
    print("     DM:    ", dict(Counter(dmm["urls"]).most_common(6)))
    # a change on the DM's side: how long until the phone has fetched the new state
    lags = []
    hit = {"t": None}
    pg.on("response", lambda r: hit.update(t=time.time()) if "/api/play/state" in r.url and hit["t"] is None else None)
    rooms = len(d["rooms"])
    for i in range(5):
        pg.wait_for_timeout(1200)
        hit["t"] = None
        t0 = time.time()
        call("POST", f"/api/maps/{mid}/rooms/{rooms - 1}/reveal", {"reveal": i % 2 == 0})
        for _ in range(100):
            if hit["t"]:
                break
            pg.wait_for_timeout(50)
        lags.append((hit["t"] or time.time()) - t0)
    lag = sorted(lags)[len(lags) // 2]
    print(f"   a DM change reaches the phone in {lag * 1000:.0f} ms (middle of {', '.join(f'{x * 1000:.0f}' for x in lags)})")
    check(lag < (1.5 if SLOW else 0.8), f"changes reach the phone quickly ({lag * 1000:.0f} ms)")
    b.close()
fails = [x for ok, x in results if not ok]
print(f"\n{len(results) - len(fails)} passed, {len(fails)} failed"); [print("FAILED:", f) for f in fails]
print("PROBLEMS:", problems)
