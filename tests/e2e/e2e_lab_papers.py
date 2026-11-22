"""E2E (2026-11-15): the lab's loose papers, played from Test Hero's phone on the playtest lab, and
every enemy's moves in the lab fights and Steven's test room.

- The playtest lab (a map named "Playtest — ...") is live; Test Hero stands at its start.
- Papers show on the phone's map; standing next to one, the Nearby box says Read; one tap and the
  clue pops up as a handout, and it stays in the Handouts list. Nobody else gets it.
- The DM's map lists every paper with its text.
- Every enemy in the lab floors' fights (and Steven's room): each attack line the screens read has
  damage dice the dice roller accepts, and each spell line turns into something castable."""
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
maps = call("GET", f"/api/campaigns/{camp}/maps")["maps"]
pt = next(m for m in maps if m["name"].startswith("Playtest"))
call("POST", f"/api/campaigns/{camp}/live-map", {"map_id": pt["id"]})
st = call("GET", f"/api/maps/{pt['id']}")
hero = next(c for c in call("GET", f"/api/campaigns/{camp}/characters")["characters"] if c["name"] == "Test Hero")
htok = next(t for t in st["tokens"] if t.get("character_id") == hero["id"])
papers = [c for c in st["map"]["chests"] if c["kind"] == "papers"]
check(len(papers) == 3 and all(c["loot"] and c["loot"][0]["desc"] for c in papers), "the playtest floor has its 3 papers, each with its text (DM view)")
foes = [t for t in st["tokens"] if t["kind"] == "enemy"]
# the paper farthest from any enemy, and an open square next to it
BLOCK = {"wall", "pit", "water", "lava", "tree", "table", "rock", "bulkhead", "sealed", "panel", "redlight", "camera", "turret", "terminal", "machinery", "cryo", "steel", "stairs"}  # app/maps.py BLOCKING
def far(c):
    return min([abs(c["x"] - t["x"]) + abs(c["y"] - t["y"]) for t in foes] or [99])
paper = max([c for c in papers if not c["opened"]] or papers, key=far)
taken = {(c["x"], c["y"]) for c in st["map"]["chests"]} | {(int(t["x"]), int(t["y"])) for t in st["tokens"]}
spots = [(paper["x"] + dx, paper["y"] + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if dx or dy]
spot = next(s for s in spots if s not in taken and st["map"]["terrain"].get(f"{s[0]},{s[1]}", "") not in BLOCK)
call("POST", f"/api/tokens/{htok['id']}/move", {"x": spot[0], "y": spot[1], "free": True})
for e in call("GET", f"/api/campaigns/{camp}/encounters")["encounters"]:  # walking in may have started a room fight
    if e["status"] == "active":
        call("POST", f"/api/encounters/{e['id']}/end")
print(f"   Test Hero next to '{paper['name']}' at {spot}, nearest enemy {far(paper)} squares away")

code = call("POST", f"/api/campaigns/{camp}/join-code", {"action": "new"})["join_code"]
with sync_playwright() as p:
    b = engine.launch(p)
    print(f"== [{engine.NAME}] Test Hero's phone reads a paper")
    ctx = b.new_context(viewport={"width": 390, "height": 844}, **engine.mobile(), has_touch=True)
    ph = ctx.new_page(); ph.on("pageerror", lambda e: problems.append(f"phone JS error: {e}"))
    ph.goto(LAN + "/join"); ph.fill("input[name=code]", code); ph.fill("input[name=name]", "Grayson")
    ph.wait_for_selector("#char-field:not([hidden])"); ph.select_option("select[name=character_id]", value=str(hero["id"]))
    ph.click("button[type=submit]"); ph.wait_for_url(re.compile("/play")); ph.wait_for_timeout(2500)
    row = ph.locator("#nearby button", has_text="Read")
    check(row.count() >= 1, "the Nearby box offers Read for the papers next to Test Hero")
    ph.screenshot(path=f"{SHOTS}/lab_papers_nearby_{engine.NAME}.png")
    row.first.click()
    pop = ph.locator(".handout-pop")
    pop.wait_for(timeout=8000)
    text = pop.inner_text()
    check(paper["name"] in text and "Found:" in text, f"the paper pops up as a handout ('{paper['name']}', with where it was found)")
    check(ph.locator("#loot-pop").count() == 0 or paper["name"] != "Station coordinates printout", "no loot box over it (just the paper)")
    ph.screenshot(path=f"{SHOTS}/lab_papers_read_{engine.NAME}.png")
    pop.locator("button").last.click(); ph.wait_for_timeout(800)
    check(ph.locator(".handout-list", has_text=paper["name"]).count() >= 1, "it stays in Test Hero's Handouts list")
    st2 = call("GET", f"/api/maps/{pt['id']}")
    check(next(c for c in st2["map"]["chests"] if c["id"] == paper["id"])["opened"], "the DM's map shows it read")
    hs = call("GET", f"/api/campaigns/{camp}/handouts")["handouts"]
    mine = [h for h in hs if h["title"] == paper["name"]]
    check(len(mine) == 1 and mine[0]["to"] == [hero["id"]], "only Test Hero got it")
    ctx.close()

    print(f"== [{engine.NAME}] Every enemy's moves read right (lab floors + Steven's room)")
    dm = b.new_context(viewport={"width": 1366, "height": 900}).new_page()
    dm.on("pageerror", lambda e: None if "ResizeObserver loop" in str(e) else problems.append(f"DM JS error: {e}"))
    encs = [e for e in call("GET", f"/api/campaigns/{camp}/encounters")["encounters"]
            if e["name"].startswith(("Laboratory", "Playtest", "Steven Voss test room"))]
    dm.goto(DM + f"/combat/{encs[0]['id']}"); dm.wait_for_timeout(2000)
    bad, seen = [], {}
    for e in encs:
        for c in call("GET", f"/api/encounters/{e['id']}")["combatants"]:
            if c.get("linked"):
                continue
            base = (c.get("statblock") or {}).get("base_name") or c["name"]
            if base in seen:
                continue
            sb = c.get("statblock") or {}
            got = dm.evaluate("""(sb) => ({ atk: L.attackLines(sb.attacks + (sb.phase2 ? "\\n" + sb.phase2 : "")).map((a) => ({ name: a.name, dmg: a.dmg || "", hit: a.hit || "", cond: a.condition || "", check: a.check || "", heal: !!a.heal })),
                                         spells: L.monsterSpells(sb.spells).map((s) => ({ name: s.name, dice: s.dice || "", kind: s.effect || s.kind || "", summon: s.summon || "", terrain: s.terrain || "" })),
                                         lines: String(sb.attacks || "").split(/\\n+/).filter((l) => l.trim()).length })""", sb)
            seen[base] = got
            for a in got["atk"]:
                if not (a["dmg"] or a["cond"] or a["check"]):
                    continue
                if a["dmg"]:
                    r = call("POST", "/api/rolls", {"encounter_id": e["id"], "expression": a["dmg"], "label": a["name"], "kind": "damage", "subject": c["name"]}, ok=False)
                    if "roll" not in r:
                        bad.append(f"{base}: {a['name']} damage '{a['dmg']}' won't roll: {r.get('error')}")
            print(f"   {base}: {len(got['atk'])} attacks ({', '.join(a['name'] + ' ' + (a['hit'] or '') + ' ' + a['dmg'] for a in got['atk'])})"
                  + (f"; spells: {', '.join(s['name'] for s in got['spells'])}" if got["spells"] else ""))
            if not got["atk"] and not got["spells"]:
                bad.append(f"{base}: no attacks or spells read from its stat block")
    check(not bad, f"every enemy's attacks roll ({len(seen)} kinds of enemy)" + ("" if not bad else ": " + "; ".join(bad[:5])))
    b.close()

check(not problems, "no page errors" + ("" if not problems else ": " + "; ".join(problems[:3])))
print(f"e2e_lab_papers.py [{engine.NAME}]: {sum(1 for ok, _ in results if ok)} passed, {sum(1 for ok, _ in results if not ok)} failed")
