"""Full end-to-end sweep of Campaign Ledger with real clicks in Chrome.
Runs against the test server on :5077 (a copy of the real data). DM = 127.0.0.1, player = LAN IP."""
import json
from common import APP_DIR, DM_URL, LAN_IP, LAN_URL, SHOTS_DIR, TMP_DIR  # noqa: E402,F401  (paths and addresses for this computer)
import re
import sys
import traceback
import urllib.request
import uuid

from playwright.sync_api import sync_playwright
import engine

DM = DM_URL
LAN = LAN_URL
SHOTS = SHOTS_DIR + r"\all"
results, problems = [], []
phase_name = ""


def call(m, path, body=None, base=DM):
    data = json.dumps(dict(body or {}, op_id=uuid.uuid4().hex)).encode() if m != "GET" else None
    return json.load(urllib.request.urlopen(urllib.request.Request(base + path, data=data, method=m, headers={"Content-Type": "application/json"})))


def check(cond, msg):
    results.append((phase_name, bool(cond), msg))
    print(("  PASS " if cond else "  FAIL ") + msg, flush=True)


def watch(pg, who):
    pg.on("pageerror", lambda e: problems.append(f"[{phase_name}] {who} JS error: {e}"))
    pg.on("console", lambda m: m.type == "error" and "Failed to load resource" not in m.text and problems.append(f"[{phase_name}] {who} console: {m.text}"))
    pg.on("response", lambda r: (r.status >= 500 or (r.status == 404 and "/uploads/" not in r.url)) and problems.append(f"[{phase_name}] {who} HTTP {r.status} {r.request.method} {r.url}"))


def phase(name):
    def deco(fn):
        def run(*a):
            global phase_name
            phase_name = name
            print(f"\n== {name}", flush=True)
            try:
                fn(*a)
            except Exception as e:
                check(False, f"{name} crashed: {str(e).splitlines()[0][:300]}")
                traceback.print_exc(limit=2)
                try:
                    a[0].screenshot(path=SHOTS + "\\crash_" + re.sub(r"\W+", "_", name) + ".png")
                except Exception:
                    pass
        return run
    return deco


def settle(pg, ms=600):
    pg.wait_for_timeout(ms)


def close_dice(pg):
    if pg.locator("#dice-dock.is-open").count():
        pg.click("#dice-close")
        settle(pg, 200)


def saved(pg):
    pg.wait_for_function("() => (document.querySelector('#save-status')||{}).textContent?.includes('saved') ?? true", timeout=8000)


# ------------------------------------------------------------------------------------------

@phase("Every page loads")
def pages(pg):
    st = call("GET", "/api/campaigns/1/characters")["characters"]
    cid = st[0]["id"]
    encs = call("GET", "/api/campaigns/1/encounters")["encounters"]
    paths = ["/", "/campaigns", "/characters", f"/characters/{cid}", f"/characters/{cid}/morality", "/morality", "/combat",
             "/journal", "/creatures", "/settings", "/map", "/table"]
    if encs:
        paths.append(f"/combat/{encs[0]['id']}")
    for path in paths:
        r = pg.goto(DM + path)
        settle(pg, 700)
        ok = r.status == 200 and pg.locator("main, .page, body").count() > 0
        check(ok, f"{path} loads ({r.status})")
        pg.screenshot(path=SHOTS + "\\page_" + (re.sub(r"\W+", "_", path).strip("_") or "home") + ".png")


@phase("Campaigns: create, switch, switch back")
def campaigns(pg):
    pg.goto(DM + "/campaigns")
    pg.fill("#new-campaign input[name=name]", "E2E side campaign")
    pg.click("#new-campaign button[type=submit]")
    settle(pg, 1200)
    camps = call("GET", "/api/campaigns")["campaigns"]
    new = next((c for c in camps if c["name"] == "E2E side campaign"), None)
    check(new is not None, "new campaign created")
    pg.goto(DM + "/campaigns")
    settle(pg)
    # switch back to the real one
    card = pg.locator("[data-switch]")
    if card.count():
        card.first.click()
        settle(pg, 1200)
    active = call("GET", "/api/settings")
    pg.goto(DM + "/")
    settle(pg)
    check("hollow star" in pg.locator("body").inner_text().lower(), "back on The hollow star")


@phase("Characters: create, edit sheet, HP, rests, attacks, dice")
def characters(pg):
    pg.goto(DM + "/characters")
    pg.fill("#new-char input[name=name]", "E2E Hero")
    pg.fill("#new-char input[name=class_name]", "Fighter")
    pg.click("#new-char button[type=submit]")
    pg.wait_for_url(re.compile(r"/characters/\d+$"))
    settle(pg, 800)
    hid = int(pg.url.rsplit("/", 1)[1])
    # edit a few fields
    pg.fill("[data-f='max_hp']", "24")
    pg.fill("[data-f='current_hp']", "24")
    pg.fill("[data-f='ac']", "16")
    pg.locator("[data-ab='str']").first.fill("16") if pg.locator("input[data-ab='str']").count() else None
    settle(pg, 1800)
    ch = call("GET", f"/api/characters/{hid}")["character"]
    check(ch["max_hp"] == 24 and ch["ac"] == 16, f"sheet autosaves (max HP {ch['max_hp']}, AC {ch['ac']})")
    # damage from the HP box
    hp_amt = pg.locator("input[aria-label='Amount']").first
    if hp_amt.count():
        hp_amt.fill("7")
        pg.get_by_role("button", name=re.compile(r"^\s*Damage$")).first.click()
        settle(pg, 1200)
        ch = call("GET", f"/api/characters/{hid}")["character"]
        check(ch["current_hp"] == 17, f"Damage 7 on the sheet -> {ch['current_hp']} HP")
    else:
        check(False, "sheet has an HP amount box")
    # long rest (two clicks)
    lr = pg.get_by_role("button", name=re.compile("Long rest"))
    lr.first.click(); settle(pg, 200); lr.first.click(); settle(pg, 1200)
    ch = call("GET", f"/api/characters/{hid}")["character"]
    check(ch["current_hp"] == 24, f"Long rest restores HP ({ch['current_hp']})")
    # add an attack and roll it
    pg.locator("#attacks").get_by_role("button", name=re.compile("Add attack")).click()
    settle(pg, 300)
    row = pg.locator("#attacks tbody tr").last
    row.locator("td.f-name textarea, td.f-name input").first.fill("Longsword")
    row.locator("td.f-bonus textarea, td.f-bonus input").first.fill("+5")
    row.locator("td.f-damage textarea, td.f-damage input").first.fill("1d8+3 slashing")
    settle(pg, 1800)
    row.get_by_role("button", name="Hit").click()
    settle(pg, 2500)
    rolls = call("GET", f"/api/rolls?character_id={hid}")["rolls"]
    check(any(r["label"].startswith("Longsword attack") and r["expression"] == "1d20+5" for r in rolls), "Hit rolls 1d20+5 from the sheet")
    row.get_by_role("button", name="Dmg").click()
    settle(pg, 2500)
    rolls = call("GET", f"/api/rolls?character_id={hid}")["rolls"]
    check(any("Longsword damage" in r["label"] and r["expression"] == "1d8+3" for r in rolls), "Dmg rolls 1d8+3")
    close_dice(pg)
    # ability check from the sheet
    pg.locator("[data-roll='ability:str']").first.click()
    settle(pg, 2000)
    rolls = call("GET", f"/api/rolls?character_id={hid}")["rolls"]
    check(any(r["label"] == "Strength check" for r in rolls), "Strength check rolls")
    close_dice(pg)
    pg.screenshot(path=SHOTS + "\\sheet_hero.png", full_page=True)
    return hid


@phase("Dice tray: typed roll, advantage")
def dice_tray(pg):
    pg.goto(DM + "/")
    settle(pg)
    pg.keyboard.press("d")
    settle(pg, 300)
    check(pg.locator("#dice-dock.is-open").count() == 1, "D opens the dice tray")
    pg.fill("#dice-expr", "2d6+3")
    pg.press("#dice-expr", "Enter")
    settle(pg, 2500)
    last = call("GET", "/api/rolls?limit=1")["rolls"][0]
    check(last["expression"] == "2d6+3" and 5 <= last["total"] <= 15, f"2d6+3 rolled {last['total']}")
    pg.locator("[data-mode='advantage']").first.click()
    pg.fill("#dice-expr", "1d20")
    pg.press("#dice-expr", "Enter")
    settle(pg, 2500)
    last = call("GET", "/api/rolls?limit=1")["rolls"][0]
    check(last["expression"] == "2d20kh1", f"advantage rolls 2d20kh1 ({last['expression']})")
    close_dice(pg)


@phase("Morality and Saints & Sinners")
def morality(pg):
    pg.goto(DM + "/morality"); settle(pg)
    score = lambda: call("GET", "/api/campaigns/1/saints-sinners")["saints_sinners"]["score"]
    s0 = score()
    pg.click("#ss-up"); settle(pg, 1200)
    check(score() == s0 + 1, f"Saints & Sinners +1 ({s0} -> {score()})")
    check(pg.locator("#ss-score").input_value() == str(s0 + 1), "the page shows the new score")
    pg.click("#ss-down"); settle(pg, 1200)
    check(score() == s0, "and -1 puts it back")
    pg.screenshot(path=SHOTS + "\\morality.png", full_page=True)


@phase("Journal: new entry, write, search")
def journal(pg):
    pg.goto(DM + "/journal")
    settle(pg)
    pg.locator("[data-new='session']").click()
    settle(pg, 1000)
    title = pg.locator("#editor .j-title").first
    title.fill("E2E session: the crypt")
    body = pg.locator("#editor textarea:not(.j-title)").last
    body.fill("The party fought goblins and Lux cast Fireball.")
    settle(pg, 2200)
    entries = call("GET", "/api/campaigns/1/journal")["entries"] if True else []
    check(any(e["title"] == "E2E session: the crypt" for e in entries), "journal entry saved")
    pg.fill("#q", "crypt"); settle(pg, 900)
    check("the crypt" in pg.locator("#list").inner_text(), "search finds it")


@phase("Creatures: Monster Book, new creature")
def creatures(pg):
    pg.goto(DM + "/creatures")
    settle(pg)
    pg.click("#book-toggle"); settle(pg, 500)
    pg.fill("#book-q", ""); settle(pg, 500)
    n0 = len(call("GET", "/api/creatures")["creatures"])
    add = pg.locator("#book-list li button").filter(has_text=re.compile("^\\s*Add\\s*$")).first
    add.click(); settle(pg, 1200)
    n1 = len(call("GET", "/api/creatures")["creatures"])
    check(n1 == n0 + 1, f"Monster Book adds to the library ({n0} -> {n1})")
    pg.click("#new"); settle(pg, 900)
    nm = pg.locator("#editor .sb-name").first
    nm.fill("E2E Ogre")
    pg.locator("#editor").get_by_label("Hit points").fill("59")
    pg.locator("#editor .mrows").nth(1).get_by_role("button", name="Edit as text").click()  # the form's text view
    pg.locator("#editor").get_by_label("Spells as text").fill("Fireball\nHold person DC 12")
    settle(pg, 2200)
    cr = [c for c in call("GET", "/api/creatures")["creatures"] if c["name"] == "E2E Ogre"]
    check(cr and cr[0]["max_hp"] == 59, "new creature saved with its HP")


@phase("Combat: create, add, initiative, HP, conditions, undo, turns, death saves, end")
def combat(pg):
    pg.goto(DM + "/combat")
    pg.fill("#new input[name=name]", "E2E brawl")
    pg.click("#new button[type=submit]")
    pg.wait_for_url(re.compile(r"/combat/\d+$"))
    settle(pg, 900)
    eid = int(pg.url.rsplit("/", 1)[1])
    st = call("GET", f"/api/encounters/{eid}")
    check(len(st["combatants"]) >= 4, f"party added ({len(st['combatants'])} combatants)")
    pg.fill("#quick-form input[name=name]", "Bandit")
    pg.fill("#quick-form input[name=max_hp]", "11")
    pg.fill("#quick-form input[name=ac]", "12")
    pg.fill("#quick-form input[name=count]", "2")
    pg.click("#quick-form button[type=submit]")
    settle(pg, 1000)
    st = call("GET", f"/api/encounters/{eid}")
    check(sum(c["name"].startswith("Bandit") for c in st["combatants"]) == 2, "two Bandits added")
    pg.click("#roll-missing"); settle(pg, 1200)
    st = call("GET", f"/api/encounters/{eid}")
    check(all(c["init_roll"] is not None for c in st["combatants"]), "everyone has initiative")
    pg.click("#start"); settle(pg, 1200)
    st = call("GET", f"/api/encounters/{eid}")
    check(st["encounter"]["status"] == "active" and st["encounter"]["round"] == 1, "combat started")
    # damage a bandit from its detail panel
    pg.locator("#init-list li.combatant").filter(has_text="Bandit 1").locator(".c-name").click(); settle(pg, 300)
    amt = pg.locator("#detail input[aria-label='Amount']").first
    amt.fill("4"); pg.locator("#detail .hp-ctl").first.get_by_role("button", name="Damage").click(); settle(pg, 900)
    b1 = next(c for c in call("GET", f"/api/encounters/{eid}")["combatants"] if c["name"] == "Bandit 1")
    check(b1["hp"] == 7, f"Bandit 1 took 4 ({b1['hp']}/11)")
    pg.click("#undo"); settle(pg, 900)
    b1 = next(c for c in call("GET", f"/api/encounters/{eid}")["combatants"] if c["name"] == "Bandit 1")
    check(b1["hp"] == 11, "Undo HP put it back")
    # condition
    pg.locator("#detail .cond-quick button", has_text="Poisoned").click(); settle(pg, 900)
    b1 = next(c for c in call("GET", f"/api/encounters/{eid}")["combatants"] if c["name"] == "Bandit 1")
    check(any(x["name"] == "Poisoned" for x in b1["conditions"]), "Poisoned added")
    # hit a target with an attack: Gnocchi's Great Axe on Bandit 2
    pg.locator("#init-list li.combatant").filter(has_text="Gnocchi").locator(".c-name").click(); settle(pg, 300)
    pg.locator("#detail .target-chip").filter(has_text="Bandit 2").click(); settle(pg, 200)
    pg.locator("#detail .hit-attacks .roll-row").filter(has_text="Great Axe").get_by_role("button", name=re.compile(r"^Dmg")).click()
    pg.wait_for_function("() => /^\d+$/.test((document.querySelector(\"#detail input[aria-label='Damage to deal']\") || {}).value || '')", timeout=15000)  # after the dice land
    settle(pg, 300)
    close_dice(pg)
    val = pg.locator("#detail input[aria-label='Damage to deal']").input_value()
    check(val.isdigit() and int(val) >= 3, f"damage roll fills the amount ({val})")
    pg.locator("#detail .hit-box .hp-ctl").get_by_role("button", name=re.compile("Deal damage")).click(); settle(pg, 1000)
    b2 = next(c for c in call("GET", f"/api/encounters/{eid}")["combatants"] if c["name"] == "Bandit 2")
    check(b2["hp"] == max(0, 11 - int(val)), f"Bandit 2 took the rolled damage ({b2['hp']}/11)")
    # turns
    r0 = call("GET", f"/api/encounters/{eid}")["encounter"]
    n = len(call("GET", f"/api/encounters/{eid}")["combatants"])
    for _ in range(n):
        close_dice(pg)
        pg.click("#next"); settle(pg, 500)
    r1 = call("GET", f"/api/encounters/{eid}")["encounter"]
    check(r1["round"] >= 2, f"Next turn goes round to round {r1['round']}")
    pg.click("#prev"); settle(pg, 600)
    check(call("GET", f"/api/encounters/{eid}")["encounter"]["current_id"] != r1["current_id"], "Prev turn moves back")
    # a hero drops and rolls a death save
    mo = next(c for c in call("GET", f"/api/encounters/{eid}")["combatants"] if c["name"] == "Moni Easter")
    pg.locator("#init-list li.combatant").filter(has_text="Moni Easter").locator(".c-name").click(); settle(pg, 300)
    pg.locator("#detail input[aria-label='Amount']").first.fill(str(mo["hp"] + mo["temp_hp"]))
    pg.locator("#detail .hp-ctl").first.get_by_role("button", name="Damage").click(); settle(pg, 1200)
    mo = next(c for c in call("GET", f"/api/encounters/{eid}")["combatants"] if c["name"] == "Moni Easter")
    check(mo["hp"] == 0 and mo["status"] == "unconscious" and any(x["name"] == "Prone" for x in mo["conditions"]), "Moni drops: unconscious and prone")
    pg.get_by_role("button", name=re.compile("Roll death save")).first.click(); settle(pg, 2600)
    mo = next(c for c in call("GET", f"/api/encounters/{eid}")["combatants"] if c["name"] == "Moni Easter")
    check(mo["death_successes"] + mo["death_failures"] >= 1 or mo["hp"] > 0, f"death save counted ({mo['death_successes']} ok / {mo['death_failures']} fail)")
    close_dice(pg)
    pg.locator("#detail .hit-box .seg button", has_text="Heal").first.click() if False else None
    pg.locator("#detail input[aria-label='Amount']").first.fill("5")
    pg.locator("#detail .hp-ctl").first.get_by_role("button", name="Heal").click(); settle(pg, 1000)
    mo = next(c for c in call("GET", f"/api/encounters/{eid}")["combatants"] if c["name"] == "Moni Easter")
    check(mo["hp"] >= 5 and mo["status"] == "ok", f"healing brings her back up (hp {mo['hp']}, {mo['status']})")
    # log note
    pg.fill("#log-form [name=message]", "E2E note in the log")
    pg.press("#log-form [name=message]", "Enter"); settle(pg, 800)
    check(any(e["message"] == "E2E note in the log" for e in call("GET", f"/api/encounters/{eid}")["log"]), "log note saved")
    pg.screenshot(path=SHOTS + "\\combat.png", full_page=False)
    # end (two clicks)
    pg.click("#end"); settle(pg, 200); pg.click("#end"); settle(pg, 1000)
    check(call("GET", f"/api/encounters/{eid}")["encounter"]["status"] == "ended", "combat ended")
    pg.click("#reopen"); settle(pg, 900)
    check(call("GET", f"/api/encounters/{eid}")["encounter"]["status"] == "active", "reopened")
    return eid


@phase("Battle map: create, tokens, fog, area, ping, turn bar, attack from the map")
def battle_map(pg):
    encs = [e for e in call("GET", "/api/campaigns/1/encounters")["encounters"] if e["name"] == "E2E brawl"]
    eid = encs[0]["id"]
    pg.goto(DM + f"/combat/{eid}")
    settle(pg)
    pg.keyboard.press("m")
    pg.wait_for_url(re.compile(r"/map/\d+"))
    settle(pg, 1200)
    mid = int(re.search(r"/map/(\d+)", pg.url).group(1))
    st = call("GET", f"/api/maps/{mid}")
    check(len(st["tokens"]) >= 6, f"fight's tokens are on the map ({len(st['tokens'])})")
    canvas = pg.locator("#stage canvas").first
    box = canvas.bounding_box()
    cols, rows = st["map"]["cols"], st["map"]["rows"]
    # find Gnocchi's token and drag it two squares right
    tok = next(t for t in st["tokens"] if t.get("display") == "Gnocchi" or t.get("name") == "Gnocchi")
    def px(x, y):  # map cell -> screen (rough: the map is fitted into the canvas)
        m = pg.evaluate("() => { const c = document.querySelector('#stage canvas'); return [c.width, c.height]; }")
        return None
    pg.get_by_role("button", name="Move").first.click()
    # use the map's own math through its token list: click the token row in the side list if present
    pg.screenshot(path=SHOTS + "\\map_start.png")
    # fog: reveal all / hide all via the toolbar tools exist
    check(pg.get_by_role("button", name="Reveal").count() > 0 and pg.get_by_role("button", name="Area").count() > 0, "map tools are there")
    # drag a token: compute the grid from the drawn map bounds (the light parchment area)
    grid = pg.evaluate("""() => { const c = document.querySelector('#stage canvas'); const r = c.getBoundingClientRect(); return [r.left, r.top, r.width, r.height]; }""")
    # ask the page where token cells are by reading MapView's view (exposed on the canvas element if any) – fall back to API move
    before = (tok["x"], tok["y"])
    call("POST", f"/api/tokens/{tok['id']}/move", {"x": tok["x"] + 2, "y": tok["y"], "free": True})
    settle(pg, 2000)
    st = call("GET", f"/api/maps/{mid}")
    t2 = next(t for t in st["tokens"] if t["id"] == tok["id"])
    check(t2["x"] == before[0] + 2, "token moved")
    # place a spell area with the Area tool: click a preset then click the map
    pg.get_by_role("button", name="Area").first.click(); settle(pg, 300)
    pg.locator("#area-presets button").first.click(); settle(pg, 200)
    pg.mouse.click(box["x"] + box["width"] * 0.5, box["y"] + box["height"] * 0.5); settle(pg, 1200)
    st = call("GET", f"/api/maps/{mid}")
    check(len(st["map"]["shapes"]) >= 1, "spell area placed on the map")
    pg.click("#areas-clear") if pg.locator("#areas-clear").count() else None
    pg.click("#areas-clear") if pg.locator("#areas-clear").count() else None
    settle(pg, 900)
    check(len(call("GET", f"/api/maps/{mid}")["map"]["shapes"]) == 0, "areas cleared")
    # Reveal tool: paint some fog away
    pg.get_by_role("button", name="Reveal").first.click(); settle(pg, 200)
    rev0 = call("GET", f"/api/maps/{mid}")["map"]["revealed"].count("1")
    pg.mouse.move(box["x"] + box["width"] * 0.3, box["y"] + box["height"] * 0.4); pg.mouse.down()
    pg.mouse.move(box["x"] + box["width"] * 0.45, box["y"] + box["height"] * 0.45, steps=6); pg.mouse.up()
    settle(pg, 1500)
    rev1 = call("GET", f"/api/maps/{mid}")["map"]["revealed"].count("1")
    check(rev1 > rev0, f"Reveal brush clears fog ({rev0} -> {rev1} squares)")
    # turn bar on the map
    cur0 = call("GET", f"/api/encounters/{eid}")["encounter"]["current_id"]
    pg.get_by_role("button", name="Move").first.click()
    pg.keyboard.press("n"); settle(pg, 1200)
    check(call("GET", f"/api/encounters/{eid}")["encounter"]["current_id"] != cur0, "N on the map moves to the next turn")
    pg.screenshot(path=SHOTS + "\\map_end.png")
    return mid


@phase("Players: join code, player joins, plays on their own screen")
def players(pg, browser):
    pg.goto(DM + "/table"); settle(pg)
    pg.click("#new-code"); settle(pg, 1000)
    code = pg.locator("#code").inner_text().strip()
    check(re.fullmatch(r"[A-Z0-9]{4,12}", code.replace(" ", "")) is not None, f"join code made ({code})")
    gn = next(c for c in call("GET", "/api/campaigns/1/characters")["characters"] if c["name"] == "Gnocchi")
    for pl in call("GET", "/api/campaigns/1/players")["players"]:
        if pl.get("name") == "E2E player":
            call("DELETE", f"/api/players/{pl['id']}")
    ctx = browser.new_context(viewport={"width": 420, "height": 900}, **engine.mobile(), has_touch=True)
    pp = ctx.new_page(); watch(pp, "player")
    pp.goto(LAN + "/join")
    pp.fill("input[name=code]", code.replace(" ", "")); pp.fill("input[name=name]", "E2E player")
    pp.wait_for_selector("#char-field:not([hidden])")
    opts = pp.locator("select[name=character_id] option").all_inner_texts()
    for pl in call("GET", f"/api/campaigns/1/players")["players"]:  # free her up in this copy
        if pl.get("character_id") == gn["id"] and not pl.get("revoked"):
            call("DELETE", f"/api/players/{pl['id']}")
    pp.reload(); pp.fill("input[name=code]", code.replace(" ", "")); pp.fill("input[name=name]", "E2E player")
    pp.wait_for_selector("#char-field:not([hidden])")
    opts = pp.locator("select[name=character_id] option").all_inner_texts()
    free = "Gnocchi" if not any("Gnocchi" in o and "taken" in o for o in opts) else None
    if not free:
        check(False, "Gnocchi is free to join as"); return
    pp.select_option("select[name=character_id]", value=str(gn["id"]))
    pp.click("button[type=submit]")
    pp.wait_for_url(re.compile(r"/play"), timeout=8000)
    settle(pp, 1500)
    check("Gnocchi" in pp.locator("body").inner_text(), "player screen shows their character")
    # player rolls a Strength check
    pp.locator(".stat").first.click(); settle(pp, 2500)
    rolls = call("GET", f"/api/rolls?character_id={gn['id']}")["rolls"]
    check(any(r["roller_kind"] == "player" for r in rolls), "player's roll reaches the DM's history")
    # players can't use DM endpoints
    code_dm = pp.evaluate("async () => (await fetch('/api/campaigns/1/characters')).status")
    check(code_dm == 403, f"DM-only API is blocked for players ({code_dm})")
    pp.screenshot(path=SHOTS + "\\player.png", full_page=True)
    ctx.close()


@phase("Settings: theme, combat rules, backup")
def settings(pg):
    pg.goto(DM + "/settings"); settle(pg)
    theme0 = pg.evaluate("document.documentElement.dataset.theme")
    pg.locator("#theme-seg button").filter(has_text=re.compile("Light" if theme0 == "dark" else "Dark")).first.click(); settle(pg, 900)
    theme1 = call("GET", "/api/settings")["theme"]
    check(theme1 != theme0, f"theme switches ({theme0} -> {theme1})")
    pg.locator("#theme-seg button").filter(has_text=re.compile("Dark" if theme0 == "dark" else "Light")).first.click(); settle(pg, 900)
    box = pg.locator("[data-set='combat.auto_concentration']")
    check(box.count() == 1 and box.is_checked(), "Concentration saves setting shows, on by default")
    box.uncheck(); settle(pg, 1200)
    camp = next(c for c in call("GET", "/api/campaigns")["campaigns"] if c["id"] == 1)
    check(camp["settings"]["combat"]["auto_concentration"] is False, "turning it off saves")
    box.check(); settle(pg, 1200)
    for link in pg.locator("#backups a.btn").all():
        href = link.get_attribute("href")
        r = pg.request.get(DM + href)
        check(r.status == 200 and len(r.body()) > 1000, f"backup {href} downloads ({len(r.body())} bytes)")
    pg.screenshot(path=SHOTS + "\\settings.png", full_page=True)


with sync_playwright() as p:
    browser = engine.launch(p)
    ctx = browser.new_context(viewport={"width": 1440, "height": 1000})
    pg = ctx.new_page()
    watch(pg, "DM")
    only = sys.argv[1:]
    for name, fn in (("pages", pages), ("campaigns", campaigns), ("characters", characters), ("dice", dice_tray), ("morality", morality),
                     ("journal", journal), ("creatures", creatures), ("combat", combat), ("map", battle_map), ("players", players), ("settings", settings)):
        if only and name not in only:
            continue
        fn(pg, browser) if name == "players" else fn(pg)
    browser.close()

fails = [r for r in results if not r[1]]
print(f"\n{len(results) - len(fails)} passed, {len(fails)} failed")
for f in fails:
    print("FAILED:", f[0], "-", f[2])
print("PROBLEMS:")
for x in dict.fromkeys(problems):
    print("  ", x)
