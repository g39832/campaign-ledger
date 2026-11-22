"""E2E (2026-11-15): Yamato's seven techniques, from his phone and from the DM's combat page.

- His sheet: no Echo Teleport or Wide Slash; Slash, Action Surge, Parry, Echo Knight, Phantasmal Killers kept;
  the seven techniques as rows.
- Phone (his turn, two clones out): the Techniques panel lists all seven with cooldown and clone tags;
  Upper Slash: tap it, tap the enemy, Go -> it recharges (1-turn cooldown shown); Clone Calling works off
  his turn too (no action), then says "used this round".
- DM combat page: select Yamato, Guard Break with a picked clone -> the clone is gone, the enemy Staggered.
- Test Hero is a level 20 Eldritch Knight with his spells and slots."""
import json, re, urllib.request, uuid
from common import DM_URL, LAN_URL, SHOTS_DIR  # noqa: E402
from playwright.sync_api import sync_playwright
import engine

DM, LAN, SHOTS = DM_URL, LAN_URL, SHOTS_DIR
results, problems = [], []


def call(m, path, body=None, ok=True):
    data = json.dumps(dict(body or {}, op_id=uuid.uuid4().hex)).encode() if m != "GET" else None
    try:
        return json.load(urllib.request.urlopen(urllib.request.Request(DM + path, data=data, method=m, headers={"Content-Type": "application/json"})))
    except urllib.error.HTTPError as e:
        if ok:
            raise
        return {"status": e.code, **json.load(e)}


def check(c, msg):
    results.append((bool(c), msg)); print(("  PASS " if c else "  FAIL ") + msg, flush=True)


camp = 1
for e in call("GET", f"/api/campaigns/{camp}/encounters")["encounters"]:
    if e["status"] == "active":
        call("POST", f"/api/encounters/{e['id']}/end")
for pl in call("GET", f"/api/campaigns/{camp}/players")["players"]:
    call("DELETE", f"/api/players/{pl['id']}")
for x in call("GET", f"/api/campaigns/{camp}/handouts").get("handouts", []):
    call("DELETE", f"/api/handouts/{x['id']}")
chars = {c["name"]: c for c in call("GET", f"/api/campaigns/{camp}/characters")["characters"]}
yam = call("GET", f"/api/characters/{chars['Yamato']['id']}")["character"]
names = [s.get("name", "").strip() for s in yam["spells"]]
check("Echo Teleport" not in names and "Wide Slash" not in names, "Echo Teleport and Wide Slash are gone from his sheet")
check({"Parry", "Echo Knight", "Phantasmal Killers"} <= set(names) and [a["name"].strip() for a in yam["attacks"]] == ["Slash", "Action Surge"],
      "Slash, Action Surge, Parry, Echo Knight and Phantasmal Killers are kept")
tech = [s["name"] for s in yam["spells"] if s.get("technique")]
check(tech == ["Phantom Blade", "Storm Wave", "Upper Slash", "Guard Break", "Clone Calling", "Chain Attack", "Mirage"], "the seven techniques are on his sheet")
hero = call("GET", f"/api/characters/{chars['Test Hero']['id']}")["character"]
check(hero["level"] == 20 and hero["subclass"] == "Eldritch Knight" and len(hero["spells"]) == 17 and hero["spell_slots"]["4"]["max"] == 1,
      "Test Hero: level 20 Eldritch Knight, 16 spells + Second Wind, a 4th-level slot")
call("POST", f"/api/characters/{yam['id']}/long-rest")

# a small fight: Yamato vs two hazmat troopers (made tough), on a live map
lib = {c["name"]: c for c in call("GET", f"/api/creatures?campaign_id={camp}")["creatures"]}
eid = call("POST", f"/api/campaigns/{camp}/encounters", {"name": "Technique test"})["encounter"]["id"]
st = call("POST", f"/api/encounters/{eid}/combatants", {"characters": [yam["id"]]})
st = call("POST", f"/api/encounters/{eid}/combatants", {"creature_id": lib["Hazmat Trooper"]["id"], "count": 2})
by = {c["name"]: c for c in st["combatants"]}
foes = [c for c in st["combatants"] if c["kind"] == "enemy"]
mp = call("POST", f"/api/campaigns/{camp}/maps", {"name": "Technique test", "cols": 14, "rows": 10, "encounter_id": eid})["map"]
call("POST", f"/api/maps/{mp['id']}/tokens/from-encounter")
call("POST", f"/api/campaigns/{camp}/live-map", {"map_id": mp["id"]})
for c, r in ((by["Yamato"], 20), (foes[0], 10), (foes[1], 5)):
    call("PATCH", f"/api/combatants/{c['id']}", {"changes": {"init_roll": {"from": None, "to": r}}})
call("POST", f"/api/encounters/{eid}/start")
for f in foes:
    call("POST", f"/api/combatants/{f['id']}/hp", {"op": "temp", "amount": 300})
call("POST", f"/api/encounters/{eid}/set-turn", {"combatant_id": by["Yamato"]["id"]})
toks = {t["display"]: t for t in call("GET", f"/api/maps/{mp['id']}")["tokens"]}
call("POST", f"/api/tokens/{toks['Yamato']['id']}/move", {"x": 4, "y": 4, "free": True})
call("POST", f"/api/tokens/{toks[foes[0]['name']]['id']}/move", {"x": 5, "y": 4, "free": True})
call("POST", f"/api/tokens/{toks[foes[1]['name']]['id']}/move", {"x": 11, "y": 8, "free": True})
killers = next(i for i, s in enumerate(yam["spells"]) if s.get("summon_count") == 2)
call("POST", f"/api/encounters/{eid}/cast", {"caster_id": by["Yamato"]["id"], "spell": killers, "targets": [], "at": [3, 4]})
# a fresh turn for him (a new round) with his clones out
st = call("POST", f"/api/encounters/{eid}/next")
while st["encounter"]["current_id"] != by["Yamato"]["id"]:
    st = call("POST", f"/api/encounters/{eid}/next")
clones = [c for c in st["combatants"] if c.get("follows") == by["Yamato"]["id"]]
check(len(clones) == 2, "two clones out (Phantasmal Killers)")

code = call("POST", f"/api/campaigns/{camp}/join-code", {"action": "new"})["join_code"]
with sync_playwright() as p:
    b = engine.launch(p)
    print(f"== [{engine.NAME}] Yamato's phone")
    ctx = b.new_context(viewport={"width": 390, "height": 844}, **engine.mobile(), has_touch=True)
    ph = ctx.new_page(); ph.on("pageerror", lambda e: problems.append(f"phone JS error: {e}"))
    ph.goto(LAN + "/join"); ph.fill("input[name=code]", code); ph.fill("input[name=name]", "Yamato player")
    ph.wait_for_selector("#char-field:not([hidden])"); ph.select_option("select[name=character_id]", value=str(yam["id"]))
    ph.click("button[type=submit]"); ph.wait_for_url(re.compile("/play")); ph.wait_for_timeout(2500)
    box = ph.locator('[data-tech="phone"]')
    check(box.count() == 1 and box.locator(".tech-row").count() == 7, "the Techniques panel shows all seven on his phone")
    txt = box.inner_text()
    check("Uses up every clone" in txt and "Uses up 1 clone" in txt and "Moves clones" in txt and "5-turn cooldown" in txt and "once a round" in txt,
          "each one says its cooldown and whether it uses up or moves clones")
    ph.screenshot(path=f"{SHOTS}/yamato_tech_phone_{engine.NAME}.png", full_page=True)
    box.locator('[data-open="upper_slash"]').click()
    box = ph.locator('[data-tech="phone"]')
    box.locator(f'[data-key="upper_slash"] [data-foe="{foes[0]["id"]}"]').click()
    box = ph.locator('[data-tech="phone"]')
    box.locator('[data-key="upper_slash"] [data-go="upper_slash"]').click()
    ph.wait_for_timeout(2000)
    log = " ".join(x["message"] for x in call("GET", f"/api/encounters/{eid}")["log"])
    check("Upper Slash" in log, "Upper Slash from the phone hits the log")
    up = ph.locator('[data-tech="phone"] [data-key="upper_slash"]').inner_text()
    check("recharging" in up, "Upper Slash now shows it's recharging")
    # off his turn: Clone Calling still works (no action)
    call("POST", f"/api/encounters/{eid}/set-turn", {"combatant_id": foes[1]["id"]})
    far = [t for t in call("GET", f"/api/maps/{mp['id']}")["tokens"] if t["display"].lower().startswith("yamato clone")][0]
    call("POST", f"/api/tokens/{far['id']}/move", {"x": 12, "y": 1, "free": True})
    ph.wait_for_timeout(2500)
    cc = ph.locator('[data-tech="phone"] [data-key="clone_calling"]')
    cc.locator('[data-open="clone_calling"]').click()
    ph.locator('[data-tech="phone"] [data-go="clone_calling"]').click()
    ph.wait_for_timeout(2000)
    ys = [t for t in call("GET", f"/api/maps/{mp['id']}")["tokens"] if t["display"].lower().startswith("yamato clone")]
    check(all(abs(t["x"] - 4) <= 1 and abs(t["y"] - 4) <= 1 for t in ys), "Clone Calling (off his turn) brings both clones back beside him")
    check("used this round" in ph.locator('[data-tech="phone"] [data-key="clone_calling"]').inner_text(), "then it says used this round")
    ctx.close()

    print(f"== [{engine.NAME}] DM combat page: Guard Break")
    call("POST", f"/api/encounters/{eid}/set-turn", {"combatant_id": by["Yamato"]["id"]})
    st = call("GET", f"/api/encounters/{eid}")
    clones = [c for c in st["combatants"] if c.get("follows") == by["Yamato"]["id"]]
    dm = b.new_context(viewport={"width": 1366, "height": 900}).new_page()
    dm.on("pageerror", lambda e: None if "ResizeObserver loop" in str(e) else problems.append(f"DM JS error: {e}"))
    dm.goto(DM + f"/combat/{eid}"); dm.wait_for_timeout(2000)
    if dm.locator("#dice-close").is_visible():
        dm.click("#dice-close")
    dm.locator("#init-list li.combatant").filter(has=dm.locator(".c-name > span:first-child", has_text=re.compile("^Yamato$"))).first.locator(".c-name").click()
    dm.wait_for_timeout(800)
    box = dm.locator(f'[data-tech="c{by["Yamato"]["id"]}"]')
    check(box.count() == 1 and box.locator(".tech-row").count() == 7, "the DM sees the same Techniques panel for Yamato")
    box.locator('[data-open="guard_break"]').click()
    box = dm.locator(f'[data-tech="c{by["Yamato"]["id"]}"]')
    box.locator(f'[data-key="guard_break"] [data-foe="{foes[0]["id"]}"]').click()
    box = dm.locator(f'[data-tech="c{by["Yamato"]["id"]}"]')
    box.locator(f'[data-key="guard_break"] [data-clone="{clones[0]["id"]}"]').click()
    box = dm.locator(f'[data-tech="c{by["Yamato"]["id"]}"]')
    box.locator('[data-go="guard_break"]').click()
    dm.wait_for_timeout(2000)
    st = call("GET", f"/api/encounters/{eid}")
    check(clones[0]["id"] not in {c["id"] for c in st["combatants"]}, "Guard Break used up the clone it sent")
    log = " ".join(x["message"] for x in st["log"])
    check("Guard Break" in log and "used up by Guard Break" in log, "the log says so")
    dm.screenshot(path=f"{SHOTS}/yamato_tech_dm_{engine.NAME}.png", full_page=True)
    b.close()

call("POST", f"/api/encounters/{eid}/end")
check(not problems, "no page errors" + ("" if not problems else ": " + "; ".join(problems[:3])))
print(f"e2e_yamato_tech.py [{engine.NAME}]: {sum(1 for ok, _ in results if ok)} passed, {sum(1 for ok, _ in results if not ok)} failed")
