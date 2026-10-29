"""E2E: results never show before the dice land, and everything shown matches the rolls:
the dice faces, the attack total, hit or miss against AC, the damage, and the HP lost."""
import json, re, time, urllib.request, uuid
from common import APP_DIR, DM_URL, LAN_IP, LAN_URL, SHOTS_DIR, TMP_DIR  # noqa: E402,F401  (paths and addresses for this computer)
from playwright.sync_api import sync_playwright
import engine

DM = DM_URL; LAN = LAN_URL
SHOTS = SHOTS_DIR
results, problems = [], []
CATCH_VIEW = """
(() => { let real; Object.defineProperty(window, 'MapView', { configurable: true, get() { return real; },
  set(v) { real = class extends v { constructor(...a) { super(...a); window.__view = this;
    const add = this.addFx.bind(this); window.__fxAt = []; this.addFx = (f) => { if (f.type === 'attack') window.__fxAt.push(performance.now()); return add(f); }; } }; } }); })();
"""


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
eid = call("POST", f"/api/campaigns/{camp}/encounters", {"name": "Accuracy"})["encounter"]["id"]
call("POST", f"/api/encounters/{eid}/combatants", {"characters": [chars["Moni Easter"]["id"]], "quick": {"name": "Goblin", "max_hp": 300, "ac": 14, "count": 1}})
mid = call("POST", f"/api/encounters/{eid}/map")["map_id"]
toks = {t["display"]: t for t in call("GET", f"/api/maps/{mid}")["tokens"]}
call("POST", f"/api/tokens/{toks['Moni Easter']['id']}/move", {"x": 4, "y": 4, "free": True})
call("POST", f"/api/tokens/{toks['Goblin']['id']}/move", {"x": 5, "y": 4, "free": True})
call("POST", f"/api/campaigns/{camp}/live-map", {"map_id": mid})
call("POST", f"/api/encounters/{eid}/start")
by = {c["name"]: c for c in call("GET", f"/api/encounters/{eid}")["combatants"]}
code = call("POST", f"/api/campaigns/{camp}/join-code", {"action": "new"})["join_code"]


def hp():
    return next(c for c in call("GET", f"/api/encounters/{eid}")["combatants"] if c["name"] == "Goblin")["hp"]


with sync_playwright() as p:
    b = engine.launch(p)
    ctx = b.new_context(viewport={"width": 390, "height": 844}, **engine.mobile(), has_touch=True); ctx.add_init_script(CATCH_VIEW)
    ph = ctx.new_page(); ph.on("pageerror", lambda e: problems.append(f"phone JS error: {e}"))
    ph.on("console", lambda m: m.type in ("error", "warning") and problems.append(f"phone console: {m.text}"))
    ph.goto(LAN + "/join"); ph.fill("input[name=code]", code); ph.fill("input[name=name]", "Accuracy")
    ph.wait_for_selector("#char-field:not([hidden])"); ph.select_option("select[name=character_id]", value=str(chars["Moni Easter"]["id"]))
    ph.click("button[type=submit]"); ph.wait_for_url(re.compile("/play")); ph.wait_for_timeout(1500)
    dmc = b.new_context(viewport={"width": 1400, "height": 950}); dmc.add_init_script(CATCH_VIEW)
    dm = dmc.new_page(); dm.on("pageerror", lambda e: problems.append(f"DM JS error: {e}"))
    dm.goto(f"{DM}/map/{mid}"); dm.wait_for_timeout(1500)
    for attempt in range(3):
        for _ in range(6):
            if call("POST", f"/api/encounters/{eid}/next")["encounter"]["current_id"] == by["Moni Easter"]["id"]:
                break
        ph.wait_for_timeout(3000)
        print(f"== [{engine.NAME}] Punch #{attempt + 1}")
        g0 = hp()
        ph.locator(".move-card").filter(has=ph.locator("b", has_text=re.compile(r"^\s*Punch\s*$"))).first.get_by_role("button", name=re.compile("Use")).click()
        ph.wait_for_timeout(300)
        ph.locator("#use-box").get_by_role("button", name=re.compile("^Goblin")).click()
        t0 = time.time(); landed = shown = None; seen_rolling = False
        while time.time() - t0 < 15:
            st = ph.evaluate("() => ({ playing: Dice.playing, box: (document.querySelector('#use-box') || {}).innerText || '' })")
            if st["playing"]:
                seen_rolling = True
            if seen_rolling and not st["playing"] and landed is None:
                landed = time.time() - t0
            if ("hit" in st["box"] or "missed" in st["box"] or "CRIT" in st["box"]) and shown is None:
                shown = time.time() - t0
            if landed and shown:
                break
            ph.wait_for_timeout(50)
        check(seen_rolling and shown is not None and landed is not None and shown >= landed - 0.05,
              f"the result shows after the dice land (dice landed {landed and round(landed, 2)} s, result {shown and round(shown, 2)} s)")
        res = ph.locator("#use-box").inner_text()
        print("    toasts:", ph.locator(".toast").all_inner_texts())
        rolls = call("GET", f"/api/rolls?encounter_id={eid}")["rolls"]
        atk = next(r for r in rolls if "attack" in (r["label"] or "").lower() and "Punch" in (r["label"] or ""))
        m = re.search(r"Goblin (hit|missed|CRIT) \((\d+)", res)
        print("    ", res.replace("\n", " / ")[:120], "| attack roll:", atk["total"], atk["result"].get("natural"))
        check(m and int(m.group(2)) == atk["total"], f"the shown attack total is the rolled one ({m and m.group(2)} = {atk['total']})")
        nat = atk["result"].get("natural")
        should_hit = nat == 20 or (nat != 1 and atk["total"] >= 14)
        check(m and (m.group(1) != "missed") == should_hit, f"hit or miss matches AC 14 ({m and m.group(1)}, {atk['total']})")
        settled = json.loads(ph.evaluate("() => document.querySelector('#dice-dock').dataset.settled || '[]'"))
        check(all(s["shown"] == s["expected"] for s in settled), f"every die landed on the face that was rolled ({[(s['shown'], s['expected']) for s in settled]})")
        if should_hit:
            dmg = next(r for r in rolls if r["kind"] == "damage" and "Punch" in (r["label"] or ""))
            check(g0 - hp() == dmg["total"] and f"{dmg['total']} " in res, f"the damage roll ({dmg['total']}) is what the goblin lost ({g0 - hp()})")
        dm.wait_for_timeout(4000)
        if ph.locator("#use-box").get_by_role("button", name="Done").count():
            ph.locator("#use-box").get_by_role("button", name="Done").click()
    fx = dm.evaluate("window.__fxAt")
    check(len(fx) >= 1, f"the DM's map played the punch animations ({len(fx)})")
    b.close()
fails = [m for ok, m in results if not ok]
print(f"\n{len(results) - len(fails)} passed, {len(fails)} failed"); [print("FAILED:", f) for f in fails]
print("PROBLEMS:", problems)
