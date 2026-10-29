"""Monster pictures, clicked: upload one on the Creatures page; it shows in the library list, the Combat
list and on the map token (DM and a player's phone); remove it again."""
import base64, json, os, re, struct, urllib.request, uuid, zlib
from common import APP_DIR, DM_URL, LAN_IP, LAN_URL, SHOTS_DIR, TMP_DIR  # noqa: E402,F401  (paths and addresses for this computer)
from playwright.sync_api import sync_playwright
import engine

DM = DM_URL; LAN = LAN_URL
SP = TMP_DIR
SHOTS = SP + r"\shots"
results, problems = [], []


def call(m, path, body=None):
    data = json.dumps(dict(body or {}, op_id=uuid.uuid4().hex)).encode() if m != "GET" else None
    return json.load(urllib.request.urlopen(urllib.request.Request(DM + path, data=data, method=m, headers={"Content-Type": "application/json"})))


def check(c, msg):
    results.append((bool(c), msg)); print(("  PASS " if c else "  FAIL ") + msg, flush=True)


def png(w, h, rgb):  # a plain-colour picture to upload
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


PIC = SP + r"\mimic_pic.png"
open(PIC, "wb").write(png(64, 64, (20, 200, 60)))  # bright green
for e in call("GET", "/api/campaigns/1/encounters")["encounters"]:
    if e["status"] == "active":
        call("POST", f"/api/encounters/{e['id']}/end")
for pl in call("GET", "/api/campaigns/1/players")["players"]:
    call("DELETE", f"/api/players/{pl['id']}")
lib = call("GET", "/api/creatures")["creatures"]
mimic = next(c for c in lib if c["name"] == "Mimic Boss")
chars = {c["name"]: c for c in call("GET", "/api/campaigns/1/characters")["characters"]}
eid = call("POST", "/api/campaigns/1/encounters", {"name": "Mimic lair"})["encounter"]["id"]
call("POST", f"/api/encounters/{eid}/combatants", {"characters": [chars["Lux Fedelis"]["id"]]})
call("POST", f"/api/encounters/{eid}/combatants", {"creature_id": mimic["id"], "count": 1})
mid = call("POST", f"/api/encounters/{eid}/map")["map_id"]
call("POST", "/api/campaigns/1/live-map", {"map_id": mid})
code = call("POST", "/api/campaigns/1/join-code", {"action": "new"})["join_code"]
with sync_playwright() as p:
    b = engine.launch(p)
    pg = b.new_page(viewport={"width": 1400, "height": 950}); pg.on("pageerror", lambda e: problems.append(f"JS error: {e}"))
    pg.goto(DM + "/creatures"); pg.wait_for_timeout(1500)
    pg.locator("#list li button").filter(has=pg.locator(".t", has_text=re.compile(r"Mimic Boss$"))).first.click(); pg.wait_for_timeout(600)
    check(pg.locator("#editor .sb-pic").count() == 1 and "Add picture" in pg.locator("#editor .sb-pic").inner_text(), "the stat block has an Add picture spot")
    pg.locator("#editor .sb-pic input[type=file]").set_input_files(PIC); pg.wait_for_timeout(2000)
    m = next(c for c in call("GET", "/api/creatures")["creatures"] if c["id"] == mimic["id"])
    check(m["portrait"], f"the picture is saved ({m['portrait']})")
    check(pg.locator("#editor .sb-pic img").count() == 1 and pg.locator("#list li button.has-pic .lib-pic").count() == 1, "it shows on the stat block and in the library list")
    check(all(c["portrait"] is None for c in call("GET", "/api/creatures")["creatures"] if c["id"] != mimic["id"]), "no other creature changed")
    pg.locator("#editor").screenshot(path=SHOTS + rf"\monicon_editor_{engine.NAME}.png")
    pg.locator("#list").screenshot(path=SHOTS + rf"\monicon_list_{engine.NAME}.png")
    # the Combat list
    pg.goto(DM + f"/combat/{eid}"); pg.wait_for_timeout(1500)
    row = pg.locator("#init-list li.combatant").filter(has_text="Mimic Boss").first
    check(row.locator("img").count() == 1, "the Combat list shows the Mimic Boss's picture")
    # the map (the DM's), and a player's phone
    def green(page):
        return page.evaluate("""() => { const c = document.querySelector('#stage canvas'); const x = c.getContext('2d'); const d = x.getImageData(0, 0, c.width, c.height).data;
          let n = 0; for (let i = 0; i < d.length; i += 4) { if (d[i + 1] > 170 && d[i] < 70 && d[i + 2] < 110) n++; } return n; }""")
    pg.goto(DM + f"/map/{mid}"); pg.wait_for_timeout(2500)
    n = green(pg); check(n > 50, f"the map token is drawn with the picture ({n} green pixels)")
    pg.locator("#stage").screenshot(path=SHOTS + rf"\monicon_map_{engine.NAME}.png")
    ph = b.new_context(viewport={"width": 390, "height": 844}, **engine.mobile(), has_touch=True).new_page()
    ph.on("pageerror", lambda e: problems.append(f"phone JS error: {e}"))
    ph.goto(LAN + "/join"); ph.fill("input[name=code]", code); ph.fill("input[name=name]", "Lux plays")
    ph.wait_for_selector("#char-field:not([hidden])"); ph.select_option("select[name=character_id]", value=str(chars["Lux Fedelis"]["id"]))
    ph.click("button[type=submit]"); ph.wait_for_url(re.compile("/play")); ph.wait_for_timeout(3000)
    n = green(ph); check(n > 20, f"the player's phone draws it on the map too ({n} green pixels)")
    # remove it
    pg.goto(DM + "/creatures"); pg.wait_for_timeout(1200)
    pg.locator("#list li button").filter(has=pg.locator(".t", has_text=re.compile(r"Mimic Boss$"))).first.click(); pg.wait_for_timeout(500)
    pg.locator("#editor").get_by_role("button", name="Remove picture").click(); pg.wait_for_timeout(1500)
    check(next(c for c in call("GET", "/api/creatures")["creatures"] if c["id"] == mimic["id"])["portrait"] is None and pg.locator("#editor .sb-pic img").count() == 0, "Remove picture takes it off")
    b.close()
fails = [m for ok, m in results if not ok]
print(f"\n{len(results) - len(fails)} passed, {len(fails)} failed"); [print("FAILED:", f) for f in fails]
print("PROBLEMS:", problems)
