"""E2E: sheet sections fold; Yamato gets Action Surge and uses it in a fight."""
import json, re, urllib.request, uuid
from common import APP_DIR, DM_URL, LAN_IP, LAN_URL, SHOTS_DIR, TMP_DIR  # noqa: E402,F401  (paths and addresses for this computer)
from playwright.sync_api import sync_playwright

DM = DM_URL
SHOTS = SHOTS_DIR + r"\fold"
results, problems = [], []


def call(m, path, body=None):
    data = json.dumps(dict(body or {}, op_id=uuid.uuid4().hex)).encode() if m != "GET" else None
    return json.load(urllib.request.urlopen(urllib.request.Request(DM + path, data=data, method=m, headers={"Content-Type": "application/json"})))


def check(c, msg):
    results.append((bool(c), msg)); print(("  PASS " if c else "  FAIL ") + msg, flush=True)


def folded(pg, k):
    return pg.locator(f'[data-fold="{k}"]').get_attribute("aria-expanded") == "false" and pg.locator(f'[data-fold-body="{k}"]').first.is_hidden()


YAM, GN = 3, 4
with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    ctx = b.new_context(viewport={"width": 1440, "height": 1000})
    pg = ctx.new_page()
    pg.on("pageerror", lambda e: problems.append(f"JS error: {e}"))
    pg.on("console", lambda m: m.type == "error" and "Failed to load resource" not in m.text and problems.append(f"console: {m.text}"))

    print("== A fresh sheet starts short")
    pg.goto(f"{DM}/characters/{GN}"); pg.wait_for_selector("#attacks tbody tr")
    for k in ("skills", "features", "proficiencies", "equipment", "notes"):
        check(folded(pg, k), f"{k} starts folded")
    for k in ("saves", "attacks", "spells"):
        check(not folded(pg, k), f"{k} starts open")
    print("    hints:", {k: pg.locator(f"#{k}-hint").inner_text() for k in ("skills", "equipment", "features", "notes")})
    check(pg.locator("#equipment-hint").inner_text().endswith("items") or pg.locator("#equipment-hint").inner_text().endswith("item"), "folded Equipment says how many items")
    h_short = pg.evaluate("document.body.scrollHeight")
    pg.screenshot(path=SHOTS + r"\sheet_folded.png", full_page=True)

    print("== Click headings to open and fold")
    pg.locator('[data-fold="skills"]').click(); pg.wait_for_timeout(200)
    check(not folded(pg, "skills") and pg.locator("#skills li").first.is_visible(), "clicking Skills opens it")
    pg.locator("[data-roll='skill:athletics']").click(); pg.wait_for_timeout(2200)
    last = call("GET", f"/api/rolls?character_id={GN}&limit=1")["rolls"][0]
    check(last["label"] == "Athletics check", "a skill rolls once opened")
    if pg.locator("#dice-dock.is-open").count():
        pg.click("#dice-close")
    pg.locator('[data-fold="attacks"]').click(); pg.wait_for_timeout(200)
    check(folded(pg, "attacks") and "attack" in pg.locator("#attacks-hint").inner_text(), "Attacks folds and says how many")
    pg.locator('[data-fold="attacks"]').click(); pg.wait_for_timeout(200)
    pg.keyboard.press("Tab")
    pg.locator('[data-fold="features"]').focus(); pg.keyboard.press("Enter"); pg.wait_for_timeout(200)
    check(not folded(pg, "features"), "Enter on a focused heading opens it (keyboard)")
    # Notes' Edit button works without folding the heading
    pg.locator('[data-fold="notes"]').click(); pg.wait_for_timeout(200)
    open_before = not folded(pg, "notes")
    pg.locator("#edit-notes").click(); pg.wait_for_timeout(400)
    check(open_before and not folded(pg, "notes"), "the Notes Edit button doesn't fold the section")
    pg.keyboard.press("Escape")
    pg.locator('[data-tab="main"]').click(); pg.wait_for_timeout(300)

    print("== Remembered: reload, and another character's sheet")
    pg.goto(f"{DM}/characters/{GN}"); pg.wait_for_selector("#attacks tbody tr")
    check(not folded(pg, "skills") and not folded(pg, "features"), "after a reload, Skills and Features stay open")
    pg.locator('[data-fold="skills"]').click(); pg.locator('[data-fold="features"]').click(); pg.locator('[data-fold="notes"]').click(); pg.wait_for_timeout(200)
    pg.goto(f"{DM}/characters/{YAM}"); pg.wait_for_selector("#attacks tbody tr")
    check(folded(pg, "skills") and folded(pg, "features"), "the same folds on Yamato's sheet")

    print("== Yamato: add Action Surge by clicking")
    pg.locator("#attacks").get_by_role("button", name=re.compile("Add attack")).click(); pg.wait_for_timeout(300)
    row = pg.locator("#attacks tbody tr").last
    row.locator("td.f-name textarea").fill("Action Surge")
    row.locator("td.f-notes textarea").fill("Two extra moves this turn")
    row.locator("td.f-extra_moves input").fill("2")
    row.locator("td.f-cooldown input").fill("3")
    pg.wait_for_timeout(2500)
    y = call("GET", f"/api/characters/{YAM}")["character"]
    r = next((a for a in y["attacks"] if a["name"] == "Action Surge"), {})
    check(r.get("extra_moves") == 2 and r.get("cooldown") == 3, f"Yamato's Action Surge saved ({r})")
    check({"Phantasaml force", "Wide Slash", "Parry", "Echo Knight"} <= {s["name"] for s in y["spells"]} and any(a["name"].strip() == "Slash" for a in y["attacks"]), "his other moves and spells are untouched")

    print("== Yamato uses it in a fight")
    for e in call("GET", "/api/campaigns/1/encounters")["encounters"]:  # a fresh fight: nothing recharging from another
        if e["status"] == "active":
            call("POST", f"/api/encounters/{e['id']}/end")
    eid = call("POST", "/api/campaigns/1/encounters", {"name": "Yamato surge"})["encounter"]["id"]
    st = call("POST", f"/api/encounters/{eid}/combatants", {"characters": [YAM], "quick": {"name": "Goblin", "max_hp": 50, "ac": 3, "count": 1}})
    by = {c["name"]: c for c in st["combatants"]}
    call("POST", f"/api/encounters/{eid}/start"); call("POST", f"/api/encounters/{eid}/set-turn", {"combatant_id": by["Yamato"]["id"]})
    pg.goto(f"{DM}/combat/{eid}"); pg.wait_for_timeout(1000)
    pg.locator("#init-list li.combatant").filter(has_text="Yamato").locator(".c-name").click(); pg.wait_for_timeout(300)
    pg.locator("#detail").get_by_role("button", name=re.compile(r"Use · \+2 moves")).first.click(); pg.wait_for_timeout(1000)
    check("2 extra moves left" in pg.locator("#init-list li.combatant").filter(has_text="Yamato").inner_text(), "Yamato: Action Surge · 2 extra moves left")
    b.close()

fails = [m for ok, m in results if not ok]
print(f"\n{len(results) - len(fails)} passed, {len(fails)} failed"); [print("FAILED:", f) for f in fails]
print("PROBLEMS:", problems)
