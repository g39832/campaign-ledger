"""E2E (2026-11-09): Steven Voss, the level 18 artificer boss, in the "Steven Voss test room" fight.

- The DM's combat screen lists his spells: Deploy Drones (relay drones) and his book spells.
- Cast Deploy Drones from the screen: two Voss Drones join on HIS side.
- With a drone next to the Test Hero, his Fire Bolt is echoed by that drone.
- The Test Hero casts a spell next to a drone: Steven's list gets "(copied)", it casts from the
  screen once, and then it's gone.
- His goggles picture is on his token on the map."""
import json, re, urllib.request, uuid
from common import DM_URL, SHOTS_DIR  # noqa: E402
from playwright.sync_api import sync_playwright
import engine

DM = DM_URL
results, problems = [], []


def call(m, path, body=None):
    data = json.dumps(dict(body or {}, op_id=uuid.uuid4().hex)).encode() if m != "GET" else None
    return json.load(urllib.request.urlopen(urllib.request.Request(DM + path, data=data, method=m, headers={"Content-Type": "application/json"})))


def fresh_fight(eid, mid):
    """The copy carries whatever the DM last did in the real test room: start it over (drones gone,
    cooldowns and effects off, full HP, his steel walls folded away)."""
    for t in call("GET", f"/api/maps/{mid}")["tokens"]:
        if t["display"].startswith("Voss Drone"):
            call("DELETE", f"/api/tokens/{t['id']}")
    for c in call("GET", f"/api/encounters/{eid}")["combatants"]:
        if c["name"].startswith("Voss Drone"):
            call("DELETE", f"/api/combatants/{c['id']}")
        elif c["name"] in ("Steven Voss", "Test Hero"):
            for x in c["conditions"]:
                call("DELETE", f"/api/combatants/{c['id']}/conditions/{x['id']}")
            if c["name"] == "Steven Voss":
                call("POST", f"/api/combatants/{c['id']}/hp", {"op": "heal", "amount": 999})
    walls = [[int(v) for v in k.split(",")] for k, t in call("GET", f"/api/maps/{mid}")["map"]["terrain"].items() if t == "bulkhead"]
    if walls:
        call("POST", f"/api/maps/{mid}/terrain", {"value": None, "cells": walls})


def check(c, msg):
    results.append((bool(c), msg)); print(("  PASS " if c else "  FAIL ") + msg, flush=True)


camp = 1
for e in call("GET", f"/api/campaigns/{camp}/encounters")["encounters"]:
    if e["status"] == "active":
        call("POST", f"/api/encounters/{e['id']}/end")
eid = next(e["id"] for e in call("GET", f"/api/campaigns/{camp}/encounters")["encounters"] if e["name"] == "Steven Voss test room")
st = call("GET", f"/api/encounters/{eid}")
by = {c["name"]: c for c in st["combatants"]}
check("Steven Voss" in by and "Test Hero" in by, "the test room has Steven Voss and the Test Hero")
check(by["Steven Voss"]["boss"] is not None and by["Steven Voss"]["portrait"] == "voss-steven-voss.png", "Steven is a boss with the goggles picture")
mid = next(m["id"] for m in call("GET", f"/api/campaigns/{camp}/maps")["maps"] if m["name"] == "Steven Voss test room")
fresh_fight(eid, mid)
call("POST", f"/api/campaigns/{camp}/live-map", {"map_id": mid})
call("POST", f"/api/encounters/{eid}/start")
call("POST", f"/api/encounters/{eid}/set-turn", {"combatant_id": by["Steven Voss"]["id"]})


def toks():
    return {t["display"]: t for t in call("GET", f"/api/maps/{mid}")["tokens"]}


with sync_playwright() as p:
    b = engine.launch(p)
    pg = b.new_page(viewport={"width": 1400, "height": 950})
    pg.on("pageerror", lambda e: problems.append(f"JS error: {e}"))
    pg.goto(f"{DM}/combat/{eid}"); pg.wait_for_timeout(2000)

    def select(name):
        pg.locator("#init-list li.combatant").filter(has=pg.locator(".c-name > span:first-child", has_text=re.compile("^" + re.escape(name) + "$"))).first.locator(".c-name").click()
        pg.wait_for_timeout(400)

    def cast(spell, targets):
        select("Steven Voss")
        pg.locator("#detail .spell-row").filter(has=pg.locator(".sr-name b", has_text=spell)).first.get_by_role("button", name="Cast").click()
        pg.wait_for_selector("#detail .cast-picker")
        for t in targets:
            for _ in range(4):  # a live update (the API moving tokens) can redraw the picker under the tap
                chip = pg.locator("#detail .cast-chip").filter(has_text=t).first
                if chip.get_attribute("aria-pressed") == "true":
                    break
                chip.click(); pg.wait_for_timeout(600)
        if not pg.locator("#detail .cast-go").is_enabled():
            pg.screenshot(path=f"{SHOTS_DIR}/voss_stuck.png"); print("    STUCK:", pg.locator("#detail .cast-picker").inner_text()[:500].replace(chr(10), " | "))
        pg.locator("#detail .cast-go").click(timeout=5000)
        pg.wait_for_selector("#detail .cast-result", timeout=30000)
        text = pg.locator("#detail .cast-result").inner_text()
        print("   ", text.replace("\n", " | "))
        pg.wait_for_timeout(2500)
        if pg.locator("#dice-dock.is-open").count():
            pg.click("#dice-close")
        pg.locator("#detail .cast-picker").get_by_role("button", name="Done").click()
        return text

    select("Steven Voss")
    rows = pg.locator("#detail .spell-row").all_inner_texts()
    names = " ".join(rows)
    for n in ("Deploy Drones", "Fire Bolt", "Fireball", "Cone of Cold", "Cure Wounds"):
        check(n in names, f"Steven's spell list has {n}")
    check("relay drones" in names, "Deploy Drones says what relay drones do")
    pg.screenshot(path=f"{SHOTS_DIR}/voss_spells_{engine.NAME}.png")

    t = cast("Deploy Drones", [])
    st = call("GET", f"/api/encounters/{eid}")
    drones = [c for c in st["combatants"] if c["name"].startswith("Voss Drone")]
    check(len(drones) == 2 and all(d["kind"] == "enemy" and d["statblock"].get("relay") for d in drones), "two relay drones join on Steven's side")
    check("appear" in t, "the result says the drones appear")

    tk = toks()
    call("POST", f"/api/tokens/{tk['Test Hero']['id']}/move", {"x": 3, "y": 6, "free": True})
    call("POST", f"/api/tokens/{tk['Voss Drone 1']['id']}/move", {"x": 4, "y": 7, "free": True})
    call("POST", f"/api/tokens/{tk['Voss Drone 2']['id']}/move", {"x": 15, "y": 0, "free": True})
    call("POST", f"/api/encounters/{eid}/set-turn", {"combatant_id": by["Steven Voss"]["id"]})
    pg.wait_for_timeout(1500)
    t = cast("Fire Bolt", ["Test Hero"])
    check("Voss Drone 1 echoes it" in t or "Voss Drone 1:" in t, "the drone next to the Test Hero echoes Fire Bolt")
    check("Voss Drone 2" not in t, "the far drone doesn't")

    # the Test Hero casts next to a drone: Steven can cast it back once
    call("POST", f"/api/encounters/{eid}/set-turn", {"combatant_id": by["Test Hero"]["id"]})
    call("POST", f"/api/encounters/{eid}/cast", {"caster_id": by["Test Hero"]["id"], "targets": [drones[0]["id"]],
                                                 "spell": {"name": "Spark Shot", "effect": "damage", "level": 0, "dice": "1", "damage_type": "lightning"}})
    call("POST", f"/api/encounters/{eid}/set-turn", {"combatant_id": by["Steven Voss"]["id"]})
    pg.wait_for_timeout(2000)
    select("Steven Voss")
    check("Spark Shot (copied)" in " ".join(pg.locator("#detail .spell-row").all_inner_texts()), "Steven's list shows Spark Shot (copied)")
    pg.screenshot(path=f"{SHOTS_DIR}/voss_copied_{engine.NAME}.png")
    t = cast("Spark Shot (copied)", ["Test Hero"])
    check("Test Hero" in t, "he casts the copied spell back at the Test Hero")
    pg.wait_for_timeout(1500)
    select("Steven Voss")
    check("Spark Shot (copied)" not in " ".join(pg.locator("#detail .spell-row").all_inner_texts()), "and then it's used up")

    pg.goto(f"{DM}/map/{mid}"); pg.wait_for_timeout(3500)
    pg.screenshot(path=f"{SHOTS_DIR}/voss_map_{engine.NAME}.png")
    b.close()

check(not problems, "no page errors" + ("" if not problems else ": " + "; ".join(problems[:3])))
print(f"e2e_voss.py [{engine.NAME}]: {sum(1 for ok, _ in results if ok)} passed, {sum(1 for ok, _ in results if not ok)} failed")
