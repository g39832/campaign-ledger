"""E2E: a map made on its own, then linked to a fight in Map & grid settings, gets a token for
everyone in that fight. A boss can't be added to a fight twice, and the boss bar shows no HP."""
import json, re, urllib.error, urllib.request, uuid
from common import APP_DIR, DM_URL, LAN_IP, LAN_URL, SHOTS_DIR, TMP_DIR  # noqa: E402,F401  (paths and addresses for this computer)
from playwright.sync_api import sync_playwright
import engine

DM = DM_URL
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
chars = {c["name"]: c for c in call("GET", f"/api/campaigns/{camp}/characters")["characters"]}
harlan = next(c for c in call("GET", "/api/creatures")["creatures"] if c["name"] == "Harlan Voss")
eid = call("POST", f"/api/campaigns/{camp}/encounters", {"name": "Link test"})["encounter"]["id"]
call("POST", f"/api/encounters/{eid}/combatants", {"characters": [chars["Moni Easter"]["id"], chars["Lux Fedelis"]["id"]],
                                                   "quick": {"name": "Goblin", "max_hp": 7, "ac": 13, "count": 2}})
call("POST", f"/api/encounters/{eid}/combatants", {"creature_id": harlan["id"], "count": 1})
try:
    call("POST", f"/api/encounters/{eid}/combatants", {"creature_id": harlan["id"], "count": 1})
    check(False, "adding Harlan a second time is refused")
except urllib.error.HTTPError as e:
    check(e.code == 400 and "already in this fight" in e.read().decode(), "adding Harlan a second time is refused")
mid = call("POST", f"/api/campaigns/{camp}/maps", {"name": "Link test map", "cols": 16, "rows": 10})["map"]["id"]

with sync_playwright() as p:
    b = engine.launch(p)
    pg = b.new_page(viewport={"width": 1400, "height": 950}); pg.on("pageerror", lambda e: problems.append(f"DM JS error: {e}"))
    pg.goto(f"{DM}/map/{mid}"); pg.wait_for_timeout(1500)
    check(call("GET", f"/api/maps/{mid}")["tokens"] == [], "the new map starts empty")
    pg.locator("select[data-m=encounter_id]").select_option(str(eid)); pg.wait_for_timeout(2500)
    toks = sorted(t["display"] for t in call("GET", f"/api/maps/{mid}")["tokens"])
    check(toks == ["Goblin 1", "Goblin 2", "Harlan Voss", "Lux Fedelis", "Moni Easter"], f"linking the fight puts everyone in it on the map ({toks})")
    check(pg.locator("#tokens li").count() == 5, "and the token list shows them without a reload")
    call("POST", f"/api/encounters/{eid}/start"); pg.reload(); pg.wait_for_timeout(2000)  # the boss bar shows in a running fight
    bar = pg.locator("#boss-bar")
    check(bar.count() == 1 and "Harlan Voss" in bar.inner_text() and "HP" not in bar.inner_text() and "/" not in bar.inner_text(),
          f"the boss bar names Harlan but shows no HP ({bar.inner_text() if bar.count() else ''!r})")
    pg.screenshot(path=SHOTS + rf"\linkmap_{engine.NAME}.png")
    pg.goto(f"{DM}/combat/{eid}"); pg.wait_for_timeout(1500)
    cbar = pg.locator("#boss-bar")
    check(cbar.count() == 1 and "HP" not in cbar.inner_text(), "no HP on the Combat page's boss bar either")
    b.close()
fails = [m for ok, m in results if not ok]
print(f"\n{len(results) - len(fails)} passed, {len(fails)} failed"); [print("FAILED:", f) for f in fails]
print("PROBLEMS:", problems)
