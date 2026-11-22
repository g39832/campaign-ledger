"""E2E (2026-11-09; Echo Teleport retired 2026-11-15): Yamato's Echo Teleport, Lux's Mend cantrip and the five-floor laboratory.

- Yamato's phone: no Phantasmal force any more; Echo Teleport shows a button per clone; one tap and
  he stands where the clone stood (they swap), with 15 ft of movement spent and no action.
- Lux's phone: Mend is a cantrip under Spells (not an attack), heals from the phone, then recharges.
- The DM's Maps page: "Laboratory" makes floor 1 (3 lockers, lab enemies), the panel says floor 1 of 5
  and the lift goes up; floor 5 has the Head Researcher and the safe, and no way any higher."""
import json, re, urllib.request, uuid
from common import APP_DIR, DM_URL, LAN_IP, LAN_URL, SHOTS_DIR, TMP_DIR  # noqa: E402,F401
from playwright.sync_api import sync_playwright
import engine

DM = DM_URL; LAN = LAN_URL
SHOTS = SHOTS_DIR
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
chars = {c["name"]: c for c in call("GET", f"/api/campaigns/{camp}/characters")["characters"]}
yam = call("GET", f"/api/characters/{chars['Yamato']['id']}")["character"]
lux = call("GET", f"/api/characters/{chars['Lux Fedelis']['id']}")["character"]
check(not any("phantas" in (s.get("name") or "").lower() and "killer" not in (s.get("name") or "").lower() for s in yam["spells"]),
      "Yamato's sheet has no Phantasmal force")
tp = next((i for i, s in enumerate(yam["spells"]) if s.get("clone_swap")), None)
echo = next((i for i, s in enumerate(yam["spells"]) if s.get("name") == "Echo Knight"), None)
check(tp is None and echo is not None, "Echo Teleport was retired on 2026-11-15 (his techniques: e2e_yamato_tech.py); Echo Knight stays")
mend = next((s for s in lux["spells"] if s.get("name") == "Mend"), None)
check(mend and mend["level"] == 0 and mend["effect"] == "heal" and mend["cooldown"] == 1, "Lux's Mend is a level 0 (cantrip) heal, 1-turn cooldown")
check(not any((a.get("name") or "").strip() == "Mend" for a in lux["attacks"]), "Mend isn't in Lux's attacks any more")
for c in (yam, lux):
    call("POST", f"/api/characters/{c['id']}/long-rest")

eid = call("POST", f"/api/campaigns/{camp}/encounters", {"name": "Echo test"})["encounter"]["id"]
call("POST", f"/api/encounters/{eid}/combatants", {"characters": [yam["id"], lux["id"]], "quick": {"name": "Goblin", "max_hp": 50, "ac": 5, "count": 1}})
mid = call("POST", f"/api/encounters/{eid}/map")["map_id"]
call("PATCH", f"/api/maps/{mid}", {"changes": {"cols": {"to": 20}, "rows": {"to": 12}}})
toks = {t["display"]: t for t in call("GET", f"/api/maps/{mid}")["tokens"]}
gname = next(n for n in toks if n.startswith("Goblin"))
for n, (x, y) in {"Yamato": (3, 3), "Lux Fedelis": (3, 8), gname: (17, 10)}.items():
    call("POST", f"/api/tokens/{toks[n]['id']}/move", {"x": x, "y": y, "free": True})
call("POST", f"/api/campaigns/{camp}/live-map", {"map_id": mid})
call("POST", f"/api/encounters/{eid}/start")
by = {c["name"]: c for c in call("GET", f"/api/encounters/{eid}")["combatants"]}
call("POST", f"/api/encounters/{eid}/set-turn", {"combatant_id": by["Yamato"]["id"]})
call("POST", f"/api/encounters/{eid}/cast", {"caster_id": by["Yamato"]["id"], "spell": echo, "targets": []})
clone_tok = next(t for t in call("GET", f"/api/maps/{mid}")["tokens"] if t["display"].lower().startswith("yamato clone"))
call("POST", f"/api/tokens/{clone_tok['id']}/move", {"x": 12, "y": 5, "free": True})


def at(name):
    t = next(t for t in call("GET", f"/api/maps/{mid}")["tokens"] if t["display"].lower().startswith(name.lower()))
    return (t["x"], t["y"])


def join(p, who, name):
    ctx = p.new_context(viewport={"width": 390, "height": 844}, **engine.mobile(), has_touch=True)
    ph = ctx.new_page(); ph.on("pageerror", lambda e: problems.append(f"{name} phone JS error: {e}"))
    ph.goto(LAN + "/join"); ph.fill("input[name=code]", code); ph.fill("input[name=name]", name)
    ph.wait_for_selector("#char-field:not([hidden])"); ph.select_option("select[name=character_id]", value=str(who["id"]))
    ph.click("button[type=submit]"); ph.wait_for_url(re.compile("/play")); ph.wait_for_timeout(2500)
    return ph


code = call("POST", f"/api/campaigns/{camp}/join-code", {"action": "new"})["join_code"]
with sync_playwright() as p:
    b = engine.launch(p)
    print(f"== [{engine.NAME}] Yamato's phone: no Echo Teleport any more")
    ph = join(b, yam, "Yamato player")
    body = ph.locator("body").inner_text()
    check("Phantasaml force" not in body and "Phantasmal force" not in body and "Echo Teleport" not in body,
          "the phone shows neither Phantasmal force nor Echo Teleport")
    ph.context.close()

    print(f"== [{engine.NAME}] Lux's phone: Mend cantrip")
    call("POST", f"/api/combatants/{by['Lux Fedelis']['id']}/hp", {"op": "damage", "amount": 30})
    hp0 = call("GET", f"/api/characters/{lux['id']}")["character"]["current_hp"]
    call("POST", f"/api/encounters/{eid}/set-turn", {"combatant_id": by["Lux Fedelis"]["id"]})
    lp = join(b, lux, "Colin")
    spells_txt = lp.locator("#me").inner_text()
    check("Mend" in spells_txt.split("Spells", 1)[-1], "Mend is listed under Spells")
    check(re.search(r"Mend[\s\S]{0,80}cantrip", spells_txt, re.I) is not None, "it says cantrip")
    lp.locator(".fight-act", has_text=re.compile(r"^\s*Mend", re.I)).first.click(); lp.wait_for_timeout(600)
    lp.locator(".cast-chip", has_text="Lux").first.click(); lp.wait_for_timeout(300)
    lp.locator("button.cast-go").first.click(); lp.wait_for_timeout(2500)
    hp1 = call("GET", f"/api/characters/{lux['id']}")["character"]["current_hp"]
    check(hp1 >= hp0 + 8, f"Mend healed Lux from the phone ({hp0} -> {hp1})")
    st = lp.evaluate("fetch('/api/play/state').then(r => r.json())")
    m = next(s for s in st["character"]["spells"] if s["name"] == "Mend")
    check(m["recharging"] > 0, "then it's recharging (cooldown kept)")
    lp.screenshot(path=f"{SHOTS}/lab_mend_{engine.NAME}.png")
    lp.context.close()
    call("POST", f"/api/encounters/{eid}/end")

    print(f"== [{engine.NAME}] The DM makes a laboratory")
    dm = b.new_context(viewport={"width": 1366, "height": 900}).new_page()
    dm.on("pageerror", lambda e: problems.append(f"DM JS error: {e}"))
    dm.goto(DM + "/map"); dm.wait_for_timeout(1200)
    labcard = dm.locator("[data-dungeon=lab]")
    check(labcard.count() == 1 and "Laboratory" in labcard.inner_text(), "the Maps page has a Laboratory card")
    labcard.click(); dm.wait_for_url(re.compile(r"/map/\d+")); dm.wait_for_timeout(2000)
    lab1 = int(re.search(r"/map/(\d+)", dm.url).group(1))
    panel = dm.locator("body").inner_text()
    check("Laboratory · floor 1 of 5" in panel, "the panel says Laboratory · floor 1 of 5")
    check("take the party up" in panel, "the lift button goes up")
    m1 = call("GET", f"/api/maps/{lab1}")
    check([c["kind"] for c in m1["map"]["chests"]].count("lab") == 3 and len([c for c in m1["map"]["chests"] if c["kind"] != "papers"]) == 3,
          "floor 1: three supply lockers (and its loose papers)")
    check(all(t["portrait"].startswith("lab-") for t in m1["tokens"] if t["kind"] == "enemy") and any(t["kind"] == "enemy" for t in m1["tokens"]),
          "floor 1 has lab enemies with their pictures")
    dm.wait_for_timeout(3500)  # (after the "new map" intro)
    dm.screenshot(path=f"{SHOTS}/lab_floor1_{engine.NAME}.png")
    cur = lab1
    for _ in range(4):
        cur = call("POST", f"/api/maps/{cur}/next-level")["next_level"]["map_id"]
    top = call("GET", f"/api/maps/{cur}")
    check(top["map"]["dungeon"]["level"] == 5 and top["map"]["dungeon"]["exit"] is None, "floor 5 is the top, no lift")
    kinds = [c["kind"] for c in top["map"]["chests"]]
    check(kinds.count("labprize") == 1 and kinds.count("lab") == 3, "floor 5: three lockers and the safe")
    check(any(t["display"].startswith("Head Researcher") for t in top["tokens"]), "the Head Researcher is on floor 5")
    dm.goto(DM + f"/map/{cur}"); dm.wait_for_timeout(2000)
    panel = dm.locator("body").inner_text()
    check("floor 5 of 5" in panel and "no lift any higher" in panel, "the panel says it's the top floor")
    check(dm.locator("button", has_text="take the party up").count() == 0, "no 'take the party up' button on the top floor")
    dm.wait_for_timeout(3500)
    dm.screenshot(path=f"{SHOTS}/lab_floor5_{engine.NAME}.png")
    safe = next(c for c in top["map"]["chests"] if c["kind"] == "labprize")
    rolled = call("POST", f"/api/chests/{safe['id']}/roll")
    items = next(c for c in rolled["map"]["chests"] if c["id"] == safe["id"]).get("loot") or []
    check(len(items) == 1 and items[0].get("magic") and items[0]["rarity"] == "rare", f"the safe holds one rare magic item ({items[0]['name'] if items else '-'})")
    b.close()

check(not problems, "no page errors" + ("" if not problems else ": " + "; ".join(problems[:3])))
print(f"e2e_lab_teleport.py [{engine.NAME}]: {sum(1 for ok, _ in results if ok)} passed, {sum(1 for ok, _ in results if not ok)} failed")
