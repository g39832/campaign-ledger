"""E2E: free roam on the real live map. Every hero joins (phone, tablet, laptop) and walks with the
arrow pad (tap and hold) or the arrow keys, one square at a time; a long drag is refused. Then Lux
uses a Stim injector and a Med-gel patch from the Inventory and heals."""
import json, re, urllib.request, uuid
from common import APP_DIR, DM_URL, LAN_IP, LAN_URL, SHOTS_DIR, TMP_DIR  # noqa: E402,F401
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


camp = 1
for pl in call("GET", f"/api/campaigns/{camp}/players")["players"]:
    call("DELETE", f"/api/players/{pl['id']}")
chars = {c["name"]: c for c in call("GET", f"/api/campaigns/{camp}/characters")["characters"]}
live = next((c for c in call("GET", "/api/campaigns")["campaigns"] if c["id"] == camp), {}).get("live_map_id") or 6
mid = live
print("live map", mid)


def my_tok(cid):
    return next(t for t in call("GET", f"/api/maps/{mid}")["tokens"] if t.get("character_id") == cid and t["kind"] == "pc")


DEVICES = {"Lux Fedelis": ("phone", {"width": 390, "height": 844}), "Moni Easter": ("tablet", {"width": 820, "height": 1180}),
           "Yamato": ("laptop", {"width": 1400, "height": 900}), "Gnocchi": ("phone", {"width": 412, "height": 915})}
code = call("POST", f"/api/campaigns/{camp}/join-code", {"action": "new"})["join_code"]
with sync_playwright() as p:
    b = engine.launch(p)
    for name, (kind, vp) in DEVICES.items():
        cid = chars[name]["id"]
        extra = dict(**engine.mobile(), has_touch=True) if kind != "laptop" else {}
        ctx = b.new_context(viewport=vp, **extra)
        pg = ctx.new_page(); pg.on("pageerror", lambda e, n=name: problems.append(f"{n} JS error: {e}"))
        pg.goto(LAN + "/join"); pg.fill("input[name=code]", code); pg.fill("input[name=name]", name.split()[0])
        pg.wait_for_selector("#char-field:not([hidden])"); pg.select_option("select[name=character_id]", value=str(cid))
        pg.click("button[type=submit]"); pg.wait_for_url(re.compile("/play")); pg.wait_for_timeout(2500)
        print(f"== [{engine.NAME}] {name} on a {kind}")
        check(pg.locator("#roam-pad").is_visible(), f"{name}: the walking pad shows")
        check("one square at a time" in pg.locator("#hint").inner_text(), f"{name}: hint '{pg.locator('#hint').inner_text()[:70]}'")
        start = my_tok(cid); moved = None
        for d in ["1,0", "-1,0", "0,1", "0,-1", "1,1", "-1,-1", "1,-1", "-1,1"]:
            btn = pg.locator(f"#roam-pad [data-step='{d}']")
            if kind == "laptop":
                btn.click()
            else:
                btn.tap()
            pg.wait_for_timeout(900)
            now = my_tok(cid)
            if (now["x"], now["y"]) != (start["x"], start["y"]):
                moved = (now["x"] - start["x"], now["y"] - start["y"]); break
        check(moved is not None and max(abs(moved[0]), abs(moved[1])) == 1, f"{name}: one tap = one square {moved}")
        if kind == "laptop":
            here = my_tok(cid)
            pg.locator("#stage").click(position={"x": 5, "y": 300}) if False else None
            for key in ["ArrowLeft", "ArrowRight", "ArrowDown", "ArrowUp"]:
                pg.keyboard.press(key); pg.wait_for_timeout(700)
                t = my_tok(cid)
                if (t["x"], t["y"]) != (here["x"], here["y"]):
                    break
            check((t["x"], t["y"]) != (here["x"], here["y"]) and max(abs(t["x"] - here["x"]), abs(t["y"] - here["y"])) == 1, f"{name}: an arrow key walks one square")
        if kind == "tablet":  # hold the arrow: keeps walking
            here = my_tok(cid)
            for d in ["-1,0", "1,0", "0,1", "0,-1"]:
                box = pg.locator(f"#roam-pad [data-step='{d}']").bounding_box()
                pg.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2); pg.mouse.down(); pg.wait_for_timeout(1500); pg.mouse.up(); pg.wait_for_timeout(800)
                t = my_tok(cid)
                if max(abs(t["x"] - here["x"]), abs(t["y"] - here["y"])) >= 2:
                    break
            check(max(abs(t["x"] - here["x"]), abs(t["y"] - here["y"])) >= 2, f"{name}: holding an arrow keeps walking ({here['x']},{here['y']} -> {t['x']},{t['y']})")
        # a long jump is refused by the server, whatever the screen does
        t = my_tok(cid)
        r = pg.evaluate("""async ([id, x, y]) => { const r = await fetch('/api/play/tokens/' + id + '/move', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ x, y }) }); return [r.status, (await r.json()).error]; }""",
                        [t["id"], t["x"] + 4 if t["x"] < 30 else t["x"] - 4, t["y"]])
        check(r[0] == 403 and "one square" in (r[1] or ""), f"{name}: a 4-square jump is refused ({r})")
        pg.screenshot(path=SHOTS + f"/roam_{engine.NAME}_{name.split()[0]}.png")
        if name == "Lux Fedelis":
            print(f"== [{engine.NAME}] Lux uses healing items")
            lux = call("GET", f"/api/characters/{cid}")["character"]
            call("PATCH", f"/api/characters/{cid}", {"changes": {"current_hp": {"from": lux["current_hp"], "to": 10}}}); pg.wait_for_timeout(2500)
            inv = pg.locator("#inventory")
            if inv.get_attribute("open") is None:
                inv.locator("summary").click()
            stim = inv.locator(".inv-item").filter(has_text="Stim injector").first
            stims0 = int(re.search(r"×(\d+)", stim.inner_text()).group(1)) if "×" in stim.inner_text() else 1
            stim.get_by_role("button", name=re.compile("Use")).click(); pg.wait_for_timeout(3500)
            if pg.locator("#dice-dock.is-open").count():
                pg.click("#dice-close")
            hp1 = call("GET", f"/api/characters/{cid}")["character"]["current_hp"]
            check(14 <= hp1 <= 20, f"Stim injector heals 2d4+2 (10 -> {hp1})")
            stim = pg.locator("#inventory .inv-item").filter(has_text="Stim injector").first
            check(f"×{stims0 - 1}" in stim.inner_text() or stims0 - 1 == 1, f"one Stim used ({stims0} -> {stims0 - 1})")
            patch = pg.locator("#inventory .inv-item").filter(has_text="Med-gel patch").first
            patch.get_by_role("button", name=re.compile("Use")).click(); pg.wait_for_timeout(3500)
            if pg.locator("#dice-dock.is-open").count():
                pg.click("#dice-close")
            hp2 = call("GET", f"/api/characters/{cid}")["character"]["current_hp"]
            check(hp1 + 2 <= hp2 <= hp1 + 5, f"Med-gel patch heals 1d4+1 ({hp1} -> {hp2})")
            check(pg.locator("#inventory .inv-item").filter(has_text="Med-gel patch").count() == 0, "the only patch is used up")
            check(pg.locator("#inventory .inv-item").filter(has_text="Duct tape").get_by_role("button", name=re.compile("Use")).count() == 0, "duct tape has no Use button")
            pg.screenshot(path=SHOTS + f"/items_{engine.NAME}.png", full_page=True)
        ctx.close()
    b.close()
fails = [m for ok, m in results if not ok]
print(f"\n{len(results) - len(fails)} passed, {len(fails)} failed"); [print("FAILED:", f) for f in fails]
print("PROBLEMS:", problems)
