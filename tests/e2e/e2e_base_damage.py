"""E2E (2026-11-18): creature attacks have a "Base damage" box next to the damage dice. A hit deals the
base damage plus the dice ("2d6" + base 10 -> "2d6+10"). On a data copy.

1. Creatures page: a new creature, an attack with dice 2d6 and base 10 is saved as 2d6+10, says
   "10 base damage + 2d6 on a hit", and opens again with 2d6 in the dice box and 10 in the base box.
2. Old lines still read right: Steven's "Piston Slam ... 3d10+5" opens as dice 3d10, base 5.
3. Typing +2 in the dice box and 3 in the base box is one number (1d6+5), not lost.
4. In a fight, every hit of that attack deals at least 12 (10 + the lowest 2d6) and at most 22."""
import json, os, urllib.request, uuid
from common import DM_URL, SHOTS_DIR  # noqa: E402
from playwright.sync_api import sync_playwright
import engine

DM = DM_URL
results, problems = [], []


def call(m, path, body=None):
    data = json.dumps(dict(body or {}, op_id=uuid.uuid4().hex)).encode() if m != "GET" else None
    return json.load(urllib.request.urlopen(urllib.request.Request(DM + path, data=data, method=m, headers={"Content-Type": "application/json"})))


def check(c, msg):
    results.append((bool(c), msg)); print(("  PASS " if c else "  FAIL ") + msg, flush=True)


def opened(page, name):
    """The open attack card whose name box says name."""
    rows = page.locator(".mrow:not(.is-folded):not(.is-note)")
    for i in range(rows.count()):
        r = rows.nth(i)
        if r.locator("input.mr-name").input_value() == name:
            return r
    raise AssertionError("no open card " + name)


NAME = "Base Damage Brute " + uuid.uuid4().hex[:4]

with sync_playwright() as p:
    b = engine.launch(p)
    ctx = b.new_context(viewport={"width": 1400, "height": 1000})
    page = ctx.new_page(); page.on("pageerror", lambda e: problems.append(f"JS error: {e}"))

    print(f"== [{engine.NAME}] 2. old lines open split")
    page.goto(f"{DM}/creatures"); page.wait_for_timeout(1500)
    page.get_by_role("button", name="Steven Voss").first.click(); page.wait_for_timeout(800)
    row = page.locator(".mrow", has_text="Piston Slam").first
    row.locator(".mr-fold").click(); page.wait_for_timeout(300)
    row = opened(page, "Piston Slam")
    check(row.get_by_label("Dice").input_value() == "3d10" and row.get_by_label("Base damage").input_value() == "5",
          "Piston Slam (3d10+5) opens as dice 3d10, base damage 5")
    before = next(c for c in call("GET", "/api/creatures")["creatures"] if c["name"] == "Steven Voss")["phase2"]

    print(f"== [{engine.NAME}] 1. a new attack with base damage")
    cid = call("POST", "/api/creatures", {"name": NAME, "max_hp": 50, "ac": 12, "attacks": ""})["creature"]["id"]
    page.goto(f"{DM}/creatures"); page.wait_for_timeout(1500)
    page.get_by_role("button", name=NAME).first.click(); page.wait_for_timeout(800)
    page.get_by_role("button", name="Add an attack").first.click(); page.wait_for_timeout(300)
    card = page.locator(".mrow:has(input.mr-name)").last
    card.get_by_label("Name").fill("Crusher")
    card.get_by_label("To hit").fill("+30")
    card.get_by_label("Dice").fill("2d6")
    card.get_by_label("Base damage").fill("10")
    page.wait_for_timeout(300)
    check("10 base damage + 2d6 on a hit" in card.inner_text(), "the card says '10 base damage + 2d6 on a hit'")
    page.screenshot(path=os.path.join(SHOTS_DIR, "base-damage-card.png"))
    page.wait_for_timeout(2500)  # autosave
    saved = next(c for c in call("GET", "/api/creatures")["creatures"] if c["id"] == cid)["attacks"]
    check("Crusher: +30 to hit, 2d6+10 damage" in saved, f"saved as one line the fight reads: {saved!r}")
    page.reload(); page.wait_for_timeout(1500)
    page.get_by_role("button", name=NAME).first.click(); page.wait_for_timeout(800)
    page.locator(".mrow", has_text="Crusher").first.locator(".mr-fold").click(); page.wait_for_timeout(300)
    card = opened(page, "Crusher")
    check(card.get_by_label("Dice").input_value() == "2d6" and card.get_by_label("Base damage").input_value() == "10", "opens again as 2d6 + base 10")

    print(f"== [{engine.NAME}] 3. +2 in the dice box and base 3 add up")
    card.get_by_label("Dice").fill("1d6+2"); card.get_by_label("Base damage").fill("3"); page.wait_for_timeout(2500)
    saved = next(c for c in call("GET", "/api/creatures")["creatures"] if c["id"] == cid)["attacks"]
    check("1d6+5 damage" in saved, f"1d6+2 with base 3 saved as 1d6+5: {saved!r}")
    card.get_by_label("Dice").fill("2d6"); card.get_by_label("Base damage").fill("10"); page.wait_for_timeout(2500)
    after = next(c for c in call("GET", "/api/creatures")["creatures"] if c["name"] == "Steven Voss")["phase2"]
    check(before == after, "opening Steven's card didn't change his saved moves")
    fight = page.evaluate("(t) => L.attackLines(t).map((a) => a.name + '|' + a.dmg)", next(c for c in call("GET", "/api/creatures")["creatures"] if c["id"] == cid)["attacks"])
    check(fight == ["Crusher|2d6+10"], f"the fight reads Crusher as 2d6+10: {fight}")
    b.close()

print(f"== [{engine.NAME}] 4. the fight's damage roll: base + dice on every hit")
import importlib.util  # noqa: E402  the same roller the fight uses (app/dice.py on its own: this venv has no Flask)
_spec = importlib.util.spec_from_file_location("app_dice", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "app", "dice.py"))
dice = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(dice)
totals = [dice.roll("2d6+10")["total"] for _ in range(300)]
check(min(totals) >= 12 and max(totals) <= 22, f"2d6+10 always 12-22 (seen {min(totals)}-{max(totals)})")
crit = [dice.roll("2d6+10", crit=True)["total"] for _ in range(300)]
check(min(crit) >= 14 and max(crit) <= 34, f"a crit doubles the dice only, base stays 10 (seen {min(crit)}-{max(crit)})")
call("DELETE", f"/api/creatures/{cid}")

check(not problems, "no JS errors: " + "; ".join(problems[:3]))
bad = [m for ok, m in results if not ok]
print(f"e2e_base_damage.py [{engine.NAME}]: {len(results) - len(bad)} passed, {len(bad)} failed")
