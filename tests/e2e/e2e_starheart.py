"""E2E (2026-11-18): Steven Voss's Hollow Star Heart, on a data copy.

1. Creatures page: Steven's "Watch the phase 2 animation" button plays the scene (shard rises, goes into
   his chest, the star lights, metal plates appear and fly into wings, the wings sweep open, the words),
   and a tap skips it.
2. A real fight in the "Steven Voss test room": dropping him to half health plays the scene by itself on
   the DM's battle map (instead of the plain "Phase 2!" banner), his token gets steel wings, and his
   phase 2 list has the four new wing/star moves, each with its look.
3. Above half health: no scene, no wings."""
import json, os, urllib.request, uuid
from common import DM_URL, SHOTS_DIR  # noqa: E402
from playwright.sync_api import sync_playwright
import engine

DM = DM_URL
results, problems = [], []
NEW = {"Wing Scythe": "slash", "Feather Storm": "arrow", "Star Core Beam": "laser", "Wing Guard Slam": "punch"}


def call(m, path, body=None):
    data = json.dumps(dict(body or {}, op_id=uuid.uuid4().hex)).encode() if m != "GET" else None
    return json.load(urllib.request.urlopen(urllib.request.Request(DM + path, data=data, method=m, headers={"Content-Type": "application/json"})))


def check(c, msg):
    results.append((bool(c), msg)); print(("  PASS " if c else "  FAIL ") + msg, flush=True)


camp = 1
for e in call("GET", f"/api/campaigns/{camp}/encounters")["encounters"]:
    if e["status"] == "active":
        call("POST", f"/api/encounters/{e['id']}/end")
eid = next(e["id"] for e in call("GET", f"/api/campaigns/{camp}/encounters")["encounters"] if e["name"] == "Steven Voss test room")
mid = next(m["id"] for m in call("GET", f"/api/campaigns/{camp}/maps")["maps"] if m["name"] == "Steven Voss test room")
by = {c["name"]: c for c in call("GET", f"/api/encounters/{eid}")["combatants"]}
ST = by["Steven Voss"]["id"]
steven_lib = next(c for c in call("GET", "/api/creatures")["creatures"] if c["name"] == "Steven Voss")
call("POST", f"/api/combatants/{ST}/hp", {"op": "heal", "amount": 999})
call("POST", f"/api/campaigns/{camp}/live-map", {"map_id": mid})
call("POST", f"/api/encounters/{eid}/start")


def state(page):
    return page.evaluate("""() => { const el = document.querySelector('.fx-starheart'); if (!el) return null;
      return { cls: el.className, plates: el.querySelectorAll('.sh-plate').length,
        shown: [...el.querySelectorAll('.sh-plate')].filter((p) => getComputedStyle(p).opacity > 0.5).length,
        shard: +getComputedStyle(el.querySelector('.sh-shard')).opacity, core: +getComputedStyle(el.querySelector('.sh-core')).opacity,
        title: +getComputedStyle(el.querySelector('.sh-title')).opacity, text: el.innerText }; }""")


with sync_playwright() as p:
    b = engine.launch(p)
    import os as _os
    PHONE = _os.environ.get("DEVICES") == "phones"
    ctx = b.new_context(viewport={"width": 390, "height": 844}, has_touch=True, **engine.mobile()) if PHONE else b.new_context(viewport={"width": 1400, "height": 1000})
    page = ctx.new_page(); page.on("pageerror", lambda e: problems.append(f"JS error: {e}"))

    print(f"== [{engine.NAME}] 1. preview on the Creatures page")
    page.goto(f"{DM}/creatures"); page.wait_for_timeout(1500)
    page.get_by_role("button", name="Steven Voss").first.click(); page.wait_for_timeout(800)
    page.screenshot(path=os.path.join(SHOTS_DIR, "starheart-0-editor.png"))
    btn = page.locator("#phase2-preview")
    check(btn.count() == 1, "Steven's editor has 'Watch the phase 2 animation'")
    btn.click()
    page.wait_for_timeout(1300); s = state(page)
    check(s and s["plates"] == 42 and s["shard"] > 0.5, f"scene open, the shard is up, 42 metal plates ready ({s and s['plates']})")
    page.screenshot(path=os.path.join(SHOTS_DIR, "starheart-1-shard.png"))
    page.wait_for_timeout(1900); s = state(page)
    check(s and "is-lit" in s["cls"] and s["core"] > 0.5 and s["shard"] < 0.5, "shard went into his chest: the star is lit")
    page.screenshot(path=os.path.join(SHOTS_DIR, "starheart-2-lit.png"))
    page.wait_for_timeout(1100); s = state(page)
    page.screenshot(path=os.path.join(SHOTS_DIR, "starheart-3-scraps.png"))
    check(s and s["shown"] >= 20, f"metal scraps formed out of nothing ({s and s['shown']} visible)")
    page.wait_for_timeout(1300)
    page.screenshot(path=os.path.join(SHOTS_DIR, "starheart-4-forming.png"))
    page.wait_for_timeout(2300); s = state(page)
    check(s and "is-winged" in s["cls"] and s["shown"] == 42, "all plates locked into the wings and they swept open")
    page.wait_for_timeout(900); s = state(page)
    page.screenshot(path=os.path.join(SHOTS_DIR, "starheart-5-wings.png"))
    check(s and s["title"] > 0.9 and "Hollow Star Heart" in s["text"], "title 'Hollow Star Heart' shows")
    page.screenshot(path=os.path.join(SHOTS_DIR, f"starheart-5-wings-{engine.NAME}{'-phone' if PHONE else ''}.png"))
    page.locator(".fx-starheart").click(); page.wait_for_timeout(900)
    check(state(page) is None, "a tap closes it")

    print(f"== [{engine.NAME}] 3. above half health: no scene, no wings")
    call("POST", f"/api/encounters/{eid}/set-turn", {"combatant_id": ST})
    me = next(c for c in call("GET", f"/api/encounters/{eid}")["combatants"] if c["id"] == ST)
    check(me["max_hp"] == 350 and me["move"] and me["move"]["speed"] == 30, f"full health: 350 HP, walks 30 ft ({me['max_hp']}, {me['move']})")
    call("POST", f"/api/combatants/{ST}/hp", {"op": "damage", "amount": 40})
    page.goto(f"{DM}/map/{mid}"); page.wait_for_timeout(3000)
    check(state(page) is None, "no scene at 150/190")

    print(f"== [{engine.NAME}] 2. dropping him to half plays it on the battle map")
    hp = next(c for c in call("GET", f"/api/encounters/{eid}")["combatants"] if c["id"] == ST)
    call("POST", f"/api/combatants/{ST}/hp", {"op": "damage", "amount": hp["hp"] - hp["max_hp"] // 2})
    s = None
    for _ in range(16):
        page.wait_for_timeout(500); s = state(page)
        if s: break
    if not s:
        print("  dbg:", page.evaluate("() => [document.querySelector('#boss-bar') && document.querySelector('#boss-bar').innerText, JSON.stringify(Object.entries(sessionStorage))]"))
    check(s is not None and "steven voss is at half health" in (s["text"] or "").lower(), "the scene starts by itself when he hits half")
    page.wait_for_timeout(4000)
    page.screenshot(path=os.path.join(SHOTS_DIR, "starheart-map-scene.png"))
    page.wait_for_timeout(8000)
    check(state(page) is None, "it closes by itself")
    page.screenshot(path=os.path.join(SHOTS_DIR, "starheart-6-token.png"))
    enc = call("GET", f"/api/encounters/{eid}")
    sb = next(c for c in enc["combatants"] if c["id"] == ST)
    check(sb["boss"]["phase"] == 2, "server says phase 2")
    check(sb["move"] and sb["move"]["speed"] == 90, f"phase 2: 90 ft of movement on his turn ({sb['move']})")
    looks = page.evaluate("(t) => Object.fromEntries(L.attackLines(t).map((a) => [a.name, a.look + '|' + (a.push||0) + '|' + (a.aimArea ? a.aimArea.kind : '')]))", sb["boss"]["phase2"])
    for n, lk in NEW.items():
        check(n in looks and looks[n].startswith(lk + "|"), f"phase 2 has {n} (look {lk}): {looks.get(n)}")
    page.reload(); page.wait_for_timeout(3000)
    check(state(page) is None, "reloading the same tab doesn't replay it")

    print(f"== [{engine.NAME}] 4. the combat page lists the new moves")
    page.goto(f"{DM}/combat/{eid}"); page.wait_for_timeout(2500)
    txt = page.inner_text("body")
    check(all(n in txt for n in NEW), "combat page shows Wing Scythe, Feather Storm, Star Core Beam, Wing Guard Slam")
    b.close()

call("POST", f"/api/encounters/{eid}/end")
check(not problems, "no JS errors: " + "; ".join(problems[:3]))
bad = [m for ok, m in results if not ok]
print(f"e2e_starheart.py [{engine.NAME}]: {len(results) - len(bad)} passed, {len(bad)} failed")
