"""E2E 2: casting in a fight on the Combat screen, with real clicks. Setup (the fight and
who's in it) goes through the API; every spell is cast by clicking."""
import json
from common import APP_DIR, DM_URL, LAN_IP, LAN_URL, SHOTS_DIR, TMP_DIR  # noqa: E402,F401  (paths and addresses for this computer)
import sys
import urllib.request
import uuid

from playwright.sync_api import sync_playwright

BASE = DM_URL
SHOTS = SHOTS_DIR
errors = []


def call(method, path, body=None):
    data = json.dumps(dict(body or {}, op_id=uuid.uuid4().hex)).encode() if method != "GET" else None
    req = urllib.request.Request(BASE + path, data=data, method=method, headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req))


def check(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond:
        errors.append(msg)


chars = {c["name"]: c for c in call("GET", "/api/campaigns/1/characters")["characters"]}
lux = call("GET", f"/api/characters/{chars['Lux Fedelis']['id']}")["character"]
_book = {x["name"]: x for x in call("GET", "/api/spell-book")["spells"]}
call("PATCH", f"/api/characters/{lux['id']}", {"changes": {"spells": {"from": lux["spells"], "to": lux["spells"] + [_book[n] for n in ("Fireball", "Bless", "Cure Wounds", "Hold Person")]
    + [{"name": "Mend", "effect": "heal", "level": 0, "dice": "1d8", "cooldown": 1}, {"name": "Sheild of faith", "effect": "buff", "level": 1, "ac": 2, "condition": "Shield of Faith", "rounds": 100}]}}})
call("PATCH", f"/api/characters/{lux['id']}", {"changes": {"level": {"to": 5}, "spell_slots": {"to": {
    "1": {"max": 4, "used": 0}, "2": {"max": 3, "used": 0}, "3": {"max": 2, "used": 0}}}}})
mage = call("POST", "/api/creatures", {"name": "Cult mage", "max_hp": 33, "ac": 12, "abilities": {"wis": 14},
                                       "traits": "Spellcasting. Wisdom (spell save DC 13, +5 to hit with spell attacks).",
                                       "spells": "Fire bolt +5 2d10\nHold person DC 13\nHealing word heal 1d4+2"})["creature"]
eid = call("POST", "/api/campaigns/1/encounters", {"name": "E2E spell fight"})["encounter"]["id"]
call("POST", f"/api/encounters/{eid}/combatants", {"characters": [chars[n]["id"] for n in ("Lux Fedelis", "Moni Easter", "Yamato", "Gnocchi")],
                                                   "quick": {"name": "Goblin", "max_hp": 30, "ac": 12, "count": 2}})
st = call("POST", f"/api/encounters/{eid}/combatants", {"creature_id": mage["id"]})
by = {c["name"]: c for c in st["combatants"]}
call("POST", f"/api/combatants/{by['Gnocchi']['id']}/hp", {"op": "damage", "amount": 6})


def state():
    s = call("GET", f"/api/encounters/{eid}")
    return s, {c["name"]: c for c in s["combatants"]}


with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    pg = b.new_page(viewport={"width": 1440, "height": 1100})
    pg.on("pageerror", lambda e: errors.append("JS error: " + str(e)))
    pg.on("console", lambda m: m.type == "error" and errors.append("console: " + m.text))
    pg.goto(f"{BASE}/combat/{eid}")
    pg.click("#start")
    pg.wait_for_timeout(800)

    def close_dice():
        pg.wait_for_timeout(2500)
        if pg.locator("#dice-dock.is-open").count():
            pg.click("#dice-close")
            pg.wait_for_timeout(200)

    def select(name):
        pg.locator("#init-list li.combatant").filter(has_text=name).first.locator(".c-name").click()
        pg.wait_for_timeout(300)

    def fresh_turn(name):
        """Two actions a turn now: each cast gets the caster a turn of their own."""
        for _ in range(12):
            st = call("POST", f"/api/encounters/{eid}/next")
            if st["encounter"]["current_id"] == by[name]["id"]:
                break
        pg.wait_for_timeout(1800)

    def cast(caster, spell, targets, slot=None):
        fresh_turn(caster)
        select(caster)
        pg.locator("#detail .spell-row").filter(has=pg.locator(".sr-name b", has_text=spell)).first.get_by_role("button", name="Cast").click()
        pg.wait_for_selector("#detail .cast-picker")
        for t in targets:
            pg.locator("#detail .cast-chip").filter(has_text=t).first.click()
        if slot and pg.locator("#detail .cast-slot select").count():
            pg.locator("#detail .cast-slot select").first.select_option(str(slot))
        if not pg.locator("#detail .cast-go").is_enabled():
            pg.screenshot(path=SHOTS + r"\combat_stuck.png"); print("    STUCK:", pg.locator("#detail .cast-picker").inner_text()[:400].replace(chr(10), " | "))
        pg.locator("#detail .cast-go").click(timeout=5000)
        pg.wait_for_selector("#detail .cast-result", timeout=30000)  # the result shows once the dice land
        text = pg.locator("#detail .cast-result").inner_text()
        print("   ", text.replace("\n", " | "))
        close_dice()
        pg.locator("#detail .cast-picker").get_by_role("button", name="Done").click()
        return text

    # damage: Fireball upcast to 3 on both goblins
    _, before = state()
    t = cast("Lux Fedelis", "Fireball", ["Goblin 1", "Goblin 2"], slot=3)
    pg.screenshot(path=SHOTS + r"\combat_fireball.png")
    s, now = state()
    check("Lux Fedelis cast Fireball" in t and "slot used" not in t, "Fireball result card shows (no spell slots: house rule)")
    check(now["Goblin 1"]["hp"] < 30 or "missed" in t or "saved" in t, "goblins took damage (or saved/missed)")
    luxs = call("GET", f"/api/characters/{lux['id']}")["character"]
    check(luxs["spell_slots"]["3"]["used"] == 0, "no slot was spent (house rule: spells only have cooldowns)")
    check(any("Lux Fedelis casts Fireball" in e["message"] for e in s["log"]), "the log says what Fireball did")
    rolls = call("GET", f"/api/rolls?encounter_id={eid}")["rolls"]
    check(any("Fireball" in r["label"] for r in rolls), "Fireball rolls are in the dice history")

    # buff: Bless on Moni and Yamato (concentration)
    t = cast("Lux Fedelis", "Bless", ["Moni Easter", "Yamato"])
    s, now = state()
    check(any(x["name"] == "Blessed" and x.get("roll_mod") == "1d4" for x in now["Yamato"]["conditions"]), "Yamato is Blessed (+1d4)")
    check(any(x["name"] == "Concentrating" for x in now["Lux Fedelis"]["conditions"]), "Lux is concentrating")
    check("Blessed" in pg.locator("#init-list li.combatant").filter(has_text="Yamato").first.inner_text(), "Blessed tag shows in the turn order")

    # heal: Cure Wounds on Gnocchi
    hp0 = now["Gnocchi"]["hp"]
    t = cast("Lux Fedelis", "Cure Wounds", ["Gnocchi"])
    s, now = state()
    check(now["Gnocchi"]["hp"] > hp0 or now["Gnocchi"]["hp"] == now["Gnocchi"]["max_hp"], "Cure Wounds healed Gnocchi")

    # Mend (moved from Attacks): heal with a 1-turn cooldown
    t = cast("Lux Fedelis", "Mend", ["Gnocchi"])
    s, now = state()
    check(any("Mend recharging" == x["name"] for x in now["Lux Fedelis"]["conditions"]), "Mend's cooldown started")
    select("Lux Fedelis")
    check("recharging" in pg.locator("#detail .spell-row").filter(has_text="Mend").first.inner_text(), "Mend shows recharging")

    # buff from the old attack row: Shield of faith +2 AC
    ac0 = now["Moni Easter"]["ac"]
    cast("Lux Fedelis", "Sheild of faith", ["Moni Easter"])
    s, now = state()
    check(now["Moni Easter"]["ac"] == ac0 + 2, "Shield of faith gave Moni +2 AC")

    # debuff: Hold Person on Goblin 2 (replaces Bless as concentration)
    t = cast("Lux Fedelis", "Hold Person", ["Cult mage"])  # (the Fireball may have dropped the goblins)
    s, now = state()
    check(not any(x["name"] == "Blessed" for x in now["Yamato"]["conditions"]), "casting Hold Person ended Bless")
    held = any(x["name"] == "Paralyzed" for x in now["Cult mage"]["conditions"])
    print("    Cult mage held:", held)

    # monster spells: Cult mage Fire bolt at Yamato, then Bane from the book
    t = cast("Cult mage", "Fire bolt", ["Yamato"])
    check("cult mage cast fire bolt" in t.lower(), "the monster's own spell line casts")
    select("Cult mage")
    pg.locator("#detail .sr-book select").select_option("Bane")
    pg.locator("#detail .sr-book").get_by_role("button", name="Cast it").click()
    pg.wait_for_selector("#detail .cast-picker")
    pg.locator("#detail .cast-chip").filter(has_text="Gnocchi").first.click()
    pg.locator("#detail .cast-go").click()
    pg.wait_for_selector("#detail .cast-result")
    print("   ", pg.locator("#detail .cast-result").inner_text().replace("\n", " | "))
    pg.screenshot(path=SHOTS + r"\combat_bane.png")
    close_dice()
    pg.locator("#detail .cast-picker").get_by_role("button", name="Done").click()

    # turns go round: effects tick, saves get rolled, nothing breaks
    close_dice()
    for _ in range(8):
        close_dice() if pg.locator("#dice-dock.is-open").count() else None
        pg.click("#next")
        pg.wait_for_timeout(450)
    s, now = state()
    print("    round", s["encounter"]["round"])
    for e in s["log"][-14:]:
        print("    LOG", e["message"])
    pg.screenshot(path=SHOTS + r"\combat_after_turns.png")
    b.close()

print("ERRORS:", errors)
print("EID", eid)
sys.exit(1 if errors else 0)
