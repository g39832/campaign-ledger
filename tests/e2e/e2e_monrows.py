"""Monster attacks as a form: every line (the library, the monster book, tricky ones) becomes a card and
back into a line the fight reads the same way; editing on the Creatures page and in a fight works."""
import json, re, urllib.request, uuid
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


lib = call("GET", "/api/creatures")["creatures"]
import subprocess
APPDIR = APP_DIR
book = json.loads(subprocess.run([APPDIR + r"\.venv\Scripts\python.exe", "-c",
    "import json; from app.monster_book import MONSTERS; print(json.dumps([{'attacks': m['attacks']} for m in MONSTERS]))"],
    cwd=APPDIR, capture_output=True, text=True).stdout)
LINES = []
for c in lib + book:
    LINES += [("attacks", l) for l in str(c.get("attacks") or "").splitlines() if l.strip()]
    LINES += [("spells", l) for l in str(c.get("spells") or "").splitlines() if l.strip()]
LINES += [("attacks", x) for x in ["Bite 1d4", "Spread 1d20 must beat a 5", "Claw +4 to hit 1d6+2", "Snipe shot - 1d20 damage",
                                   "Poison sting +3 to hit 1d4 piercing Poisoned 2 rounds 3 turn cooldown", "Fire breath 6d6 fire 15 ft cone, 3 turn cooldown",
                                   "Longbow +5 to hit 1d8+3 piercing ranged", "Halberd +5 to hit 1d10+3 slashing reach 10 ft", "Mend heal 1d8"]]
LINES += [("spells", x) for x in ["Fire bolt +5 2d10", "Fireball 8d6", "Healing word heal 1d4+2", "Web: Restrained 10 rounds", "Hold person DC 13"]]
print(len(LINES), "lines")
with sync_playwright() as p:
    b = engine.launch(p)
    pg = b.new_page(viewport={"width": 1400, "height": 950}); pg.on("pageerror", lambda e: problems.append(f"JS error: {e}"))
    pg.goto(DM + "/creatures"); pg.wait_for_timeout(1500)
    # 1. every line: card -> line -> read the same in a fight
    bad = pg.evaluate("""(lines) => {
      const P = L.attackRowParts, out = [];
      const key = (kind, line) => {
        if (kind === "spells") { const s = L.monsterSpells(line)[0]; return s ? JSON.stringify([s.name, s.dice || "", s.effect || s.kind, s.condition || "", s.rounds || null, s.attack_bonus ?? null, s.dc ?? null, s.cooldown || 0, s.area ? [s.area.kind, s.area.size] : null]) : "none"; }
        const a = L.attackLines(line)[0];
        if (!a) return "note";
        return JSON.stringify([a.name, a.hit || null, a.dmg || null, !!a.heal, a.check || null, a.beat ?? null, a.condition || "", a.rounds || null, a.aimArea ? [a.aimArea.kind, a.aimArea.size, a.aimArea.range] : null, a.reach ?? null, a.cooldown || 0]);
      };
      for (const [kind, line] of lines) {
        const r = P.rowFromLine(line, kind); r.dirty = true;
        const back = P.lineFromRow(r, kind);
        const k1 = key(kind, line), k2 = key(kind, back);
        if (k1 !== k2) out.push({ kind, line, back, k1, k2 });
      }
      return out;
    }""", LINES)
    for x in bad[:12]:
        print("    MISMATCH", x["kind"], repr(x["line"][:90]), "->", repr(x["back"]), "\n        ", x["k1"], "\n        ", x["k2"])
    check(not bad, f"all {len(LINES)} attack and spell lines come back from the form reading exactly the same in a fight ({len(bad)} differ)")

    # 2. the Creatures page: bat has no attack -> the warning, Add a basic attack, then edit it with the form
    bat = next(c for c in lib if c["name"] == "bat")
    if bat["attacks"]:  # in this copy, start the bat with no attacks again
        call("PATCH", f"/api/creatures/{bat['id']}", {"changes": {"attacks": {"from": bat["attacks"], "to": ""}, "spells": {"from": bat["spells"], "to": ""}}}); pg.reload(); pg.wait_for_timeout(1500)
    pg.locator("#list li button").filter(has=pg.locator(".t", has_text=re.compile(r"^bat$"))).first.click(); pg.wait_for_timeout(600)
    ed = pg.locator("#editor")
    check(ed.locator(".mr-warn").count() == 1, "bat: 'No attacks yet' warning on the Creatures page")
    ed.get_by_role("button", name="Add a basic attack").click(); pg.wait_for_timeout(2500)
    got = next(c for c in call("GET", "/api/creatures")["creatures"] if c["id"] == bat["id"])["attacks"]
    check(got.startswith("Strike: +2 to hit, 1d6 bludgeoning damage"), f"one click gives it a basic attack ({got!r})")
    card = ed.locator(".mrows").first.locator(".mrow").first
    card.locator(".mr-name").fill("Bite"); card.get_by_label("To hit").fill("+0"); card.get_by_label("Dice").fill("1d4")
    card.get_by_label("Damage type").select_option("piercing"); pg.wait_for_timeout(300)
    card.get_by_label("Condition").select_option("Poisoned"); pg.wait_for_timeout(300)
    card = ed.locator(".mrows").first.locator(".mrow").first
    card.get_by_label("Rounds").fill("1"); pg.wait_for_timeout(2500)
    got = next(c for c in call("GET", "/api/creatures")["creatures"] if c["id"] == bat["id"])["attacks"]
    check(got == "Bite: +0 to hit, 1d4 piercing damage, Poisoned 1 rounds", f"filled in like a hero's attack row, saved ({got!r})")
    check("In a fight: +0 to hit · 1d4 damage · Poisoned for 1 rounds · reaches 5 ft" in card.inner_text(), f"the card says what it'll do in a fight ({card.locator('.mr-fight').inner_text()!r})")
    ed.screenshot(path=SHOTS + rf"\monrows_creature_{engine.NAME}.png")
    # spells: add a rulebook spell by name
    sp = ed.locator(".mrows").nth(1)
    sp.get_by_role("button", name="Add a spell").click(); pg.wait_for_timeout(300)
    sc = sp.locator(".mrow").last
    sc.locator(".mr-name").fill("Fireball"); sc.get_by_label("Dice").fill("8d6"); pg.wait_for_timeout(2500)
    got = next(c for c in call("GET", "/api/creatures")["creatures"] if c["id"] == bat["id"])["spells"]
    check(got.startswith("Fireball: 8d6"), f"a spell from the form ({got!r})")
    check("rulebook's Fireball" in sc.inner_text(), "it says it uses the rulebook's Fireball")
    # Edit as text still works
    sp.get_by_role("button", name="Edit as text").click(); pg.wait_for_timeout(300)
    check("Fireball: 8d6" in sp.locator("textarea").input_value(), "Edit as text shows the same lines")
    sp.get_by_role("button", name="Back to the form").click(); pg.wait_for_timeout(300)
    check(sp.locator(".mrow").count() == 1, "and back to the form")
    # an untouched monster from the book keeps its exact text
    mage = next(c for c in lib if c["name"] == "Mage")
    pg.locator("#list li button").filter(has=pg.locator(".t", has_text=re.compile(r"^Mage$"))).first.click(); pg.wait_for_timeout(800)
    pg.locator("#editor .mr-name").first.click(); pg.wait_for_timeout(2000)
    check(next(c for c in call("GET", "/api/creatures")["creatures"] if c["id"] == mage["id"])["attacks"] == mage["attacks"], "looking at a monster changes nothing (its lines stay word for word)")

    # 3. in a fight: the bat's new Bite is a button; change it with the form on the map
    eid = call("POST", "/api/campaigns/1/encounters", {"name": "Bat fight"})["encounter"]["id"]
    st = call("POST", f"/api/encounters/{eid}/combatants", {"creature_id": bat["id"], "count": 1})
    mid = call("POST", f"/api/encounters/{eid}/map")["map_id"]
    call("POST", f"/api/encounters/{eid}/start")
    batcb = next(c for c in call("GET", f"/api/encounters/{eid}")["combatants"] if c["name"].startswith("bat"))
    pg.evaluate(f"localStorage.setItem('combat-sel-{eid}', '{batcb['id']}')")
    pg.goto(DM + f"/map/{mid}"); pg.wait_for_timeout(2000)
    acts = [x.split("\n")[0] for x in pg.locator(".fight-act").all_inner_texts()]
    check(any("Bite" in x for x in acts), f"the bat's Bite is a move on the map ({acts})")
    pg.locator(".mon-edit > summary").first.click(); pg.wait_for_timeout(300)
    me = pg.locator(".mon-edit").first
    check(me.locator(".mrow").count() >= 1, "the map's 'Change attacks & spells' is the form too")
    me.get_by_role("button", name="Add an attack").click(); pg.wait_for_timeout(200)
    nc = me.locator(".mrows").first.locator(".mrow").last
    nc.locator(".mr-name").fill("Screech"); nc.get_by_label("What it does").select_option("condition"); pg.wait_for_timeout(200)
    nc = me.locator(".mrows").first.locator(".mrow").last
    nc.get_by_label("Condition").select_option("Frightened"); pg.wait_for_timeout(200)
    nc = me.locator(".mrows").first.locator(".mrow").last
    nc.get_by_label("Area size in feet").fill("15"); pg.wait_for_timeout(200)
    me.get_by_role("button", name=re.compile("Save attacks")).click(); pg.wait_for_timeout(2500)
    sb = next(c for c in call("GET", f"/api/encounters/{eid}")["combatants"] if c["id"] == batcb["id"])["statblock"]
    check("Screech:" in sb["attacks"] and "Frightened" in sb["attacks"] and "15 ft cone" in sb["attacks"], f"saved in the fight ({sb['attacks']!r})")
    acts = [x.split("\n")[0] for x in pg.locator(".fight-act").all_inner_texts()]
    check(any("Screech" in x for x in acts), f"Screech is a new move right away ({acts})")
    b.close()
fails = [m for ok, m in results if not ok]
print(f"\n{len(results) - len(fails)} passed, {len(fails)} failed"); [print("FAILED:", f) for f in fails]
print("PROBLEMS:", problems)
