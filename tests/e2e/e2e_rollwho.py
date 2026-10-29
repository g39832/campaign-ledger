"""Who is rolling: a title across the top while dice roll (a player's phone and the DM's map),
then what they rolled; rolls slower."""
import json, re, time, urllib.request, uuid
from common import APP_DIR, DM_URL, LAN_IP, LAN_URL, SHOTS_DIR, TMP_DIR  # noqa: E402,F401  (paths and addresses for this computer)
from playwright.sync_api import sync_playwright

DM = DM_URL; LAN = LAN_URL
SHOTS = SHOTS_DIR
results = []


def call(m, path, body=None):
    data = json.dumps(dict(body or {}, op_id=uuid.uuid4().hex)).encode() if m != "GET" else None
    return json.load(urllib.request.urlopen(urllib.request.Request(DM + path, data=data, method=m, headers={"Content-Type": "application/json"})))


def check(c, msg):
    results.append((bool(c), msg)); print(("  PASS " if c else "  FAIL ") + msg, flush=True)


for e in call("GET", "/api/campaigns/1/encounters")["encounters"]:
    if e["status"] == "active":
        call("POST", f"/api/encounters/{e['id']}/end")
for pl in call("GET", "/api/campaigns/1/players")["players"]:
    call("DELETE", f"/api/players/{pl['id']}")
chars = {c["name"]: c for c in call("GET", "/api/campaigns/1/characters")["characters"]}
eid = call("POST", "/api/campaigns/1/encounters", {"name": "Who rolls"})["encounter"]["id"]
call("POST", f"/api/encounters/{eid}/combatants", {"characters": [chars["Lux Fedelis"]["id"]], "quick": {"name": "Goblin", "max_hp": 20, "ac": 10, "count": 2}})
mid = call("POST", f"/api/encounters/{eid}/map")["map_id"]
call("POST", "/api/campaigns/1/live-map", {"map_id": mid})
call("POST", f"/api/encounters/{eid}/start")
code = call("POST", "/api/campaigns/1/join-code", {"action": "new"})["join_code"]
with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    ph = b.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True).new_page()
    ph.goto(LAN + "/join"); ph.fill("input[name=code]", code); ph.fill("input[name=name]", "Lux plays")
    ph.wait_for_selector("#char-field:not([hidden])"); ph.select_option("select[name=character_id]", value=str(chars["Lux Fedelis"]["id"]))
    ph.click("button[type=submit]"); ph.wait_for_url(re.compile("/play")); ph.wait_for_timeout(2500)
    dm = b.new_page(viewport={"width": 1400, "height": 900}); dm.goto(DM + f"/map/{mid}"); dm.wait_for_timeout(2500)
    # the DM rolls a goblin's attack from the dice tray (as the goblin): everyone sees who's rolling
    t0 = time.time()
    dm.evaluate("Dice.roll({ expression: '1d20+4', label: 'Scimitar attack', kind: 'attack', subject: 'Goblin 1', encounter_id: %d })" % eid)
    dm.wait_for_timeout(900)
    cap = dm.locator("#roll-who").inner_text().replace("\n", " ")
    check("Goblin 1" in cap and "is rolling" in cap, f"DM's screen while it rolls: {cap!r}")
    dm.screenshot(path=SHOTS + r"\rollwho_dm_rolling.png")
    ph.wait_for_timeout(2600)  # the phone picks it up on its next look (every 1.5 s)
    pc = ph.locator("#roll-who").inner_text().replace("\n", " ") if ph.locator("#roll-who").count() else ""
    check("Goblin 1" in pc, f"Lux's phone shows who: {pc!r}")
    ph.screenshot(path=SHOTS + r"\rollwho_phone.png")
    dm.wait_for_timeout(2600)
    cap = dm.locator("#roll-who").inner_text().replace("\n", " ")
    check("Goblin 1 rolled" in cap and re.search(r"rolled\s+\d+", cap), f"after it lands: {cap!r}")
    dm.screenshot(path=SHOTS + r"\rollwho_dm_done.png")
    dm.wait_for_timeout(4500)
    check(not dm.locator("#roll-who.is-on").count(), "the title goes away after a moment")
    b.close()
fails = [m for ok, m in results if not ok]
print(f"\n{len(results) - len(fails)} passed, {len(fails)} failed")
