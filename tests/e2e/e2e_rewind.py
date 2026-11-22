"""E2E: Lux's Worldheart Fate Ring (Time Reversal). A goblin walks off and hits Lux; right after
its turn ends, Lux's phone offers "Rewind it": one tap and the goblin is back where its turn
began, Lux's HP is back, and it's the goblin's turn again. The ring is then used until a long
rest. The DM can also use it from the combat screen."""
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
for e in call("GET", f"/api/campaigns/{camp}/encounters")["encounters"]:
    if e["status"] == "active":
        call("POST", f"/api/encounters/{e['id']}/end")
for pl in call("GET", f"/api/campaigns/{camp}/players")["players"]:
    call("DELETE", f"/api/players/{pl['id']}")
chars = {c["name"]: c for c in call("GET", f"/api/campaigns/{camp}/characters")["characters"]}
lux = call("GET", f"/api/characters/{chars['Lux Fedelis']['id']}")["character"]
ring = next((i for i, s in enumerate(lux["spells"]) if s.get("rewind")), None)
check(ring is not None, "Lux's sheet has the Time Reversal row")
call("POST", f"/api/characters/{lux['id']}/long-rest")  # full HP, ring ready
eid = call("POST", f"/api/campaigns/{camp}/encounters", {"name": "Fate ring"})["encounter"]["id"]
call("POST", f"/api/encounters/{eid}/combatants", {"characters": [lux["id"]], "quick": {"name": "Goblin", "max_hp": 50, "ac": 5, "count": 1}})
mid = call("POST", f"/api/encounters/{eid}/map")["map_id"]
call("PATCH", f"/api/maps/{mid}", {"changes": {"cols": {"to": 20}, "rows": {"to": 12}}})
toks = {t["display"]: t for t in call("GET", f"/api/maps/{mid}")["tokens"]}
gname = next(n for n in toks if n.startswith("Goblin"))
for n, (x, y) in {"Lux Fedelis": (5, 5), gname: (7, 5)}.items():
    call("POST", f"/api/tokens/{toks[n]['id']}/move", {"x": x, "y": y, "free": True})
call("POST", f"/api/campaigns/{camp}/live-map", {"map_id": mid})
call("POST", f"/api/encounters/{eid}/start")
by = {c["name"]: c for c in call("GET", f"/api/encounters/{eid}")["combatants"]}


def turn_to(name):
    for _ in range(6):
        if call("GET", f"/api/encounters/{eid}")["encounter"]["current_id"] == by[name]["id"]:
            return
        call("POST", f"/api/encounters/{eid}/next")


def lux_hp():
    return call("GET", f"/api/characters/{lux['id']}")["character"]["current_hp"]


def gob_at():
    t = next(t for t in call("GET", f"/api/maps/{mid}")["tokens"] if t["display"] == gname)
    return (t["x"], t["y"])


code = call("POST", f"/api/campaigns/{camp}/join-code", {"action": "new"})["join_code"]
with sync_playwright() as p:
    b = engine.launch(p)
    ctx = b.new_context(viewport={"width": 390, "height": 844}, **engine.mobile(), has_touch=True)
    ph = ctx.new_page(); ph.on("pageerror", lambda e: problems.append(f"phone JS error: {e}"))
    ph.goto(LAN + "/join"); ph.fill("input[name=code]", code); ph.fill("input[name=name]", "Colin")
    ph.wait_for_selector("#char-field:not([hidden])"); ph.select_option("select[name=character_id]", value=str(lux["id"]))
    ph.click("button[type=submit]"); ph.wait_for_url(re.compile("/play")); ph.wait_for_timeout(2500)
    card = ph.locator(".move-card").filter(has_text="Time Reversal").first
    check(card.count() == 1 and "takes the turn again" in card.inner_text(), "the phone shows the ring and what it does")

    print(f"== [{engine.NAME}] The goblin's turn: it walks off and hits Lux")
    turn_to(gname)
    call("POST", f"/api/tokens/{toks[gname]['id']}/move", {"x": 11, "y": 5})
    hp0 = lux_hp()
    call("POST", f"/api/combatants/{by['Lux Fedelis']['id']}/hp", {"op": "damage", "amount": 6})
    check(lux_hp() == hp0 - 6 and gob_at() == (11, 5), "goblin moved and Lux took 6")
    call("POST", f"/api/encounters/{eid}/next")  # its turn ends
    ph.wait_for_selector(".parry-box:has-text('just ended its turn')", timeout=15000)
    box = ph.locator(".parry-box").filter(has_text="just ended its turn")
    check(gname in box.inner_text(), f"Lux's phone: '{box.inner_text().splitlines()[0][:80]}'")
    ph.screenshot(path=SHOTS + f"/rewind_{engine.NAME}_offer.png")
    box.get_by_role("button", name="Rewind it").click(); ph.wait_for_timeout(2500)
    st = call("GET", f"/api/encounters/{eid}")
    check(st["encounter"]["current_id"] == by[gname]["id"], "it's the goblin's turn again")
    check(lux_hp() == hp0, f"Lux's HP is back ({lux_hp()})")
    check(gob_at() == (7, 5), f"the goblin is back where its turn began ({gob_at()})")
    check(any("Time Reversal" in l["message"] for l in st["log"]), "the fight log says what happened")
    check(ph.locator(".parry-box").filter(has_text="just ended its turn").count() == 0, "the offer is gone")
    check("long rest" in ph.locator(".move-card").filter(has_text="Time Reversal").first.inner_text(), "the ring now says used · back after a long rest")
    ph.screenshot(path=SHOTS + f"/rewind_{engine.NAME}_after.png")

    print(f"== [{engine.NAME}] After a long rest, the DM uses it from the combat screen")
    call("POST", f"/api/characters/{lux['id']}/long-rest")
    turn_to(gname); call("POST", f"/api/tokens/{toks[gname]['id']}/move", {"x": 9, "y": 6})
    call("POST", f"/api/encounters/{eid}/next")
    dmc = b.new_context(viewport={"width": 1400, "height": 950})
    dm = dmc.new_page(); dm.on("pageerror", lambda e: problems.append(f"DM JS error: {e}"))
    dm.goto(f"{DM}/combat/{eid}"); dm.wait_for_timeout(1500)
    dm.locator("#init-list li.combatant").filter(has=dm.locator(".c-name > span:first-child", has_text=re.compile("^Lux Fedelis$"))).first.locator(".c-name").click()
    dm.wait_for_timeout(400)
    btn = dm.locator("#detail .spell-row").filter(has_text="Time Reversal").first.get_by_role("button", name=re.compile("Rewind"))
    check(btn.count() == 1, "the DM sees 'Rewind Goblin's turn' on Lux")
    btn.click(); dm.wait_for_timeout(1500)
    check(call("GET", f"/api/encounters/{eid}")["encounter"]["current_id"] == by[gname]["id"] and gob_at() == (7, 5), "the DM's rewind works too")
    b.close()
call("POST", f"/api/encounters/{eid}/end")
fails = [m for ok, m in results if not ok]
print(f"\n{len(results) - len(fails)} passed, {len(fails)} failed"); [print("FAILED:", f) for f in fails]
print("PROBLEMS:", problems)
